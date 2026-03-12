from conversations import router as convos_router
from skills import router as skills_router, parse_skill_md
from admin import router as admin_router
from auth import router as auth_router, get_current_user, get_user_dir
from tools import TOOL_DEFINITIONS, ALWAYS_ON_TOOLS, execute_tool
from tools.memory import get_memory_block
import os
import re
import json
import logging
import asyncio
import uuid
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("piailot")

app = FastAPI()
app.include_router(auth_router)
app.include_router(skills_router)
app.include_router(convos_router)
app.include_router(admin_router)
API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

_free_models_cache: list[dict] = []
_cache_lock = asyncio.Lock()
_last_fetch: float = 0
CACHE_TTL = 300


async def fetch_free_models() -> list[dict]:
    global _free_models_cache, _last_fetch
    now = asyncio.get_event_loop().time()

    async with _cache_lock:
        if _free_models_cache and (now - _last_fetch) < CACHE_TTL:
            return _free_models_cache

        log.info("Fetching models from OpenRouter...")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(OPENROUTER_MODELS_URL)
                resp.raise_for_status()
                data = resp.json().get("data", [])

                free = []
                for m in data:
                    mid = m["id"]
                    # Only include models with :free tag or the openrouter/free router
                    if ":free" not in mid and mid != "openrouter/free":
                        continue
                    free.append({
                        "id": mid,
                        "name": m.get("name", mid),
                        "context_length": m.get("context_length", 0),
                    })

                # Sort by context length (larger = more capable), but pin openrouter/free at top
                free.sort(key=lambda x: (x["id"] != "openrouter/free", -x.get("context_length", 0)))
                _free_models_cache = free
                _last_fetch = now
                log.info(f"Found {len(free)} free models")
        except Exception as e:
            log.error(f"Failed to fetch models: {e}")
        return _free_models_cache


def get_model_cache_info() -> dict:
    """Return model cache state for admin panel."""
    return {
        "models": _free_models_cache,
        "count": len(_free_models_cache),
        "last_fetch": _last_fetch,
    }


def clear_model_cache():
    """Clear the model cache so next request refetches."""
    global _free_models_cache, _last_fetch
    _free_models_cache = []
    _last_fetch = 0


@app.on_event("startup")
async def startup():
    await fetch_free_models()


@app.get("/api/models")
async def get_models():
    models = await fetch_free_models()
    return JSONResponse([{"id": m["id"], "name": m["name"]} for m in models])


@app.get("/api/tools")
async def list_available_tools():
    """Return available opt-in tools with descriptions for the skill editor."""
    from tools import TOOL_DEFINITIONS
    from skills import AVAILABLE_TOOLS
    result = []
    for name in AVAILABLE_TOOLS:
        defn = TOOL_DEFINITIONS.get(name)
        if defn:
            func = defn.get("function", {})
            result.append({
                "id": name,
                "desc": func.get("description", "")[:80],
            })
    return JSONResponse(result)


def _load_skill(username: str, skill_name: str) -> dict | None:
    """Load and parse a SKILL.md file for the given user and skill name."""
    skill_path = get_user_dir(username) / "skills" / skill_name / "SKILL.md"
    if not skill_path.exists():
        return None
    try:
        return parse_skill_md(skill_path.read_text())
    except Exception as e:
        log.error(f"Failed to load skill {skill_name}: {e}")
        return None


def _parse_xml_tool_calls(content: str) -> list[dict] | None:
    """Parse XML <tool_call> tags emitted by models that don't support function calling.

    Handles two formats:
    1. XML-style: <function=name><parameter=key>value</parameter></function>
    2. JSON-style: {"name": "...", "arguments": {...}}

    Returns a list in OpenAI tool_calls format, or None if parsing fails.
    """
    matches = re.findall(r"<tool_call>(.*?)</tool_call>", content, re.DOTALL)
    if not matches:
        return None
    calls = []
    for raw in matches:
        fn_match = re.search(r"<function=(\w+)>", raw)
        if fn_match:
            fn_name = fn_match.group(1)
            # Extract <parameter=key>value</parameter> pairs
            params = {}
            for pm in re.finditer(r"<parameter=(\w+)>(.*?)</parameter>", raw, re.DOTALL):
                params[pm.group(1)] = pm.group(2).strip()
            param_str = json.dumps(params)
        else:
            # Try JSON format
            try:
                parsed = json.loads(raw.strip())
                fn_name = parsed.get("name", "")
                param_str = json.dumps(parsed.get("arguments", {}))
            except (json.JSONDecodeError, TypeError):
                continue

        calls.append({
            "id": f"xml_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {"name": fn_name, "arguments": param_str},
        })
    return calls if calls else None


async def _call_openrouter(client, headers, model_id, messages, tools=None):
    """Make a single (non-streaming) call to OpenRouter. Returns parsed JSON or None."""
    payload = {"model": model_id, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    try:
        resp = await client.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120.0)
        if resp.status_code == 200:
            return resp.json()
        else:
            log.info(f"Failed {model_id}: {resp.status_code}")
            return None
    except Exception as e:
        log.error(f"Error calling {model_id}: {e}")
        return None


async def _call_openrouter_stream(client, headers, model_id, messages):
    """Make a streaming call to OpenRouter. Returns the response object or None."""
    payload = {"model": model_id, "messages": messages, "stream": True}
    r = await client.send(
        client.build_request("POST", OPENROUTER_URL, json=payload, headers=headers),
        stream=True,
    )
    if r.status_code == 200:
        return r
    else:
        await r.aread()
        await r.aclose()
        log.info(f"Failed {model_id}: {r.status_code}")
        return None


@app.post("/api/chat")
async def chat(request: Request):
    user = get_current_user(request)
    if user is None:
        return JSONResponse({"error": "not authenticated"}, status_code=401)

    body = await request.json()
    messages = body.get("messages", [])
    preferred = body.get("model", "")
    skill_name = body.get("skill")

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "PiAiLot",
    }

    # ── Resolve skill (system prompt + tools) ───────────────────────
    system_prompt = None
    skill_tool_names = []
    if skill_name:
        user_data = get_current_user(request)
        if user_data:
            skill_data = _load_skill(user_data["username"], skill_name)
            if skill_data:
                system_prompt = skill_data.get("system_prompt", "")
                skill_tool_names = skill_data.get("tools", [])
                log.info(f"Loaded skill '{skill_name}' with tools: {skill_tool_names}")

    # Inject user memory into system prompt
    username = user["username"]
    memory_block = get_memory_block(str(get_user_dir(username)))

    # Browser timezone from request
    browser_tz = body.get("timezone")

    # Build system prompt with memory
    system_parts = []
    if memory_block:
        system_parts.append(memory_block)
    if system_prompt:
        system_parts.append(system_prompt)
    full_system = "\n\n".join(system_parts) if system_parts else None

    if full_system:
        messages = [{"role": "system", "content": full_system}] + messages

    # Build tool definitions: always-on + skill-specific
    tool_names = list(ALWAYS_ON_TOOLS)
    for t in skill_tool_names:
        # Backwards compat: datetime -> user_time
        mapped = "user_time" if t == "datetime" else t
        if mapped not in tool_names:
            tool_names.append(mapped)

    tools_for_request = [TOOL_DEFINITIONS[t] for t in tool_names if t in TOOL_DEFINITIONS]

    # Build context for tool execution
    tool_context = {"username": username}
    if browser_tz:
        tool_context["timezone"] = browser_tz

    # ── Model fallback order ────────────────────────────────────────
    models = await fetch_free_models()
    model_ids = [m["id"] for m in models]

    if not model_ids:
        async def no_models():
            err = {"choices": [{"delta": {"content": "[no free models available]"}, "finish_reason": "stop"}]}
            yield f"data: {json.dumps(err)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(no_models(), media_type="text/event-stream")

    if preferred in model_ids:
        fallback_order = [preferred] + [m for m in model_ids if m != preferred]
    else:
        fallback_order = model_ids

    # ── Tool-use path (non-streaming with tool loop) ────────────────
    if tools_for_request:
        async def tool_stream():
            async with httpx.AsyncClient(timeout=120.0) as client:
                result_data = None
                used_model = preferred

                for model_id in fallback_order:
                    log.info(f"Trying (tool mode): {model_id}")
                    result_data = await _call_openrouter(
                        client, headers, model_id, messages, tools=tools_for_request
                    )
                    if result_data is not None:
                        used_model = model_id
                        log.info(f"Success: {model_id}")
                        break

                if result_data is None:
                    error_chunk = {"choices": [{"delta": {"content": "[all models rate-limited — try again in a minute]"}, "finish_reason": "stop"}]}
                    yield f"data: {json.dumps(error_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                if used_model != preferred:
                    name = next((m["name"] for m in models if m["id"] == used_model), used_model)
                    note = {"choices": [{"delta": {"content": f"[using {name}]\n\n"}, "finish_reason": None}]}
                    yield f"data: {json.dumps(note)}\n\n"

                # Tool loop — max 10 rounds
                loop_messages = list(messages)
                xml_tool_mode = False  # Track if model uses XML tool calls
                for round_num in range(10):
                    choice = result_data.get("choices", [{}])[0]
                    message = choice.get("message", {})
                    tool_calls = message.get("tool_calls")

                    # Some models emit XML <tool_call> tags instead of using the
                    # tool_calls response field. Parse those into standard format.
                    if not tool_calls:
                        content = message.get("content") or ""
                        if "<tool_call>" in content:
                            tool_calls = _parse_xml_tool_calls(content)
                            if tool_calls:
                                xml_tool_mode = True
                                cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL).strip()
                                message = {
                                    "role": "assistant",
                                    "content": cleaned or None,
                                    "tool_calls": tool_calls,
                                }

                    if not tool_calls:
                        # No more tool calls — emit the final text
                        content = message.get("content") or ""
                        if not content:
                            # Model returned no content — retry without tools to get text
                            log.info("Empty content after tool calls, retrying without tools for summary")
                            summary_data = await _call_openrouter(
                                client, headers, used_model, loop_messages
                            )
                            if summary_data:
                                content = summary_data.get("choices", [{}])[0].get("message", {}).get("content") or ""
                        if content:
                            chunk = {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}]}
                            yield f"data: {json.dumps(chunk)}\n\n"
                        else:
                            chunk = {"choices": [{"delta": {"content": "[no response from model]"}, "finish_reason": "stop"}]}
                            yield f"data: {json.dumps(chunk)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    # Append the assistant message
                    if xml_tool_mode:
                        # For XML tool models, append as plain assistant message
                        loop_messages.append({"role": "assistant", "content": message.get("content") or ""})
                    else:
                        loop_messages.append(message)

                    # Execute each tool call
                    tool_results_text = []
                    for tc in tool_calls:
                        fn_name = tc["function"]["name"]
                        try:
                            fn_args = json.loads(tc["function"]["arguments"])
                        except (json.JSONDecodeError, TypeError):
                            fn_args = {}
                        tool_result = await execute_tool(fn_name, fn_args, context=tool_context)
                        log.info(f"Tool {fn_name} result: {tool_result[:200]}")

                        # Emit widget events to frontend
                        try:
                            result_json = json.loads(tool_result)
                            if isinstance(result_json, dict) and "__piailot_widget__" in result_json:
                                yield f"data: {tool_result}\n\n"
                        except (json.JSONDecodeError, TypeError):
                            pass

                        if xml_tool_mode:
                            # Collect results for a single user message
                            tool_results_text.append(f"[Tool '{fn_name}' returned: {tool_result}]")
                        else:
                            loop_messages.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": tool_result,
                            })

                    if xml_tool_mode:
                        # Send tool results as a user message the model can understand
                        loop_messages.append({"role": "user", "content": "\n".join(tool_results_text)})

                    # Call the model again with tool results
                    result_data = await _call_openrouter(
                        client, headers, used_model, loop_messages,
                        tools=None if xml_tool_mode else tools_for_request,
                    )
                    if result_data is None:
                        error_chunk = {"choices": [{"delta": {"content": "[model error during tool loop]"}, "finish_reason": "stop"}]}
                        yield f"data: {json.dumps(error_chunk)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                # Exhausted tool rounds — do a final call without tools to get summary
                log.info("Tool loop exhausted, making final text-only call")
                final_data = await _call_openrouter(
                    client, headers, used_model, loop_messages
                )
                content = ""
                if final_data:
                    content = final_data.get("choices", [{}])[0].get("message", {}).get("content") or ""
                if not content:
                    content = "[tool loop limit reached — please try again]"
                chunk = {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}]}
                yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(tool_stream(), media_type="text/event-stream")

    # ── Standard streaming path (no tools) ──────────────────────────
    async def stream():
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = None
            used_model = preferred

            for model_id in fallback_order:
                log.info(f"Trying: {model_id}")
                resp = await _call_openrouter_stream(client, headers, model_id, messages)
                if resp is not None:
                    used_model = model_id
                    log.info(f"Success: {model_id}")
                    break

            if resp is None:
                error_chunk = {"choices": [{"delta": {"content": "[all models rate-limited — try again in a minute]"}, "finish_reason": "stop"}]}
                yield f"data: {json.dumps(error_chunk)}\n\n"
                yield "data: [DONE]\n\n"
                return

            if used_model != preferred:
                name = next((m["name"] for m in models if m["id"] == used_model), used_model)
                note = {"choices": [{"delta": {"content": f"[using {name}]\n\n"}, "finish_reason": None}]}
                yield f"data: {json.dumps(note)}\n\n"

            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    yield line + "\n\n"
            await resp.aclose()

    return StreamingResponse(stream(), media_type="text/event-stream")

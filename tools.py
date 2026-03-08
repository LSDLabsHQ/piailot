import re
import math
import html
import logging
from datetime import datetime, timezone
import httpx

log = logging.getLogger("piailot")

# ── OpenAI-compatible tool definitions ──────────────────────────────

TOOL_DEFINITIONS = {
    "web_search": {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web using DuckDuckGo. Returns up to 5 result snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    }
                },
                "required": ["query"],
            },
        },
    },
    "web_fetch": {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a URL and return its text content (HTML tags stripped).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch",
                    }
                },
                "required": ["url"],
            },
        },
    },
    "calculator": {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate a mathematical expression safely. Supports basic arithmetic, sqrt, sin, cos, tan, log, log10, pi, e, pow, abs, round, min, max.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The math expression to evaluate, e.g. sqrt(144) + 17",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    "datetime": {
        "type": "function",
        "function": {
            "name": "datetime",
            "description": "Get the current UTC date, time, and day of week.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
}

# ── Safe math builtins for calculator ───────────────────────────────

_SAFE_MATH = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "pi": math.pi,
    "e": math.e,
    "pow": pow,
}


# ── Tool execution ─────────────────────────────────────────────────

async def _tool_web_search(query: str) -> str:
    url = f"https://html.duckduckgo.com/html/?q={query}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; PiAiLot/1.0)"},
            )
            resp.raise_for_status()
            body = resp.text
            snippets = re.findall(
                r'class="result__snippet"[^>]*>(.*?)</(?:a|td|span)',
                body,
                re.DOTALL,
            )
            cleaned = []
            for s in snippets[:5]:
                text = re.sub(r"<[^>]+>", "", s)
                text = html.unescape(text).strip()
                if text:
                    cleaned.append(text)
            if not cleaned:
                return "No results found."
            return "\n\n".join(cleaned)
    except Exception as e:
        return f"Search error: {e}"


async def _tool_web_fetch(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; PiAiLot/1.0)"},
            )
            resp.raise_for_status()
            text = resp.text
            # Strip script and style tags and their contents
            text = re.sub(
                r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE
            )
            text = re.sub(
                r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE
            )
            # Strip all remaining HTML tags
            text = re.sub(r"<[^>]+>", " ", text)
            text = html.unescape(text)
            # Collapse whitespace
            text = re.sub(r"\s+", " ", text).strip()
            return text[:3000]
    except Exception as e:
        return f"Fetch error: {e}"


def _tool_calculator(expression: str) -> str:
    # Validate input: strip known function names, then only allow safe characters
    safe_check = re.sub(
        r"\b(abs|round|min|max|sqrt|sin|cos|tan|log10|log|pi|pow|e)\b", "", expression
    )
    if not re.match(r"^[0-9+\-*/().,%^ \t]*$", safe_check):
        return "Error: expression contains disallowed characters"
    try:
        result = eval(expression, {"__builtins__": {}}, _SAFE_MATH)
        return str(result)
    except Exception as e:
        return f"Calculation error: {e}"


def _tool_datetime() -> str:
    now = datetime.now(timezone.utc)
    return (
        f"Date: {now.strftime('%Y-%m-%d')}\n"
        f"Time: {now.strftime('%H:%M:%S')} UTC\n"
        f"Day: {now.strftime('%A')}"
    )


async def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool by name and return the result string."""
    log.info(f"Executing tool: {name} with args: {arguments}")
    try:
        if name == "web_search":
            return await _tool_web_search(arguments.get("query", ""))
        elif name == "web_fetch":
            return await _tool_web_fetch(arguments.get("url", ""))
        elif name == "calculator":
            return _tool_calculator(arguments.get("expression", ""))
        elif name == "datetime":
            return _tool_datetime()
        else:
            return f"Unknown tool: {name}"
    except Exception as e:
        log.error(f"Tool {name} failed: {e}")
        return f"Tool error: {e}"

# Hidden Toolkit Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 15 piailot-native tools inspired by Claude.ai's hidden toolkit — memory, context, data, and interactive widgets — across 4 phases.

**Architecture:** Split monolithic `tools.py` into a `tools/` package. Always-on tools (memory, context, discovery) inject into every conversation. Opt-in tools enabled per skill. Rich tool responses use `__piailot_widget__` JSON markers delivered via SSE events, rendered by the frontend.

**Tech Stack:** Python/FastAPI (backend), vanilla JS + Chart.js CDN + Leaflet CDN (frontend), Open-Meteo/Nominatim/TheSportsDB (free APIs)

**Spec:** `docs/superpowers/specs/2026-03-12-hidden-toolkit-design.md`

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `tools/__init__.py` | Tool registry, `TOOL_DEFINITIONS`, `ALWAYS_ON_TOOLS`, `execute_tool()` with context |
| `tools/memory.py` | `memory_edit`, `conversation_search`, `recent_chats` implementations |
| `tools/context.py` | `user_time`, `calculator` implementations |
| `tools/search.py` | `web_search`, `web_fetch`, `image_search` implementations |
| `tools/data.py` | `weather`, `places_search`, `sports_data` implementations |
| `tools/widgets.py` | `ask_user_input`, `message_compose`, `chart_display` implementations |
| `tools/discovery.py` | `tool_search` meta-tool |
| `tests/test_memory.py` | Tests for memory_edit |
| `tests/test_context.py` | Tests for user_time, calculator |
| `tests/test_conversation_search.py` | Tests for conversation_search |

### Modified files

| File | Changes |
|------|---------|
| `main.py` | Import from `tools/` package, pass context to `execute_tool`, always use tool-use path, inject memory into system prompt, emit widget SSE events, include browser timezone |
| `skills.py` | Update `AVAILABLE_TOOLS`, add `/api/tools` endpoint |
| `static/index.html` | Widget renderer dispatch, lazy CDN loading, widget CSS, timezone in chat requests, `ask_user_input` auto-send |
| `static/skills.html` | Fetch tools from `/api/tools` instead of hardcoded array |

### Removed files

| File | Reason |
|------|--------|
| `tools.py` | Replaced by `tools/` package |

---

## Chunk 1: Package Migration + Phase 1 (Always-On Tools)

### Task 1: Create tools/ package and migrate existing tools

**Files:**
- Create: `tools/__init__.py`
- Create: `tools/context.py`
- Create: `tools/search.py`

- [ ] **Step 1: Create tools/ directory and install test dependencies**

```bash
mkdir -p tools tests
pip install pytest
```

- [ ] **Step 2: Create tools/search.py with migrated web_search and web_fetch**

```python
import re
import html
import logging
import httpx

log = logging.getLogger("piailot")


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


async def _tool_web_fetch(url_str: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                url_str,
                headers={"User-Agent": "Mozilla/5.0 (compatible; PiAiLot/1.0)"},
            )
            resp.raise_for_status()
            text = resp.text
            text = re.sub(
                r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE
            )
            text = re.sub(
                r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE
            )
            text = re.sub(r"<[^>]+>", " ", text)
            text = html.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:3000]
    except Exception as e:
        return f"Fetch error: {e}"
```

- [ ] **Step 3: Create tools/context.py with calculator and user_time**

```python
import re
import math
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger("piailot")

_SAFE_MATH = {
    "abs": abs, "round": round, "min": min, "max": max,
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "log": math.log, "log10": math.log10, "pi": math.pi, "e": math.e, "pow": pow,
}


def _tool_calculator(expression: str) -> str:
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


def _tool_user_time(arguments: dict, context: dict = None) -> str:
    tz_name = arguments.get("timezone")
    if not tz_name and context:
        tz_name = context.get("timezone")

    try:
        if tz_name:
            tz = ZoneInfo(tz_name)
        else:
            tz = timezone.utc
            tz_name = "UTC"
    except Exception:
        tz = timezone.utc
        tz_name = "UTC"

    now = datetime.now(tz)
    return (
        f'{{"current_time": "{now.isoformat()}", '
        f'"timezone": "{tz_name}", '
        f'"day": "{now.strftime("%A")}"}}'
    )
```

- [ ] **Step 4: Create tools/__init__.py with registry and executor**

```python
import json
import logging
from tools.search import _tool_web_search, _tool_web_fetch
from tools.context import _tool_calculator, _tool_user_time

log = logging.getLogger("piailot")

# ── Tool definitions (OpenAI-compatible) ──

TOOL_DEFINITIONS = {
    "web_search": {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web using DuckDuckGo. Returns up to 5 result snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
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
                    "url": {"type": "string", "description": "The URL to fetch"}
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
                    "expression": {"type": "string", "description": "The math expression to evaluate, e.g. sqrt(144) + 17"}
                },
                "required": ["expression"],
            },
        },
    },
    "user_time": {
        "type": "function",
        "function": {
            "name": "user_time",
            "description": "Get the current date, time, and day of week. Optionally specify a timezone (e.g. 'America/New_York', 'Asia/Tokyo'). If omitted, uses the user's browser timezone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {"type": "string", "description": "IANA timezone name (optional)"}
                },
                "required": [],
            },
        },
    },
}

# Backwards compat: "datetime" aliases "user_time" so existing skills don't break
TOOL_DEFINITIONS["datetime"] = TOOL_DEFINITIONS["user_time"]

# ── Always-on tools (injected into every request) ──

ALWAYS_ON_TOOLS = ["user_time"]

# ── Tool executor ──

async def execute_tool(name: str, arguments: dict, context: dict = None) -> str:
    """Execute a tool by name and return the result string."""
    # Backwards compat: datetime -> user_time
    if name == "datetime":
        name = "user_time"

    log.info(f"Executing tool: {name} with args: {arguments}")
    try:
        if name == "web_search":
            return await _tool_web_search(arguments.get("query", ""))
        elif name == "web_fetch":
            return await _tool_web_fetch(arguments.get("url", ""))
        elif name == "calculator":
            return _tool_calculator(arguments.get("expression", ""))
        elif name == "user_time":
            return _tool_user_time(arguments, context)
        else:
            return f"Unknown tool: {name}"
    except Exception as e:
        log.error(f"Tool {name} failed: {e}")
        return f"Tool error: {e}"
```

- [ ] **Step 5: Update main.py to import from tools/ package**

In `main.py`, change line 5:
```python
# OLD:
from tools import TOOL_DEFINITIONS, execute_tool
# NEW (same import, works with package):
from tools import TOOL_DEFINITIONS, ALWAYS_ON_TOOLS, execute_tool
```

Update the `execute_tool` call at line 261 to pass context:
```python
# OLD:
tool_result = await execute_tool(fn_name, fn_args)
# NEW:
tool_result = await execute_tool(fn_name, fn_args, context={"username": user["username"]})
```

- [ ] **Step 6: Delete old tools.py**

```bash
rm tools.py
```

- [ ] **Step 7: Verify the app starts and existing tools work**

```bash
cd /Users/lewisleighton/p/piailot && python -c "from tools import TOOL_DEFINITIONS, ALWAYS_ON_TOOLS, execute_tool; print(f'Loaded {len(TOOL_DEFINITIONS)} tools, {len(ALWAYS_ON_TOOLS)} always-on')"
```

Expected: `Loaded 5 tools, 1 always-on` (5 because `datetime` is aliased to `user_time`)

- [ ] **Step 8: Commit**

```bash
git add tools/ && git rm tools.py && git add main.py
git commit -m "refactor: migrate tools.py to tools/ package with context support"
```

---

### Task 2: Add memory_edit tool

**Files:**
- Create: `tools/memory.py`
- Modify: `tools/__init__.py`
- Create: `tests/test_memory.py`

- [ ] **Step 1: Write failing test for memory_edit**

Create `tests/test_memory.py`:

```python
import json
import pytest
import tempfile
import os
from pathlib import Path


@pytest.fixture
def user_dir(tmp_path):
    """Create a temporary user directory structure."""
    user_path = tmp_path / "users" / "testuser"
    user_path.mkdir(parents=True)
    return user_path


@pytest.fixture
def memory_file(user_dir):
    return user_dir / "memory.json"


class TestMemoryEdit:
    def test_view_empty(self, user_dir):
        from tools.memory import _tool_memory_edit
        result = _tool_memory_edit(
            {"command": "view"},
            str(user_dir)
        )
        data = json.loads(result)
        assert data["facts"] == []
        assert data["count"] == 0

    def test_add_fact(self, user_dir, memory_file):
        from tools.memory import _tool_memory_edit
        result = _tool_memory_edit(
            {"command": "add", "content": "User is a Python developer"},
            str(user_dir)
        )
        assert "added" in result.lower()
        # Verify persisted
        facts = json.loads(memory_file.read_text())
        assert len(facts) == 1
        assert facts[0] == "User is a Python developer"

    def test_add_respects_limit(self, user_dir, memory_file):
        from tools.memory import _tool_memory_edit
        # Pre-fill with 50 facts
        memory_file.write_text(json.dumps([f"fact {i}" for i in range(50)]))
        result = _tool_memory_edit(
            {"command": "add", "content": "One more fact"},
            str(user_dir)
        )
        assert "limit" in result.lower() or "full" in result.lower()

    def test_add_respects_char_limit(self, user_dir):
        from tools.memory import _tool_memory_edit
        result = _tool_memory_edit(
            {"command": "add", "content": "x" * 301},
            str(user_dir)
        )
        assert "300" in result or "long" in result.lower()

    def test_remove_fact(self, user_dir, memory_file):
        from tools.memory import _tool_memory_edit
        memory_file.write_text(json.dumps(["fact A", "fact B", "fact C"]))
        result = _tool_memory_edit(
            {"command": "remove", "index": 1},
            str(user_dir)
        )
        assert "removed" in result.lower()
        facts = json.loads(memory_file.read_text())
        assert facts == ["fact A", "fact C"]

    def test_remove_invalid_index(self, user_dir, memory_file):
        from tools.memory import _tool_memory_edit
        memory_file.write_text(json.dumps(["fact A"]))
        result = _tool_memory_edit(
            {"command": "remove", "index": 5},
            str(user_dir)
        )
        assert "invalid" in result.lower() or "out of range" in result.lower()

    def test_replace_fact(self, user_dir, memory_file):
        from tools.memory import _tool_memory_edit
        memory_file.write_text(json.dumps(["old fact", "keep this"]))
        result = _tool_memory_edit(
            {"command": "replace", "index": 0, "replacement": "new fact"},
            str(user_dir)
        )
        assert "replaced" in result.lower()
        facts = json.loads(memory_file.read_text())
        assert facts == ["new fact", "keep this"]

    def test_invalid_command(self, user_dir):
        from tools.memory import _tool_memory_edit
        result = _tool_memory_edit(
            {"command": "delete"},
            str(user_dir)
        )
        assert "invalid" in result.lower() or "unknown" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/lewisleighton/p/piailot && python -m pytest tests/test_memory.py -v
```

Expected: FAIL — `ImportError: cannot import name '_tool_memory_edit' from 'tools.memory'`

- [ ] **Step 3: Implement memory_edit in tools/memory.py**

```python
import json
import logging
from pathlib import Path

log = logging.getLogger("piailot")

MAX_FACTS = 50
MAX_CHARS = 300


def _load_memory(user_dir: str) -> list[str]:
    path = Path(user_dir) / "memory.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, Exception):
        return []


def _save_memory(user_dir: str, facts: list[str]):
    path = Path(user_dir) / "memory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(facts, indent=2))


def get_memory_block(user_dir: str) -> str:
    """Build the memory injection block for system prompt. Capped at 2000 chars."""
    facts = _load_memory(user_dir)
    if not facts:
        return ""

    lines = []
    total = 0
    for i, fact in enumerate(facts):
        line = f"- {fact}"
        if total + len(line) + 1 > 2000:
            remaining = len(facts) - i
            lines.append(f"[... {remaining} more facts stored]")
            break
        lines.append(line)
        total += len(line) + 1

    return "[User Memory]\n" + "\n".join(lines)


def _tool_memory_edit(arguments: dict, user_dir: str) -> str:
    command = arguments.get("command", "")

    if command == "view":
        facts = _load_memory(user_dir)
        return json.dumps({"facts": facts, "count": len(facts), "limit": MAX_FACTS})

    elif command == "add":
        content = arguments.get("content", "").strip()
        if not content:
            return "Error: content is required for add command"
        if len(content) > MAX_CHARS:
            return f"Error: fact too long ({len(content)} chars). Maximum is {MAX_CHARS} characters."
        facts = _load_memory(user_dir)
        if len(facts) >= MAX_FACTS:
            return f"Error: memory is full ({MAX_FACTS}/{MAX_FACTS} facts). Remove a fact first."
        facts.append(content)
        _save_memory(user_dir, facts)
        return f"Fact added ({len(facts)}/{MAX_FACTS}): {content}"

    elif command == "remove":
        index = arguments.get("index")
        if index is None:
            return "Error: index is required for remove command"
        facts = _load_memory(user_dir)
        if not isinstance(index, int) or index < 0 or index >= len(facts):
            return f"Error: invalid index {index}. Valid range: 0-{len(facts) - 1}"
        removed = facts.pop(index)
        _save_memory(user_dir, facts)
        return f"Removed fact at index {index}: {removed}"

    elif command == "replace":
        index = arguments.get("index")
        replacement = arguments.get("replacement", "").strip()
        if index is None:
            return "Error: index is required for replace command"
        if not replacement:
            return "Error: replacement text is required"
        if len(replacement) > MAX_CHARS:
            return f"Error: replacement too long ({len(replacement)} chars). Maximum is {MAX_CHARS} characters."
        facts = _load_memory(user_dir)
        if not isinstance(index, int) or index < 0 or index >= len(facts):
            return f"Error: invalid index {index}. Valid range: 0-{len(facts) - 1}"
        old = facts[index]
        facts[index] = replacement
        _save_memory(user_dir, facts)
        return f"Replaced fact at index {index}: '{old}' -> '{replacement}'"

    else:
        return f"Error: unknown command '{command}'. Valid commands: view, add, remove, replace"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/lewisleighton/p/piailot && python -m pytest tests/test_memory.py -v
```

Expected: All 8 tests PASS

- [ ] **Step 5: Register memory_edit in tools/__init__.py**

Add to imports at top of `tools/__init__.py`:
```python
from tools.memory import _tool_memory_edit
```

Add to `TOOL_DEFINITIONS`:
```python
    "memory_edit": {
        "type": "function",
        "function": {
            "name": "memory_edit",
            "description": "Manage persistent memory about the user. Commands: 'view' (list all facts), 'add' (store a new fact), 'remove' (delete by index), 'replace' (update by index). Memory persists across conversations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "One of: view, add, remove, replace", "enum": ["view", "add", "remove", "replace"]},
                    "content": {"type": "string", "description": "Fact text to add (max 300 chars). Required for 'add'."},
                    "index": {"type": "integer", "description": "0-indexed position. Required for 'remove' and 'replace'."},
                    "replacement": {"type": "string", "description": "New text. Required for 'replace'."}
                },
                "required": ["command"],
            },
        },
    },
```

Add `"memory_edit"` to `ALWAYS_ON_TOOLS`.

Add to `execute_tool`:
```python
        elif name == "memory_edit":
            from auth import get_user_dir
            user_dir = str(get_user_dir(context["username"])) if context else ""
            return _tool_memory_edit(arguments, user_dir)
```

- [ ] **Step 6: Commit**

```bash
git add tools/memory.py tools/__init__.py tests/test_memory.py
git commit -m "feat: add memory_edit tool with persistent per-user fact storage"
```

---

### Task 3: Add conversation_search and recent_chats tools

**Files:**
- Modify: `tools/memory.py`
- Modify: `tools/__init__.py`
- Create: `tests/test_conversation_search.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_conversation_search.py`:

```python
import json
import pytest
from pathlib import Path


@pytest.fixture
def history_dir(tmp_path):
    """Create a history directory with sample conversations."""
    hist = tmp_path / "history"
    hist.mkdir()

    conv1 = {
        "id": "abc123",
        "title": "Python help",
        "skill": "coding",
        "model": "test-model",
        "messages": [
            {"role": "user", "content": "How do I use Python decorators?"},
            {"role": "assistant", "content": "Decorators are functions that modify other functions."},
        ],
        "created": "2026-03-10T10:00:00+00:00",
        "updated": "2026-03-10T10:05:00+00:00",
    }
    (hist / "abc123.json").write_text(json.dumps(conv1))

    conv2 = {
        "id": "def456",
        "title": "Weather chat",
        "skill": None,
        "model": "test-model",
        "messages": [
            {"role": "user", "content": "What's the weather like in London?"},
            {"role": "assistant", "content": "It's rainy in London today."},
        ],
        "created": "2026-03-11T14:00:00+00:00",
        "updated": "2026-03-11T14:10:00+00:00",
    }
    (hist / "def456.json").write_text(json.dumps(conv2))

    conv3 = {
        "id": "ghi789",
        "title": "FastAPI routing",
        "skill": "coding",
        "model": "test-model",
        "messages": [
            {"role": "user", "content": "How does FastAPI routing work with Python?"},
            {"role": "assistant", "content": "FastAPI uses decorators like @app.get to define routes."},
        ],
        "created": "2026-03-12T08:00:00+00:00",
        "updated": "2026-03-12T08:15:00+00:00",
    }
    (hist / "ghi789.json").write_text(json.dumps(conv3))

    return tmp_path  # Return parent (acts as user_dir)


class TestConversationSearch:
    def test_search_finds_matches(self, history_dir):
        from tools.memory import _tool_conversation_search
        result = json.loads(_tool_conversation_search(
            {"query": "Python"},
            str(history_dir)
        ))
        assert len(result["results"]) == 2  # conv1 and conv3

    def test_search_respects_max_results(self, history_dir):
        from tools.memory import _tool_conversation_search
        result = json.loads(_tool_conversation_search(
            {"query": "Python", "max_results": 1},
            str(history_dir)
        ))
        assert len(result["results"]) == 1

    def test_search_no_results(self, history_dir):
        from tools.memory import _tool_conversation_search
        result = json.loads(_tool_conversation_search(
            {"query": "JavaScript"},
            str(history_dir)
        ))
        assert len(result["results"]) == 0

    def test_search_empty_history(self, tmp_path):
        from tools.memory import _tool_conversation_search
        result = json.loads(_tool_conversation_search(
            {"query": "anything"},
            str(tmp_path)
        ))
        assert len(result["results"]) == 0


class TestRecentChats:
    def test_recent_default(self, history_dir):
        from tools.memory import _tool_recent_chats
        result = json.loads(_tool_recent_chats(
            {},
            str(history_dir)
        ))
        assert len(result["conversations"]) == 3
        # Default sort is newest first
        assert result["conversations"][0]["conversation_id"] == "ghi789"

    def test_recent_count(self, history_dir):
        from tools.memory import _tool_recent_chats
        result = json.loads(_tool_recent_chats(
            {"count": 2},
            str(history_dir)
        ))
        assert len(result["conversations"]) == 2

    def test_recent_oldest_first(self, history_dir):
        from tools.memory import _tool_recent_chats
        result = json.loads(_tool_recent_chats(
            {"sort": "oldest"},
            str(history_dir)
        ))
        assert result["conversations"][0]["conversation_id"] == "abc123"

    def test_recent_empty_history(self, tmp_path):
        from tools.memory import _tool_recent_chats
        result = json.loads(_tool_recent_chats(
            {},
            str(tmp_path)
        ))
        assert len(result["conversations"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/lewisleighton/p/piailot && python -m pytest tests/test_conversation_search.py -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement conversation_search and recent_chats in tools/memory.py**

Add to `tools/memory.py`:

```python
import time


def _tool_conversation_search(arguments: dict, user_dir: str) -> str:
    query = arguments.get("query", "").lower().strip()
    max_results = min(arguments.get("max_results", 5), 10)
    if not query:
        return json.dumps({"results": [], "error": "query is required"})

    history_dir = Path(user_dir) / "history"
    if not history_dir.exists():
        return json.dumps({"results": []})

    # Get conversation files sorted by modification time (newest first), limit 100
    files = sorted(history_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:100]

    results = []
    start_time = time.monotonic()

    for f in files:
        # 5-second timeout
        if time.monotonic() - start_time > 5.0:
            break
        try:
            convo = json.loads(f.read_text())
            snippets = []
            for msg in convo.get("messages", []):
                content = msg.get("content", "")
                if query in content.lower():
                    # Extract snippet around match
                    idx = content.lower().index(query)
                    start = max(0, idx - 40)
                    end = min(len(content), idx + len(query) + 40)
                    snippet = ("..." if start > 0 else "") + content[start:end] + ("..." if end < len(content) else "")
                    snippets.append(snippet)

            if snippets:
                results.append({
                    "conversation_id": convo.get("id", f.stem),
                    "title": convo.get("title", "Untitled"),
                    "timestamp": convo.get("updated", convo.get("created", "")),
                    "matching_snippets": snippets[:3],
                })
                if len(results) >= max_results:
                    break
        except (json.JSONDecodeError, Exception):
            continue

    return json.dumps({"results": results})


def _tool_recent_chats(arguments: dict, user_dir: str) -> str:
    count = min(arguments.get("count", 5), 20)
    sort_order = arguments.get("sort", "newest")
    before = arguments.get("before")
    after = arguments.get("after")

    history_dir = Path(user_dir) / "history"
    if not history_dir.exists():
        return json.dumps({"conversations": []})

    convos = []
    for f in history_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            updated = data.get("updated", data.get("created", ""))

            # Apply time filters
            if before and updated > before:
                continue
            if after and updated < after:
                continue

            convos.append({
                "conversation_id": data.get("id", f.stem),
                "title": data.get("title", "Untitled"),
                "created": data.get("created", ""),
                "updated": updated,
                "message_count": len(data.get("messages", [])),
                "skill": data.get("skill"),
            })
        except (json.JSONDecodeError, Exception):
            continue

    reverse = sort_order != "oldest"
    convos.sort(key=lambda c: c["updated"], reverse=reverse)

    return json.dumps({"conversations": convos[:count]})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/lewisleighton/p/piailot && python -m pytest tests/test_conversation_search.py -v
```

Expected: All 8 tests PASS

- [ ] **Step 5: Register in tools/__init__.py**

Add imports:
```python
from tools.memory import _tool_conversation_search, _tool_recent_chats
```

Add definitions to `TOOL_DEFINITIONS`:
```python
    "conversation_search": {
        "type": "function",
        "function": {
            "name": "conversation_search",
            "description": "Search the user's past conversations by keyword. Returns matching conversation titles and message snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords"},
                    "max_results": {"type": "integer", "description": "Maximum results (1-10, default 5)"}
                },
                "required": ["query"],
            },
        },
    },
    "recent_chats": {
        "type": "function",
        "function": {
            "name": "recent_chats",
            "description": "List the user's recent conversations. Returns titles, timestamps, and message counts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of conversations (1-20, default 5)"},
                    "sort": {"type": "string", "description": "'newest' (default) or 'oldest'", "enum": ["newest", "oldest"]},
                    "before": {"type": "string", "description": "ISO 8601 datetime — only conversations before this time"},
                    "after": {"type": "string", "description": "ISO 8601 datetime — only conversations after this time"}
                },
                "required": [],
            },
        },
    },
```

Add both to `ALWAYS_ON_TOOLS`:
```python
ALWAYS_ON_TOOLS = ["user_time", "memory_edit", "conversation_search", "recent_chats"]
```

Add to `execute_tool`:
```python
        elif name == "conversation_search":
            from auth import get_user_dir
            user_dir = str(get_user_dir(context["username"])) if context else ""
            return _tool_conversation_search(arguments, user_dir)
        elif name == "recent_chats":
            from auth import get_user_dir
            user_dir = str(get_user_dir(context["username"])) if context else ""
            return _tool_recent_chats(arguments, user_dir)
```

- [ ] **Step 6: Commit**

```bash
git add tools/memory.py tools/__init__.py tests/test_conversation_search.py
git commit -m "feat: add conversation_search and recent_chats tools"
```

---

### Task 4: Wire always-on tools into main.py

**Files:**
- Modify: `main.py`

This task changes `main.py` to:
1. Always include always-on tool definitions in requests
2. Inject user memory into system prompt
3. Pass browser timezone via context
4. Emit widget SSE events

- [ ] **Step 1: Update main.py imports**

At the top of `main.py`, update line 5:
```python
from tools import TOOL_DEFINITIONS, ALWAYS_ON_TOOLS, execute_tool
```

Add import for memory:
```python
from tools.memory import get_memory_block
```

- [ ] **Step 2: Update the chat endpoint to always include always-on tools**

Replace the tool resolution section in the `chat` function (around lines 161-178) with:

```python
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
```

- [ ] **Step 3: Update execute_tool calls to pass context**

In the tool loop (around line 261), update:
```python
tool_result = await execute_tool(fn_name, fn_args, context=tool_context)
```

- [ ] **Step 4: Update frontend to send timezone in chat requests**

In `static/index.html`, in the `send()` function (around line 562), update the body construction:

```javascript
      var body = { messages: messages, model: modelSelect.value };
      var sk = skillSelect.value;
      if (sk) body.skill = sk;
      // Send browser timezone
      try { body.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch(e) {}
```

- [ ] **Step 5: Add widget SSE event detection to frontend**

In `static/index.html`, in the SSE parsing loop (around line 584-604), update the JSON parsing to detect widget events:

```javascript
          try {
            var json = JSON.parse(line.slice(6));

            // Check for widget events
            if (json.__piailot_widget__) {
              var widgetDiv = document.createElement('div');
              widgetDiv.className = 'piailot-widget piailot-widget-' + json.__piailot_widget__;
              widgetDiv.dataset.widget = JSON.stringify(json);
              chatEl.insertBefore(widgetDiv, assistantDiv);
              // Widget rendering will be added in Phase 2/3
              continue;
            }

            var delta = '';
            if (json.choices && json.choices[0] && json.choices[0].delta && json.choices[0].delta.content) {
              delta = json.choices[0].delta.content;
            }
```

- [ ] **Step 6: Verify the app starts with always-on tools**

```bash
cd /Users/lewisleighton/p/piailot && python -c "
from tools import TOOL_DEFINITIONS, ALWAYS_ON_TOOLS
print(f'Tools: {len(TOOL_DEFINITIONS)}')
print(f'Always-on: {ALWAYS_ON_TOOLS}')
assert 'memory_edit' in ALWAYS_ON_TOOLS
assert 'conversation_search' in ALWAYS_ON_TOOLS
assert 'recent_chats' in ALWAYS_ON_TOOLS
assert 'user_time' in ALWAYS_ON_TOOLS
print('All checks passed')
"
```

- [ ] **Step 7: Commit**

```bash
git add main.py static/index.html
git commit -m "feat: wire always-on tools into every conversation with memory injection"
```

---

## Chunk 2: Phase 2 (Data Tools)

### Task 5: Add image_search tool

**Files:**
- Modify: `tools/search.py`
- Modify: `tools/__init__.py`

- [ ] **Step 1: Implement image_search in tools/search.py**

Add to `tools/search.py`:

```python
import json


async def _tool_image_search(query: str, max_results: int = 3) -> str:
    max_results = max(3, min(max_results, 5))
    url = "https://duckduckgo.com/"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # First get the vqd token
            resp = await client.get(
                url,
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible; PiAiLot/1.0)"},
            )
            # Extract vqd token from page
            vqd_match = re.search(r'vqd=["\']([^"\']+)', resp.text)
            if not vqd_match:
                # Fallback: try the API directly
                return json.dumps({"__piailot_widget__": "images", "data": {"query": query, "images": [], "error": "Could not get search token"}})

            vqd = vqd_match.group(1)

            # Fetch images
            img_resp = await client.get(
                "https://duckduckgo.com/i.js",
                params={"q": query, "vqd": vqd, "l": "us-en", "o": "json"},
                headers={"User-Agent": "Mozilla/5.0 (compatible; PiAiLot/1.0)"},
            )
            img_data = img_resp.json()
            results = []
            for item in img_data.get("results", [])[:max_results]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("image", ""),
                    "thumbnail_url": item.get("thumbnail", ""),
                    "source": item.get("source", ""),
                })

            widget = {"__piailot_widget__": "images", "data": {"query": query, "images": results}}
            return json.dumps(widget)
    except Exception as e:
        return json.dumps({"__piailot_widget__": "images", "data": {"query": query, "images": [], "error": str(e)}})
```

- [ ] **Step 2: Register in tools/__init__.py**

Add import:
```python
from tools.search import _tool_image_search
```

Add definition:
```python
    "image_search": {
        "type": "function",
        "function": {
            "name": "image_search",
            "description": "Search for images on the web. Returns image URLs with thumbnails.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Image search query (3-6 words work best)"},
                    "max_results": {"type": "integer", "description": "Number of results (3-5, default 3)"}
                },
                "required": ["query"],
            },
        },
    },
```

Add to `execute_tool`:
```python
        elif name == "image_search":
            return await _tool_image_search(arguments.get("query", ""), arguments.get("max_results", 3))
```

- [ ] **Step 3: Commit**

```bash
git add tools/search.py tools/__init__.py
git commit -m "feat: add image_search tool with DuckDuckGo backend"
```

---

### Task 6: Add weather tool

**Files:**
- Modify: `tools/data.py` (create)
- Modify: `tools/__init__.py`

- [ ] **Step 1: Create tools/data.py with weather implementation**

```python
import json
import logging
import httpx

log = logging.getLogger("piailot")

# WMO weather code descriptions
_WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Rime fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


async def _tool_weather(location: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # Check if location is coordinates
            lat, lon, location_name = None, None, location
            if "," in location:
                parts = location.split(",")
                try:
                    lat, lon = float(parts[0].strip()), float(parts[1].strip())
                    location_name = f"{lat}, {lon}"
                except ValueError:
                    pass

            # Geocode if needed
            if lat is None:
                geo_resp = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": location, "count": 1, "language": "en"},
                )
                geo_data = geo_resp.json()
                results = geo_data.get("results", [])
                if not results:
                    return json.dumps({"__piailot_widget__": "weather", "data": {"error": f"Location '{location}' not found"}})
                lat = results[0]["latitude"]
                lon = results[0]["longitude"]
                location_name = results[0].get("name", location)
                country = results[0].get("country", "")
                if country:
                    location_name = f"{location_name}, {country}"

            # Fetch weather
            wx_resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                    "forecast_days": 5,
                },
            )
            wx = wx_resp.json()

            current = wx.get("current", {})
            daily = wx.get("daily", {})

            weather_code = current.get("weather_code", 0)
            conditions = _WMO_CODES.get(weather_code, "Unknown")

            temp_c = current.get("temperature_2m", 0)
            temp_f = round(temp_c * 9 / 5 + 32, 1)

            forecast = []
            dates = daily.get("time", [])
            highs = daily.get("temperature_2m_max", [])
            lows = daily.get("temperature_2m_min", [])
            codes = daily.get("weather_code", [])
            precip = daily.get("precipitation_probability_max", [])

            for i in range(min(5, len(dates))):
                high_c = highs[i] if i < len(highs) else 0
                forecast.append({
                    "date": dates[i],
                    "high_c": high_c,
                    "high_f": round(high_c * 9 / 5 + 32, 1),
                    "low_c": lows[i] if i < len(lows) else 0,
                    "conditions": _WMO_CODES.get(codes[i] if i < len(codes) else 0, "Unknown"),
                    "precipitation_chance": precip[i] if i < len(precip) else 0,
                })

            widget = {
                "__piailot_widget__": "weather",
                "data": {
                    "location_name": location_name,
                    "current": {
                        "temp_c": temp_c,
                        "temp_f": temp_f,
                        "conditions": conditions,
                        "humidity": current.get("relative_humidity_2m", 0),
                        "wind_speed": current.get("wind_speed_10m", 0),
                    },
                    "forecast": forecast,
                },
            }
            return json.dumps(widget)
    except Exception as e:
        return json.dumps({"__piailot_widget__": "weather", "data": {"error": str(e)}})
```

- [ ] **Step 2: Register in tools/__init__.py**

Add import:
```python
from tools.data import _tool_weather
```

Add definition:
```python
    "weather": {
        "type": "function",
        "function": {
            "name": "weather",
            "description": "Get current weather and 5-day forecast for a location. Returns temperature, conditions, humidity, wind, and daily forecast.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name (e.g. 'London') or coordinates (e.g. '51.5,-0.1')"}
                },
                "required": ["location"],
            },
        },
    },
```

Add to `execute_tool`:
```python
        elif name == "weather":
            return await _tool_weather(arguments.get("location", ""))
```

- [ ] **Step 3: Commit**

```bash
git add tools/data.py tools/__init__.py
git commit -m "feat: add weather tool with Open-Meteo backend"
```

---

### Task 7: Add places_search tool

**Files:**
- Modify: `tools/data.py`
- Modify: `tools/__init__.py`

- [ ] **Step 1: Add places_search to tools/data.py**

```python
import os
import time

_last_nominatim_call = 0.0


async def _tool_places_search(query: str, latitude: float = None, longitude: float = None, max_results: int = 5) -> str:
    global _last_nominatim_call
    max_results = max(1, min(max_results, 10))

    # Check for Google Places API key
    places_key = os.getenv("PLACES_API_KEY")

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            if places_key:
                return await _places_google(client, query, latitude, longitude, max_results, places_key)
            else:
                return await _places_nominatim(client, query, latitude, longitude, max_results)
    except Exception as e:
        return json.dumps({"__piailot_widget__": "places", "data": {"query": query, "places": [], "error": str(e)}})


async def _places_nominatim(client, query, latitude, longitude, max_results):
    global _last_nominatim_call
    # Rate limit: 1 req/sec
    now = time.monotonic()
    wait = 1.0 - (now - _last_nominatim_call)
    if wait > 0:
        import asyncio
        await asyncio.sleep(wait)
    _last_nominatim_call = time.monotonic()

    params = {
        "q": query,
        "format": "json",
        "limit": max_results,
        "addressdetails": 1,
    }
    if latitude is not None and longitude is not None:
        params["viewbox"] = f"{longitude-0.1},{latitude+0.1},{longitude+0.1},{latitude-0.1}"
        params["bounded"] = 0

    resp = await client.get(
        "https://nominatim.openstreetmap.org/search",
        params=params,
        headers={"User-Agent": "PiAiLot/1.0 (self-hosted AI gateway)"},
    )
    data = resp.json()

    places = []
    for item in data[:max_results]:
        addr = item.get("address", {})
        address_parts = []
        for key in ["road", "house_number", "city", "town", "village", "state", "country"]:
            if key in addr:
                address_parts.append(addr[key])

        places.append({
            "name": item.get("display_name", "").split(",")[0],
            "address": ", ".join(address_parts) if address_parts else item.get("display_name", ""),
            "latitude": float(item.get("lat", 0)),
            "longitude": float(item.get("lon", 0)),
            "type": item.get("type", ""),
        })

    return json.dumps({"__piailot_widget__": "places", "data": {"query": query, "places": places}})


async def _places_google(client, query, latitude, longitude, max_results, api_key):
    params = {
        "query": query,
        "key": api_key,
    }
    if latitude is not None and longitude is not None:
        params["location"] = f"{latitude},{longitude}"
        params["radius"] = 5000

    resp = await client.get(
        "https://maps.googleapis.com/maps/api/place/textsearch/json",
        params=params,
    )
    data = resp.json()

    places = []
    for item in data.get("results", [])[:max_results]:
        loc = item.get("geometry", {}).get("location", {})
        places.append({
            "name": item.get("name", ""),
            "address": item.get("formatted_address", ""),
            "latitude": loc.get("lat", 0),
            "longitude": loc.get("lng", 0),
            "type": ", ".join(item.get("types", [])[:2]),
            "rating": item.get("rating"),
        })

    return json.dumps({"__piailot_widget__": "places", "data": {"query": query, "places": places}})
```

- [ ] **Step 2: Register in tools/__init__.py**

Add import:
```python
from tools.data import _tool_places_search
```

Add definition:
```python
    "places_search": {
        "type": "function",
        "function": {
            "name": "places_search",
            "description": "Search for places and locations. Returns place names, addresses, coordinates, and an interactive map.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (e.g. 'coffee shops near Camden')"},
                    "latitude": {"type": "number", "description": "Optional latitude for proximity bias"},
                    "longitude": {"type": "number", "description": "Optional longitude for proximity bias"},
                    "max_results": {"type": "integer", "description": "Number of results (1-10, default 5)"}
                },
                "required": ["query"],
            },
        },
    },
```

Add to `execute_tool`:
```python
        elif name == "places_search":
            return await _tool_places_search(
                arguments.get("query", ""),
                arguments.get("latitude"),
                arguments.get("longitude"),
                arguments.get("max_results", 5),
            )
```

- [ ] **Step 3: Commit**

```bash
git add tools/data.py tools/__init__.py
git commit -m "feat: add places_search tool with Nominatim/Google Places backend"
```

---

### Task 8: Add sports_data tool

**Files:**
- Modify: `tools/data.py`
- Modify: `tools/__init__.py`

- [ ] **Step 1: Add sports_data to tools/data.py**

```python
async def _tool_sports_data(data_type: str, league: str, team: str = None) -> str:
    sports_key = os.getenv("SPORTS_API_KEY", "1")  # TheSportsDB free key is "1"
    base = "https://www.thesportsdb.com/api/v1/json"

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            if data_type == "standings":
                # Lookup league ID first
                league_resp = await client.get(f"{base}/{sports_key}/search_all_leagues.php", params={"s": league})
                leagues = league_resp.json().get("countrys") or league_resp.json().get("leagues") or []
                if not leagues:
                    return json.dumps({"error": f"League '{league}' not found"})
                league_id = leagues[0].get("idLeague", "")
                season = "2025-2026"  # Current season

                resp = await client.get(f"{base}/{sports_key}/lookuptable.php", params={"l": league_id, "s": season})
                table = resp.json().get("table", [])
                if not table:
                    # Try single-year season format
                    resp = await client.get(f"{base}/{sports_key}/lookuptable.php", params={"l": league_id, "s": "2025"})
                    table = resp.json().get("table", [])

                standings = []
                for entry in table:
                    row = {
                        "rank": entry.get("intRank"),
                        "team": entry.get("strTeam"),
                        "played": entry.get("intPlayed"),
                        "wins": entry.get("intWin"),
                        "draws": entry.get("intDraw"),
                        "losses": entry.get("intLoss"),
                        "points": entry.get("intPoints"),
                    }
                    if team and team.lower() not in (row.get("team") or "").lower():
                        continue
                    standings.append(row)

                return json.dumps({"__piailot_widget__": "sports", "data": {"type": "standings", "league": league, "standings": standings}})

            elif data_type == "scores":
                # Lookup league ID first
                league_resp = await client.get(f"{base}/{sports_key}/search_all_leagues.php", params={"s": league})
                leagues = league_resp.json().get("countrys") or league_resp.json().get("leagues") or []

                if team:
                    # Search by team
                    resp = await client.get(f"{base}/{sports_key}/searchteams.php", params={"t": team})
                    teams = resp.json().get("teams", [])
                    if not teams:
                        return json.dumps({"__piailot_widget__": "sports", "data": {"error": f"Team '{team}' not found"}})
                    team_id = teams[0].get("idTeam", "")
                    resp = await client.get(f"{base}/{sports_key}/eventslast.php", params={"id": team_id})
                    events = resp.json().get("results", [])
                elif leagues:
                    league_id = leagues[0].get("idLeague", "")
                    resp = await client.get(f"{base}/{sports_key}/eventsseason.php", params={"id": league_id, "s": "2025-2026"})
                    events = resp.json().get("events", []) or []
                else:
                    return json.dumps({"__piailot_widget__": "sports", "data": {"error": f"League '{league}' not found"}})

                scores = []
                for ev in (events or [])[:10]:
                    scores.append({
                        "event": ev.get("strEvent", ""),
                        "date": ev.get("dateEvent", ""),
                        "home": ev.get("strHomeTeam", ""),
                        "away": ev.get("strAwayTeam", ""),
                        "home_score": ev.get("intHomeScore"),
                        "away_score": ev.get("intAwayScore"),
                    })
                return json.dumps({"__piailot_widget__": "sports", "data": {"type": "scores", "league": league, "scores": scores}})

            else:
                return json.dumps({"__piailot_widget__": "sports", "data": {"error": f"Unknown data_type '{data_type}'. Use: scores, standings"}})

    except Exception as e:
        return json.dumps({"__piailot_widget__": "sports", "data": {"error": f"Sports data error: {e}"}})
```

- [ ] **Step 2: Register in tools/__init__.py**

Add import:
```python
from tools.data import _tool_sports_data
```

Add definition:
```python
    "sports_data": {
        "type": "function",
        "function": {
            "name": "sports_data",
            "description": "Get live sports scores, league standings, and team stats. Supports multiple leagues and sports.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Data type: 'scores' or 'standings'", "enum": ["scores", "standings"]},
                    "league": {"type": "string", "description": "League name (e.g. 'English Premier League', 'NBA')"},
                    "team": {"type": "string", "description": "Optional team name filter"}
                },
                "required": ["type", "league"],
            },
        },
    },
```

Add to `execute_tool`:
```python
        elif name == "sports_data":
            return await _tool_sports_data(
                arguments.get("type", ""),
                arguments.get("league", ""),
                arguments.get("team"),
            )
```

- [ ] **Step 3: Commit**

```bash
git add tools/data.py tools/__init__.py
git commit -m "feat: add sports_data tool with TheSportsDB backend"
```

---

### Task 9: Add frontend widget renderers for Phase 2

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Add widget CSS**

Add before the closing `</style>` tag in `index.html` (before line 219):

```css
  /* ── Widgets ── */
  .piailot-widget {
    align-self: flex-start; max-width: 85%; margin: 4px 0;
    border: 1px solid var(--border); border-radius: 8px;
    background: var(--surface); overflow: hidden; font-size: 0.82em;
  }
  .widget-header {
    padding: 10px 14px; border-bottom: 1px solid var(--border);
    color: var(--amber); font-weight: 700; font-size: 0.9em;
  }
  .widget-body { padding: 12px 14px; }

  /* Image search */
  .image-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
    gap: 8px;
  }
  .image-grid a { display: block; }
  .image-grid img {
    width: 100%; height: 90px; object-fit: cover;
    border-radius: 4px; border: 1px solid var(--border);
    transition: border-color 0.2s;
  }
  .image-grid img:hover { border-color: var(--cyan); }
  .image-grid .img-title {
    font-size: 0.75em; color: var(--text-dim); margin-top: 4px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }

  /* Weather */
  .weather-current {
    display: flex; align-items: center; gap: 16px; margin-bottom: 12px;
  }
  .weather-temp { font-size: 2em; color: var(--green); font-weight: 700; }
  .weather-details { color: var(--text-dim); font-size: 0.9em; line-height: 1.6; }
  .weather-forecast {
    display: flex; gap: 8px; overflow-x: auto; padding: 4px 0;
  }
  .forecast-day {
    flex: 0 0 auto; text-align: center; padding: 8px 12px;
    border: 1px solid var(--border); border-radius: 6px;
    min-width: 80px;
  }
  .forecast-day .day-name { color: var(--text-dim); font-size: 0.8em; margin-bottom: 4px; }
  .forecast-day .day-temp { color: var(--green); font-weight: 700; }
  .forecast-day .day-cond { color: var(--text-dim); font-size: 0.75em; margin-top: 4px; }

  /* Places */
  .places-list { margin-bottom: 12px; }
  .place-item {
    padding: 8px 0; border-bottom: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: start;
  }
  .place-item:last-child { border-bottom: none; }
  .place-name { color: var(--cyan); font-weight: 700; }
  .place-address { color: var(--text-dim); font-size: 0.85em; margin-top: 2px; }
  .place-rating { color: var(--amber); white-space: nowrap; }
  .places-map { height: 250px; border-radius: 4px; margin-top: 8px; }

  /* Sports */
  .sports-table { width: 100%; border-collapse: collapse; }
  .sports-table th {
    text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border);
    color: var(--amber); font-size: 0.8em; text-transform: uppercase;
  }
  .sports-table td {
    padding: 6px 10px; border-bottom: 1px solid var(--border);
    color: var(--text); font-size: 0.85em;
  }
  .sports-table tr:last-child td { border-bottom: none; }
```

- [ ] **Step 2: Add widget renderer JavaScript**

Add before the closing `})();` (before line 642) in `index.html`:

```javascript
  // ── Widget Renderers ──

  var _leafletLoaded = false;
  var _leafletCallbacks = [];

  function loadLeaflet(cb) {
    if (_leafletLoaded) { cb(); return; }
    _leafletCallbacks.push(cb);
    if (_leafletCallbacks.length > 1) return; // Already loading

    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
    document.head.appendChild(link);

    var script = document.createElement('script');
    script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    script.onload = function() {
      _leafletLoaded = true;
      _leafletCallbacks.forEach(function(c) { c(); });
      _leafletCallbacks = [];
    };
    script.onerror = function() {
      _leafletCallbacks.forEach(function(c) { c(true); });
      _leafletCallbacks = [];
    };
    var timeout = setTimeout(function() {
      if (!_leafletLoaded) {
        script.onerror();
      }
    }, 10000);
    script.addEventListener('load', function() { clearTimeout(timeout); });
    document.head.appendChild(script);
  }

  function renderWidget(el) {
    var data;
    try { data = JSON.parse(el.dataset.widget); } catch(e) { return; }
    var type = data.__piailot_widget__;
    var d = data.data;

    if (type === 'images') renderImages(el, d);
    else if (type === 'weather') renderWeather(el, d);
    else if (type === 'places') renderPlaces(el, d);
    else if (type === 'sports') renderSports(el, d);
  }

  function renderImages(el, d) {
    if (d.error || !d.images || !d.images.length) {
      el.innerHTML = '<div class="widget-body" style="color:var(--text-dim)">No images found</div>';
      return;
    }
    var html = '<div class="widget-header">Images: ' + escText(d.query) + '</div><div class="widget-body"><div class="image-grid">';
    d.images.forEach(function(img) {
      html += '<a href="' + escAttr(img.url) + '" target="_blank" rel="noopener">' +
        '<img src="' + escAttr(img.thumbnail_url || img.url) + '" alt="' + escAttr(img.title) + '" loading="lazy">' +
        '<div class="img-title">' + escText(img.title) + '</div></a>';
    });
    html += '</div></div>';
    el.innerHTML = html;
  }

  function renderWeather(el, d) {
    if (d.error) {
      el.innerHTML = '<div class="widget-body" style="color:var(--red)">' + escText(d.error) + '</div>';
      return;
    }
    var c = d.current;
    var html = '<div class="widget-header">' + escText(d.location_name) + '</div><div class="widget-body">';
    html += '<div class="weather-current">';
    html += '<div class="weather-temp">' + c.temp_c + '°C</div>';
    html += '<div class="weather-details">' + escText(c.conditions) + '<br>Humidity: ' + c.humidity + '%<br>Wind: ' + c.wind_speed + ' km/h</div>';
    html += '</div>';

    if (d.forecast && d.forecast.length) {
      html += '<div class="weather-forecast">';
      d.forecast.forEach(function(day) {
        var dayName = new Date(day.date + 'T00:00:00').toLocaleDateString('en', {weekday: 'short'});
        html += '<div class="forecast-day"><div class="day-name">' + dayName + '</div>';
        html += '<div class="day-temp">' + day.high_c + '°</div>';
        html += '<div class="day-cond">' + escText(day.conditions) + '</div></div>';
      });
      html += '</div>';
    }
    html += '</div>';
    el.innerHTML = html;
  }

  function renderPlaces(el, d) {
    if (!d.places || !d.places.length) {
      el.innerHTML = '<div class="widget-body" style="color:var(--text-dim)">No places found</div>';
      return;
    }
    var html = '<div class="widget-header">Places: ' + escText(d.query) + '</div><div class="widget-body">';
    html += '<div class="places-list">';
    d.places.forEach(function(p) {
      html += '<div class="place-item"><div><div class="place-name">' + escText(p.name) + '</div>';
      html += '<div class="place-address">' + escText(p.address) + '</div></div>';
      if (p.rating) html += '<div class="place-rating">' + p.rating + ' ★</div>';
      html += '</div>';
    });
    html += '</div>';
    html += '<div id="map-' + Date.now() + '" class="places-map"></div>';
    html += '</div>';
    el.innerHTML = html;

    // Load Leaflet for map
    var mapEl = el.querySelector('.places-map');
    loadLeaflet(function(err) {
      if (err || !window.L) {
        // Fallback: show as links
        mapEl.style.display = 'none';
        return;
      }
      var map = L.map(mapEl).setView([d.places[0].latitude, d.places[0].longitude], 13);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap'
      }).addTo(map);
      d.places.forEach(function(p) {
        L.marker([p.latitude, p.longitude]).addTo(map).bindPopup('<b>' + escText(p.name) + '</b><br>' + escText(p.address));
      });
      // Fit bounds
      if (d.places.length > 1) {
        var bounds = d.places.map(function(p) { return [p.latitude, p.longitude]; });
        map.fitBounds(bounds, {padding: [20, 20]});
      }
    });
  }

  function renderSports(el, d) {
    if (d.error) {
      el.innerHTML = '<div class="widget-body" style="color:var(--red)">' + escText(d.error) + '</div>';
      return;
    }
    var html = '<div class="widget-header">' + escText(d.league || 'Sports') + ' ' + escText(d.type || '') + '</div><div class="widget-body">';

    if (d.standings) {
      html += '<table class="sports-table"><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>Pts</th></tr>';
      d.standings.forEach(function(s) {
        html += '<tr><td>' + (s.rank||'') + '</td><td>' + escText(s.team||'') + '</td><td>' + (s.played||'') + '</td><td>' + (s.wins||'') + '</td><td>' + (s.draws||'') + '</td><td>' + (s.losses||'') + '</td><td style="color:var(--green);font-weight:700">' + (s.points||'') + '</td></tr>';
      });
      html += '</table>';
    } else if (d.scores) {
      html += '<table class="sports-table"><tr><th>Date</th><th>Match</th><th>Score</th></tr>';
      d.scores.forEach(function(s) {
        html += '<tr><td>' + escText(s.date||'') + '</td><td>' + escText(s.home||'') + ' vs ' + escText(s.away||'') + '</td><td style="color:var(--green)">' + (s.home_score||'-') + ' - ' + (s.away_score||'-') + '</td></tr>';
      });
      html += '</table>';
    }
    html += '</div>';
    el.innerHTML = html;
  }

  // Helpers
  function escText(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
  function escAttr(s) { return (s || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
```

- [ ] **Step 3: Update the SSE widget detection to call renderers**

In the SSE parsing, update the widget detection block (added in Task 4) to render widgets:

```javascript
            // Check for widget events
            if (json.__piailot_widget__) {
              var widgetDiv = document.createElement('div');
              widgetDiv.className = 'piailot-widget piailot-widget-' + json.__piailot_widget__;
              widgetDiv.dataset.widget = JSON.stringify(json);
              chatEl.insertBefore(widgetDiv, assistantDiv);
              renderWidget(widgetDiv);
              continue;
            }
```

Also update `renderMessages()` to render widgets from saved messages. In the assistant message rendering block, after creating the message div, add widget detection for tool results embedded in the message content:

```javascript
      // Inside renderMessages(), after rendering each assistant message div:
      // Check if content contains widget JSON (from stored tool results)
      if (msg.role === 'assistant' && msg.content) {
        var widgetMatch = msg.content.match(/"__piailot_widget__"\s*:\s*"([^"]+)"/);
        if (widgetMatch) {
          try {
            var widgetData = JSON.parse(msg.content);
            if (widgetData.__piailot_widget__) {
              var wd = document.createElement('div');
              wd.className = 'piailot-widget piailot-widget-' + widgetData.__piailot_widget__;
              wd.dataset.widget = msg.content;
              chatEl.appendChild(wd);
              renderWidget(wd);
            }
          } catch(e) {}
        }
      }
```

- [ ] **Step 4: Emit widget SSE events from backend**

In `main.py`, in the tool loop, after executing a tool and before appending to `loop_messages`, check if the result contains a widget marker and emit it as an SSE event:

```python
                    tool_result = await execute_tool(fn_name, fn_args, context=tool_context)
                    log.info(f"Tool {fn_name} result: {tool_result[:200]}")

                    # Emit widget events to frontend
                    try:
                        result_json = json.loads(tool_result)
                        if isinstance(result_json, dict) and "__piailot_widget__" in result_json:
                            yield f"data: {tool_result}\n\n"
                    except (json.JSONDecodeError, TypeError):
                        pass

                    loop_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result,
                    })
```

- [ ] **Step 5: Commit**

```bash
git add static/index.html main.py
git commit -m "feat: add frontend widget renderers for images, weather, places, sports"
```

---

## Chunk 3: Phase 3 (Interactive Widgets) + Phase 4 (Polish)

### Task 10: Add ask_user_input tool + frontend

**Files:**
- Create: `tools/widgets.py`
- Modify: `tools/__init__.py`
- Modify: `static/index.html`

- [ ] **Step 1: Create tools/widgets.py with ask_user_input**

```python
import json
import logging

log = logging.getLogger("piailot")


def _tool_ask_user_input(arguments: dict) -> str:
    questions = arguments.get("questions", [])
    if not questions:
        return json.dumps({"error": "questions array is required"})
    if len(questions) > 3:
        questions = questions[:3]

    validated = []
    for q in questions:
        qtype = q.get("type", "single_select")
        if qtype not in ("single_select", "multi_select", "rank_priorities"):
            qtype = "single_select"
        options = q.get("options", [])[:6]
        if len(options) < 2:
            continue
        validated.append({
            "question": q.get("question", ""),
            "type": qtype,
            "options": options,
        })

    if not validated:
        return json.dumps({"error": "At least one valid question with 2+ options is required"})

    return json.dumps({"__piailot_widget__": "ask_input", "data": {"questions": validated}})
```

- [ ] **Step 2: Register in tools/__init__.py**

Add import, definition (name: `ask_user_input`, parameter: `questions` array), and executor case.

- [ ] **Step 3: Add frontend renderer in index.html**

Add to the widget renderers section:

```javascript
  function renderAskInput(el, d) {
    if (!d.questions || !d.questions.length) return;

    var currentQ = 0;
    var answers = [];

    function showQuestion(idx) {
      var q = d.questions[idx];
      var html = '<div class="widget-header">' + escText(q.question);
      if (d.questions.length > 1) html += ' <span style="color:var(--text-dim)">(' + (idx+1) + ' of ' + d.questions.length + ')</span>';
      html += '</div><div class="widget-body">';

      if (q.type === 'single_select') {
        q.options.forEach(function(opt, i) {
          html += '<button class="ask-option" data-idx="' + i + '" style="display:block;width:100%;text-align:left;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:10px 14px;margin-bottom:6px;border-radius:4px;cursor:pointer;font-family:inherit;font-size:0.9em;transition:all 0.15s">' + escText(opt) + '</button>';
        });
      } else if (q.type === 'multi_select') {
        q.options.forEach(function(opt, i) {
          html += '<label style="display:flex;align-items:center;gap:10px;padding:8px 14px;margin-bottom:4px;background:var(--bg);border:1px solid var(--border);border-radius:4px;cursor:pointer;font-size:0.9em;transition:all 0.15s">';
          html += '<input type="checkbox" data-idx="' + i + '" style="accent-color:var(--green)">';
          html += '<span>' + escText(opt) + '</span></label>';
        });
        html += '<div style="margin-top:10px;display:flex;gap:8px"><button class="ask-submit" style="background:var(--green-dim);color:var(--bg);border:none;padding:8px 16px;border-radius:4px;font-family:inherit;font-weight:700;cursor:pointer">Submit</button>';
        html += '<span class="ask-counter" style="color:var(--text-dim);font-size:0.8em;line-height:36px">0 selected</span></div>';
      } else if (q.type === 'rank_priorities') {
        html += '<div class="rank-list" style="list-style:none">';
        q.options.forEach(function(opt, i) {
          html += '<div class="rank-item" draggable="true" data-idx="' + i + '" style="display:flex;align-items:center;gap:10px;padding:10px 14px;margin-bottom:4px;background:var(--bg);border:1px solid var(--border);border-radius:4px;cursor:grab;font-size:0.9em">';
          html += '<span style="color:var(--text-dim);cursor:grab">⠿</span>';
          html += '<span class="rank-num" style="color:var(--amber);font-weight:700;min-width:20px">' + (i+1) + '.</span>';
          html += '<span>' + escText(opt) + '</span></div>';
        });
        html += '</div>';
        html += '<button class="ask-submit" style="margin-top:10px;background:var(--green-dim);color:var(--bg);border:none;padding:8px 16px;border-radius:4px;font-family:inherit;font-weight:700;cursor:pointer">Submit ranking</button>';
      }

      html += '<button class="ask-skip" style="margin-top:8px;background:none;border:none;color:var(--text-dim);cursor:pointer;font-family:inherit;font-size:0.8em;padding:4px 0">Skip</button>';
      html += '</div>';
      el.innerHTML = html;

      // Wire up events
      if (q.type === 'single_select') {
        el.querySelectorAll('.ask-option').forEach(function(btn) {
          btn.addEventListener('click', function() {
            answers.push({question: q.question, type: q.type, answer: q.options[parseInt(btn.dataset.idx)]});
            nextQuestion();
          });
          btn.addEventListener('mouseenter', function() { btn.style.borderColor = 'var(--green-dim)'; btn.style.color = 'var(--green)'; });
          btn.addEventListener('mouseleave', function() { btn.style.borderColor = 'var(--border)'; btn.style.color = 'var(--text)'; });
        });
      } else if (q.type === 'multi_select') {
        var counter = el.querySelector('.ask-counter');
        el.querySelectorAll('input[type=checkbox]').forEach(function(cb) {
          cb.addEventListener('change', function() {
            var count = el.querySelectorAll('input:checked').length;
            counter.textContent = count + ' selected';
          });
        });
        el.querySelector('.ask-submit').addEventListener('click', function() {
          var selected = [];
          el.querySelectorAll('input:checked').forEach(function(cb) {
            selected.push(q.options[parseInt(cb.dataset.idx)]);
          });
          answers.push({question: q.question, type: q.type, answer: selected});
          nextQuestion();
        });
      } else if (q.type === 'rank_priorities') {
        setupDragReorder(el.querySelector('.rank-list'));
        el.querySelector('.ask-submit').addEventListener('click', function() {
          var ranked = [];
          el.querySelectorAll('.rank-item').forEach(function(item) {
            ranked.push(q.options[parseInt(item.dataset.idx)]);
          });
          answers.push({question: q.question, type: q.type, ranked: ranked});
          nextQuestion();
        });
      }

      el.querySelector('.ask-skip').addEventListener('click', function() {
        answers.push({question: q.question, type: q.type, answer: 'skipped'});
        nextQuestion();
      });

      // Keyboard navigation
      var focusIdx = -1;
      var optionEls = el.querySelectorAll('.ask-option, label, .rank-item');
      el.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
          el.querySelector('.ask-skip').click();
          return;
        }
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          if (e.key === 'ArrowDown') focusIdx = Math.min(focusIdx + 1, optionEls.length - 1);
          else focusIdx = Math.max(focusIdx - 1, 0);
          optionEls[focusIdx].focus();
          optionEls[focusIdx].style.outline = '2px solid var(--green-dim)';
          optionEls.forEach(function(o, i) { if (i !== focusIdx) o.style.outline = ''; });
        }
        if (e.key === 'Enter') {
          e.preventDefault();
          if (q.type === 'single_select' && focusIdx >= 0) optionEls[focusIdx].click();
          else { var sub = el.querySelector('.ask-submit'); if (sub) sub.click(); }
        }
      });
      el.setAttribute('tabindex', '0');
      el.focus();
    }

    function nextQuestion() {
      currentQ++;
      if (currentQ < d.questions.length) {
        showQuestion(currentQ);
      } else {
        // Send answers as user message (per spec format)
        var parts = answers.map(function(a) {
          if (a.type === 'rank_priorities' && a.ranked) return '[User ranked: ' + a.ranked.map(function(r,i) { return (i+1) + '. ' + r; }).join(', ') + ']';
          if (a.type === 'multi_select' && Array.isArray(a.answer)) return '[User selected: ' + a.answer.join(', ') + ']';
          return '[User selected: ' + a.answer + ']';
        });
        el.innerHTML = '<div class="widget-body" style="color:var(--text-dim)">Responses submitted</div>';
        // Auto-send
        inputEl.value = parts.join(' ');
        send();
      }
    }

    function setupDragReorder(list) {
      var dragItem = null;
      list.querySelectorAll('.rank-item').forEach(function(item) {
        item.addEventListener('dragstart', function(e) { dragItem = item; item.style.opacity = '0.5'; });
        item.addEventListener('dragend', function() { dragItem.style.opacity = '1'; dragItem = null; updateNumbers(list); });
        item.addEventListener('dragover', function(e) { e.preventDefault(); });
        item.addEventListener('drop', function(e) {
          e.preventDefault();
          if (dragItem && dragItem !== item) {
            var items = Array.from(list.children);
            var dragIdx = items.indexOf(dragItem);
            var dropIdx = items.indexOf(item);
            if (dragIdx < dropIdx) list.insertBefore(dragItem, item.nextSibling);
            else list.insertBefore(dragItem, item);
          }
        });
      });
    }

    function updateNumbers(list) {
      list.querySelectorAll('.rank-num').forEach(function(num, i) { num.textContent = (i+1) + '.'; });
    }

    showQuestion(0);
  }
```

Add `ask_input` to the renderer dispatch:
```javascript
    else if (type === 'ask_input') renderAskInput(el, d);
```

- [ ] **Step 4: Commit**

```bash
git add tools/widgets.py tools/__init__.py static/index.html
git commit -m "feat: add ask_user_input tool with interactive choice widgets"
```

---

### Task 11: Add message_compose tool + frontend

**Files:**
- Modify: `tools/widgets.py`
- Modify: `tools/__init__.py`
- Modify: `static/index.html`

- [ ] **Step 1: Add message_compose to tools/widgets.py**

```python
def _tool_message_compose(arguments: dict) -> str:
    kind = arguments.get("kind", "other")
    if kind not in ("email", "text", "other"):
        kind = "other"
    summary_title = arguments.get("summary_title", "Message")
    variants = arguments.get("variants", [])

    if not variants:
        return json.dumps({"error": "variants array is required"})

    validated = []
    for v in variants[:3]:
        entry = {"label": v.get("label", "Draft"), "body": v.get("body", "")}
        if kind == "email":
            entry["subject"] = v.get("subject", "")
        validated.append(entry)

    return json.dumps({
        "__piailot_widget__": "message_compose",
        "data": {"kind": kind, "summary_title": summary_title, "variants": validated}
    })
```

- [ ] **Step 2: Register in tools/__init__.py**

- [ ] **Step 3: Add frontend renderer**

Add CSS for message compose:
```css
  /* Message compose */
  .compose-tabs { display: flex; border-bottom: 1px solid var(--border); }
  .compose-tab {
    padding: 8px 16px; cursor: pointer; color: var(--text-dim);
    border-bottom: 2px solid transparent; font-size: 0.85em;
    background: none; border-top: none; border-left: none; border-right: none;
    font-family: inherit; transition: all 0.2s;
  }
  .compose-tab:hover { color: var(--text); }
  .compose-tab.active { color: var(--cyan); border-bottom-color: var(--cyan); }
  .compose-subject {
    padding: 8px 14px; border-bottom: 1px solid var(--border);
    color: var(--text-dim); font-size: 0.8em;
  }
  .compose-body {
    padding: 14px; white-space: pre-wrap; line-height: 1.6;
    color: var(--text); font-size: 0.9em;
  }
  .compose-actions { padding: 10px 14px; display: flex; gap: 8px; border-top: 1px solid var(--border); }
  .compose-btn {
    background: var(--green-dim); color: var(--bg); border: none;
    padding: 6px 14px; border-radius: 4px; font-family: inherit;
    font-weight: 700; cursor: pointer; font-size: 0.8em;
  }
  .compose-btn:hover { background: var(--green); }
  .compose-btn-outline {
    background: none; color: var(--text-dim); border: 1px solid var(--border);
    padding: 6px 14px; border-radius: 4px; font-family: inherit;
    cursor: pointer; font-size: 0.8em;
  }
  .compose-btn-outline:hover { color: var(--text); border-color: var(--text-dim); }
```

Add JavaScript renderer:
```javascript
  function renderMessageCompose(el, d) {
    var currentVar = 0;
    function show(idx) {
      var v = d.variants[idx];
      var html = '<div class="widget-header">' + escText(d.summary_title) + '</div>';
      if (d.variants.length > 1) {
        html += '<div class="compose-tabs">';
        d.variants.forEach(function(vr, i) {
          html += '<button class="compose-tab' + (i === idx ? ' active' : '') + '" data-idx="' + i + '">' + escText(vr.label) + '</button>';
        });
        html += '</div>';
      }
      if (d.kind === 'email' && v.subject) {
        html += '<div class="compose-subject">Subject: ' + escText(v.subject) + '</div>';
      }
      html += '<div class="compose-body">' + escText(v.body) + '</div>';
      html += '<div class="compose-actions">';
      if (d.kind === 'email' && v.subject) {
        html += '<a class="compose-btn" href="mailto:?subject=' + encodeURIComponent(v.subject) + '&body=' + encodeURIComponent(v.body) + '" target="_blank">Open in email</a>';
      }
      html += '<button class="compose-btn-outline compose-copy">Copy</button>';
      html += '</div>';
      el.innerHTML = html;

      // Tab switching
      el.querySelectorAll('.compose-tab').forEach(function(tab) {
        tab.addEventListener('click', function() { show(parseInt(tab.dataset.idx)); });
      });

      // Copy
      el.querySelector('.compose-copy').addEventListener('click', function() {
        navigator.clipboard.writeText(v.body).then(function() {
          var copyBtn = el.querySelector('.compose-copy');
          if (copyBtn) copyBtn.textContent = 'Copied!';
          setTimeout(function() { var btn = el.querySelector('.compose-copy'); if (btn) btn.textContent = 'Copy'; }, 1500);
        });
      });
    }
    show(0);
  }
```

Add to renderer dispatch:
```javascript
    else if (type === 'message_compose') renderMessageCompose(el, d);
```

- [ ] **Step 4: Commit**

```bash
git add tools/widgets.py tools/__init__.py static/index.html
git commit -m "feat: add message_compose tool with variant tabs and copy/mailto"
```

---

### Task 12: Add chart_display tool + frontend

**Files:**
- Modify: `tools/widgets.py`
- Modify: `tools/__init__.py`
- Modify: `static/index.html`

- [ ] **Step 1: Add chart_display to tools/widgets.py**

```python
def _tool_chart_display(arguments: dict) -> str:
    series = arguments.get("series", [])
    style = arguments.get("style", "line")
    if style not in ("line", "bar", "scatter"):
        style = "line"
    title = arguments.get("title", "")
    x_labels = arguments.get("x_labels", [])
    y_label = arguments.get("y_label", "")

    if not series:
        return json.dumps({"error": "series array is required"})

    validated = []
    for s in series:
        validated.append({
            "name": s.get("name", f"Series {len(validated) + 1}"),
            "data": s.get("data", []),
        })

    return json.dumps({
        "__piailot_widget__": "chart",
        "data": {
            "series": validated,
            "style": style,
            "title": title,
            "x_labels": x_labels,
            "y_label": y_label,
        }
    })
```

- [ ] **Step 2: Register in tools/__init__.py**

- [ ] **Step 3: Add Chart.js lazy loading and renderer**

Add CSS:
```css
  /* Chart */
  .chart-container { padding: 14px; }
  .chart-container canvas { max-height: 300px; }
  .chart-fallback table { width: 100%; border-collapse: collapse; }
  .chart-fallback th, .chart-fallback td { padding: 4px 8px; border-bottom: 1px solid var(--border); text-align: right; font-size: 0.82em; }
  .chart-fallback th { text-align: left; color: var(--amber); }
```

Add JavaScript:
```javascript
  var _chartjsLoaded = false;
  var _chartjsCallbacks = [];

  function loadChartJS(cb) {
    if (_chartjsLoaded) { cb(); return; }
    _chartjsCallbacks.push(cb);
    if (_chartjsCallbacks.length > 1) return;

    var script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js';
    script.onload = function() {
      _chartjsLoaded = true;
      _chartjsCallbacks.forEach(function(c) { c(); });
      _chartjsCallbacks = [];
    };
    script.onerror = function() {
      _chartjsCallbacks.forEach(function(c) { c(true); });
      _chartjsCallbacks = [];
    };
    setTimeout(function() { if (!_chartjsLoaded) script.onerror(); }, 10000);
    document.head.appendChild(script);
  }

  function renderChart(el, d) {
    var html = '';
    if (d.title) html += '<div class="widget-header">' + escText(d.title) + '</div>';
    html += '<div class="chart-container"><canvas></canvas></div>';
    html += '<div class="chart-fallback" style="display:none"></div>';
    el.innerHTML = html;

    var canvas = el.querySelector('canvas');
    var fallback = el.querySelector('.chart-fallback');

    loadChartJS(function(err) {
      if (err || !window.Chart) {
        // Fallback: data table
        canvas.style.display = 'none';
        fallback.style.display = 'block';
        var tbl = '<table><tr><th></th>';
        d.series.forEach(function(s) { tbl += '<th>' + escText(s.name) + '</th>'; });
        tbl += '</tr>';
        var maxLen = Math.max.apply(null, d.series.map(function(s) { return s.data.length; }));
        for (var i = 0; i < maxLen; i++) {
          tbl += '<tr><td>' + (d.x_labels && d.x_labels[i] ? escText(d.x_labels[i]) : i) + '</td>';
          d.series.forEach(function(s) { tbl += '<td>' + (s.data[i] !== undefined ? s.data[i] : '') + '</td>'; });
          tbl += '</tr>';
        }
        tbl += '</table>';
        fallback.innerHTML = tbl;
        return;
      }

      // Resolve CSS variables — canvas doesn't support var() syntax
      var cs = getComputedStyle(document.documentElement);
      var textColor = cs.getPropertyValue('--text').trim();
      var textDimColor = cs.getPropertyValue('--text-dim').trim();
      var borderColor = cs.getPropertyValue('--border').trim();

      var colors = ['#00ff41', '#00d4ff', '#ffb000', '#ff3333', '#b99aff'];
      var datasets = d.series.map(function(s, i) {
        var color = colors[i % colors.length];
        var ds = { label: s.name, data: s.data, borderColor: color, backgroundColor: color + '33' };
        if (d.style === 'scatter') { ds.type = 'scatter'; ds.showLine = false; }
        if (d.style === 'bar') { ds.type = 'bar'; }
        return ds;
      });

      new Chart(canvas, {
        type: d.style === 'scatter' ? 'scatter' : d.style,
        data: {
          labels: d.x_labels.length ? d.x_labels : d.series[0].data.map(function(_, i) { return i; }),
          datasets: datasets
        },
        options: {
          responsive: true,
          plugins: { legend: { labels: { color: textColor } } },
          scales: {
            x: { ticks: { color: textDimColor }, grid: { color: borderColor } },
            y: {
              title: { display: !!d.y_label, text: d.y_label, color: textDimColor },
              ticks: { color: textDimColor }, grid: { color: borderColor }
            }
          }
        }
      });
    });
  }
```

Add to renderer dispatch:
```javascript
    else if (type === 'chart') renderChart(el, d);
```

- [ ] **Step 4: Commit**

```bash
git add tools/widgets.py tools/__init__.py static/index.html
git commit -m "feat: add chart_display tool with Chart.js rendering and table fallback"
```

---

### Task 13: Add tool_search meta-tool

**Files:**
- Create: `tools/discovery.py`
- Modify: `tools/__init__.py`

- [ ] **Step 1: Create tools/discovery.py**

```python
import json
import logging

log = logging.getLogger("piailot")


def _tool_search(query: str, definitions: dict) -> str:
    """Fuzzy search through available tool definitions."""
    query_lower = query.lower()
    query_words = query_lower.split()
    results = []

    for name, defn in definitions.items():
        func = defn.get("function", {})
        desc = func.get("description", "").lower()
        score = 0

        for word in query_words:
            if word in name.lower():
                score += 2
            if word in desc:
                score += 1

        if score > 0:
            params = func.get("parameters", {}).get("properties", {})
            param_summary = ", ".join(f"{k} ({v.get('type', '?')})" for k, v in params.items())
            results.append({
                "name": func.get("name", name),
                "description": func.get("description", ""),
                "parameters": param_summary or "none",
                "_score": score,
            })

    results.sort(key=lambda r: r["_score"], reverse=True)
    # Remove internal score
    for r in results:
        del r["_score"]

    return json.dumps({"tools": results[:10]})
```

- [ ] **Step 2: Register in tools/__init__.py**

Add import:
```python
from tools.discovery import _tool_search
```

Add definition:
```python
    "tool_search": {
        "type": "function",
        "function": {
            "name": "tool_search",
            "description": "Search for available tools by keyword. Use this when you're not sure which tool to use for a task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords to match against tool names and descriptions"}
                },
                "required": ["query"],
            },
        },
    },
```

Add to `ALWAYS_ON_TOOLS`:
```python
ALWAYS_ON_TOOLS = ["user_time", "memory_edit", "conversation_search", "recent_chats", "tool_search"]
```

Add to `execute_tool`:
```python
        elif name == "tool_search":
            return _tool_search(arguments.get("query", ""), TOOL_DEFINITIONS)
```

- [ ] **Step 3: Commit**

```bash
git add tools/discovery.py tools/__init__.py
git commit -m "feat: add tool_search meta-tool for AI self-discovery of capabilities"
```

---

### Task 14: Add /api/tools endpoint and update skills.html

**Files:**
- Modify: `main.py`
- Modify: `skills.py`
- Modify: `static/skills.html`

- [ ] **Step 1: Add /api/tools endpoint to skills.py**

Update the `AVAILABLE_TOOLS` list at the top of `skills.py`:
```python
AVAILABLE_TOOLS = [
    "web_search", "web_fetch", "calculator", "image_search",
    "weather", "places_search", "sports_data",
    "ask_user_input", "message_compose", "chart_display",
]
```

Add the endpoint in `main.py` (not on the skills router, to match spec path `/api/tools`):
```python
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
```

- [ ] **Step 2: Update skills.html to fetch tools from API**

Replace the hardcoded `TOOLS` array (lines 259-264 of `skills.html`) with:
```javascript
var TOOLS = [];

async function loadTools() {
  try {
    var res = await fetch('/api/tools');
    if (res.ok) TOOLS = await res.json();
  } catch(e) {
    // Fallback
    TOOLS = [
      { id: 'web_search', desc: 'Search the web' },
      { id: 'web_fetch', desc: 'Fetch a web page' },
      { id: 'calculator', desc: 'Evaluate math' },
    ];
  }
}
```

Update the init section (lines 586-589) to load tools before skills:
```javascript
(async function() {
  var ok = await checkAuth();
  if (ok) {
    await loadTools();
    loadSkills();
  }
})();
```

Also ensure `renderToolToggles` is called after TOOLS is populated (it already reads from `TOOLS`, so this works).

- [ ] **Step 3: Handle datetime backwards compat in skills.py**

In the `_validate_tools` function, add mapping. Note: `datetime` maps to `user_time` which is always-on, so just strip it from the list:
```python
def _validate_tools(tools: list[str]) -> tuple[str | None, list[str]]:
    """Return (error_message, cleaned_tools). Error is None if valid."""
    # Map deprecated names: datetime is now always-on as user_time, strip it
    cleaned = [t for t in tools if t != "datetime"]
    bad = [t for t in cleaned if t not in AVAILABLE_TOOLS]
    if bad:
        return f"invalid tools: {bad}. available: {AVAILABLE_TOOLS}", tools
    return None, cleaned
```

Update callers of `_validate_tools` to use the returned cleaned list:
```python
err, cleaned_tools = _validate_tools(tools)
if err:
    return JSONResponse({"error": err}, status_code=400)
# Use cleaned_tools instead of tools
```

- [ ] **Step 4: Commit**

```bash
git add main.py skills.py static/skills.html
git commit -m "feat: add /api/tools endpoint and dynamic tool loading in skills editor"
```

---

### Task 15: Final integration test and cleanup

**Files:**
- All files

- [ ] **Step 1: Run all tests**

```bash
cd /Users/lewisleighton/p/piailot && python -m pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 2: Verify the app imports cleanly**

```bash
cd /Users/lewisleighton/p/piailot && python -c "
from tools import TOOL_DEFINITIONS, ALWAYS_ON_TOOLS, execute_tool
print(f'Total tools: {len(TOOL_DEFINITIONS)}')
print(f'Always-on: {ALWAYS_ON_TOOLS}')
print(f'Tool names: {list(TOOL_DEFINITIONS.keys())}')
assert len(TOOL_DEFINITIONS) >= 14
assert len(ALWAYS_ON_TOOLS) == 5
print('All checks passed!')
"
```

- [ ] **Step 3: Verify old tools.py is removed**

```bash
test ! -f /Users/lewisleighton/p/piailot/tools.py && echo "OK: tools.py removed" || echo "FAIL: tools.py still exists"
```

- [ ] **Step 4: Final commit with any cleanup**

```bash
git add -A && git status
# Only commit if there are changes
git diff --cached --quiet || git commit -m "chore: final cleanup for hidden toolkit implementation"
```

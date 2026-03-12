import json
import logging
from tools.search import _tool_web_search, _tool_web_fetch
from tools.context import _tool_calculator, _tool_user_time
from tools.memory import _tool_memory_edit, _tool_conversation_search, _tool_recent_chats

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
}

# Backwards compat: "datetime" aliases "user_time" so existing skills don't break
TOOL_DEFINITIONS["datetime"] = TOOL_DEFINITIONS["user_time"]

# ── Always-on tools (injected into every request) ──

ALWAYS_ON_TOOLS = ["user_time", "memory_edit", "conversation_search", "recent_chats"]

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
        elif name == "memory_edit":
            from auth import get_user_dir
            user_dir = str(get_user_dir(context["username"])) if context else ""
            return _tool_memory_edit(arguments, user_dir)
        elif name == "conversation_search":
            from auth import get_user_dir
            user_dir = str(get_user_dir(context["username"])) if context else ""
            return _tool_conversation_search(arguments, user_dir)
        elif name == "recent_chats":
            from auth import get_user_dir
            user_dir = str(get_user_dir(context["username"])) if context else ""
            return _tool_recent_chats(arguments, user_dir)
        else:
            return f"Unknown tool: {name}"
    except Exception as e:
        log.error(f"Tool {name} failed: {e}")
        return f"Tool error: {e}"

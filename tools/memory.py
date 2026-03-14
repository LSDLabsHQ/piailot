import json
import logging
import time
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

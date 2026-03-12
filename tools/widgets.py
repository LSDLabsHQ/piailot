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

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

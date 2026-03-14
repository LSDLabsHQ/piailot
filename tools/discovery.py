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

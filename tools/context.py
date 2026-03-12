import json
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
    return json.dumps({
        "current_time": now.isoformat(),
        "timezone": tz_name,
        "day": now.strftime("%A"),
    })

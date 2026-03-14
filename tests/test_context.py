import json
import pytest
from tools.context import _tool_calculator, _tool_user_time


class TestCalculator:
    def test_basic_arithmetic(self):
        assert _tool_calculator("2 + 3") == "5"

    def test_math_functions(self):
        assert _tool_calculator("sqrt(144)") == "12.0"

    def test_disallowed_characters(self):
        result = _tool_calculator("__import__('os')")
        assert "disallowed" in result

    def test_division_by_zero(self):
        result = _tool_calculator("1/0")
        assert "error" in result.lower()


class TestUserTime:
    def test_utc_fallback(self):
        result = json.loads(_tool_user_time({}))
        assert result["timezone"] == "UTC"
        assert "current_time" in result
        assert "day" in result

    def test_explicit_timezone(self):
        result = json.loads(_tool_user_time({"timezone": "US/Eastern"}))
        assert result["timezone"] == "US/Eastern"

    def test_context_timezone(self):
        result = json.loads(_tool_user_time({}, context={"timezone": "Europe/London"}))
        assert result["timezone"] == "Europe/London"

    def test_explicit_overrides_context(self):
        result = json.loads(_tool_user_time(
            {"timezone": "Asia/Tokyo"},
            context={"timezone": "Europe/London"}
        ))
        assert result["timezone"] == "Asia/Tokyo"

    def test_invalid_timezone_falls_back_to_utc(self):
        result = json.loads(_tool_user_time({"timezone": "Not/A/Timezone"}))
        assert result["timezone"] == "UTC"

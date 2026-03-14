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

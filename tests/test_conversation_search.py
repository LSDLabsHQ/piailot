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

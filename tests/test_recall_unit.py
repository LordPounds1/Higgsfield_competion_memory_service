from __future__ import annotations

from typing import Any

from src.recall import RecallEngine, approx_tokens, intent_keys


class FakeDatabase:
    def __init__(self) -> None:
        self.memories = [
            memory("loc-1", "location.current", "Lives in Berlin; moved from NYC", 0.92),
            memory("job-1", "employment.current", "Works at Notion as product engineer", 0.9),
        ]

    def active_memories(self, user_id: str | None, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.memories

    def search_memories(self, query: str, user_id: str | None, session_id: str | None, limit: int = 25) -> list[dict[str, Any]]:
        return []

    def search_messages(self, query: str, user_id: str | None, session_id: str | None, limit: int = 10) -> list[dict[str, Any]]:
        return []

    def recent_messages(self, user_id: str | None, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        return []


def memory(memory_id: str, key: str, value: str, confidence: float) -> dict[str, Any]:
    return {
        "id": memory_id,
        "type": "fact",
        "key": key,
        "value": value,
        "confidence": confidence,
        "source_session": "unit-session",
        "source_turn": f"turn-{memory_id}",
        "created_at": "2025-03-15T10:30:00Z",
        "updated_at": "2025-03-15T10:30:00Z",
        "supersedes": None,
        "active": True,
    }


def test_employment_question_does_not_treat_where_as_location() -> None:
    assert intent_keys("Where does the user work now?") == ["employment.current"]


def test_location_question_maps_to_location_intent() -> None:
    assert "location.current" in intent_keys("Where does this user live?")


def test_recall_does_not_include_location_for_job_question() -> None:
    result = RecallEngine(FakeDatabase()).recall(
        query="Where does the user work now?",
        session_id="unit-session",
        user_id="unit-user",
        max_tokens=512,
    )

    assert "Notion" in result["context"]
    assert "Berlin" not in result["context"]


def test_tight_token_budget_returns_empty_instead_of_header_only() -> None:
    result = RecallEngine(FakeDatabase()).recall(
        query="Where does this user live?",
        session_id="unit-session",
        user_id="unit-user",
        max_tokens=1,
    )

    assert result == {"context": "", "citations": []}


def test_noise_query_does_not_return_active_memories() -> None:
    result = RecallEngine(FakeDatabase()).recall(
        query="What is this user's favorite basketball team?",
        session_id="unit-session",
        user_id="unit-user",
        max_tokens=512,
    )

    assert result == {"context": "", "citations": []}


def test_approx_token_counter_is_conservative() -> None:
    assert approx_tokens("Berlin") >= 1
    assert approx_tokens("a" * 80) >= 20

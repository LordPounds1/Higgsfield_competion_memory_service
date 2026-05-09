from __future__ import annotations

from pathlib import Path

from src.database import MemoryDatabase
from src.models import TurnRequest


def make_turn(session_id: str, user_id: str | None, text: str) -> TurnRequest:
    return TurnRequest(
        session_id=session_id,
        user_id=user_id,
        messages=[{"role": "user", "content": text}],
        timestamp="2025-03-15T10:30:00Z",
        metadata={},
    )


def make_memory(
    key: str,
    value: str,
    source_session: str,
    source_turn: str,
    user_id: str | None,
    memory_type: str = "fact",
) -> dict:
    return {
        "type": memory_type,
        "key": key,
        "value": value,
        "confidence": 0.9,
        "user_id": user_id,
        "source_session": source_session,
        "source_turn": source_turn,
    }


def test_mutable_fact_supersession_preserves_history(tmp_path: Path) -> None:
    database = MemoryDatabase(tmp_path / "memory.db")
    try:
        turn_1 = database.create_turn(make_turn("job-1", "user-1", "I work at Stripe."))
        database.add_memories([make_memory("employment.current", "Works at Stripe", "job-1", turn_1, "user-1")])
        turn_2 = database.create_turn(make_turn("job-2", "user-1", "I joined Notion."))
        database.add_memories([make_memory("employment.current", "Works at Notion", "job-2", turn_2, "user-1")])

        memories = database.get_user_memories("user-1")
        active = [memory for memory in memories if memory["active"]]
        inactive = [memory for memory in memories if not memory["active"]]

        assert [memory["value"] for memory in active] == ["Works at Notion"]
        assert [memory["value"] for memory in inactive] == ["Works at Stripe"]
        assert active[0]["supersedes"] == inactive[0]["id"]
    finally:
        database.close()


def test_stable_duplicate_memory_is_not_inserted_twice(tmp_path: Path) -> None:
    database = MemoryDatabase(tmp_path / "memory.db")
    try:
        turn_id = database.create_turn(make_turn("pet-1", "user-1", "I have a dog named Biscuit."))
        memory = make_memory("pet.biscuit", "Has a dog named Biscuit", "pet-1", turn_id, "user-1")

        assert len(database.add_memories([memory])) == 1
        assert database.add_memories([memory]) == []
        assert len(database.get_user_memories("user-1")) == 1
    finally:
        database.close()


def test_anonymous_sessions_do_not_supersede_each_other(tmp_path: Path) -> None:
    database = MemoryDatabase(tmp_path / "memory.db")
    try:
        turn_1 = database.create_turn(make_turn("anon-1", None, "I live in Berlin."))
        database.add_memories([make_memory("location.current", "Lives in Berlin", "anon-1", turn_1, None)])
        turn_2 = database.create_turn(make_turn("anon-2", None, "I live in Lisbon."))
        database.add_memories([make_memory("location.current", "Lives in Lisbon", "anon-2", turn_2, None)])

        anon_1 = database.active_memories(None, "anon-1")
        anon_2 = database.active_memories(None, "anon-2")

        assert [memory["value"] for memory in anon_1] == ["Lives in Berlin"]
        assert [memory["value"] for memory in anon_2] == ["Lives in Lisbon"]
    finally:
        database.close()


def test_same_session_id_does_not_bleed_between_users(tmp_path: Path) -> None:
    database = MemoryDatabase(tmp_path / "memory.db")
    try:
        turn_1 = database.create_turn(make_turn("shared-session", "user-a", "I live in Berlin."))
        database.add_memories([make_memory("location.current", "Lives in Berlin", "shared-session", turn_1, "user-a")])
        turn_2 = database.create_turn(make_turn("shared-session", "user-b", "I live in Seattle."))
        database.add_memories([make_memory("location.current", "Lives in Seattle", "shared-session", turn_2, "user-b")])

        user_a = database.active_memories("user-a", "shared-session")
        user_b = database.active_memories("user-b", "shared-session")

        assert [memory["value"] for memory in user_a] == ["Lives in Berlin"]
        assert [memory["value"] for memory in user_b] == ["Lives in Seattle"]
    finally:
        database.close()

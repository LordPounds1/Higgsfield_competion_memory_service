from __future__ import annotations

from src.extraction import extract_memories
from src.models import TurnRequest


def make_turn(text: str, session_id: str = "unit-session", user_id: str | None = "unit-user") -> TurnRequest:
    return TurnRequest(
        session_id=session_id,
        user_id=user_id,
        messages=[{"role": "user", "content": text}],
        timestamp="2025-03-15T10:30:00Z",
        metadata={},
    )


def by_key(memories: list[dict], key: str) -> list[dict]:
    return [memory for memory in memories if memory["key"] == key]


def test_extracts_structured_location_with_origin() -> None:
    memories = extract_memories(make_turn("I just moved to Berlin from NYC last month."), "turn-1")

    location = by_key(memories, "location.current")
    assert len(location) == 1
    assert location[0]["type"] == "fact"
    assert location[0]["value"] == "Lives in Berlin; moved from NYC"
    assert location[0]["confidence"] >= 0.9
    assert location[0]["source_turn"] == "turn-1"


def test_extracts_employment_pet_allergy_and_answer_style() -> None:
    text = (
        "I joined Notion as a product engineer. "
        "I have a dog named Biscuit. "
        "I am vegetarian and allergic to shellfish. "
        "Please keep answers concise and direct."
    )
    memories = extract_memories(make_turn(text), "turn-2")
    values_by_key = {memory["key"]: memory["value"] for memory in memories}

    assert values_by_key["employment.current"] == "Works at Notion as product engineer"
    assert values_by_key["pet.biscuit"] == "Has a dog named Biscuit"
    assert values_by_key["diet.vegetarian"] == "Is vegetarian"
    assert values_by_key["allergy.shellfish"] == "Allergic to shellfish"
    assert values_by_key["preference.answer_style"] == "Prefers answers concise and direct"


def test_extracts_implicit_pet_from_walking_phrase() -> None:
    memories = extract_memories(make_turn("I was walking Biscuit this morning."), "turn-3")

    pet = by_key(memories, "pet.biscuit")
    assert len(pet) == 1
    assert pet[0]["value"] == "Has a pet named Biscuit"


def test_extracts_current_typescript_opinion() -> None:
    memories = extract_memories(
        make_turn("TypeScript is fine for big projects but I would use Python for scripts."),
        "turn-4",
    )

    opinion = by_key(memories, "opinion.typescript")
    assert len(opinion) == 1
    assert "big projects" in opinion[0]["value"]

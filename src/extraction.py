from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from src.models import TurnRequest


@dataclass
class ExtractedMemory:
    type: str
    key: str
    value: str
    confidence: float
    user_id: str | None
    source_session: str
    source_turn: str
    metadata: dict[str, Any] = field(default_factory=dict)


def extract_memories(request: TurnRequest, turn_id: str) -> list[dict[str, Any]]:
    text = "\n".join(message.content for message in request.messages if message.role == "user")
    memories: list[ExtractedMemory] = []

    def emit(memory_type: str, key: str, value: str, confidence: float, evidence: str) -> None:
        value = clean_value(value)
        key = key.strip().lower()
        if not key or not value:
            return
        memories.append(
            ExtractedMemory(
                type=memory_type,
                key=key,
                value=value,
                confidence=confidence,
                user_id=request.user_id,
                source_session=request.session_id,
                source_turn=turn_id,
                metadata={"extractor": "rules-v1", "evidence": evidence[:500]},
            )
        )

    for sentence in sentences(text):
        lower = sentence.lower()

        moved = re.search(
            r"\b(?:i\s+)?(?:just\s+|recently\s+)?(?:moved|relocated) to (?P<to>.+?)(?: from (?P<from>.+?))?(?: last month| last year| recently| this month|$)",
            sentence,
            re.IGNORECASE,
        )
        if moved:
            destination = clean_entity(moved.group("to"))
            origin = clean_entity(moved.group("from") or "")
            if destination and origin:
                emit("fact", "location.current", f"Lives in {destination}; moved from {origin}", 0.92, sentence)
            elif destination:
                emit("fact", "location.current", f"Lives in {destination}", 0.86, sentence)

        location = re.search(
            r"\b(?:i\s+(?:now\s+)?live in|i'm\s+(?:now\s+)?living in|i am\s+(?:now\s+)?living in|i'm based in|i am based in|currently based in)\s+(?P<place>.+)$",
            sentence,
            re.IGNORECASE,
        )
        if location:
            place = clean_entity(location.group("place"))
            if place:
                emit("fact", "location.current", f"Lives in {place}", 0.84, sentence)

        employment = re.search(
            r"\b(?:i\s+)?(?:currently\s+)?work (?:at|for)\s+(?P<company>.+?)(?:\s+as\s+(?:a|an)?\s*(?P<role>.+))?$",
            sentence,
            re.IGNORECASE,
        )
        joined = re.search(
            r"\b(?:i\s+)?(?:just\s+|recently\s+)?(?:joined|started at|started with|started a new role at|now work at|am now at|i'm now at)\s+(?P<company>.+?)(?:\s+as\s+(?:a|an)?\s*(?P<role>.+))?$",
            sentence,
            re.IGNORECASE,
        )
        transition = re.search(
            r"\b(?:i\s+)?(?:left|am no longer at|no longer work at|stopped working at)\s+.+?\s+(?:and\s+)?(?:joined|started at|now work at|am now at|i'm now at)\s+(?P<company>.+?)(?:\s+as\s+(?:a|an)?\s*(?P<role>.+))?$",
            sentence,
            re.IGNORECASE,
        )
        job_match = transition or joined or employment
        if job_match:
            company = clean_entity(job_match.group("company"))
            role = clean_value(job_match.group("role") or "")
            if company:
                value = f"Works at {company}" + (f" as {role}" if role else "")
                emit("fact", "employment.current", value, 0.9, sentence)

        pet = re.search(
            r"\b(?:i have|we have|my)\s+(?:a|an)?\s*(?P<animal>dog|cat|pet)\s+(?:is\s+)?(?:named|called)?\s*(?P<name>[A-Z][A-Za-z0-9_-]{1,40})\b",
            sentence,
            re.IGNORECASE,
        )
        if pet:
            animal = pet.group("animal").lower()
            name = pet.group("name")
            emit("fact", f"pet.{slug(name)}", f"Has a {animal} named {name}", 0.9, sentence)

        walking = re.search(r"\bwalking\s+(?P<name>[A-Z][A-Za-z0-9_-]{1,40})\b", sentence, re.IGNORECASE)
        if walking:
            name = walking.group("name")
            emit("fact", f"pet.{slug(name)}", f"Has a pet named {name}", 0.72, sentence)

        if "vegetarian" in lower:
            emit("preference", "diet.vegetarian", "Is vegetarian", 0.86, sentence)
        if "vegan" in lower:
            emit("preference", "diet.vegan", "Is vegan", 0.86, sentence)

        allergy = re.search(r"\ballergic to\s+(?P<item>[^.;,]+)", sentence, re.IGNORECASE)
        if allergy:
            item = clean_entity(allergy.group("item"))
            if item:
                emit("fact", f"allergy.{slug(item)}", f"Allergic to {item}", 0.9, sentence)
        allergy_noun = re.search(r"\b(?:i have|with)\s+(?:a\s+)?(?P<item>[A-Za-z][A-Za-z -]{1,60})\s+allergy\b", sentence, re.IGNORECASE)
        if allergy_noun:
            item = clean_entity(allergy_noun.group("item"))
            if item:
                emit("fact", f"allergy.{slug(item)}", f"Allergic to {item}", 0.82, sentence)

        prefer = re.search(r"\b(?:i prefer|please keep|keep)\s+(?P<pref>[^.;]+)", sentence, re.IGNORECASE)
        if prefer:
            pref = clean_value(prefer.group("pref"))
            if pref:
                key = "preference.answer_style" if "answer" in lower or "concise" in lower else f"preference.{slug(pref)[:40]}"
                emit("preference", key, f"Prefers {pref}", 0.78, sentence)
        likes_answer_style = re.search(r"\bi like\s+(?P<pref>concise|direct|short|brief)(?:\s+answers?)?\b", sentence, re.IGNORECASE)
        if likes_answer_style:
            pref = clean_value(likes_answer_style.group("pref"))
            emit("preference", "preference.answer_style", f"Prefers {pref} answers", 0.72, sentence)

        if "typescript" in lower and any(marker in lower for marker in ["i love", "i hate", "fine for", "annoying"]):
            emit("opinion", "opinion.typescript", clean_value(sentence), 0.74, sentence)

    return [asdict(memory) for memory in dedupe(memories)]


def dedupe(memories: list[ExtractedMemory]) -> list[ExtractedMemory]:
    seen: dict[str, ExtractedMemory] = {}
    for memory in memories:
        identity = f"{memory.type}:{memory.key}:{slug(memory.value)}"
        current = seen.get(identity)
        if current is None or memory.confidence > current.confidence:
            seen[identity] = memory
    return list(seen.values())


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [part.strip(" \t\r\n.!?") for part in parts if part.strip()]


def clean_entity(raw: str) -> str:
    raw = raw or ""
    raw = re.split(
        r"\b(?:last month|last year|this month|recently|right now|now|so far|because|while|and loving|and)\b",
        raw,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return clean_value(raw)


def clean_value(raw: str) -> str:
    return re.sub(r"\s+", " ", raw or "").strip(" \t\r\n,;:.!?\"'")[:500]


def slug(raw: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", raw.lower())
    return "-".join(tokens) or "unknown"

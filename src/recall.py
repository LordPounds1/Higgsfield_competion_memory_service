from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.database import MemoryDatabase

TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


@dataclass
class ScoredItem:
    kind: str
    payload: dict[str, Any]
    score: float


class RecallEngine:
    def __init__(self, database: MemoryDatabase) -> None:
        self.database = database

    def recall(self, query: str, session_id: str, user_id: str | None, max_tokens: int) -> dict[str, Any]:
        memories = self.rank_memories(query, session_id, user_id)
        messages = self.rank_messages(query, session_id, user_id, include_recent=bool(memories))
        if not memories and not messages:
            return {"context": "", "citations": []}
        return self.assemble(memories, messages, max_tokens)

    def search(self, query: str, session_id: str | None, user_id: str | None, limit: int) -> dict[str, Any]:
        items: list[ScoredItem] = []
        for memory in self.database.search_memories(query, user_id, session_id, limit=limit):
            items.append(ScoredItem("memory", memory, float(memory.get("score", 1.0)) + 0.5))
        for message in self.database.search_messages(query, user_id, session_id, limit=limit):
            items.append(ScoredItem("message", message, float(message.get("score", 1.0))))
        items.sort(key=lambda item: item.score, reverse=True)
        return {"results": [self.search_result(item) for item in items[:limit]]}

    def rank_memories(self, query: str, session_id: str, user_id: str | None) -> list[ScoredItem]:
        query_tokens = set(tokens(query))
        intents = intent_keys(query)
        broad = is_broad_memory_query(query)
        scores: dict[str, ScoredItem] = {}

        for memory in self.database.active_memories(user_id, session_id):
            key_hit = matches_intent(memory["key"], intents)
            overlap = overlap_score(query_tokens, set(tokens(f"{memory['key']} {memory['value']}")))
            if not key_hit and overlap <= 0 and not broad:
                continue
            score = 0.25 + 0.35 * float(memory.get("confidence", 0.0))
            if memory["source_session"] == session_id:
                score += 0.2
            if key_hit:
                score += 3.0
            score += overlap
            if broad:
                score += 0.75
            scores[memory["id"]] = ScoredItem("memory", memory, score)

        for memory in self.database.search_memories(query, user_id, session_id, limit=25):
            item = scores.setdefault(memory["id"], ScoredItem("memory", memory, 0.0))
            item.score += 2.0 * float(memory.get("score", 1.0))

        ranked = [item for item in scores.values() if item.score >= 0.9]
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:25]

    def rank_messages(
        self, query: str, session_id: str, user_id: str | None, include_recent: bool
    ) -> list[ScoredItem]:
        items: dict[str, ScoredItem] = {}
        for message in self.database.search_messages(query, None, session_id, limit=10):
            if message["role"] == "assistant":
                continue
            items[message["id"]] = ScoredItem("message", message, float(message.get("score", 1.0)))
        if include_recent:
            for message in self.database.recent_messages(user_id, session_id, limit=6):
                if message["role"] == "assistant":
                    continue
                items.setdefault(message["id"], ScoredItem("message", message, 0.35))
        ranked = list(items.values())
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:6]

    def assemble(self, memories: list[ScoredItem], messages: list[ScoredItem], max_tokens: int) -> dict[str, Any]:
        lines: list[str] = []
        citations: list[dict[str, Any]] = []

        def try_add(line: str, item: ScoredItem) -> bool:
            next_text = "\n".join([*lines, line]).strip()
            if approx_tokens(next_text) > max_tokens:
                return False
            lines.append(line)
            if item.kind == "memory":
                citations.append(
                    {
                        "turn_id": item.payload["source_turn"],
                        "score": round(item.score, 4),
                        "snippet": item.payload["value"][:240],
                    }
                )
            else:
                citations.append(
                    {
                        "turn_id": item.payload["turn_id"],
                        "score": round(item.score, 4),
                        "snippet": item.payload["content"][:240],
                    }
                )
            return True

        def add_header(header: str) -> bool:
            next_text = "\n".join([*lines, header]).strip()
            if approx_tokens(next_text) > max_tokens:
                return False
            lines.append(header)
            return True

        fact_items = [item for item in memories if item.payload["type"] in {"fact", "preference", "opinion"}]
        event_items = [item for item in memories if item.payload["type"] == "event"]

        if fact_items:
            section_started = add_header("## Known facts about this user")
            for item in fact_items:
                if section_started:
                    try_add(f"- {item.payload['value']} (updated {item.payload['updated_at'][:10]})", item)

        if event_items:
            if lines:
                lines.append("")
            section_started = add_header("## Relevant memories")
            for item in event_items:
                if section_started:
                    try_add(f"- {item.payload['value']} (updated {item.payload['updated_at'][:10]})", item)

        if messages:
            if lines:
                lines.append("")
            section_started = add_header("## Relevant from recent conversations")
            for item in messages:
                if section_started:
                    content = " ".join(item.payload["content"].split())[:220]
                    try_add(f"- [{item.payload['timestamp'][:10]}] {item.payload['role']}: {content}", item)

        context = "\n".join(lines).strip()
        if not citations:
            return {"context": "", "citations": []}
        return {"context": context, "citations": citations}

    def search_result(self, item: ScoredItem) -> dict[str, Any]:
        payload = item.payload
        if item.kind == "memory":
            return {
                "content": f"{payload['key']}: {payload['value']}",
                "score": round(item.score, 4),
                "session_id": payload["source_session"],
                "timestamp": payload["updated_at"],
                "metadata": {"kind": "memory", "key": payload["key"], "type": payload["type"]},
            }
        return {
            "content": payload["content"],
            "score": round(item.score, 4),
            "session_id": payload["session_id"],
            "timestamp": payload["timestamp"],
            "metadata": {"kind": "message", "role": payload["role"], "turn_id": payload["turn_id"]},
        }


def tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def intent_keys(query: str) -> list[str]:
    lower = query.lower()
    intents: list[str] = []
    asks_employment = any(word in lower for word in ["work", "job", "company", "employer", "joined"])
    asks_location = any(word in lower for word in ["city", "live", "lives", "based", "moved", "location"])
    if "where" in lower and not asks_employment:
        asks_location = True
    if asks_location:
        intents.append("location.current")
    if asks_employment:
        intents.append("employment.current")
    if any(word in lower for word in ["dog", "cat", "pet", "biscuit"]):
        intents.append("pet.")
    if any(word in lower for word in ["allergy", "allergic", "food", "cook", "shellfish"]):
        intents.extend(["allergy.", "diet."])
    if any(word in lower for word in ["prefer", "concise", "direct", "style"]):
        intents.append("preference.")
    if any(word in lower for word in ["opinion", "typescript", "love", "hate"]):
        intents.append("opinion.")
    return intents


def matches_intent(key: str, intents: list[str]) -> bool:
    return any(key == intent or key.startswith(intent) for intent in intents)


def is_broad_memory_query(query: str) -> bool:
    lower = query.lower()
    phrases = [
        "what do you know",
        "known facts",
        "remember about",
        "context about",
        "about this user",
        "user profile",
    ]
    return any(phrase in lower for phrase in phrases)


def overlap_score(query_tokens: set[str], content_tokens: set[str]) -> float:
    stop = {"the", "a", "an", "this", "that", "user", "their", "what", "does", "do", "is"}
    filtered = {token for token in query_tokens if token not in stop}
    if not filtered:
        return 0.0
    overlap = filtered & content_tokens
    return min(2.0, 0.55 * len(overlap) + len(overlap) / len(filtered))


def approx_tokens(text: str) -> int:
    return max(1, int(len(text) / 4) + 1)

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
import requests

from scripts.self_eval import DEFAULT_FIXTURE, run_fixture


BASE_URL = os.getenv("BASE_URL", "http://localhost:8080").rstrip("/")


def test_contract_roundtrip_and_structured_memories() -> None:
    user_id = "test-contract-user"
    cleanup_user(user_id)

    response = post_turn(
        user_id=user_id,
        session_id="test-contract-1",
        text="I just moved to Berlin from NYC last month. Loving it so far.",
        timestamp="2025-03-15T10:30:00Z",
    )

    assert response.status_code == 201
    turn_id = response.json()["id"]
    assert isinstance(turn_id, str) and turn_id

    recall = recall_query("Where does this user live?", "test-contract-2", user_id)
    assert recall.status_code == 200
    body = recall.json()
    assert "Berlin" in body["context"]
    assert body["citations"]
    assert all("turn_id" in citation and "score" in citation for citation in body["citations"])

    memories = requests.get(f"{BASE_URL}/users/{user_id}/memories", timeout=10)
    assert memories.status_code == 200
    memory_rows = memories.json()["memories"]
    assert any(row["key"] == "location.current" and row["active"] for row in memory_rows)
    assert all("source_turn" in row and "confidence" in row for row in memory_rows)


def test_fact_supersession_keeps_history() -> None:
    user_id = "test-job-user"
    cleanup_user(user_id)
    post_turn(user_id, "test-job-1", "I work at Stripe as a backend engineer.", "2025-03-10T09:00:00Z")
    post_turn(user_id, "test-job-2", "I joined Notion as a product engineer.", "2025-03-18T09:00:00Z")

    recall = recall_query("Where does the user work now?", "test-job-3", user_id).json()
    assert "Notion" in recall["context"]
    assert "Stripe" not in recall["context"]

    memories = requests.get(f"{BASE_URL}/users/{user_id}/memories", timeout=10).json()["memories"]
    active = [row for row in memories if row["active"]]
    inactive = [row for row in memories if not row["active"]]
    assert any("Notion" in row["value"] for row in active)
    assert any("Stripe" in row["value"] for row in inactive)
    assert any(row["supersedes"] for row in active)


def test_concurrent_sessions_do_not_bleed_between_users() -> None:
    cleanup_user("test-user-a")
    cleanup_user("test-user-b")
    post_turn("test-user-a", "test-isolation-a", "I live in Berlin.", "2025-03-15T10:00:00Z")
    post_turn("test-user-b", "test-isolation-b", "I live in Seattle.", "2025-03-15T10:00:00Z")

    a_recall = recall_query("Where does this user live?", "test-isolation-probe-a", "test-user-a").json()
    b_recall = recall_query("Where does this user live?", "test-isolation-probe-b", "test-user-b").json()

    assert "Berlin" in a_recall["context"]
    assert "Seattle" not in a_recall["context"]
    assert "Seattle" in b_recall["context"]
    assert "Berlin" not in b_recall["context"]


def test_malformed_and_unicode_inputs_are_safe() -> None:
    malformed = requests.post(f"{BASE_URL}/turns", data="{bad json", headers={"Content-Type": "application/json"}, timeout=10)
    assert 400 <= malformed.status_code < 500

    missing = requests.post(f"{BASE_URL}/turns", json={"session_id": "missing-fields"}, timeout=10)
    assert 400 <= missing.status_code < 500

    user_id = "test-unicode-user"
    cleanup_user(user_id)
    response = post_turn(
        user_id=user_id,
        session_id="test-unicode-1",
        text="I live in M\u00fcnchen and prefer concise answers.",
        timestamp="2025-03-20T10:00:00Z",
    )
    assert response.status_code == 201


def test_recall_respects_tight_token_budget() -> None:
    user_id = "test-budget-user"
    cleanup_user(user_id)
    post_turn(user_id, "test-budget-1", "I just moved to Berlin from NYC last month.", "2025-03-15T10:00:00Z")

    response = requests.post(
        f"{BASE_URL}/recall",
        json={"query": "Where does this user live?", "session_id": "test-budget-2", "user_id": user_id, "max_tokens": 4},
        timeout=10,
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {"context": "", "citations": []}


def test_anonymous_sessions_do_not_share_memories() -> None:
    post_turn(None, "test-anon-a", "I live in Berlin.", "2025-03-15T10:00:00Z")
    post_turn(None, "test-anon-b", "I live in Seattle.", "2025-03-15T10:00:00Z")

    a_recall = requests.post(
        f"{BASE_URL}/recall",
        json={"query": "Where does this user live?", "session_id": "test-anon-a", "user_id": None, "max_tokens": 512},
        timeout=10,
    ).json()
    b_recall = requests.post(
        f"{BASE_URL}/recall",
        json={"query": "Where does this user live?", "session_id": "test-anon-b", "user_id": None, "max_tokens": 512},
        timeout=10,
    ).json()

    assert "Berlin" in a_recall["context"]
    assert "Seattle" not in a_recall["context"]
    assert "Seattle" in b_recall["context"]
    assert "Berlin" not in b_recall["context"]


def test_correction_phrase_updates_current_location() -> None:
    user_id = "test-correction-user"
    cleanup_user(user_id)
    post_turn(user_id, "test-correction-1", "I live in NYC.", "2025-03-15T10:00:00Z")
    post_turn(user_id, "test-correction-2", "Actually, I live in Berlin now, not NYC.", "2025-03-16T10:00:00Z")

    recall = recall_query("Where does this user live?", "test-correction-3", user_id).json()
    assert "Berlin" in recall["context"]
    assert "NYC" not in recall["context"]


def test_recall_quality_fixture() -> None:
    report = run_fixture(BASE_URL, DEFAULT_FIXTURE)
    assert report["composite_score"] >= 0.75, report


def test_restart_persistence_when_enabled() -> None:
    if os.getenv("RUN_RESTART_TEST") != "1":
        pytest.skip("set RUN_RESTART_TEST=1 to run the Docker persistence check")

    user_id = "test-restart-user"
    cleanup_user(user_id)
    post_turn(user_id, "test-restart-1", "I live in Lisbon.", "2025-03-21T10:00:00Z")

    subprocess.run(["docker", "compose", "restart", "memory-service"], cwd=project_root(), check=True)
    wait_for_health()

    recall = recall_query("Where does this user live?", "test-restart-2", user_id).json()
    assert "Lisbon" in recall["context"]


def post_turn(user_id: str | None, session_id: str, text: str, timestamp: str) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/turns",
        json={
            "session_id": session_id,
            "user_id": user_id,
            "messages": [{"role": "user", "content": text}],
            "timestamp": timestamp,
            "metadata": {},
        },
        timeout=20,
    )


def recall_query(query: str, session_id: str, user_id: str) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/recall",
        json={"query": query, "session_id": session_id, "user_id": user_id, "max_tokens": 512},
        timeout=10,
    )


def cleanup_user(user_id: str) -> None:
    response = requests.delete(f"{BASE_URL}/users/{user_id}", timeout=10)
    assert response.status_code in {204, 404}


def wait_for_health() -> None:
    for _ in range(30):
        try:
            response = requests.get(f"{BASE_URL}/health", timeout=2)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise AssertionError("service did not become healthy")


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]

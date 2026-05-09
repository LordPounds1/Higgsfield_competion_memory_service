from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status

from src.config import Settings
from src.database import MemoryDatabase
from src.extraction import extract_memories
from src.models import (
    RecallRequest,
    RecallResponse,
    SearchRequest,
    SearchResponse,
    TurnRequest,
    TurnResponse,
    UserMemoriesResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    database = MemoryDatabase(settings.database_path)
    app.state.settings = settings
    app.state.database = database
    try:
        yield
    finally:
        database.close()


app = FastAPI(title="Higgsfield Memory Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/turns", response_model=TurnResponse, status_code=status.HTTP_201_CREATED)
def create_turn(request: TurnRequest) -> TurnResponse:
    database: MemoryDatabase = app.state.database
    turn_id = database.create_turn(request)
    memories = extract_memories(request, turn_id)
    if memories:
        database.add_memories(memories)
    return TurnResponse(id=turn_id)


@app.post("/recall", response_model=RecallResponse)
def recall(request: RecallRequest) -> RecallResponse:
    database: MemoryDatabase = app.state.database
    messages = database.search_messages(request.query, request.user_id, request.session_id, limit=5)
    if not messages:
        messages = database.recent_messages(request.user_id, request.session_id, limit=3)
    citations = []
    lines = []
    for message in messages:
        if message["role"] == "assistant":
            continue
        snippet = " ".join(message["content"].split())[:220]
        lines.append(f"- [{message['timestamp'][:10]}] {message['role']}: {snippet}")
        citations.append({"turn_id": message["turn_id"], "score": float(message.get("score", 0.1)), "snippet": snippet})
    if not lines:
        return RecallResponse(context="", citations=[])
    return RecallResponse(context="## Recent conversation context\n" + "\n".join(lines), citations=citations)


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    database: MemoryDatabase = app.state.database
    messages = database.search_messages(request.query, request.user_id, request.session_id, request.limit)
    return SearchResponse(
        results=[
            {
                "content": item["content"],
                "score": float(item.get("score", 0.0)),
                "session_id": item["session_id"],
                "timestamp": item["timestamp"],
                "metadata": {"role": item["role"], "turn_id": item["turn_id"]},
            }
            for item in messages
        ]
    )


@app.get("/users/{user_id}/memories", response_model=UserMemoriesResponse)
def user_memories(user_id: str) -> UserMemoriesResponse:
    database: MemoryDatabase = app.state.database
    return UserMemoriesResponse(memories=database.get_user_memories(user_id))


@app.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str) -> Response:
    database: MemoryDatabase = app.state.database
    database.delete_session(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str) -> Response:
    database: MemoryDatabase = app.state.database
    database.delete_user(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

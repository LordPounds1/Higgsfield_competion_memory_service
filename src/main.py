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
from src.recall import RecallEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    database = MemoryDatabase(settings.database_path)
    app.state.settings = settings
    app.state.database = database
    app.state.recall = RecallEngine(database)
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
    engine: RecallEngine = app.state.recall
    return RecallResponse(**engine.recall(request.query, request.session_id, request.user_id, request.max_tokens))


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    engine: RecallEngine = app.state.recall
    return SearchResponse(**engine.search(request.query, request.session_id, request.user_id, request.limit))


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

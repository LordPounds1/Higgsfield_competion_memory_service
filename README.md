# Higgsfield Memory Service

Dockerized FastAPI memory service for an AI agent.

This repository is being built iteratively. The first milestone focuses on the HTTP contract, Docker startup, SQLite WAL persistence, and the base tables required for later structured memories.

## Current Milestone

`v2 - Structured extraction`

- FastAPI application on port `8080`.
- Required endpoints are present.
- SQLite database persists under `/data/memory.db`.
- Docker Compose uses the named volume `memory_data:/data`.
- Tables exist for `turns`, `messages`, and `memories`.
- FTS5 tables exist for message and future memory search.
- `POST /turns` now extracts structured memories from user messages.
- `/users/{user_id}/memories` shows typed facts and preferences with keys, confidence, active status, and provenance.

Fact evolution, hybrid recall, fixtures, and final documentation are intentionally added in later milestones.

## Run

```bash
docker compose up --build -d
curl http://localhost:8080/health
```

## Development Direction

The design follows a SQLite-first memory system:

1. Store completed turns and messages.
2. Extract structured memories instead of raw chunks. (current milestone)
3. Supersede mutable facts without deleting history.
4. Rank active facts, query-relevant memories, and recent session context under a token budget.

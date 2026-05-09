# Higgsfield Memory Service

Dockerized FastAPI memory service for an AI agent. It accepts completed conversation turns, persists the transcript, extracts structured user memories, evolves mutable facts, and returns prompt-ready context through `POST /recall`.

The design is intentionally SQLite-first. I optimized for correctness, inspectability, and an evaluation loop rather than a large vector stack.

## Architecture

```text
HTTP eval harness
        |
        v
FastAPI routes (src/main.py)
        |
        +--> Extraction (src/extraction.py)
        +--> SQLite + FTS5 (src/database.py)
        +--> Recall ranking (src/recall.py)
```

`POST /turns` is synchronous. A turn is stored, user memories are extracted, mutable facts are superseded, and FTS rows are updated before the endpoint returns. After a successful `201`, the data is immediately queryable through `/recall`, `/search`, and `/users/{user_id}/memories`.

## HTTP Contract

Implemented endpoints:

- `GET /health`
- `POST /turns`
- `POST /recall`
- `POST /search`
- `GET /users/{user_id}/memories`
- `DELETE /sessions/{session_id}`
- `DELETE /users/{user_id}`

Auth headers are accepted but not required. This keeps the service compatible with the provided eval setup.

## Backing Store

The service uses SQLite in WAL mode with a Docker named volume:

```yaml
memory_data:/data
```

Default path:

```text
/data/memory.db
```

Tables:

- `turns`: completed conversation turns.
- `messages`: individual messages inside turns.
- `memories`: structured extracted knowledge.
- `messages_fts`: FTS5 index for message search.
- `memories_fts`: FTS5 index for memory search.

SQLite was chosen because this challenge rewards a small, reproducible memory system. FTS5 gives deterministic lexical retrieval, and the memory table remains easy to inspect during review.

## Structured Extraction

The extractor is deterministic and works without API keys. It emits structured memories like:

```json
{
  "type": "fact",
  "key": "location.current",
  "value": "Lives in Berlin; moved from NYC",
  "confidence": 0.92,
  "source_session": "session-id",
  "source_turn": "turn-id",
  "active": true
}
```

Covered categories:

- `location.current`: moved, relocated, live in, now living in, based in.
- `employment.current`: work at, joined, started a new role, left X and joined Y.
- `pet.<name>`: explicit pets and implicit walking references.
- `allergy.<item>`: allergic to X, X allergy.
- `diet.vegetarian`, `diet.vegan`.
- `preference.answer_style`: concise/direct answer preferences.
- `opinion.typescript`: simple current TypeScript opinion examples.

This is not a general NLP extractor. The tradeoff is deliberate: deterministic extraction is reproducible in Docker and easy to test. The `.env.example` includes Groq placeholders as a future extension point, but the current implementation does not require an LLM key.

## Fact Evolution

Mutable facts use stable keys. Keys ending in `.current` and keys under `opinion.*` supersede prior active memories for the same user.

Example:

```text
I work at Stripe as a backend engineer.
I joined Notion as a product engineer.
```

Result:

- old Stripe memory remains stored with `active=false`;
- new Notion memory is stored with `active=true`;
- the Notion row points to the old row through `supersedes`;
- `/recall` returns Notion, not Stripe;
- `/users/{user_id}/memories` still shows the history.

For anonymous traffic (`user_id = null`), mutable facts are scoped to the session. For identified users, memories are scoped by `user_id`. This avoids cross-user leakage even if two users reuse the same `session_id`.

## Recall Strategy

`POST /recall` is the main endpoint and uses a hybrid ranking pipeline:

1. Load active structured memories for the user or anonymous session.
2. Search active memories with SQLite FTS5.
3. Apply scoring boosts:
   - exact key intent, for example `where/live/city` -> `location.current`;
   - active memory;
   - confidence;
   - same-session memory;
   - lexical overlap.
4. Add recent current-session context below structured facts.
5. Assemble readable context under `max_tokens`.

Example output:

```text
## Known facts about this user
- Works at Notion as product engineer (updated 2026-05-09)
- Lives in Berlin; moved from NYC (updated 2026-05-09)

## Relevant from recent conversations
- [2025-03-15] user: I just moved to Berlin from NYC last month.
```

Noise behavior is explicit: if nothing relevant is found, `/recall` returns:

```json
{"context": "", "citations": []}
```

## Token Budget

The service uses an approximate token counter based on character count. It is conservative enough to avoid returning context that is far over budget.

When budget is tight, priority is:

1. active structured user facts;
2. query-relevant memories;
3. recent current-session context.

If even the first useful line does not fit, recall returns an empty context rather than a header-only prompt fragment.

## Search

`POST /search` returns structured results instead of prompt prose. It searches memories and messages, ranks memory results slightly higher, and includes metadata describing the result source.

## Testing And Self-Eval

The project includes service-level tests, unit tests, a recall-quality fixture, and a small benchmark runner.

Run the service:

```bash
docker compose up --build -d
curl http://localhost:8080/health
```

Run unit tests inside the Docker image:

```bash
docker compose run --rm --no-deps -v "$PWD:/app" memory-service \
  python -m pytest tests/test_extraction_unit.py tests/test_recall_unit.py tests/test_database_unit.py -v
```

Run service tests against a running service:

```bash
BASE_URL=http://localhost:8080 pytest tests/test_service.py -v
```

Run self-eval:

```bash
python scripts/self_eval.py --base-url http://localhost:8080 --fail-under 0.75
```

Latest local verification:

- Unit tests in Docker: `18 passed`
- Service tests: `9 passed, 1 skipped`
- Self-eval composite score: `1.0`
- Expected facts found: `7/7`
- Noise probes empty: `1/1`
- p95 recall latency: about `31 ms`

The skipped test is restart persistence, guarded by:

```bash
RUN_RESTART_TEST=1
```

## PowerShell Smoke Test

```powershell
$body = @{
  session_id = "smoke-1"
  user_id = "user-1"
  messages = @(
    @{ role = "user"; content = "I just moved to Berlin from NYC last month. Loving it so far." }
  )
  timestamp = "2025-03-15T10:30:00Z"
  metadata = @{}
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri "http://localhost:8080/turns" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body

$recallBody = @{
  query = "Where does this user live?"
  session_id = "smoke-2"
  user_id = "user-1"
  max_tokens = 512
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://localhost:8080/recall" `
  -Method Post `
  -ContentType "application/json" `
  -Body $recallBody
```

The recall context should mention Berlin.

## Failure Modes

- No data: recall returns empty context and citations.
- Missing API keys: service still works because extraction is deterministic.
- Malformed JSON or missing fields: FastAPI/Pydantic returns 4xx.
- Unicode input: stored as UTF-8 text in SQLite.
- Same session id across users: user-scoped recall does not mix their memories or raw context.
- SQLite lock contention: WAL mode and `busy_timeout` reduce transient failures, but this is still a single-node design.

## Tradeoffs

- No vector DB. This avoids operational complexity and keeps behavior inspectable.
- Regex extraction is not broad NLP. It is stable, fast, and tested, but will miss unusual phrasing.
- Opinion evolution is current-state supersession, not a full belief timeline.
- Turn storage and memory insertion are separate database calls in the route. The route is synchronous, but a future version should wrap turn + memories as one higher-level ingestion transaction.
- The design targets the challenge workload, not horizontal scale.

# CHANGELOG

## v1 - Contract skeleton

**What changed:** Added the Dockerized FastAPI service, Pydantic models, SQLite WAL setup, `turns`, `messages`, and `memories` tables, plus FTS5 tables for later lexical search.

**Why:** The private eval first needs a service that starts reliably and exposes the exact HTTP contract. This milestone deliberately avoids extraction and ranking so the foundation can be tested independently.

**Observation:** A memory service should not begin with vector infrastructure. The useful base is a durable turn/message store and a structured memory table that later milestones can populate.

**Result:** `/health`, `/turns`, `/recall`, `/search`, `/users/{user_id}/memories`, and cleanup endpoints exist. `/recall` is still a simple recent-message fallback and will be replaced by structured recall in later iterations.

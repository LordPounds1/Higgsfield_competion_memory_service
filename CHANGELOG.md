# CHANGELOG

## v1 - Contract skeleton

**What changed:** Added the Dockerized FastAPI service, Pydantic models, SQLite WAL setup, `turns`, `messages`, and `memories` tables, plus FTS5 tables for later lexical search.

**Why:** The private eval first needs a service that starts reliably and exposes the exact HTTP contract. This milestone deliberately avoids extraction and ranking so the foundation can be tested independently.

**Observation:** A memory service should not begin with vector infrastructure. The useful base is a durable turn/message store and a structured memory table that later milestones can populate.

**Result:** `/health`, `/turns`, `/recall`, `/search`, `/users/{user_id}/memories`, and cleanup endpoints exist. `/recall` is still a simple recent-message fallback and will be replaced by structured recall in later iterations.

## v2 - Structured extraction

**What changed:** Added a deterministic extraction module and wired it into `POST /turns`. The service now extracts structured memories such as `location.current`, `employment.current`, `pet.<name>`, `diet.vegetarian`, `allergy.<item>`, `preference.answer_style`, and `opinion.typescript`.

**Why:** The assignment is about memory, not only message storage. This iteration makes `/users/{user_id}/memories` useful for inspection and gives recall a structured source to use in later milestones.

**Observation:** A small rules-based extractor is enough to cover the self-eval-style examples without depending on an external API key. It is also easier to debug than an LLM-only extractor.

**Result:** Turns are still stored synchronously, and newly extracted memories are inserted before `POST /turns` returns. Fact supersession is not implemented yet, so mutable facts can still accumulate as active history until v3.

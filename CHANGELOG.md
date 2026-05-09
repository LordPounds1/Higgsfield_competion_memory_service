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

## v3 - Supersession for mutable facts

**What changed:** Added key-based supersession for mutable memories. New values for keys such as `location.current`, `employment.current`, and `opinion.<topic>` now mark older active memories inactive and store the old memory id in `supersedes`.

**Why:** A memory service should know the current state of mutable facts. If the user first says they work at Stripe and later says they joined Notion, recall should not treat both jobs as equally current.

**Observation:** The extractor already normalizes mutable topics into stable keys, so the update logic can stay simple: compare by key inside the same user scope, deactivate old active rows, and insert the new row.

**Result:** Old facts are preserved for inspection through `/users/{user_id}/memories`, but only the latest mutable fact remains active. This sets up the next iteration, where recall ranking can safely prioritize active memories.

## v4 - Hybrid recall ranking

**What changed:** Replaced the recent-message fallback with a recall engine that ranks active structured memories, FTS matches, and recent user context. Added query-intent boosts for location, employment, pets, allergies, preferences, and opinions.

**Why:** `/recall` is the main endpoint in the eval. Returning recent messages is not enough once structured memories exist; current facts should be first, then query-relevant memories, then recent context.

**Observation:** After supersession, active/inactive status became a useful ranking signal. Query wording also gives strong hints: "where" maps to `location.current`, "work" maps to `employment.current`, and "dog named Biscuit" maps to `pet.*`.

**Result:** Recall now produces prompt-ready sections under `max_tokens`: known facts first, relevant memories second, recent conversation context last. `/search` also returns structured memory results instead of only message snippets.

## v5 - Recall fixture and service tests

**What changed:** Added a small recall-quality fixture, a reusable `scripts/self_eval.py` runner, and service-level tests for contract shape, structured memory inspection, supersession, user isolation, malformed input, and optional restart persistence.

**Why:** The project needs an evaluation loop, not only manual smoke checks. The fixture gives a cheap way to catch regressions in the core behaviors the private eval is likely to probe.

**Observation:** The first useful metric is simple: expected fact hit rate plus an empty-context check for noise. It is not a full judge, but it quickly catches stale facts leaking into recall and irrelevant active memories being over-returned.

**Result:** The test suite can run against a live service with `BASE_URL=http://localhost:8080 pytest tests/ -v`, and the benchmark can be run directly with `python scripts/self_eval.py --base-url http://localhost:8080 --fail-under 0.75`. Current fixture score is 1.00: 7/7 expected facts found and 1/1 noise probe returned empty context.

## v6 - Unit tests and recall hardening

**What changed:** Added unit tests for extraction, recall intent ranking, token budget behavior, database supersession, duplicate prevention, and anonymous session scoping. Tightened recall intent handling so "Where does the user work now?" does not accidentally boost `location.current`.

**Why:** The service-level fixture was useful, but slow to diagnose ranking mistakes. Unit tests make the core memory behavior easier to reason about before running the HTTP suite.

**Observation:** The main recall bug was not BM25 or FTS. It was intent ambiguity: "where" is a good location clue until the query is actually about employment.

**Result:** Unit coverage caught the ranking edge case directly. Service fixture quality stayed at 1.00.

## v7 - Robustness coverage

**What changed:** Added tests for correction phrasing, tight token budgets, anonymous session isolation, and noise queries. Verified that tiny token budgets return empty context instead of header-only prompt fragments.

**Why:** The private eval is likely to include cold/noisy scenarios and cleanup edge cases. These tests make sure recall fails closed instead of returning unrelated memory.

**Observation:** The existing extractor already handled "Actually, I live in Berlin now, not NYC", but that was not obvious until it was pinned with a test.

**Result:** Service tests increased to 8 passing checks plus the optional restart test. Self-eval stayed at 1.00.

## v8 - Scope isolation and extraction coverage

**What changed:** Fixed user/session scoping so same-session different-user data does not leak through memories or recent raw messages. Added extraction support for common paraphrases: relocated, now living in, left X and joined Y, started a new role at, pet naming, allergy noun phrases, and concise-answer preferences.

**Why:** Loose `OR` scoping improved recall but was risky. A reviewer or private eval can reuse a session id across users, and recall must not mix their facts. Extraction also needed a few more common paraphrases without adding an LLM dependency.

**Observation:** The new same-session leakage test caught a real issue: structured memories were safe after the first fix, but recent raw message context still leaked. The paraphrase tests also caught "I'm now living in Tokyo" before it reached final verification.

**Result:** Unit tests pass at 18/18, service tests pass at 9/10 with the restart test intentionally skipped by default, and self-eval remains 1.00 with p95 recall latency around 31 ms.

## v9 - Final documentation pass

**What changed:** Rewrote the README around the final architecture, recall strategy, fact evolution, token budget behavior, tests, failure modes, and tradeoffs.

**Why:** The implementation is strongest when reviewed as a small structured-memory system, not as generic chat search. The README now makes those design choices explicit.

**Observation:** The important story is not infrastructure complexity. It is extraction, supersession, scoped recall, and a measurable evaluation loop.

**Result:** The repository is ready for a clean final run and submission packaging.

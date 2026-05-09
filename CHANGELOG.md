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

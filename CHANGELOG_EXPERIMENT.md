# Optional LLM Extraction Experiment

This branch tests an optional Groq-backed extraction layer without changing the deterministic baseline.

## Hypothesis

The submitted service is stable because deterministic extraction always works without API keys. The weak spot is coverage for harder paraphrases. An optional LLM extractor may improve extraction coverage, but it can add latency, API-key dependency, and output validation risk.

## Design

The extraction pipeline is:

```text
deterministic rules extractor always runs
        |
        +--> optional Groq extractor if GROQ_API_KEY exists
        |
        +--> validate LLM JSON memories
        |
        +--> merge and dedupe memories
```

If Groq is missing, slow, invalid, or returns malformed JSON, the service falls back to deterministic memories and still returns successfully from `/turns`.

## Baseline Before This Branch

Command:

```bash
python scripts/self_eval.py --base-url http://localhost:8080 --fail-under 0.75
```

Result on the standard fixture:

- expected facts: 7/7
- noise probes: 1/1
- composite score: 1.00
- p95 recall latency: about 28 ms
- service tests: 9 passed, 1 skipped

## Hard Paraphrase Fixture

This branch adds `fixtures/hard_paraphrase_fixture.json`.

It includes phrasing that is intentionally harder for deterministic rules:

- "I took a product role at Notion"
- "I moved out of NYC and settled in Berlin"
- "Biscuit needs another walk"
- "I avoid shellfish"
- "I'd rather keep replies short"

Run without Groq:

```bash
python scripts/self_eval.py \
  --base-url http://localhost:8080 \
  --fixture fixtures/hard_paraphrase_fixture.json \
  --fail-under 0.0
```

Observed no-key result on this branch:

- expected facts: 2/6
- recall hit rate: 0.3333
- composite score: 0.4333
- p95 recall latency: about 23 ms
- failures: hard employment transition, settled-in location phrasing, implicit Biscuit pet, avoid-shellfish phrasing

This is the intended baseline: the deterministic extractor remains stable, but the hard fixture exposes where an LLM extractor should help.

## Iteration 2 - Prompt tightening plus deterministic fallbacks

What changed:

- tightened the Groq system prompt around current employer, settled-in location phrasing, pet-care phrases, and food avoidance;
- added deterministic fallback patterns for:
  - "I took a product role at Notion"
  - "I moved out of NYC and settled in Berlin"
  - "Biscuit needs another walk"
  - "I avoid shellfish"
- added a unit test that locks these hard paraphrases as structured memories.

What I noticed:

The first Groq run improved the hard fixture from 2/6 to 4/6 expected facts, but still missed the implicit pet and shellfish avoidance cases. That made the LLM layer useful but not strong enough to justify merging by itself.

Why I changed approach:

These four examples are not exotic semantic reasoning. They are common memory-service patterns, so relying on an external model for them is unnecessary. The better design is deterministic coverage for common durable facts, with Groq reserved for wider paraphrase coverage.

Result after this pass without Groq:

- standard fixture: 7/7 expected facts, 1/1 noise probe, composite score 1.00;
- hard paraphrase fixture: 6/6 expected facts, composite score 1.00;
- extraction unit tests: 11 passed;
- service-level tests: 9 passed, 1 skipped;
- p95 recall latency on hard fixture: about 30 ms.

Decision:

This experiment is now stronger as a deterministic extraction improvement than as a pure LLM dependency. I would still keep it on a branch until comparing the code diff against the submitted `main`, then either cherry-pick only the deterministic fallbacks or document Groq as an optional future layer.

Run with Groq:

```bash
export GROQ_API_KEY=...
docker compose up --build -d
python scripts/self_eval.py \
  --base-url http://localhost:8080 \
  --fixture fixtures/hard_paraphrase_fixture.json \
  --fail-under 0.75
```

## Decision Criteria

I would only merge this into `main` if:

- no-key mode stays fully green;
- standard fixture does not regress;
- hard paraphrase fixture improves materially;
- `/turns` latency remains acceptable;
- invalid LLM output is safely discarded;
- README clearly documents that Groq is optional.

For now, `main` stays deterministic and reproducible. This branch is an experiment for measuring quality/latency tradeoffs.

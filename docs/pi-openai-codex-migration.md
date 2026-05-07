# Pi + GPT-5.1 via OpenAI-Codex Migration Notes

This note captures the setup that worked in this repo when using `pi` with the user's Codex subscription instead of the OpenAI API.

## Core Rule

Use:

- `provider = openai-codex`
- `model = gpt-5.1`

Do not use:

- `provider = openai`

`openai-codex` uses the ChatGPT/Codex subscription path. `openai` uses the OpenAI API key path. In this repo, those two paths behaved differently for Graphiti ingest:

- `openai-codex + gpt-5.1` could produce non-empty graph extractions
- `openai + gpt-5.1` could return empty graph extractions for the same input

## Recommended Runtime Shape

For integrations, do not repeatedly spawn `pi -p ...` per request.

Use a long-lived RPC worker pool instead:

```bash
pi --mode rpc --provider openai-codex --model gpt-5.1
```

Recommended defaults:

- `thinking = off`
- `concurrency = 3`
- keep the proxy process alive

In this repo, the effective settings were:

```bash
PI_PROVIDER=openai-codex
PI_MODEL=gpt-5.1
PI_PROXY_THINKING=off
PI_PROXY_CONCURRENCY=3
```

## Why RPC Matters

`pi -p` is acceptable for manual one-off use, but it is the wrong shape for high-frequency structured extraction.

Graphiti ingest is expensive because one logical memory can trigger multiple LLM steps:

- entity extraction
- resolution / dedupe
- edge extraction
- follow-up normalization

If each of those calls cold-starts a new CLI process, latency compounds badly.

RPC mode removes most of that overhead.

## Graphiti-Specific Lessons

### 1. Do not ingest giant transcripts as one episode

This was one of the biggest quality problems.

Better:

- split transcripts into smaller episodes
- prefer user-authored fact blocks
- optionally add focused episodes for numeric / late-turn facts

In this repo, graph quality improved when transcript ingestion changed from:

- one full session transcript per extract job

to:

- smaller user-focused windows
- extra focused episodes for fact-heavy user turns

### 2. Pass the session time through

If your graph layer supports it, pass session/message time into the ingest call.

In this repo:

- the transcript already contained `[session_date] ...`
- that value is now forwarded as `reference_time`

Without this, temporal graph behavior is weaker and all facts effectively look like "ingested now".

### 3. Embeddings are still separate

`pi` does not solve embeddings.

Even if:

- Pi handles LLM extraction well

you still need:

- a working embeddings provider for graph search

Otherwise ingest may succeed while graph search remains poor or broken.

## Search Lessons

Even after ingest was fixed, graph search needed work.

Problems observed:

- raw memory dominated ranking
- graph search returned semantically related but irrelevant facts
- graph search could miss the concrete answer span even when the graph had partial relevant structure

What helped:

- keep full `facts + edges + nodes` from graph search
- normalize graph queries before sending them
- derive query anchors from strong raw hits
- rerank graph results against signal tokens, not just provider scores
- merge raw and graph on a normalized score scale

## Working Configuration Pattern

For a Graphiti-style setup, the practical split is:

- LLM extraction: `pi + openai-codex + gpt-5.1`
- embeddings: separate embeddings provider
- chat/runtime: can also stay on `pi`, but that is independent from graph ingest

## Minimal Migration Checklist

1. Set Pi provider to `openai-codex`, not `openai`.
2. Use `gpt-5.1` first. It was the best default in this repo.
3. Run Pi through RPC mode, not repeated `pi -p`.
4. Turn `thinking` off first, then only raise it if extraction quality demands it.
5. Keep a small worker pool, such as `3`.
6. Do not feed Graphiti giant transcripts as single episodes.
7. Pass transcript/session time into ingest if your stack supports it.
8. Keep embeddings configured separately.
9. Add a guard so "empty graph extraction" is treated as failure, not success.
10. Validate graph search independently from raw-memory fallback.

## Model Notes

The Codex subscription models tested in this repo behaved roughly like this for Graphiti ingest:

- `gpt-5.1`: best default balance
- `gpt-5.4`: also strong, worth testing if quality matters more than stability tuning
- `gpt-5.1-codex-mini`: usable, but not clearly better
- `gpt-5.1-codex-max`: slower and noisier in extraction output

Default recommendation:

- start with `gpt-5.1`

## Validation You Should Run In a New Project

Before trusting the setup, verify these in order:

1. Pi RPC responds through the subscription path.
2. A minimal fact sentence produces non-empty graph nodes and edges.
3. Graph search can retrieve those edges.
4. A transcript with a concrete entity/value fact survives ingest.
5. A transcript with a late-turn numeric fact survives ingest.

If step 2 fails, stop. The rest of the pipeline is not trustworthy.

## Repo References

Relevant files in this repo:

- [pi_proxy.py](/Users/thursday/go/play/MiroFish/graphiti-zep/pi_proxy.py)
- [graphiti-zep/.env](/Users/thursday/go/play/MiroFish/graphiti-zep/.env)
- [memory_adapter.py](/Users/thursday/go/play/MiroFish/graphiti-studio/backend/app/services/memory_adapter.py)
- [graphiti_client.py](/Users/thursday/go/play/MiroFish/graphiti-studio/backend/app/services/graphiti_client.py)
- [server.py](/Users/thursday/go/play/MiroFish/graphiti-zep/graphiti_zep/server.py)

## Current Known Limit

The current state in this repo is:

- coupon / Target style facts improved materially once ingest was chunked and user-focused
- some numeric span facts, such as `45 minutes each way`, are still harder for the graph layer than for raw-memory retrieval

So the migration recipe is good, but you should still test:

- entity facts
- monetary facts
- numeric duration facts
- temporal updates

separately.

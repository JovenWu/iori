# iori — Backend Design Spec

> **Superseded** — historical document kept for reference. The shipped code
> differs (Python 3.10 container, newer endpoint set, current layout); the
> root `README.md` is authoritative.

Sectors Hackathon 2026 · Track 01 (AI Agents & Assistants) · Build groundwork for a
Sectors-powered agentic workflow. This document covers the backend foundation:
auth, a ReAct agent loop, long-term memory, context management, resumable SSE
streaming, and durable LangGraph checkpoints. Sectors-specific tools are added
on top of this base in later work.

## Stack

- Python 3.12+, FastAPI, Uvicorn
- LangGraph (`StateGraph` + `AsyncPostgresSaver` checkpoints)
- LangChain `ChatOpenAI` pointed at OpenRouter
  - Chat / classification / summarization: `openai/gpt-5.6-luna`
  - Embeddings: `openai/text-embedding-3-small` (1536-dim)
- TypeSafe **JEV** (`typesafe-sdk`, `AsyncTypeSafeClient`, model `jev-latest`)
  for all classification decisions; LLM fallback when `TYPESAFE_API_KEY` unset
- PostgreSQL 16 + pgvector (Docker Compose), SQLAlchemy 2 async + asyncpg,
  Alembic migrations
- JWT auth (`python-jose`), bcrypt via passlib, tiktoken for token counting,
  slowapi for rate limiting

## Repository layout

```
backend/
  requirements.txt  .env.example  docker-compose.yml  alembic.ini
  alembic/          env.py + versions/
  app/
    main.py         lifespan: startup guard, AgentService init/shutdown
    core/           config, logging, security, llm, jev, exceptions, handlers,
                    middleware, ratelimit
    db/             base (DeclarativeBase + timestamps), session
    models/         user, thread, memory, thread_digest
    schemas/        auth, chat, memory
    api/            deps (get_db, get_current_user)
      v1/api.py     router aggregation
      v1/endpoints/ auth.py, chat.py, memory.py
    agent/          state, context, router, graph, runs, service
    memory/         embeddings, extractor, store, recall, pipeline, digests
    prompts/        system.md, summarize.md, extract.md
  tests/            pytest (asyncio)
```

## Data model

- **users**: id (int PK), username (unique), email?, name?, hashed_password?,
  is_active, token_version (monotonic; embedded in JWT `ver` claim — logout
  bumps it to revoke all outstanding tokens), timestamps.
- **threads**: id (uuid PK), user_id FK, title (derived from first message,
  word-boundary trimmed), first_answer_preview (denormalized, set once),
  timestamps.
- **memories**: id (uuid PK), user_id FK (cascade), content (Text), embedding
  (Vector(1536)), hash (SHA-256 of normalized content, indexed — exact-dedup
  without an LLM call), source_thread_id?, timestamps.
- **thread_digests**: id (uuid PK), thread_id FK unique (cascade), user_id FK,
  title?, digest (Text), embedding (Vector(1536)), message_count, stale_turns,
  last_turn_at, timestamps.

## Auth (login only, no registration)

- `POST /api/v1/auth/login` {username, password} — single account configured via
  env (`APP_USERNAME` / `APP_PASSWORD`); `secrets.compare_digest`; user row is
  auto-provisioned on first successful login. Rate-limited.
- `POST /api/v1/auth/refresh` — exchange refresh token (`type=refresh` claim)
  for a new pair; rejects revoked (`ver` mismatch) tokens.
- `POST /api/v1/auth/logout` — bumps `token_version`, invalidating all tokens.
- `GET /api/v1/users/me` — current user profile.
- JWT claims: `sub` (user id), `type` (access|refresh), `ver` (token_version).

## Agent graph (ReAct, tools deferred)

```
START → context_manager → router → agent ──→ END
                        │          ↑  └→ tools →┘   (tools wired, empty list)
                        └──────────┘   (router is pass-through to `general`
                                        until Sectors workflows register)
```

- **state**: `messages` (add_messages reducer, never trimmed), `summary`,
  `summarized_upto` (index into messages folded into summary),
  `recalled_memories`, `related_threads`, `route`.
- **context_manager** (per turn):
  1. JEV gate call — one `system_one` request, parallel questions:
     `needs_user_memory` (Noul: message depends on stored user facts/preferences),
     `needs_past_chats` (Noul: message references earlier conversations).
     Skips the retrieval pipelines entirely on small talk. Falls back to
     "retrieve both" when JEV is unavailable/fails.
  2. Rolling summarization — when `tokens(summary + active_messages) >
     CONTEXT_TOKEN_LIMIT`, find the boundary that keeps the last KEEP_TURNS
     human/AI pairs intact, summarize everything before it (chaining the
     existing summary), advance `summarized_upto`.
- **router**: JEV `Choice` over a registry of workflow keys. Groundwork ships
  `general` only; Sectors workflows later register `{key: {criteria, graph}}`
  without touching the router. Confidence is logged; low confidence falls back
  to `general`.
- **agent**: builds `[system] + [memory block] + [related-threads block] +
  [summary block] + active messages` — each injected block wrapped as a fenced
  READ-ONLY SystemMessage so retrieved content can never override the prompt —
  then calls the tool-bound LLM.

## Memory system

**Write path** (post-turn, fire-and-forget, semaphore-bounded so it never pins
the DB pool):

1. Cheap pre-filter: skip LLM unless the user message has ≥4 words and a
   first-person marker (id/en).
2. Extract facts via structured-output LLM — short standalone Indonesian
   statements prefixed "Pengguna …"; output sanitized (allowlist, length cap,
   control-char collapse).
3. Per fact: exact-hash dedup → top-k similar memories → **one JEV call**
   (parallel Noul per candidate "does this fact update or contradict it?" +
   Choice `refines`/`contradicts`/`restates`) → apply:
   - no relation → **ADD**
   - `restates` → **NOOP**
   - `contradicts` → **DELETE** + **ADD**
   - `refines` → **UPDATE** (one small LLM merge call — JEV cannot generate)
4. Enforce per-user memory cap (evict oldest by updated_at).

**Read path** (hybrid retrieval, on JEV-gated demand):

1. Normalize query into the stored fact's shape (HyDE-style, same "Pengguna …"
   form) via the classifier LLM.
2. Semantic arm: pgvector cosine ≥ threshold (top 20).
3. Keyword arm: Postgres `ts_rank` BM25 over a GIN index (top 20, OR-joined
   tokens for id/en mixed queries).
4. RRF merge (k=60), dedupe by id.
5. Rerank: **JEV `Score` fan-out** (one Score question per candidate in a single
   request; criteria = ordered relevance levels). LLM structured-output rerank
   is the fallback when TypeSafe is unconfigured. Threshold + cosine-floor
   rescue (keep strongest hit if all reranked out).
6. Inject top-k as the fenced `[LONG-TERM MEMORIES]` block.

**Cross-thread recall**: debounced digest upkeep — regenerate a thread's 2–4
sentence digest every N stale turns (from rolling summary when available),
embed it, and surface top matches (same hybrid pipeline, no rerank for the
signal path) as the `related_threads` block.

## Streaming (SSE, detached producer)

Generation is decoupled from the HTTP request so a disconnect never loses a
turn:

- `runs.py` — in-process registry: `AgentRun` per thread_id with a
  seq-numbered replay buffer (deque), subscriber queues, `stop_event`,
  `terminal` event, per-user + global active-run caps, linger-then-evict for
  late reconnects.
- `POST /api/v1/chat/stream` {message, thread_id?} — get-or-create thread →
  per-thread mutation lock → stop+await any in-flight producer (escalate to
  cancel, then 409) → register run → detached task drives `graph.astream`
  (`updates`, `messages`, `custom` modes) → publish events; the HTTP response
  only subscribes.
- Events: `metadata` (thread_id, started_at), `token`, `node_finished`,
  `done`/`stopped`/`error`. `tool_update`/`thinking` plumbing kept for later
  Sectors tools.
- `GET /api/v1/chat/threads/{id}/stream` — resume: replay buffer then tail live;
  204 when no run is active.
- `POST /api/v1/chat/threads/{id}/stop` — graceful stop; the partial answer is
  persisted to the checkpoint as an AI message.
- `GET /api/v1/chat/history/{thread_id}` — serialized turns from checkpoint
  state.
- Thread CRUD: `GET /threads` (paged), `GET /threads/all` (with preview),
  `PATCH /threads/{id}` (rename), `DELETE /threads/{id}` (row + checkpoints),
  `DELETE /threads/{id}/last-turn`, `POST .../edit/stream`,
  `POST .../regenerate/stream`.
- Mutation paths reserve run capacity *before* destructive work so a capped
  request never half-mutates.
- Shutdown: signal in-flight runs → drain producers + memory tasks → cancel
  linger tasks → close pools.

## JEV fallback contract

Every JEV call site wraps the client so that a missing `TYPESAFE_API_KEY` or an
API error degrades predictably: gates default to retrieve-both, router defaults
to `general`, rerank falls back to the LLM scorer (then cosine order),
dedup decisions default to ADD. No JEV outage can break a user-facing turn.

## Non-goals (this spec)

Sectors MCP/REST tools, citations, file uploads, multi-model routing,
frontend. The tool node, `tool_update` events, and router registry are the
deliberate seams where those attach.

## Build phases (each lands as one reviewed commit)

1. Scaffold — git/repo, deps, config, db session, compose, alembic, health.
2. Auth — users+threads models, JWT, login/refresh/logout/me, migration.
3. Memory — models+migration, embeddings, extractor, store, JEV rerank,
   Mem0-style pipeline, digests, memory endpoints.
4. Agent graph — state, context manager (JEV gates + summarization), JEV
   router, agent node, prompts.
5. Service + SSE — run registry, AgentService, chat/thread endpoints.
6. Verify — smoke test (login → stream → history), README, env docs.

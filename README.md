# sectors-agent

Backend groundwork for an agentic stock-analysis assistant — FastAPI + LangGraph + PostgreSQL/pgvector, with long-term memory, rolling context management, resumable SSE streaming, and TypeSafe JEV as the classifier for routing and retrieval decisions.

> Built for the Sectors Hackathon Indonesia 2026. The agent provides information and analysis only — it does not give financial advice or execute trades.

## Architecture

```
START → context_manager → router → agent ⇄ tools → END
```

- **context_manager** — one JEV call asks two parallel `Noul` gates (`needs_user_memory`, `needs_past_chats`) so chit-chat never pays for retrieval. Token counting (tiktoken) + a rolling chained summary (`summarized_upto` pointer; history is never trimmed).
- **router** — JEV `Choice` over registered workflows. Ships with `general` only; Sectors workflows register in `WORKFLOWS` later.
- **agent** — composes `system.md` + summary + recalled-memory + related-thread blocks into the system prompt per turn. `TOOLS` is the empty extension point for future Sectors tools.
- **JEV fallback** — every `jev_ask` returns `None` on missing key/failure; call sites degrade to LLM structured output or deterministic defaults, so a JEV outage never breaks a turn.

### Memory (Mem0-style)

Post-turn background task: extract `"User …"` facts (LLM, first-person pre-filter, sanitization) → SHA-256 hash dedup → pgvector cosine + Postgres `ts_rank` → RRF(k=60) → JEV `Score` fan-out rerank (LLM fallback) → JEV `Choice` dedup (`restates`/`refines`/`contradicts`/`unrelated` → NOOP/UPDATE+merge/DELETE+ADD/ADD) → per-user cap. Debounced per-thread digests power cross-thread recall.

### SSE runs

Detached producers keyed by thread: generation survives client disconnects. Each run holds a seq-numbered replay buffer — `GET /threads/{id}/stream?last_seq=N` replays missed events. `POST /threads/{id}/stop` cancels gracefully and checkpoints the partial answer. Global and per-user run caps; finished runs linger for replay then evict.

### Checkpoints

LangGraph `AsyncPostgresSaver` on a psycopg pool (pool size must exceed `STREAM_MAX_ACTIVE_RUNS` — enforced at startup). Full `messages` history + `summary`/`summarized_upto` per thread.

## Stack

Python 3.10+ · FastAPI · LangGraph · SQLAlchemy async (asyncpg) · psycopg pool · Alembic · Postgres 16 + pgvector · `typesafe-sdk` (JEV) · OpenRouter (`openai/gpt-5.6-luna` chat, `openai/text-embedding-3-small` embeddings) · `python-jose` JWT · slowapi · pytest.

## Quickstart

```bash
cd backend
cp .env.example .env          # fill SECRET_KEY, OPENROUTER_API_KEY, APP_* creds, TYPESAFE_API_KEY
docker compose up -d          # Postgres 16 + pgvector on localhost:5433
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

API docs: `http://localhost:8000/api/v1/docs` (hidden when `ENVIRONMENT=production`).

> **Windows note:** the app forces `WindowsSelectorEventLoopPolicy` — psycopg async can't run on the default Proactor loop.

## API surface

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/auth/login` | env-credential login → access+refresh JWT (auto-provisions user) |
| POST | `/api/v1/auth/refresh` | rotate token pair |
| POST | `/api/v1/auth/logout` | bump `token_version`, revoking all tokens |
| GET | `/api/v1/users/me` | current user |
| POST | `/api/v1/chat/stream` | start a turn → SSE (`token`/`done`/`stopped`/`error`, seq-numbered) |
| GET | `/api/v1/threads` | list threads |
| GET | `/api/v1/threads/{id}` | thread detail + checkpointed messages |
| GET | `/api/v1/threads/{id}/stream` | re-attach/replay (`?last_seq=N`) |
| POST | `/api/v1/threads/{id}/stop` | graceful stop, partial answer persisted |
| DELETE | `/api/v1/threads/{id}` | delete thread + checkpoints + digest |
| GET | `/api/v1/memories` | list remembered facts |
| GET | `/api/v1/memories/search?q=` | hybrid recall pipeline (vector+BM25+RRF+rerank) |
| DELETE | `/api/v1/memories/{id}` | delete a memory |

SSE events are JSON in `data:` lines: `{"seq": N, "type": "token|done|stopped|error", "data": ...}`.

## Testing

```bash
cd backend
docker compose up -d          # tests use a dedicated `sectors_agent_test` DB
pytest -q                     # 53 tests
```

## Layout

```
backend/app/
  core/        config, security(JWT), llm factory, jev client, exceptions, middleware, ratelimit
  db/          base, session
  models/      user, thread, memory, thread_digest
  schemas/     auth, chat, memory
  api/v1/      deps, endpoints/{auth, users, memory, chat}
  agent/       state, context(gates+summary), router(JEV), nodes, graph, runs, service
  memory/      embeddings, extractor, store, recall, pipeline, digests
  prompts/     system.md, summarize.md, extract.md
```

## Roadmap

- Register Sectors MCP/REST tools in `agent/nodes.TOOLS` + workflow entries in `agent/router.WORKFLOWS`
- Tool-call SSE event payloads (plumbing already exists)
- Frontend client

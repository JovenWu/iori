# sectors-agent

Backend for an agentic IDX market-analysis assistant — FastAPI + LangGraph + PostgreSQL/pgvector, with long-term memory, rolling context management, resumable SSE streaming, TypeSafe JEV as the classifier for routing and retrieval decisions, and a credit-aware Sectors API integration (17 tools over a permanent Postgres cache).

> Built for the Sectors Hackathon Indonesia 2026. The agent provides information and analysis only — it does not give financial advice or execute trades.

## Architecture

```
START → context_manager → router → agent ⇄ tools → END
```

- **context_manager** — one JEV call asks two parallel `Noul` gates (`needs_user_memory`, `needs_past_chats`) so chit-chat never pays for retrieval. Token counting (tiktoken) + a rolling chained summary (`summarized_upto` pointer; history is never trimmed).
- **router** — JEV `Choice` over `WORKFLOWS`: `general` vs `sectors_data` (IDX market-data questions). Falls back to `general` when JEV is down or answers an unregistered key.
- **agent** — composes `system.md` + current WIB time + workflow hint + summary + recalled-memory + related-thread blocks into the system prompt per turn. `TOOLS` binds the 17 Sectors tools.
- **JEV fallback** — every `jev_ask` returns `None` on missing key/failure; call sites degrade to LLM structured output or deterministic defaults, so a JEV outage never breaks a turn.

### Sectors integration (credit-aware)

Every tool call flows through a permanent Postgres cache (`sectors_cache` table, keyed by sha256 of path + canonical params — global, shared across users since market data is identical for everyone):

- **Permanent store, dynamic freshness** — entries never expire. On read, `is_stale` compares `fetched_at` against the last weekday 17:00 WIB refresh boundary (weekends skipped — IDX doesn't publish). Historical windows (`end < today`) promote to `HISTORICAL` and stay fresh forever; helper lists are `STATIC` (7d); news/filings are `NEWS` (30min). The agent sees `stale`, `fetched_at`, and current `now_wib` in every response and decides whether `refresh=true` is warranted.
- **Credit discipline in code** — symbols validated before any call (malformed tickers never reach the paid 404); `company_report` defaults to `["overview"]` not all 8 sections; `top_movers` to `1d` not 10 credit combos; structured screener `where` preferred over 3-credit `q`. 404s are cached (they cost a credit); 400/429/5xx never are.
- **Stale-if-error** — transport failure or a failed refresh (429/5xx) serves the stored entry flagged `stale_fallback` rather than erroring the turn.
- **Single-flight** — concurrent identical requests share one upstream call.
- **Billing reference** (docs.sectors.app): 2xx and 404 consume credits; 400/401/403/429/5xx are free. Per-section reports and per-classification rankings bill per part.

### Tools

| Tool | Endpoint | Credits |
|---|---|---|
| `sectors_screen` | `GET /v2/companies/` | 1 structured / 3 NL |
| `sectors_company_report` | `GET /v2/company/report/{symbol}/` | 1/section |
| `sectors_subsector_report` | `GET /v2/subsector/report/{slug}/` | 1/section |
| `sectors_quarterly_financials` | `GET /v2/financials/quarterly/{symbol}/` | 1/quarter |
| `sectors_daily_prices` | `GET /v2/daily/{symbol}/` | 1 |
| `sectors_idx_market_summary` | `GET /v2/idx-total/` | 1 |
| `sectors_most_traded` | `GET /v2/most-traded/` | 2 |
| `sectors_top_movers` | `GET /v2/companies/top-changes/` | 1/class×period |
| `sectors_foreign_flow` | `GET /v2/foreign-flow/{symbol}/` | 1 |
| `sectors_news` | `GET /v2/news/` | 1 |
| `sectors_broker_summary` | `GET /v2/broker-summary/{symbol}/` | 1 |
| `sectors_broker_top` | `GET /v2/broker-summary/{symbol}/top/` | 2 |
| `sectors_insider_filings` | `GET /v2/filings/` | 1 |
| `sectors_suspensions` | `GET /v2/suspensions/` | 1 |
| `sectors_corporate_actions` | `GET /v2/corporate-actions/` | 1/type |
| `sectors_listing_performance` | `GET /v2/listing-performance/{symbol}/` | 1 |
| `sectors_list_subsectors` | `GET /v2/subsectors/` | 1 |

### Memory (Mem0-style)

Post-turn background task: extract `"User …"` facts (LLM, first-person pre-filter, sanitization) → SHA-256 hash dedup → pgvector cosine + Postgres `ts_rank` → RRF(k=60) → JEV `Score` fan-out rerank (LLM fallback) → JEV `Choice` dedup (`restates`/`refines`/`contradicts`/`unrelated` → NOOP/UPDATE+merge/DELETE+ADD/ADD) → per-user cap. Debounced per-thread digests power cross-thread recall.

### SSE runs

Detached producers keyed by thread: generation survives client disconnects. Each run holds a seq-numbered replay buffer — `GET /threads/{id}/stream?last_seq=N` replays missed events. `POST /threads/{id}/stop` cancels gracefully and checkpoints the partial answer. Global and per-user run caps; finished runs linger for replay then evict.

### Checkpoints

LangGraph `AsyncPostgresSaver` on a psycopg pool (pool size must exceed `STREAM_MAX_ACTIVE_RUNS` — enforced at startup). Full `messages` history + `summary`/`summarized_upto` per thread.

### Aksi Korporasi (corporate-action copilot)

A dedicated LangGraph (`app/aksi/`) checks the user's saved holdings against the Sectors corporate-action calendar — rights issues (HMETD), dividends, warrants — and produces per-event figures, sourced findings, and a gated bilingual brief, streamed live over SSE and persisted as a replayable report. Every number comes from pure calculators (`calc.py`); the LLM may only gather cached context and write `{{placeholders}}`, while a deterministic + JEV gate rejects digits or advice language and falls back to templates. Replay mode (`as_of`) clamps every tool window to the analysis date so historical runs never peek ahead.

```
scan → load_pack → calculate → investigate → brief → finish   (brief loops back to load_pack per event)
```

## Stack

Python 3.10+ · FastAPI · LangGraph · SQLAlchemy async (asyncpg) · psycopg pool · Alembic · Postgres 16 + pgvector · `typesafe-sdk` (JEV) · OpenRouter (`openai/gpt-5.6-luna` chat, `openai/text-embedding-3-small` embeddings) · `python-jose` JWT · slowapi · pytest.

## Quickstart

```bash
cd backend
cp .env.example .env          # fill SECRET_KEY, OPENROUTER_API_KEY, APP_* creds,
                              #   TYPESAFE_API_KEY, SECTORS_API_KEY
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
| GET | `/api/v1/sectors/cache/stats` | cache entries, hits, credits saved (per endpoint) |
| DELETE | `/api/v1/sectors/cache` | flush the cache (returns count cleared) |
| GET/PUT | `/api/v1/aksi/holdings` | user's holdings (scope of checks) |
| POST | `/api/v1/aksi/check` | run a corporate-action check → SSE (`started`/`tool`/`event_found`/`numbers`/`finding`/`brief`/`budget`/`done`) |
| GET | `/api/v1/aksi/check/stream` | re-attach/replay a check (`?last_seq=N`) |
| POST | `/api/v1/aksi/check/stop` | stop the active check (partial report kept) |
| GET | `/api/v1/aksi/reports/latest` | latest report (`?mode=live|replay`) |
| GET | `/api/v1/aksi/reports/{id}` | one report |
| POST | `/api/v1/aksi/impact` | one holding's corporate-action figures, no LLM |

SSE events are JSON in `data:` lines: `{"seq": N, "type": "token|tool|done|stopped|error", "data": ...}` — `tool` events carry `{name, status: "call"|"done"}` so clients can render tool progress.

## Testing

```bash
cd backend
docker compose up -d          # tests use a dedicated `sectors_agent_test` DB
pytest -q                     # 83 tests
```

## Layout

```
backend/app/
  core/        config, security(JWT), llm factory, jev client, exceptions, middleware, ratelimit
  db/          base, session
  models/      user, thread, memory, thread_digest, sectors_cache
  schemas/     auth, chat, memory
  api/v1/      deps, endpoints/{auth, users, memory, chat, sectors}
  agent/       state, context(gates+summary), router(JEV), nodes, graph, runs, service
  memory/      embeddings, extractor, store, recall, pipeline, digests
  sectors/     client(httpx), freshness(WIB boundaries), cache(permanent), tools(17)
  prompts/     system.md, summarize.md, extract.md
```

## Roadmap

- Custom analysis agents/workflows — register in `agent/router.WORKFLOWS` + a hint in `nodes._WORKFLOW_HINTS`; tools import from `app.sectors.tools` and inherit the cache
- SGX/KLSE/mining tool coverage (same client → cache → tools pattern)
- Frontend client

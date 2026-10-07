# Scheduled Jobs — Design Spec

| | |
|---|---|
| Feature | **Scheduled jobs** — user-named recurring prompts, ChatGPT/Claude-style scheduled tasks |
| Track | Track 01 — AI Agents & Assistants: the **autonomous task execution** leg |
| Written | Wednesday 7 Oct 2026 (WIB), v2 — replaces the fixed "aksi check" schedule design |
| Hard constraint | Repo freezes **Thursday 8 Oct 23:59 WIB** — v1 deliberately minimal |
| Core insight | A job fires a **normal agent turn** on its own thread — `service.run_turn` verbatim — so routing, memory, tools, checkpointing, and live-reattach all work unchanged |

---

## 0. TL;DR

- **What:** the user creates named jobs — a prompt + a cadence (`daily` / `weekly` / `monthly` + WIB time). When due, the backend runs a full agent turn with that prompt on the job's own thread: the agent reasons, calls Sectors/aksi tools, and its answer lands in the thread like any chat reply.
- **Why it wins the track:** "the agent works while you're away" — *"I told it: every weekday at 17:00, check my holdings for new corporate actions"* — and next morning the job's thread sits on top of the sidebar with fresh findings. Autonomous execution, tool use, persistence, memory — the whole rubric in one feature.
- **Zero new plumbing:** job ↔ thread is 1:1. The run keys on the thread id, so `GET /threads/{id}/stream` live-attach, `has_active_run`, the replay buffer, and the `finishedRun` notifier all come free. The notification surface **is** the thread list bumping to Recent.
- **Credits:** a job's prompt can spend Sectors credits (whatever the agent calls). Mitigations: opt-in per job, one run per slot (errors don't retry until next slot), jobs can be paused, `run_turn` keeps the existing "keep calls cheap" hints.

## 1. Demo narrative

1. In chat: *"every trading day at 5pm, scan my holdings for new corporate actions and summarize what changed"* — the `schedule_create` tool saves the job, replies with next run time.
2. 17:00 next day: worker fires `run_turn` on the job's thread — the agent calls `aksi_check`/`sectors_*` tools, writes the answer.
3. User opens the app: job thread is on top of Recent with the new answer preview. Opens it → sees the full reasoning/tools/answer (or watches mid-run live via reattach).
4. `/schedules` lists all jobs with name, cadence, next run, enabled toggle.

## 2. Data model — `scheduled_jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `user_id` | int FK → users | indexed |
| `name` | varchar | shown in the list + becomes the thread title |
| `prompt` | text | the instruction sent as the agent turn's user message |
| `frequency` | varchar(7) | `"daily" \| "weekly" \| "monthly"` |
| `run_time` | time, default 17:00 | interpreted as **WIB** (fixed tz in v1) |
| `weekday` | smallint, null | weekly only — 0=Mon … 6=Sun |
| `day_of_month` | smallint, null | monthly only — clamped 1–28 (no month-end edge cases) |
| `enabled` | bool, default true | pause without deleting |
| `thread_id` | uuid FK → threads, unique | created when the job is; survives job deletion |
| `last_run_at` | timestamptz, null | stamped at fire time — an error does NOT retry same slot |
| timestamps | | via `TimeStampedBase` |

Validation: `weekly` requires `weekday`, `monthly` requires `day_of_month`, `daily` requires neither.

## 3. Scheduler worker — `app/agent/scheduler.py`

asyncio task in `main.py` lifespan (after `init_service`, cancelled on shutdown). No extra infra.

```
every SCHEDULER_TICK_SECONDS (default 60):
  due = jobs where enabled AND due_now(job, now_wib)
  for each due job (sequential — few users in demo):
    - stamp last_run_at FIRST  (never retry-loop an error)
    - if registry has a live run for the job's thread: skip this slot
      (user is mid-conversation on it — don't interleave)
    - run = registry.start_run(user_id, str(thread_id))
      run.task = asyncio.create_task(
          service.run_turn(run, user_id, str(thread_id), job.prompt, lang=None)
      )
      run.emit("started", {...})                      # same as chat_stream
```

`due_now(job, now_wib)`:

- `slot = today@run_time` (daily), `today@run_time if weekday matches` (weekly), `today@run_time if day == day_of_month` (monthly)
- due iff `now_wib >= slot` AND (`last_run_at` is null OR `last_run_at < slot`)

**Free wins from reusing the chat pipeline:** router routes the prompt (holdings prompt → `corporate_actions` → `aksi_check` works), JEV-judged memory feeds it, the answer checkpoints, `_post_turn` still extracts memories/titles, and a user who happens to be on the thread watches it stream live.

**Why the job's own thread (not a fresh thread per run):** runs accumulate → the thread reads as the job's history log; sidebar/history surface it by recency; no list clutter.

Config: `SCHEDULER_ENABLED`, `SCHEDULER_TICK_SECONDS=60`, `SCHEDULER_MAX_PER_TICK=5` (backpressure cap — leftover due jobs fire next tick).

## 4. API — `/api/v1/schedules`

| Method | Path | Notes |
|---|---|---|
| GET | `/schedules` | → list of the user's jobs: `{id, name, prompt, frequency, run_time, weekday, day_of_month, enabled, thread_id, last_run_at, next_run_at}` |
| POST | `/schedules` | `{name, prompt, frequency, run_time?, weekday?, day_of_month?}` → job + `next_run_at`; creates the backing thread |
| PATCH | `/schedules/{id}` | partial update — name/prompt/cadence/enabled |
| DELETE | `/schedules/{id}` | deletes the job; the thread **stays** (it holds real answers) |
| POST | `/schedules/{id}/run` | run now (stretch — great for demos: fire a job on stage) |

`next_run_at` computed in WIB at response time; creating at 18:00 with `run_time 17:00` → next run is tomorrow (stated explicitly in the response).

## 5. Chat tools — `app/agent/tools`-adjacent (schedule tools live in `app/aksi`-style module or a new `app/schedules/tools.py`)

Registered into `AGENT_TOOLS` so the agent manages its own jobs — the ChatGPT-tasks feel:

- `schedule_list` — the user's jobs + next run times.
- `schedule_create(name, prompt, frequency, run_time?, weekday?, day_of_month?)` — confirm back the cadence + next run.
- `schedule_update(job_id, ...)` — rename/rephrase/reschedule/pause.
- `schedule_delete(job_id)` — confirm it keeps the thread.

Router: the `corporate_actions` workflow or a `sectors_data` one doesn't own this — job prompts are topic-agnostic. Add "scheduled/recurring tasks — 'remind me', 'every day', 'each week', 'run X nightly'" to a workflow description (likely `general` gains tools for this, or `sectors_data` — decide: put schedule tools on `sectors_data` + `corporate_actions` since that's where useful jobs live; `general` stays tool-less).

**Prompt safety:** the agent should refuse to create a job whose prompt is a one-off question ("what's BBCA's price" is not a job) — the tool's docstring steers; the agent confirms cadence before creating.

## 6. Frontend

- **`/schedules` page** — job cards: name, prompt excerpt, cadence chip ("Daily 17:00", "Mon 09:00", "1st 08:00"), next run, enabled toggle, delete, link → thread. Create/edit form (name, prompt textarea, frequency select → conditional weekday/day-of-month, time input).
- **Sidebar**: "Schedules" menu item (CalendarClock is taken by Aksi — use e.g. `TimerIcon`/`AlarmClockIcon`). Job threads appear in Recent naturally — no special casing needed.
- **Job threads look like normal threads** — the scheduled user message gets a small "Scheduled" prefix/marker so the transcript reads clearly (message content prefixed `⏰`/`[Scheduled]` — or a `scheduled` flag on the message row if cheap).
- Badge: none needed — thread bump is the notification. (Stretch: unread marker later.)

## 7. Failure & edge cases

- **Worker/deploy restart mid-run** — the run is a detached registry run; a hard restart kills it — the job's thread keeps whatever checkpointed (same semantics as a chat turn cut mid-flight). `last_run_at` already stamped → next slot only.
- **Job fires while user is chatting on the same thread** — registry lock: live run present → slot skipped.
- **Two jobs same minute** — sequential per tick, capped by `SCHEDULER_MAX_PER_TICK`.
- **Job deleted mid-run** — deleting a job doesn't kill its in-flight turn; the answer still lands in the (now-orphaned) thread.
- **Monthly clamping** — `day_of_month` limited to 1–28 so February never misses.
- **Credits** — one agent turn per slot; prompts that route `general` cost nothing; data prompts spend whatever tools fire — the run inherits the existing cheap-call guidance.

## 8. Testing

- `test_due_now_daily/weekly/monthly` — slot math, weekday/month-day matching, last_run_at dedup, late-create waits for next slot.
- `test_tick_fires_agent_turn` — mock `run_turn`; assert started event, run keyed on the job's thread.
- `test_skip_when_thread_run_live`.
- `test_job_crud_and_validation` — weekly needs weekday, monthly needs day_of_month≤28, auth scoping.
- `test_schedule_tools_roundtrip` — create via tool → job row + thread exist.
- No Sectors calls in scheduler tests (mock `run_turn`).

## 9. Build order (fits the freeze)

1. Model + migration + store CRUD + due-math (pure, fully testable).
2. REST API + worker loop in lifespan.
3. Chat tools (agent creates its own jobs — the demo beat).
4. `/schedules` page + sidebar entry.
5. Stretch: `POST /schedules/{id}/run` (demo-time live fire), "Scheduled" message marker.

Cut lines: §5 chat tools first if the clock slips — but they're ~100 lines and carry the demo, so build them before the page if choosing.

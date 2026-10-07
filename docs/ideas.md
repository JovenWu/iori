# Flagship idea list

Candidates for the main showcase feature (AI Agents & Assistants track). Each must include custom agent orchestration around the model, use Sectors data as the core source, and never give financial advice or execute trades.

**Filter:** an idea only qualifies if it needs something the current chat agent structurally cannot do — it is request/response, has no schedule, no memory of market state over time, no external inputs, and cannot reach the user outside the app. "A good question the chat agent can already answer, behind a new UI" does not count.

---

## A. Tip Investigator ("Gorengan Radar") — status: section 1 of design approved

### Problem

Retail investors in Indonesia keep buying into *saham gorengan* (pumped, thinly traded stocks), often after a tip in a Telegram/Stockbit/X group. IDX protections (UMA notices, suspensions, special-monitoring board) arrive after the spike. The warning signs sit in public data — broker concentration, low free float, shareholder shifts, insider selling, moves without news — but connecting them takes hours of manual bandarmology.

### Pitch

Paste a tip (text, screenshot, ticker, or link). The agent extracts the tickers and the tip's claims, fact-checks each claim against Sectors data, and runs a forensic pump-risk investigation — producing a Case File where every piece of evidence cites its source.

### Decisions so far

- **Entry point:** on-demand investigation of a tip. A daily Radar scan is an optional add-on that feeds tickers into the same Investigator.
- **Inputs:** tip text, screenshot (vision model), ticker, or social link (best-effort: public Telegram posts and generic pages; X/Stockbit/IG/TikTok fall back to "paste text or screenshot").
- **UI:** dedicated "Check a tip" page — drop zone → live investigation → Case File view → saved cases list.
- **Approach:** dedicated investigation graph with structured case state, credit budget, and claim verification (not a chat prompt, not a fixed pipeline).

### Design section 1 — architecture & data flow (approved)

New `app/investigate/` package, separate from chat:

```
START → intake → plan → gather ⇄ tools → assess → verdict → END
                   ↑__________________|   (loop until enough evidence or budget spent)
```

- **intake** — normalize input to `{tickers[], claims[]}`. Text → LLM structured output; screenshot → vision model → same; link → server-side fetch (Telegram `?embed=1`, generic readability, SSRF guard); ticker → direct.
- **Claim types** (enum) mapped to evidence:
  - `foreign_accumulation` → `foreign_flow`
  - `bandar_accumulation` → `broker_top` / `broker_summary`
  - `insider_buying` → `insider_filings` / `shareholders`
  - `corporate_action` → `company_corporate_actions`
  - `earnings_growth` → `quarterly_financials`
  - `news_catalyst` → `news`
  - `price_target` → flagged as opinion / unverifiable
- **plan** — JEV `Choice` orders hypotheses from the claims plus the standard pump-risk checklist.
- **gather ⇄ tools** — agent calls existing `sectors_*` tools (inherits the cache). After each result, a pure-Python signal extractor turns raw data into a **finding** (signal, value, source call, date). JEV `Noul` "enough evidence to conclude?" gates each loop, allowing an early "likely organic" exit. Hard caps: credit budget (default 25) and max steps.
- **assess** — each claim becomes `supported | contradicted | unverifiable`.
- **verdict** — JEV `Score` → risk tier + confidence; LLM writes a short bilingual summary grounded only in findings.
- **Multi-ticker tips** — investigate the primary ticker; the others are listed with an "Investigate" button to protect the budget.

**Reused:** sectors tools + credit-aware cache, `jev_ask` with fallbacks, `RunRegistry` (keyed by `case_id`), chart specs.

**New:**
- `cases` table — `id, user_id, input_kind, raw_input, tickers, status, case JSONB, credits_spent, created_at`. Written incrementally so stopped cases keep partial evidence.
- Endpoints — `POST /cases` (create + SSE), `GET /cases`, `GET /cases/{id}`, `GET /cases/{id}/stream?last_seq=`, `POST /cases/{id}/stop`.
- SSE events — `intake`, `step`, `finding`, `claim`, `budget`, `verdict`, `done`, `error` (plus existing `tool`, `chart`).

### Evidence signals (draft)

| Question | Source |
|---|---|
| Is the move abnormal for this stock? | `daily_prices`, `company_report` |
| Is buying concentrated in a few brokers? | `broker_top` (cohort-aware) |
| Who are they — retail, institutional, foreign? | `broker_registry` |
| Did they accumulate quietly before the spike? | `broker_summary` |
| Is the float thin? | `free_float` |
| Did shareholder composition shift? | `shareholders` |
| Are insiders selling into the rally? | `insider_filings` |
| Does news or a corporate action explain it? | `news`, `company_corporate_actions` |
| Prior suspensions, and why? | `suspensions` |

### Demo hook

Replay real past suspensions: run the Investigator "as of" a date before IDX suspended the stock and show the Case File flagging it days earlier. 3–5 such backtests double as an evaluation slide.

### Risks

- **Legal framing** — never "manipulated" or accusing a broker; use "pattern consistent with…" and "risk signals", plus a disclaimer.
- **Historical broker-data depth** — needs a data spike around real suspension dates before committing to the backtest demo.
- **Credits** — ~10–20 per case; mitigated by the cache and a visible per-case budget.
- **False positives** — news-driven rallies; handled by the "likely organic" exit and confidence score.

### Remaining design sections

2. Signals & scoring · 3. Case File UI · 4. Error handling & testing

---

## B. Thesis Guardian — status: unexplored

The user writes why they hold a stock ("BBRI: NIM stable, foreign inflow, dividend yield > 5%"). JEV decomposes it into measurable claims; the agent autonomously re-checks each against Sectors data after every close and alerts when a claim breaks. Strong on memory and autonomy; counters confirmation bias. Less visual.

## C. Smart-Money Tracer — status: unexplored

Pick a broker (e.g. a foreign institutional one); the agent traces what it has been accumulating across the market, cross-checks with foreign flow and sector moves, and explains the pattern. Narrower; could become a module of A.

## D. A + B combined — status: unexplored

Thesis Guardian watches holdings and escalates to the Tip Investigator when an alarm fires. Best story, largest scope.

## E + F. The Standing Committee — status: not selected (Aksi Korporasi shipped instead — phase 14)

> "An investment committee that keeps meeting after you close the app."

- Committee (F) researches and debates a ticker; the chair memo ends with **falsifiers** ("what would change our view") expressed as testable conditions.
- Falsifiers compile into **Watch Rules** (E), evaluated after each close.
- A triggered rule raises an **in-app alert** and **reconvenes the committee**, which updates the memo.
- **Delivery decision:** in-page web alerts only — no Telegram bot.
- **Rule sources:** both — committee falsifiers become *proposed* rules (user confirms), and users can write their own NL rules on a covered ticker.
- **Risk seat:** runs idea A's pump-risk forensics (broker concentration, free float, shareholder shifts, insider selling, suspensions, news-vs-move).

### Design section 1 — architecture & flow (drafted, paused before approval)

**Concepts**
- **Coverage** — a ticker the user has asked the committee to follow. Owns a versioned **memo**, a set of **watch rules**, and an **alert feed**.
- **Session** — one committee meeting: `convene` (first, user-started) or `reconvene` (alert-started; reviews only what the alert changed).

**Committee graph** (new `app/committee/`)

```
START → brief ─┬→ bull_research ─┐
               ├→ bear_research ─┼→ gate → debate(round 1..N) → gate → chair → rules → END
               └→ risk_research ─┘
```

- **brief** — shared fact pack fetched once (company report, recent prices, subsector) so seats don't re-pay for it.
- **Seats** — parallel agent ⇄ tools loops over existing `sectors_*` tools, each with its own tool allowlist and credit budget. Output: **claims**, each citing a finding from the pure-Python signal extractor.
  - Bull — growth, earnings, foreign inflow, sector strength.
  - Bear — valuation, earnings deterioration, outflows.
  - Risk — pump-risk checklist from idea A.
- **gate** — JEV judges each claim against its cited finding: `supported | overstated | unsupported`. Unsupported claims are struck from the record.
- **debate** — each round, every seat picks the strongest surviving opposing claims to rebut; rebuttals may trigger new tool calls within budget. Re-gated after every round. JEV `Noul` "converged?" ends early; max 2 rounds.
- **chair** — memo: case for, case against, disputed points, open questions, and **falsifiers**. No stance, no rating.
- **rules** — each falsifier compiles into a typed Watch Rule as a *proposal*.

**Watch system** (new `app/watch/`)
- **Rule compiler** — NL (user or falsifier) → typed rule `{subject, metric, op, threshold, window, streak}` over a fixed metric vocabulary. JEV `Choice` asks for clarification when ambiguous; inexpressible rules are rejected with a reason. Each rule shows an estimated daily credit cost.
- **Evaluator** — in-process scheduler after the 17:00 WIB weekday boundary, plus a "Run evaluation now" button. Groups all active rules by data need, fetches each dataset once through the cache, evaluates all. **Replay mode** runs the evaluator over past trading days for the demo.
- **Trigger** — persists an alert (condition, observed value, short agent explanation), pushes to the in-app alert feed over SSE, and optionally reconvenes the committee (debounced: max once per ticker per day).

**Persistence** (new tables)
- `coverage` (user, ticker, created_at)
- `committee_sessions` (coverage, kind, trigger_alert, status, transcript JSONB, credits_spent)
- `memos` (coverage, session, version, content JSONB)
- `watch_rules` (coverage, source user|falsifier, text, compiled JSONB, status proposed|active|paused)
- `alerts` (rule, fired_at, observed JSONB, explanation, read)

**API**
- `POST /coverage/{ticker}/convene` (SSE)
- `GET /coverage`, `GET /coverage/{ticker}` (memo + rules + alerts)
- `/rules` CRUD, `POST /rules/compile` (preview)
- `POST /watch/evaluate?replay_days=`
- `GET /alerts`, `GET /alerts/stream`
- Committee SSE events: `seat_step`, `claim`, `gate`, `round`, `memo`, `rule_proposed`, `budget`, `done`

### Remaining design sections

2. Claims, gating & rule metric vocabulary · 3. UI (coverage board, committee room, alert feed) · 4. Error handling, credit budgets & testing

## E. Natural-language Watch Rules — status: merged into E + F

The user writes rules in plain language ("alert me if foreign net-sells BBRI 3 days in a row", "any insider selling in banks", "if a stock I hold gets UMA/suspended"). The agent compiles each rule into a typed, inspectable condition over Sectors data (shown back to the user for confirmation), a scheduler evaluates rules after each close, and when one fires the agent investigates *why* and delivers an explained alert via a Telegram bot. Why the chat agent can't: no schedule, no persisted conditions, no way to reach the user outside the app. Shares machinery with B (Thesis Guardian).

## F. Multi-agent Investment Committee — status: merged into E + F

Bull, bear, and risk agents research independently with separate credit budgets, then debate in rounds; a chair agent writes a memo that preserves dissent. Visibly agentic; the pattern is common at hackathons, so differentiation must come from the IDX-specific angle and the debate mechanics.

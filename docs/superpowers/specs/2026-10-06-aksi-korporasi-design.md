# Aksi Korporasi Copilot — Full Product & Technical Spec

> **Superseded — built.** The feature shipped as the `/action` route (this doc
> says `/aksi`) with the current endpoint set and layout; some details below
> (Python version, endpoint paths, component layout) no longer match the code.
> Kept for design rationale only — the README and implementation plan are
> authoritative.
>
> Implementation plan: `docs/superpowers/plans/2026-10-06-aksi-korporasi.md`.

| | |
|---|---|
| Working name | **Aksi Korporasi Copilot** (brand candidates: **JagaHak** — "guard your rights", a pun on HMETD = *hak*; **Kawal Aksi**) |
| Event | Sectors Hackathon Indonesia 2026 · Track 01 — AI Agents & Assistants |
| Written | Tuesday 6 Oct 2026 (WIB) |
| Deadline | Thursday 8 Oct 2026, 23:59 WIB — repo freezes on submission |
| Codebase | `D:\Joven Kuliah\Hackhathon\Sectors-3.0` (FastAPI + LangGraph backend, Next.js 16 frontend) |
| Status | **Approved by the team — building.** First task is the ~13-credit data check (§18.2) |

---

## Table of contents

0. [TL;DR](#0-tldr)
1. [Problem statement and pitch](#1-problem-statement-and-pitch)
2. [The problem in detail](#2-the-problem-in-detail)
3. [Evidence that the problem is real](#3-evidence-that-the-problem-is-real)
4. [Why now](#4-why-now)
5. [Existing solutions and the gap](#5-existing-solutions-and-the-gap)
6. [Why this idea wins](#6-why-this-idea-wins)
7. [Users and jobs-to-be-done](#7-users-and-jobs-to-be-done)
8. [Scope](#8-scope)
9. [User experience and flows](#9-user-experience-and-flows)
10. [Data: Sectors endpoints](#10-data-sectors-endpoints)
11. [Calculation engine](#11-calculation-engine)
12. [Agent architecture](#12-agent-architecture)
13. [Backend implementation](#13-backend-implementation)
14. [Frontend implementation](#14-frontend-implementation)
15. [Implementation plan and timeline](#15-implementation-plan-and-timeline)
16. [Testing and verification](#16-testing-and-verification)
17. [Demo and video plan](#17-demo-and-video-plan)
18. [Risks, data checks, kill criteria](#18-risks-data-checks-kill-criteria)
19. [Appendix](#19-appendix)

---

## 0. TL;DR

- **What:** an agent that watches the corporate actions (rights issues/HMETD, dividends, warrants, stock splits, bonus shares) of the stocks a user **already holds**, and for each event explains **what it means for that user's own position**, in rupiah and in days, with sourced context.
- **Why it matters:** rights left unexercised or unsold **expire worthless** and the holder is diluted (WIFI's 2025 rights issue: up to **55.56 %** dilution for anyone who did nothing). Dividends are lost by buying after the cum date. Broker apps show the **dates**; nobody computes the **personal consequence**.
- **How it's agentic:** detect events against holdings → plan and run an investigation over Sectors data (controller's insider filings, ownership shifts, price vs exercise price, the company's past actions) → **deterministic** calculators produce every number → an LLM writes a bilingual brief that may only reference those numbers → a JEV gate rejects advice-shaped or ungrounded text → persisted report + deadline alerts.
- **Why it wins:** unanimous pick of 4 independent judges in a blind final round (avg **8.6/10** vs 7.9 for the runner-up); independently invented by 5 separate agents; no competing hackathon repo covers it; data is already wrapped in the repo; POJK-6/2026-safe by construction (numbers and deadlines, never "buy/sell/exercise").
- **Effort:** ~22–28 focused hours. Fits the deadline with time left for the videos if scope is cut as in §8.

---

## 1. Problem statement and pitch

**One-sentence problem statement (submission field):**
> Indonesian retail investors keep losing money on corporate actions they technically saw coming — rights that expire worthless, dilution they didn't calculate, dividends missed by a day — because apps show the dates but nobody tells them what each event means for *their* shares; Aksi Korporasi Copilot watches their holdings and does exactly that, with every number sourced from Sectors data.

**Elevator pitch (10 seconds, video hook):**
> *"Every year, Indonesian investors lose money not to bad stocks, but to deadlines they never understood."*

**Indonesian version:**
> *"Setiap tahun investor ritel rugi bukan karena salah pilih saham, tapi karena tenggat aksi korporasi yang tidak mereka pahami."*

---

## 2. The problem in detail

### 2.1 What a corporate action does to a holder

| Action | What the holder must understand | What goes wrong |
|---|---|---|
| **Rights issue (PMHMETD / HMETD)** | Entitlement (how many rights), exercise price, cost to exercise, theoretical ex-rights price (TERP), value of the rights, dilution if ignored, trading/exercise window, deadline | Rights not exercised or sold by the end of the period are **void** ("dinyatakan tidak berlaku lagi") and removed from the account **without compensation**; the holder is diluted |
| **Cash dividend** | Cum date (last day to buy to be entitled), ex date, recording date, payment date, gross amount for *their* shares | Buying on/after the ex date → no dividend; confusion between cum/ex/recording dates |
| **Warrant** | Exercise price, ratio, exercise period, maturity, whether it is in/out of the money | Warrants expire worthless at maturity |
| **Stock split / reverse split** | New share count, adjusted price, odd-lot consequences | Panic at "price dropped 90 %" that is just a split; odd lots after reverse splits |
| **Bonus shares** | Number of bonus shares, dates | Misreading the ratio |

### 2.2 Why it is hard for a retail holder today

1. **Information is scattered and legalistic.** Prospectus PDFs and IDX announcements describe schedules in dense legal Indonesian (cum/ex for the regular *and* the cash market, DPS, SBHMETD distribution, trading period, exercise period).
2. **The arithmetic is non-trivial.** Entitlement rounding, TERP, the theoretical value of a right, dilution and break-even all require a formula most beginners don't know.
3. **The window is short.** WIFI's 2025 rights could be traded/exercised for **7 trading days** (7–15 July 2025). BBRI's 2021 rights issue ran for **8 working days**.
4. **Context matters and is hard to find.** Is the controlling shareholder putting in fresh money or not? Is the exercise price above or below the market? What happened after this company's previous rights issue?
5. **Apps show dates, not consequences.** See §5.

### 2.3 A concrete example (real event, illustrative position)

**WIFI (PT Solusi Sinergi Digital Tbk) rights issue, July 2025** (sources in §19.1):
- Ratio **4 : 5** — each holder of 4 old shares receives 5 HMETD; 1 HMETD = right to buy 1 new share at **Rp2,000**.
- Cum date (regular market) **1 Jul 2025**, ex date **2 Jul**, recording date **3 Jul**, trading/exercise period **7–15 Jul 2025**.
- Up to **2.95 billion** new shares, **Rp5.89 trillion**; holders who do not exercise are diluted by up to **55.56 %**.
- Controlling holder PT Investasi Sukses Bersama committed to exercise **1.48 billion HMETD (≈Rp2.97 T)**.

A holder of **10 lots (1,000 shares)** at an illustrative cum price of Rp3,000 receives **1,250 HMETD**, needs **Rp2,500,000** to exercise them all, and the theoretical value of those rights is **≈Rp555,556**. That amount is lost if they do nothing (worked out in §11.3). That is the screen this product produces in seconds.

---

## 3. Evidence that the problem is real

All figures below were checked against the cited sources on 6 Oct 2026.

| # | Evidence | Source |
|---|---|---|
| E1 | Unexercised HMETD become void after the exercise period ends ("HMETD yang tidak dilaksanakan hingga tanggal akhir periode tersebut dinyatakan tidak berlaku lagi") | BBRI 2021 prospectus (bri.listedcompany.com) |
| E2 | Unexercised HMETD are removed from the securities account automatically **without compensation**; "those who do nothing lose both" (ownership share and cash compensation) | radarpasar.com rights-issue guide |
| E3 | Retail forums regularly carry stories of investors who forgot to exercise and lost their rights | idxstock.com rights-issue guide |
| E4 | Even in Southeast Asia's largest rights issue (BBRI 2021), **7.33 billion HMETD were still unexercised the day before the deadline**; final exercise was 97.4 %, i.e. ~2.6 % of rights lapsed | CNBC Indonesia (22 Sep 2021); Bisnis (24 Sep 2021) |
| E5 | **14 rights issues raising Rp34.47 T** on IDX in 2025 (Rp34.41 T in 2024) — large-ticket, recurring events | Bisnis (26 Dec 2025, quoting IDX) |
| E6 | KSEI handled **4,727 corporate actions**, including **391 dividend distributions**, between 1 Jan and 8 Aug 2025 | VIVA (11 Aug 2025, quoting KSEI) |
| E7 | **31.90 million** capital-market investors (SID) at end-Sep 2026; **10.05 million** stock investors (Aug 2026); +9.9 M SIDs in 2026 alone | Pantau / Koran Jakarta (1 Oct 2026); Liputan6 (9 Aug 2026) |
| E8 | WIFI 2025: holders who did not exercise were diluted by **up to 55.56 %** | EmitenNews; IDX Channel |
| E9 | New **15 % minimum free float** (IDX Rule I-A, effective 31 Mar 2026) with tiered deadlines to 2029 → issuers below 15 % must create float, typically via rights issues or placements | KSEI press release (8 Apr 2026); Bisnis (1 Apr 2026); Kompas (27 Apr 2026) |
| E10 | POJK 6/2026: giving "recommendations" to own or not own a capital-market product requires an investment-adviser licence → a tool must explain, never recommend | OJK press release + FAQ |
| E11 | Stockbit's Calendar lists corporate-action **dates**; its in-app corporate-action marker only appears from one day before to one day after the event | Stockbit help centre |

**Reading of the evidence:** the harm is real and recurring (E1–E4, E8), the volume is large (E5–E7), the next two years will bring more such events (E9), the incumbents show schedules but not consequences (E11), and regulation rewards an explain-don't-recommend design (E10).

---

## 4. Why now

1. **The free-float reform creates a wave of supply-side corporate actions.** From 31 Mar 2026, listed companies must reach 15 % free float:
   - market cap ≥ Rp5 T and float < 12.5 % → 12.5 % by **31 Mar 2027**, 15 % by **31 Mar 2028**;
   - market cap ≥ Rp5 T and float 12.5–15 % → 15 % by **31 Mar 2027**;
   - market cap < Rp5 T → 15 % by **31 Mar 2029**.

   Rights issues and placements are standard ways to comply, so retail holders of these names will face exactly the events this product explains.
2. **Investor base exploded.** +9.9 M SIDs in the first seven months of 2026; most of these investors have never been through a rights issue.
3. **Regulation favours this design.** POJK 6/2026 draws a hard line between information and recommendation. This product sits on the right side by construction: arithmetic, dates and sourced facts, never "should".
4. **The data just became available.** Sectors added per-ticker corporate actions, shareholder composition and the broker/insider endpoints in June 2026 (v2 changelog, 2026-06-12). The calendar returns exercise price, ratios and all key dates.

---

## 5. Existing solutions and the gap

| Solution | What it does | What it doesn't do |
|---|---|---|
| **Stockbit Calendar / Corporate Action page** | Lists dividends, splits, rights issues, warrants, bonus, tender offers, RUPS with dates; a "C" marker near the ticker around the event | No entitlement for *your* shares, no cost/TERP/dilution, no deadline countdown tied to your portfolio, no context (controller participation, past actions); marker visible only ±1 day |
| **Broker notifications / e-mails** | Generic announcements; some brokers send exercise instructions | Not computed per holder; no context; varies by broker |
| **IDX / KSEI announcements, prospectus PDFs** | Authoritative schedule and terms | Legal language; no personal arithmetic |
| **Generic AI chatbots** | Can explain "what is a rights issue" | No reliable live data; mental arithmetic errors; risk of advice language |
| **Other hackathon entries seen** (public repos) | Tip fact-checkers, pump/gorengan detectors, distress warning-sign replays with custom alarms (one uses dilutive rights issues only as a *warning signal*), general research agents | **None** computes the personal impact of corporate actions on a holder's position |

**The gap:** *personal, deadline-driven, sourced consequence of a corporate action for the shares I hold*. Dates are a commodity; consequences are not.

---

## 6. Why this idea wins

### 6.1 How it was selected

| Round | What happened | Result |
|---|---|---|
| 1 | 4 independent judge agents (usability, video, technical, contrarian) scored all ideas from the two idea docs | All picked the tip investigator ("Gorengan Radar") |
| Saturation check | Searched public GitHub repos for this hackathon | ≥ 6 teams already in the tip/gorengan/bandar space, one with the identical product → idea A dropped |
| 2 | 4 fresh judges with the competitor list, each required to invent new ideas | **All four independently invented the corporate-action idea**; it was in every judge's top 2 |
| 3 | 4 researchers explored outside the docs (investor pain & 2026 events, non-retail users, underused Sectors data, global agent patterns) | 9+ new ideas; the global-patterns researcher independently re-invented this idea (5th agent) |
| Final (blind) | 4 judges scored a 7-idea shortlist presented in random order, without knowing which was the favourite | **Unanimous #1**, avg weighted score **8.6** |

Final-round averages (weighted 0.4 usability + 0.3 video + 0.3 technical):

| Idea | Avg | Note |
|---|---|---|
| **Aksi Korporasi Copilot** | **8.6** | #1 for all four judges |
| Mining license early warning ("Kadal Izin") | 7.9 | Most distinctive data, but 30–38 h build and ticker↔mining-entity resolution risk |
| Free-float / MSCI exposure tracker ("Pengawal Float") | 7.7 | Timely, but free float is current-only → a snapshot, thin agent role |
| Thesis Guardian | 7.3 | Overlaps research agents; replay easy to fake |
| Thesis research copilot ("SkripsiLab") | 6.5 | Commodity data use, payoff is a dataset |
| Finfluencer compliance studio | 6.2 | Sectors data decorative |
| Sharia watch | 6.2 | Mature competitors; no sharia-list endpoint |

### 6.2 Fit to the official rubric

| Criterion (weight) | How this idea scores |
|---|---|
| **Real-world usability (40 %)** — "can someone use it today and benefit?" | Yes: enter holdings → see money and deadlines at stake today. The pain is documented (E1–E8); the user base is 10 M stock investors (E7) |
| **Video & storytelling (30 %)** | A single memorable screen: *"Ignore = −55.56 % ownership. Exercise = Rp2.5 jt by 15 Jul."* Countable in rupiah and days; emotionally obvious; honest (real event) |
| **Technical depth (30 %)** — "innovative use of Sectors API, real not faked" | Uses Sectors' distinctive Indonesian datasets (corporate-action calendar with ratios/prices, insider filings with % before/after, monthly shareholder composition, free float) joined by an agent; deterministic calculators are unit-tested and verifiable in the repo; all tool calls visible live |
| **Track bar (AI Agents & Assistants)** | Multi-step tool pipeline, state/memory (holdings, reports), autonomous per-event investigation, purpose-built interface — not a prompt on someone else's client |
| **Hard rules** | Sectors data is the core (remove it → nothing works); no advice (gate enforces); no trading |

### 6.3 What the Sectors team gets to show off
"Our corporate-actions and filings data turned into personal, verifiable decisions support for 10 M retail investors": a showcase for endpoints released in 2026.

---

## 7. Users and jobs-to-be-done

### 7.1 Primary user
**Retail holder** of 2–15 IDX stocks, 1–3 years of experience, uses a broker app (Stockbit/Ajaib/IPOT/etc.), checks the market a few times a week, Indonesian-first.

*Illustrative persona:* **Rina, 27, office worker in Jakarta.** Holds 6 stocks (2–30 lots each). Got burned once when rights she didn't understand disappeared from her account. Wants to know, without reading a prospectus: "Do I need to do anything, by when, and what does each choice cost me?"

### 7.2 Secondary users
- **Dividend investors** — want exact gross amounts and cum dates across their portfolio.
- **Newer investors who arrived in 2026** — first time facing a split, bonus or rights issue.
- **Financial educators / community admins** — use the explanations (not recommendations) for teaching.

### 7.3 Jobs-to-be-done
1. "When one of my stocks announces a corporate action, tell me **if it affects me, how much, and by when**."
2. "Show me the **numbers for each choice** (exercise, sell rights, do nothing) for **my** share count, without telling me what to do."
3. "Tell me **what the people who control the company are doing** around this event."
4. "Let me **check the source** of every number."
5. "Remind me **before** the window closes."

---

## 8. Scope

### 8.1 P0 — must ship for the demo
- Holdings management: add/edit/remove ticker + share count (lembar; lot helper ×100).
- **"Cek aksi korporasi" run** (manual trigger), streamed live with visible tool steps.
- Event detection for holdings via the corporate-actions calendar: **rights issue, upcoming dividend, dividend (recent), warrant**.
- Deterministic calculators for rights issues and dividends (§11); warrants as basic (entitlement, exercise price vs current price, dates).
- Base context pack per event: company ownership section, insider filings around the event, shareholder composition (current + previous year), daily prices (≤ 90 days).
- LLM brief (ID + EN) restricted to placeholders → numbers come only from calculators.
- Gate: deterministic digit/banned-phrase check + JEV advice/grounding check (with fallback).
- Event cards with numbers grid, deadline timeline, context points with evidence chips, evidence drawer (raw fields, formulas, `fetched_at`), disclaimer.
- **Historical replay mode** (`as_of` date) — clearly labelled; enables an honest demo on WIFI July 2025.
- Report persistence (latest report reload).
- Sidebar navigation entry + upcoming-deadline badge.

### 8.2 P1 — if time allows (in order)
1. Chat integration: `corporate_actions` router workflow + `aksi_impact` tool (ask in chat, get exact numbers).
2. "Discuss in chat" button on event cards (prefilled message).
3. "What happened next" panel in replay mode (price after ex date vs TERP; controller filings after the window).
4. Free-float status chip (current float vs 15 %, tier deadline) — "why now" context.
5. Stock split / bonus calculators.
6. Paste-to-import holdings ("BBRI 10 lot, WIFI 500 lembar") via structured output.
7. Scenario row "fund exercise by selling part of the rights (theoretical, cash-neutral)".

### 8.3 P2 — after the hackathon
Scheduled daily check after 17:00 WIB with in-app inbox; Telegram/e-mail delivery; broker CSV import; tender offers & private placements (need sources Sectors doesn't expose yet); multi-user sharing.

### 8.4 Non-goals
- Any recommendation ("tebus/jangan tebus", "layak", "buy/sell/hold").
- Tax advice (show **gross** dividends; point to DJP rules).
- Order placement or broker integration.
- Predicting prices.

---

## 9. User experience and flows

### 9.1 Entry points
1. **Sidebar → "Aksi Korporasi"** (new nav item above the thread list, with a badge = number of events whose deadline is ≤ 7 days away in the latest report).
2. **Chat** (P1): questions like *"WIFI rights issue, saya punya 10 lot, artinya apa buat saya?"* route to the `corporate_actions` workflow, which calls `aksi_impact`.
3. **Event card → "Tanya di chat"** (P1) opens a new chat with a prefilled message containing ticker, event and share count.

### 9.2 Flow A — first-time setup
1. User opens `/aksi`. Empty state: *"Masukkan saham yang kamu pegang. Kami pantau aksi korporasinya dan hitung dampaknya untuk posisimu."*
2. User adds rows: `Ticker` (4 letters, validated; autocomplete optional), `Jumlah` (lembar, or toggle to lot), optional `Harga rata-rata`.
3. **Save** → `PUT /aksi/holdings`. Holdings persist per user.
4. Primary button **"Cek aksi korporasi"** (lavender) becomes active.

### 9.3 Flow B — run a check (live)
1. Click **"Cek aksi korporasi"** → `POST /aksi/check` (SSE).
2. The Spark status line narrates the run (same component as chat): *"Checking corporate actions… · Fetching insider filings WIFI · Computing · Writing brief…"*, with the step rail behind the chevron and a credit meter (`credits 7/25`, mono).
3. Events stream in as **skeleton cards** (`event_found`), then fill: numbers (`numbers`), context points (`finding`), brief (`brief`).
4. Run ends (`done`) → report saved; the badge updates.
5. **No events** → calm empty result: *"Tidak ada aksi korporasi untuk sahammu dalam 30 hari terakhir dan 60 hari ke depan."* plus the scan window and data timestamp.

### 9.4 Flow C — read an event card

```
┌──────────────────────────────────────────────────────────────────────────┐
│ WIFI · Rights issue (HMETD)                     4 hari lagi · 15 Jul 2025 │
│ Rasio 4 : 5 · Harga pelaksanaan Rp2.000                                   │
├──────────────────────────────────────────────────────────────────────────┤
│  HMETD kamu        Dana untuk tebus semua   TERP (teoretis)   Jika hangus │
│  1.250             Rp2.500.000              Rp2.444           −Rp555.556  │
│                                                               kepemilikan │
│                                                               −55,56 %    │
├──────────────────────────────────────────────────────────────────────────┤
│  1 Jul ───── 2 Jul ───── 3 Jul ───── 7 Jul ══════ 15 Jul                 │
│  Cum         Ex          Recording   Perdagangan & pelaksanaan HMETD     │
│                                          ▲ hari ini                       │
├──────────────────────────────────────────────────────────────────────────┤
│  Tiga skenario (teoretis, sebelum biaya transaksi):                       │
│  • Tebus semua:  2.250 saham, porsi kepemilikan tetap                    │
│  • Jual HMETD:   terima ±Rp555.556, porsi turun 55,56 %                  │
│  • Diamkan:      HMETD hangus, nilai teoretis −Rp555.556                 │
├──────────────────────────────────────────────────────────────────────────┤
│  Konteks                                                                  │
│  • Pemegang saham pengendali tercatat menambah kepemilikan              │
│    40,2 % → 42,7 % pada 9 Jul  [insider_filings · 2025-07-10]            │
│  • Harga terakhir Rp2.310 — 15,5 % di atas harga pelaksanaan             │
│    [daily_prices · 2025-07-10]                                            │
│  • Porsi investor asing turun 1,2 poin dalam 3 bulan [shareholders]      │
├──────────────────────────────────────────────────────────────────────────┤
│  Ringkasan (ID | EN)  … two-paragraph brief …                            │
│  Yang perlu kamu cek: batas waktu internal broker untuk penebusan.       │
├──────────────────────────────────────────────────────────────────────────┤
│  Edukasi, bukan rekomendasi.   [Lihat sumber data]   [Tanya di chat]     │
└──────────────────────────────────────────────────────────────────────────┘
```
*(Context values above are illustrative. The real card shows only what the data returns.)*

- **Numbers grid:** 4 tiles, mono numerals, units explicit (lembar, Rp, %). Each tile has a tooltip with its formula.
- **Timeline:** exact dates from the data. "Hari ini" marker. The countdown chip turns danger-red at ≤ 2 days, otherwise neutral hairline (no yellow, per DESIGN.md).
- **Scenarios:** neutral, parallel phrasing, theoretical values, "sebelum biaya transaksi". No option is highlighted.
- **Context:** each point carries an evidence chip (tool name in mono + `fetched_at`). Clicking it opens the evidence drawer at that row.
- **Evidence drawer** (Sheet): raw Sectors rows used, the calculator inputs and outputs, formulas, data gaps ("subscription_date semantics unverified"), cache source (`hit`/`upstream`).
- **What to verify:** a short checklist (broker cut-off, prospectus for additional-share subscription, tax status for dividends).

### 9.5 Flow D — dividend card (simpler)

```
BBMD · Dividen tunai                      Cum 30 Jun 2025 (lewat) · Bayar 18 Jul
Dividen per saham Rp34,25 · Yield 1,69 %
Untuk 5.000 saham kamu: Rp171.250 (bruto)
Timeline: Cum 30 Jun → Ex 1 Jul → Recording 2 Jul → Payment 18 Jul
Catatan: jumlah bersih tergantung status pajakmu (lihat ketentuan DJP).
```
State-dependent copy:
- **Before cum:** "Untuk berhak, saham harus dibeli paling lambat pada tanggal cum (pasar reguler)."
- **After ex, before payment:** "Kamu tercatat berhak jika memegang saham pada akhir tanggal cum."

### 9.6 Flow E — historical replay (demo and education)
1. A toggle **"Mode replay"** opens a date picker (`as_of`).
2. A banner across the page: **"Replay historis — data per 30 Jun 2025. Bukan data hari ini."** (muted surface, hairline border).
3. The run uses only data dated ≤ `as_of` (anti-lookahead, §12.8).
4. (P1) A **"Apa yang terjadi kemudian"** panel appears under each card, clearly separated: price path after the ex date vs TERP, and controller filings during and after the window.

### 9.7 Flow F — chat (P1)
User in chat: *"Saya pegang 1.000 saham WIFI, rights issue Juli 2025 itu artinya apa buat saya?"*
→ router `corporate_actions` → agent calls `aksi_impact(symbol="WIFI", shares=1000, as_of="2025-06-30")` → answer quotes the computed numbers with `fetched_at`, plus the standard disclaimer. The chart system is unchanged.

### 9.8 Empty, error and edge states
| Situation | Behaviour |
|---|---|
| No holdings | Empty state with the add form |
| Invalid ticker | Inline validation (regex `^[A-Z]{4}$`), never calls the API |
| Sectors API unavailable | Banner "Data Sectors sedang tidak tersedia"; cached results still shown with `stale` label |
| Field null (e.g. `price` missing) | Calculator returns `None` for dependent tiles → tile shows "—" with "data tidak tersedia" tooltip; brief mentions the gap |
| Credit budget exhausted | Run finishes with the events computed so far; banner "Batas kredit run tercapai" |
| JEV unavailable | Deterministic gate only; brief still produced |
| LLM fails | Template-only brief (numbers + dates, no prose) |
| Run stopped by user | Partial report saved (`status=stopped`) |

### 9.9 Copy and framing rules (POJK 6/2026)
- **Allowed:** "Jika ditebus…", "Jika dijual…", "Jika dibiarkan…", "nilai teoretis", "skenario", "data menunjukkan", "tercatat".
- **Banned** (gate rejects): *sebaiknya, harus, wajib (as advice), layak, rekomendasi, saran, beli, jual sekarang, tahan, hold, buy, sell, should, must, worth it, untung pasti, cuan*.
- **No motive attribution:** "Pemegang saham X tercatat menjual N saham pada D" — never "X keluar karena…".
- **Every card footer:** *"Informasi edukatif, bukan rekomendasi investasi. Verifikasi dengan keterbukaan informasi resmi IDX dan prospektus."*

---

## 10. Data: Sectors endpoints

### 10.1 Endpoints used

| Purpose | Sectors endpoint | Repo tool (exists) | Cost | Freshness in cache | Key fields |
|---|---|---|---|---|---|
| Detect events (market-wide window) | `GET /v2/corporate-actions/?type=…&start=&end=` | `sectors_corporate_actions` (`tools.py:771`) | 1 credit **per type** | EOD | See §10.2. Window ≤ 90 days, `end` may be future |
| Company action history (context, past actions) | `GET /v2/company/corporate-actions/{symbol}/` | `sectors_company_corporate_actions` (`tools.py:993`) | 1 | EOD | Same row keys as the calendar, grouped by type |
| Controller / insider activity | `GET /v2/filings/?symbol=&start=&end=` | `sectors_insider_filings` (`tools.py:697`) | 1 / page | NEWS (30 min) | `holder_name`, `holder_type`, `transaction_type`, `amount_transaction`, `price`, `price_transaction[]`, `share_percentage_before/after/transaction`, `timestamp` |
| Major shareholders (identify the controller) | `GET /v2/company/report/{symbol}/?sections=ownership` | `sectors_company_report` (`tools.py:312`) | 1 per section | EOD | Major shareholders + % (verify exact keys) |
| Ownership mix over time | `GET /v2/company/shareholders-composition/{symbol}/?year=` | `sectors_shareholders` (`tools.py:957`) | 1 | EOD / HISTORICAL for past years | Monthly rows: `date`, `shares_number`, categories `*_l` local / `*_f` foreign (insurance, corporate, pension_fund, financial_institutions, individual, mutual_fund, securities_companies, foundation, other), `total_l`, `total_f` |
| Price inputs (cum price, current price, post-ex path) | `GET /v2/daily/{symbol}/?start=&end=` | `sectors_daily_prices` (`tools.py:399`) | 1 | EOD; past windows permanent | `date`, `close`, `volume`, `market_cap` |
| (P1) Free-float status | `GET /v2/free-float/?sub_sector=` | `sectors_free_float` (`tools.py:1229`) | ~1 per 100 companies | EOD | `free_float` per company (current only; no per-ticker filter — filter by the holding's subsector, then pick the row) |
| (P1) News around the event | `GET /v2/news/?symbols=` | `sectors_news` | 1 | NEWS | headline, date, url |

All tools already go through the permanent, credit-aware Postgres cache (`backend/app/sectors/cache.py`). Past windows are cached permanently, so replays cost zero credits after the first run.

### 10.2 Corporate-action row schemas (from the official docs)

| Type | Fields |
|---|---|
| `right_issue` | `symbol`, `ex_date`, `cum_date`, `recording_date`, `trading_period_start`, `trading_period_end`, `subscription_date`, `price` (exercise price), `old_ratio`, `new_ratio` |
| `dividend` | `symbol`, `ex_date`, `cum_date`, `recording_date`, `payment_date`, `dividend_amount`, `dividend_yield` |
| `upcoming_dividend` | `symbol`, `ex_date`, `cum_date`, `recording_date`, `payment_date`, `dividend_amount` |
| `warrant` | `symbol`, `trading_period_start`, `trading_period_end`, `ex_per_start`, `ex_per_end`, `maturity_date`, `price`, `ratio_warrant`, `ratio_shares` |
| `stock_split` | `symbol`, `date` (ex date), `cum_date`, `recording_date`, `split_ratio`, `ratio` (e.g. `"1:10"`) |
| `bonus` | `symbol`, `ex_date`, `cum_date`, `recording_date`, `payment_date`, `old_ratio`, `new_ratio` |
| `agm` | `symbol`, `agm_date`, `recording_date`, `agm_time`, `agm_place` |

Calendar `start/end` filter on: `ex_date` (dividend, upcoming_dividend, bonus, right_issue), `date` (stock_split), `trading_period_start` (warrant), `agm_date` (agm). Wider ranges are clamped to the 90 days ending at `end`.

### 10.3 Field semantics: verified vs to verify

| Field | Status | Meaning used by the calculator |
|---|---|---|
| `right_issue.old_ratio / new_ratio` | **Verified.** WIFI docs row `4 / 5` = news "setiap pemegang 4 saham lama memperoleh 5 HMETD"; stated max dilution 55.56 % = 5/9 (consistent) | Holder of `old_ratio` shares receives `new_ratio` HMETD; 1 HMETD = 1 new share |
| `right_issue.price` | **Verified** (WIFI Rp2,000) | Exercise price per new share |
| `right_issue.trading_period_start/end` | **Verified** (WIFI 7–15 Jul 2025 = "Periode Perdagangan/Pelaksanaan HMETD") | Window to trade or exercise rights. **Deadline = `trading_period_end`** (brokers may set an earlier internal cut-off → "what to verify") |
| `right_issue.subscription_date` | **Unclear.** WIFI row shows 2025-07-03 = recording date | Display only as "subscription date (per data)"; never used as the deadline |
| `cum_date / ex_date` | Verified (WIFI cum 1 Jul regular market, ex 2 Jul) | Regular-market dates |
| `warrant.ratio_warrant / ratio_shares` | **To verify** with one real warrant | Assume an issuance ratio (shares : warrants); exercise 1 warrant = 1 share at `price` |
| `bonus.old_ratio / new_ratio` | **To verify** | Assume holder of `old_ratio` shares receives `new_ratio` bonus shares |
| `stock_split.split_ratio` | Likely new shares per old share (`ratio "1:10"`, `split_ratio 10`) | `new_shares = shares × split_ratio`; reverse split if < 1 |
| Insider `share_percentage_before/after` | Verified in the docs example (40.17 → 42.73) | Controller participation signal |

---

## 11. Calculation engine

All numbers shown to users come from **pure, unit-tested Python functions** in `backend/app/aksi/calc.py`. The LLM never computes or writes numbers (§12.6).

### 11.1 Inputs
- `shares` — holder's current shares (int, ≥ 1).
- The event row (§10.2).
- `p_ref` — reference price:
  - **before ex date** → latest close ≤ min(today/as_of, cum_date);
  - **after ex date** → the cum-date close (for TERP), plus the latest close for "current vs exercise".

### 11.2 Rights issue formulas

| Output | Formula | Notes |
|---|---|---|
| `rights_entitled` | `floor(shares × new_ratio / old_ratio)` | Fractional HMETD rounded down (standard prospectus term — show "verify in prospectus") |
| `cost_to_exercise_all` | `rights_entitled × price` | Rupiah, before fees |
| `terp` | `(old_ratio × p_cum + new_ratio × price) / (old_ratio + new_ratio)` | Theoretical ex-rights price |
| `right_value` | `max(0, terp − price)` | Theoretical value of one HMETD |
| `rights_value_total` | `rights_entitled × right_value` | Theoretical value lost if rights lapse |
| `dilution_if_ignored` | `new_ratio / (old_ratio + new_ratio)` | Fractional ownership reduction assuming full subscription by others |
| `ownership_factor_if_ignored` | `old_ratio / (old_ratio + new_ratio)` | |
| `value_if_ignored` | `shares × terp` | Theoretical |
| `value_if_exercised` | `(shares + rights_entitled) × terp` | Equals `shares × p_cum + cost_to_exercise_all` (sanity check) |
| `discount_to_market` | `(p_ref − price) / p_ref` | Positive = exercise price below market |
| `days_to_deadline` | `trading_period_end − today` (calendar days) | Exact date is always shown; trading-day count labelled "≈" (no IDX holiday feed) |
| `phase` | announced → cum passed → rights distributed → **window open** → expired | From dates vs today/as_of |
| (P1) `cash_neutral_exercise` | `floor(rights_entitled × right_value / (price + right_value))` | Rights exercised if the rest are sold at theoretical value; scenario only |

### 11.3 Worked example (WIFI, illustrative price)
Inputs: `shares = 1,000` (10 lots); `old_ratio = 4`; `new_ratio = 5`; `price = 2,000`; illustrative `p_cum = 3,000`.

| Output | Value |
|---|---|
| `rights_entitled` | floor(1,000 × 5/4) = **1,250 HMETD** |
| `cost_to_exercise_all` | 1,250 × 2,000 = **Rp2,500,000** |
| `terp` | (4 × 3,000 + 5 × 2,000) / 9 = 22,000 / 9 = **Rp2,444.44** |
| `right_value` | 2,444.44 − 2,000 = **Rp444.44** |
| `rights_value_total` | 1,250 × 444.44 = **≈Rp555,556** |
| `dilution_if_ignored` | 5 / 9 = **55.56 %** (matches WIFI's stated maximum dilution) |
| `value_if_ignored` | 1,000 × 2,444.44 = Rp2,444,444 (vs Rp3,000,000 before) |
| `value_if_exercised` | 2,250 × 2,444.44 = Rp5,500,000 = 3,000,000 + 2,500,000 (identity holds) |
| Sell rights at theoretical value | 2,444,444 + 555,556 = Rp3,000,000 (identity holds: value preserved, ownership diluted) |

These three identities are the unit-test oracle.

### 11.4 Dividends
| Output | Formula |
|---|---|
| `gross_dividend` | `shares × dividend_amount` |
| `entitled` | holder had the shares at the end of `cum_date` (regular market). In live mode, assume yes if the holding exists and today ≤ cum_date, or today > cum_date and the holding existed before (UI states the assumption) |
| `days_to_cum` | `cum_date − today` |
| `yield_on_cost` (if `avg_price` given) | `dividend_amount / avg_price` |

Example (docs row): BBMD Rp34.25, cum 30 Jun 2025, payment 18 Jul 2025; 5,000 shares → **Rp171,250 gross**.

### 11.5 Warrants (P0 basic)
| Output | Formula |
|---|---|
| `warrants_entitled` (if issued to holders) | `floor(shares × ratio_warrant / ratio_shares)` (semantics to verify) |
| `intrinsic_per_warrant` | `max(0, p_ref − price)` |
| `cost_to_exercise_all` | `warrants_entitled × price` |
| `days_to_maturity` | `maturity_date − today` |
| `phase` | trading / exercise window (`ex_per_start..ex_per_end`) / matured |

### 11.6 Stock split / bonus (P1)
- Split: `new_shares = shares × split_ratio`; `adjusted_price = p_ref / split_ratio`; odd-lot flag if `new_shares % 100 != 0`.
- Bonus: `bonus_shares = floor(shares × new_ratio / old_ratio)`; `new_total = shares + bonus_shares`.

### 11.7 Rounding and formatting
- Calculations use `Decimal`; values are rounded only for display.
- Rupiah: `Rp2.500.000` (ID) / `Rp2,500,000` (EN); percentages to 2 decimals.
- Each output carries `{value, formula, inputs, unit}` for the evidence drawer.
- Missing input → output `None` + `gap` reason (never fabricated).

### 11.8 Python shape

```python
@dataclass(frozen=True)
class Figure:
    key: str            # "cost_to_exercise_all"
    value: Decimal | None
    unit: str           # "IDR" | "shares" | "rights" | "pct" | "days"
    formula: str        # human-readable
    inputs: dict        # {"rights_entitled": 1250, "price": 2000}
    gap: str | None = None

def rights_issue(shares: int, row: dict, p_cum: Decimal | None,
                 p_now: Decimal | None, today: date) -> dict[str, Figure]: ...
def dividend(shares: int, row: dict, today: date, avg_price: Decimal | None = None) -> dict[str, Figure]: ...
def warrant(shares: int, row: dict, p_now: Decimal | None, today: date) -> dict[str, Figure]: ...
def phase(row: dict, kind: str, today: date) -> str: ...
```

---

## 12. Agent architecture

### 12.1 Why a dedicated graph (not just a chat workflow)
- The output is a **structured report** (cards, numbers, timeline), not a chat answer.
- It runs **per holding × per event**, with a credit budget and deterministic steps between LLM steps.
- It must work on demand **and** later on a schedule (P2) without a chat thread.
- The chat agent still benefits through a small `aksi_impact` tool (P1), reusing the same calculator.

### 12.2 Topology

```
(service: load holdings → create report row → emit started)
START
  → scan         calendar per type over [as_of−30d, as_of+60d]; filter to holdings;
                 triage (normalize → events, phase, urgency, sort, cap ≤ 5); emit event_found
  ── no events ──→ END
  → context      deterministic base pack per event (parallel tool calls)
  → investigate  bounded LLM tool loop over an allowlist (≤ 2 rounds, budget-guarded; rights issues only)
  → compute      pure calculators → figures; deterministic findings; emit numbers + finding
  → brief        LLM draft with placeholders → gate (deterministic + JEV) → 1 retry → else template; emit brief
  → persist      append to report JSONB; cursor++
  ── more events ──→ context
  ── done ──→ END
(service: finish report → emit done)
```

LangGraph `StateGraph` with conditional edges after `scan` and `persist`. The investigate tool loop runs inside its node (not as separate graph nodes) to keep the topology small; the gate runs inside `brief`. Event-level parallelism (LangGraph `Send`) is an optimisation for later; sequential processing keeps the live narration readable on video. The graph needs `recursion_limit≈100` (5 events × 5 nodes exceeds LangGraph's default of 25).

### 12.3 State

```python
class AksiState(TypedDict):
    report_id: str
    user_id: int
    mode: Literal["live", "replay"]
    as_of: str                       # YYYY-MM-DD (today in live mode)
    holdings: list[dict]             # [{symbol, shares, avg_price}]
    events: list[dict]               # normalized events (see 12.4 triage)
    cursor: int                      # index of the event being processed
    context: dict                    # base-pack envelopes for the current event
    messages: Annotated[list[BaseMessage], add_messages]  # investigate scratchpad; reset per event
    results: Annotated[list[dict], operator.add]          # finished event results
    credits_used: int
    budget: int                      # default 25 per run
```

### 12.4 Nodes in detail

> Responsibilities are described one by one below. Per §12.2, some run inside a single graph node: `load` lives in the service, `triage` runs in `scan`, `findings` in `compute`, `gate` in `brief`, and `finalize` in the service.

**`load`.** Reads holdings from `holdings` (or the request override), sets `as_of` (today in WIB for live), `budget`, and creates the `aksi_reports` row (`status=running`). Emits `started`.

**`scan`.** Calls `sectors_corporate_actions(types=["right_issue","warrant","upcoming_dividend","dividend"], start=as_of−30d, end=as_of+60d)` once. That is 4 credits, cached EOD and shared across all users, so normally it costs 0. It filters rows whose `symbol` (strip `.JK`) is in the holdings and emits `tool` events. If a holding has no hit, it may (P1) call `sectors_company_corporate_actions(symbol)` to catch rows outside the window that are still "active" (e.g. a warrant in its exercise period).

**`triage`.** Pure code:
- Normalizes rows into `Event{id, symbol, kind, row, phase, key_date, deadline, urgency}`, where `id = f"{symbol}:{kind}:{key_date}"` and `urgency = days_to_deadline` (rights/warrants) or `days_to_cum` (dividends).
- Drops expired events older than 30 days.
- Sorts by urgency and caps at 5 events per run.
- Emits `event_found` per event.

**`context`.** Deterministic base pack, run in parallel through the tools:

| Event kind | Base pack |
|---|---|
| right_issue | `company_report(sections=["ownership"])`, `insider_filings(symbol, start=cum−60d, end=min(as_of, trading_period_end+14d))`, `shareholders(symbol, year=as_of.year)` (+ previous year if `as_of` is in Q1), `daily_prices(symbol, start=as_of−89d, end=as_of)` |
| dividend / upcoming_dividend | `daily_prices(symbol, last 30d)`, `company_report(sections=["dividend"])` |
| warrant | `daily_prices(symbol, last 30d)`, `company_corporate_actions(symbol)` |

**`investigate` ⇄ `tools`.** An LLM bound to an **allowlist**: `sectors_insider_filings`, `sectors_shareholders`, `sectors_daily_prices`, `sectors_company_corporate_actions`, `sectors_news`, `sectors_broker_top`, `sectors_free_float`. The prompt contains the event, the computed phase, a compact summary of the base pack, and the **investigation checklist** (§12.5). It may make ≤ 2 rounds of extra calls. The tools node checks `credits_used + cost(tool) ≤ budget` before executing; over budget it returns a ToolMessage `{"error":"budget_exhausted"}`. When done, it returns a short JSON `{"probes_done": [...], "notes": "..."}` (not user-facing).

**`compute`.** Picks `p_cum` and `p_now` from the price envelope (closest date ≤ cum_date / ≤ as_of), calls the calculators and emits `numbers`.

**`findings`.** Pure code over the envelopes; each finding is `{id, kind, text_template, values, source_tool, fetched_at, row_ref}`:
- `controller_change` — filings by the top shareholder (matched by name from the ownership section, fallback: largest `share_percentage_after`) inside the window: before → after %, transaction type, date.
- `insider_net` — net buy/sell value of insider filings in the window.
- `ownership_shift` — change in `total_f / shares_number` (foreign %) and `individual_l` share over the last 3 monthly rows.
- `price_vs_exercise` — discount/premium of the latest close vs exercise price.
- `past_rights` (P1) — previous `right_issue` rows in the company history, plus the 30-day post-ex return vs TERP if the prices are cached.
- `free_float_status` (P1) — current float vs 15 % with the tier deadline (by market cap).

Emits `finding` per item.

**`brief`.** LLM structured output (Pydantic):

```python
class BriefText(BaseModel):
    headline_id: str; headline_en: str
    summary_id: str;  summary_en: str           # ≤ 90 words each
    context_ids: list[str]                      # finding ids referenced, in order
    verify_id: list[str]; verify_en: list[str]  # "what to verify" bullets
```

Rules in the prompt: no digits at all; numbers and dates only via placeholders like `{{rights_entitled}}`, `{{cost_to_exercise_all}}`, `{{deadline}}`, `{{dilution_if_ignored}}`; no advice verbs; neutral conditionals ("Jika…"). The renderer substitutes formatted values.

**`gate`.**
1. **Deterministic** — the LLM text must contain no digits (`\d`) outside placeholders; no banned phrases (§9.9); every placeholder must exist in the computed figures; every `context_ids` entry must exist in the findings.
2. **JEV** (one `jev_ask`, parallel questions):
   - `advice` — `Noul`: "Does this text urge or advise the reader to buy, sell, hold, exercise or not exercise?"
   - `grounded` — `Noul`: "Is every statement supported by the listed findings and figures?"

   Pass when `advice < 0.3` and `grounded ≥ 0.6`.
3. On failure: regenerate once with the failure reasons. If it fails again → **template brief** (fixed sentences per event kind, placeholders only).
4. JEV `None` → deterministic checks only (consistent with the repo's fail-closed pattern).

**`persist_event`.** Appends `{event, figures, findings, brief, gate}` to `aksi_reports.events` (JSONB) incrementally, so stopped runs keep partial results. Emits `brief`.

**`finalize`.** Sets `status=done`, `credits_spent`, and emits `done {report_id}`.

### 12.5 Investigation checklist given to the LLM (rights issue)
1. Is the controlling shareholder visible in filings during the window? (bought / exercised / sold / no filing)
2. Did foreign or institutional ownership move noticeably in the last 3 months?
3. Where is the current price vs the exercise price and vs TERP?
4. Has this company done rights issues before (company history)? (P1: what happened after)
5. Is there news explaining the use of proceeds? (optional, if budget allows)

Stop when the checklist is answered or the budget/round cap is reached. Never speculate about motives.

### 12.6 Why numbers can't be faked or hallucinated
- Calculators are pure functions with tests (§16).
- The LLM is forbidden from writing digits; the gate enforces it in code.
- Every figure exposes formula + inputs + source rows in the evidence drawer.
- Every tool call is visible live (same Spark status system as chat), and `/api/v1/sectors/cache/stats` shows real upstream usage.

### 12.7 Credit budget
| Item | Credits (cold) | Warm |
|---|---|---|
| Calendar scan (4 types) | 4 (shared by all users, once per EOD) | 0 |
| Rights-issue base pack | ownership 1 + filings 1 + shareholders 1–2 + prices 1 = 4–5 | 0 |
| Investigate extras | 0–3 | 0 |
| Dividend pack | 1–2 | 0 |

A typical run with 1 rights issue + 2 dividends costs ≈ **10–14 credits cold, ≈ 0 warm**. Default budget per run: **25**. `credits_used` counts only `source == "upstream"` envelopes × the known tool cost (static map in `aksi/budget.py`).

### 12.8 Replay mode (`as_of`)
- All tool windows end at `min(end, as_of)`; the calendar window is centred on `as_of`.
- **Anti-lookahead:** `findings` and `compute` ignore rows dated after `as_of`. Only the P1 "what happened next" panel reads post-`as_of` data, and it is rendered separately and labelled.
- **Known limit:** calendar rows carry no announcement date, so a replay can surface an event that was announced after `as_of` but has dates inside the window. The ownership section of the company report is also current-only (used just to name the controller). Both are acceptable for a labelled replay; mention them in the evidence drawer.
- Past windows are cached permanently, so replays are cheap and deterministic. That makes the demo reproducible, and judges can re-run it from the repo.
- The report stores `mode="replay"`; the UI shows the banner on every card.

### 12.9 JEV usage summary
| Call site | Type | Fallback |
|---|---|---|
| Gate: advice | Noul | Deterministic banned-phrase check |
| Gate: grounded | Noul | Deterministic placeholder/finding-id check |
| (Optional) investigate: "enough context?" | Noul | Round cap |
| Chat router: `corporate_actions` workflow | Choice (existing router) | `general` |

### 12.10 Chat integration (P1)
- `router.WORKFLOWS["corporate_actions"] = "Questions about a stock's corporate actions — rights issues (HMETD), dividends, warrants, stock splits, bonus shares — and what they mean for the user's shares."`
- `nodes._WORKFLOW_HINTS["corporate_actions"]`: "Use `aksi_impact` for any holder-specific figure; never compute mentally; quote fetched_at; never advise buying, selling, exercising or holding; end with the standard disclaimer."
- New tool `aksi_impact(symbol: str, shares: int, as_of: str | None = None, kind: str | None = None)` in `app/aksi/tools.py`: runs `scan` for that symbol + `compute` and returns `{events: [{kind, dates, figures}]}`. Added to `AGENT_TOOLS` (`tools_node.py`) and to `frontend/lib/tool-labels.ts` (`aksi_impact: "Computing corporate-action impact"`).
- (Optional) `get_holdings()` tool so the chat agent can answer "what about my portfolio?".

---

## 13. Backend implementation

### 13.1 File layout

**New**
```
backend/app/aksi/
  __init__.py
  calc.py          # pure calculators (§11) + figures_for + close_on_or_before
  fmt.py           # ID/EN number, rupiah, percent, date formatting
  events.py        # calendar rows → holding events; phase/urgency; scan window
  findings.py      # deterministic fact extraction from envelopes (code writes the sentences)
  gate.py          # deterministic brief checks + JEV gate
  briefs.py        # LLM draft (placeholders only), render, templates
  budget.py        # tool cost map, budget guard
  store.py         # holdings + reports persistence
  nodes.py         # scan, context, investigate, compute, brief, persist
  graph.py         # AksiState + aksi_graph
  service.py       # run_check producer (detached run)
  impact.py        # single-holding impact without LLM (API + chat tool)
  tools.py         # aksi_impact LangChain tool for the chat agent (P1)
backend/app/prompts/aksi_investigate.md
backend/app/prompts/aksi_brief.md
backend/app/models/holding.py
backend/app/models/aksi_report.py
backend/app/schemas/aksi.py
backend/app/api/v1/endpoints/aksi.py
backend/app/api/sse.py               # shared SSE helpers (moved from chat.py)
backend/alembic/versions/20261006_1200_b4e1a7c9d2f3_holdings_aksi_reports.py
backend/scripts/aksi_data_check.py
backend/tests/test_aksi_calc.py
backend/tests/test_aksi_events.py
backend/tests/test_aksi_findings.py
backend/tests/test_aksi_gate.py
backend/tests/test_aksi_holdings_api.py
backend/tests/test_aksi_graph.py
backend/tests/test_aksi_check_api.py
```

**Changed**
```
backend/app/api/v1/api.py            # include aksi router (prefix "/aksi")
backend/app/api/v1/endpoints/chat.py # use shared SSE helpers
backend/app/models/__init__.py       # export new models (alembic autogenerate)
backend/app/main.py                  # compile aksi graph at startup (lifespan) if needed
backend/app/agent/router.py          # (P1) corporate_actions workflow
backend/app/agent/nodes.py           # (P1) workflow hint
backend/app/agent/tools_node.py      # (P1) add aksi_impact to AGENT_TOOLS
```

### 13.2 Database

```python
class Holding(TimeStampedBase):
    __tablename__ = "holdings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(4))
    shares: Mapped[int] = mapped_column(BigInteger)
    avg_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    __table_args__ = (UniqueConstraint("user_id", "symbol"),)

class AksiReport(TimeStampedBase):
    __tablename__ = "aksi_reports"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(8))          # live | replay
    as_of: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10))       # running | done | stopped | error
    holdings_snapshot: Mapped[list] = mapped_column(JSONB)
    events: Mapped[list] = mapped_column(JSONB, default=list)
    credits_spent: Mapped[int] = mapped_column(Integer, default=0)
```

Migration: one Alembic revision creating both tables and the index `(user_id, created_at desc)` on `aksi_reports`. `TimeStampedBase` (`app/db/base.py`) supplies `created_at/updated_at`. Explicit `__tablename__` is needed because the base pluralises class names (`aksireports`).

### 13.3 API (prefix `/api/v1/aksi`, all JWT-protected via `deps.get_current_user`)

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/holdings` | — | `{holdings: [{symbol, shares, avg_price}]}` |
| PUT | `/holdings` | `{holdings: [{symbol, shares, avg_price?}]}` (≤ 30 rows, replace-all) | same as GET |
| POST | `/check` | `{as_of?: "YYYY-MM-DD", symbols?: [..], budget?: int ≤ 40}` | **SSE stream** (§13.4) |
| GET | `/check/stream` | `?last_seq=N` | SSE re-attach / replay (linger window) |
| POST | `/check/stop` | — | `{stopped: bool}` |
| GET | `/reports/latest` | `?mode=live|replay` | `ReportOut` |
| GET | `/reports/{id}` | — | `ReportOut` |
| POST | `/impact` | `{symbol, shares, as_of?}` | `{events: [{kind, row, figures}]}` (no LLM; also backs the chat tool) |

Validation: symbol `^[A-Z]{4}$` after upper/strip `.JK`; `shares` 1…10¹²; `as_of` ≥ 2021-01-01 and ≤ today; rate limits with the existing slowapi limiter (`core/ratelimit.py`), e.g. `/check` 6/min per user.

### 13.4 SSE contract
Same envelope as chat: `data: {"seq": n, "type": "...", "data": {...}}`.

| type | data |
|---|---|
| `started` | `{report_id, mode, as_of, started_at}` |
| `step` | `{node: "scan"|"triage"|"context"|"investigate"|"compute"|"brief"|"gate", event_id?}` |
| `tool` | `{name, args, status: "call"|"done"}` — identical to chat, so `AgentStatus` works unchanged |
| `event_found` | `{event_id, symbol, kind, phase, key_dates, deadline, urgency}` |
| `numbers` | `{event_id, figures: {key: {value, unit, formula, inputs, gap}}}` |
| `finding` | `{event_id, id, kind, text_id, text_en, source_tool, fetched_at}` |
| `brief` | `{event_id, headline_id, headline_en, summary_id, summary_en, verify_id, verify_en, context_ids, gate: {passed, reasons, template}}` |
| `budget` | `{credits_used, budget}` |
| `done` | `{report_id, events: n, credits_spent}` |
| `stopped` | `{report_id}` |
| `error` | message string |

### 13.5 Run registry reuse
`app/agent/runs.registry` is keyed by an arbitrary string. Use the key `f"aksi:{user_id}"`: one active check per user, existing global/per-user caps, the replay buffer and linger eviction all reused. `aksi/service.run_check(run, user_id, req)` mirrors `agent/service.run_turn`: it iterates `aksi_graph.astream(..., stream_mode="values")` (tracking the latest state for credits), while nodes emit custom events through an `emit` callable passed in `config["configurable"]["emit"]`. On `CancelledError` → `status=stopped`, partial events kept.

### 13.6 Prompts (summary)
- `aksi_investigate.md` — role ("analyst assistant gathering context; you never advise"), event JSON, base-pack summary, checklist, budget remaining, allowlisted tools, stop condition, output JSON schema.
- `aksi_brief.md` — audience (Indonesian retail holder), tone (calm, plain Indonesian; English mirror), the **no-digits / placeholders-only** rule with the full placeholder list for the event kind, banned phrases, neutral-conditional style, 90-word limit, required "what to verify" bullets.

### 13.7 Error handling
| Failure | Handling |
|---|---|
| Sectors unavailable | Tool envelopes return `sectors_api_unavailable`; cache `stale_fallback` used when available; the event shows a gap |
| Field null | Figure `value=None`, `gap="field X missing"` |
| LLM error / timeout | Template brief; `gate.template=true` |
| JEV down | Deterministic gate only |
| Budget exhausted | Stop investigating; compute/brief with what's available; `budget` event |
| DB write error | Log, emit `error`, run ends; partial report status `error` |

---

## 14. Frontend implementation

> Per `frontend/AGENTS.md`: this is **Next.js 16.3.5** with breaking changes. Read `node_modules/next/dist/docs/` before writing routing or data-fetching code. Stack: React 19.2, Tailwind 4, shadcn/radix-ui, zustand 5, recharts 3, lucide-react, sonner.

### 14.1 Routing and navigation
- New page **`frontend/app/(chat)/aksi/page.tsx`** inside the existing `(chat)` group, so it inherits `ChatLayout` (auth guard, `SidebarProvider`, inset panel).
- **Sidebar:** add a third item to the existing "New Thread / History" menu in `components/sidebar-threads.tsx`: **Aksi Korporasi** → `/aksi` (`CalendarClockIcon`), with a `SidebarMenuBadge` showing the count of events whose deadline is ≤ 7 days away (from the latest live report in `useAksiStore`).
- `isActive={pathname === "/aksi"}`.

### 14.2 Components (`frontend/components/aksi/`)
| Component | Purpose |
|---|---|
| `aksi-view.tsx` | Page shell: header ("Aksi Korporasi", replay toggle, run button), holdings panel, status line, results |
| `holdings-panel.tsx` | Editable table (ticker, lembar/lot toggle, avg price), add row, save (`PUT /aksi/holdings`), validation |
| `run-status.tsx` | Wraps the existing `AgentStatus` (Spark) with `ToolActivity[]` from the store + mono credit meter |
| `event-card.tsx` | Card per event: header (ticker, kind badge, countdown chip), `NumbersGrid`, `DeadlineTimeline`, scenarios, context list, brief (ID/EN tabs), verify list, footer actions |
| `numbers-grid.tsx` | 4 tiles; tooltip shows formula + inputs |
| `deadline-timeline.tsx` | Horizontal dates with a "hari ini" marker; window segment highlighted with a lavender hairline |
| `context-list.tsx` | Finding rows with evidence chips (`EvidenceChip`: mono tool name + `fetched_at`) |
| `evidence-drawer.tsx` | shadcn `Sheet` with raw rows (JSON pretty), figures table (value, formula, inputs), gaps, cache source |
| `ownership-sparkline.tsx` (P1) | recharts mini area of foreign % from shareholders rows (reuse `ChartCard` styling) |
| `replay-banner.tsx` | Muted banner while `mode=replay` |
| `empty-state.tsx` | No holdings / no events / API down |

### 14.3 Store: `frontend/lib/stores/aksi.ts` (zustand, mirrors `stores/chat.ts`)
```ts
interface AksiStore {
  holdings: Holding[];
  mode: "live" | "replay";
  asOf: string | null;
  running: boolean;
  tools: ToolActivity[];                 // for AgentStatus
  credits: { used: number; budget: number } | null;
  events: Record<string, AksiEvent>;     // keyed by event_id, filled incrementally
  order: string[];                       // event display order
  latest: Report | null;                 // last saved report (badge + reload)
  loadHoldings(): Promise<void>;
  saveHoldings(h: Holding[]): Promise<void>;
  run(opts?: { asOf?: string }): void;   // starts SSE, handles events
  stop(): void;
  loadLatest(mode?: "live" | "replay"): Promise<void>;
}
```
Event handling: `started` → reset; `tool` → same push/settle logic as chat (`verbFor`/`detailFor` from `lib/tool-labels.ts`); `event_found` → skeleton card; `numbers`/`finding`/`brief` → patch card; `budget` → meter; `done`/`stopped`/`error` → settle + `loadLatest()`.

### 14.4 API client (`frontend/lib/api.ts`)
- Refactor the SSE frame parser in `streamChat` into `streamSSE(path, body, signal)`; keep `streamChat` as a thin wrapper.
- Add `getHoldings`, `putHoldings`, `streamAksiCheck(body, signal)`, `stopAksiCheck`, `getLatestReport(mode)`, `getReport(id)`, `postImpact`.
- Types in `frontend/lib/aksi.ts`: `Holding`, `Figure`, `Finding`, `Brief`, `AksiEvent`, `Report`, `AksiStreamEvent`.

### 14.5 Design system mapping (DESIGN.md / PRODUCT.md)
- Dark canvas `#010102`; cards on surface-1 `#0f1011` with hairline `#23252a`, 12 px radius; no shadows.
- **Lavender `#5e6ad2` only** for the primary "Cek aksi korporasi" button, focus rings and the active timeline window. No decorative accent.
- Countdown chip: neutral (surface-2 + hairline) by default; **danger `#eb5757`** when ≤ 2 days; never yellow.
- Numbers and tool names in **JetBrains Mono**; body Inter 14–16 px; captions 12 px muted.
- Spark status system unchanged; finale pop once on `done`.
- Copy: Indonesian first, English toggle (tabs) on the brief.

### 14.6 Accessibility
- Countdown chips carry text ("4 hari lagi"), not colour only.
- Timeline exposed as an ordered list for screen readers.
- Evidence chips are buttons with `aria-label="Lihat sumber: insider filings, diambil 10 Jul 2025"`.
- `prefers-reduced-motion` respected (inherited from the Spark system).

---

## 15. Implementation plan and timeline

### 15.1 Phases
| # | Work | Output | Est. |
|---|---|---|---|
| 0 | **Data check** (§18.2) — ~13 credits | Go/no-go; pick demo tickers; confirm field semantics | 0.5 h |
| 1 | `calc.py` + `events.py` + tests (WIFI oracle) | Pure, tested calculators | 2.5 h |
| 2 | Models + migration + `schemas/aksi.py` + holdings endpoints | Holdings CRUD | 1.5 h |
| 3 | `findings.py`, `budget.py`, `gate.py` (+ tests) | Deterministic fact extraction and gate | 2 h |
| 4 | `graph.py` + `nodes.py` + prompts + `service.run_check` + `/check` SSE + stop + reports | End-to-end agent run over SSE | 5 h |
| 5 | Frontend: route, sidebar nav, holdings panel, store, SSE client, run status | Page runs a check live | 3.5 h |
| 6 | Frontend: event card, numbers grid, timeline, context list, evidence drawer, replay banner | Demo-quality cards | 3.5 h |
| 7 | Replay mode end-to-end (WIFI as of 2025-06-30) | Reproducible demo | 1 h |
| 8 | (P1) Chat workflow + `aksi_impact` tool + "Tanya di chat" | Chat integration | 1.5 h |
| 9 | Polish, empty/error states, copy review against banned list | Ready to film | 2 h |
| 10 | Video recording + editing + teaser + submission form | Submission | 3–4 h |
| | **Total build** | | **≈ 22–24 h** (+ video) |

### 15.2 Day plan
- **Tue 6 Oct (evening):** Phase 0 → 1 → 2.
- **Wed 7 Oct:** Phases 3 → 4 (morning/afternoon), 5 → 6 (evening).
- **Thu 8 Oct:** Phase 7 + 9 (morning), P1 items if ahead, **record videos by mid-afternoon**, submit by evening. Leave a buffer: the repo freezes on submission.

### 15.3 Cut list (in this order if behind)
1. P1 chat integration.
2. Warrant calculator → show warrant rows as "info only".
3. Investigate LLM loop → deterministic base pack only (keep the visible tool steps).
4. JEV gate → deterministic gate only.
5. EN translation of briefs.

**Never cut:** rights-issue calculator, live tool narration, evidence drawer, replay label, disclaimer.

### 15.4 Repo conventions (from `AGENTS.md`)
- Commit style: lowercase `phase N: short description`. The next phase number is **14** (last commit: `phase 13: reasoning exposure …`). E.g. `phase 14: aksi korporasi calculators + holdings`, `phase 14b: aksi agent graph + sse`, `phase 14c: aksi page + event cards`.
- **No** `Co-Authored-By` / "Generated with" trailers.
- Run `/code-simplifier` after code changes before finishing.
- Never commit `.env` or secrets.
- Dev stack: `docker compose up -d`; backend on :8000 runs `alembic upgrade head` on start; frontend on :3000.

---

## 16. Testing and verification

### 16.1 Backend tests (`docker compose exec backend python -m pytest tests`)
| File | Covers |
|---|---|
| `test_aksi_calc.py` | WIFI oracle (1,250 rights; Rp2,500,000; TERP 2,444.44; 55.56 %; value identities); rounding (fractional rights floored); null inputs → `gap`; dividend gross; warrant intrinsic; split/bonus (P1) |
| `test_aksi_events.py` | Row normalization per kind; `.JK` stripping; phase by date (before cum / window open / expired); urgency sort; cap at 5; replay anti-lookahead |
| `test_aksi_findings.py` | Controller change, price vs exercise, ownership shift, no-filings fact, anti-lookahead on rows after `as_of` |
| `test_aksi_gate.py` | Digit detection, banned phrases (ID/EN), unknown placeholder, unknown finding id; JEV mocked pass/fail/`None`; templates always pass; render substitutes per language |
| `test_aksi_holdings_api.py` | Holdings PUT/GET validation, symbol normalization, duplicates rejected, auth required |
| `test_aksi_graph.py` | Graph with mocked upstream (fixture envelopes through the real tools + cache) and mocked LLM/JEV: events found → numbers → findings → briefs → persisted; credit accounting; no-events path |
| `test_aksi_check_api.py` | `/check` emits `started` … `done`; `/reports/latest`; `/impact` |

Fixtures: one calendar envelope (WIFI right_issue + BBMD dividend from the docs examples), insider filings, shareholders, daily prices.

### 16.2 Frontend checks
`docker compose exec frontend npx tsc --noEmit` · `npx eslint .` · `npm run build`.

### 16.3 Manual end-to-end checklist
1. Add holdings (WIFI 1,000; BBCA 500; one ticker with a live event found in the data check).
2. Live run: tool steps stream; cards appear; numbers match a hand calculation; evidence drawer shows raw rows.
3. Replay WIFI `as_of=2025-06-30`: banner visible; no post-`as_of` data in findings; numbers match §11.3 with the real `p_cum`.
4. Stop mid-run → partial report persists and reloads.
5. Kill the network to Sectors → cached results with the `stale` label.
6. Copy audit: grep briefs for banned phrases.
7. `/api/v1/sectors/cache/stats` shows hits increasing on the second run (credit discipline visible).

---

## 17. Demo and video plan

### 17.1 Demo data preparation
- From the data check, pick **1 live event** (an upcoming or ongoing rights issue/warrant/dividend in the next 60 days) and add that ticker to the demo holdings.
- Pre-warm the cache by running the full flow once (the second run costs ~0 credits and is fast on camera).
- Replay case: **WIFI, as_of 2025-06-30** (real event, documented ratio and dates, controller commitment).

### 17.2 Three-minute judging video
| Time | On screen | Voiceover gist (ID or EN) |
|---|---|---|
| 0:00–0:12 | Black → a real rights-issue announcement fragment, then the line "HMETD yang tidak dilaksanakan … dinyatakan tidak berlaku lagi" | *"Every year Indonesian investors lose money not to bad stocks, but to deadlines they never understood."* |
| 0:12–0:30 | Stats cards: 31.9 M investors, 14 rights issues worth Rp34 T in 2025, 391 dividend events in 7 months, the free-float reform wave | Who and why now |
| 0:30–0:50 | `/aksi`: enter holdings (3 tickers, share counts) | "I hold three stocks. Do I need to do anything?" |
| 0:50–1:30 | Click **Cek aksi korporasi**: Spark line narrates calendar scan → insider filings → shareholders → prices → computing → writing brief; credit meter | The agent at work, visibly |
| 1:30–2:05 | The WIFI card fills: **1,250 HMETD · Rp2.5 jt to exercise · TERP · −55.56 % if ignored · 15 Jul deadline**; three neutral scenarios | The memorable screen |
| 2:05–2:30 | Context: controller's filing (% before → after), price vs exercise, ownership shift; click an evidence chip → drawer with raw Sectors rows + formula | "Every number is sourced and checkable" |
| 2:30–2:45 | Replay banner + (P1) "what happened next" panel; or the dividend card | Honesty: labelled replay |
| 2:45–3:00 | Footer disclaimer; architecture one-liner (Sectors → agent → deterministic calculators → gated brief) | *"Corporate actions are public. Your deadlines shouldn't be a surprise."* |

### 17.3 One-minute teaser
Vertical cut: the announcement line → the numbers grid filling in → the countdown chip turning red → the end card "JagaHak / Aksi Korporasi Copilot — dampak aksi korporasi untuk sahammu, dalam hitungan detik." Captions instead of voiceover.

### 17.4 What makes the video fail, and the guard
| Risk | Guard |
|---|---|
| Looks like a calculator, not an agent | Show the investigation steps and the context findings live; the numbers are only half the story |
| Advice-shaped output in front of regulator-adjacent judges | Gate + scripted review; neutral scenarios; disclaimer visible |
| No live event available | Labelled replay (WIFI) as the centrepiece + dividend live |
| Slow run on camera | Pre-warmed cache; cap events at 3 for the demo |

---

## 18. Risks, data checks, kill criteria

### 18.1 Risk register
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Calendar has no live rights/warrant rows in the window | Medium | Medium | Dividends are always present; WIFI replay as centrepiece; extend the window to ±90 days |
| Per-ticker endpoint lacks upcoming rights | Low–Med | Low | The calendar is the primary detector |
| `subscription_date`, warrant and bonus semantics wrong | Medium | Medium | Deadline uses `trading_period_end` only; warrant/bonus marked "verify" or cut |
| Controller not identifiable (ownership section keys differ) | Medium | Low | Fallback: largest `share_percentage_after` in filings; else omit the finding |
| Insider filings sparse for small caps | Medium | Low | Finding omitted with "no filing in window" (a fact, not a gap) |
| LLM writes numbers or advice | Medium | High | No-digit rule + banned list + JEV gate + template fallback |
| Credit overrun | Low | Medium | Budget guard (25/run), shared EOD cache, pre-warming |
| Time overrun | Medium | High | Cut list §15.3; video slot protected on Thursday |
| Overlap perception with Alarm Saham (rights as a warning sign) | Low | Low | Framing: personal consequence + deadlines, not distress warnings |

### 18.2 Data check before building (~13 credits; also pre-warms the cache for the demo)
| # | Call | Confirms | Kill / adjust |
|---|---|---|---|
| 1 | `GET /v2/corporate-actions/?type=right_issue,warrant,upcoming_dividend&start=<today−30>&end=<today+60>` (3) | Live events exist; fields populated | No right_issue/warrant rows → live demo uses dividends; rights shown via replay |
| 2 | `GET /v2/company/corporate-actions/WIFI/` (1) | Row keys; whether history includes the 2025 rights issue | Missing → replay uses the calendar for July 2025 instead (1 more credit) |
| 3 | `GET /v2/daily/WIFI/?start=2025-05-01&end=2025-07-31` (1) | `p_cum` on 2025-07-01; post-ex path | Missing → choose another past rights issue |
| 4 | `GET /v2/filings/?symbol=WIFI&start=2025-06-01&end=2025-08-31` (1) | Controller (ISB) filing with % before/after | Missing → context uses ownership shift + price only |
| 5 | `GET /v2/company/shareholders-composition/WIFI/?year=2025` (1) | Monthly rows for the ownership shift | Missing → drop the finding |
| 6 | `GET /v2/company/report/WIFI/?sections=ownership` (1) | Major-shareholder keys/names | Missing → filing-based controller fallback |

**Go criterion:** rows 2–3 succeed (the WIFI replay works end to end) **and** row 1 returns at least one usable live dividend row.

---

## 19. Appendix

### 19.1 Sources
**Problem and market**
- BBRI 2021 prospectus (unexercised HMETD void): https://bri.listedcompany.com/newsroom/517b4fc5b6_2c2f4260a4.pdf
- CNBC Indonesia, BBRI 7.33 bn HMETD unexercised (22 Sep 2021): https://www.cnbcindonesia.com/market/20210922082707-17-278144/rights-issue-terbesar-bri-sudah-diguyur-modal-baru-rp-71-t
- Bisnis, BBRI 97.4 % exercised (24 Sep 2021): https://finansial.bisnis.com/read/20210924/90/1446654/raup-rp934-triliun-bri-bbri-catatkan-rights-issue-terbesar-di-asia-tenggara
- Radar Pasar, rights-issue guide (rights removed without compensation): https://radarpasar.com/laporan/rights-issue-pmhmetd-panduan
- IdxStock, rights-issue guide (retail forgetting to exercise): https://idxstock.com/right-issue/
- Bisnis, 14 rights issues / Rp34.47 T in 2025: https://market.bisnis.com/read/20251226/192/1939659/rights-issue-jumbo-towr-hingga-wifi-pada-2025-raup-dana-rp3447-triliun
- Bisnis, OJK 2025 fundraising (210 offerings, 14 rights issues): https://market.bisnis.com/read/20251231/7/1940591/total-dana-ipo-hingga-rights-issue-terkumpul-rp26814-triliun-pada-2025
- VIVA, KSEI 4,727 corporate actions / 391 dividends to 8 Aug 2025: https://www.viva.co.id/bisnis/1842461-ada-391-aksi-tebar-dividen-di-pasar-modal-indonesia-hingga-8-agustus-2025
- ANTARA, KSEI dividends by sector 2025: https://www.antaranews.com/berita/5326882/ksei-perbankan-sumbang-dividen-terbesar-rp8034-triliun-pada-2025
- Pantau, 31.90 M SID end-Sep 2026: https://www.pantau.com/ekonomi/370077/investor-pasar-modal-indonesia-tembus-319-juta-sid-bei-membidik-35-juta-pada-2030
- Liputan6, 30.27 M SID / 10.05 M stock investors (Aug 2026): https://www.liputan6.com/saham/read/8265362/investor-pasar-modal-indonesia-tembus-3027-juta-sid

**WIFI 2025 rights issue**
- Kontan (ratio 4:5, Rp2,000, schedule): https://investasi.kontan.co.id/news/bernilai-rp-589-triliun-intip-jadwal-rights-issue-solusi-sinergi-digital-wifi
- EmitenNews (max dilution 55.56 %): https://emitennews.com/news/prospek-cerah-right-issue-saham-wifi-bakal-sukses
- IDX Channel (terms, ISB commitment): https://www.idxchannel.com/market-news/surge-wifi-rights-issue-di-harga-rp2000-potensi-raup-rp589-triliun/all
- KabarBursa (effective date, ISB 1.48 bn HMETD): https://www.kabarbursa.com/market-hari-ini/wifi-mulai-rights-issue-saham-turun-240-persen

**Regulation and reform**
- KSEI/OJK/BEI reform press release (8 Apr 2026): https://web.ksei.co.id/files/uploads/press_releases/press_file/id-id/253_ojk_bei_dan_ksei_tuntaskan_empat_agenda_reformasi_transparansi_pasar_modal_indonesia_20260408105917.pdf
- Bisnis, free float 15 % tiers (1 Apr 2026): https://market.bisnis.com/read/20260401/7/1963525/bei-resmi-berlakukan-free-float-15-big-caps-diberi-tenggat-waktu-hingga-2027
- Kompas, free float phased / delisting risk (27 Apr 2026): https://money.kompas.com/read/2026/04/27/163503426/free-float-15-persen-berlaku-bertahap-ojk-antisipasi-risiko-delisting
- KabarBursa, free float tiers to 2029: https://www.kabarbursa.com/market-hari-ini/bei-naikkan-free-float-15-persen-reformasi-pasar-dimulai
- OJK, POJK 6/2026 press release: https://ojk.go.id/id/berita-dan-kegiatan/siaran-pers/Pages/POJK-6-Tahun-2026-Perilaku-Penyampai-Informasi-Sektor-Jasa-Keuangan-Financial-Influencer.aspx
- OJK, POJK 6/2026 FAQ (definition of "pemberian rekomendasi"): https://ojk.go.id/id/regulasi/Documents/Pages/POJK-6-Tahun-2026-Perilaku-Penyampai-Informasi-Sektor-Jasa-Keuangan/FAQ%20POJK%20Nomor%206%20Tahun%202026.pdf

**Existing products**
- Stockbit Calendar help: https://help.stockbit.com/id/article/calendar-bagaimana-cara-menggunakan-fitur-calendar-xyx6s2/
- Stockbit Corporate Action help (marker ±1 day): https://help.stockbit.com/id/article/corporate-action-bagaimana-cara-menggunakan-fitur-corporate-action-1wok01t/

**Sectors API docs**
- Index: https://docs.sectors.app/llms.txt
- Corporate actions per symbol: https://docs.sectors.app/api-references/v2/indonesia/company/corporate-actions
- Corporate actions calendar (row schemas): https://docs.sectors.app/api-references/v2/indonesia/news/corporate-actions
- Company filings: https://docs.sectors.app/api-references/v2/indonesia/news/filings
- Shareholders composition: https://docs.sectors.app/api-references/v2/indonesia/company/shareholders-composition
- Free float: https://docs.sectors.app/api-references/v2/indonesia/screener/free-float
- v2 changelog: https://docs.sectors.app/api-references/v2/changelog

**Hackathon**
- Rules (rubric, deadlines, freeze, no-advice rule): https://hackathon.sectors.app/rules
- Track 01 requirements: https://hackathon.sectors.app/tracks/ai-agents-assistants

### 19.2 Glossary
| Term | Meaning |
|---|---|
| **HMETD** | *Hak Memesan Efek Terlebih Dahulu* — pre-emptive right to buy new shares in a rights issue (PMHMETD) |
| **Cum date** | Last trading day (regular market) on which buying the stock still carries the entitlement |
| **Ex date** | First trading day without the entitlement |
| **Recording date** | Date the shareholder register (DPS) is fixed (T+2 settlement after cum) |
| **Trading period (HMETD)** | Window in which rights can be traded (ticker suffix `-R`) and exercised |
| **TERP** | Theoretical ex-rights price — blended price after new shares are issued at the exercise price |
| **Dilution** | Reduction in ownership percentage when new shares are issued and the holder doesn't take up their rights |
| **Free float** | Shares held by the public (not controllers/affiliates); minimum raised to 15 % from 31 Mar 2026 |
| **Controller / pengendali** | Shareholder with controlling interest (typically the largest holder in the ownership section) |
| **KSEI** | Indonesian Central Securities Depository — credits HMETD to accounts |
| **POJK 6/2026** | OJK regulation on information conveyors; unlicensed "recommendations" prohibited |

### 19.3 Sample `numbers` event payload (WIFI, illustrative `p_cum`)

```json
{
  "event_id": "WIFI:right_issue:2025-07-02",
  "figures": {
    "rights_entitled":      {"value": 1250,       "unit": "rights", "formula": "floor(shares × new_ratio / old_ratio)", "inputs": {"shares": 1000, "new_ratio": 5, "old_ratio": 4}},
    "cost_to_exercise_all": {"value": 2500000,    "unit": "IDR",    "formula": "rights_entitled × price", "inputs": {"rights_entitled": 1250, "price": 2000}},
    "terp":                 {"value": 2444.44,    "unit": "IDR",    "formula": "(old_ratio × p_cum + new_ratio × price) / (old_ratio + new_ratio)", "inputs": {"p_cum": 3000}},
    "rights_value_total":   {"value": 555555.56,  "unit": "IDR",    "formula": "rights_entitled × max(0, terp − price)"},
    "dilution_if_ignored":  {"value": 0.5556,     "unit": "pct",    "formula": "new_ratio / (old_ratio + new_ratio)"},
    "deadline":             {"value": "2025-07-15","unit": "date",  "formula": "trading_period_end"},
    "days_to_deadline":     {"value": 15,         "unit": "days",   "formula": "deadline − as_of (calendar days)"}
  }
}
```

### 19.4 Sample brief (before placeholder substitution)

```json
{
  "headline_id": "Rights issue WIFI: {{rights_entitled}} HMETD untuk posisimu, batas {{deadline}}",
  "summary_id": "Dengan {{shares}} saham, kamu tercatat berhak atas {{rights_entitled}} HMETD dengan harga pelaksanaan {{price}} per saham. Jika ditebus semuanya, dana yang dibutuhkan {{cost_to_exercise_all}}. Jika HMETD dibiarkan sampai {{deadline}}, hak itu hangus dan porsi kepemilikanmu turun {{dilution_if_ignored}}, dengan nilai teoretis hak sekitar {{rights_value_total}}.",
  "context_ids": ["controller_change", "price_vs_exercise"],
  "verify_id": ["Batas waktu internal broker untuk instruksi penebusan", "Ketentuan pemesanan saham tambahan di prospektus"]
}
```

### 19.5 Template brief (gate fallback, rights issue)
> **ID:** "Kamu tercatat memegang {{shares}} saham {{symbol}}. Rasio {{old_ratio}}:{{new_ratio}} memberi {{rights_entitled}} HMETD dengan harga pelaksanaan {{price}}. Periode perdagangan dan pelaksanaan: {{trading_period_start}}–{{deadline}}. Informasi edukatif, bukan rekomendasi."

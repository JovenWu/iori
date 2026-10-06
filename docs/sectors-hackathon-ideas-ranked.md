# Sectors Hackathon: seven ideas and demo priorities

Prepared for team review on **5 October 2026 (WIB)**. These are subjective product judgments, not measured demand, verified competitor gaps, or a final feature decision.

## Recommendation

Make **user-controlled investigation of earnings and cash-flow changes** the primary workflow. Add **saved research assumptions with manual revisits** as the supporting feature, if reliable persistence is feasible. The story: “Help me interpret a holding's figures, save the evidence and revisit it when I choose.”

Differentiation must come from comparable evidence, structured investigation, chart interactions and preserved research. Renaming a chat command adds little: good prompts already let the team's agent check stock claims.

The provisional audience is **a newer investor holding a few Indonesian stocks who struggles to interpret company figures and keep research organized**. Beginners and shareholders overlap; experienced researchers may prefer deeper comparisons or mining relationships. Validate this audience with real users.

Mining maps are the most distinctive idea in my judgment, but entity and contract risks weaken their deadline fit. Promote them if a useful chain is quickly verifiable and reachable users prefer that problem. If financial comparability fails, simplify to a sourced review. If persistence fails, omit the supporting feature.

## Starting point and boundaries

The team describes a working general agent using Sectors data for Indonesian company and stock analysis. Its implementation, tools, persistence and account access have **not been inspected**. Establish which proposed capabilities actually add to what works.

All exploration is **user initiated**: selecting companies and periods, starting investigations, changing scenarios, saving findings and pressing Recheck. The scope excludes automatic discovery, scheduling, background refresh, autonomous monitoring, notifications and unsolicited action. Charts and filters need no extra confirmation.

The deadline is **8 October 2026, 23:59 WIB**; submitting freezes the repository and application immediately. Judging weights usability 40%, demo/storytelling 30% and technical execution 30%. A working end-to-end prototype with essential Sectors data is required; deployment is optional, with a public repository and working video sufficient for the product gate. The judging video is up to three minutes, plus a public one-minute teaser. Position the product as information and analysis, not investment recommendations; real-account automated trading is prohibited. [Official rules](https://hackathon.sectors.app/rules)

The AI Agents & Assistants track requires an LLM and custom agent logic or orchestration. Purpose-specific workflows, multi-step tool use and state/memory are qualifying directions; connecting an off-the-shelf client through prompts/configuration alone is insufficient. The proposed workspace must therefore demonstrate the team's own orchestration. [AI track requirements](https://hackathon.sectors.app/tracks/ai-agents-assistants)

## Two rankings: practical demo priority and interest

**Demo priority** considers problem clarity, differentiation beyond prompting, visual interaction, agent contribution, data readiness and deadline scope. **Interest rank** emphasizes distinctiveness and exploration potential, discounting delivery risk. Both are subjective.

| Demo priority | Idea | Interest rank | Main tradeoff |
| --- | --- | --- | --- |
| 1 | Investigate earnings and cash-flow changes | 3 | Clear visual question; comparable periods are essential |
| 2 | Track research assumptions | 4 | Persistent workflow value; depends on working storage |
| 3 | Guide company research | 7 | Useful foundation; broad and easy to reproduce in chat |
| 4 | Check stock claims | 6 | Already useful; weak standalone differentiation |
| 5 | Explain watchlist changes | 5 | Strong revisit story; needs a trustworthy baseline |
| 6 | Explore portfolio liquidity under stress | 2 | Engaging scenarios; adds a separate analytical mode |
| 7 | Map mining business dependencies | 1 | Memorable map; highest entity and coverage uncertainty |

Interest order: **mining maps → liquidity scenarios → earnings/cash-flow investigation → research assumptions → watchlist changes → claim checking → guided research**. Choose the demo for a working, understandable workflow.

## All seven ideas

### 1. Check stock claims

**User/problem fit:** Someone encounters a confident statement about an Indonesian stock and wants to inspect the factual evidence before relying on it.

**User action → agent work → visible result:** Paste a claim and select a company/period → the agent separates factual subclaims, retrieves Sectors evidence and investigates counterevidence → a claim table shows supported, contradicted or insufficient evidence, with dates and sources. The user opens a row to inspect its evidence on the dashboard.

**Data needs and minimal demo:** Use one bounded financial claim, two or three subclaims and relevant financial/company records. Match scope, units and dates. Numerical evidence may test a factual premise without establishing a causal explanation or future prediction.

**Pros:** Understandable, bounded and evidence focused; reuses reported existing capability.

**Cons:** The current agent already does this with good prompts. Several other platforms suggested it to the user, raising a competition concern; actual hackathon saturation is unverified. A verdict badge alone does not add much workflow value.

**Demo value:** Include claim checking inside the evidence workspace when useful; do not make it the main headline unless structured review materially improves the user's task.

### 2. Guide company research

**User/problem fit:** A beginner or shareholder knows a ticker but does not know which figures, comparisons or unanswered questions matter.

**User action → agent work → visible result:** Choose a ticker and research question → the agent retrieves trends, proposes suitable peers and checks gaps → stable charts, a comparison table and a sourced brief appear. The user selects a peer or a finding to deepen the investigation.

**Data needs and minimal demo:** One company, a small comparable history and one justified peer. Sectors documents company financials and same-subsector peer information; availability and suitability still require checking. [Company report documentation](https://docs.sectors.app/api-references/v2/indonesia/report/company-report)

**Pros:** Accessible starting point, fits several audiences and supplies the primary workspace's research foundation.

**Cons:** “Research this company” is broad and readily handled by general chat. Long summaries can obscure the actual question; a same-subsector company is not automatically a good comparator.

**Demo value:** Start the earnings investigation with a brief focused on evidence, unresolved questions and the user's next step.

### 3. Explain watchlist changes

**User/problem fit:** A shareholder returns to a small watchlist and wants to understand what differs from the last review.

**User action → agent work → visible result:** Open a saved review and press Recheck → the agent compares the preserved baseline with currently available data → a dated before/after table explains changed figures, unchanged evidence and gaps. The user chooses a difference to investigate.

**Data needs and minimal demo:** One company, one saved baseline and one explicit comparison. Preserve report periods, retrieval times and evidence references. Separate newly available reports, revisions to earlier data and price changes; do not mix their time scales.

**Pros:** Concrete return visit, strong visual comparison and a reason to keep research outside a chat transcript.

**Cons:** Without a baseline it becomes another company summary. Stale data, period mismatches or no new report can weaken the story. A daily market change does not automatically have an explainable business cause.

**Demo value:** Treat this as the comparison behavior of saved research, rather than a third headline. This is a **manual recheck**, with no background monitoring or alerts.

### 4. Track research assumptions

**User/problem fit:** A shareholder forgets why an interpretation seemed plausible or which evidence would weaken it.

**User action → agent work → visible result:** Save an assumption and selected evidence → the agent structures the assumption, period and open questions → a research card persists. On a later user-triggered Recheck, it shows what remains supported, has weakened or is unknown, with reasons and dated evidence.

**Data needs and minimal demo:** One saved card containing the user's wording, company, comparable periods, evidence snapshot/references and unresolved questions; reopen it and perform one recheck.

**Pros:** Creates continuity beyond prompting; makes the evidence workspace useful across visits and gives agent state a clear purpose.

**Cons:** Existing persistence is unverified. Vague assumptions are difficult to evaluate, and status labels can overstate certainty. Users must be able to inspect and edit how their assumption was represented.

**Demo value:** Best supporting feature. Use real historical reports for a clearly labeled replay if needed; never invent a changed finding to demonstrate the recheck.

### 5. Map mining business dependencies

**User/problem fit:** An experienced mining researcher wants to trace documented connections among listed parents, subsidiaries, mine operators and service contractors. A possible question is whether apparently separate watched companies share an underlying operator; that relationship is hypothetical until verified.

**User action → agent work → visible result:** Select a company and expand a relationship → the agent joins documented ownership and contract paths → a map displays entities, edge types, dates and evidence. Clicking an edge opens the supporting records and uncertainties.

**Data needs and minimal demo:** One verified chain between a listed parent, operating entity and contractor. The [Sectors data index](https://docs.sectors.app/llms.txt) lists ownership trees. [Mining contracts documentation](https://docs.sectors.app/api-references/v2/mining/licenses-auctions/mining-contracts) specifies owner/contractor names and slugs, filters and nullable end dates. Documentation examples do not prove a contract is active today.

**Pros:** Most distinctive visual exploration; potentially meaningful multi-source agent work and a memorable demo.

**Cons:** Mapping mining entities to listed parents and verifying current contract coverage are major feasibility gates. A relationship does not establish revenue exposure percentages, material dependence or future stock movement.

**Demo value:** Keep as a later mode unless both evidence and audience fit are already strong. A polished map with uncertain joins would weaken the demo.

### 6. Explore portfolio liquidity under stress

**User/problem fit:** A holder wants to understand how the size of their share positions compares with observed trading activity under chosen volume assumptions.

**User action → agent work → visible result:** Enter share holdings, select a historical window and change an assumed volume level → the app recalculates transparent liquidity indicators while the agent investigates relevant ownership/free-float context and gaps → per-holding charts and a scenario table update.

**Data needs and minimal demo:** Two holdings, a defined historical volume window and one scenario control. Sectors documents [daily close/volume data](https://docs.sectors.app/api-references/v2/indonesia/transaction/daily), [free float](https://docs.sectors.app/api-references/v2/indonesia/screener/free-float) and [shareholder composition](https://docs.sectors.app/api-references/v2/indonesia/company/shareholders-composition). Show holdings divided by assumed daily volume as a scale comparison, not a promised number of days to sell; handle zero volume and verify share/lot units.

**Pros:** Highly interactive, easy to see changes and more concrete than a generic stock explanation.

**Cons:** The calculator alone has a limited agent role. Basic volume screening already exists, including [Stockbit's documented stock screening](https://snips.stockbit.com/investasi/4-alasan-mengapa-pemula-wajib-pilih-saham-yang-likuid). Free float alone is insufficient differentiation. Historical volume does not model order-book depth, price impact or executable liquidity.

**Demo value:** Strong alternative if users prioritize this question; approximate analytical exploration, not execution advice or a liquidation forecast. It adds too much separate scope to the recommended demo.

### 7. Investigate earnings and cash-flow changes

**User/problem fit:** A newer shareholder sees different movements in earnings and operating cash flow and cannot tell what to investigate next.

**User action → agent work → visible result:** Select a company, periods and question, then start investigation → the agent checks comparability, retrieves context and follows evidence → earnings/cash-flow charts, annotations, a justified peer comparison and sourced findings update. The user selects a point, asks a follow-up and saves a finding.

**Data needs and minimal demo:** One suitable company, a few verified comparable periods and one follow-up. Sectors documents earnings, revenue and operating cash flow; fields vary by sector and may be null. Quarterly records cost one credit per quarter returned. [Quarterly financials documentation](https://docs.sectors.app/api-references/v2/indonesia/report/quarterly-financials)

**Pros:** Best balance of understandable problem, visual evidence, agent investigation and bounded scope. It provides a natural home for claims, guided research and saved assumptions.

**Cons:** Check seasonality, sector differences and quarterly versus cumulative conventions. Missing data is not zero. Earnings rising while operating cash flow falls is a question, not evidence of wrongdoing; summary figures alone may not explain the cause.

**Demo value:** Primary workflow. No automatic issue queue: users choose the company and question. Do not promise a divergence or an explanation before observing the data.

## How the focused workspace should work

Start with a small dashboard: company/period selectors, earnings/cash-flow charts, evidence table, saved research and agent input. Users control investigations; chat supports them. Stable layouts keep updates and comparisons understandable.

Give the agent structured context: ticker, period, chart values, question and saved findings. Screenshot interpretation is optional. The app calculates metrics, renders charts and preserves state; the agent chooses follow-up data, justifies comparisons, connects evidence and explains uncertainty. These responsibilities are proposed, not verified existing functions.

Embed claims and guided research in this workflow; manual watchlist comparisons belong to saved research. Keep mining and liquidity as later modes. Seven equal entry points would dilute the problem and burden users.

## Three-minute demo outline and success criteria

Prepare a company and periods from **observed Sectors responses**. If no suitable earnings/cash-flow divergence is verified, demonstrate an honest comparison or another real change. Clearly label any historical replay or illustrative scenario; documentation examples are not live findings.

| Time | Visible action and story |
| --- | --- |
| 0:00–0:20 | State the intended user's problem: interpreting a holding's figures and preserving the reasoning |
| 0:20–0:45 | Select the company and comparable periods; show chart values, units, dates and data gaps |
| 0:45–1:35 | User starts an investigation; agent retrieves evidence and adds a useful annotation or justified comparison |
| 1:35–2:10 | User selects a point and asks a follow-up; show evidence that supports or limits the explanation |
| 2:10–2:45 | Save one assumption, reopen it and press Recheck; show genuine changes or honestly report no new evidence |
| 2:45–3:00 | State the concrete result: a sourced interpretation, unresolved question and reusable research record |

Label revisits using older reports as a **historical replay**, not a live update. Without persistence, show a second user-directed comparison instead. Cut a one-minute teaser from the clearest working interactions.

Success means users complete a review without elaborate prompts; charts match retrieved records; explanations distinguish facts, hypotheses and gaps; follow-ups visibly improve the workspace; and saved research, if included, survives reopening. The agent contributes an evidence step beyond charting. Refreshes and investigations require user action. Removing Sectors data must remove the core workflow.

## Consequential team decisions and validation gates

1. **Reachable users:** Confirm that newer shareholders actually struggle with these two tasks. If experienced mining researchers are easier to reach and need relationship tracing, reconsider the audience and primary workflow together.
2. **Actual tools and coverage:** Inventory the existing agent's tools and test account access for the chosen companies and periods. Documentation confirms interfaces, not coverage, freshness or this project's access tier. Prefer a narrow verified dataset over several speculative modes.
3. **Persistence:** Prove that one research card can be saved, reopened and rechecked without losing its baseline. If it cannot, remove the supporting feature from the demo claim.
4. **Comparable periods:** Verify units, report dates, sector conventions, quarter/cumulative treatment and null handling before telling the story. If these cannot be resolved, use a simpler sourced review and state the gaps.
5. **Submission status:** Establish whether the project has already been submitted and frozen before implementation proceeds. The freeze begins at submission or the deadline, whichever comes first. [Official freeze rule](https://hackathon.sectors.app/rules)

# Data Visualization — Design

Automatically create interactive charts when a query returns chartable
financial data. JEV judges chartability and picks a predefined view per tool
result; code builds a normalized chart spec; specs stream over SSE, persist in
the LangGraph checkpoint, and render as purpose-built recharts components.

Decisions locked with the user: **JEV judgment** for detection, **persist in
checkpoint** for history, **all feasible tools** in scope, **recharts** on the
frontend.

## Approach

Chosen: JEV-judged, graph-resident detection.

- Rejected — agent-authored charts (`render_chart` tool / structured output):
  burns generation tokens, unreliable JSON, no guaranteed mapping to
  predefined components.
- Rejected — frontend-side detection (stream raw tool payloads): ships large
  envelopes to clients, no judgment layer, persistence awkward.

## Pipeline

The prebuilt `ToolNode` is replaced by a custom `tools` node in
`app/agent/graph.py`. Topology is unchanged: `agent ⇄ tools`.

Per ToolMessage produced by a chartable tool:

1. Parse the JSON envelope. Skip on `status != "ok"`, `truncated: true`, or
   non-structured `data` — never spend a judgment on junk.
2. Build a compact preview for JEV: tool name, the user's question, `data`
   shape (keys, row count, first few rows) — not the full payload.
3. One `jev_ask` call asks in parallel:
   - `chartable`: `Noul` — "Would a chart make this result meaningfully
     clearer for the user's question?"
   - `view`: `Choice` — options are the tool's registered views plus `none`.
4. `chartable >= 0.5` and `view != "none"` → the view's deterministic
   extractor builds a spec from the envelope `data`.
5. Append `{anchor, **spec}` to `state["charts"]` where `anchor` is the
   ToolMessage's index in `messages` (pre-node length + position in the
   ToolNode result).

Tools with no registered views (`news`, `insider_filings`, `suspensions`,
`corporate_actions`) are skipped before step 2 — zero JEV spend.

`jev_ask` returning `None` (unconfigured/failed) → no chart, same fail-closed
pattern as the router and context gates.

## State & persistence

```python
class ChatState(TypedDict):
    ...
    charts: Annotated[list[dict[str, Any]], operator.add]
```

`charts` rides the existing `AsyncPostgresSaver` checkpointer — reloads and
thread reopening restore charts with no new tables. `anchor` is stable because
`messages` is append-only (summarization never trims; if trimming is ever
added, anchors must be remapped).

## Streaming

`run_turn` already iterates `updates`. When the tools-node update contains
`charts`, emit one `chart` SSE event per appended spec:

```
data: {"seq": n, "type": "chart", "data": {spec}}
```

Replay/reattach works for free via the run buffer.

## History serialization

`get_thread_messages` walks messages with indices. A chart attaches to the
first `AIMessage` with string content at an index greater than its `anchor`
(i.e., the assistant answer that closed that turn). Serialized shape per
message: `{role, content, charts?: [...]}`.

## Spec schema

```ts
type ChartSpec = {
  id: string;            // unique per spec
  tool: string;          // e.g. "sectors_daily_prices"
  view: string;          // registry key, e.g. "price_volume"
  kind: "line" | "area" | "bar" | "diverging_bar" | "grouped_bar" | "pie";
  title: string;
  x: { key: string; label: string; type: "time" | "category" };
  series: { key: string; label: string }[];
  data: Record<string, string | number | null>[];
  fetched_at: string;    // from the envelope — rendered as a caption
};
```

`view` selects the purpose-built component; `kind` is the generic fallback so
an unknown view still renders something sane.

## Per-tool view registry

New module `app/sectors/charts.py` — sectors data-shape knowledge stays with
the sectors module. Each entry: `{view_key: {description_for_jev, extractor}}`.

| Tool | Views | Chart |
| --- | --- | --- |
| sectors_daily_prices | `price_volume` | close line + volume bars |
| sectors_top_movers | `movers` | diverging horizontal bar per class/period |
| sectors_most_traded | `traded_bars` | ranked volume/value bars |
| sectors_foreign_flow | `netflow` | net foreign flow area/bars over time |
| sectors_idx_market_summary | `mcap_area` | total market cap area over time |
| sectors_quarterly_financials | `quarterly_grouped` | revenue vs net income grouped bars |
| sectors_broker_summary | `broker_net_bars` | net buy/sell per broker |
| sectors_broker_top | `broker_rank_bars` | ranked broker bars |
| sectors_listing_performance | `perf_line` | price since listing |
| sectors_screen | `ranked_metric` | bar of the `order_by` metric per symbol |
| sectors_company_report | `financials_trend`, `peers_bar`, `dividend_history` | per sections present in the result |
| sectors_subsector_report | `mcap_share`, `companies_bar` | composition donut / member bars |
| sectors_list_subsectors | `subsector_mcap` | bar — only if the payload carries a metric |

Extractor field names are verified against real Sectors API responses during
implementation; an extractor that can't find its fields returns `None`.

## Frontend

- Add `recharts` (React-19-compatible release, ≥7 days old).
- `components/charts/` — `ChartBlock` dispatcher keyed by `view` →
  purpose-built cards (`PriceVolumeChart`, `MoversBar`, `NetFlowArea`,
  `QuarterlyBars`, `BrokerBars`, `RankedBar`, `MarketCapArea`, `PerfLine`,
  `ShareDonut`, `FinancialsTrend`), falling back to generic `kind` renderers.
- Shared `ChartCard` shell: title, `fetched_at` caption, dark canvas +
  lavender accent per DESIGN.md. Interactivity: recharts `Tooltip` on all;
  `Brush` zoom on time-series charts.
- `Message.charts?: ChartSpec[]` — rendered below the assistant markdown,
  inside `AssistantMessage`.
- `chat.ts` store: `chart` events append to the current assistant message's
  `charts`; `toMessages` passes through `charts` from history. `StreamEvent`
  union gains `"chart"`.
- `lib/api.ts`: `ChatMessage` gains `charts?: ChartSpec[]`; spec types live in
  `lib/charts.ts` shared by store and components.

## Error handling

- JEV `None` / noul < 0.5 / `view == "none"` → no chart.
- Envelope error status, `truncated`, or string `data` → skipped pre-JEV.
- Extractor returns `None` or raises → logged, no chart; the turn is never
  affected.
- Chart specs never enter `messages` — zero context pollution for the model.

## Latency

One JEV call per chartable tool result, inside the `tools` node, delaying the
agent's resume by ~one judgment — the same cost model already accepted in
`context_manager` + `router`. If it proves slow, judging can move to a
parallel service-layer task (specs collected on the run, persisted post-turn
via `aupdate_state`) with no spec or frontend changes.

## Testing

- `tests/test_charts.py`: extractor output from fixture envelopes; JEV mocked
  to return chartable/none/`None`; truncated + error envelopes skipped;
  reducer accumulates across tool loops.
- `test_agent_graph.py`: updated for the custom tools node; assert `charts`
  appended and anchored.
- History: `get_thread_messages` attaches a chart to the correct assistant
  message when a turn has multiple messages.
- Frontend: `npx tsc --noEmit`, `npx eslint .`, `npm run build` in the
  frontend container.

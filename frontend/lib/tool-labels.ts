/* Tool name → verb phrase for the status line ("Fetching daily prices…",
   never "tool_call sectors_daily_prices"). The raw name rides along in mono. */

const LABELS: Record<string, string> = {
  sectors_screen: "Screening stocks",
  sectors_company_report: "Fetching company report",
  sectors_subsector_report: "Fetching subsector report",
  sectors_quarterly_financials: "Fetching quarterly financials",
  sectors_daily_prices: "Fetching daily prices",
  sectors_idx_market_summary: "Fetching market summary",
  sectors_most_traded: "Fetching most-traded stocks",
  sectors_top_movers: "Ranking top movers",
  sectors_foreign_flow: "Fetching foreign flow",
  sectors_news: "Scanning news",
  sectors_broker_summary: "Fetching broker summary",
  sectors_broker_top: "Ranking top brokers",
  sectors_insider_filings: "Scanning insider filings",
  sectors_suspensions: "Checking suspensions",
  sectors_corporate_actions: "Checking corporate actions",
  sectors_listing_performance: "Checking listing performance",
  sectors_list_subsectors: "Listing subsectors",
};

export function verbFor(tool: string): string {
  return (
    LABELS[tool] ??
    `Running ${tool.replace(/^sectors_/, "").replaceAll("_", " ")}`
  );
}

/* Args → short caption shown next to the label ("Fetching foreign flow BBCA").
   Picks the arg that identifies the subject; everything else is noise. */
const DETAIL_KEYS = ["symbol", "sub_sector", "symbols", "q", "keyword", "where"];

export function detailFor(
  args?: Record<string, unknown> | null,
): string | null {
  if (!args) return null;
  for (const key of DETAIL_KEYS) {
    const v = args[key];
    if (typeof v === "string" && v.trim()) {
      const s = v.trim();
      return s.length > 28 ? `${s.slice(0, 28)}…` : s;
    }
  }
  return null;
}

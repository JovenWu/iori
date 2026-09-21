/* Tool name → verb phrase for the status line ("Fetching daily prices…",
   never "tool_call sectors_daily_prices"). The raw name rides along in mono. */

const LABELS: Record<string, string> = {
  sectors_screen: "Screening IDX companies",
  sectors_company_report: "Pulling the company report",
  sectors_subsector_report: "Pulling the subsector report",
  sectors_quarterly_financials: "Pulling quarterly financials",
  sectors_daily_prices: "Fetching daily prices",
  sectors_idx_market_summary: "Fetching the market summary",
  sectors_most_traded: "Fetching the most-traded list",
  sectors_top_movers: "Ranking top movers",
  sectors_foreign_flow: "Tracing foreign flow",
  sectors_news: "Scanning the news",
  sectors_broker_summary: "Fetching the broker summary",
  sectors_broker_top: "Ranking broker flow",
  sectors_insider_filings: "Scanning insider filings",
  sectors_suspensions: "Checking suspensions",
  sectors_corporate_actions: "Reading corporate actions",
  sectors_listing_performance: "Checking listing performance",
  sectors_list_subsectors: "Listing subsectors",
};

export function verbFor(tool: string): string {
  return (
    LABELS[tool] ??
    `Running ${tool.replace(/^sectors_/, "").replaceAll("_", " ")}`
  );
}

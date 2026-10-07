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
  sectors_company_segments: "Fetching segment breakdown",
  sectors_companies_with_segments: "Checking segment coverage",
  sectors_index_daily: "Fetching index history",
  sectors_index_universe: "Fetching index board",
  sectors_market_close: "Fetching market-close board",
  sectors_shareholders: "Fetching shareholder mix",
  sectors_company_corporate_actions: "Fetching corporate actions",
  sectors_quarterly_dates: "Resolving report periods",
  sectors_broker_registry: "Fetching broker registry",
  sectors_broker_activity: "Fetching broker activity",
  sectors_broker_activity_top: "Fetching top broker trades",
  sectors_top_brokers: "Ranking top brokers",
  sectors_foreign_flow_universe: "Fetching foreign-flow board",
  sectors_free_float: "Fetching free-float data",
  sectors_list_industries: "Listing industries",
  sectors_list_subindustries: "Listing sub-industries",
  sectors_list_tags: "Listing stock tags",
  sectors_compare: "Comparing tickers",
  sectors_mining_companies: "Searching mining companies",
  sectors_mining_company_detail: "Fetching mining company",
  sectors_mining_company_performance: "Fetching mine performance",
  sectors_commodity_prices: "Fetching commodity prices",
  sectors_mining_sites: "Listing mining sites",
  sectors_mining_exports: "Fetching export destinations",
  sectors_global_commodity: "Fetching global commodity data",
  aksi_calc: "Computing your figures",
  aksi_investigate: "Investigating",
  aksi_brief: "Writing brief",
  aksi_impact: "Computing corporate-action impact",
  aksi_check: "Checking corporate actions",
  aksi_report: "Reading a saved check",
  aksi_reports: "Listing past checks",
  holdings_list: "Reading holdings",
  holdings_save: "Saving holdings",
  holdings_remove: "Removing holding",
  compute: "Computing",
};

export function verbFor(tool: string): string {
  return (
    LABELS[tool] ??
    `Running ${tool.replace(/^sectors_/, "").replaceAll("_", " ")}`
  );
}

/* Args → short caption shown next to the label ("Fetching foreign flow BBCA").
   Subject identifiers first; scope keys (date, sector, metric…) only when no
   subject arg exists. Everything else is noise. */
const DETAIL_KEYS = [
  "symbol",
  "symbols",
  "sub_sector",
  "index_code",
  "broker_code",
  "expression",
  "q",
  "keyword",
  "where",
  "date",
  "report_date",
  "financial_year",
  "year",
  "metric",
  "cohort",
  "origin",
  "sector",
  "industry",
  "sub_industry",
];

export function detailFor(
  args?: Record<string, unknown> | null,
): string | null {
  if (!args) return null;
  for (const key of DETAIL_KEYS) {
    const v = args[key];
    const s =
      typeof v === "string"
        ? v.trim()
        : typeof v === "number" && Number.isFinite(v)
          ? String(v)
          : "";
    if (s) return s.length > 28 ? `${s.slice(0, 28)}…` : s;
  }
  return null;
}

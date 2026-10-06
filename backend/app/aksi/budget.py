"""Per-run credit accounting — only upstream (non-cache) responses cost."""

DEFAULT_BUDGET = 25

_COST = {
    "sectors_company_corporate_actions": 1,
    "sectors_insider_filings": 1,
    "sectors_shareholders": 1,
    "sectors_daily_prices": 1,
    "sectors_news": 1,
    "sectors_broker_top": 2,
}


def estimate(name: str, args: dict) -> int:
    if name == "sectors_corporate_actions":
        return max(1, len(args.get("types") or []))
    if name == "sectors_company_report":
        return max(1, len(args.get("sections") or []))
    return _COST.get(name, 1)


def cost(name: str, args: dict, envelope: dict) -> int:
    return estimate(name, args) if envelope.get("source") == "upstream" else 0

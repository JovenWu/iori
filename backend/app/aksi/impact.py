"""Single-holding impact without an LLM — backs POST /aksi/impact and the
chat agent's `aksi_impact` tool. Same calendar + calculators as the graph."""

from datetime import date, timedelta

from app.aksi import calc, events, findings, sources

NOTE = "Informasi edukatif, bukan rekomendasi investasi."


async def impact(symbol: str, shares: int, as_of: date | None = None) -> dict:
    day = as_of or events.today_wib()
    start, end = events.scan_window(day)
    cal = await sources.calendar(events.KINDS, start, end)
    data = cal.get("data")
    found = events.normalize(data if isinstance(data, dict) else {},
                             [{"symbol": symbol, "shares": shares}], day)
    out = []
    if found:
        prices = await sources.daily_prices(
            symbol, (day - timedelta(days=89)).isoformat(), day.isoformat())
        price_rows = findings.rows(prices)
        out = [{"event": events.public(ev), "figures": calc.figures_for(ev, price_rows, day)}
               for ev in found]
    return {"symbol": symbol, "as_of": day.isoformat(), "events": out,
            "fetched_at": cal.get("fetched_at"), "note": NOTE,
            "upstream_error": cal.get("status") != 200}

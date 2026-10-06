"""`aksi_impact` — corporate-action impact for one holding, for the chat agent.

Deterministic: same calendar + calculators as the Aksi page, no LLM inside.
"""

import json
import re
from datetime import date

from langchain_core.tools import tool

from app.aksi import impact

_SYMBOL = re.compile(r"^[A-Z]{4}$")


@tool
async def aksi_impact(symbol: str, shares: int, as_of: str | None = None) -> str:
    """Corporate actions (rights issue/HMETD, dividends, warrants) affecting a
    holding, with the holder's personal figures computed in code: rights
    entitled, cost to exercise, theoretical ex-rights price, dilution if
    ignored, gross dividend, deadlines. Use for any holder-specific number —
    never compute these mentally. Never advise buying, selling or exercising.

    Args:
        symbol: IDX ticker, e.g. WIFI.
        shares: Number of shares held (lembar; 1 lot = 100 shares).
        as_of: Optional YYYY-MM-DD for a historical replay (default: today).
    """
    sym = symbol.strip().upper().removesuffix(".JK")
    if not _SYMBOL.match(sym) or shares < 1:
        return json.dumps({"error": "invalid_input"})
    try:
        day = date.fromisoformat(as_of) if as_of else None
    except ValueError:
        return json.dumps({"error": "invalid_date"})
    return json.dumps(await impact.impact(sym, shares, day), default=str)

"""One-off data check for the Aksi Korporasi feature (~13 credits cold).

Requests exactly what the feature requests for the live scan and the WIFI
replay (same paths + params → same cache keys), so the demo later replays from
the permanent cache for free. Prints a compact report.

Run: docker compose exec backend python -m scripts.aksi_data_check
"""

import asyncio
import json
from datetime import date, datetime, timedelta

from app.sectors import cache, client
from app.sectors.freshness import WIB, Freshness

KINDS = "dividend,right_issue,upcoming_dividend,warrant"  # sorted, as the feature sends them
REPLAY_AS_OF = date(2025, 7, 10)


def _window(as_of: date) -> dict:
    return {
        "start": (as_of - timedelta(days=30)).isoformat(),
        "end": (as_of + timedelta(days=60)).isoformat(),
        "type": KINDS,
    }


CHECKS = [
    ("calendar_live", "corporate_actions", "/v2/corporate-actions/",
     _window(datetime.now(WIB).date()), Freshness.EOD, 4),
    ("calendar_replay", "corporate_actions", "/v2/corporate-actions/",
     _window(REPLAY_AS_OF), Freshness.EOD, 4),
    ("wifi_actions", "company_corporate_actions",
     "/v2/company/corporate-actions/WIFI/", {}, Freshness.EOD, 1),
    ("wifi_prices", "daily", "/v2/daily/WIFI/",
     {"start": (REPLAY_AS_OF - timedelta(days=89)).isoformat(),
      "end": REPLAY_AS_OF.isoformat()}, Freshness.EOD, 1),
    ("wifi_filings", "filings", "/v2/filings/",
     {"limit": 30, "symbol": "WIFI",
      "start": (REPLAY_AS_OF - timedelta(days=45)).isoformat(),
      "end": REPLAY_AS_OF.isoformat()}, Freshness.NEWS, 1),
    ("wifi_shareholders", "shareholders",
     "/v2/company/shareholders-composition/WIFI/", {"year": 2025},
     Freshness.HISTORICAL, 1),
    ("wifi_ownership", "company_report", "/v2/company/report/WIFI/",
     {"sections": "ownership"}, Freshness.EOD, 1),
]


def _describe(data) -> str:
    if isinstance(data, list):
        return f"{len(data)} rows"
    if isinstance(data, dict):
        return ", ".join(
            f"{k}:{len(v)}" if isinstance(v, list) else k for k, v in data.items()
        )
    return type(data).__name__


async def main() -> None:
    client.init_client()
    try:
        for label, endpoint, path, params, freshness, credits in CHECKS:
            res = await cache.cached_get(
                endpoint, path, params, freshness, credits=credits
            )
            print(f"\n== {label}: status={res.status} source={res.source} "
                  f"{_describe(res.data)}")
            if label.startswith("calendar") and isinstance(res.data, dict):
                for kind in ("right_issue", "warrant"):
                    for row in res.data.get(kind) or []:
                        print(f"   {kind}: {json.dumps(row, default=str)}")
            else:
                print("   " + json.dumps(res.data, default=str)[:1500])
    finally:
        await client.close_client()


if __name__ == "__main__":
    asyncio.run(main())

"""Brief gate — deterministic checks first, then one JEV judgment.

The LLM may only write placeholders (`{{name}}`) for numbers and dates; any
digit, advice word, unknown placeholder or unknown finding id rejects the
draft. JEV then checks for advice language and grounding (fail-open when JEV
is unavailable — the deterministic checks already ran).
"""

import re

from app.core.jev import Noul, jev_ask

BANNED = (
    "sebaiknya", "disarankan", "rekomendasi", "saran", "layak", "wajib", "harus",
    "jangan", "segera", "tahan", "beli sekarang", "jual sekarang", "cuan",
    "untung pasti", "should", "must", "recommend", "advise", "worth it",
    "buy now", "sell now",
)
_BANNED_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in BANNED) + r")\b", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
_DIGIT_RE = re.compile(r"\d")
TEXT_FIELDS = ("headline_id", "headline_en", "summary_id", "summary_en")
LIST_FIELDS = ("verify_id", "verify_en")


def _texts(brief: dict) -> list[str]:
    return [str(brief.get(k) or "") for k in TEXT_FIELDS] + [
        str(x) for k in LIST_FIELDS for x in (brief.get(k) or [])
    ]


def check(brief: dict, allowed: set[str], finding_ids: set[str]) -> list[str]:
    reasons: set[str] = set()
    for text in _texts(brief):
        if _DIGIT_RE.search(PLACEHOLDER_RE.sub("", text)):
            reasons.add("digits_outside_placeholders")
        for name in PLACEHOLDER_RE.findall(text):
            if name not in allowed:
                reasons.add(f"unknown_placeholder:{name}")
        for match in _BANNED_RE.findall(text):
            reasons.add(f"banned_phrase:{match.lower()}")
    for fid in brief.get("context_ids") or []:
        if fid not in finding_ids:
            reasons.add(f"unknown_finding:{fid}")
    return sorted(reasons)


async def judge(summary: str, evidence: list[str]) -> list[str]:
    result = await jev_ask(
        {"brief": summary, "evidence": evidence},
        {
            "advice": Noul(instructions=(
                "Does the brief urge or advise the reader to buy, sell, hold, "
                "exercise, or not exercise a security?")),
            "grounded": Noul(instructions=(
                "Is every statement in the brief supported by the evidence list?")),
        },
    )
    if result is None:
        return []
    reasons = []
    advice = result.nouls.get("advice")
    grounded = result.nouls.get("grounded")
    if advice is not None and float(advice.noul) >= 0.3:
        reasons.append("advice_language")
    if grounded is not None and float(grounded.noul) < 0.6:
        reasons.append("ungrounded")
    return reasons

"""Brief gate — deterministic checks first, then one JEV judgment.

The LLM may only write placeholders (`{{name}}`) for numbers and dates; any
digit, advice word, unknown placeholder or unknown finding id rejects the
draft. JEV then checks for advice language and grounding (fail-open when JEV
is unavailable — the deterministic checks already ran).
"""

import re

from app.core.jev import Noul, jev_ask

# Spec §9.9 banned list — bare advice verbs included; descriptive passives
# ("diperdagangkan", "dijual", "holdings") stay allowed via word boundaries.
BANNED = (
    "sebaiknya", "disarankan", "rekomendasi", "saran", "layak", "wajib", "harus",
    "jangan", "segera", "tahan", "beli", "jual", "cuan",
    "untung pasti", "should", "must", "recommend", "advise", "worth it",
    "buy", "sell", "hold", "exercise now", "buy now", "sell now",
)
_BANNED_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in BANNED) + r")\b", re.IGNORECASE)

# Any {{...}} is a placeholder-shaped token — an unknown one must reject the
# draft, not slip through because its name isn't [a-z_].
PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}\s][^{}]*?)\s*\}\}")
_DIGIT_RE = re.compile(r"\d")

# Spelled-out numbers smuggle fabricated figures past the digit gate — a run
# of number words ("tiga puluh lima"), a lone magnitude ("sejuta", "juta"),
# or a thousand-style token. Prose false-positives just fall back to the
# template — the safe direction.
_NUM_WORD = (
    r"nol|satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh|"
    r"sebelas|belas|puluh|ratus|ribu|juta|miliar|milyar|triliun|setengah|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"thousand|million|billion|trillion"
)
_MAGNITUDE = (
    r"ratus|ribu|juta|miliar|milyar|triliun|puluh|belas|"
    r"seratus|seribu|sejuta|semiliar|setriliun|sepuluh|sebelas|"
    r"hundred|thousand|million|billion|trillion"
)
_SPELLED_RE = re.compile(
    rf"\b(?:{_NUM_WORD})\b(?:[\s\-]+(?:{_NUM_WORD})\b)+"
    rf"|\b(?:{_MAGNITUDE})\b",
    re.IGNORECASE,
)

TEXT_FIELDS = ("headline_id", "headline_en", "summary_id", "summary_en")
LIST_FIELDS = ("verify_id", "verify_en")


def _texts(brief: dict) -> list[str]:
    return [str(brief.get(k) or "") for k in TEXT_FIELDS] + [
        str(x) for k in LIST_FIELDS for x in (brief.get(k) or [])
    ]


def check(brief: dict, allowed: set[str], finding_ids: set[str]) -> list[str]:
    reasons: set[str] = set()
    for text in _texts(brief):
        stripped = PLACEHOLDER_RE.sub("", text)
        if _DIGIT_RE.search(stripped):
            reasons.add("digits_outside_placeholders")
        if _SPELLED_RE.search(stripped):
            reasons.add("spelled_out_number")
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
        # JEV unavailable — fail closed. The draft is unjudged, so it falls
        # back to the deterministic template rather than shipping unreviewed
        # LLM copy (POJK gate).
        return ["jev_unavailable"]
    reasons = []
    advice = result.nouls.get("advice")
    grounded = result.nouls.get("grounded")
    if advice is not None and float(advice.noul) >= 0.3:
        reasons.append("advice_language")
    if grounded is not None and float(grounded.noul) < 0.6:
        reasons.append("ungrounded")
    return reasons

"""Briefs: the LLM drafts with placeholders only; code fills every number.

`produce` runs draft → gate → (one retry with the rejection reasons) → and
falls back to a fixed template, so a brief always exists and never carries an
LLM-written number or advice.
"""

import json
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.aksi import fmt, gate
from app.core.config import settings
from app.core.llm import get_chat_model

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parent.parent / "prompts" / "aksi_brief.md").read_text(encoding="utf-8")

_ROW_MONEY = ("price", "dividend_amount")
_ROW_NUMBER = ("old_ratio", "new_ratio")
_ROW_DATES = (
    "cum_date", "ex_date", "recording_date", "trading_period_start", "trading_period_end",
    "payment_date", "ex_per_start", "ex_per_end", "maturity_date",
)


class BriefDraft(BaseModel):
    headline_id: str = Field(description="Indonesian headline, at most 12 words, no digits")
    headline_en: str = Field(description="English headline, at most 12 words, no digits")
    summary_id: str = Field(description="Indonesian summary, at most 90 words, no digits")
    summary_en: str = Field(description="English summary, at most 90 words, no digits")
    context_ids: list[str] = Field(default_factory=list)
    verify_id: list[str] = Field(default_factory=list)
    verify_en: list[str] = Field(default_factory=list)


_writer = get_chat_model(
    settings.MODEL_NAME, temperature=0.2, timeout=60, max_retries=1, reasoning_effort="none",
).with_structured_output(BriefDraft)

TEMPLATES: dict[str, dict] = {
    "right_issue": {
        "headline_id": "Rights issue {{symbol}}: {{rights_entitled}} HMETD untuk posisimu",
        "headline_en": "{{symbol}} rights issue: {{rights_entitled}} rights for your position",
        "summary_id": (
            "Dengan {{shares}} saham, kamu tercatat berhak atas {{rights_entitled}} HMETD "
            "(rasio {{old_ratio}}:{{new_ratio}}) dengan harga pelaksanaan {{price}}. Menebus "
            "semua hak membutuhkan {{cost_to_exercise_all}}. HMETD dapat diperdagangkan atau "
            "dilaksanakan sampai {{trading_period_end}}; jika dibiarkan, hak hangus dan porsi "
            "kepemilikan turun {{dilution_if_ignored}}."
        ),
        "summary_en": (
            "With {{shares}} shares you are entitled to {{rights_entitled}} rights (ratio "
            "{{old_ratio}}:{{new_ratio}}) at an exercise price of {{price}}. Exercising all of "
            "them costs {{cost_to_exercise_all}}. Rights can be traded or exercised until "
            "{{trading_period_end}}; if left alone they lapse and your ownership falls by "
            "{{dilution_if_ignored}}."
        ),
        "verify_id": ["Batas waktu internal broker untuk instruksi penebusan",
                      "Ketentuan pemesanan saham tambahan di prospektus"],
        "verify_en": ["Your broker's internal cut-off for exercise instructions",
                      "Additional-share subscription terms in the prospectus"],
    },
    "dividend": {
        "headline_id": "Dividen {{symbol}}: {{gross_dividend}} bruto untuk posisimu",
        "headline_en": "{{symbol}} dividend: {{gross_dividend}} gross for your position",
        "summary_id": (
            "Dividen {{dividend_amount}} per saham. Untuk {{shares}} saham, jumlah bruto "
            "{{gross_dividend}}. Tanggal cum {{cum_date}}, pembayaran {{payment_date}}. "
            "Jumlah bersih tergantung status pajakmu."
        ),
        "summary_en": (
            "Dividend of {{dividend_amount}} per share. For {{shares}} shares the gross amount "
            "is {{gross_dividend}}. Cum date {{cum_date}}, payment {{payment_date}}. The net "
            "amount depends on your tax status."
        ),
        "verify_id": ["Ketentuan pajak dividen yang berlaku untukmu (DJP)"],
        "verify_en": ["Dividend tax rules that apply to you (DJP)"],
    },
    "warrant": {
        "headline_id": "Waran {{symbol}}: harga pelaksanaan {{price}}",
        "headline_en": "{{symbol}} warrant: exercise price {{price}}",
        "summary_id": (
            "Periode pelaksanaan waran berakhir {{deadline}}. Nilai intrinsik per waran saat "
            "ini {{intrinsic_per_warrant}}. Waran yang tidak dilaksanakan sampai jatuh tempo "
            "menjadi tidak bernilai."
        ),
        "summary_en": (
            "The warrant exercise period ends {{deadline}}. Current intrinsic value per warrant "
            "is {{intrinsic_per_warrant}}. Warrants not exercised by maturity expire worthless."
        ),
        "verify_id": ["Rasio dan ketentuan waran di prospektus"],
        "verify_en": ["Warrant ratio and terms in the prospectus"],
    },
}


def placeholder_values(ev: dict, figures: dict, lang: str) -> dict[str, str]:
    row = ev["row"]
    values = {"symbol": ev["symbol"], "shares": fmt.number(ev["shares"], lang)}
    for key in _ROW_MONEY:
        if row.get(key) is not None:
            try:
                values[key] = fmt.idr(row[key], lang)
            except Exception:
                pass  # unformattable → key absent → drafts using it get rejected
    for key in _ROW_NUMBER:
        if row.get(key) is not None:
            try:
                values[key] = fmt.number(row[key], lang)
            except Exception:
                pass
    for key in _ROW_DATES:
        if row.get(key):
            values[key] = fmt.day(row[key], lang)
    for key, fig in figures.items():
        values[key] = fmt.figure(fig, lang)
    return values


def allowed_placeholders(ev: dict, figures: dict) -> set[str]:
    return set(placeholder_values(ev, figures, "id"))


def render(draft: dict, ev: dict, figures: dict) -> dict:
    vid = placeholder_values(ev, figures, "id")
    ven = placeholder_values(ev, figures, "en")

    def sub(text: str, values: dict[str, str]) -> str:
        return gate.PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), "—"), text)

    return {
        "headline_id": sub(draft["headline_id"], vid),
        "headline_en": sub(draft["headline_en"], ven),
        "summary_id": sub(draft["summary_id"], vid),
        "summary_en": sub(draft["summary_en"], ven),
        "verify_id": [sub(x, vid) for x in draft.get("verify_id") or []],
        "verify_en": [sub(x, ven) for x in draft.get("verify_en") or []],
        "context_ids": list(draft.get("context_ids") or []),
    }


def template(ev: dict) -> dict:
    return {**TEMPLATES[ev["kind"]], "context_ids": []}


async def write(ev: dict, figures: dict, found: list[dict],
                feedback: list[str] | None = None) -> dict | None:
    payload = {
        "event": {"symbol": ev["symbol"], "kind": ev["kind"], "phase": ev["phase"]},
        "placeholders": sorted(allowed_placeholders(ev, figures)),
        "figures": {k: {"formula": v["formula"], "missing": v["gap"] is not None}
                    for k, v in figures.items()},
        "findings": [{"id": f["id"], "kind": f["kind"]} for f in found],
        "feedback": feedback or [],
    }
    try:
        draft = await _writer.ainvoke(
            [SystemMessage(content=_PROMPT), HumanMessage(content=json.dumps(payload))]
        )
    except Exception:
        logger.warning("aksi brief: writer failed", exc_info=True)
        return None
    return draft.model_dump()


async def produce(ev: dict, figures: dict, found: list[dict]) -> dict:
    allowed = allowed_placeholders(ev, figures)
    finding_ids = {f["id"] for f in found}
    feedback: list[str] | None = None
    reasons: list[str] = []
    accepted: dict | None = None
    for _ in range(2):
        draft = await write(ev, figures, found, feedback)
        if draft is None:
            reasons = ["writer_unavailable"]
            break
        reasons = gate.check(draft, allowed, finding_ids)
        if not reasons:
            # Judge every user-visible field, not just summary_id — advice can
            # hide in a headline or a verify bullet just as easily.
            rendered = render(draft, ev, figures)
            joined = "\n".join(
                [
                    rendered["headline_id"], rendered["headline_en"],
                    rendered["summary_id"], rendered["summary_en"],
                    *rendered["verify_id"], *rendered["verify_en"],
                ]
            )
            reasons = await gate.judge(joined, [f.get("text_id", "") for f in found])
        if not reasons:
            accepted = draft
            break
        feedback = reasons
    out = render(accepted or template(ev), ev, figures)
    if accepted is None:
        out["context_ids"] = [f["id"] for f in found]
    out["gate"] = {"passed": accepted is not None, "reasons": reasons,
                   "template": accepted is None}
    return out

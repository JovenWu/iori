from datetime import date
from types import SimpleNamespace

import pytest

from app.aksi import briefs, calc, gate

AS_OF = date(2025, 7, 10)
WIFI = {"symbol": "WIFI.JK", "ex_date": "2025-07-02", "cum_date": "2025-07-01",
        "recording_date": "2025-07-03", "trading_period_start": "2025-07-07",
        "trading_period_end": "2025-07-15", "subscription_date": "2025-07-03",
        "price": 2000, "old_ratio": 4, "new_ratio": 5}
EV = {"id": "WIFI:right_issue:2025-07-02", "symbol": "WIFI", "kind": "right_issue",
      "row": WIFI, "shares": 1000, "phase": "window_open"}
DIV_EV = {"id": "BBMD:dividend:2025-07-14", "symbol": "BBMD", "kind": "dividend", "shares": 5000,
          "phase": "before_cum", "row": {"symbol": "BBMD.JK", "ex_date": "2025-07-14",
          "cum_date": "2025-07-11", "recording_date": "2025-07-15",
          "payment_date": "2025-07-25", "dividend_amount": 34.25}}
WAR_EV = {"id": "ABCD:warrant:2025-01-10", "symbol": "ABCD", "kind": "warrant", "shares": 1000,
          "phase": "window_open", "row": {"symbol": "ABCD.JK", "trading_period_start": "2025-01-10",
          "ex_per_start": "2025-07-01", "ex_per_end": "2026-01-09",
          "maturity_date": "2026-01-09", "price": 150}}
PRICES = [{"date": "2025-07-01", "close": 3000}, {"date": "2025-07-09", "close": 180}]
FIGS = calc.figures_for(EV, PRICES, AS_OF)


def good_draft() -> dict:
    return {
        "headline_id": "HMETD {{symbol}}: {{rights_entitled}} hak",
        "headline_en": "{{symbol}} rights: {{rights_entitled}}",
        "summary_id": "Jika ditebus semua, dana yang dibutuhkan {{cost_to_exercise_all}} sampai {{trading_period_end}}.",
        "summary_en": "Exercising all rights needs {{cost_to_exercise_all}} by {{trading_period_end}}.",
        "context_ids": ["controller_change"],
        "verify_id": ["Batas waktu internal broker"],
        "verify_en": ["Your broker's internal cut-off"],
    }


def test_check_passes_clean_draft():
    assert gate.check(good_draft(), briefs.allowed_placeholders(EV, FIGS), {"controller_change"}) == []


def test_check_flags_digits_banned_words_and_unknowns():
    d = good_draft()
    d["summary_id"] = "Sebaiknya tebus 1250 HMETD {{magic}}."
    d["context_ids"] = ["nope"]
    reasons = gate.check(d, briefs.allowed_placeholders(EV, FIGS), {"controller_change"})
    assert {"digits_outside_placeholders", "banned_phrase:sebaiknya",
            "unknown_placeholder:magic", "unknown_finding:nope"} <= set(reasons)


def test_templates_always_pass_the_gate():
    for ev in (EV, DIV_EV, WAR_EV):
        figs = calc.figures_for(ev, PRICES, AS_OF)
        assert gate.check(briefs.template(ev), briefs.allowed_placeholders(ev, figs), set()) == [], ev["kind"]


def test_render_substitutes_per_language():
    out = briefs.render(good_draft(), EV, FIGS)
    assert out["summary_id"] == "Jika ditebus semua, dana yang dibutuhkan Rp2.500.000 sampai 15 Jul 2025."
    assert out["summary_en"] == "Exercising all rights needs Rp2,500,000 by 15 Jul 2025."
    assert out["headline_id"] == "HMETD WIFI: 1.250 hak"


@pytest.mark.asyncio
async def test_judge_reasons_and_fail_open(monkeypatch):
    async def strict(state, questions):
        return SimpleNamespace(nouls={"advice": SimpleNamespace(noul=0.8),
                                      "grounded": SimpleNamespace(noul=0.2)})

    async def missing(state, questions):
        return None

    monkeypatch.setattr(gate, "jev_ask", strict)
    assert await gate.judge("x", []) == ["advice_language", "ungrounded"]
    monkeypatch.setattr(gate, "jev_ask", missing)
    assert await gate.judge("x", []) == []


@pytest.mark.asyncio
async def test_produce_accepts_good_draft_and_falls_back_on_bad(monkeypatch):
    class Writer:
        def __init__(self, draft):
            self.draft = draft

        async def ainvoke(self, messages, config=None):
            return briefs.BriefDraft(**self.draft)

    async def missing(state, questions):
        return None

    monkeypatch.setattr(gate, "jev_ask", missing)
    monkeypatch.setattr(briefs, "_writer", Writer(good_draft()))
    found = [{"id": "controller_change", "kind": "controller_change", "text_id": "x"}]
    ok = await briefs.produce(EV, FIGS, found)
    assert ok["gate"] == {"passed": True, "reasons": [], "template": False}

    bad = {**good_draft(), "summary_id": "Harus tebus 1250 hak."}
    monkeypatch.setattr(briefs, "_writer", Writer(bad))
    fallback = await briefs.produce(EV, FIGS, found)
    assert fallback["gate"]["template"] is True
    assert "1.250 HMETD" in fallback["summary_id"]
    assert fallback["context_ids"] == ["controller_change"]

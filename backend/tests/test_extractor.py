"""Fact-extraction pre-filter and sanitizer — pure units, no LLM calls."""

import pytest

from app.memory.extractor import (
    _has_extractable_substance,
    _sanitize_facts,
    extract_facts,
)


def test_prefilter_skips_chitchat():
    assert not _has_extractable_substance("")
    assert not _has_extractable_substance("   ")
    assert not _has_extractable_substance("halo")
    assert not _has_extractable_substance("terima kasih banyak ya")
    assert not _has_extractable_substance("bagaimana performa saham BBCA hari ini")


def test_prefilter_accepts_first_person():
    assert _has_extractable_substance("nama saya Budi dan saya investor ritel")
    assert _has_extractable_substance("I hold BBCA and I prefer dividend stocks")
    assert _has_extractable_substance("portofolio ku mayoritas sektor perbankan")


def test_sanitize_drops_non_conforming():
    facts = _sanitize_facts(
        [
            "User is named Budi",
            "Budi likes coffee",  # missing "User " prefix
            "",
            "   ",
            None,
            "User " + "x" * 400,  # over max length
            "User likes\ncoffee\tblack",  # control chars collapse
        ]
    )
    assert facts == ["User is named Budi", "User likes coffee black"]


@pytest.mark.asyncio
async def test_extract_facts_prefilter_never_calls_llm():
    assert await extract_facts("halo", "halo juga") == []

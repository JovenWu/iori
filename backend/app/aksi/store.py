"""Persistence for holdings and check reports (own sessions, like the cache)."""

import uuid
from datetime import date

from sqlalchemy import delete, select

from app.db.session import async_session_maker
from app.models.aksi_report import AksiReport
from app.models.holding import Holding


def _holding(h: Holding) -> dict:
    return {
        "symbol": h.symbol,
        "shares": int(h.shares),
        "avg_price": float(h.avg_price) if h.avg_price is not None else None,
    }


def _report(r: AksiReport) -> dict:
    return {
        "id": str(r.id),
        "mode": r.mode,
        "as_of": r.as_of.isoformat(),
        "status": r.status,
        "holdings_snapshot": r.holdings_snapshot or [],
        "events": r.events or [],
        "credits_spent": r.credits_spent,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


async def list_holdings(user_id: int) -> list[dict]:
    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(Holding).where(Holding.user_id == user_id).order_by(Holding.symbol)
            )
        ).scalars().all()
    return [_holding(h) for h in rows]


async def replace_holdings(user_id: int, holdings: list[dict]) -> None:
    async with async_session_maker() as db:
        await db.execute(delete(Holding).where(Holding.user_id == user_id))
        db.add_all(
            Holding(user_id=user_id, symbol=h["symbol"], shares=h["shares"],
                    avg_price=h.get("avg_price"))
            for h in holdings
        )
        await db.commit()


async def create_report(user_id: int, mode: str, as_of: date, holdings: list[dict]) -> str:
    async with async_session_maker() as db:
        report = AksiReport(user_id=user_id, mode=mode, as_of=as_of, status="running",
                            holdings_snapshot=holdings, events=[], credits_spent=0)
        db.add(report)
        await db.commit()
        return str(report.id)


async def append_event(report_id: str, result: dict, credits: int) -> None:
    async with async_session_maker() as db:
        report = await db.get(AksiReport, uuid.UUID(report_id))
        if report is None:
            return
        report.events = [*(report.events or []), result]  # new list → change detected
        report.credits_spent = credits
        await db.commit()


async def finish_report(report_id: str, status: str, credits: int | None) -> None:
    async with async_session_maker() as db:
        report = await db.get(AksiReport, uuid.UUID(report_id))
        if report is None:
            return
        report.status = status
        if credits is not None:
            report.credits_spent = credits
        await db.commit()


async def latest_report(user_id: int, mode: str | None = None,
                        as_of: date | None = None) -> dict | None:
    stmt = (
        select(AksiReport)
        .where(AksiReport.user_id == user_id, AksiReport.status != "running")
        .order_by(AksiReport.created_at.desc())
        .limit(1)
    )
    if mode:
        stmt = stmt.where(AksiReport.mode == mode)
    if as_of:
        stmt = stmt.where(AksiReport.as_of == as_of)
    async with async_session_maker() as db:
        report = (await db.execute(stmt)).scalars().first()
    return _report(report) if report else None


async def list_reports(user_id: int, limit: int = 10) -> list[dict]:
    """Recent checks, newest first — compact rows without the events payload."""
    stmt = (
        select(AksiReport)
        .where(AksiReport.user_id == user_id)
        .order_by(AksiReport.created_at.desc())
        .limit(limit)
    )
    async with async_session_maker() as db:
        rows = (await db.execute(stmt)).scalars().all()
    return [
        {**_report(r), "events": len(r.events or [])}
        for r in rows
    ]


async def get_report(user_id: int, report_id: str) -> dict | None:
    async with async_session_maker() as db:
        report = await db.get(AksiReport, uuid.UUID(report_id))
    if report is None or report.user_id != user_id:
        return None
    return _report(report)

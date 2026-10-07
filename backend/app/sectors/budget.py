"""Global Sectors credit budget — one shared cap across all users.

`try_spend` is an atomic conditional update: the reservation lands only when
`spent + credits <= cap`, so concurrent misses can't race past the limit.
The caller refunds when the upstream response was a non-billable status
(400/401/403/429/5xx are free per Sectors billing), keeping `spent` equal to
real consumption.
"""

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_maker
from app.models.credit_budget import CreditBudget

_ROW_ID = 1


async def _ensure_row(db: AsyncSession) -> None:
    if await db.get(CreditBudget, _ROW_ID) is not None:
        return
    db.add(CreditBudget(id=_ROW_ID, spent=0))
    try:
        await db.flush()
    except IntegrityError:
        # Another process seeded it first.
        await db.rollback()


async def try_spend(credits: int) -> bool:
    """Reserve `credits` from the global budget; False when exhausted."""
    async with async_session_maker() as db:
        await _ensure_row(db)
        res = await db.execute(
            update(CreditBudget)
            .where(
                CreditBudget.id == _ROW_ID,
                CreditBudget.spent + credits <= settings.SECTORS_CREDIT_BUDGET,
            )
            .values(spent=CreditBudget.spent + credits)
        )
        await db.commit()
        return (res.rowcount or 0) > 0


async def refund(credits: int) -> None:
    async with async_session_maker() as db:
        await db.execute(
            update(CreditBudget)
            .where(CreditBudget.id == _ROW_ID)
            .values(spent=func.greatest(CreditBudget.spent - credits, 0))
        )
        await db.commit()


async def snapshot() -> dict:
    """{spent, budget, remaining} for the stats endpoint."""
    async with async_session_maker() as db:
        await _ensure_row(db)
        spent = (
            await db.execute(
                select(CreditBudget.spent).where(CreditBudget.id == _ROW_ID)
            )
        ).scalar_one()
        cap = settings.SECTORS_CREDIT_BUDGET
        return {"spent": spent, "budget": cap, "remaining": max(0, cap - spent)}

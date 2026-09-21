from typing import Any

from fastapi import APIRouter, Depends

from app.api import deps
from app.models.user import User
from app.schemas.auth import UserOut

router = APIRouter()


@router.get("/me", response_model=UserOut)
async def read_me(current_user: User = Depends(deps.get_current_user)) -> Any:
    return current_user

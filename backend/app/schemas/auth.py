from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(
        min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$"
    )
    # bcrypt only reads the first 72 bytes — cap at 72 chars, not bytes.
    password: str = Field(min_length=8, max_length=72)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserOut(BaseModel):
    id: int
    username: str
    email: str | None = None
    name: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: str
    user: UserOut


class TokenPayload(BaseModel):
    sub: str | None = None
    type: str | None = None
    ver: int | None = None
    exp: int | None = None

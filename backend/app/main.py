from dotenv import load_dotenv

load_dotenv()

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.handlers import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from app.core.ratelimit import limiter

setup_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up (environment=%s)...", settings.ENVIRONMENT)

    violations = settings.production_safety_violations()
    if violations:
        msg = (
            "Refusing to start in production — unsafe configuration:\n- "
            + "\n- ".join(violations)
        )
        logger.critical(msg)
        raise RuntimeError(msg)

    if settings.CHECKPOINTER_POOL_MAX_SIZE <= settings.STREAM_MAX_ACTIVE_RUNS:
        msg = (
            f"CHECKPOINTER_POOL_MAX_SIZE ({settings.CHECKPOINTER_POOL_MAX_SIZE}) "
            f"must be greater than STREAM_MAX_ACTIVE_RUNS "
            f"({settings.STREAM_MAX_ACTIVE_RUNS}); otherwise concurrent "
            "generations would exhaust the checkpointer pool and stall."
        )
        logger.critical(msg)
        raise RuntimeError(msg)

    yield

    logger.info("Shutdown complete.")


_docs_kwargs = (
    {"openapi_url": None, "docs_url": None, "redoc_url": None}
    if settings.is_production
    else {"openapi_url": f"{settings.API_V1_STR}/openapi.json"}
)
app = FastAPI(title="sectors-agent API", lifespan=lifespan, **_docs_kwargs)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.MAX_JSON_BODY_BYTES)
app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}

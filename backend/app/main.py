from dotenv import load_dotenv

load_dotenv()

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}

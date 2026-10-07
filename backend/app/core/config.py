from pydantic import PostgresDsn, computed_field
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        extra="ignore",
    )

    # "production" enables fail-closed startup checks and hides API docs.
    ENVIRONMENT: str = "development"

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_DB: str

    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30

    # Single login-only account provisioned from env; there is no registration.
    APP_USERNAME: str = "demo"
    APP_PASSWORD: str = "demo123"

    # All chat / classification / embedding calls go through OpenRouter.
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_APP_NAME: str = "sectors-agent"
    MODEL_NAME: str = "openai/gpt-5.6-luna"
    CLASSIFIER_MODEL: str = "openai/gpt-5.6-luna"
    # Reasoning effort for the agent model. Reasoning-capable models then
    # return a summary of their thinking, streamed to clients as `reasoning`
    # events. Empty disables — the model uses plain chat completions.
    MODEL_REASONING_EFFORT: str = "high"
    EMBEDDING_MODEL: str = "openai/text-embedding-3-small"
    EMBEDDING_TIMEOUT: float = 30.0
    EMBEDDING_MAX_RETRIES: int = 5

    # TypeSafe JEV — System One classifier for routing, retrieval gates and
    # reranking. Unset means every JEV call site uses its LLM/deterministic
    # fallback instead.
    TYPESAFE_API_KEY: str | None = None
    TYPESAFE_MODEL: str = "jev-latest"

    # Sectors API — IDX market data. Unset key = tools report "not configured"
    # and no upstream calls are made.
    SECTORS_API_KEY: str | None = None
    SECTORS_BASE_URL: str = "https://api.sectors.app"
    SECTORS_TIMEOUT: float = 20.0
    # EOD data is published after market close; EOD cache entries expire at the
    # next weekday occurrence of this hour (Asia/Jakarta).
    SECTORS_REFRESH_HOUR_WIB: int = 17
    SECTORS_CACHE_STATIC_DAYS: int = 7
    SECTORS_CACHE_NEWS_MINUTES: int = 30
    SECTORS_TOOL_MAX_CHARS: int = 12_000

    CONTEXT_TOKEN_LIMIT: int = 16_000
    KEEP_TURNS: int = 2
    THREAD_TITLE_MAX_CHARS: int = 80

    LOG_LEVEL: str = "INFO"
    API_V1_STR: str = "/api/v1"

    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Long-term memory retrieval pipeline.
    MEMORY_RETRIEVAL_THRESHOLD: float = 0.15
    MEMORY_RETRIEVAL_CANDIDATES: int = 20
    MEMORY_TOP_K: int = 5
    MEMORY_BM25_CANDIDATES: int = 20
    MEMORY_RRF_K: int = 60
    MEMORY_RERANK_THRESHOLD: float = 0.5
    MEMORY_MAX_PER_USER: int = 200
    MEMORY_BACKGROUND_CONCURRENCY: int = 4
    MEMORY_VECTOR_FLOOR: float = 0.6

    # Cross-thread recall via per-thread digests.
    THREAD_DIGEST_STALE_TURNS: int = 3
    THREAD_DIGEST_MAX_CHARS: int = 1500
    THREAD_SIGNAL_TOP_K: int = 3
    THREAD_RECALL_CANDIDATES: int = 20
    THREAD_RECALL_BM25_CANDIDATES: int = 20
    THREAD_RECALL_RRF_K: int = 60
    THREAD_RECALL_THRESHOLD: float = 0.15

    # Resumable streaming. The checkpointer pool must exceed the global run cap
    # or concurrent generations starve it (enforced at startup).
    STREAM_MAX_ACTIVE_RUNS: int = 20
    STREAM_MAX_ACTIVE_RUNS_PER_USER: int = 5
    STREAM_RUN_BUFFER_MAX: int = 4000
    STREAM_RUN_LINGER_SECONDS: int = 45
    CHECKPOINTER_POOL_MAX_SIZE: int = 25

    # Max JSON request body buffered into memory (DoS guard).
    MAX_JSON_BODY_BYTES: int = 256 * 1024

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() == "production"

    def production_safety_violations(self) -> list[str]:
        """Config that must never be active in production. Empty list = safe."""
        if not self.is_production:
            return []
        violations: list[str] = []
        secret = self.SECRET_KEY or ""
        weak_secrets = {"changeme", "secret", "secretkey"}
        if len(secret) < 32 or secret.lower() in weak_secrets:
            violations.append(
                "SECRET_KEY must be a strong random value of at least 32 characters."
            )
        if self.APP_USERNAME == "demo" or self.APP_PASSWORD == "demo123":
            violations.append(
                "APP_USERNAME/APP_PASSWORD still have their shipped defaults "
                "(demo/demo123) — set real credentials."
            )
        return violations

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return MultiHostUrl.build(
            scheme="postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )


settings = Settings()

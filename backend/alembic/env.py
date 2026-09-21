import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from app.core.config import settings
from app.db.base import Base

# Import every model so autogenerate sees the full metadata.
from app import models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", str(settings.SQLALCHEMY_DATABASE_URI))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Managed outside Alembic: LangGraph's checkpointer creates its own tables via
# saver.setup(), and the HNSW/GIN indexes are hand-written in the migration.
# Without this filter autogenerate proposes dropping all of them.
_EXTERNAL_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
}
_EXTERNAL_INDEXES = {
    "ix_memories_content_fts",
    "ix_memories_embedding_hnsw",
    "ix_thread_digests_fts",
    "ix_thread_digests_embedding_hnsw",
}


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table" and name in _EXTERNAL_TABLES:
        return False
    if type_ == "index" and name in _EXTERNAL_INDEXES:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

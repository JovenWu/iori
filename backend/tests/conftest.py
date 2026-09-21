import os

# Point the app at a dedicated test database before any app import touches
# settings. docker-compose stays the source of the Postgres instance.
os.environ.setdefault("POSTGRES_DB", "sectors_agent_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

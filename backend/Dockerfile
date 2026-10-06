# Backend dev image — source is bind-mounted in compose, uvicorn --reload
# picks up edits. requirements-dev is the superset (adds pytest).
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

EXPOSE 8000

# Migrate, then serve. Plain uvicorn is fine here — the Windows selector-loop
# shim in app/main.py is only needed on a Windows host, not in the container.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]

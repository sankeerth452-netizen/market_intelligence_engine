# syntax=docker/dockerfile:1
# Production image for the Market Intelligence Engine.
# Works as-is on Render, Fly.io, Railway, Hugging Face Spaces, Cloud Run, etc.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Application code.
COPY . .

# The platform injects $PORT at runtime; default to 8000 for local `docker run`.
ENV PORT=8000
EXPOSE 8000

# IMPORTANT: a single worker, on purpose.
# The LinUCB bandit lives in memory (engine_service.ENGINE). Multiple workers
# would each train a *different* model and the dashboard would show whichever
# one your request happened to hit. One process keeps the learning consistent.
# Move state to Postgres (roadmap) before scaling beyond one worker.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]

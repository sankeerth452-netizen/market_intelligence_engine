"""
store.py
--------
Durable persistence for the feedback loop, backed by SQLAlchemy Core so the SAME
code runs on SQLite locally and Postgres in production.

Pick the backend with the DATABASE_URL environment variable:
  * unset / a bare path   -> SQLite file (great for dev, the CLI and the sim)
  * postgres://... URL     -> Postgres (what Render injects in production)

Three tables:
  * recommendations — one row per (week, topic), with the context vector that
    produced it (so a later result can be fed straight back to the learner)
  * outcomes        — one realised reward per recommendation
  * model_state     — the serialised LinUCB model, so the learned weights survive
    a restart even on an ephemeral filesystem (no local JSON file needed)

Writes are idempotent (upsert on week+topic / on rec_id) so refreshing the
dashboard never inflates the log.
"""
import json
import os
import time

from sqlalchemy import (Column, Float, Integer, MetaData, Table, Text,
                        UniqueConstraint, create_engine, func, insert, select,
                        update)

metadata = MetaData()

recommendations = Table(
    "recommendations", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("week", Integer), Column("topic", Text),
    Column("category", Text), Column("kind", Text),
    Column("roi", Float), Column("value_mean", Float),
    Column("uncertainty", Float), Column("effort", Text),
    Column("rationale", Text), Column("context", Text),
    Column("created_at", Float),
    UniqueConstraint("week", "topic", name="uq_recommendation_week_topic"),
)

outcomes = Table(
    "outcomes", metadata,
    Column("rec_id", Integer, primary_key=True),
    Column("reward", Float), Column("recorded_at", Float),
)

model_state = Table(
    "model_state", metadata,
    Column("key", Text, primary_key=True),
    Column("payload", Text), Column("updated_at", Float),
)


def _normalize_url(url: str) -> str:
    """Accept a bare file path or any DB URL; return a SQLAlchemy URL."""
    if "://" not in url:
        return f"sqlite:///{url}"                       # bare path -> sqlite file
    # Render/Heroku hand out 'postgres://'; SQLAlchemy + psycopg3 want this form:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def connect(url: str = None):
    """Create (or open) the database and return a SQLAlchemy Engine."""
    url = _normalize_url(url or os.environ.get("DATABASE_URL", "sqlite:///mie.db"))
    kwargs = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    metadata.create_all(engine)
    return engine


def save_recommendation(engine, week, topic, category, kind, roi, value_mean,
                        uncertainty, effort, rationale, context_json=None) -> int:
    """Insert a recommendation, or update it in place if (week, topic) exists."""
    with engine.begin() as conn:
        row = conn.execute(
            select(recommendations.c.id).where(
                recommendations.c.week == week,
                recommendations.c.topic == topic)).first()
        if row:
            rid = row[0]
            vals = dict(roi=roi, value_mean=value_mean, uncertainty=uncertainty,
                        effort=effort, rationale=rationale)
            if context_json is not None:    # never overwrite a stored vector with null
                vals["context"] = context_json
            conn.execute(update(recommendations)
                         .where(recommendations.c.id == rid).values(**vals))
            return int(rid)
        res = conn.execute(insert(recommendations).values(
            week=week, topic=topic, category=category, kind=kind, roi=roi,
            value_mean=value_mean, uncertainty=uncertainty, effort=effort,
            rationale=rationale, context=context_json, created_at=time.time()))
        return int(res.inserted_primary_key[0])


def get_context(engine, rec_id: int):
    """Return the stored context vector for a recommendation, or None."""
    with engine.begin() as conn:
        row = conn.execute(select(recommendations.c.context)
                           .where(recommendations.c.id == rec_id)).first()
    if not row or row[0] is None:
        return None
    return json.loads(row[0])


def record_outcome(engine, rec_id: int, reward: float) -> None:
    """Store (or replace) the realised reward for a recommendation."""
    with engine.begin() as conn:
        exists = conn.execute(select(outcomes.c.rec_id)
                              .where(outcomes.c.rec_id == rec_id)).first()
        if exists:
            conn.execute(update(outcomes).where(outcomes.c.rec_id == rec_id)
                         .values(reward=reward, recorded_at=time.time()))
        else:
            conn.execute(insert(outcomes).values(
                rec_id=rec_id, reward=reward, recorded_at=time.time()))


def summary(engine) -> dict:
    with engine.begin() as conn:
        n_rec = conn.execute(select(func.count()).select_from(recommendations)).scalar()
        n_out = conn.execute(select(func.count()).select_from(outcomes)).scalar()
        avg = conn.execute(select(func.avg(outcomes.c.reward))).scalar()
    return {"recommendations": int(n_rec), "outcomes": int(n_out),
            "avg_reward": round(float(avg), 4) if avg is not None else None}


# ---- learned-model persistence (so the model survives a restart) ----
def save_model(engine, key: str, payload_json: str) -> None:
    with engine.begin() as conn:
        exists = conn.execute(select(model_state.c.key)
                              .where(model_state.c.key == key)).first()
        if exists:
            conn.execute(update(model_state).where(model_state.c.key == key)
                         .values(payload=payload_json, updated_at=time.time()))
        else:
            conn.execute(insert(model_state).values(
                key=key, payload=payload_json, updated_at=time.time()))


def load_model(engine, key: str):
    with engine.begin() as conn:
        row = conn.execute(select(model_state.c.payload)
                           .where(model_state.c.key == key)).first()
    return json.loads(row[0]) if row and row[0] else None


def reset_all(engine) -> None:
    """Wipe recommendations, outcomes and the saved model (the demo reset)."""
    with engine.begin() as conn:
        conn.execute(outcomes.delete())
        conn.execute(recommendations.delete())
        conn.execute(model_state.delete())

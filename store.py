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

# Competitor page inventory: one row per (site, url), with when we first saw it.
# Diffing week-over-week surfaces the pages a competitor has newly published.
competitor_pages = Table(
    "competitor_pages", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("site", Text), Column("url", Text),
    Column("first_seen", Float), Column("last_seen", Float),
    UniqueConstraint("site", "url", name="uq_competitor_site_url"),
)

# One row per crawl attempt per site — the status feed (accessible? blocked?).
crawl_runs = Table(
    "crawl_runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("site", Text), Column("ran_at", Float),
    Column("found", Integer), Column("added", Integer),
    Column("ok", Integer), Column("note", Text),
)

# ---- Google integration (OAuth tokens, fetched SEO metrics, outcome tracking) ----
# All keyed by client_key so the schema is multi-client-ready (this deployment
# serves one client, but tokens/metrics/outcomes are namespaced per client).

# Encrypted OAuth tokens, one row per (client, service = 'gsc' | 'ga4').
google_tokens = Table(
    "google_tokens", metadata,
    Column("client_key", Text), Column("service", Text),
    Column("token_enc", Text),                 # Fernet-encrypted {access,refresh,expiry,scope}
    Column("property_id", Text),               # the chosen GSC site / GA4 property
    Column("connected_at", Float), Column("updated_at", Float),
    UniqueConstraint("client_key", "service", name="uq_google_client_service"),
)

# Daily per-page SEO metrics fetched from GSC / GA4 (the raw performance history
# the outcome evaluator diffs). metrics_json holds the standardised numbers.
seo_metrics = Table(
    "seo_metrics", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("client_key", Text), Column("source", Text),   # 'gsc' | 'ga4'
    Column("page", Text), Column("date", Text),           # 'YYYY-MM-DD'
    Column("metrics_json", Text), Column("fetched_at", Float),
    UniqueConstraint("client_key", "source", "page", "date", name="uq_seo_metric"),
)

# Recommendation tracking beyond the base row: which page it targets and when the
# client marked it implemented (the anchor for before/after evaluation).
rec_meta = Table(
    "rec_meta", metadata,
    Column("rec_id", Integer, primary_key=True),
    Column("target_url", Text), Column("implemented_at", Float),
)

# Measured, real-world outcome of an implemented recommendation (from Google data).
# Separate from `outcomes` (manual agree/disagree) but both feed the same learner.
seo_outcomes = Table(
    "seo_outcomes", metadata,
    Column("rec_id", Integer, primary_key=True),
    Column("status", Text),                    # 'pending' | 'evaluated'
    Column("reward", Float), Column("evaluated_at", Float),
    Column("detail_json", Text),               # the standardised outcome (metric changes)
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
    """Wipe recommendations, outcomes and the saved model (the demo reset).
    Competitor crawl history and Google connections/metrics are deliberately kept
    — slow/valuable to rebuild and not part of the learning-demo reset."""
    with engine.begin() as conn:
        conn.execute(outcomes.delete())
        conn.execute(recommendations.delete())
        conn.execute(model_state.delete())
        conn.execute(rec_meta.delete())          # tracking is tied to the wiped recs
        conn.execute(seo_outcomes.delete())


# ---- competitor page inventory + new-page detection ----
def sync_site_pages(engine, site: str, urls) -> dict:
    """Record the current page URLs for a site. New URLs get first_seen=now;
    already-known URLs just have last_seen bumped. Returns {found, added}."""
    now = time.time()
    urls = list(dict.fromkeys(urls))          # de-dup, keep order
    with engine.begin() as conn:
        known = {r[0] for r in conn.execute(
            select(competitor_pages.c.url).where(competitor_pages.c.site == site))}
        fresh = [u for u in urls if u not in known]
        if fresh:
            conn.execute(insert(competitor_pages), [
                {"site": site, "url": u, "first_seen": now, "last_seen": now}
                for u in fresh])
        # bump last_seen for the pages still present (in chunks; IN-lists stay small)
        present = [u for u in urls if u in known]
        for i in range(0, len(present), 400):
            chunk = present[i:i + 400]
            conn.execute(update(competitor_pages)
                         .where(competitor_pages.c.site == site,
                                competitor_pages.c.url.in_(chunk))
                         .values(last_seen=now))
    return {"found": len(urls), "added": len(fresh)}


def record_crawl_run(engine, site, found, added, ok, note="") -> None:
    with engine.begin() as conn:
        conn.execute(insert(crawl_runs).values(
            site=site, ran_at=time.time(), found=int(found), added=int(added),
            ok=1 if ok else 0, note=note))


def new_pages(engine, site: str, since_ts: float, limit: int = 40):
    """Pages for a site whose first_seen is at/after since_ts — the 'new' ones."""
    with engine.begin() as conn:
        rows = conn.execute(
            select(competitor_pages.c.url, competitor_pages.c.first_seen)
            .where(competitor_pages.c.site == site,
                   competitor_pages.c.first_seen >= since_ts)
            .order_by(competitor_pages.c.first_seen.desc())
            .limit(limit)).all()
    return [{"url": r[0], "first_seen": r[1]} for r in rows]


def first_crawl_at(engine, site: str):
    """When we first successfully crawled this site (the baseline). Pages present
    at the baseline are NOT 'new'; only ones seen afterwards are."""
    with engine.begin() as conn:
        return conn.execute(select(func.min(crawl_runs.c.ran_at))
                            .where(crawl_runs.c.site == site,
                                   crawl_runs.c.ok == 1)).scalar()


def site_page_count(engine, site: str) -> int:
    with engine.begin() as conn:
        return int(conn.execute(select(func.count()).select_from(competitor_pages)
                                .where(competitor_pages.c.site == site)).scalar() or 0)


def last_crawl_run(engine, site: str):
    with engine.begin() as conn:
        row = conn.execute(
            select(crawl_runs.c.ran_at, crawl_runs.c.found, crawl_runs.c.added,
                   crawl_runs.c.ok, crawl_runs.c.note)
            .where(crawl_runs.c.site == site)
            .order_by(crawl_runs.c.ran_at.desc()).limit(1)).first()
    if not row:
        return None
    return {"ran_at": row[0], "found": row[1], "added": row[2],
            "ok": bool(row[3]), "note": row[4]}


# ---- Google integration persistence ----
def save_google_token(engine, client_key, service, token_enc, property_id=None):
    now = time.time()
    with engine.begin() as conn:
        exists = conn.execute(select(google_tokens.c.client_key).where(
            google_tokens.c.client_key == client_key,
            google_tokens.c.service == service)).first()
        if exists:
            vals = {"token_enc": token_enc, "updated_at": now}
            if property_id is not None:
                vals["property_id"] = property_id
            conn.execute(update(google_tokens).where(
                google_tokens.c.client_key == client_key,
                google_tokens.c.service == service).values(**vals))
        else:
            conn.execute(insert(google_tokens).values(
                client_key=client_key, service=service, token_enc=token_enc,
                property_id=property_id, connected_at=now, updated_at=now))


def set_google_property(engine, client_key, service, property_id):
    with engine.begin() as conn:
        conn.execute(update(google_tokens).where(
            google_tokens.c.client_key == client_key, google_tokens.c.service == service
        ).values(property_id=property_id, updated_at=time.time()))


def load_google_token(engine, client_key, service):
    with engine.begin() as conn:
        row = conn.execute(select(
            google_tokens.c.token_enc, google_tokens.c.property_id,
            google_tokens.c.connected_at).where(
            google_tokens.c.client_key == client_key,
            google_tokens.c.service == service)).first()
    if not row:
        return None
    return {"token_enc": row[0], "property_id": row[1], "connected_at": row[2]}


def delete_google_token(engine, client_key, service):
    with engine.begin() as conn:
        conn.execute(google_tokens.delete().where(
            google_tokens.c.client_key == client_key, google_tokens.c.service == service))


def save_seo_metrics(engine, client_key, source, rows):
    """rows = [{'page','date','metrics':{...}}]. Upsert per (client, source, page, date)."""
    now = time.time()
    with engine.begin() as conn:
        for r in rows:
            exists = conn.execute(select(seo_metrics.c.id).where(
                seo_metrics.c.client_key == client_key, seo_metrics.c.source == source,
                seo_metrics.c.page == r["page"], seo_metrics.c.date == r["date"])).first()
            payload = json.dumps(r.get("metrics", {}))
            if exists:
                conn.execute(update(seo_metrics).where(seo_metrics.c.id == exists[0])
                             .values(metrics_json=payload, fetched_at=now))
            else:
                conn.execute(insert(seo_metrics).values(
                    client_key=client_key, source=source, page=r["page"],
                    date=r["date"], metrics_json=payload, fetched_at=now))


def seo_page_metrics(engine, client_key, source, page, start_date, end_date):
    """Daily metric rows for a page in [start_date, end_date] (YYYY-MM-DD strings)."""
    with engine.begin() as conn:
        rows = conn.execute(select(seo_metrics.c.date, seo_metrics.c.metrics_json).where(
            seo_metrics.c.client_key == client_key, seo_metrics.c.source == source,
            seo_metrics.c.page == page, seo_metrics.c.date >= start_date,
            seo_metrics.c.date <= end_date).order_by(seo_metrics.c.date)).all()
    return [{"date": r[0], "metrics": json.loads(r[1] or "{}")} for r in rows]


def set_rec_meta(engine, rec_id, target_url=None, implemented_at=None):
    with engine.begin() as conn:
        exists = conn.execute(select(rec_meta.c.rec_id).where(rec_meta.c.rec_id == rec_id)).first()
        vals = {}
        if target_url is not None:
            vals["target_url"] = target_url
        if implemented_at is not None:
            vals["implemented_at"] = implemented_at
        if exists:
            if vals:
                conn.execute(update(rec_meta).where(rec_meta.c.rec_id == rec_id).values(**vals))
        else:
            conn.execute(insert(rec_meta).values(rec_id=rec_id, **vals))


def implemented_recs(engine):
    """Recommendations marked implemented, joined with their base row + stored context
    vector — everything the outcome evaluator + learner need."""
    with engine.begin() as conn:
        rows = conn.execute(select(
            rec_meta.c.rec_id, rec_meta.c.target_url, rec_meta.c.implemented_at,
            recommendations.c.topic, recommendations.c.context, recommendations.c.roi,
            recommendations.c.uncertainty).select_from(
            rec_meta.join(recommendations, rec_meta.c.rec_id == recommendations.c.id)
        ).where(rec_meta.c.implemented_at.isnot(None))).all()
    return [{"rec_id": r[0], "target_url": r[1], "implemented_at": r[2], "topic": r[3],
             "context": json.loads(r[4]) if r[4] else None, "roi": r[5],
             "uncertainty": r[6]} for r in rows]


def save_seo_outcome(engine, rec_id, status, reward=None, detail=None):
    now = time.time()
    with engine.begin() as conn:
        exists = conn.execute(select(seo_outcomes.c.rec_id)
                              .where(seo_outcomes.c.rec_id == rec_id)).first()
        vals = dict(status=status, reward=reward, evaluated_at=now,
                    detail_json=json.dumps(detail or {}))
        if exists:
            conn.execute(update(seo_outcomes).where(seo_outcomes.c.rec_id == rec_id).values(**vals))
        else:
            conn.execute(insert(seo_outcomes).values(rec_id=rec_id, **vals))


def seo_outcomes_all(engine):
    with engine.begin() as conn:
        rows = conn.execute(select(seo_outcomes.c.rec_id, seo_outcomes.c.status,
                                   seo_outcomes.c.reward, seo_outcomes.c.detail_json)).all()
    return [{"rec_id": r[0], "status": r[1], "reward": r[2],
             "detail": json.loads(r[3] or "{}")} for r in rows]

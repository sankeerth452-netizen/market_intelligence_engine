"""
radar_app.py — The Radar: a daily social-trend dashboard for one topic (crafts).

Run locally (from the radar/ folder):
    uvicorn radar_app:app --reload --port 8000
Then open http://localhost:8000

Endpoints:
    GET  /api/radar          today's radar (5 ideas + ranked trends + raw signals),
                              built once per calendar day (by the first request that
                              day — there is no user-facing refresh control)
    GET  /api/history        dates with a stored past build, newest first (empty
                              unless DATABASE_URL is configured — see store.py)
    GET  /api/history/{date} a specific past day's radar, 404 if not stored
    POST /api/refresh        force a rebuild now (ops/debugging only, no UI button)
    GET  /api/health         liveness + whether Apify/history storage are configured

Self-contained — imports only `engine`/`sources`/`store` in this folder, so the
whole `radar/` directory ports cleanly into another dashboard.
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import engine
import sources
import store

app = FastAPI(title="The Radar — daily social trend discovery")
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


@app.get("/api/health")
def health():
    return {"status": "ok", "apify": sources.live(),
            "ai": bool(os.environ.get("ANTHROPIC_API_KEY")), "topic": sources.TOPIC,
            "history": store.enabled()}


@app.get("/api/radar")
def radar():
    """Today's radar — built once per calendar day, by whoever loads the page first."""
    return engine.daily()


@app.get("/api/history")
def history_list():
    """Dates with a stored build, newest first (empty if no database configured)."""
    return {"dates": engine.history_dates()}


@app.get("/api/history/{date}")
def history_day(date: str):
    """A specific past day's radar, by date (YYYY-MM-DD)."""
    day = engine.history(date)
    if day is None:
        raise HTTPException(status_code=404, detail="No stored radar for that date")
    return day


@app.post("/api/refresh")
def refresh():
    """Force a rebuild now. Not exposed in the UI — the daily read refreshes
    itself automatically; this exists for ops/debugging."""
    return engine.daily(force=True)


app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
def index():
    with open(os.path.join(WEB, "index.html"), encoding="utf-8") as f:
        html = f.read()
    ver = int(max(os.path.getmtime(os.path.join(WEB, n)) for n in ("app.js", "styles.css")))
    html = (html.replace("/static/app.js", "/static/app.js?v=%d" % ver)
                .replace("/static/styles.css", "/static/styles.css?v=%d" % ver))
    return HTMLResponse(html)

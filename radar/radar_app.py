"""
radar_app.py — The Radar: a daily social-trend dashboard for one topic (crafts).

Run locally (from the radar/ folder):
    uvicorn radar_app:app --reload --port 8000
Then open http://localhost:8000

Endpoints:
    GET  /api/radar     today's radar (5 ideas + ranked trends + raw signals), cached daily
    POST /api/refresh   force a fresh build for today
    GET  /api/health    liveness + whether Apify is configured (live vs sample)

Self-contained — imports only `engine`/`sources` in this folder, so the whole
`radar/` directory ports cleanly into another dashboard.
"""
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import engine
import sources

app = FastAPI(title="The Radar — daily social trend discovery")
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


@app.get("/api/health")
def health():
    return {"status": "ok", "apify": sources.live(),
            "ai": bool(os.environ.get("ANTHROPIC_API_KEY")), "topic": sources.TOPIC}


@app.get("/api/radar")
def radar():
    """Today's radar — cached to one build per day."""
    return engine.daily()


@app.post("/api/refresh")
def refresh():
    """Rebuild today's radar now (re-pulls the sources)."""
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

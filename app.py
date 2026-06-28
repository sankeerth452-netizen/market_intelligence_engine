"""
app.py
------
FastAPI backend for the Market Intelligence Engine web app.

Run locally:
    uvicorn app:app --reload --port 8000
Then open http://localhost:8000

Endpoints
    GET  /api/brief?week=8&k=3   ranked opportunities for a week
    POST /api/outcome           {rec_id, reward} -> closes the loop live
    GET  /api/weights           what the engine has learned to weigh
    GET  /api/status            feedback-loop counters
    GET  /api/simulate          head-to-head proof data (cached)
    GET  /api/robustness        multi-seed robustness + ablation (from evaluate.py)
    POST /api/reset             forget the learned model (demo reset)
"""
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
from engine_service import ENGINE

app = FastAPI(title="Market Intelligence Engine")
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


class Outcome(BaseModel):
    rec_id: int
    # Net realised value, including the negative tail (a flop is a real loss).
    reward: float = Field(ge=config.REWARD_MIN, le=config.REWARD_MAX)


@app.get("/api/brief")
def get_brief(week: int = 8, k: int = 3):
    week = max(0, min(week, 19))
    k = max(1, min(k, 6))
    return ENGINE.brief(week, k)


@app.post("/api/outcome")
def post_outcome(o: Outcome):
    return ENGINE.record_outcome(o.rec_id, o.reward)


@app.get("/api/weights")
def get_weights():
    return ENGINE.weights()


@app.get("/api/status")
def get_status():
    return ENGINE.status()


@app.get("/api/simulate")
def get_simulate():
    return ENGINE.simulate()


@app.get("/api/robustness")
def get_robustness():
    """Multi-seed robustness + ablation (from evaluate.py); null if not yet run."""
    return ENGINE.robustness()


@app.get("/api/signals")
def get_signals():
    """Per-category live signals (news, demand-trend, content-gap) + the bandit's score."""
    return ENGINE.signals()


@app.get("/api/summary")
def get_summary():
    """A narrative weekly intelligence summary composed from the live signals."""
    return ENGINE.summary()


class Question(BaseModel):
    question: str = Field(default="", max_length=500)


@app.post("/api/assistant")
def post_assistant(q: Question):
    """Virtual assistant — answers grounded in the live data (free-form if an
    ANTHROPIC_API_KEY is set, else rule-based)."""
    return ENGINE.assistant(q.question)


@app.get("/api/health")
def health():
    """Liveness probe for the hosting platform's health check."""
    return {"status": "ok", "model_updates": ENGINE.bandit.n_updates}


@app.post("/api/reset")
def post_reset():
    return ENGINE.reset()


# ---- frontend ----
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))

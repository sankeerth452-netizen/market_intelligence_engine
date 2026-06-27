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
    POST /api/reset             forget the learned model (demo reset)
"""
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine_service import ENGINE

app = FastAPI(title="Market Intelligence Engine")
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


class Outcome(BaseModel):
    rec_id: int
    reward: float = Field(ge=0.0, le=1.0)


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


@app.post("/api/reset")
def post_reset():
    return ENGINE.reset()


# ---- frontend ----
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))

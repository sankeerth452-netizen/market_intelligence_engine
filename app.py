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
import tempfile

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
import import_ahrefs
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


class PlaybookReq(BaseModel):
    topic: str = Field(default="", max_length=200)
    action: str = Field(default="", max_length=60)
    effort: str = Field(default="", max_length=12)
    headlines: list[str] = Field(default_factory=list)
    signals: dict = Field(default_factory=dict)
    target: dict = Field(default_factory=dict)


@app.post("/api/playbook")
def post_playbook(req: PlaybookReq):
    """AI Strategist — a grounded, client-ready action plan for one recommendation
    (Claude-written if an ANTHROPIC_API_KEY is set, else a real templated plan)."""
    return ENGINE.playbook(req.model_dump())


@app.get("/api/competitors")
def get_competitors():
    """Competitor page inventory + newly-published pages (week-over-week diff)."""
    return ENGINE.competitors()


@app.post("/api/competitors/refresh")
def post_competitors_refresh():
    """Trigger a competitor crawl in the background (the weekly cron does this
    automatically; this is the on-demand button)."""
    return ENGINE.refresh_competitors()


@app.get("/api/demand")
def get_demand():
    """Per-category demand trend + seasonality + next-month forecast (Ahrefs volume
    history). Empty/enabled:false unless AHREFS_API_KEY is set; cached a week."""
    return ENGINE.demand_forecast()


@app.get("/api/ai-visibility")
def get_ai_visibility():
    """AI 'share of voice' — the client vs competitors in AI answers (Brand Radar).
    Empty/enabled:false unless AHREFS_API_KEY is set; cached a week (expensive)."""
    return ENGINE.ai_visibility()


@app.get("/api/content-gaps")
def get_content_gaps():
    """Ranked missing-content opportunities from the Ahrefs content-gap export
    (competitor ranks, JB doesn't), filtered to JB's categories + buyer intent."""
    return ENGINE.content_gaps()


@app.get("/api/ideas")
def get_ideas():
    """Topics discovered from the content gaps, each with many ranked marketing
    ideas across SEO / Content / Social / Commercial / AI Visibility."""
    return ENGINE.marketing_ideas()


@app.get("/api/principles")
def get_principles():
    """Learned marketing principles — which idea TYPES pay off (expert prior now,
    refined by real GSC/GA4 outcomes over time)."""
    return ENGINE.principles()


# ---- Ahrefs exports: upload the weekly CSVs; they go straight into the AI ----
_MAX_UPLOAD = 30 * 1024 * 1024        # 30 MB per file — an Ahrefs export is a few MB
_TOP_PAGE_FILES = {                    # form field -> (site name, pages to keep)
    "jbhifi": ("JB Hi-Fi", 150), "harveynorman": ("Harvey Norman", 80),
    "thegoodguys": ("The Good Guys", 80), "officeworks": ("Officeworks", 80),
}
_READ_ERRORS = (UnicodeError, OSError, ValueError, IndexError, StopIteration)


async def _save_upload(f: UploadFile) -> str:
    """Persist an uploaded file to a temp path so the importer can read it. Rejects
    oversized files."""
    data = await f.read()
    if len(data) > _MAX_UPLOAD:
        raise ValueError(f"{f.filename or 'file'} is larger than 30 MB.")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    tmp.write(data)
    tmp.close()
    return tmp.name


@app.get("/api/ahrefs/status")
def ahrefs_status():
    """What market data the engine is running on right now (uploaded vs built-in)."""
    return ENGINE.ahrefs_status()


@app.post("/api/ahrefs/upload")
async def ahrefs_upload(
    content_gap: UploadFile | None = File(default=None),
    jbhifi: UploadFile | None = File(default=None),
    harveynorman: UploadFile | None = File(default=None),
    thegoodguys: UploadFile | None = File(default=None),
    officeworks: UploadFile | None = File(default=None),
):
    """Accept this week's Ahrefs CSV exports, run the same import as the CLI, and
    apply them live — persisted to the DB (survives restarts) and reflected in the
    plan/gaps/demand immediately, with no redeploy. Any subset of files is allowed."""
    fields = {"content_gap": content_gap, **{k: v for k, v in
              (("jbhifi", jbhifi), ("harveynorman", harveynorman),
               ("thegoodguys", thegoodguys), ("officeworks", officeworks))}}
    saved, paths = {}, []
    try:
        for field, f in fields.items():
            if f is not None and f.filename:
                path = await _save_upload(f)
                saved[field] = path
                paths.append(path)
        if not saved:
            return JSONResponse({"ok": False, "error": "No files were uploaded."}, status_code=400)

        cg = tp = None
        if "content_gap" in saved:
            try:
                cg = import_ahrefs.build_content_gaps(saved["content_gap"])
            except _READ_ERRORS as e:
                return JSONResponse({"ok": False, "error": "Could not read the Content Gap file — is "
                                     f"it the raw Ahrefs UTF-16 .csv export? ({type(e).__name__})"},
                                    status_code=400)
        tp_files = [(site, saved[field], limit)
                    for field, (site, limit) in _TOP_PAGE_FILES.items() if field in saved]
        if tp_files:
            try:
                tp = import_ahrefs.build_top_pages(tp_files)
            except _READ_ERRORS as e:
                return JSONResponse({"ok": False, "error": "Could not read a Top Pages file — a raw "
                                     f"Ahrefs UTF-16 .csv export is expected. ({type(e).__name__})"},
                                    status_code=400)

        ENGINE.apply_ahrefs(content_gaps=cg, top_pages=tp)
        return {
            "ok": True,
            "updated": [n for n, d in (("content_gaps", cg), ("top_pages", tp)) if d is not None],
            "content_gaps": (None if cg is None else {
                "kept": cg["kept"], "total_gaps_scanned": cg["total_gaps_scanned"],
                "total_demand": cg["total_demand"], "by_category": cg["by_category"]}),
            "top_pages": (None if tp is None else {
                "sites": {s: v["total_traffic"] for s, v in tp["sites"].items()}}),
        }
    finally:
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass


@app.post("/api/ahrefs/revert")
def ahrefs_revert():
    """Drop uploaded exports and fall back to the built-in committed snapshot (live)."""
    return ENGINE.revert_ahrefs()


# ---- Google integrations: real outcome-based learning loop ----
@app.get("/api/google/status")
def google_status():
    """GSC/GA4 connection + selected properties (all false/None if not configured)."""
    return ENGINE.google_status()


@app.get("/api/google/auth")
def google_auth():
    """The Google consent URL to start the OAuth flow (null if not configured)."""
    return ENGINE.google_auth_url()


@app.get("/api/google/callback")
def google_callback(code: str = "", state: str = "", error: str = ""):
    """OAuth redirect target — exchanges the code, then returns to the dashboard."""
    if error:
        return RedirectResponse(url=f"/?google=error&reason={error}")
    if code and ENGINE.google_connect(code).get("ok"):
        return RedirectResponse(url="/?google=connected")
    return RedirectResponse(url="/?google=error")


@app.get("/api/google/properties")
def google_properties(service: str = "gsc"):
    """The user's available GSC sites / GA4 properties, to pick the right one."""
    return ENGINE.google_properties("ga4" if service == "ga4" else "gsc")


class PropertySelection(BaseModel):
    service: str = Field(max_length=8)
    property_id: str = Field(max_length=300)


@app.post("/api/google/select")
def google_select(p: PropertySelection):
    return ENGINE.google_select("ga4" if p.service == "ga4" else "gsc", p.property_id)


@app.post("/api/google/disconnect")
def google_disconnect():
    return ENGINE.google_disconnect()


class Implemented(BaseModel):
    rec_id: int
    target_url: str = Field(default="", max_length=500)
    idea_type: str = Field(default="", max_length=60)


@app.post("/api/recommendations/implemented")
def recommendation_implemented(r: Implemented):
    """Mark a recommendation as shipped (records the date + target page), so its
    real-world impact can be measured later."""
    return ENGINE.mark_implemented(r.rec_id, r.target_url or None, r.idea_type or None)


@app.get("/api/performance")
def performance():
    """Recommendation-performance stats (real measured outcomes)."""
    return ENGINE.performance()


@app.post("/api/google/refresh")
def google_refresh():
    """Manually kick off a data-collect + outcome-evaluation pass (background)."""
    import threading
    threading.Thread(
        target=lambda: (ENGINE._collect_seo_data(True), ENGINE.evaluate_outcomes()),
        daemon=True).start()
    return {"ok": True, "status": "started"}


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
    # Serve index.html with a cache-busting ?v=<mtime> on the JS/CSS so a deploy
    # is picked up immediately instead of clients running stale assets.
    with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    ver = int(max(os.path.getmtime(os.path.join(WEB_DIR, n)) for n in ("app.js", "styles.css")))
    html = (html.replace("/static/app.js", f"/static/app.js?v={ver}")
                .replace("/static/styles.css", f"/static/styles.css?v={ver}"))
    return HTMLResponse(html)

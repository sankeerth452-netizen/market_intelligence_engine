# Market Intelligence Engine — Web App

A local dashboard on top of the closed-loop engine. It serves the morning brief,
shows how confident the engine is in each pick, lets you record real results that
teach it live, and renders the proof that learning beats a static scorer.

## Run it (about 30 seconds)

```bash
cd market_intelligence_engine
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Then open <http://localhost:8000>.

On first launch the engine ships **pre-trained** on its synthetic history, so the
dashboard opens with informed opinions instead of a blank slate. Everything you do
after that keeps teaching it.

## What you're looking at

- Left rail — pick the planning week and watch the live feedback-loop gauges.
- Morning brief — the ranked plan. Each card shows value-per-effort (ROI) and a
  **conviction meter**: the dot is the estimate, the band is how unsure the engine
  is. A wide band tagged `probe` means it's exploring on purpose to learn.
- Record result — drag the slider to the value a page actually delivered and hit
  Save result. This feeds straight back into the model; watch the weights panel
  and gauges move.
- What it trusts & distrusts — the weights the engine learned from outcomes. The
  amber `tiktok_velocity` bar pointing left is the engine having taught itself to
  distrust loud single-channel hype.
- Why the loop wins — the head-to-head: closed-loop vs the original static design.

## Try this to feel the loop

1. Open the dashboard — note the learned weights (TikTok already negative).
2. Click **Reset learning** in the rail. Everything zeroes; the model forgets.
3. Step through a few weeks and Save a result on each card. Watch the weights
   separate from zero and the gauges climb — the engine relearning in real time.

## Endpoints (for wiring a different frontend or automating)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/brief?week=8&k=3` | ranked opportunities |
| POST | `/api/outcome` | `{rec_id, reward}` → closes the loop |
| GET | `/api/weights` | learned signal weights |
| GET | `/api/status` | loop counters |
| GET | `/api/simulate` | head-to-head proof data |
| POST | `/api/reset` | forget the learned model |

Interactive API docs are auto-generated at <http://localhost:8000/docs>.

## Files added for the web app

| File | Role |
|---|---|
| `app.py` | FastAPI backend; serves the dashboard + JSON API |
| `engine_service.py` | stateful, thread-safe engine (live learning + persistence) |
| `web/index.html` | dashboard markup |
| `web/styles.css` | the visual design system |
| `web/app.js` | fetches data, draws conviction meters + charts, closes the loop |

State lives in `webapp.db` (audit log) and `bandit_state.json` (the learned
model). Delete both to start completely fresh.

## Toward online deployment

This runs as a normal ASGI app, so any of these work with almost no change:

```bash
# production server
pip install gunicorn
gunicorn -k uvicorn.workers.UvicornWorker app:app --bind 0.0.0.0:8000
```

For a real deployment: move `webapp.db` to managed Postgres, put the bandit state
in that DB (or object storage), run behind the gunicorn/uvicorn combo above, and
host on Render / Railway / Fly.io / a container on any cloud. Swap the synthetic
`world.py` for real data adapters and you have a live product.

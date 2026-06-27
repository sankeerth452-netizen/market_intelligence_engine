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
- Record result — the slider starts **neutral**; drag it to what the page
  *actually* delivered (0% = the build was wasted, 100% = a top performer) and hit
  Save. This feeds straight back into the model — watch the cards' conviction
  meters slide, the weight bars shift, and the gauges climb, all at once.
- What it trusts & distrusts — the weights the engine learned from outcomes. The
  amber `tiktok_velocity` bar pointing left is the engine having taught itself to
  distrust loud single-channel hype.
- Why the loop wins — a bold headline (**+40% ± 1% across 30 independent markets,
  winning all 30**, computed by `evaluate.py`), then the head-to-head curve for one
  representative market.

## Try this to feel the loop

1. Open the dashboard — note the learned weights (TikTok already negative).
2. Click **Reset learning** in the rail. Everything zeroes; the model forgets.
3. Step through a few weeks recording *honest* results — drag cards with
   **multi-source** evidence high, and ones tagged **single-channel only** low
   (0% = the build was wasted). Watch the weights separate from zero and
   `tiktok_velocity` dive — the engine relearning, in real time, that loud
   single-channel hype doesn't pay.

## Endpoints (for wiring a different frontend or automating)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/brief?week=8&k=3` | ranked opportunities |
| POST | `/api/outcome` | `{rec_id, reward}` → closes the loop |
| GET | `/api/weights` | learned signal weights |
| GET | `/api/status` | loop counters |
| GET | `/api/simulate` | head-to-head proof data (one market) |
| GET | `/api/robustness` | multi-seed robustness + ablation (from `evaluate.py`) |
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

State lives entirely in `webapp.db` — the audit log *and* the learned model (in a
`model_state` table) — so deleting that one file resets everything locally (in
production it all lives in Postgres instead). Or just hit **Reset learning** in the UI.

## Online deployment

Wired for **Render + Postgres** out of the box: `store.py` runs on SQLite locally
and Postgres in the cloud (chosen by `DATABASE_URL`), the learned model persists
to the database so it survives restarts, a `Dockerfile` builds the image, and
`render.yaml` provisions the web service + database together.

See **[DEPLOY.md](DEPLOY.md)** for the click-by-click guide. The short version:

```bash
# run the production image locally first
docker build -t mie:local . && docker run --rm -p 8011:8000 mie:local   # http://localhost:8011
```

Then push to GitHub and point Render at the repo (New → Blueprint) — it reads
`render.yaml` and creates everything. Swap the synthetic `world.py` for real data
adapters and you have a live product.

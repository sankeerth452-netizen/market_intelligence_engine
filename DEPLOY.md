# Deploying the Market Intelligence Engine

The app is production-ready: it runs on **Postgres** in the cloud (SQLite locally),
ships as a **Docker** image, and includes a Render **Blueprint** (`render.yaml`)
that provisions the web service + database together. All of it is verified
locally — including against a real Postgres and the built container — before you
touch the cloud.

Steps marked **🙋 you** are yours to do; everything else I can run for you.

---

## Already done & verified locally (no action needed)
- `store.py` uses SQLAlchemy → SQLite locally, Postgres in production (chosen by `DATABASE_URL`).
- The learned model persists to the database, so it survives restarts (no local file).
- `Dockerfile` + `.dockerignore` build a clean, single-worker image.
- `render.yaml` wires a free web service to a free managed Postgres.
- `/api/health` is the platform health check.

**Verified locally (2026-06-27), not just claimed:** the full test suite (29 tests)
passes; the app boots, pre-trains and closes the loop (including a negative-reward
"flop") against a **real Postgres 16** in Docker, with the learned model reloading
after a simulated restart; and the **production Docker image** — run against that
same Postgres — serves `/`, `/api/health`, `/api/brief` and `/api/robustness`
(all HTTP 200). So the cloud deploy is exercising a path that already works.

---

## Part 1 — Get the code on GitHub (~5 min)

The GitHub CLI (`gh`) is the smoothest path and isn't installed yet.

1. **🙋 you** — install it and log in (the login opens your browser):
   ```bash
   brew install gh
   gh auth login          # choose: GitHub.com → HTTPS → "Login with a web browser"
   ```
2. Then create the repo and push in one command (I can run this once you're logged in):
   ```bash
   gh repo create market_intelligence_engine --private --source=. --remote=origin --push
   ```

> Prefer not to install `gh`? Create an empty repo at <https://github.com/new>
> (no README/.gitignore), then tell me the URL — I'll wire the remote and you
> approve the push.

---

## Part 2 — Deploy on Render (~10 min, mostly waiting)

1. **🙋 you** — sign up at <https://render.com> and **"Sign in with GitHub"**
   (connects your repos automatically; free, no credit card).
2. **🙋 you** — dashboard → **New +** → **Blueprint**.
3. **🙋 you** — pick the `market_intelligence_engine` repo. Render reads
   `render.yaml`, shows it will create a **web service + a Postgres database**,
   and you click **Apply**.
4. Render builds the image, provisions Postgres, injects `DATABASE_URL`, and boots
   the app (it pre-trains on first start — a few seconds). First build ≈ 5–10 min.
5. **🙋 you** — open the URL Render gives you
   (e.g. `https://market-intelligence-engine.onrender.com`) and share it.

---

## Good to know
- **Cold start:** the free web service sleeps after ~15 min idle and wakes on the
  next request (~30–60 s). Fine for a demo; upgrade the plan to keep it warm.
- **Free Postgres expires after 90 days** (Render policy). Before then, create a
  fresh free DB (or upgrade) — the model and log re-seed automatically on boot.
- **Every `git push`** to the default branch auto-redeploys (`autoDeploy` in `render.yaml`).
- **Logs & shell** live in the Render dashboard for the service.

---

## Run the production image locally (optional sanity check)
```bash
docker build -t mie:local .
docker run --rm -p 8011:8000 mie:local        # then open http://localhost:8011
```

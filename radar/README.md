# The Radar — daily social trend discovery

A self-contained mini-dashboard that reads three sources every day — **Google Trends,
TikTok and Instagram** — for one topic (default: **crafts**, Australia) and turns what's
trending into **5 social content ideas** you can pitch.

Built to be lifted straight into another dashboard: the whole `radar/` folder is
self-contained (no imports from the parent project) and depends only on `fastapi` +
`uvicorn` — everything else is the Python standard library.

## Run it

```bash
cd radar
pip install -r requirements.txt
uvicorn radar_app:app --reload --port 8000
# open http://localhost:8000
```

With **no keys set it runs in SAMPLE mode** — realistic crafts trends so you can see the
shape of it. Nothing is presented as real live data; the header shows a `SAMPLE DATA`
badge. Add the keys below and it goes **live**.

## Configuration (all optional; env vars)

| Variable | What it does | Default |
|---|---|---|
| `APIFY_API_KEY` | Turns on live data (Google Trends + TikTok + Instagram via Apify). | — (sample mode) |
| `ANTHROPIC_API_KEY` | Writes the 5 ideas with Claude; without it, a grounded rule-based fallback is used. | — (rules) |
| `RADAR_TOPIC` | The topic label. | `crafts` |
| `RADAR_TOPIC_MID` | Google Trends topic id. | `/m/01mrgs` (Craft) |
| `RADAR_GEO` | Region. | `AU` |
| `RADAR_KEYWORDS` | Seed hashtags/keywords to scan socially. | `crafts,craftok,diy crafts,craft ideas` |
| `APIFY_TIKTOK_ACTOR` | Apify actor id for TikTok. | `sociavault~tiktok-keyword-search-scraper` |
| `APIFY_INSTAGRAM_ACTOR` | Apify actor id for Instagram. | `apify~instagram-hashtag-scraper` |
| `APIFY_TRENDS_ACTOR` | Apify actor id for Google Trends. | `emastra~google-trends-scraper` |

> **Note on the Apify actors:** the TikTok actor is the same one the parent project already
> uses. The Instagram and Google Trends actor input/output shapes vary between actors, so the
> parsers in `sources.py` are deliberately defensive — when you plug in your real key, sanity-
> check one live run and tweak the field mapping there if a chosen actor returns different keys.
> (Google is used via Apify on purpose: Google 429s direct server access to Trends.)

## How it works

```
sources.py   → pulls raw signals from the 3 sources (fail-soft; sample fallback)
engine.py    → collect → rank_trends (define "trending") → make_ideas (Claude/rules) → cache daily
radar_app.py → FastAPI: GET /api/radar, POST /api/refresh, GET /api/health, and the dashboard
web/         → the dashboard (index.html, app.js, styles.css)
data/        → daily.json (one cached build per day)
```

**"Trending" (our definition):** a sub-topic is trending when it shows recent momentum
(velocity) on a source, and it trends *more strongly* when independent sources agree — a
breakout that Trends, TikTok and Instagram all show is a stronger, earlier signal than one
channel alone. Each trend is also tagged **right-now** (memes, ~1 week) or **building**
(6–12 weeks), matching the brief's two speeds of opportunity.

## Endpoints

- `GET /api/radar` — today's radar (5 ideas + ranked trends + raw signals), cached to one build/day.
- `POST /api/refresh` — force a fresh build for today.
- `GET /api/health` — liveness + whether Apify/AI are configured.

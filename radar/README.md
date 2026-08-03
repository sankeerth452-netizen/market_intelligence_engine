# The Radar — daily social trend discovery

A self-contained mini-dashboard that reads three sources every day — **Google Trends,
TikTok and Instagram** — for one topic (default: **crafts**, Australia) and turns what's
trending into **5 specific, immediately-postable content ideas** for organic Meta/TikTok.

Built to be lifted straight into another dashboard: the whole `radar/` folder is
self-contained (no imports from the parent project). It depends on `fastapi` + `uvicorn`,
plus `psycopg` for the optional history archive — everything else is the Python standard
library.

## Run it

```bash
cd radar
pip install -r requirements.txt
uvicorn radar_app:app --reload --port 8000
# open http://localhost:8000
With no keys set it runs in SAMPLE mode — realistic crafts trends so you can see the
shape of it. Nothing is presented as real live data; the header shows a SAMPLE DATA
badge. Add the keys below and it goes live.

There is no manual refresh control. The first request of each new calendar day
automatically triggers that day's build; everyone after that gets the same cached read
for the rest of the day.

Configuration (all optional; env vars)
Variable	What it does	Default
APIFY_API_KEY	Turns on live TikTok + Instagram data via Apify.	— (sample mode)
ANTHROPIC_API_KEY	Writes the 5 ideas with Claude; without it, a grounded rule-based fallback is used.	— (rules)
DATABASE_URL	A Postgres connection string — turns on the History calendar (past days survive restarts/redeploys).	— (no history)
RADAR_TOPIC	The topic label.	crafts
RADAR_TOPIC_MID	Google Trends topic id.	/m/01mrgs (Craft)
RADAR_GEO	Region.	AU
RADAR_KEYWORDS	Seed hashtags/keywords to scan socially.	crafts,craftok,diy crafts,craft ideas
APIFY_TIKTOK_ACTOR	Apify actor id for TikTok.	sociavault~tiktok-keyword-search-scraper
APIFY_INSTAGRAM_ACTOR	Apify actor id for Instagram.	apify~instagram-hashtag-scraper
TRENDS_TIMEOUT	Seconds before a direct Google Trends/News request gives up.	8
Google Trends needs no key at all. It hits the same free, unofficial endpoint
pytrends uses for rising related queries. Google rate-limits that endpoint hard from
cloud/datacenter IPs, so a 429 trips a circuit breaker and sources.py falls back to
real Google News coverage (also free) for candidate rising terms — filtered so a phrase
that just restates the topic itself ("arts and crafts") doesn't get treated as a
micro-trend — then to sample data only if both are unreachable.

Note on the Apify actors: TikTok + Instagram still need APIFY_API_KEY — neither
platform has a free public trend API. The TikTok actor is the same one the parent
project already uses. Actor input/output shapes vary, so the parsers in sources.py
are deliberately defensive — when you plug in your real key, sanity-check one live run
and tweak the field mapping there if a chosen actor returns different keys.

Turning on the History calendar
The History button/calendar in the UI is populated from Postgres, not local disk — Render's
free-tier disk does not survive redeploys or periodic restarts, so a JSON file alone can't
back a reliable archive. To enable it:

Render dashboard → New + → PostgreSQL → create a small free database (separate
from any other database in this project — Radar owns its own history table).
Copy its Internal Database URL.
On the Radar web service → Environment → add DATABASE_URL with that value → save
(triggers a redeploy).
With no DATABASE_URL set, the app runs exactly as before: no history, one day's build
cached locally, GET /api/history returns an empty list, and the calendar shows a
"no history yet" message instead of erroring.

How it works
sources.py   → pulls raw signals from the 3 sources (fail-soft; sample fallback)
engine.py    → collect → rank_trends (define "trending") → make_ideas (Claude/rules) → cache + persist daily
store.py     → optional Postgres history archive (no-op without DATABASE_URL)
radar_app.py → FastAPI: GET /api/radar, GET /api/history[/date], GET /api/health, and the dashboard
web/         → the dashboard (index.html, app.js, styles.css) incl. the History calendar
data/        → daily.json (this instance's own cache; Postgres is the durable copy)
"Trending" (our definition): a sub-topic is trending when it shows recent momentum
(velocity) on a source, and it trends more strongly when independent sources agree — a
breakout that Trends, TikTok and Instagram all show is a stronger, earlier signal than one
channel alone. Each trend is also tagged right-now (memes, ~1 week) or building
(6–12 weeks), matching the brief's two speeds of opportunity. Ideas are written as one
concrete, filmable/postable concept per micro-trend — naming the exact term, the platform
and format, and a literal hook/caption line — never a broad category statement.

Endpoints
GET /api/radar — today's radar (5 ideas + ranked trends + raw signals); built once per
calendar day, by whichever request happens to be first that day.
GET /api/history — dates with a stored past build, newest first (empty without
DATABASE_URL).
GET /api/history/{date} — a specific past day's radar (YYYY-MM-DD), 404 if not stored.
POST /api/refresh — force a rebuild now. Not exposed in the UI; ops/debugging only —
each call is a real, billed Apify run, so don't script this on a loop.
GET /api/health — liveness + whether Apify/AI/history storage are configured.

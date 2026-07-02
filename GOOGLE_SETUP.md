# Google integration setup (real outcome-based learning)

The engine works fully **without** Google. Connecting Google Search Console + GA4
just adds a real, outcome-based learning loop: it measures whether the pages you
build actually gained clicks/rankings/traffic, and uses that to refine scoring.

Everything is off until these four environment variables are set — nothing else
in the app changes or breaks in the meantime.

## 1. Create a Google Cloud project + OAuth client

1. https://console.cloud.google.com → create a project.
2. **APIs & Services → Enable APIs** — enable:
   - *Google Search Console API*
   - *Google Analytics Data API*
   - *Google Analytics Admin API*
3. **OAuth consent screen** → External. Add the two scopes (read-only):
   - `.../auth/webmasters.readonly`
   - `.../auth/analytics.readonly`
   These are "sensitive" scopes. In **Testing** mode you can add a handful of test
   users immediately (no Google review). For public/production use you'll submit
   the consent screen for Google verification.
4. **Credentials → Create OAuth client ID → Web application.**
   - Authorized redirect URI:
     `https://market-intelligence-engine-x998.onrender.com/api/google/callback`
     (must exactly match `GOOGLE_REDIRECT_URI`).
   - Copy the **Client ID** and **Client secret**.

## 2. Set the environment variables (Render → Environment)

| Variable | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | from step 1.4 |
| `GOOGLE_CLIENT_SECRET` | from step 1.4 |
| `GOOGLE_REDIRECT_URI` | `https://…/api/google/callback` (already in render.yaml) |
| `TOKEN_ENCRYPTION_KEY` | a Fernet key (below) — **keep it stable**, tokens are encrypted with it |

Generate the encryption key once:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 3. Connect (the client does this in the app)

Dashboard → **Settings → Integrations → Connect Google** → grant read-only access →
pick the Search Console site and GA4 property that match the website.

## How the loop then runs (automatically)

1. **Collect** — a background job pulls ~120 days of per-page metrics from GSC + GA4
   (throttled to ~once/day; cached, so the APIs aren't spammed).
2. **Track** — mark a recommendation "We built this" on the plan and give the page URL.
3. **Evaluate** — 30–90 days later, the target page's performance is compared
   *before vs after* implementation (clicks, impressions, position, CTR, traffic,
   conversions).
4. **Learn** — that real result becomes a reward that updates the model *from the
   recommendation's own signals*. Real outcomes gradually supersede the expert
   priors. Nothing is ever fabricated — with no data, priors + live signals stand.

## Security

- Only **read-only** scopes are requested; Google passwords are never seen or stored.
- Tokens (access + refresh) are **encrypted at rest** (Fernet) and auto-refresh.
- A revoked grant is detected and the connection is cleared gracefully.
- Everything is namespaced per client, ready for multiple clients.

## Adding other data sources later

The learner consumes a **standardised outcome** (`reward_engine.py`). Any future
source (Adobe Analytics, a CRM, etc.) only needs to emit that same dict — the
learning logic doesn't change.

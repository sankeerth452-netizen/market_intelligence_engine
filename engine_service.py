"""
engine_service.py
-----------------
A stateful, thread-safe wrapper that turns the offline engine into a live
service the web app can drive. It holds the market world and the learning bandit
in memory, and persists recommendations, outcomes AND the learned model to the
database (SQLite locally, Postgres in production) so progress survives a restart
even on an ephemeral filesystem.

Recording a result here genuinely closes the loop: the realised reward is fed
straight into bandit.update(), so the next brief reflects what was learned.
"""
import json
import os
import threading
import time

import numpy as np

import config
import client_config
import assistant as assistant_mod
import strategist as strategist_mod
import competitors as competitors_mod
import ahrefs
import content_gap
import forecast
import ideas as ideas_mod
import google_oauth
import search_console
import ga4
import outcome_evaluator
import principles
import reward_engine
from world import build_world
from bandit import LinUCB
from engine_core import iter_candidates, run_head_to_head
import recommender as rec
import store

# Web-app database: Postgres in production (via DATABASE_URL), else a local
# SQLite file. Kept separate from the CLI/sim's mie.db on purpose.
DB_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(os.path.dirname(__file__), "webapp.db"))
MODEL_KEY = "bandit"
EVAL_PATH = os.path.join(os.path.dirname(__file__), "evaluation.json")

# Data source for the live brief: "synthetic" (default — the seeded demo world,
# what the deployed dashboard shows) or "real" (live Google News + site crawl via
# realworld.py). Flip with the DATA_MODE env var; synthetic is always the safe
# fallback so the public demo can never break.
DATA_MODE = os.environ.get("DATA_MODE", "synthetic").strip().lower()
REAL_CACHE_TTL = 1800.0  # seconds; live signals are slow + rate-limited -> cache


class EngineService:
    def __init__(self):
        self.lock = threading.Lock()
        self.topics, self.index, _ = build_world()
        self.engine = store.connect(DB_URL)
        self.bandit = self._load_bandit()   # ships pre-trained on first boot
        self._sim_cache = None
        self._real_cache = None             # (timestamp, candidates, index)
        self._plan_cache = {}               # topic -> AI action plan (stable per session)
        self._comp_cache = None             # (timestamp, competitor report)
        self._comp_refreshing = False
        self._vol_cache = None              # (timestamp, {category_lower: volume})
        self._aiv_cache = None              # (timestamp, AI-visibility report)
        self._demand_cache = None           # (timestamp, demand forecast report)
        self._seo_collect_ts = 0.0          # last SEO-metrics collection time
        if DATA_MODE == "real":             # warm the live-data cache off the request path
            threading.Thread(target=self._warm_real_cache, daemon=True).start()
        if os.environ.get("COMPETITOR_CRAWL_ON_BOOT", "").strip() == "1":
            threading.Thread(target=self._baseline_competitors, daemon=True).start()
        if google_oauth.enabled():          # collect SEO data + evaluate outcomes periodically
            threading.Thread(target=self._google_worker, daemon=True).start()

    def _warm_real_cache(self):
        """Pre-fetch live signals after boot so the first request isn't slow.
        Runs in the background; the health check stays instant either way."""
        try:
            self._real_candidates()
        except Exception:
            pass

    # ---------------------------------------------------------- persistence ----
    def _load_bandit(self) -> LinUCB:
        data = store.load_model(self.engine, MODEL_KEY)
        if data:
            try:
                loaded = LinUCB.from_dict(data)
                if loaded.d == config.N_FEATURES:
                    # Keep a model that has learned from real verdicts, or one
                    # already seeded with the prior. Only a pristine EMPTY model
                    # (0 updates AND zero weights) is upgraded to the prior — this
                    # also auto-heals an older blank/cold model on the next boot.
                    if loaded.n_updates > 0 or float(np.max(np.abs(loaded.b))) > 1e-9:
                        return loaded
            except Exception:
                pass
        bandit = self._seed_prior()
        store.save_model(self.engine, MODEL_KEY, json.dumps(bandit.to_dict()))
        return bandit

    def _seed_prior(self) -> LinUCB:
        """A live model that starts from the marketing best-practice PRIOR (not
        blank, not synthetic): it ranks well from day one on the real signals and
        refines from any real verdicts recorded on the plan."""
        return LinUCB(config.N_FEATURES, alpha=config.SETTINGS["linucb_alpha"]) \
            .seed_prior(config.PRIOR_WEIGHTS, config.PRIOR_STRENGTH)

    def _save_bandit(self) -> None:
        store.save_model(self.engine, MODEL_KEY, json.dumps(self.bandit.to_dict()))

    # ----------------------------------------------------------------- brief ----
    def brief(self, week: int, k: int):
        """Ranked opportunities. In synthetic mode the plan is deterministic per
        week (the bandit's view evolves as results come in); in real mode it's the
        live picture from the adapters (Google News + site crawl), cached."""
        with self.lock:
            if DATA_MODE == "real":
                cands, index = self._real_candidates()
            else:
                rng = np.random.default_rng(config.SETTINGS["seed"] * 1000 + week)
                cands = iter_candidates(self.topics, self.index, week, rng)
                index = self.index
            picks = rec.recommend(cands, self.bandit, index, k)
            out = []
            for i, p in enumerate(picks, 1):
                rid = store.save_recommendation(
                    self.engine, week, p["topic"].name, p["topic"].category,
                    p["topic"].kind, p["roi"], p["pred"]["mean"],
                    p["pred"]["uncertainty"], p["topic"].effort,
                    rec.rationale(p["signals"], p["pred"], p["topic"].effort,
                                  p["exploring"]),
                    context_json=json.dumps(p["x"]))
                out.append(self._serialize(rid, i, p, week))
            scored = self._all_scored()
            cuts = self._priority_cuts([o["roi"] for o in scored])
            top = scored[0]["roi"] if scored else 1.0
            for c in out:
                c["priority"] = self._priority_label(c["roi"], cuts)
                c["strength"] = round(min(1.0, c["roi"] / top), 3) if top > 0 else 0.0
            return out

    def _real_candidates(self):
        """Live candidates from the adapters, cached. Fetching ~12 live sources is
        slow and rate-limited, so we refresh at most every REAL_CACHE_TTL seconds
        and reuse the result for briefs in between."""
        now = time.time()
        if self._real_cache and now - self._real_cache[0] < REAL_CACHE_TTL:
            return self._real_cache[1], self._real_cache[2]
        import realworld
        cands, index, _label = realworld.real_candidates()
        self._real_cache = (now, cands, index)
        return cands, index

    def _serialize(self, rid, rank, p, week):
        sig = p["signals"]
        chips = []
        if sig["trend_surprise"] > 0.6:
            chips.append("demand rising")
        if sig["trend_changepoint"] > 0.5:
            chips.append("change-point")
        if sig["cross_source_agreement"] > 0.6:
            chips.append("multi-source")
        elif sig["cross_source_agreement"] < 0.4:
            chips.append("single-channel only")
        if sig["reddit_neg_sentiment"] > 0.5:
            chips.append("reputation risk")
        if sig["semantic_gap"] > 0.6:
            chips.append("content gap")
        action = "Optimise existing page" if sig["semantic_gap"] < 0.45 else "Create new page"
        return {
            "id": rid, "rank": rank, "week": week,
            "topic": p["topic"].name, "category": p["topic"].category,
            "effort": p["topic"].effort, "action": action,
            "roi": round(p["roi"], 3),
            "value": round(float(p["pred"]["mean"]), 3),
            "uncertainty": round(float(p["pred"]["uncertainty"]), 3),
            "exploring": bool(p["exploring"]),
            "evidence": chips,
            "headlines": p.get("headlines", [])[:2],
            "confidence": self._confidence(sig),
            "signals": {k: round(float(v), 3) for k, v in sig.items()},
        }

    # --------------------------------------------------------------- outcome ----
    def record_outcome(self, rec_id: int, reward: float):
        with self.lock:
            x = store.get_context(self.engine, rec_id)
            if x is None:
                return {"ok": False,
                        "error": f"No recommendation #{rec_id} to attach a result to."}
            self.bandit.update(np.asarray(x, dtype=float), float(reward))
            store.record_outcome(self.engine, rec_id, float(reward))
            self._save_bandit()
            self._sim_cache = None
            return {"ok": True, "model_updates": self.bandit.n_updates}

    # --------------------------------------------------------------- weights ----
    def weights(self):
        theta = self.bandit.learned_weights()["theta"]
        items = []
        for name, w in zip(config.FEATURE_NAMES, theta):
            if name == "bias":
                continue
            items.append({"name": name, "weight": round(float(w), 4),
                          "fixed": round(config.STATIC_WEIGHTS.get(name, 0.0), 3)})
        items.sort(key=lambda d: d["weight"], reverse=True)
        return {"learned": items, "model_updates": self.bandit.n_updates}

    # ---------------------------------------------------------------- status ----
    def status(self):
        s = store.summary(self.engine)
        s["model_updates"] = self.bandit.n_updates
        s["data_mode"] = DATA_MODE
        c = client_config.active_client()
        s["client"] = {
            "name": c.name, "industry": c.industry,
            "categories": len(c.categories), "site_source": c.site_source,
            "is_demo": c.is_demo,
        }
        return s

    def reset(self):
        with self.lock:
            self.bandit = self._seed_prior()      # back to the prior, not blank
            store.reset_all(self.engine)
            self._save_bandit()
            self._sim_cache = None
            return {"ok": True}

    # ------------------------------------------- robustness (precomputed) ----
    def robustness(self):
        """The multi-seed robustness + ablation result produced by evaluate.py.

        Read from evaluation.json so a single web request never has to run the
        2-minute sweep. Returns None when the file is absent, so the dashboard
        degrades gracefully to just the single-market proof curve."""
        try:
            with open(EVAL_PATH) as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return None

    # ------------------------------------ signals / summary / assistant ----
    @staticmethod
    def _priority_cuts(rois):
        """Relative High/Medium ROI cutoffs from the current candidate spread, so
        priority stays meaningful whatever the ROI scale (a cold model explores
        with higher uncertainty, so its ROIs sit higher — relative bands fix it)."""
        vals = sorted([float(r) for r in rois if r is not None], reverse=True)
        if not vals:
            return (0.62, 0.40)
        top = vals[0]
        return (0.72 * top, 0.5 * top)

    @staticmethod
    def _priority_label(roi, cuts):
        hi, mid = cuts
        return "High" if roi >= hi else "Medium" if roi >= mid else "Low"

    @staticmethod
    def _confidence(sig):
        """How sure we are of THIS recommendation, from the data itself — do
        independent sources corroborate, and are the core demand signals strong?
        (This is the client-facing 'confidence', not the bandit's exploration
        uncertainty, which measures model training, not recommendation quality.)"""
        cross = sig.get("cross_source_agreement", 0.5)
        core = (sig.get("trend_surprise", 0) + sig.get("news_relevance", 0)
                + sig.get("semantic_gap", 0)) / 3.0
        return round(min(1.0, 0.55 * cross + 0.45 * core), 3)

    def _all_scored(self):
        """All current candidates, scored by the bandit, sorted by ROI. Real mode
        uses the live adapters (cached); synthetic uses the seeded world."""
        if DATA_MODE == "real":
            cands, _index = self._real_candidates()
        else:
            rng = np.random.default_rng(config.SETTINGS["seed"] * 1000 + 8)
            cands = iter_candidates(self.topics, self.index, 8, rng)
        out = []
        for c in cands:
            pred = self.bandit.predict(c["x"])
            out.append({
                "topic": c["topic"].name, "category": c["topic"].category,
                "effort": c["topic"].effort,
                "signals": {k: round(float(v), 3) for k, v in c["signals"].items()},
                "roi": round(float(rec.roi_score(pred, c["topic"].effort)), 3),
                "value": round(float(pred["mean"]), 3),
                "uncertainty": round(float(pred["uncertainty"]), 3),
                "confidence": self._confidence(c["signals"]),
                "headlines": c.get("headlines", []),
            })
        out.sort(key=lambda s: s["roi"], reverse=True)
        cuts = self._priority_cuts([o["roi"] for o in out])
        top = out[0]["roi"] if out else 1.0
        for o in out:
            o["priority"] = self._priority_label(o["roi"], cuts)
            o["strength"] = round(min(1.0, o["roi"] / top), 3) if top > 0 else 0.0
        return out

    def _weights_list(self):
        theta = self.bandit.learned_weights()["theta"]
        items = [{"name": n, "weight": round(float(w), 4)}
                 for n, w in zip(config.FEATURE_NAMES, theta) if n != "bias"]
        items.sort(key=lambda d: d["weight"], reverse=True)
        return items

    def ai_visibility(self):
        """AI 'share of voice' for the client vs its competitors, from Ahrefs
        Brand Radar. Cached a full week by default because the call is expensive
        (~3-4k units). {enabled: false} unless AHREFS_API_KEY is set."""
        if not ahrefs.enabled():
            return {"enabled": False, "brands": []}
        now = time.time()
        ttl = float(os.environ.get("AIV_CACHE_TTL", "604800"))   # 7 days
        if self._aiv_cache and now - self._aiv_cache[0] < ttl:
            return self._aiv_cache[1]
        client = client_config.active_client()
        competitors = [c["name"] for c in competitors_mod.sites()]
        rows = ahrefs.share_of_voice(client.name, competitors)
        data = {"enabled": True, "client": client.name, "sources": ahrefs.AI_SOURCES,
                "brands": rows, "updated": now}
        if rows:                                   # only cache a real result
            self._aiv_cache = (now, data)
        return data

    def content_gaps(self):
        """Ranked missing-content opportunities from the Ahrefs content-gap export
        (keywords where a competitor ranks and JB does not), plus JB's own content
        strengths from the top-pages export. Empty until exports are imported."""
        gaps = content_gap.content_gaps()
        tp = content_gap.top_pages()
        opps = gaps.get("opportunities", [])
        return {
            "available": content_gap.available(),
            "client": client_config.active_client().name,
            "generated": gaps.get("generated"),
            "kept": gaps.get("kept", 0),
            "scanned": gaps.get("total_gaps_scanned", 0),
            "addressable_volume": sum(o.get("volume", 0) for o in opps),
            "by_category": gaps.get("by_category", {}),
            "opportunities": opps,
            "jb_strengths": tp.get("jb_strengths", {}),
            "competitors": [n for n in tp.get("sites", {}) if n != "JB Hi-Fi"],
        }

    def marketing_ideas(self):
        """Topics discovered from the content gaps, each with many ranked marketing
        ideas across SEO / Content / Social / Commercial / AI Visibility — re-weighted
        by the principle effectiveness learned so far."""
        mult = principles.multipliers(self.engine, self._client_key())
        data = ideas_mod.generate(mult=mult)
        data["client"] = client_config.active_client().name
        return data

    def principles(self):
        """Learned marketing principles: which idea TYPES pay off (expert prior now,
        refined by real GSC/GA4 outcomes over time)."""
        return {"principles": principles.effectiveness(self.engine, self._client_key())}

    def demand_forecast(self):
        """Per-category demand trend, seasonality and next-month forecast from real
        Ahrefs monthly volume history. Cached a week (history moves slowly); ~500
        units per refresh (date-capped). {enabled:false} unless AHREFS_API_KEY set."""
        if not ahrefs.enabled():
            return {"enabled": False, "categories": []}
        now = time.time()
        ttl = float(os.environ.get("DEMAND_CACHE_TTL", "604800"))   # 7 days
        if self._demand_cache and now - self._demand_cache[0] < ttl:
            return self._demand_cache[1]
        out = []
        for c in client_config.active_client().categories:
            a = forecast.analyze(ahrefs.volume_history(c.lower()))
            if a:
                out.append({"category": c, **a})
        out.sort(key=lambda x: x["current"], reverse=True)
        data = {"enabled": True, "categories": out}
        if out:
            self._demand_cache = (now, data)
        return data

    def _category_volumes(self):
        """Per-category monthly search demand. Prefers TRUE aggregated demand across
        ALL of a category's keywords (from the Ahrefs content-gap export) — so 'Phones'
        counts phone + mobile + smartphone + iphone, not one seed keyword. Falls back
        to live Ahrefs seed-keyword volume, then to {}."""
        demand = content_gap.content_gaps().get("category_demand") or {}
        if demand:
            return {c.lower(): v for c, v in demand.items()}
        if not ahrefs.enabled():
            return {}
        now = time.time()
        if self._vol_cache and now - self._vol_cache[0] < 86400:
            return self._vol_cache[1]
        cats = client_config.active_client().categories
        vols = ahrefs.search_volumes([c.lower() for c in cats])
        self._vol_cache = (now, vols)
        return vols

    def signals(self, k: int = 14):
        with self.lock:
            items = self._all_scored()[:k]
        vols = self._category_volumes()          # outside the lock (network)
        if vols:
            for it in items:
                v = vols.get((it.get("category") or it["topic"]).lower())
                if v is not None:
                    it["volume"] = v
        return {"data_mode": DATA_MODE,
                "client": client_config.active_client().name,
                "items": items, "has_volume": bool(vols)}

    def summary(self):
        with self.lock:
            items = self._all_scored()
            weights = self._weights_list()
            n = self.bandit.n_updates
        client = client_config.active_client()
        if not items:
            return {"client": client.name, "data_mode": DATA_MODE,
                    "actions": [], "rising": [], "gaps": [], "covered": [], "learned": ""}

        def by(sig, rev):
            return [i["topic"] for i in sorted(items, key=lambda i: i["signals"][sig], reverse=rev)[:3]]

        actions = [{"topic": i["topic"],
                    "action": "Create new page" if i["signals"]["semantic_gap"] >= 0.45
                    else "Optimise existing page",
                    "roi": i["roi"], "priority": i.get("priority")} for i in items[:3]]
        top_w = (config.FEATURE_LABELS.get(weights[0]["name"], weights[0]["name"])
                 if weights else "—")
        learned = (f"After learning from {n} results, the system has found that {top_w} "
                   f"is what most reliably pays off."
                   if n else f"Guided by proven marketing priors — {top_w} matters most — and your live "
                             f"signals; it sharpens further as real results are recorded.")
        return {"client": client.name, "industry": client.industry, "data_mode": DATA_MODE,
                "rising": by("trend_surprise", True), "gaps": by("semantic_gap", True),
                "covered": by("semantic_gap", False), "actions": actions, "learned": learned}

    def _assistant_docs(self):
        """The knowledge base the assistant retrieves over (RAG): one document per
        category (with signals, real search volume and headlines) plus competitors,
        AI visibility, what the model has learned, and the validation result. All
        real, already-computed data — assembled from the live caches."""
        with self.lock:
            items = self._all_scored()[:14]
            weights = self._weights_list()
            n = self.bandit.n_updates
        vols = self._category_volumes()                 # cached
        docs = []
        for it in items:
            s = it["signals"]
            vol = vols.get((it.get("category") or it["topic"]).lower())
            heads = "; ".join(f'"{h}"' for h in it.get("headlines", [])[:2])
            gap = s["semantic_gap"]
            parts = [f"{it['topic']} — {it.get('priority', '')} priority.",
                     f"Search demand {round(s['trend_surprise'] * 100)}/100, "
                     f"news coverage {round(s['news_relevance'] * 100)}/100, "
                     f"content gap {round(gap * 100)}/100."]
            if vol is not None:
                parts.append(f"Real search volume about {vol:,} per month.")
            if abs(s.get("tiktok_velocity", 0.5) - 0.5) > 1e-6:
                parts.append(f"TikTok velocity {round(s['tiktok_velocity'] * 100)}/100.")
            if heads:
                parts.append(f"In the news: {heads}.")
            parts.append(f"Recommended: {'create a new page' if gap >= 0.45 else 'strengthen the existing page'}.")
            docs.append({"title": f"Category — {it['topic']}", "text": " ".join(parts)})

        if weights and n > 0:
            top = config.FEATURE_LABELS.get(weights[0]["name"], weights[0]["name"])
            bot = config.FEATURE_LABELS.get(weights[-1]["name"], weights[-1]["name"])
            docs.append({"title": "What the system has learned",
                         "text": f"Learned from {n} real results recorded on the plan: '{top}' most "
                                 f"reliably pays off; '{bot}' least. It updates from every agree/disagree verdict."})
        else:
            docs.append({"title": "Learning status",
                         "text": "No results recorded yet. Recommendations start from the live signals; the "
                                 "system learns what drives results from each verdict recorded on the plan."})
        try:
            for c in self.competitors().get("competitors", []):
                newp = "; ".join(p["title"] for p in c.get("new_pages", [])[:6])
                src = " (data via Ahrefs)" if c.get("note") == "via Ahrefs" else ""
                body = f"{c['name']}{src}: {c.get('total', 0):,} pages tracked."
                body += f" Recently published pages: {newp}." if newp else " No new pages since the last crawl."
                docs.append({"title": f"Competitor — {c['name']}", "text": body})
        except Exception:
            pass
        aiv = self._aiv_cache[1] if self._aiv_cache else None   # peek only (the call is expensive)
        if aiv and aiv.get("brands"):
            sov = ", ".join(f"{b['brand']} {round(b['sov'] * 100)}%" for b in aiv["brands"])
            docs.append({"title": "AI visibility — share of voice",
                         "text": f"How often each brand appears when shoppers ask AI assistants (ChatGPT, "
                                 f"Australia): {sov}. Higher is better."})
        rob = (self.robustness() or {}).get("robustness")
        if rob:
            docs.append({"title": "Validation — does it work",
                         "text": f"Validated across {rob.get('n')} simulated markets: consistently found the "
                                 f"high-value topics and kept dead-end picks low. Real-world lift is confirmed "
                                 f"with live A/B testing once running for the client."})
        return docs

    def assistant(self, question: str):
        docs = self._assistant_docs()
        with self.lock:
            ctx = {
                "client": client_config.active_client().name,
                "data_mode": DATA_MODE,
                "items": self._all_scored()[:14],
                "weights": self._weights_list(),
                "model_updates": self.bandit.n_updates,
                "robustness": (self.robustness() or {}).get("robustness"),
            }
        return {"answer": assistant_mod.answer(question, ctx, docs)}

    # ------------------------------------------------ AI strategist (cached) ----
    def playbook(self, item: dict):
        """A grounded, client-ready action plan for one recommendation. Cached by
        topic so the (possibly LLM-backed) plan is computed once per session."""
        topic = (item.get("topic") or "").strip()
        if topic and topic in self._plan_cache:
            return self._plan_cache[topic]
        plan = strategist_mod.action_plan(item)
        if topic:
            self._plan_cache[topic] = plan
        return plan

    # ------------------------------------------ competitor monitoring ----------
    def competitors(self):
        """Per-competitor page inventory + newly-published pages (cached)."""
        now = time.time()
        if self._comp_cache and now - self._comp_cache[0] < 300:
            return self._comp_cache[1]
        rep = competitors_mod.report(self.engine)
        rep["refreshing"] = self._comp_refreshing
        self._comp_cache = (now, rep)
        return rep

    def refresh_competitors(self):
        """Kick off a competitor crawl in the background (crawling is slow); the
        report picks up the results when it finishes."""
        if self._comp_refreshing:
            return {"ok": True, "status": "already running"}
        self._comp_refreshing = True
        threading.Thread(target=self._refresh_competitors_bg, daemon=True).start()
        return {"ok": True, "status": "started"}

    def _refresh_competitors_bg(self):
        try:
            competitors_mod.refresh(self.engine)
        finally:
            self._comp_refreshing = False
            self._comp_cache = None

    def _baseline_competitors(self):
        """First-boot only: seed a baseline so the view isn't empty. The weekly
        cron + manual refresh handle ongoing updates."""
        try:
            rep = competitors_mod.report(self.engine)
            if all(c["last_crawled"] is None for c in rep["competitors"]):
                self._refresh_competitors_bg()
        except Exception:
            pass

    # ---------------------------- Google integration (real outcome loop) --------
    def _client_key(self):
        c = client_config.active_client()
        return c.site_source or c.name or "default"

    def google_status(self):
        return google_oauth.status(self.engine, self._client_key())

    def google_auth_url(self):
        import base64
        state = base64.urlsafe_b64encode(os.urandom(12)).decode()
        return {"configured": google_oauth.enabled(),
                "auth_url": google_oauth.auth_url(state) if google_oauth.enabled() else None}

    def google_connect(self, code):
        ok = google_oauth.connect(self.engine, self._client_key(), code)
        if ok:
            threading.Thread(target=self._collect_seo_data, args=(True,), daemon=True).start()
        return {"ok": ok}

    def google_properties(self, service):
        tok = google_oauth.access_token(self.engine, self._client_key())
        if not tok:
            return {"properties": [], "error": "not_connected"}
        if service == "gsc":
            sites = search_console.list_sites(tok)
            return {"properties": [{"id": s["url"], "name": s["url"]} for s in sites],
                    "error": search_console.last_error()}
        props = ga4.list_properties(tok)
        return {"properties": [{"id": p["property"], "name": p["name"]} for p in props],
                "error": ga4.last_error()}

    def google_select(self, service, property_id):
        ok = google_oauth.set_property(self.engine, self._client_key(), service, property_id)
        if ok:
            threading.Thread(target=self._collect_seo_data, args=(True,), daemon=True).start()
        return {"ok": ok}

    def google_disconnect(self):
        google_oauth.disconnect(self.engine, self._client_key())
        return {"ok": True}

    def _collect_seo_data(self, force=False):
        """Data Collector: fetch ~120 days of per-page GSC + GA4 metrics for the
        connected property and store them (throttled to ~once/day; cached history
        means the outcome evaluator never re-hits the APIs)."""
        now = time.time()
        if not force and now - self._seo_collect_ts < 86400:
            return
        ck = self._client_key()
        tok = google_oauth.access_token(self.engine, ck)
        if not tok:
            return
        import datetime
        end = datetime.date.today()
        s, e = (end - datetime.timedelta(days=120)).isoformat(), end.isoformat()
        st = google_oauth.status(self.engine, ck)
        try:
            if st["gsc"]["property"]:
                rows = search_console.daily_by_page(tok, st["gsc"]["property"], s, e)
                store.save_seo_metrics(self.engine, ck, "gsc",
                                       [{"page": r["page"], "date": r["date"], "metrics": r} for r in rows])
            if st["ga4"]["property"]:
                rows = ga4.daily_by_page(tok, st["ga4"]["property"], s, e)
                store.save_seo_metrics(self.engine, ck, "ga4",
                                       [{"page": r["page"], "date": r["date"], "metrics": r} for r in rows])
            self._seo_collect_ts = now
        except Exception:
            pass

    def mark_implemented(self, rec_id, target_url=None, idea_type=None):
        """Recommendation Tracker: record when the client shipped a recommendation,
        which page it targets, and which marketing idea TYPE it used — the anchors for
        before/after evaluation and for principle-based learning."""
        store.set_rec_meta(self.engine, int(rec_id), target_url=target_url,
                           implemented_at=time.time())
        store.save_seo_outcome(self.engine, int(rec_id), "pending")
        if idea_type:
            store.principle_set_type(self.engine, int(rec_id), self._client_key(), idea_type)
        return {"ok": True}

    def evaluate_outcomes(self):
        """Outcome Evaluator + Learning hook: for each implemented recommendation,
        measure real before/after impact; when it's readable, turn it into a reward
        and teach the model from that recommendation's OWN stored context vector.
        Real outcomes thus gradually supersede the expert priors. Never fabricated."""
        ck = self._client_key()
        learned = {o["rec_id"]: o for o in store.seo_outcomes_all(self.engine)}
        results = []
        for rec in store.implemented_recs(self.engine):
            outcome = outcome_evaluator.evaluate(self.engine, ck, rec)
            if outcome.get("status") != "evaluated":
                store.save_seo_outcome(self.engine, rec["rec_id"], "pending", detail=outcome)
                results.append({"rec_id": rec["rec_id"], "status": "pending"})
                continue
            r = reward_engine.reward(outcome)
            if r is None:
                store.save_seo_outcome(self.engine, rec["rec_id"], "pending", detail=outcome)
                continue
            already = learned.get(rec["rec_id"], {}).get("status") == "evaluated"
            store.save_seo_outcome(self.engine, rec["rec_id"], "evaluated", reward=r, detail=outcome)
            if not already and rec.get("context"):          # teach once, from real data
                with self.lock:
                    self.bandit.update(np.asarray(rec["context"], dtype=float), float(r))
                    self._save_bandit()
                    self._sim_cache = None
                store.principle_set_reward(self.engine, rec["rec_id"], float(r))  # learn the principle
            results.append({"rec_id": rec["rec_id"], "status": "evaluated", "reward": r})
        return {"evaluated": results}

    def performance(self):
        """Recommendation-Performance dashboard stats (real measured outcomes)."""
        implemented = store.implemented_recs(self.engine)
        outs = store.seo_outcomes_all(self.engine)
        evaluated = [o for o in outs if o["status"] == "evaluated" and o.get("reward") is not None]
        positive = [o for o in evaluated if reward_engine.is_success(o["detail"])]

        def avg(vals):
            vals = [v for v in vals if v is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        return {
            "connected": self.google_status()["account_connected"],
            "total": len(implemented),
            "evaluated": len(evaluated),
            "pending": max(0, len(implemented) - len(evaluated)),
            "positive": len(positive),
            "avg_click_growth": avg([o["detail"].get("clicks_change_pct") for o in evaluated]),
            "avg_position_gain": avg([o["detail"].get("position_change") for o in evaluated]),
            "real_updates": len(evaluated),
        }

    def _google_worker(self):
        """Periodically collect SEO data + evaluate outcomes while connected."""
        while True:
            try:
                if self.google_status()["account_connected"]:
                    self._collect_seo_data()
                    self.evaluate_outcomes()
            except Exception:
                pass
            time.sleep(6 * 3600)

    # ------------------------------------------- head-to-head proof (cached) ----
    def simulate(self):
        if self._sim_cache is not None:
            return self._sim_cache
        s = config.SETTINGS
        topics, index, _ = build_world()
        rng = np.random.default_rng(s["seed"] + 1)
        bandit = LinUCB(config.N_FEATURES, alpha=s["linucb_alpha"])
        res = run_head_to_head(topics, index, s["weeks"], s["weekly_budget"],
                               rng, bandit)
        res.pop("last_loop_picks", None)   # Topic objects: not JSON-serialisable
        self._sim_cache = res
        return self._sim_cache


ENGINE = EngineService()

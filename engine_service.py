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
from world import build_world
from bandit import LinUCB
from engine_core import iter_candidates, run_loop_training, run_head_to_head
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
        if DATA_MODE == "real":             # warm the live-data cache off the request path
            threading.Thread(target=self._warm_real_cache, daemon=True).start()

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
                # Guard: ignore a stale model from a different feature schema
                # (would mis-align with today's context vectors), OR an UNTRAINED
                # one (0 updates — e.g. left behind by a reset). Either way,
                # re-pretrain so the app always boots with informed weights.
                if loaded.d == config.N_FEATURES and loaded.n_updates > 0:
                    return loaded
            except Exception:
                pass
        # First boot (or a stale/incompatible model): pre-train on the synthetic
        # history and log it, so the dashboard opens with informed opinions.
        bandit = self._train_initial()
        store.save_model(self.engine, MODEL_KEY, json.dumps(bandit.to_dict()))
        return bandit

    def _train_initial(self) -> LinUCB:
        """Warm-start the model by replaying the closed-loop learning once,
        recording each recommendation + outcome so the loop counters are real."""
        s = config.SETTINGS
        rng = np.random.default_rng(s["seed"] + 1)
        bandit = LinUCB(config.N_FEATURES, alpha=s["linucb_alpha"])

        def persist(week, p, reward):
            rid = store.save_recommendation(
                self.engine, week, p["topic"].name, p["topic"].category,
                p["topic"].kind, p["roi"], p["pred"]["mean"],
                p["pred"]["uncertainty"], p["topic"].effort,
                rec.rationale(p["signals"], p["pred"], p["topic"].effort,
                              p["exploring"]),
                context_json=json.dumps(p["x"]))
            store.record_outcome(self.engine, rid, reward)

        return run_loop_training(self.topics, self.index, s["weeks"],
                                 s["weekly_budget"], rng, bandit, on_pick=persist)

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
            self.bandit = LinUCB(config.N_FEATURES,
                                 alpha=config.SETTINGS["linucb_alpha"])
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
                "headlines": c.get("headlines", []),
            })
        out.sort(key=lambda s: s["roi"], reverse=True)
        return out

    def _weights_list(self):
        theta = self.bandit.learned_weights()["theta"]
        items = [{"name": n, "weight": round(float(w), 4)}
                 for n, w in zip(config.FEATURE_NAMES, theta) if n != "bias"]
        items.sort(key=lambda d: d["weight"], reverse=True)
        return items

    def signals(self, k: int = 14):
        with self.lock:
            return {"data_mode": DATA_MODE,
                    "client": client_config.active_client().name,
                    "items": self._all_scored()[:k]}

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
                    "roi": i["roi"]} for i in items[:3]]
        top_w = weights[0]["name"].replace("_", " ") if weights else "—"
        learned = (f"After {n} recorded results, the engine most values {top_w}."
                   if n else "No results recorded yet — record outcomes on the plan to start learning.")
        return {"client": client.name, "industry": client.industry, "data_mode": DATA_MODE,
                "rising": by("trend_surprise", True), "gaps": by("semantic_gap", True),
                "covered": by("semantic_gap", False), "actions": actions, "learned": learned}

    def assistant(self, question: str):
        with self.lock:
            ctx = {
                "client": client_config.active_client().name,
                "data_mode": DATA_MODE,
                "items": self._all_scored()[:14],
                "weights": self._weights_list(),
                "model_updates": self.bandit.n_updates,
                "robustness": (self.robustness() or {}).get("robustness"),
            }
        return {"answer": assistant_mod.answer(question, ctx)}

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

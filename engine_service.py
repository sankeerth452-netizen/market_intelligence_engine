"""
engine_service.py
-----------------
A stateful, thread-safe wrapper that turns the offline engine into a live
service the web app can drive. It holds the market world and the learning
bandit in memory, persists recommendations + outcomes to SQLite, and saves the
learned model to disk so progress survives a restart.

Recording a result here genuinely closes the loop: the realised reward is fed
straight into bandit.update(), so the next brief reflects what was learned.
"""
import json
import os
import threading

import numpy as np

import config
from world import build_world, observe, realised_reward
from bandit import LinUCB
import recommender as rec
import store

DB_PATH = os.path.join(os.path.dirname(__file__), "webapp.db")
STATE_PATH = os.path.join(os.path.dirname(__file__), "bandit_state.json")


class EngineService:
    def __init__(self):
        self.lock = threading.Lock()
        self.topics, self.index, _ = build_world()
        self.conn = store.connect(DB_PATH)
        self.bandit = self._load_bandit()   # ships pre-trained on first boot
        self._sim_cache = None

    # ---------------------------------------------------------- persistence ----
    def _load_bandit(self) -> LinUCB:
        if os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH) as f:
                    return LinUCB.from_dict(json.load(f))
            except Exception:
                pass
        # First boot: pre-train on the synthetic history and log it, so the
        # dashboard opens with a model that already has informed opinions.
        bandit = self._train_initial()
        with open(STATE_PATH, "w") as f:
            json.dump(bandit.to_dict(), f)
        return bandit

    def _train_initial(self) -> LinUCB:
        """Warm-start the model by replaying the closed-loop learning once,
        recording each recommendation + outcome so the loop counters are real."""
        s = config.SETTINGS
        weeks, k = s["weeks"], s["weekly_budget"]
        rng = np.random.default_rng(s["seed"] + 1)
        bandit = LinUCB(config.N_FEATURES, alpha=s["linucb_alpha"])
        done = set()
        for week in range(weeks):
            cands = []
            for t in self.topics:
                if t.id in done:
                    continue
                o = observe(t, self.index, week, rng)
                cands.append({"topic": t, "x": o["x"],
                              "signals": o["signals"], "gap": o["gap"]})
            for p in rec.recommend(cands, bandit, self.index, k):
                reward = realised_reward(p["topic"], p["gap"], rng)
                rid = store.save_recommendation(
                    self.conn, week, p["topic"].name, p["topic"].category,
                    p["topic"].kind, p["roi"], p["pred"]["mean"],
                    p["pred"]["uncertainty"], p["topic"].effort,
                    rec.rationale(p["signals"], p["pred"], p["topic"].effort,
                                  p["exploring"]),
                    context_json=json.dumps(p["x"]))
                store.record_outcome(self.conn, rid, reward)
                bandit.update(p["x"], reward)
                done.add(p["topic"].id)
        return bandit

    def _save_bandit(self) -> None:
        with open(STATE_PATH, "w") as f:
            json.dump(self.bandit.to_dict(), f)

    # ----------------------------------------------------------------- brief ----
    def brief(self, week: int, k: int):
        """Ranked opportunities for a given week. Deterministic per week so a
        page refresh shows the same plan, while the bandit's view evolves as
        results come in."""
        with self.lock:
            rng = np.random.default_rng(config.SETTINGS["seed"] * 1000 + week)
            cands = []
            for t in self.topics:
                o = observe(t, self.index, week, rng)
                cands.append({"topic": t, "x": o["x"],
                              "signals": o["signals"], "gap": o["gap"]})
            picks = rec.recommend(cands, self.bandit, self.index, k)
            out = []
            for i, p in enumerate(picks, 1):
                rid = store.save_recommendation(
                    self.conn, week, p["topic"].name, p["topic"].category,
                    p["topic"].kind, p["roi"], p["pred"]["mean"],
                    p["pred"]["uncertainty"], p["topic"].effort,
                    rec.rationale(p["signals"], p["pred"], p["topic"].effort,
                                  p["exploring"]),
                    context_json=json.dumps(p["x"]))
                out.append(self._serialize(rid, i, p, week))
            return out

    def _serialize(self, rid, rank, p, week):
        sig = p["signals"]
        chips = []
        if sig["trend_surprise"] > 0.6:
            chips.append("search rise")
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
            x = store.get_context(self.conn, rec_id)
            if x is None:
                return {"ok": False,
                        "error": f"No recommendation #{rec_id} to attach a result to."}
            self.bandit.update(np.asarray(x, dtype=float), float(reward))
            store.record_outcome(self.conn, rec_id, float(reward))
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
        s = store.summary(self.conn)
        s["model_updates"] = self.bandit.n_updates
        return s

    def reset(self):
        with self.lock:
            self.bandit = LinUCB(config.N_FEATURES,
                                 alpha=config.SETTINGS["linucb_alpha"])
            self.conn.execute("DELETE FROM outcomes")
            self.conn.execute("DELETE FROM recommendations")
            self.conn.commit()
            self._save_bandit()
            self._sim_cache = None
            return {"ok": True}

    # ------------------------------------------- head-to-head proof (cached) ----
    def simulate(self):
        if self._sim_cache is not None:
            return self._sim_cache
        s = config.SETTINGS
        weeks, k = s["weeks"], s["weekly_budget"]
        topics, index, _ = build_world()
        rng = np.random.default_rng(s["seed"] + 1)
        bandit = LinUCB(config.N_FEATURES, alpha=s["linucb_alpha"])
        done_s, done_l = set(), set()
        cum_s, cum_l, tot_s, tot_l, dec_s, dec_l = [], [], 0.0, 0.0, 0, 0

        def cands(done):
            r = []
            for t in topics:
                if t.id in done:
                    continue
                o = observe(t, index, week, rng)
                r.append({"topic": t, "x": o["x"], "signals": o["signals"],
                          "gap": o["gap"]})
            return r

        for week in range(weeks):
            for p in rec.static_select(cands(done_s), k):
                tot_s += realised_reward(p["topic"], p["gap"], rng)
                done_s.add(p["topic"].id)
                dec_s += p["topic"].kind == "decoy"
            cum_s.append(round(tot_s, 3))
            for p in rec.recommend(cands(done_l), bandit, index, k):
                r = realised_reward(p["topic"], p["gap"], rng)
                tot_l += r
                done_l.add(p["topic"].id)
                dec_l += p["topic"].kind == "decoy"
                bandit.update(p["x"], r)
            cum_l.append(round(tot_l, 3))

        self._sim_cache = {
            "weeks": list(range(1, weeks + 1)),
            "static": cum_s, "loop": cum_l,
            "decoys_static": int(dec_s), "decoys_loop": int(dec_l),
            "total_static": round(tot_s, 2), "total_loop": round(tot_l, 2),
            "lift_pct": round((tot_l - tot_s) / max(1e-9, abs(tot_s)) * 100),
        }
        return self._sim_cache


ENGINE = EngineService()

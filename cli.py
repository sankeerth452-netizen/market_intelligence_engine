"""
cli.py
------
A small command line over the engine for day-to-day use.

  python cli.py brief            # generate this week's ranked opportunities
  python cli.py brief --week 6   # simulate a later week (sleepers wake up)
  python cli.py outcome 12 0.7   # record realised reward for recommendation #12
  python cli.py status           # show what the feedback loop has learned

In production the `observe()` calls would hit real adapters (Google Trends,
Reddit/TikTok via Apify, News RSS, site crawl) instead of the synthetic world.
"""
import argparse

import config
from world import build_world, observe
from bandit import LinUCB
import recommender as rec
import store


def _fresh_engine():
    """A demo engine warm-started on a few weeks so predictions aren't blank."""
    topics, index, _ = build_world()
    import numpy as np
    rng = np.random.default_rng(config.SETTINGS["seed"] + 99)
    bandit = LinUCB(config.N_FEATURES, alpha=config.SETTINGS["linucb_alpha"])
    from world import realised_reward
    seen = set()
    for w in range(4):                      # quick warm-up so it has opinions
        for t in topics:
            if t.id in seen:
                continue
            o = observe(t, index, w, rng)
            p = bandit.predict(o["x"])
            if p["ucb"] * 0.7 > 0.4:
                bandit.update(o["x"], realised_reward(t, o["gap"], rng))
                seen.add(t.id)
    return topics, index, bandit


def cmd_brief(args):
    topics, index, bandit = _fresh_engine()
    cands = [{"topic": t, **observe(t, index, args.week, _rng())} for t in topics]
    picks = rec.recommend(cands, bandit, index, args.k)
    conn = store.connect()
    print(f"\nMORNING BRIEF \u2014 week {args.week}  (top {args.k} opportunities)\n")
    for i, p in enumerate(picks, 1):
        rid = store.save_recommendation(
            conn, args.week, p["topic"].name, p["topic"].category, p["topic"].kind,
            p["roi"], p["pred"]["mean"], p["pred"]["uncertainty"], p["topic"].effort,
            rec.rationale(p["signals"], p["pred"], p["topic"].effort, p["exploring"]))
        print(f"[{rid}] {i}. {p['topic'].name}   (ROI {p['roi']:.2f})")
        print(f"      {rec.rationale(p['signals'], p['pred'], p['topic'].effort, p['exploring'])}\n")
    print("Record an outcome later with:  python cli.py outcome <id> <reward 0..1>")


def cmd_outcome(args):
    conn = store.connect()
    store.record_outcome(conn, args.rec_id, args.reward)
    print(f"Recorded reward {args.reward} for recommendation #{args.rec_id}. "
          f"In production this feeds bandit.update() to close the loop.")


def cmd_status(args):
    conn = store.connect()
    print("Feedback-loop summary:", store.summary(conn))


def _rng():
    import numpy as np
    return np.random.default_rng()


def main():
    ap = argparse.ArgumentParser(description="Market Intelligence Engine CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("brief", help="generate this week's ranked opportunities")
    b.add_argument("--week", type=int, default=8)
    b.add_argument("--k", type=int, default=config.SETTINGS["weekly_budget"])
    b.set_defaults(func=cmd_brief)

    o = sub.add_parser("outcome", help="record realised reward for a recommendation")
    o.add_argument("rec_id", type=int)
    o.add_argument("reward", type=float)
    o.set_defaults(func=cmd_outcome)

    s = sub.add_parser("status", help="show what the loop has learned")
    s.set_defaults(func=cmd_status)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

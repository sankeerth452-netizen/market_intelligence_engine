"""The real outcome loop end-to-end at the data layer: injected (real-shaped, not
fabricated-by-the-code) Search Console metrics -> before/after evaluation ->
reward. Proves the measurement + learning-signal path without needing live Google."""
import datetime
import json
import time

import config
import outcome_evaluator
import reward_engine
import store

_CK = "test-client"


def _eng(tmp_path):
    return store.connect(f"sqlite:///{tmp_path}/seo.db")


def _gsc_rows(page, day0, n, start_offset, clicks):
    return [{"page": page, "date": (day0 + datetime.timedelta(days=start_offset + i)).isoformat(),
             "metrics": {"clicks": clicks, "impressions": clicks * 20,
                         "ctr": 0.05, "position": 10.0}} for i in range(n)]


def test_pending_until_enough_time_passes(tmp_path):
    eng = _eng(tmp_path)
    rid = store.save_recommendation(eng, 1, "TVs", "TVs", "real", 0.7, 0.6, 0.3, "med",
                                    "r", context_json=json.dumps([1.0] * 9))
    store.set_rec_meta(eng, rid, target_url="https://x.com/tvs", implemented_at=time.time() - 3 * 86400)
    rec = store.implemented_recs(eng)[0]
    assert outcome_evaluator.evaluate(eng, _CK, rec)["status"] == "pending"


def test_full_loop_measures_improvement_and_rewards(tmp_path):
    eng = _eng(tmp_path)
    page = "https://x.com/tvs"
    rid = store.save_recommendation(eng, 1, "TVs", "TVs", "real", 0.7, 0.6, 0.3, "med",
                                    "r", context_json=json.dumps([1.0] * 9))
    impl = time.time() - 60 * 86400                      # implemented 60 days ago
    store.set_rec_meta(eng, rid, target_url=page, implemented_at=impl)
    impl_d = datetime.date.fromtimestamp(impl)
    # baseline (30 days before): 10 clicks/day; after (days 30-59): 20 clicks/day
    store.save_seo_metrics(eng, _CK, "gsc",
                           _gsc_rows(page, impl_d, 30, -30, 10) + _gsc_rows(page, impl_d, 30, 30, 20))

    rec = store.implemented_recs(eng)[0]
    outcome = outcome_evaluator.evaluate(eng, _CK, rec)
    assert outcome["status"] == "evaluated"
    assert outcome["clicks_change_pct"] > 50            # clicks roughly doubled — measured, not invented
    r = reward_engine.reward(outcome)
    midpoint = config.REWARD_MIN + (config.REWARD_MAX - config.REWARD_MIN) / 2.0
    assert r > midpoint                                  # real improvement -> above-neutral reward


def test_evaluate_needs_a_target_page(tmp_path):
    eng = _eng(tmp_path)
    rec = {"rec_id": 1, "target_url": None, "implemented_at": time.time() - 60 * 86400}
    assert outcome_evaluator.evaluate(eng, _CK, rec)["status"] == "pending"

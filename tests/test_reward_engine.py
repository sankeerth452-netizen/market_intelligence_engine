"""The reward engine maps a standardised outcome to a learning reward: no change
-> neutral midpoint, real improvement -> high, real decline -> negative."""
import config
import reward_engine

_MID = config.REWARD_MIN + (config.REWARD_MAX - config.REWARD_MIN) / 2.0


def test_no_change_is_neutral_midpoint():
    o = {"clicks_change_pct": 0, "position_change": 0, "sessions_change_pct": 0}
    assert abs(reward_engine.reward(o) - _MID) < 0.02


def test_improvement_scores_high():
    o = {"clicks_change_pct": 80, "position_change": 6, "sessions_change_pct": 60,
         "conversions_change_pct": 40}
    r = reward_engine.reward(o)
    assert r > 0.75 and reward_engine.is_success(o) is True


def test_decline_scores_negative():
    o = {"clicks_change_pct": -70, "position_change": -5, "sessions_change_pct": -50}
    r = reward_engine.reward(o)
    assert r < _MID and r >= config.REWARD_MIN and reward_engine.is_success(o) is False


def test_none_when_no_measurable_metrics():
    assert reward_engine.reward({"data_confidence": 0.5}) is None


def test_reward_stays_in_range():
    for o in ({"clicks_change_pct": 9999, "position_change": 99},
              {"clicks_change_pct": -9999, "position_change": -99}):
        r = reward_engine.reward(o)
        assert config.REWARD_MIN <= r <= config.REWARD_MAX

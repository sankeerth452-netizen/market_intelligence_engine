"""
radar/engine.py — The Radar's brain: collect -> rank -> 5 ideas, cached daily.

Pipeline (a daily read):
  1. collect()      pull signals from the 3 sources (Google Trends, TikTok, Instagram)
  2. rank_trends()  DEFINE "trending" = velocity + cross-source agreement, then rank
  3. make_ideas()   turn the top trends into exactly 5 social content-idea cards
                    (Claude Haiku when ANTHROPIC_API_KEY is set, else a grounded
                    rule-based fallback — either way grounded in the real trends)

"Trending" (our chosen definition, per the brief): a sub-topic is trending when it
shows recent momentum (velocity) on at least one source, and it is trending MORE
strongly when independent sources agree — a breakout that TikTok, Instagram and
Google Trends all show is a stronger, earlier signal than one channel alone.
"""
import datetime as _dt
import json
import os
import re
import urllib.request

import sources

MODEL = os.environ.get("RADAR_MODEL", os.environ.get("ASSISTANT_MODEL", "claude-haiku-4-5-20251001"))
_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_CACHE = os.path.join(_DATA, "daily.json")


# --------------------------------------------------------------- collect -------
def collect():
    """Gather raw signals from all three sources. Marks the read live vs sample."""
    g, t, i = sources.google_trends(), sources.tiktok(), sources.instagram()
    is_sample = any(s.get("sample") for s in (g + t + i))
    return {
        "live": sources.live() and not is_sample,
        "sample": is_sample or not sources.live(),
        "topic": sources.TOPIC,
        "geo": sources.GEO,
        "sources": {"google_trends": g, "tiktok": t, "instagram": i},
    }


# ------------------------------------------------- rank (define "trending") ----
_SUFFIXES = ["ofinstagram", "tiktok", "australia", "aus", "ideas", "idea", "kits", "kit",
             "patterns", "pattern", "projects", "project", "making", "tutorial",
             "aesthetic", "art", "diy", "ers", "ing", "s"]


def _canon(term):
    """Collapse hashtag/keyword variants to a shared root so the same trend on
    different sources clusters together (punch needle kit / punchneedle /
    punchneedleart -> punchneedle-ish)."""
    t = re.sub(r"[^a-z]", "", (term or "").lower())
    changed = True
    while changed and len(t) > 5:
        changed = False
        for suf in _SUFFIXES:
            if t.endswith(suf) and len(t) - len(suf) >= 4:
                t = t[:-len(suf)]; changed = True; break
    return t


def _same(a, b):
    if not a or not b:
        return False
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return short == long or (len(short) >= 5 and long.startswith(short)) or a[:6] == b[:6]


def rank_trends(collected, top=6):
    """Cluster signals across sources into ranked trends. Score = strongest velocity
    seen, boosted when independent sources corroborate."""
    signals = []
    for src, arr in collected["sources"].items():
        signals.extend(arr)
    signals.sort(key=lambda s: -s.get("score", 0))

    clusters = []
    for s in signals:
        c = next((c for c in clusters if _same(c["_canon"], _canon(s["term"]))), None)
        if c is None:
            c = {"_canon": _canon(s["term"]), "term": s["term"], "signals": [],
                 "sources": set(), "metrics": [], "links": []}
            clusters.append(c)
        c["signals"].append(s)
        c["sources"].add(s["source"])
        c["metrics"].append(s["metric"])
        c["links"].append({"source": s["source"], "url": s["url"]})
        # prefer a readable, spaced label (Google Trends queries read best)
        if s["source"] == "google_trends" and " " in s["term"]:
            c["term"] = s["term"]

    trends = []
    for c in clusters:
        base = max(s["score"] for s in c["signals"])
        agree = len(c["sources"])
        score = min(1.0, round(base + 0.12 * (agree - 1), 3))
        # two-speed classification (per the brief)
        fast = ("tiktok" in c["sources"] or "instagram" in c["sources"]) and base >= 0.8
        trends.append({
            "term": c["term"],
            "score": score,
            "base": round(base, 3),
            "agreement": agree,
            "sources": sorted(c["sources"]),
            "speed": "right-now" if fast else "building",
            "window": "about a week" if fast else "6-12 weeks",
            "metrics": c["metrics"][:3],
            "links": c["links"][:3],
        })
    trends.sort(key=lambda t: (-t["score"], -t["agreement"], -t["base"]))
    return trends[:top]


# ------------------------------------------------------- 5 ideas (Haiku) -------
_PLAYS = ["Organic social", "Creator campaign", "Publisher partnership"]
_SRC_NAME = {"google_trends": "Google Trends", "tiktok": "TikTok", "instagram": "Instagram"}


def _srcs(sources):
    return ", ".join(_SRC_NAME.get(s, s) for s in sources)


def _llm_ideas(topic, trends):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    facts = "\n".join(
        "- %s (score %.2f, %s, on %s) — %s" % (
            t["term"], t["score"], t["speed"], _srcs(t["sources"]), t["metrics"][0])
        for t in trends)
    system = (
        "You are the trend analyst behind 'The Radar' at a social media agency. From TODAY'S "
        "trending sub-topics within '%s' (from Google Trends, TikTok and Instagram), write EXACTLY "
        "5 punchy social content ideas a brand could act on. Ground every idea in the trends provided "
        "— never invent a trend. Return ONLY a JSON array of 5 objects with keys: "
        "\"title\" (max 8 words), \"signal\" (what's trending, one line), \"why_now\" (right-now moment "
        "or building trend + rough window), \"play\" (one of: Organic social, Creator campaign, "
        "Publisher partnership). No prose outside the JSON." % topic)
    body = json.dumps({
        "model": MODEL, "max_tokens": 900, "system": system,
        "messages": [{"role": "user", "content": "TODAY'S TRENDS:\n%s" % facts}],
    }).encode("utf-8")
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        m = re.search(r"\[.*\]", text, re.S)
        ideas = json.loads(m.group(0) if m else text)
        return ideas[:5] if isinstance(ideas, list) else None
    except Exception:
        return None


def _rule_ideas(trends):
    """Grounded fallback when no AI key: one idea per top trend, with a sensible play."""
    ideas = []
    for i, t in enumerate(trends[:5]):
        fast = t["speed"] == "right-now"
        play = "Organic social" if fast else ("Creator campaign" if t["score"] >= 0.85 else "Publisher partnership")
        title = ("Jump on “%s” now" % t["term"]) if fast else ("Build a series around “%s”" % t["term"])
        why = ("Right-now moment — %s across %s. Window: %s." %
               ("breakout" if t["base"] >= 0.9 else "rising", _srcs(t["sources"]), t["window"])) if fast else \
              ("Building trend on %s — get ahead before it's common knowledge. Window: %s." %
               (_srcs(t["sources"]), t["window"]))
        ideas.append({"title": title, "signal": t["metrics"][0], "why_now": why, "play": play})
    return ideas


def _match_trend(idea, trends, used):
    """Which trend is this idea actually about? Match by content (the idea's
    title/signal text) rather than list position — an LLM idea's order isn't
    guaranteed to follow `trends`, so a positional pairing can attach the
    wrong link/source to an idea."""
    text = _canon((idea.get("title") or "") + " " + (idea.get("signal") or ""))
    for t in trends:
        if t["term"] not in used and _canon(t["term"]) and _canon(t["term"]) in text:
            return t
    return next((t for t in trends if t["term"] not in used), trends[0] if trends else None)


def make_ideas(topic, trends):
    ideas = _llm_ideas(topic, trends) or _rule_ideas(trends)
    used = set()
    for idea in ideas:
        t = _match_trend(idea, trends, used)
        if t is None:
            continue
        used.add(t["term"])
        idea["link"] = (t["links"][0] if t.get("links") else {}).get("url", "")
        idea["source_of_signal"] = _srcs(t["sources"])
    return ideas[:5]


# --------------------------------------------------------- daily orchestration -
def build_radar():
    collected = collect()
    trends = rank_trends(collected)
    ideas = make_ideas(collected["topic"], trends)
    return {
        "date": _dt.date.today().isoformat(),
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "topic": collected["topic"],
        "geo": collected["geo"],
        "live": collected["live"],
        "sample": collected["sample"],
        "ideas": ideas,
        "trends": trends,
        "raw": collected["sources"],
        "ai": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


def daily(force=False):
    """Today's radar, cached to one build per day (unless forced)."""
    today = _dt.date.today().isoformat()
    if not force:
        try:
            with open(_CACHE) as f:
                cached = json.load(f)
            if cached.get("date") == today:
                return cached
        except (OSError, ValueError):
            pass
    result = build_radar()
    try:
        os.makedirs(_DATA, exist_ok=True)
        with open(_CACHE, "w") as f:
            json.dump(result, f, indent=1)
    except OSError:
        pass
    return result

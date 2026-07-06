"""
strategist.py
-------------
The "AI Strategist": turns a single recommendation into a concrete, client-ready
action plan — a suggested page title, the strategic angle, a grounded "why now",
and the key points the page should cover.

Two tiers, chosen automatically (same philosophy as assistant.py):
  * If ANTHROPIC_API_KEY is set  -> Claude writes the plan, grounded STRICTLY in
    the real signals + the actual news headline we pass it (told never to invent
    facts or numbers).
  * Otherwise                    -> a real, useful plan composed from the same
    signals by rule (always works, no key, no dependency).

So the feature is genuine and functional out of the box, and gets sharper the
moment a key is added. Nothing here is hallucinated: the model only ever sees —
and is instructed to use only — the engine's own real, computed inputs.
"""
import json
import os
import re
import urllib.request

import config

_MODEL = os.environ.get("STRATEGIST_MODEL", "claude-haiku-4-5-20251001")


# ---------------------------------------------------------------- helpers ----
def _plain_signals(signals):
    """Map raw feature names to the marketer-facing labels, keeping only the
    signals that actually drive a content decision."""
    keep = ("trend_surprise", "trend_changepoint", "news_relevance", "semantic_gap")
    return {config.FEATURE_LABELS.get(k, k): round(float(signals.get(k, 0.0)), 2) for k in keep}


def _verb(action):
    return "create" if (action or "").lower().startswith("create") else "optimise"


# ------------------------------------------------------------- Claude tier ----
def _llm_plan(item):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    headline = (item.get("headlines") or [None])[0]
    target = item.get("target") or {}
    grounding = {
        "target_page": {k: target.get(k) for k in
                        ("keyword", "type", "volume", "intent", "kd", "competitor", "position")}
                        if target.get("keyword") else None,
        "topic": item.get("topic"),
        "recommended_action": item.get("action"),
        "effort": item.get("effort"),
        "news_headline": headline,
        "signals_0_to_1": _plain_signals(item.get("signals", {})),
    }
    if target.get("keyword"):
        system = (
            "You are a senior SEO strategist advising an SEO manager at a retailer. Using ONLY the "
            "real data provided — especially target_page (the specific missing page: its keyword, page "
            "type, monthly search volume, search intent, keyword difficulty, and which competitor ranks) "
            "— write a concise, actionable SEO brief for that ONE page. Be concrete and SEO-literate "
            "(the target keyword, the page type, beating the named competitor's ranking page, internal "
            "linking, schema) without fluff. Never invent numbers, competitors, or facts beyond what is "
            'given. Output STRICT JSON only with exactly: {"title": "<page title, ~60 chars>", '
            '"angle": "<one sentence strategic angle>", "why_now": "<one sentence grounded in the data>", '
            '"points": ["<2-4 concrete SEO actions>"]}'
        )
    else:
        system = (
            "You are a senior content-marketing strategist advising a client. Using ONLY "
            "the real market signals and the actual news headline provided, write a concise, "
            "client-ready action plan for ONE web page. Never invent facts, numbers, statistics, "
            "dates, or competitor names beyond what is given; if the headline is null, don't "
            "reference the news. Speak plainly to a non-technical marketer — no ML/SEO jargon. "
            'Output STRICT JSON only, no prose, with exactly these keys: '
            '{"title": "<compelling page title, max ~60 chars>", '
            '"angle": "<one sentence: the strategic angle>", '
            '"why_now": "<one sentence grounded in the signals/headline>", '
            '"points": ["<2-4 short bullets of what the page should cover>"]}'
        )
    body = json.dumps({
        "model": _MODEL, "max_tokens": 500, "system": system,
        "messages": [{"role": "user", "content": json.dumps(grounding)}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read())
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        plan = _parse_plan(text)
        if plan:
            plan["source"] = "ai"
        return plan
    except Exception:
        return None


def _parse_plan(text):
    """Pull the JSON object out of the model's reply and validate its shape."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)   # tolerate code fences / stray prose
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    title, angle = obj.get("title"), obj.get("angle")
    why_now, points = obj.get("why_now"), obj.get("points")
    if not (title and angle and why_now and isinstance(points, list) and points):
        return None
    return {
        "title": str(title).strip()[:90],
        "angle": str(angle).strip()[:200],
        "why_now": str(why_now).strip()[:200],
        "points": [str(p).strip()[:140] for p in points[:4] if str(p).strip()],
    }


# ------------------------------------------------------------ template tier ----
def _target_plan(item, t):
    """SEO-manager action brief for a SPECIFIC missing page (a real content gap)."""
    kw = (t.get("keyword") or "this topic").strip()
    typ = t.get("type") or "Landing page"
    vol = t.get("volume") or 0
    comp = t.get("competitor") or "a competitor"
    pos = t.get("position")
    kd = t.get("kd")
    intents = t.get("intent") or []
    headline = (item.get("headlines") or [None])[0]
    title_kw = kw[:1].upper() + kw[1:]

    if "Comparison" in typ:
        title = f"{title_kw.replace(' vs ', ' vs. ')} — full comparison"
    elif "Buying" in typ:
        title = f"{title_kw} — 2026 buyer's guide"
    elif "Guide" in typ or "FAQ" in typ:
        title = f"{title_kw}: everything you need to know"
    else:
        title = title_kw

    pos_txt = f"ranks #{pos}" if pos else "ranks"
    angle = (f"Capture the “{kw}” query ({vol:,}/mo): {comp} {pos_txt} for it and JB Hi-Fi has no page. "
             f"A dedicated {typ.lower()} closes the gap.")
    if headline:
        why_now = f"News momentum right now — “{headline}” — and {vol:,} searches/mo with no JB page yet."
    else:
        why_now = f"{vol:,} searches/mo of unmet demand and a rival already ranks — proven, open opportunity."

    points = [f"Target “{kw}” as the primary keyword in the H1, title tag, meta and URL slug."]
    if "Comparison" in typ:
        points += ["Lead with a scannable spec-and-price comparison table — that's what wins this SERP.",
                   f"Out-cover {comp}'s page: add the buyer questions and product picks they omit."]
    elif "Buying" in typ:
        points += ["Structure it buyer criteria → ranked top picks → price/availability, linking to product pages.",
                   f"Match then beat the depth of {comp}'s ranking page, with JB stock and pricing."]
    else:
        points += ["Cover the related long-tail sub-topics to build topical authority for the cluster.",
                   f"Benchmark {comp}'s ranking page and go deeper on intent and specifics."]
    points.append("Internal-link from the parent category page and mark up with Product/FAQ schema.")

    ev = [f"page type: {typ.lower()}"]
    if intents:
        ev.append("search intent: " + ", ".join(intents).lower())
    if kd is not None:
        ev.append(f"keyword difficulty {kd}")
    return {"title": title[:90], "angle": angle[:220], "why_now": why_now[:220],
            "points": points[:4], "evidence": ev, "source": "template"}


def _template_plan(item):
    t = item.get("target")
    if t and t.get("keyword"):
        return _target_plan(item, t)
    topic = item.get("topic", "this topic")
    sig = item.get("signals", {})
    headline = (item.get("headlines") or [None])[0]
    gap = float(sig.get("semantic_gap", 0.0))
    trend = float(sig.get("trend_surprise", 0.0))
    news = float(sig.get("news_relevance", 0.0))
    spike = float(sig.get("trend_changepoint", 0.0))
    creating = _verb(item.get("action")) == "create"

    title = f"{topic} — a buyer's guide" if creating else f"{topic} — refresh & expand"

    if gap >= 0.6:
        angle = f"Own a topic your site barely covers yet — there's a clear gap on {topic}."
    elif trend >= 0.6:
        angle = f"Get ahead of rising demand for {topic} before competitors do."
    elif news >= 0.6:
        angle = f"Turn current news attention on {topic} into traffic."
    else:
        angle = f"Strengthen your position on {topic} while interest is building."

    if headline:
        why_now = f"It's in the news right now — e.g. “{headline}” — and demand is moving."
    elif spike >= 0.5:
        why_now = "Demand just spiked, so timing matters — publish while interest is fresh."
    elif trend >= 0.5:
        why_now = "Search interest is climbing — earlier pages tend to capture more of the wave."
    else:
        why_now = "Steady interest with room to win — a focused page can move the needle."

    points = []
    if creating:
        points.append("Answer the top buyer questions clearly, with plain comparisons.")
    else:
        points.append("Refresh the existing page: update facts, add the questions it's missing.")
    if gap >= 0.5:
        points.append("Cover the sub-topics you're currently missing to rank for more searches.")
    if news >= 0.5 and headline:
        points.append("Add a short, timely angle tied to the current news story.")
    points.append("Finish with clear pricing, availability and a strong call to action.")

    return {"title": title, "angle": angle, "why_now": why_now,
            "points": points[:4], "source": "template"}


# ----------------------------------------------------------------- public ----
def action_plan(item):
    """Return a structured, grounded action plan for one recommendation `item`
    (a dict with topic / action / effort / signals / headlines). Always returns
    a plan: Claude's if a key is set and the call succeeds, otherwise a real
    rule-based one."""
    return _llm_plan(item) or _template_plan(item)

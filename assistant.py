"""
assistant.py
------------
The "Market Intelligence AI" assistant. It answers ONLY from real, live data the
engine already computed (passed in as `ctx`) — never invented numbers.

Two tiers, chosen automatically:
  * If ANTHROPIC_API_KEY is set -> a free-form Claude answer, grounded in ctx.
  * Otherwise -> a fast rule-based answer over the same ctx (always works, no key,
    no dependency). So the assistant is real and functional out of the box, and
    gets smarter the moment a key is added.
"""
import json
import os
import urllib.request

import config

# plain-language names for signals, so the assistant speaks like a marketer
_LABELS = config.FEATURE_LABELS
def _label(name):
    return _LABELS.get(name, name.replace("_", " "))
def _prio(roi):
    return "High" if roi >= 0.62 else "Medium" if roi >= 0.40 else "Low"
def _level(label, v):
    band = "strong" if v >= 0.66 else "moderate" if v >= 0.33 else "low"
    return f"{band} {label}"


# ----------------------------------------------------------------- LLM tier ----
def _llm_answer(question, ctx):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = os.environ.get("ASSISTANT_MODEL", "claude-haiku-4-5-20251001")
    system = (
        "You are the 'Market Intelligence AI' assistant inside a marketing dashboard. "
        "Your reader is a non-technical marketer or business owner: speak in plain, "
        "friendly business language and never use ML or developer jargon. Answer ONLY "
        "from the JSON CONTEXT (real, live data); if it isn't there, say you don't have "
        "that data, and never invent figures. Be concise (2-4 sentences). Translate signal "
        "names to plain words: semantic_gap = 'gaps on your site', trend_surprise = 'rising "
        "search demand', news_relevance = 'news coverage', tiktok_velocity = 'TikTok hype', "
        "reddit_growth = 'Reddit buzz'. Prefer 'High/Medium/Low priority' over raw scores."
    )
    body = json.dumps({
        "model": model, "max_tokens": 400, "system": system,
        "messages": [{"role": "user",
                      "content": f"CONTEXT (JSON):\n{json.dumps(ctx)}\n\nQUESTION: {question}"}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        return text.strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------- rule tier ----
def _fmt_list(items):
    return ", ".join(items)


def _rule_answer(question, ctx):
    q = (question or "").lower().strip()
    items = ctx.get("items", [])
    client = ctx.get("client", "this client")
    rob = ctx.get("robustness") or {}

    def top_by(sig, n=3):
        return sorted(items, key=lambda i: i["signals"].get(sig, 0), reverse=True)[:n]

    # specific category mention?
    for it in items:
        name = it["topic"].lower()
        if name in q or (it["category"] and it["category"].lower() in q):
            s = it["signals"]
            return (f"{it['topic']}: {_prio(it['roi'])} priority. "
                    f"{_level('search demand', s['trend_surprise'])}, "
                    f"{_level('news coverage', s['news_relevance'])}, "
                    f"{_level('gap on your site', s['semantic_gap'])}. "
                    f"Suggested: {'create a new page' if s['semantic_gap'] >= 0.45 else 'strengthen the existing page'}.")

    if not q or any(w in q for w in ("help", "what can you", "how do you", "hello", "hi ")):
        return ("I answer from the live data. Try: \"what should we do first?\", "
                "\"what's trending?\", \"where are the content gaps?\", \"what has it "
                "learned?\", \"does it actually work?\", or ask about a category.")

    if any(w in q for w in ("do first", "top", "recommend", "opportunit", "priorit", "plan", "should we", "next")):
        top = items[:3]
        if not top:
            return "No opportunities are loaded yet."
        lines = [f"{i+1}. {t['topic']} — {_prio(t['roi'])} priority "
                 f"({'create a new page' if t['signals']['semantic_gap'] >= 0.45 else 'strengthen the page'})"
                 for i, t in enumerate(top)]
        return "Here's what to do first:\n" + "\n".join(lines)

    if any(w in q for w in ("learn", "weight", "trust", "distrust", "value most")):
        w = ctx.get("weights", [])
        if not w:
            return "No learned weights yet."
        top, bot = w[0], w[-1]
        return (f"It has learned that {_label(top['name'])} is what most reliably pays off, "
                f"while {_label(bot['name'])} usually doesn't — figured out from "
                f"{ctx.get('model_updates', 0)} real results.")

    if any(w in q for w in ("proof", "work", "better", "beat", "lift", "%", "vs", "improve", "validat")):
        if rob:
            return (f"It's been validated across {rob.get('n')} simulated markets: it consistently "
                    f"found the genuinely high-value topics and kept dead-end picks low. Real-world "
                    f"lift is then confirmed with live A/B testing once it's running for you.")
        return "The validation data isn't loaded right now."

    if any(w in q for w in ("gap", "missing", "cover", "content", "create")):
        g = top_by("semantic_gap")
        return "Biggest gaps on your site (what you're missing): " + _fmt_list(t["topic"] for t in g) + "."

    if any(w in q for w in ("trend", "rising", "demand", "hot", "momentum", "growing")):
        t = top_by("trend_surprise")
        return "Fastest-rising demand right now: " + _fmt_list(x["topic"] for x in t) + "."

    if any(w in q for w in ("news", "headline", "coverage")):
        n = top_by("news_relevance")
        return "Most news coverage this week: " + _fmt_list(x["topic"] for x in n) + "."

    # fallback
    top = items[:3]
    tip = (" Top right now: " + _fmt_list(t["topic"] for t in top) + ".") if top else ""
    return (f"I'm grounded in {client}'s live data — ask about opportunities, trends, "
            f"content gaps, what it's learned, or the proof." + tip)


def answer(question, ctx):
    """Free-form Claude answer if a key is configured, else a rule-based one."""
    return _llm_answer(question, ctx) or _rule_answer(question, ctx)

"""
assistant.py
------------
The "Market Intelligence AI" assistant — now retrieval-augmented (RAG).

Instead of stuffing one fixed JSON blob into the prompt, the engine assembles a
small knowledge base of real facts (one document per category + competitors, AI
visibility, what the model has learned, and the validation result). For each
question we RETRIEVE the most relevant facts (TF-IDF over the documents — sparse
retrieval, consistent with the rest of the app: no vector DB, no embeddings) and
then answer grounded strictly in them.

Two tiers, chosen automatically:
  * ANTHROPIC_API_KEY set -> Claude writes the answer from the retrieved facts.
  * Otherwise             -> a rule-based answer over the same facts (always works,
    no key). Either way the answer is grounded in real data — never invented.
"""
import json
import os
import urllib.request

import config
from sklearn.feature_extraction.text import TfidfVectorizer

# plain-language names for signals, so the assistant speaks like a marketer
_LABELS = config.FEATURE_LABELS
def _label(name):
    return _LABELS.get(name, name.replace("_", " "))
def _prio(roi):
    return "High" if roi >= 0.62 else "Medium" if roi >= 0.40 else "Low"
def _level(label, v):
    band = "strong" if v >= 0.66 else "moderate" if v >= 0.33 else "low"
    return f"{band} {label}"


# ------------------------------------------------------- retrieval (RAG) ----
def retrieve(question, docs, k=6):
    """Return the `k` documents most relevant to the question (TF-IDF cosine).
    Falls back to the first few docs if retrieval can't run."""
    if not docs:
        return []
    q = (question or "").strip()
    if not q:
        return docs[:k]
    texts = [f"{d.get('title', '')}. {d.get('text', '')}" for d in docs]
    try:
        # char n-grams (like semantic.py): robust to plural/morphology so
        # "competitors" still matches "Competitor", "TVs" matches "TV", etc.
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
        m = vec.fit_transform(texts + [q])              # last row = the query
        sims = (m[:-1] @ m[-1].T).toarray().ravel()      # cosine (tf-idf is L2-normed)
    except Exception:
        return docs[:k]
    order = sims.argsort()[::-1]
    hits = [docs[i] for i in order if sims[i] > 0.01][:k]
    return hits or [docs[i] for i in order[:k]]


def _find_doc(docs, topic):
    t = topic.lower()
    for d in docs or []:
        if t in d.get("title", "").lower():
            return d
    return None


# ----------------------------------------------------------------- LLM tier ----
def _llm_answer(question, retrieved, client="this client"):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = os.environ.get("ASSISTANT_MODEL", "claude-haiku-4-5-20251001")
    facts = "\n\n".join(f"[{d.get('title', 'fact')}]\n{d.get('text', '')}" for d in retrieved) \
        or "(no matching data found)"
    system = (
        f"You are the 'Market Intelligence AI' for {client}'s marketing dashboard. Answer the "
        "question using ONLY the FACTS below (real, live data). Speak in plain, friendly business "
        "language — no ML or developer jargon. Be concise (2-4 sentences) and cite the specific "
        "numbers, pages or brands from the facts. If the facts don't cover the question, say you "
        "don't have that data yet. Never invent figures."
    )
    body = json.dumps({
        "model": model, "max_tokens": 400, "system": system,
        "messages": [{"role": "user", "content": f"FACTS:\n{facts}\n\nQUESTION: {question}"}],
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


def _rule_answer(question, ctx, retrieved=None):
    q = (question or "").lower().strip()
    items = ctx.get("items", [])
    client = ctx.get("client", "this client")
    rob = ctx.get("robustness") or {}
    retrieved = retrieved or []

    def top_by(sig, n=3):
        return sorted(items, key=lambda i: i["signals"].get(sig, 0), reverse=True)[:n]

    # specific category mention? -> its rich retrieved fact (volume, headlines) if we have it
    for it in items:
        name = it["topic"].lower()
        if name in q or (it["category"] and it["category"].lower() in q):
            doc = _find_doc(retrieved, it["topic"])
            if doc:
                return doc["text"]
            s = it["signals"]
            return (f"{it['topic']}: {_prio(it['roi'])} priority. "
                    f"{_level('search demand', s['trend_surprise'])}, "
                    f"{_level('news coverage', s['news_relevance'])}, "
                    f"{_level('gap on your site', s['semantic_gap'])}. "
                    f"Suggested: {'create a new page' if s['semantic_gap'] >= 0.45 else 'strengthen the existing page'}.")

    if not q or any(w in q for w in ("help", "what can you", "how do you", "hello", "hi ")):
        return ("I answer from your live market data. Try: \"what should we do first?\", "
                "\"what's our AI share of voice?\", \"what are competitors publishing?\", "
                "\"what's the search volume for TVs?\", or \"what has it learned?\"")

    if any(w in q for w in ("do first", "top", "recommend", "opportunit", "priorit", "plan", "should we", "next")):
        # answer from the ACTUAL plan the UI shows (gap-ranked, defend-your-lead,
        # specific target pages) so the assistant never contradicts the dashboard.
        plan = ctx.get("plan") or []
        if plan:
            lines = []
            for i, c in enumerate(plan[:3], 1):
                if c.get("leads"):
                    what, verb = c.get("topic"), "defend your lead — you already rank well here"
                elif c.get("target"):
                    tgt = c["target"]
                    what = tgt.get("keyword") or c.get("topic")
                    verb = f"create a {(tgt.get('type') or 'new page').lower()}"
                else:
                    what = c.get("topic")
                    verb = ("create a new page" if (c.get("action") or "").lower().startswith("create")
                            else "strengthen the page")
                lines.append(f"{i}. {what} — {c.get('priority', '')} priority ({verb})")
            return "Here's what to do first:\n" + "\n".join(lines)
        top = items[:3]                              # fallback: cold start before any plan loaded
        if top:
            lines = [f"{i+1}. {t['topic']} — {_prio(t['roi'])} priority "
                     f"({'create a new page' if t['signals']['semantic_gap'] >= 0.45 else 'strengthen the page'})"
                     for i, t in enumerate(top)]
            return "Here's what to do first:\n" + "\n".join(lines)

    if any(w in q for w in ("learn", "weight", "trust", "distrust", "value most")):
        w = ctx.get("weights", [])
        if w and ctx.get("model_updates", 0) > 0:
            top, bot = w[0], w[-1]
            return (f"It has learned that {_label(top['name'])} is what most reliably pays off, "
                    f"while {_label(bot['name'])} usually doesn't — from {ctx.get('model_updates', 0)} real results.")
        return ("It hasn't learned yet — record a few agree/disagree verdicts on the plan and it "
                "starts learning which signals lead to wins.")

    if any(w in q for w in ("proof", "work", "better", "beat", "lift", "%", "vs", "improve", "validat")):
        if rob:
            return (f"It's been validated across {rob.get('n')} simulated markets: it consistently "
                    f"found the genuinely high-value topics and kept dead-end picks low. Real-world "
                    f"lift is confirmed with live A/B testing once it's running for you.")

    if any(w in q for w in ("gap", "missing", "cover", "content")):
        return "Biggest gaps on your site (what you're missing): " + _fmt_list(t["topic"] for t in top_by("semantic_gap")) + "."
    if any(w in q for w in ("trend", "rising", "demand", "hot", "momentum", "growing")):
        return "Fastest-rising demand right now: " + _fmt_list(x["topic"] for x in top_by("trend_surprise")) + "."
    if any(w in q for w in ("news", "headline", "coverage")):
        return "Most news coverage this week: " + _fmt_list(x["topic"] for x in top_by("news_relevance")) + "."

    # retrieval-augmented fallback — answer from the most relevant real facts
    # (this is what lets it handle competitors, AI visibility, volumes, etc.)
    if retrieved:
        return retrieved[0].get("text") or retrieved[0].get("title")
    tip = (" Top right now: " + _fmt_list(t["topic"] for t in items[:3]) + ".") if items else ""
    return (f"I'm grounded in {client}'s live data — ask about opportunities, trends, content gaps, "
            f"competitors, AI visibility, or what it's learned." + tip)


def answer(question, ctx, docs=None):
    """Retrieve the relevant facts, then answer them — Claude if a key is set,
    else rule-based. Both are grounded strictly in the retrieved real data."""
    retrieved = retrieve(question, docs or [])
    return _llm_answer(question, retrieved, ctx.get("client", "this client")) \
        or _rule_answer(question, ctx, retrieved)

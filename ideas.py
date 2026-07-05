"""
ideas.py — the marketing-idea engine (Nitin v2, phase 2).

Realises the core of the brief: THINK IN TOPICS, GENERATE MANY IDEAS PER TOPIC,
THEN RANK.

  1. Topics are discovered from the content-gap data itself (the salient shared
     term inside each category) — not a fixed keyword list.
  2. For each topic we generate many marketing ideas across five lanes
     (SEO / Content / Social / Commercial / AI Visibility), each grounded in real
     evidence (search volume, buyer intent, which competitor already ranks).
  3. Every idea is scored (demand x intent x competitive pressure x lane value)
     and ranked; topics are ranked by total unmet demand.

Rule-based and dependency-free, so it works with no LLM key. The AI Strategist can
still enrich an individual idea when ANTHROPIC_API_KEY is set, but the ideas — and
their reasoning — exist without it.
"""
import re
from collections import Counter, defaultdict

import content_gap

STOP = set((
    "best top the a an for and or vs versus to in of with near me australia au aus "
    "cheap buy sale review reviews how what why is are was under over price prices deals "
    "on off new used my your setup set up between difference compare comparison good "
    "which where when does do can size inch inches").split())

LANE_VALUE = {"SEO": 1.0, "Commercial": 0.95, "Content": 0.85, "AI Visibility": 0.8, "Social": 0.72}
INTENT_WEIGHT = {"Transactional": 1.0, "Commercial": 0.9, "Informational": 0.65, "Local": 0.5}

ACRONYMS = {"oled": "OLED", "qled": "QLED", "uhd": "UHD", "ssd": "SSD", "gpu": "GPU",
            "hdmi": "HDMI", "tv": "TV", "pc": "PC", "usb": "USB", "vr": "VR", "anc": "ANC",
            "dslr": "DSLR", "led": "LED", "4k": "4K", "8k": "8K", "cpu": "CPU", "ram": "RAM"}


def _label(key, cat):
    return cat if key == cat else ACRONYMS.get(key.lower(), key.title())


def _tokens(keyword, category):
    kw = re.sub(r"[^a-z0-9 ]", " ", keyword.lower())
    cat = category.lower().rstrip("s")
    out = []
    for w in kw.split():
        if len(w) <= 2 or w.isdigit() or w in STOP or cat in w:
            continue
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]                      # light plural stem: "monitors" == "monitor"
        out.append(w)
    return out


def _intent_weight(opps):
    best = 0.0
    for o in opps:
        for i in o.get("intent", []):
            best = max(best, INTENT_WEIGHT.get(i, 0.4))
    return best or 0.5


def _confidence(opps, best_comp):
    if len(opps) >= 3 and best_comp <= 10:
        return "High"
    if len(opps) >= 2 or best_comp <= 15:
        return "Medium"
    return "Emerging"


def _impact(volume, iw):
    if volume >= 5000 and iw >= 0.9:
        return "High"
    if volume >= 1500:
        return "Medium"
    return "Niche"


def _idea(lane, kind, what, why, why_now, evidence, effort, volume, iw, ncomp, type_mult=1.0):
    demand = min(volume / 8000.0, 1.6)
    pressure = 1.0 + 0.12 * ncomp
    score = round(demand * iw * LANE_VALUE[lane] * pressure * type_mult * 100)
    return {"lane": lane, "type": kind, "what": what, "why": why, "why_now": why_now,
            "evidence": evidence, "effort": effort, "score": score}


def _ideas_for_topic(cat, label, opps, volume, comps):
    kws = sorted(opps, key=lambda o: -o["volume"])
    top = kws[0]
    best_comp_name, best_comp_pos = (comps[0]["name"], comps[0]["position"]) if comps else ("a competitor", 99)
    iw = _intent_weight(opps)
    ncomp = len(comps)
    conf = _confidence(opps, best_comp_pos)
    impact = _impact(volume, iw)

    ev_demand = f"{volume:,}/mo of unmet demand across {len(opps)} '{label}' quer{'y' if len(opps)==1 else 'ies'} where you don't rank"
    ev_comp = f"{best_comp_name} ranks #{best_comp_pos} for “{top['keyword']}” — you're absent"

    def cmp_kw():
        for o in kws:
            if "Comparison" in o["type"] or " vs " in o["keyword"] or "difference between" in o["keyword"]:
                return o["keyword"]
        return None

    def guide_kw():
        for o in kws:
            if "Buying" in o["type"] or re.search(r"\bbest\b", o["keyword"]):
                return o["keyword"]
        return None

    def q_kw():
        for o in kws:
            if o["type"].startswith("Guide") or o["keyword"].split()[0] in ("how", "what", "why", "is", "are"):
                return o["keyword"]
        return None

    out = []
    ck, gk, qk = cmp_kw(), guide_kw(), q_kw()

    if ck:
        out.append(_idea("SEO", "Comparison page",
            f"Publish a comparison page for {label} (target “{ck}”)",
            "Shoppers are actively comparing options and a rival already owns this high-intent query; a dedicated side-by-side page turns researchers into buyers.",
            "The comparison demand is live now and unclaimed by you.",
            [f"“{ck}” is a commercial comparison query", ev_comp, ev_demand],
            "Medium", volume, iw, ncomp, type_mult=1.15))
        out.append(_idea("Social", "Short-form video",
            f"Film a 30-second {label} side-by-side for TikTok / Reels",
            "The same comparison interest drives huge short-form watch time; video seeds demand that later converts on the page.",
            "Ride the comparison interest while it's peaking.",
            [f"comparison interest: “{ck}”", ev_demand], "Low", volume, iw, ncomp, type_mult=0.9))

    if gk:
        out.append(_idea("Content", "Buying guide",
            f"Write a buying guide — “Best {label}”",
            "“Best…” queries catch buyers at the decision point; a guide ranks, earns trust, and links straight to your product pages.",
            "Buyers are searching for a shortlist you can own.",
            [f"buying-intent query: “{gk}”", ev_comp, ev_demand], "Medium", volume, iw, ncomp, type_mult=1.1))

    if qk:
        out.append(_idea("AI Visibility", "Answer content",
            f"Publish an answer-first explainer for “{qk}”",
            "Clear, structured answers are what AI assistants cite — this is how you show up when shoppers ask ChatGPT, not just Google.",
            "AI answers are becoming the new shelf; early answer content compounds.",
            [f"question query: “{qk}”", "answer content is favoured by AI Overviews"], "Medium", volume, iw, ncomp, type_mult=1.0))

    out.append(_idea("SEO", "Category optimisation",
        f"Optimise the {cat} category page for “{top['keyword']}”",
        "You already have category authority; targeting these terms on an existing page is the fastest, lowest-risk way to close the gap.",
        "Low effort, and the demand is already proven.",
        [f"top gap: “{top['keyword']}” ({top['volume']:,}/mo)", ev_comp], "Low", volume, iw, ncomp, type_mult=1.05))

    out.append(_idea("Commercial", "Bundle / merchandising",
        f"Bundle {label} products and feature them on the {cat} landing page",
        "Turn the interest into basket size — bundling accessories lifts average order value on proven-demand topics.",
        "Demand exists now; capture it commercially, not just editorially.",
        [ev_demand, f"buyer intent present across {label} queries"], "Low", volume, iw, ncomp, type_mult=0.92))

    out.append(_idea("Content", "Blog / explainer",
        f"Blog post — “{label} explained” for {cat} shoppers",
        "Top-of-funnel content builds the topic's entity coverage and internal links, strengthening every product page beneath it.",
        "Compounds your authority in a category rivals are winning.",
        [ev_demand, "supports the whole topic cluster"], "Medium", volume, iw, ncomp, type_mult=0.78))

    if not ck:                                   # ensure every topic spans the Social lane
        out.append(_idea("Social", "Short-form video",
            f"Showcase the top {label} picks in a TikTok / Reel",
            "Short-form video builds awareness on the topic and feeds shoppers into your product and guide pages.",
            "Cheap to produce, and it seeds demand rivals are already capturing.",
            [ev_demand], "Low", volume, iw, ncomp, type_mult=0.85))
    if not qk:                                   # ...and the AI Visibility lane
        out.append(_idea("AI Visibility", "Answer content",
            f"Add FAQ / structured answers for {label} so AI assistants cite JB",
            "Structured, answer-first content is what AI Overviews and ChatGPT surface — the visibility that now sits above the classic blue links.",
            "AI search is where more of this demand is resolved every month.",
            [ev_demand, "structured answers are favoured by AI Overviews"], "Medium", volume, iw, ncomp, type_mult=0.95))

    out.sort(key=lambda i: -i["score"])
    for i in out:
        i["confidence"], i["impact"] = conf, impact
    return out


def _make_topic(cat, label, key, opps):
    volume = sum(o["volume"] for o in opps)
    comp = {}
    for o in opps:
        for c in o["competitors"]:
            comp[c["name"]] = min(comp.get(c["name"], 99), c["position"])
    comps = [{"name": n, "position": p} for n, p in sorted(comp.items(), key=lambda x: x[1])]
    ideas = _ideas_for_topic(cat, label, opps, volume, comps)
    kws = sorted(opps, key=lambda o: -o["volume"])
    return {
        "category": cat,
        "topic": label if label.lower() != cat.lower() else f"{cat} — general",
        "total_volume": volume,
        "gap_count": len(opps),
        "top_keyword": kws[0]["keyword"],
        "competitors": comps,
        "keywords": [{"keyword": o["keyword"], "volume": o["volume"], "type": o["type"]} for o in kws[:6]],
        "ideas": ideas,
        "idea_count": len(ideas),
        "score": round(volume * (1.0 + 0.08 * len(opps))),
    }


def discover_topics(opps):
    """Cluster opportunities into topics by the most salient shared term per category."""
    by_cat = defaultdict(list)
    for o in opps:
        by_cat[o["category"]].append(o)
    topics = []
    for cat, items in by_cat.items():
        freq = Counter()
        toks = {}
        for o in items:
            t = _tokens(o["keyword"], cat)
            toks[id(o)] = t
            freq.update(set(t))
        groups = defaultdict(list)
        for o in items:
            cand = [(freq[t], len(t), t) for t in toks[id(o)] if freq[t] >= 2]
            groups[max(cand)[2] if cand else cat].append(o)
        for key, gopps in groups.items():
            topics.append(_make_topic(cat, _label(key, cat), key, gopps))
    topics.sort(key=lambda t: -t["score"])
    return topics


def generate(limit_topics=12, mult=None):
    gaps = content_gap.content_gaps()
    opps = gaps.get("opportunities", [])
    if not opps:
        return {"available": False, "topics": [], "topic_count": 0, "idea_count": 0}
    topics = discover_topics(opps)
    if mult:                                     # re-weight by learned principle effectiveness
        for t in topics:
            for i in t["ideas"]:
                i["score"] = round(i["score"] * mult.get(i["type"], 1.0))
            t["ideas"].sort(key=lambda x: -x["score"])
    topics = topics[:limit_topics]
    lane_counter = Counter(i["lane"] for t in topics for i in t["ideas"])
    return {
        "available": True,
        "topic_count": len(topics),
        "idea_count": sum(t["idea_count"] for t in topics),
        "addressable_volume": sum(t["total_volume"] for t in topics),
        "top_lane": lane_counter.most_common(1)[0][0] if lane_counter else None,
        "topics": topics,
    }

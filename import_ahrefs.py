"""
import_ahrefs.py — turn Ahrefs exports into the app's compact market-intel data.

Nitin's brief provides two exports (dropped in weekly):
  * Content Gap (JB vs Harvey Norman / The Good Guys / Officeworks)
  * Top Pages  (one per site)

This script reads the raw UTF-16 / tab-delimited exports from a folder and writes
two small, committed JSON files the running app reads:
  * data/ahrefs/content_gaps.json  — ranked *relevant* missing-content opportunities
  * data/ahrefs/top_pages.json     — each site's strongest pages + JB category strengths

Run weekly when new exports arrive:
    python import_ahrefs.py [RAW_DIR]        (RAW_DIR default: $AHREFS_RAW_DIR or ~/Downloads)

The intelligence is in the FILTER: the raw "gap by volume" is dominated by competitor
brand terms and off-topic queries. We keep only gaps that (a) JB does not rank for,
(b) a competitor does, (c) carry commercial/informational (not branded/navigational)
intent, and (d) map to one of JB's actual product categories.
"""
import csv, glob, json, os, re, sys, time

# ---- JB Hi-Fi categories + the terms that map a keyword to each ------------
# Order = priority (first match wins), so specific beats generic (Computers last).
# Ambiguous bare words are avoided; single-word terms match on word boundaries.
CATEGORY_TERMS = [
    ("Gaming",       ["playstation", "ps5", "ps4", "xbox", "nintendo switch", "nintendo",
                      "gaming console", "gaming monitor", "gaming laptop", "gaming pc",
                      "gaming chair", "gaming headset", "gaming mouse", "gaming keyboard",
                      "gaming desk", "dualsense", "steam deck", "meta quest", "vr headset",
                      "game controller", "ps5 controller", "xbox controller", "esports"]),
    ("Headphones",   ["headphones", "headphone", "earbuds", "earbud", "earphones",
                      "airpods", "noise cancelling headphones", "wireless earbuds",
                      "anc headphones", "over-ear headphones"]),
    ("Soundbars",    ["soundbar", "sound bar"]),
    ("Speakers",     ["bluetooth speaker", "wireless speaker", "portable speaker",
                      "party speaker", "smart speaker", "sonos", "subwoofer", "speaker"]),
    ("Smartwatches", ["smartwatch", "smart watch", "apple watch", "galaxy watch",
                      "garmin", "fitbit", "fitness tracker", "fitness watch"]),
    ("Tablets",      ["ipad", "android tablet", "samsung tablet", "kids tablet",
                      "drawing tablet", "graphics tablet", "galaxy tab", "surface pro", "tablet"]),
    ("Cameras",      ["digital camera", "dslr", "mirrorless", "action camera",
                      "security camera", "instant camera", "camera lens", "camera tripod",
                      "gopro", "polaroid", "camcorder", "drone", "dash cam", "camera"]),
    ("Laptops",      ["laptop", "macbook", "chromebook", "ultrabook"]),
    ("Phones",       ["iphone", "smartphone", "mobile phone", "android phone", "phone case",
                      "phone charger", "phone holder", "phone cover", "phone mount",
                      "screen protector", "foldable phone", "galaxy s", "google pixel"]),
    ("TVs",          ["television", "smart tv", "oled tv", "qled tv", "4k tv", "led tv",
                      "8k tv", "tv antenna", "tv wall mount", "tv mount", "oled", "qled"]),
    ("Computers",    ["desktop computer", "computer monitor", "uhd monitor", "4k monitor",
                      "curved monitor", "mechanical keyboard", "wireless mouse",
                      "wireless keyboard", "printer", "ink cartridge", "hard drive", "ssd",
                      "usb-c", "usb hub", "wifi router", "router", "modem", "webcam",
                      "graphics card", "docking station", "monitor arm", "monitor", "keyboard"]),
]

# Non-electronics / non-content queries: if a keyword contains any of these, drop it
# entirely (furniture, cleaning, stationery, services, health, etc.).
BLOCK = [
    "near me", "repair", "warranty", "gift card", "catalogue", "opening hour",
    "store locator", "trade in", "trade-in", "dishwasher", "dishwashing", "dish washing",
    "washing machine", "detergent", "cleaner", "vacuum", "vitamin", "supplement",
    "fish oil", "protein", " a4", " a5", "paper", "notebook", "calculator", "stapler",
    "envelope", "diary", "planner", "cabinet", "cupboard", "wardrobe", "bean bag", "sofa",
    "mattress", "dining", "bookshelf", "entertainment unit", "tv unit", "tv console",
    "furniture", "ear plug", "ear wax", "ear camera", "ear cleaner", "reverse camera",
    "rear camera", "backup camera", "megaphone", "baby monitor", "blood pressure",
    "heart rate monitor", "piano",
]


def _mk(terms):
    pats = []
    for t in terms:
        pats.append(re.escape(t) if (" " in t or "-" in t) else r"\b" + re.escape(t) + r"s?\b")
    return re.compile("|".join(pats))


_CATEGORY_RE = [(cat, _mk(terms)) for cat, terms in CATEGORY_TERMS]

DROP_INTENTS = {"Branded", "Navigational"}
INTENT_WEIGHT = {"Transactional": 1.0, "Commercial": 0.9, "Informational": 0.65, "Local": 0.5}
MIN_VOLUME = 200
MAX_COMP_POSITION = 30       # a competitor must rank at least this well
TOP_N = 300                  # opportunities kept overall
PER_CATEGORY_CAP = 45

COMPETITORS = [("Harvey Norman", 17), ("The Good Guys", 26), ("Officeworks", 35)]
JB_POS = 8


def _num(x):
    x = (x or "").strip()
    try:
        return int(float(x))
    except ValueError:
        return None


def categorise(keyword):
    k = keyword.lower()
    if any(b in k for b in BLOCK):
        return None
    for cat, rx in _CATEGORY_RE:
        if rx.search(k):
            return cat
    return None


def content_type(keyword):
    k = keyword.lower()
    if " vs " in k or " versus " in k or k.endswith(" vs"):
        return "Comparison page"
    if re.search(r"\bbest\b|top \d", k):
        return "Buying guide"
    if k.startswith(("how ", "what ", "why ", "can ", "do ", "is ")) or "how to" in k or " guide" in k:
        return "Guide / FAQ"
    if "review" in k:
        return "Review roundup"
    if any(w in k for w in ("deal", "sale", "cheap", "price", "discount", "buy ", "for sale")):
        return "Category / deals page"
    return "Landing page"


def _rows(path):
    with open(path, encoding="utf-16") as f:
        r = csv.reader(f, delimiter="\t")
        next(r, None)                      # header
        for row in r:
            yield row


def build_content_gaps(gap_csv):
    opps = []
    demand, seen = {}, set()                          # TRUE per-category demand: every keyword
    for row in _rows(gap_csv):
        if len(row) <= 35:
            continue
        vol = _num(row[4]) or 0
        cat = categorise(row[0])
        if cat and vol > 0:                            # aggregate demand across ALL keywords
            kw = row[0].strip().lower()               # (phone + mobile + smartphone all count)
            if kw not in seen:
                seen.add(kw)
                demand[cat] = demand.get(cat, 0) + vol
        if _num(row[JB_POS]) is not None:          # JB already ranks -> not a gap
            continue
        if vol < MIN_VOLUME or not cat:              # a gap needs volume + a mapped category
            continue
        intents = [i.strip() for i in (row[2] or "").split(",") if i.strip()]
        if not intents or DROP_INTENTS & set(intents):   # brand / nav queries -> skip
            continue
        ranked = [(n, _num(row[i])) for n, i in COMPETITORS if _num(row[i]) is not None]
        ranked = [(n, p) for n, p in ranked if p <= MAX_COMP_POSITION]
        if not ranked:                               # no competitor ranks well -> skip
            continue
        best = min(p for _, p in ranked)
        iw = max((INTENT_WEIGHT.get(i, 0.4) for i in intents), default=0.4)
        cf = 1.0 if best <= 10 else 0.85 if best <= 20 else 0.7
        score = round(vol * iw * cf)
        opps.append({
            "keyword": row[0], "category": cat, "volume": vol,
            "intent": [i for i in intents if i not in DROP_INTENTS],
            "kd": _num(row[5]), "type": content_type(row[0]),
            "competitors": [{"name": n, "position": p} for n, p in sorted(ranked, key=lambda x: x[1])],
            "best_position": best, "score": score,
        })
    opps.sort(key=lambda o: -o["score"])
    # keep a spread: cap per category, then take the overall top N
    per_cat, kept = {}, []
    for o in opps:
        c = o["category"]
        if per_cat.get(c, 0) >= PER_CATEGORY_CAP:
            continue
        per_cat[c] = per_cat.get(c, 0) + 1
        kept.append(o)
        if len(kept) >= TOP_N:
            break
    by_cat = {}
    for o in kept:
        by_cat[o["category"]] = by_cat.get(o["category"], 0) + 1
    return {
        "generated": time.time(),
        "total_gaps_scanned": len(opps),
        "kept": len(kept),
        "by_category": dict(sorted(by_cat.items(), key=lambda x: -x[1])),
        "category_demand": dict(sorted(demand.items(), key=lambda x: -x[1])),
        "total_demand": sum(demand.values()),
        "opportunities": kept,
    }


def build_top_pages(files):
    sites, jb_strength = {}, {}
    for site, path, limit in files:
        pages = []
        for row in _rows(path):
            if len(row) < 10:
                continue
            traffic = _num(row[2]) or 0
            if traffic <= 0:
                continue
            pages.append({
                "url": row[0], "traffic": traffic,
                "keyword": row[6], "volume": _num(row[7]) or 0,
                "position": _num(row[8]), "page_type": row[9],
            })
        pages.sort(key=lambda p: -p["traffic"])
        pages = pages[:limit]
        sites[site] = {"total_traffic": sum(p["traffic"] for p in pages), "pages": pages}
        if site == "JB Hi-Fi":
            for p in pages:
                c = categorise(p["keyword"]) or categorise(p["url"])
                if c:
                    s = jb_strength.setdefault(c, {"traffic": 0, "pages": 0})
                    s["traffic"] += p["traffic"]
                    s["pages"] += 1
    return {"generated": time.time(), "sites": sites,
            "jb_strengths": dict(sorted(jb_strength.items(), key=lambda x: -x[1]["traffic"]))}


def _find(raw_dir, *patterns):
    for pat in patterns:
        hits = sorted(glob.glob(os.path.join(raw_dir, pat)))
        if hits:
            return hits[-1]          # most recent by name (timestamped)
    return None


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "AHREFS_RAW_DIR", os.path.expanduser("~/Downloads"))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ahrefs")
    os.makedirs(out, exist_ok=True)

    gap = _find(raw, "*content-gap*.csv")
    if gap:
        data = build_content_gaps(gap)
        with open(os.path.join(out, "content_gaps.json"), "w") as f:
            json.dump(data, f, indent=1)
        print(f"content_gaps.json: kept {data['kept']} of {data['total_gaps_scanned']} "
              f"relevant gaps -> {data['by_category']}")

    tp = [
        ("JB Hi-Fi",      _find(raw, "jbhifi*top-pages*.csv", "*jbhifi*top-pages*.csv"), 150),
        ("Harvey Norman", _find(raw, "harveynorman*top-pages*.csv"), 80),
        ("The Good Guys", _find(raw, "thegoodguys*top-pages*.csv"), 80),
        ("Officeworks",   _find(raw, "officeworks*top-pages*.csv"), 80),
    ]
    tp = [(n, p, l) for n, p, l in tp if p]
    if tp:
        data = build_top_pages(tp)
        with open(os.path.join(out, "top_pages.json"), "w") as f:
            json.dump(data, f, indent=1)
        print("top_pages.json:", {s: v["total_traffic"] for s, v in data["sites"].items()},
              "| JB strengths:", {c: v["traffic"] for c, v in data["jb_strengths"].items()})


if __name__ == "__main__":
    main()

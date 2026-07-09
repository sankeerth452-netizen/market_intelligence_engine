"""
content_gap.py — runtime access to the Ahrefs-derived market intelligence.

Reads the compact JSON produced by import_ahrefs.py (data/ahrefs/*.json):
  * content_gaps.json — ranked, category-tagged missing-content opportunities
  * top_pages.json    — each site's strongest pages + JB's category strengths

Two sources, in priority order:
  1. RUNTIME OVERRIDE — data uploaded in-app (the Data page) and restored from
     the DB on boot. Preferred, so a weekly upload takes effect live with no
     redeploy.
  2. COMMITTED FILE  — the snapshot shipped in the repo (data/ahrefs/*.json).

Fail-soft: if neither exists, everything returns empty and the feature simply
reports "not available" — nothing else breaks.
"""
import functools
import json
import os

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ahrefs")

# name -> dict, set at runtime from an in-app upload (see engine.apply_ahrefs).
# Preferred over the committed file so a fresh upload is live immediately.
_OVERRIDE = {}


@functools.lru_cache(maxsize=4)
def _load(name):
    try:
        with open(os.path.join(_DIR, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def set_override(name, data):
    """Install (or clear, if data is None) uploaded data for `name`, taking
    precedence over the committed file until the process restarts."""
    if data is None:
        _OVERRIDE.pop(name, None)
    else:
        _OVERRIDE[name] = data


def _get(name):
    if name in _OVERRIDE:
        return _OVERRIDE[name]
    return _load(name)


def source(name):
    """Where the data for `name` currently comes from: uploaded | committed | none."""
    if name in _OVERRIDE:
        return "uploaded"
    return "committed" if _load(name) is not None else "none"


def available() -> bool:
    return _get("content_gaps.json") is not None


def content_gaps() -> dict:
    return _get("content_gaps.json") or {
        "opportunities": [], "by_category": {}, "kept": 0, "total_gaps_scanned": 0}


def top_pages() -> dict:
    return _get("top_pages.json") or {"sites": {}, "jb_strengths": {}}

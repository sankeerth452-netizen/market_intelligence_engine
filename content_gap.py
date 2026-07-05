"""
content_gap.py — runtime access to the Ahrefs-derived market intelligence.

Reads the compact JSON produced by import_ahrefs.py (data/ahrefs/*.json):
  * content_gaps.json — ranked, category-tagged missing-content opportunities
  * top_pages.json    — each site's strongest pages + JB's category strengths

Fail-soft: if the files are absent (no exports imported yet), everything returns
empty and the feature simply reports "not available" — nothing else breaks.
"""
import functools
import json
import os

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ahrefs")


@functools.lru_cache(maxsize=4)
def _load(name):
    try:
        with open(os.path.join(_DIR, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def available() -> bool:
    return _load("content_gaps.json") is not None


def content_gaps() -> dict:
    return _load("content_gaps.json") or {
        "opportunities": [], "by_category": {}, "kept": 0, "total_gaps_scanned": 0}


def top_pages() -> dict:
    return _load("top_pages.json") or {"sites": {}, "jb_strengths": {}}

"""
demo_client.py
==============
DEMO DATA — NOT product logic.
================================
This file is the ONLY place the "Home Builder" example from the original
specification lives. It is used solely when no real client is configured (no
SITE_URL / CLIENT_CATEGORIES). The engine itself contains no business knowledge;
everything here is illustrative and swappable.

To onboard a real client, set SITE_URL + CLIENT_CATEGORIES (+ CLIENT_INDUSTRY) in
the environment — no code change, and nothing in this file is used.
"""
from client_config import ClientConfig

# The specification's example category framework (Home Builder). Kept in this
# exact order because the synthetic proof world labels its topics from it.
_HOME_BUILDER_CATEGORIES = [
    "Home Builder", "House and Land Packages", "Display Homes", "Knockdown Rebuild",
    "Townhouse Builder", "Home Designs", "Single Storey Homes", "Double Storey Homes",
    "Custom Homes", "First Home Buyers", "Building Costs", "Sustainable Homes",
]

# A stand-in for the client's existing website, used for content-gap analysis when
# SITE_URL is unset. It deliberately COVERS some categories (display homes, single/
# double storey, house & land, first home buyers, custom homes) and NOT others
# (knockdown rebuild, sloping/split-level blocks, building costs, sustainability),
# so the gap signal has something meaningful to find. Real clients supply SITE_URL
# and this is never touched.
DEMO_SITE_PAGES = [
    "Display homes locations opening hours book an appointment visit our estates near you",
    "Single storey home designs four bedroom family floor plans modern facade fixed price",
    "Double storey home designs upstairs living master retreat facade options price guide",
    "House and land packages turnkey move in ready estates titled land inclusions",
    "First home buyers guide deposit grants getting started loan pre approval steps",
    "Custom home builder fixed price contract building stages design consultation",
    "Home designs gallery browse floor plans bedrooms bathrooms living areas garage",
]

DEMO_CLIENT = ClientConfig(
    name="Demo — Home Builder (specification example)",
    industry="home_builder",
    categories=_HOME_BUILDER_CATEGORIES,
    site_url=None,                  # demo uses DEMO_SITE_PAGES instead of a live crawl
    business_priority_weights={},   # reserved for the spec's "Business Priority"
    is_demo=True,
)

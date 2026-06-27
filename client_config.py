"""
client_config.py
----------------
The platform is client-agnostic: it serves one CLIENT at a time, and a client is
described entirely by a ClientConfig. The engine never hardcodes a business — it
reads this config. Onboarding a new client is configuration, not code.

A client is resolved from environment variables, which override the built-in demo
client (see demo_client.py). Switching clients requires NO code changes:

  SITE_URL                 the client's website, crawled for content-gap analysis
  CLIENT_NAME              display name
  CLIENT_INDUSTRY          e.g. "home_builder", "saas", "automotive"
  CLIENT_CATEGORIES        comma-separated category framework
  CLIENT_PRIORITY_WEIGHTS  optional JSON {category: weight} (the spec's
                           "Business Priority"; reserved for future scoring)

If none of these are set, the demo client is used so the whole engine runs out of
the box for development and the public demo.
"""
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class ClientConfig:
    name: str
    industry: str
    categories: List[str]
    site_url: Optional[str] = None
    business_priority_weights: dict = field(default_factory=dict)
    is_demo: bool = False

    @property
    def site_source(self) -> str:
        """Human-readable description of where content-gap analysis is looking."""
        if self.site_url:
            return self.site_url
        return "demo site (no SITE_URL configured)"


def load_client_config() -> "ClientConfig":
    """Build the active client from env vars, falling back to the demo client."""
    from demo_client import DEMO_CLIENT  # lazy import avoids a circular dependency

    site_url = (os.environ.get("SITE_URL") or "").strip() or None
    cats_env = (os.environ.get("CLIENT_CATEGORIES") or "").strip()
    name_env = (os.environ.get("CLIENT_NAME") or "").strip()
    industry_env = (os.environ.get("CLIENT_INDUSTRY") or "").strip()
    weights_env = (os.environ.get("CLIENT_PRIORITY_WEIGHTS") or "").strip()

    # No client-specific configuration at all -> run the built-in demo client.
    if not any([site_url, cats_env, name_env, industry_env]):
        return DEMO_CLIENT

    categories = [c.strip() for c in cats_env.split(",") if c.strip()] or list(DEMO_CLIENT.categories)
    weights = {}
    if weights_env:
        try:
            weights = json.loads(weights_env)
        except ValueError:
            weights = {}
    return ClientConfig(
        name=name_env or "Configured client",
        industry=industry_env or DEMO_CLIENT.industry,
        categories=categories,
        site_url=site_url,
        business_priority_weights=weights,
        is_demo=False,
    )


_active: Optional[ClientConfig] = None


def active_client() -> ClientConfig:
    """The current client (cached). Resolved once from the environment."""
    global _active
    if _active is None:
        _active = load_client_config()
    return _active


def set_active_client(cfg: Optional[ClientConfig]) -> None:
    """Override (or reset with None) the active client — for tests and for
    programmatic onboarding of additional clients."""
    global _active
    _active = cfg

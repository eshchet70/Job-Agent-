"""
Portal registry — single access point for all configured job portal adapters.
"""
from __future__ import annotations

from app.integrations.portal_base import JobPortalAdapter
from app.integrations.indeed_adapter import IndeedAdapter
from app.integrations.linkedin_adapter import LinkedInAdapter
from app.integrations.mygreenhouse_adapter import MyGreenhouseAdapter
from app.integrations.glassdoor_adapter import GlassdoorAdapter

# Registry of all adapters — extend this list to add new portals
_ADAPTERS: dict[str, JobPortalAdapter] = {
    "indeed":       IndeedAdapter(),
    "linkedin":     LinkedInAdapter(),
    "mygreenhouse": MyGreenhouseAdapter(),
    "glassdoor":    GlassdoorAdapter(),
}


def get_adapter(name: str) -> JobPortalAdapter:
    """Return the adapter for a given portal name (case-insensitive)."""
    adapter = _ADAPTERS.get(name.lower())
    if not adapter:
        raise KeyError(f"Unknown portal: '{name}'. Available: {list(_ADAPTERS.keys())}")
    return adapter


def all_adapters() -> dict[str, JobPortalAdapter]:
    """Return all registered portal adapters."""
    return dict(_ADAPTERS)


def all_statuses() -> list[dict]:
    """Return status info for every configured portal."""
    statuses = []
    for name, adapter in _ADAPTERS.items():
        try:
            s = adapter.status()
            statuses.append({
                "portal": adapter.portal_name,
                "key": name,
                "authenticated": s.authenticated,
                "public_mode": s.public_mode,
                "message": s.message,
                "capabilities": s.capabilities,
            })
        except Exception as exc:
            statuses.append({
                "portal": name, "key": name,
                "authenticated": False, "public_mode": False,
                "message": f"Error: {exc}", "capabilities": [],
            })
    return statuses

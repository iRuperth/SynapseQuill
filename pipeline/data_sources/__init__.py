"""
data_sources — switchable football data providers.

All providers return the same `Match`/`Goal` dataclasses (from match_monitor),
so the rest of the pipeline never depends on which API is configured.

DATA_PROVIDER (env / profile):
    espn          ESPN public API — CURRENT-season La Liga 2025/26 and World Cup
                  2026 with final scores AND scorers+minutes, free, no key.
                  This is the default so content is always recent.
    apifootball   API-Football — full scorers, but the free plan only covers
                  seasons 2021-2024 (no current season).
    thesportsdb   TheSportsDB — current scores (free key 123) but no scorers.
    fcf           Federació Catalana de Futbol — Catalan amateur leagues
                  (Tercera Catalana), the only public source for a club ESPN
                  does not cover. Final scores only, no scorers.
    multi         SEVERAL of the above merged into one feed, each leg optionally
                  narrowed to one club. This is what lets a channel cover all of
                  LaLiga AND one amateur club, from two unrelated providers.

`get_data_source(cfg)` returns the provider selected for a profile.
"""

import os

from .apifootball import ApiFootballSource
from .espn import EspnSource
from .thesportsdb import TheSportsDbSource

_SOURCES = {
    "espn": EspnSource,
    "apifootball": ApiFootballSource,
    "thesportsdb": TheSportsDbSource,
}


def _source_class(name: str):
    """Resolve a provider name to its class, importing the optional ones lazily
    so a missing dependency in a rarely-used source can't break the common path."""
    if name == "fcf":
        from .fcf import FcfSource
        return FcfSource
    return _SOURCES.get(name)


class _LegConfig:
    """A per-leg view of the profile.

    Each leg of a merged feed needs its OWN competition ids (one is ESPN's
    esp.1, another is an FCF group) while still sharing the profile's secrets,
    language and output dirs. This wraps the real BrandProfile and shadows only
    the id fields the leg overrides; everything else falls through untouched.
    """

    def __init__(self, cfg, spec: dict):
        self._cfg = cfg
        self.ESPN_SLUG = spec.get("espn_slug") or getattr(cfg, "ESPN_SLUG", "esp.1")
        self.FCF_COMPETITION = spec.get("fcf_competition") or ""
        self.FCF_GROUP = spec.get("fcf_group") or ""
        self.FCF_SEASON = spec.get("fcf_season") or ""
        self.FCF_TEAM = spec.get("team") or ""

    def __getattr__(self, key):
        # Only reached for attributes NOT set above — delegate to the profile.
        return getattr(self._cfg, key)

    def get_secret(self, key, default=None):
        return self._cfg.get_secret(key, default)


def get_data_source(cfg):
    """Return the configured data source for a BrandProfile."""
    name = (getattr(cfg, "DATA_PROVIDER", None)
            or os.getenv("DATA_PROVIDER", "espn")).lower()

    if name == "multi":
        from .multi import Leg, MultiSource
        specs = getattr(cfg, "COMPETITION_LEGS", None) or []
        if not specs:
            raise ValueError("DATA_PROVIDER 'multi' needs a 'legs' list in the "
                             "competition preset (core/competitions.py).")
        legs = []
        for spec in specs:
            sub = (spec.get("provider") or "espn").lower()
            cls = _source_class(sub)
            if cls is None:
                raise ValueError(f"Unknown provider '{sub}' in competition leg "
                                 f"'{spec.get('key')}'.")
            legs.append(Leg(spec["key"], cls(_LegConfig(cfg, spec)),
                            spec.get("team", "")))
        return MultiSource(legs)

    cls = _source_class(name)
    if cls is None:
        raise ValueError(f"Unknown DATA_PROVIDER '{name}'. "
                         f"Choose {[*_SOURCES, 'fcf', 'multi']}.")
    return cls(cfg)

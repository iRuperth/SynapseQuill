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


def get_data_source(cfg):
    """Return the configured data source for a BrandProfile."""
    name = (getattr(cfg, "DATA_PROVIDER", None)
            or os.getenv("DATA_PROVIDER", "espn")).lower()
    cls = _SOURCES.get(name)
    if cls is None:
        raise ValueError(f"Unknown DATA_PROVIDER '{name}'. Choose {list(_SOURCES)}.")
    return cls(cfg)

"""
data_sources — switchable football data providers.

All providers return the same `Match`/`Goal` dataclasses (from match_monitor),
so the rest of the pipeline never depends on which API is configured.

DATA_PROVIDER (env / profile):
    apifootball   API-Football — La Liga/Premier/etc with full scorers+minutes
                  (free plan covers seasons 2021-2023)
    thesportsdb   TheSportsDB — covers the World Cup 2026 (free key 123); final
                  scores yes, scorers+minutes only on its paid v2

`get_data_source(cfg)` returns the provider selected for a profile.
"""

import os

from .apifootball import ApiFootballSource
from .thesportsdb import TheSportsDbSource

_SOURCES = {
    "apifootball": ApiFootballSource,
    "thesportsdb": TheSportsDbSource,
}


def get_data_source(cfg):
    """Return the configured data source for a BrandProfile."""
    name = (getattr(cfg, "DATA_PROVIDER", None)
            or os.getenv("DATA_PROVIDER", "apifootball")).lower()
    cls = _SOURCES.get(name)
    if cls is None:
        raise ValueError(f"Unknown DATA_PROVIDER '{name}'. Choose {list(_SOURCES)}.")
    return cls(cfg)

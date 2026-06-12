"""
competitions.py — named competition presets.

Lets the frontend offer a friendly dropdown ("La Liga", "World Cup 2026")
instead of asking for raw provider/league/season ids. A preset bundles the
data provider and its identifiers so switching is a single choice.
"""

# key -> preset. `provider` picks the data source; the id fields are read by
# that source (apifootball uses league_id/season; thesportsdb uses tsdb_league).
COMPETITIONS = {
    # Spanish first division (La Liga), CURRENT season via ESPN (free, with
    # scorers+minutes). Never old seasons. Was the default pre-tournament.
    "laliga": {
        "label": "La Liga — Primera División (España, temporada actual)",
        "provider": "espn",
        "espn_slug": "esp.1",       # ESPN slug for La Liga
        "mode": "latest",
        "scorers": "full",          # ESPN gives scorers + minutes for free
    },
    # The default since the tournament kicked off on 11 Jun 2026.
    "worldcup_2026": {
        "label": "Mundial 2026 (FIFA World Cup)",
        "provider": "espn",
        "espn_slug": "fifa.world",  # ESPN slug for the World Cup
        "mode": "today",            # live competition -> show today's fixtures
        "scorers": "full",
    },
    # Other major football competitions — all via ESPN (free, with scorers +
    # minutes), CURRENT season. Each preset is just an ESPN slug; the whole
    # pipeline (narration, scorers, crests, guardrail, video) works unchanged
    # because every source returns the shared Match dataclass. Slugs verified
    # live against ESPN's public API.
    "premier": {
        "label": "Premier League (Inglaterra, temporada actual)",
        "provider": "espn", "espn_slug": "eng.1", "mode": "latest", "scorers": "full",
    },
    "seriea": {
        "label": "Serie A (Italia, temporada actual)",
        "provider": "espn", "espn_slug": "ita.1", "mode": "latest", "scorers": "full",
    },
    "bundesliga": {
        "label": "Bundesliga (Alemania, temporada actual)",
        "provider": "espn", "espn_slug": "ger.1", "mode": "latest", "scorers": "full",
    },
    "ligue1": {
        "label": "Ligue 1 (Francia, temporada actual)",
        "provider": "espn", "espn_slug": "fra.1", "mode": "latest", "scorers": "full",
    },
    "champions": {
        "label": "UEFA Champions League (temporada actual)",
        "provider": "espn", "espn_slug": "uefa.champions", "mode": "latest", "scorers": "full",
    },
    "europa": {
        "label": "UEFA Europa League (temporada actual)",
        "provider": "espn", "espn_slug": "uefa.europa", "mode": "latest", "scorers": "full",
    },
    "primeira": {
        "label": "Primeira Liga (Portugal, temporada actual)",
        "provider": "espn", "espn_slug": "por.1", "mode": "latest", "scorers": "full",
    },
    "eredivisie": {
        "label": "Eredivisie (Países Bajos, temporada actual)",
        "provider": "espn", "espn_slug": "ned.1", "mode": "latest", "scorers": "full",
    },
    "ligamx": {
        "label": "Liga MX (México, temporada actual)",
        "provider": "espn", "espn_slug": "mex.1", "mode": "latest", "scorers": "full",
    },
    "mls": {
        "label": "MLS (EE. UU. / Canadá, temporada actual)",
        "provider": "espn", "espn_slug": "usa.1", "mode": "latest", "scorers": "full",
    },
    "argentina": {
        "label": "Liga Profesional (Argentina, temporada actual)",
        "provider": "espn", "espn_slug": "arg.1", "mode": "latest", "scorers": "full",
    },
    "brasileirao": {
        "label": "Brasileirão Serie A (Brasil, temporada actual)",
        "provider": "espn", "espn_slug": "bra.1", "mode": "latest", "scorers": "full",
    },
}

DEFAULT = "worldcup_2026"


def get(key: str) -> dict:
    return COMPETITIONS.get(key, COMPETITIONS[DEFAULT])


def options() -> list[dict]:
    """List for the frontend dropdown: [{key, label, scorers}]."""
    return [{"key": k, "label": v["label"], "scorers": v["scorers"]}
            for k, v in COMPETITIONS.items()]

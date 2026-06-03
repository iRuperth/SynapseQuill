"""
competitions.py — named competition presets.

Lets the frontend offer a friendly dropdown ("La Liga", "World Cup 2026")
instead of asking for raw provider/league/season ids. A preset bundles the
data provider and its identifiers so switching is a single choice.
"""

# key -> preset. `provider` picks the data source; the id fields are read by
# that source (apifootball uses league_id/season; thesportsdb uses tsdb_league).
COMPETITIONS = {
    # Default until the World Cup starts: Spanish first division (La Liga),
    # CURRENT season via ESPN (free, with scorers+minutes). Never old seasons.
    "laliga": {
        "label": "La Liga — Primera División (España, temporada actual)",
        "provider": "espn",
        "espn_slug": "esp.1",       # ESPN slug for La Liga
        "mode": "latest",
        "scorers": "full",          # ESPN gives scorers + minutes for free
    },
    # Switch to this once the 2026 World Cup kicks off (11 Jun 2026).
    "worldcup_2026": {
        "label": "Mundial 2026 (FIFA World Cup)",
        "provider": "espn",
        "espn_slug": "fifa.world",  # ESPN slug for the World Cup
        "mode": "today",            # live competition -> show today's fixtures
        "scorers": "full",
    },
}

DEFAULT = "laliga"


def get(key: str) -> dict:
    return COMPETITIONS.get(key, COMPETITIONS[DEFAULT])


def options() -> list[dict]:
    """List for the frontend dropdown: [{key, label, scorers}]."""
    return [{"key": k, "label": v["label"], "scorers": v["scorers"]}
            for k, v in COMPETITIONS.items()]

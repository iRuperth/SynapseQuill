"""
competitions.py — named competition presets.

Lets the frontend offer a friendly dropdown ("La Liga", "World Cup 2026")
instead of asking for raw provider/league/season ids. A preset bundles the
data provider and its identifiers so switching is a single choice.
"""

# key -> preset. `provider` picks the data source; the id fields are read by
# that source (apifootball uses league_id/season; thesportsdb uses tsdb_league).
COMPETITIONS = {
    "laliga_2023": {
        "label": "La Liga 2023/24 (España)",
        "provider": "apifootball",
        "league_id": 140,
        "season": 2023,
        "mode": "latest",
        "scorers": "full",          # API-Football gives scorers on the free plan
    },
    "premier_2023": {
        "label": "Premier League 2023/24",
        "provider": "apifootball",
        "league_id": 39,
        "season": 2023,
        "mode": "latest",
        "scorers": "full",
    },
    "worldcup_2026": {
        "label": "Mundial 2026 (FIFA World Cup)",
        "provider": "thesportsdb",
        "tsdb_league": "4429",
        "season": 2026,
        "mode": "today",            # live competition -> show today's fixtures
        "scorers": "espn",          # scores from TheSportsDB, scorers via ESPN
    },
    "worldcup_2022": {
        "label": "Mundial 2022 (Qatar)",
        "provider": "apifootball",
        "league_id": 1,
        "season": 2022,
        "mode": "latest",
        "scorers": "full",
    },
}

DEFAULT = "laliga_2023"


def get(key: str) -> dict:
    return COMPETITIONS.get(key, COMPETITIONS[DEFAULT])


def options() -> list[dict]:
    """List for the frontend dropdown: [{key, label, scorers}]."""
    return [{"key": k, "label": v["label"], "scorers": v["scorers"]}
            for k, v in COMPETITIONS.items()]

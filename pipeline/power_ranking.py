"""
power_ranking.py — Power Ranking of the 48 World Cup 2026 national teams.

The "power" here is the official FIFA/Coca-Cola World Ranking (rank + points),
the canonical strength ranking of national teams. FIFA doesn't publish a free
API and the live pages are JS-rendered, so the rank+points below are a curated
snapshot of the real ranking as of 10 June 2026 (sources: football-ranking.com
live table for the top 50, FIFA/Wikipedia for the rest). The FIFA ranking only
changes on official monthly updates, so this snapshot is stable; refresh it when
a new official ranking is published.

At request time we enrich each team with its World Cup group and a flag, pulled
live from ESPN's free fifa.world standings (which lists the 48 teams by group),
so flags/groups stay correct without bundling image assets. ESPN is best-effort:
if it's unavailable the ranking still renders, just without flags/groups.
"""

from datetime import date

# Real FIFA ranking snapshot (10 Jun 2026): the 48 qualified teams, each with
# its global FIFA rank and points. `name` matches ESPN's displayName so we can
# join on it for flags/groups (aliases handled in _norm).
# rank, name, points
_FIFA_2026 = [
    (1, "Argentina", 1876.11),
    (2, "Spain", 1873.87),
    (3, "France", 1870.69),
    (4, "England", 1827.05),
    (5, "Portugal", 1766.17),
    (6, "Brazil", 1765.86),
    (7, "Morocco", 1755.44),
    (8, "Netherlands", 1753.57),
    (9, "Belgium", 1742.23),
    (10, "Germany", 1735.77),
    (11, "Croatia", 1714.87),
    (12, "Italy", 1704.73),    # not in WC26, kept out below — see _WC_NAMES
    (13, "Colombia", 1698.35),
    (14, "Mexico", 1687.48),
    (15, "Senegal", 1685.24),
    (16, "Uruguay", 1673.07),
    (17, "USA", 1671.24),
    (18, "Japan", 1661.58),
    (19, "Switzerland", 1650.07),
    (20, "IR Iran", 1619.58),
    (22, "Türkiye", 1605.73),
    (23, "Ecuador", 1598.51),
    (24, "Austria", 1597.41),
    (25, "South Korea", 1591.63),
    (27, "Australia", 1579.34),
    (28, "Algeria", 1571.04),
    (29, "Egypt", 1562.37),
    (30, "Canada", 1559.48),
    (31, "Norway", 1557.44),
    (33, "Côte d'Ivoire", 1540.87),
    (34, "Panama", 1539.15),
    (38, "Sweden", 1509.79),
    (40, "Czech Republic", 1505.74),
    (41, "Paraguay", 1505.35),
    (42, "Scotland", 1503.34),
    (45, "Tunisia", 1476.40),
    (46, "Congo DR", 1477.06),
    (50, "Uzbekistan", 1458.73),
    (55, "Qatar", 1454.00),
    (57, "Iraq", 1447.00),
    (60, "South Africa", 1429.00),
    (61, "Saudi Arabia", 1421.00),
    (63, "Jordan", 1391.00),
    (64, "Bosnia-Herzegovina", 1385.84),
    (67, "Cape Verde", 1366.00),
    (73, "Ghana", 1346.00),
    (82, "Curaçao", 1294.00),
    (83, "Haiti", 1291.00),
    (85, "New Zealand", 1281.00),
]

# Sanity: this must be the 48 World Cup teams. (Italy is in the FIFA top-12 but
# did NOT qualify; it's excluded so the list is exactly the 48 participants.)
_NOT_IN_WC = {"Italy"}


def _norm(name: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold().strip()
    aliases = {
        "united states": "usa", "korea republic": "south korea",
        "ir iran": "iran", "iran": "iran", "turkiye": "turkey",
        "czechia": "czech republic", "cote d'ivoire": "ivory coast",
        "ivory coast": "ivory coast", "cabo verde": "cape verde",
        "dr congo": "congo dr", "curacao": "curacao",
    }
    return aliases.get(s, s)


def _espn_group_flags() -> dict:
    """{normalized team name -> {group, flag}} from ESPN's free WC standings.
    Best-effort: returns {} on any failure."""
    try:
        import requests
        url = ("https://site.web.api.espn.com/apis/v2/sports/soccer/"
               "fifa.world/standings")
        data = requests.get(url, timeout=20).json()
    except Exception:
        return {}
    out = {}
    for child in data.get("children", []):
        group = child.get("name", "")        # e.g. "Group A"
        for e in (child.get("standings") or {}).get("entries", []):
            team = e.get("team") or {}
            name = team.get("displayName", "")
            logos = team.get("logos") or []
            flag = (logos[0].get("href") if logos else team.get("logo", "")) or ""
            if name:
                out[_norm(name)] = {"group": group, "flag": flag}
    return out


def power_ranking() -> dict:
    """The 48 WC2026 teams ordered by FIFA rank, enriched with group + flag."""
    from .data_sources import cache
    key = ("wc_power_ranking", date.today().isoformat())
    cached = cache.get(key)
    if cached is not None:
        return cached

    meta = _espn_group_flags()
    rows = []
    for rank, name, points in _FIFA_2026:
        if name in _NOT_IN_WC:
            continue
        info = meta.get(_norm(name), {})
        rows.append({
            "rank": rank,                 # global FIFA rank
            "team": name,
            "points": points,
            "group": info.get("group", ""),
            "flag": info.get("flag", ""),
        })
    rows.sort(key=lambda r: r["rank"])
    # Display position (1..48) distinct from the global FIFA rank.
    for i, r in enumerate(rows, 1):
        r["pos"] = i

    result = {
        "source": "FIFA/Coca-Cola World Ranking",
        "as_of": "2026-06-10",
        "count": len(rows),
        "rows": rows,
    }
    cache.put(key, result)
    return result

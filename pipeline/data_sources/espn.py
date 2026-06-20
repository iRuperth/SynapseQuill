"""
espn.py — ESPN public (unofficial) API as a PRIMARY football data source.

Verified live (June 2026) to provide CURRENT-season data — La Liga 2025/26 and
the FIFA World Cup 2026 — with final scores AND scorers+minutes, for FREE with
no API key. This is what lets the app show recent matches (not old seasons).

League slug per competition (ESPN naming):
    esp.1         La Liga (Spanish Primera División)
    fifa.world    FIFA World Cup

Returns the shared Match/Goal/Card dataclasses so the pipeline stays
provider-agnostic. Undocumented API: cache responses and keep it best-effort.
"""

import os
import re
from datetime import date, timedelta

import requests

from pipeline.match_monitor import Card, Goal, Match

from .base import FootballDataSource

_FINISHED_STATES = {"STATUS_FULL_TIME", "STATUS_FINAL"}

# Pull the cause out of an ESPN card sentence so the narrator can state it as a
# FACT (never invented): "... is shown the yellow card for a bad foul." ->
# "a bad foul". Returns "" when ESPN gives no reason, so nothing is fabricated.
_CARD_REASON_RE = re.compile(
    r"(?:shown the (?:yellow|red) card|is sent off|receives a (?:yellow|red) card)"
    r"\s+for\s+(.+?)\s*\.?\s*$", re.IGNORECASE)


def _card_reason(text: str | None) -> str:
    m = _CARD_REASON_RE.search((text or "").strip())
    return m.group(1).strip() if m else ""


# Who the foul was committed ON — recovered from the play-by-play commentary, so
# the narrator can say "por una falta sobre X" (a FACT, never invented). ESPN
# logs a booking's foul as two adjacent lines: "<victim> wins a free kick ..."
# immediately followed by "Foul by <carded player> (...)". Pairing those gives
# the victim. Only emitted when the adjacency is unambiguous (~37% of cards);
# the rest carry no victim and the narration simply omits it.
_WINS_FK_RE = re.compile(r"^(.+?)\s+\(.+?\)\s+wins a free kick", re.IGNORECASE)
_FOUL_BY_RE = re.compile(r"^Foul by\s+(.+?)\s+\(", re.IGNORECASE)


def _with_victim(reason: str, carded_player: str, victims: dict) -> str:
    """Append the foul victim to a FOUL reason when one was paired from the
    commentary: 'a bad foul' -> 'a bad foul on Enner Valencia'. Only for foul-type
    reasons (a victim makes no sense for hand ball / dissent / celebration), and
    only when the carded player matches a paired foul — otherwise the reason is
    returned unchanged so nothing is invented."""
    if not reason or "foul" not in reason.lower() and "tackle" not in reason.lower():
        return reason
    key = carded_player.split()[-1] if carded_player.split() else carded_player
    victim = victims.get(key)
    if victim and victim.split()[-1] != key:        # guard: not a self-match
        return f"{reason} on {victim}"
    return reason


def merge_second_yellow(cards: list[Card]) -> list[Card]:
    """Collapse a second-booking sending-off into ONE red card flagged as a
    double yellow, so the timeline draws a single 'yellow+yellow -> red' icon.

    A second yellow arrives as TWO key events on the same player and minute: a
    plain 'Yellow Card' AND a 'Red Card' whose text reads 'Second yellow card
    to ...'. Left as two cards the timeline draws both — and the stray yellow
    can be the icon shown, so an expulsion looks like a mere booking. We drop
    that duplicate yellow and mark the red as `second_yellow=True` so the
    graphics know it came from a double booking and the narrator can say
    'doble amarilla, expulsado'."""
    red_keys = {(c.player, c.minute) for c in cards
                if (c.color or "").lower() == "red"}
    out = []
    for c in cards:
        is_dup_yellow = ((c.color or "").lower() == "yellow"
                         and (c.player, c.minute) in red_keys)
        if is_dup_yellow:
            continue                                # drop the redundant yellow
        if (c.color or "").lower() == "red" and (c.player, c.minute) in red_keys \
                and any((o.player, o.minute) == (c.player, c.minute)
                        and (o.color or "").lower() == "yellow" for o in cards):
            c.second_yellow = True                  # this red WAS a double booking
        out.append(c)
    return out


def _card_victims(summary: dict) -> dict:
    """Map 'carded player surname' -> 'foul victim full name' from the commentary.
    Keyed by the carded player's LAST token so it lines up with the keyEvents
    display name regardless of accents/first-name differences across feeds."""
    com = [(c.get("text") or "").strip() for c in summary.get("commentary") or []]
    victims: dict = {}
    for i, line in enumerate(com):
        fb = _FOUL_BY_RE.match(line)
        if not fb or i == 0:
            continue
        prev = com[i - 1]
        w = _WINS_FK_RE.match(prev)
        if not w:
            continue
        fouler = fb.group(1).strip()
        victim = w.group(1).strip()
        # Key by the fouler's last token (a surname) — robust across feeds.
        key = fouler.split()[-1] if fouler.split() else fouler
        victims.setdefault(key, victim)
    return victims


def _goal_kind(ke: dict, ttype: str, text: str) -> str:
    """Classify a goal as 'Penalty' / 'Own Goal' / 'Normal Goal'. ESPN often
    leaves the boolean flags (penaltyKick / ownGoal) UNSET and only signals the
    type via the event's type label ('Penalty - Scored') or its sentence
    ('converts the penalty', 'own goal'). Reading all three keeps the kind
    correct — and stops the guardrail from rejecting a narration that rightly
    calls a penalty a penalty."""
    low = f"{ttype} {text}".lower()
    if ke.get("penaltyKick") or "penalty" in low or "from the penalty spot" in low:
        return "Penalty"
    if ke.get("ownGoal") or "own goal" in low:
        return "Own Goal"
    return "Normal Goal"


class EspnSource(FootballDataSource):
    name = "espn"

    def __init__(self, cfg):
        self.cfg = cfg
        # The profile's resolved slug (cfg.ESPN_SLUG) already applies the right
        # precedence: competition preset > profile.json > .env. Trust it so the
        # league chosen in the UI wins over the global ESPN_LEAGUE_SLUG default.
        # Fall back to the raw env only when no profile slug is available.
        self.slug = (getattr(cfg, "ESPN_SLUG", None)
                     or cfg.get_secret("ESPN_LEAGUE_SLUG")
                     or os.getenv("ESPN_LEAGUE_SLUG", "esp.1"))
        self.base = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{self.slug}"

    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict, ttl: float | None = None) -> dict:
        from . import cache
        key = ("espn", self.slug, path, tuple(sorted(params.items())))
        cached = cache.get(key, max_age=ttl)
        if cached is not None:
            return cached
        r = requests.get(f"{self.base}/{path}", params=params, timeout=30)
        if not r.ok:
            stale = cache.get_stale(key)
            if stale is not None:
                return stale
            r.raise_for_status()
        data = r.json()
        cache.put(key, data)
        return data

    # ------------------------------------------------------------------
    def _event_to_match(self, ev: dict) -> Match:
        comp = (ev.get("competitions") or [{}])[0]
        competitors = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        home, away = competitors.get("home", {}), competitors.get("away", {})

        def _name(c):
            return (c.get("team") or {}).get("displayName", "")

        def _score(c):
            try:
                return int(c.get("score"))
            except (TypeError, ValueError):
                return None

        def _pens(c):
            try:
                return int(c.get("shootoutScore"))
            except (TypeError, ValueError):
                return None

        venue = (comp.get("venue") or {})
        status = ((ev.get("status") or {}).get("type") or {}).get("name", "")
        return Match(
            fixture_id=int(ev["id"]) if str(ev.get("id", "")).isdigit() else ev.get("id"),
            status="FT" if status in _FINISHED_STATES else status or "NS",
            home=_name(home), away=_name(away),
            home_goals=_score(home), away_goals=_score(away),
            home_pens=_pens(home), away_pens=_pens(away),
            home_logo=(home.get("team") or {}).get("logo", "") or "",
            away_logo=(away.get("team") or {}).get("logo", "") or "",
            venue=venue.get("fullName", "") or "",
            city=(venue.get("address") or {}).get("city", "") or "",
            country=(venue.get("address") or {}).get("country", "") or "",
            competition=(ev.get("league") or {}).get("name", "")
            or self._league_name(ev),
            date=(ev.get("date", "") or "")[:10],
            kickoff=ev.get("date", "") or "",   # full ISO datetime (UTC)
        )

    @staticmethod
    def _league_name(ev: dict) -> str:
        # scoreboard puts the league name at the top level, not on the event.
        return ""

    # ------------------------------------------------------------------
    def _scoreboard(self, dates: str, ttl: float | None = None) -> list[Match]:
        data = self._get("scoreboard", {"dates": dates, "limit": 300}, ttl=ttl)
        league_name = ((data.get("leagues") or [{}])[0]).get("name", "")
        matches = []
        for ev in data.get("events", []):
            m = self._event_to_match(ev)
            if not m.competition:
                m.competition = league_name
            matches.append(m)
        return matches

    def fixtures_on(self, day: str | None = None) -> list[Match]:
        day = (day or date.today().isoformat()).replace("-", "")
        # Yesterday's and today's scoreboards are LIVE data: cache them for
        # only 60s — under the scheduler's poll interval — so a result is
        # seen moments after full time, not when the 6h snapshot expires.
        # ESPN is keyless and free, there is no quota to protect; older days
        # are final and keep the long default TTL.
        live = {(date.today() - timedelta(days=d)).strftime("%Y%m%d")
                for d in (0, 1)}
        return self._scoreboard(day, ttl=60 if day in live else None)

    def latest_finished(self, limit: int = 10) -> list[Match]:
        # Scan the last ~45 days; return the most recent finished matches.
        end = date.today()
        start = end - timedelta(days=45)
        rng = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
        matches = self._scoreboard(rng)
        finished = [m for m in matches if m.is_finished]
        finished.sort(key=lambda m: (m.date or "", m.fixture_id or 0), reverse=True)
        return finished[:limit]

    def fixture(self, fixture_id) -> Match:
        data = self._get("summary", {"event": str(fixture_id)})
        header = (data.get("header") or {})
        comp = (header.get("competitions") or [{}])[0]
        competitors = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        home, away = competitors.get("home", {}), competitors.get("away", {})

        def _name(c):
            return (c.get("team") or {}).get("displayName", "")

        def _score(c):
            try:
                return int(c.get("score"))
            except (TypeError, ValueError):
                return None

        def _pens(c):
            try:
                return int(c.get("shootoutScore"))
            except (TypeError, ValueError):
                return None

        gameinfo = (data.get("gameInfo") or {})
        venue = (gameinfo.get("venue") or {})
        league = (header.get("league") or {})
        status = ((comp.get("status") or {}).get("type") or {}).get("name", "")
        match = Match(
            fixture_id=int(fixture_id) if str(fixture_id).isdigit() else fixture_id,
            status="FT" if status in _FINISHED_STATES else status or "FT",
            home=_name(home), away=_name(away),
            home_goals=_score(home), away_goals=_score(away),
            home_pens=_pens(home), away_pens=_pens(away),
            home_logo=(home.get("team") or {}).get("logos", [{}])[0].get("href", "")
            if (home.get("team") or {}).get("logos") else (home.get("team") or {}).get("logo", ""),
            away_logo=(away.get("team") or {}).get("logos", [{}])[0].get("href", "")
            if (away.get("team") or {}).get("logos") else (away.get("team") or {}).get("logo", ""),
            venue=venue.get("fullName", "") or "",
            city=(venue.get("address") or {}).get("city", "") or "",
            country=(venue.get("address") or {}).get("country", "") or "",
            competition=league.get("name", "") or "",
            date=(header.get("date") or comp.get("date", "") or "")[:10],
            kickoff=header.get("date") or comp.get("date", "") or "",
        )
        match.goals, match.cards = self._events(data)
        match.stats = _team_stats(data)
        match.notes = _key_notes(data)
        return match

    # ------------------------------------------------------------------
    @staticmethod
    def _events(summary: dict) -> tuple[list[Goal], list[Card]]:
        goals, cards = [], []
        victims = _card_victims(summary)
        for ke in summary.get("keyEvents", []):
            ttype = (ke.get("type") or {}).get("text", "")
            minute = str((ke.get("clock") or {}).get("displayValue", "?")).rstrip("'")
            team = (ke.get("team") or {}).get("displayName", "")
            parts = ke.get("participants") or [{}]
            player = (parts[0].get("athlete") or {}).get("displayName", "Unknown")
            if ke.get("scoringPlay") or ttype == "Goal":
                text = (ke.get("text") or "").strip()
                goals.append(Goal(player=player, team=team, minute=minute,
                                  kind=_goal_kind(ke, ttype, text),
                                  description=text))
            elif "Card" in ttype or "card" in ttype.lower():
                color = "Red" if "Red" in ttype else "Yellow"
                cards.append(Card(player=player, team=team, minute=minute,
                                  color=color,
                                  reason=_with_victim(_card_reason(ke.get("text")),
                                                      player, victims)))
        return goals, merge_second_yellow(cards)


# ---------------------------------------------------------------------------
# Optional enrichment from the match summary: team statistics + key notes.
# Both are best-effort and used only to make a FACTUAL narration richer; they
# never feed an invented claim (the narrator restates them, the guardrail still
# blocks anything not present in the facts).
# ---------------------------------------------------------------------------

# ESPN boxscore stat name -> our compact key. Only the stats a commentator
# actually narrates; the rest of the boxscore is ignored.
_STAT_KEYS = {
    "possessionPct": "possession", "possession": "possession",
    "totalShots": "shots", "shotsOnTarget": "shots_on",
    "wonCorners": "corners", "foulsCommitted": "fouls",
}


def _team_stats(summary: dict) -> dict:
    """{team_name: {possession, shots, shots_on, corners, fouls}} from the ESPN
    boxscore. Missing stats are simply absent; an empty dict means no boxscore
    (older or lower-profile fixtures), and the narration just omits stats."""
    out: dict = {}
    for t in (summary.get("boxscore") or {}).get("teams", []):
        name = (t.get("team") or {}).get("displayName", "")
        if not name:
            continue
        vals: dict = {}
        for s in t.get("statistics") or []:
            key = _STAT_KEYS.get(s.get("name", ""))
            if not key:
                continue
            raw = (s.get("displayValue") or "").replace("%", "").strip()
            try:
                vals[key] = float(raw) if "." in raw else int(raw)
            except ValueError:
                continue
        if vals:
            out[name] = vals
    return out


# Commentary lines worth surfacing that the goal/card key-events miss: a VAR
# overturn, a goal off the woodwork, a missed/saved penalty, and HOW a penalty
# was won (who drew it / who conceded it in the box). Matched on ESPN's own
# wording so nothing is invented; capped to keep the facts block tight.
_NOTE_RE = re.compile(
    r"\b(VAR|overturned|disallowed|ruled out|hits the (?:post|bar|crossbar)|"
    r"off the (?:post|bar|crossbar)|misses the penalty|penalty saved|"
    r"saved penalty|misses? a penalty|draws a foul in the penalty area|"
    r"penalty conceded by)\b", re.IGNORECASE)


def _key_notes(summary: dict, limit: int = 6) -> list[str]:
    """Short factual notes from the play-by-play commentary that the key events
    don't carry (VAR, woodwork, missed penalties). Each is 'minute · text', in
    chronological order, capped at `limit`."""
    notes: list[str] = []
    for c in summary.get("commentary") or []:
        text = (c.get("text") or "").strip()
        if not text or not _NOTE_RE.search(text):
            continue
        minute = str((c.get("time") or {}).get("displayValue", "")).rstrip("'")
        notes.append(f"{minute} · {text}" if minute else text)
        if len(notes) >= limit:
            break
    return notes


# ---------------------------------------------------------------------------
# League standings (a different ESPN host than the scoreboard one above).
# ---------------------------------------------------------------------------
# The scoreboard lives on site.api.espn.com, but standings are only served by
# the site.web.api host under /apis/v2 (the site.api path returns {}). So this
# is a standalone module function rather than an EspnSource method.
_STANDINGS_BASE = "https://site.web.api.espn.com/apis/v2/sports/soccer"


def standings(slug: str = "esp.1") -> list[dict]:
    """Flattened league table for an ESPN soccer slug (esp.1 = La Liga).

    Returns rows pre-sorted by rank. Cached per (slug, day); on a failed fetch
    falls back to the stale cache so the table still renders.
    """
    from . import cache
    key = ("espn_standings", slug, date.today().isoformat())
    cached = cache.get(key)
    if cached is not None:
        return cached
    r = requests.get(f"{_STANDINGS_BASE}/{slug}/standings", timeout=30)
    if not r.ok:
        stale = cache.get_stale(key)
        if stale is not None:
            return stale
        r.raise_for_status()
    rows = _flatten_standings(r.json())
    cache.put(key, rows)
    return rows


def _flatten_standings(data: dict) -> list[dict]:
    """ESPN standings JSON -> [{rank, team, abbr, flag, played, won, draw,
    lost, gf, ga, gd, points}], sorted by rank."""
    children = data.get("children") or [{}]
    entries = (children[0].get("standings") or {}).get("entries", [])
    out = []
    for e in entries:
        team = e.get("team") or {}
        stats = {s.get("name"): s for s in (e.get("stats") or [])}

        def _num(name, _stats=stats):
            s = _stats.get(name) or {}
            v = s.get("value")
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        logos = team.get("logos") or []
        out.append({
            "rank": _num("rank"),
            "team": team.get("displayName", ""),
            "abbr": team.get("abbreviation", ""),
            "flag": (logos[0].get("href") if logos else team.get("logo", "")) or "",
            "played": _num("gamesPlayed"),
            "won": _num("wins"),
            "draw": _num("ties"),
            "lost": _num("losses"),
            "gf": _num("pointsFor"),
            "ga": _num("pointsAgainst"),
            "gd": _num("pointDifferential"),
            "points": _num("points"),
        })
    out.sort(key=lambda r: r["rank"])
    return out

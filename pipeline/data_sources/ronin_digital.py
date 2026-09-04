"""
ronin_digital.py — Rōnin FC's fixtures and results from the club's community
site, roninfc.digital.

WHY A SECOND RŌNIN SOURCE. The primary one (fcf.py, reading roninfc.fans) is
richer by far: it republishes the federation's own acta, so it carries scorers,
minutes, cards, referee and line-ups. But on 4 Sep 2026 it held NOTHING of the
2026/27 season — no results and no calendar, its front page still reading
"Último Partido 16/05/26" and "No hay partidos próximos" — while this site and
BeSoccer both already listed the full Tercera Catalana fixture list. A club feed
that goes quiet for a whole season is not a feed, so this exists to guarantee
the match is at least NOTICED. See fallback.FallbackSource for how the two are
combined: the acta still wins whenever it exists.

WHAT IT YIELDS: the scoreline, both crests, the kickoff datetime and the
competition as the site names it ("3ª Catalana."). NOT the goals — there is no
scorer or minute anywhere on the page, so a video built from this source alone
narrates the result without naming who scored. That is the whole reason it is
the backup and not the primary.

HOW IT IS PARSED. The site is a Next.js app whose match list is embedded in the
HTML itself as React Server Component payload — `self.__next_f.push([1,"…"])`
chunks holding JSON with the quotes backslash-escaped. So the data is read
straight out of the delivered document with no headless browser and no call to
the site's /api/, which its robots.txt disallows (verified 4 Sep 2026:
`User-Agent: * / Allow: / Disallow: /api/`). One request serves every fixture of
the season, which is why the poll costs the same whether it is asked for one day
or twelve.

Fixture ids are the site's own ("match-2026181442"), which are stable and
already filename-safe.
"""

import json
import re
from datetime import date as _date

import requests

from pipeline.match_monitor import Match

from . import cache
from .base import FootballDataSource

_BASE = "https://roninfc.digital"
_FIXTURES = "/partidos"

# Identify ourselves honestly rather than impersonating a browser. This is a
# community site run by supporters, not a CDN-backed API.
_HEADERS = {"User-Agent": "F88tball/1.0 (football highlight generator; contact via repo)"}
_TIMEOUT = 30

# One document carries the WHOLE season, so this TTL is not a per-match cost:
# fifteen minutes bounds the site to at most four requests an hour no matter how
# often the scheduler wakes.
_TTL = 15 * 60

# A finished match on this site is labelled in Spanish. Anything else ("Próximo",
# "En directo") is not a result yet.
_DONE = "finalizado"

# The site prints the competition with a numeral and a trailing dot ("3ª
# Catalana."), sometimes followed by the round ("4ª Catalana. Jornada 25").
# core/competitions.py matches its presets against this string, so both the
# numeral forms and the round suffix are handled there by the tier aliases.


class RoninDigitalSource(FootballDataSource):
    """Rōnin FC's season, read from the community site's embedded payload."""

    name = "ronindigital"

    def __init__(self, cfg=None):
        self.cfg = cfg
        self.base = (getattr(cfg, "RONIN_DIGITAL_BASE_URL", "") or _BASE).rstrip("/")

    # ------------------------------------------------------------------
    def _document(self) -> str:
        key = ("ronindigital", self.base, _FIXTURES)
        cached = cache.get(key, max_age=_TTL)
        if cached is not None:
            return cached
        r = requests.get(f"{self.base}{_FIXTURES}", headers=_HEADERS, timeout=_TIMEOUT)
        if not r.ok:
            stale = cache.get_stale(key)
            if stale is not None:
                return stale      # a flaky community site must not stop the feed
            r.raise_for_status()
        cache.put(key, r.text)
        return r.text

    # ------------------------------------------------------------------
    def _all(self) -> list[Match]:
        """Every fixture of the season, played or not.

        The RSC payload escapes its JSON for embedding in a JavaScript string
        literal, so the document's `\\"` are unescaped before the objects are
        cut out of it. Each object is then parsed with a real JSON parser rather
        than by regex, so a field moving or being added cannot silently produce
        a half-read match.
        """
        doc = self._document().replace('\\"', '"')
        seen: dict[str, Match] = {}
        for raw in re.finditer(r'\{"id":"match-\d+".*?"startTime":"[^"]*"\}', doc):
            try:
                obj = json.loads(raw.group(0))
            except json.JSONDecodeError:
                continue          # a truncated chunk drops one match, not the feed
            match = self._to_match(obj)
            if match is not None:
                # The page renders the same fixture in more than one block (a
                # "next match" hero and the full calendar). Keeping the last one
                # seen is safe: they carry identical data under identical ids.
                seen[str(match.fixture_id)] = match
        out = list(seen.values())
        out.sort(key=lambda m: (m.date or "", str(m.fixture_id)))
        return out

    @staticmethod
    def _to_match(obj: dict) -> Match | None:
        home, away = (obj.get("homeTeam") or "").strip(), (obj.get("awayTeam") or "").strip()
        if not home or not away:
            return None
        finished = (obj.get("status") or "").strip().lower() == _DONE
        # `startTime` is a full ISO datetime with the club's own offset
        # ("2026-09-20T12:30:00+02:00"); its date half is the calendar day the
        # scheduler and the digest key everything off.
        start = (obj.get("startTime") or "").strip()
        day = start[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            return None           # without a date it can be neither polled nor grouped
        return Match(
            fixture_id=str(obj.get("id") or "").strip(),
            status="FT" if finished else "NS",
            home=home, away=away,
            home_goals=_int(obj.get("homeScore")) if finished else None,
            away_goals=_int(obj.get("awayScore")) if finished else None,
            home_logo=(obj.get("homeLogo") or "").strip(),
            away_logo=(obj.get("awayLogo") or "").strip(),
            competition=(obj.get("competition") or "").strip(),
            date=day, kickoff=start,
        )

    # ------------------------------------------------------------------
    def fixtures_on(self, day: str | None = None) -> list[Match]:
        day = day or _date.today().isoformat()
        return [m for m in self._all() if m.date == day]

    def latest_finished(self, limit: int = 10) -> list[Match]:
        done = [m for m in self._all() if m.is_finished]
        done.sort(key=lambda m: (m.date or "", str(m.fixture_id)), reverse=True)
        return done[:limit]

    def fixture(self, fixture_id) -> Match:
        """The match as the season listing already gives it.

        There is no per-match page to fetch: this source has no goals to add, so
        the listing entry IS the complete record. Callers still get a Match with
        an empty `goals` list, exactly as they do for an FCF friendly whose acta
        carries no goals either.
        """
        wanted = str(fixture_id)
        for m in self._all():
            if str(m.fixture_id) == wanted:
                return m
        raise LookupError(f"{self.name}: no fixture '{wanted}'")


def _int(value) -> int | None:
    """The scores arrive as strings ("5"); a blank or absent one is unknown."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None

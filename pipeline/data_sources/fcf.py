"""
fcf.py — Catalan amateur football (Rōnin FC), the club ESPN does not cover.

WHY NOT fcf.cat DIRECTLY: the Catalan federation is the origin of this data, but
its robots.txt says `Disallow: /api/`, so its JSON API is off limits to an
automated poller. This source therefore reads the club's public supporters site
(roninfc.fans), which republishes the federation's own match report — the
"acta" — and whose robots.txt allows automated access (`User-Agent: * / Allow: /`,
only /private/ disallowed, sitemap published). Verified 17 Aug 2026.

WHAT IT YIELDS: much more than a scoreline. The acta is the official record, so
a Tercera Catalana video gets the same factual richness as a LaLiga one:
    · goals with minute AND scorer          "10' 1-0 JIMENEZ MOYA, DIEGO"
    · cards with minute and colour          "LOUAH MHAND YAMNA, NADIR (14') Amarilla"
    · kickoff datetime, venue, referee, line-ups
What it does NOT have is possession/shot statistics, a goal description, or crest
artwork — so the narration stays factual but leaner, and the scoreboard draws no
crest (there is no logo URL to fetch).

TWO-STEP FETCH, mirroring the ESPN source so polling stays cheap:
    listing page  -> every match with date + score      (one request per poll)
    acta page     -> goals and cards for ONE match      (only when it finishes)

Fixture ids are the acta path with "/" replaced by "_", which is stable,
reversible (so `fixture()` can rebuild the URL without any lookup table) and
safe as a filename.
"""

import re
import unicodedata
from datetime import date as _date

import requests

from pipeline.match_monitor import Card, Goal, Match

from . import cache
from .base import FootballDataSource

_BASE = "https://www.roninfc.fans"
_LISTING = "/resultados/partidos"
_ACTA_PREFIX = "/resultados/partidos/acta/"

# Identify ourselves honestly rather than impersonating a browser, and keep the
# poll gentle: this is a small community site, not a CDN-backed API.
_HEADERS = {"User-Agent": "F88tball/1.0 (football highlight generator; contact via repo)"}
_TIMEOUT = 30

# The listing is cheap and changes only on matchday; the acta of a finished game
# never changes at all.
_LIST_TTL = 15 * 60          # 15 min
_ACTA_TTL = 30 * 24 * 3600   # a closed acta is final


def _text(fragment: str) -> str:
    """Visible text of an HTML fragment, whitespace-collapsed."""
    import html as _html
    f = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", fragment, flags=re.S | re.I)
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", f))).strip()


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if not unicodedata.combining(c)).strip()


def path_to_id(acta_path: str) -> str:
    """'/resultados/partidos/acta/2526/.../away' -> '2526_..._away'."""
    return acta_path.removeprefix(_ACTA_PREFIX).strip("/").replace("/", "_")


def id_to_path(fixture_id) -> str:
    """Inverse of path_to_id, so a stored id can be re-fetched with no state."""
    return _ACTA_PREFIX + str(fixture_id).replace("_", "/")


def _competition_from_path(acta_path: str) -> str:
    """'.../2526/futbol-11/tercera-catalana/grup-7/...' -> 'Tercera Catalana'.

    The competition is read from the URL rather than scraped from the page, so
    the club moving up a division (or playing a cup tie) is picked up with no
    code change — and the name lands in Match.competition, which is what
    core/competitions.py matches its presets against for hashtags and titles.

    Friendlies use a shorter, different shape — '.../2526/amistosos/2', where
    the last segment is just a counter — so a positional read would name the
    competition "2". Those are detected and named properly instead.
    """
    parts = acta_path.removeprefix(_ACTA_PREFIX).strip("/").split("/")
    # Competition shape: [season, sport, competition, group, cat, home, cat, away]
    # Friendly shape:    [season, "amistosos", n]
    if len(parts) >= 2 and parts[1].startswith("amistos"):
        return "Amistoso"
    if len(parts) >= 3 and not parts[2].isdigit():
        return parts[2].replace("-", " ").title()
    return ""


def _ddmmyy(s: str) -> str:
    """'10/05/26' -> '2026-05-10'. Returns '' when it doesn't match."""
    m = re.match(r"(\d{2})/(\d{2})/(\d{2})$", s.strip())
    if not m:
        return ""
    d, mo, y = m.groups()
    return f"20{y}-{mo}-{d}"


class FcfSource(FootballDataSource):
    """Rōnin FC's fixtures and results, from the federation acta."""

    name = "fcf"

    def __init__(self, cfg=None):
        self.cfg = cfg
        self.base = (getattr(cfg, "FCF_BASE_URL", "") or _BASE).rstrip("/")
        # The club this feed is about. Only used to label things; the site is
        # already a single-club feed, and multi.py applies the real filter.
        self.team = getattr(cfg, "FCF_TEAM", "") or "Rōnin FC"

    # ------------------------------------------------------------------
    def _get(self, path: str, ttl: float) -> str:
        key = ("fcf", self.base, path)
        cached = cache.get(key, max_age=ttl)
        if cached is not None:
            return cached
        r = requests.get(f"{self.base}{path}", headers=_HEADERS, timeout=_TIMEOUT)
        if not r.ok:
            stale = cache.get_stale(key)
            if stale is not None:
                return stale          # a flaky community site must not stop the feed
            r.raise_for_status()
        cache.put(key, r.text)
        return r.text

    # ------------------------------------------------------------------
    def _listing_matches(self) -> list[Match]:
        """Every match on the results page: date, teams, score. No goals — those
        cost one request each and are only fetched by `fixture()`."""
        html_doc = self._get(_LISTING, _LIST_TTL)
        # The page renders the same fixture in two layouts: a wide "last match"
        # hero card and the compact result rows. Keep the BEST parse per fixture
        # rather than the first one seen — the hero card puts everything in a
        # single text blob, so its names are the shakier of the two.
        best: dict[str, tuple[int, Match]] = {}
        # Each match is one <a> pointing at its acta. Non-greedy to the closing
        # tag: these anchors are leaves, they never nest another <a>.
        for m in re.finditer(r'<a[^>]+href="(' + re.escape(_ACTA_PREFIX) +
                             r'[^"]+)"[^>]*>(.*?)</a>', html_doc, re.S):
            path, inner = m.group(1), m.group(2)
            parsed = self._from_listing_anchor(path, inner)
            if not parsed:
                continue
            rank, match = parsed
            if path not in best or rank > best[path][0]:
                best[path] = (rank, match)
        out = [match for _, match in best.values()]
        out.sort(key=lambda x: (x.date or "", str(x.fixture_id)))
        return out

    def _from_listing_anchor(self, path: str, inner: str) -> tuple[int, Match] | None:
        """Parse one fixture anchor. Returns (confidence, Match): 2 when the team
        names came from their own cells, 1 from the text blob, 0 from URL slugs."""
        text = _text(inner)
        day = ""
        dm = re.search(r"\b(\d{2}/\d{2}/\d{2})\b", text)
        if dm:
            day = _ddmmyy(dm.group(1))
        score = re.search(r"\b(\d{1,2})\s*-\s*(\d{1,2})\b", text)

        # Best: each team in its own <p>, with the "vs" separator dropped. Read
        # from the markup, not the URL slug, so the accents and punctuation are
        # the ones the acta itself uses ("Pª REC.SAN FELIU", not "pa-recsan-...").
        cells = [_text(c) for c in re.findall(r"<p[^>]*>(.*?)</p>", inner, re.S)]
        names = [c for c in cells if c and _fold(c) != "vs"]
        rank = 2
        if len(names) < 2:
            names, rank = self._names_from_text(text, score), 1
        if len(names) < 2:
            # Last resort: the URL slugs. Uglier, but a layout change degrades
            # to a usable name instead of silently dropping the match.
            parts = path.removeprefix(_ACTA_PREFIX).strip("/").split("/")
            if len(parts) >= 8:
                names = [parts[5].replace("-", " ").upper(),
                         parts[7].replace("-", " ").upper()]
                rank = 0
            else:
                return None
        return rank, Match(
            fixture_id=path_to_id(path),
            # A score on the results page means the game is played; without one
            # it is a scheduled fixture.
            status="FT" if score else "NS",
            home=_club(names[0]), away=_club(names[1]),
            home_goals=int(score.group(1)) if score else None,
            away_goals=int(score.group(2)) if score else None,
            competition=_competition_from_path(path),
            date=day,
        )

    @staticmethod
    def _names_from_text(text: str, score) -> list[str]:
        """Pull both teams out of the hero card's single text blob:
        "16/05/26 · 20:00 <HOME> 5 - 2 <AWAY> CAMP DE FUTBOL MPAL. DEL 25 ...".

        The score splits the two sides; the trailing venue is then cut off the
        away name, which is the only ambiguous part of the line.
        """
        if not score:
            return []
        head = text[:score.start()]
        tail = text[score.end():]
        # Drop the leading "DD/MM/YY" and an optional "· HH:MM".
        home = re.sub(r"^\s*\d{2}/\d{2}/\d{2}\s*(?:·\s*\d{2}:\d{2})?\s*", "", head)
        # The venue always follows the away team and always starts with one of
        # these words, so it is cut at the first of them.
        away = re.split(r"\s+(?=CAMP\b|CAMPO\b|ESTADI\b|ESTADIO\b|MUNICIPAL\b|C\.E\.M\.)",
                        tail.strip(), maxsplit=1)[0]
        home, away = home.strip(" -·"), away.strip(" -·")
        return [home, away] if home and away else []

    # ------------------------------------------------------------------
    def fixtures_on(self, day: str | None = None) -> list[Match]:
        day = day or _date.today().isoformat()
        return [m for m in self._listing_matches() if m.date == day]

    def latest_finished(self, limit: int = 10) -> list[Match]:
        done = [m for m in self._listing_matches() if m.is_finished]
        done.sort(key=lambda m: (m.date or "", str(m.fixture_id)), reverse=True)
        return done[:limit]

    # ------------------------------------------------------------------
    def fixture(self, fixture_id) -> Match:
        """One match with goals and cards, parsed from its acta."""
        path = id_to_path(fixture_id)
        doc = self._get(path, _ACTA_TTL)
        text = _text(doc)

        home = away = ""
        hg = ag = None
        kickoff = ""
        # The acta header reads "<HOME> <h> - <a> <DD-MM-YYYY> <HH:MM> <AWAY>".
        head = re.search(
            r"([A-ZÀ-ÿ0-9ª.,'’\-/ ]{3,60}?)\s+(\d{1,2})\s*-\s*(\d{1,2})\s+"
            r"(\d{2})-(\d{2})-(\d{4})\s+(\d{2}:\d{2})\s+([A-ZÀ-ÿ0-9ª.,'’\-/ ]{3,60}?)\s+(?:Árbitro|Arbitro|Estadio|CAMP)",
            text)
        day = ""
        if head:
            home = _club(head.group(1))
            hg, ag = int(head.group(2)), int(head.group(3))
            day = f"{head.group(6)}-{head.group(5)}-{head.group(4)}"
            kickoff = f"{day}T{head.group(7)}:00"
            away = _club(head.group(8))

        listed = next((m for m in self._listing_matches()
                       if str(m.fixture_id) == str(fixture_id)), None)
        if listed:
            # The listing is the more reliable source for the names and the day;
            # the acta regex only fills what the listing could not provide.
            home = listed.home or home
            away = listed.away or away
            day = listed.date or day
            if hg is None:
                hg, ag = listed.home_goals, listed.away_goals

        match = Match(
            fixture_id=str(fixture_id),
            status="FT" if hg is not None else "NS",
            home=home, away=away, home_goals=hg, away_goals=ag,
            competition=_competition_from_path(path),
            date=day, kickoff=kickoff,
            venue=self._venue(text),
        )
        match.goals = self._goals(text, match)
        match.cards = self._cards(doc, match)
        return match

    # ------------------------------------------------------------------
    @staticmethod
    def _venue(text: str) -> str:
        m = re.search(r"(CAMP DE FUTBOL[^,]{0,60}?)(?:\s+c/|\s+Goles|\s+Estadio|$)", text)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _goals(text: str, match: Match) -> list[Goal]:
        """Parse the 'Goles' block: "10 ' 1 - 0 JIMENEZ MOYA, DIEGO".

        The running score is what tells us WHICH side scored — the acta never
        labels a goal with its team. Whichever half of the score went up is the
        scoring team, so an own goal is still credited to the correct side of
        the scoreboard (the narrator only ever restates what it is given).
        """
        block = re.search(r"\bGoles\b(.*?)(?:\bEstadio\b|$)", text)
        if not block:
            return []
        goals: list[Goal] = []
        prev_h = prev_a = 0
        for m in re.finditer(
                r"(\d{1,3})\s*'\s*(\d{1,2})\s*-\s*(\d{1,2})\s+"
                r"([A-ZÀ-ÿ][A-ZÀ-ÿ'’.\- ]*(?:,\s*[A-ZÀ-ÿ][A-ZÀ-ÿ'’.\- ]*)?)",
                block.group(1)):
            minute, h, a, player = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
            team = match.home if h > prev_h else match.away if a > prev_a else ""
            prev_h, prev_a = h, a
            goals.append(Goal(player=_name(player), team=team, minute=minute,
                              kind="Normal Goal"))
        return goals

    @staticmethod
    def _cards(doc: str, match: Match) -> list[Card]:
        """Parse both teams' 'Tarjetas' blocks: "NAME ( 14 ') Amarilla".

        Each team has its OWN Tarjetas block, in the same order the two squads
        appear, so the block index is what assigns a card to a team — the line
        itself carries no club name. Staff bookings are kept: they are on the
        acta, and the narrator may mention them factually.
        """
        text = _text(doc)
        cards: list[Card] = []
        blocks = re.findall(r"\bTarjetas\b(.*?)(?:\bActa\b|\bTitulares\b|\bEstadio\b|$)",
                            text)
        # The acta prints the HOME squad first, then the away one.
        for idx, block in enumerate(blocks[:2]):
            team = match.home if idx == 0 else match.away
            for m in re.finditer(
                    r"-\s*([A-ZÀ-ÿ][A-ZÀ-ÿ'’.\- ]*(?:,\s*[A-ZÀ-ÿ][A-ZÀ-ÿ'’.\- ]*)?)"
                    r"\s*\(\s*(\d{1,3})\s*'\s*\)\s*(Amarilla|Vermella|Roja)", block):
                colour = "Yellow" if m.group(3).lower().startswith("amar") else "Red"
                cards.append(Card(player=_name(m.group(1)), team=team,
                                  minute=m.group(2), color=colour))
        return cards


# The federation register writes club names in caps, abbreviated, and often with
# the club type trailing after a comma ("ESPARREGUERA, C.E. A"). Spoken by the
# TTS and printed on the scoreboard that reads as shouting, so display names are
# rebuilt. The channel's own club is pinned to its brand spelling — the register
# says "RÖNIN" with a diaeresis, the club writes itself "Rōnin" with a macron.
_CLUB_FIXED = {
    "ronin futbol club a": "Rōnin FC",
    "ronin futbol club": "Rōnin FC",
}

# Club-type abbreviations that trail after a comma and belong in FRONT.
_CLUB_TYPES = {"c.e.", "u.e.", "f.c.", "c.f.", "a.e.", "c.d.", "u.d.", "a.d.",
               "c.p.", "e.f.", "s.d.", "ce", "ue", "fc", "cf", "ae", "cd", "ud"}

_PARTICLES = {"de", "la", "del", "los", "las", "y", "i", "el", "d'", "dels"}

# Catalan football shorthand the register uses. These are SPOKEN by the TTS, so
# "Pª REC.SAN FELIU" left alone is read out as "pa rec punto san feliu".
_ABBREV = {
    "pª": "Peña", "penya": "Peña", "pena": "Peña",
    "barc.": "Barcelonista", "rec.": "Recreativa", "agrup.": "Agrupació",
    "at.": "Atlético", "atl.": "Atlético", "esp.": "Esportiu",
    "mpal.": "Municipal", "ct.": "Centre", "assoc.": "Associació",
}


def _expand(s: str) -> str:
    """Split run-together abbreviations and spell them out.

    "REC.SAN FELIU" -> "Recreativa SAN FELIU". A space is inserted after a dot
    only when what precedes it is more than one letter, so genuine initialisms
    ("C.E.", "U.E.") are left intact.
    """
    s = re.sub(r"(?<=\w{2})\.(?=[A-Za-zÀ-ÿ])", ". ", s)
    return " ".join(_ABBREV.get(w.lower(), w) for w in s.split())


def _club(raw: str) -> str:
    """'ESPARREGUERA, C.E. A' -> 'C.E. Esparreguera'; 'Pª BARC. SANT VICENÇ
    HORTS B' -> 'Peña Barc. Sant Vicenç Horts B'.

    A reserve-team letter is meaningful (B/C are different teams) and is kept;
    a trailing "A" is dropped, since the first team is just the club.
    """
    s = re.sub(r"\s+", " ", (raw or "").strip())
    if not s:
        return ""
    if _fold(s) in _CLUB_FIXED:
        return _CLUB_FIXED[_fold(s)]

    # Peel off a trailing squad letter before any other reshaping.
    squad = ""
    m = re.match(r"^(.*?)\s+([A-D])$", s)
    if m:
        s, squad = m.group(1), m.group(2)

    # "ESPARREGUERA, C.E." -> "C.E. ESPARREGUERA"
    if "," in s:
        head, _, tail = s.rpartition(",")
        if tail.strip() and tail.strip().lower().rstrip(" ") in _CLUB_TYPES:
            s = f"{tail.strip()} {head.strip()}"

    s = _expand(s)
    words = []
    for i, w in enumerate(s.split()):
        low = w.lower()
        if low in _CLUB_TYPES or re.fullmatch(r"[A-Z]\.([A-Z]\.)+", w):
            words.append(w.upper())            # keep C.E. / U.E. as initials
        elif i and low in _PARTICLES:
            words.append(low)
        elif w.isdigit():
            words.append(w)
        else:
            words.append(w[:1].upper() + w[1:].lower())
    out = " ".join(words)
    # "B"/"C" name a distinct reserve side and must survive; "A" is the first
    # team, where the letter is federation bookkeeping, not part of the name.
    if squad and squad != "A":
        out = f"{out} {squad}"
    return out


def _name(raw: str) -> str:
    """'JIMENEZ MOYA, DIEGO' -> 'Diego Jimenez Moya'.

    The acta prints SURNAMES, FORENAME in caps. Left as-is the narration would
    shout a surname-first name at the viewer, and the TTS would read the comma
    as a pause mid-name.
    """
    raw = re.sub(r"\s+", " ", (raw or "").strip(" -")).strip()
    if not raw:
        return ""
    if "," in raw:
        surnames, _, forenames = raw.partition(",")
        raw = f"{forenames.strip()} {surnames.strip()}"
    # Title-case, but keep the Spanish/Catalan particles lower ("de la Barca").
    small = {"de", "la", "del", "los", "las", "y", "i", "van", "der", "el"}
    words = [w for w in raw.split() if w]
    out = [w.capitalize() if (i == 0 or w.lower() not in small) else w.lower()
           for i, w in enumerate(words)]
    return " ".join(out)

"""
competitions.py — named competition presets.

Lets the frontend offer a friendly dropdown ("La Liga", "World Cup 2026")
instead of asking for raw provider/league/season ids. A preset bundles the
data provider and its identifiers so switching is a single choice.

A preset is also the competition's IDENTITY, not just its data ids: the Spanish
name the narrator uses, the hashtags the uploads carry, the corner logo, and how
its recap is grouped. Everything downstream (narrator, digest, video) reads it
from here, so pointing the app at another competition never means editing
hardcoded "#FIFAWorldCup"/"Mundial 2026" strings scattered through the pipeline.

Preset keys
    label       friendly name for the frontend dropdown
    provider    data source ("espn")
    espn_slug   ESPN league slug (esp.1 = LaLiga, fifa.world = World Cup)
    mode        "latest" (most recent finished) | "today" (today's fixtures)
    scorers     "full" when the source gives scorers + minutes
    name_es     how the narration/titles name the competition in Spanish, with
                NO article — the article is its own key so callers can join it
                grammatically instead of concatenating a broken "de Mundial"
    article     "el" / "la" when Spanish wants one before the name; omitted for
                names that are used bare ("LaLiga", "Copa del Rey" takes "la")
    tags        competition hashtags for YouTube, most-searched first
    logo        corner logo drawn on every frame (relative to the repo root)
    digest      "matchday" — a round spans several days (leagues: Fri-Mon)
                "daily"    — every day is its own round (a tournament)
    hide_venue  True to never name the stadium (the World Cup rule)
    aliases     lower-case fragments of the competition name AS THE DATA SOURCE
                reports it, so a Match can be traced back to its preset
"""

import re

# ── The clubs the channel films individually in European competition ──
# Every match of LaLiga and of the club's own league is covered regardless, so
# this list decides ONE thing: which foreign/cup fixtures are worth a video of
# their own rather than a mention in the round-up. Two groups, one list:
# the clubs a Spanish audience follows abroad, and every LaLiga side, so a
# Spanish club's European night is never missed.
#
# THIS IS THE ONLY PART OF THE CONFIG THAT NEEDS A LOOK EACH SUMMER — promotions,
# relegations, who qualified for Europe. Nothing else here is season-specific:
# the ESPN source queries by DATE, never by season, so a new campaign starts on
# its own. LaLiga itself is unfiltered, so a newly promoted side is covered
# without touching this list; it only gates European ties and the Copa del Rey.
#
# Names are matched accent- and case-insensitively, as a substring either way
# (see multi.Leg.wants), so the short form here still matches a provider's long
# official name.
CLUBES_GRANDES = [
    # Spain — every LaLiga club, so any of them in Europe or the Copa is filmed.
    "Real Madrid", "Barcelona", "Atletico Madrid", "Athletic Club", "Villarreal",
    "Real Sociedad", "Real Betis", "Sevilla", "Valencia", "Celta Vigo",
    "Rayo Vallecano", "Osasuna", "Mallorca", "Girona", "Getafe", "Alaves",
    "Espanyol", "Elche", "Levante", "Oviedo",
    # The rest of Europe — the clubs a Spanish viewer recognises on sight.
    "Bayern Munich", "Paris Saint-Germain", "Manchester City", "Liverpool",
    "Arsenal", "Manchester United", "Chelsea", "Tottenham", "Internazionale",
    "AC Milan", "Juventus", "Napoli", "Atalanta", "Borussia Dortmund",
    "Bayer Leverkusen", "Newcastle United", "Benfica", "FC Porto",
    "Sporting CP", "Ajax", "PSV Eindhoven",
]

# The national team, kept apart from the clubs: it is what makes a Nations
# League or a qualifier belong on this channel at all.
SELECCION = ["Spain"]

# key -> preset. `provider` picks the data source; the id fields are read by
# that source (apifootball uses league_id/season; thesportsdb uses tsdb_league).
COMPETITIONS = {
    # Spanish first division (LaLiga), CURRENT season via ESPN (free, with
    # scorers+minutes). Never old seasons. The default since the focus moved
    # off the World Cup.
    "laliga": {
        "label": "La Liga — Primera División (España, temporada actual)",
        "provider": "espn",
        "espn_slug": "esp.1",       # ESPN slug for LaLiga
        "mode": "latest",
        "scorers": "full",          # ESPN gives scorers + minutes for free
        "name_es": "LaLiga",
        "tags": ["#LaLiga"],
        "logo": "assets/logos/laliga.png",
        "digest": "matchday",       # a jornada runs Friday to Monday
        "aliases": ["laliga", "la liga", "primera divis"],
    },
    # The 2026 tournament, kept as a preset so its videos/bracket still work.
    "worldcup_2026": {
        "label": "Mundial 2026 (FIFA World Cup)",
        "provider": "espn",
        "espn_slug": "fifa.world",  # ESPN slug for the World Cup
        "mode": "today",            # live competition -> show today's fixtures
        "scorers": "full",
        "name_es": "Mundial de Fútbol 2026", "article": "el",
        "tags": ["#FIFAWorldCup", "#Mundial2026"],
        "logo": "assets/logos/worldcup_2026.png",
        "digest": "daily",          # the World Cup plays every day
        "hide_venue": True,         # the stadium is never named
        "aliases": ["world cup", "mundial", "copa mundial"],
    },
    # ── The channel ──────────────────────────────────────────────────────
    # Several unrelated providers merged into one feed (data_sources/multi.py):
    # ESPN for the Spanish and European competitions, the Catalan federation for
    # Rōnin. The `team` on the Rōnin leg is what narrows that source to the club's
    # own games, home or away, in whichever competition it is playing — so a Copa
    # Catalunya tie is picked up as readily as a league fixture.
    #
    # Every leg brings its whole competition INTO the feed, so each round-up
    # accounts for all of it. `video_teams` then decides which of those matches
    # earn a video of their own; the rest appear only in their round's recap.
    # That split is what lets the channel carry the Champions League and the Copa
    # del Rey — 189 and 137 matches a season — without filming a first round of
    # 25 ties between clubs the audience has never heard of. See multi.Leg.
    #
    # NOTHING HERE IS TIED TO A SEASON: the ESPN source queries by date, so each
    # new campaign starts on its own. The national-team legs cover the full
    # rotation (Nations League -> qualifying -> tournament -> friendlies) so the
    # cycle turning over never needs a config change either; a competition that
    # is not currently being played simply returns no fixtures, at the cost of
    # one cached request per poll against a keyless, quota-free API.
    "laliga_ronin": {
        "label": "LaLiga + Rōnin FC + Champions y selección española",
        "provider": "multi",
        "legs": [
            # The channel's base: every match, always filmed.
            {"key": "laliga", "provider": "espn", "espn_slug": "esp.1"},
            # Two providers for ONE club, not two legs. The acta source is
            # preferred because it alone carries scorers and cards; the community
            # site is the safety net, because the acta source held nothing at all
            # of the 2026/27 season while the club's calendar was already public
            # elsewhere. See data_sources/fallback.py.
            {"key": "ronin", "provider": "fcf", "team": "Rōnin",
             "fallback": "ronindigital"},
            # Spanish cups.
            {"key": "copadelrey", "provider": "espn",
             "espn_slug": "esp.copa_del_rey", "video_teams": CLUBES_GRANDES},
            {"key": "supercopa", "provider": "espn", "espn_slug": "esp.super_cup"},
            # Europe. Filmed for the clubs the audience follows, plus every tie
            # from the quarter-finals on (multi.DEFAULT_ALWAYS_ROUNDS).
            {"key": "champions", "provider": "espn",
             "espn_slug": "uefa.champions", "video_teams": CLUBES_GRANDES},
            {"key": "europa", "provider": "espn",
             "espn_slug": "uefa.europa", "video_teams": CLUBES_GRANDES},
            {"key": "conference", "provider": "espn",
             "espn_slug": "uefa.europa.conf", "video_teams": CLUBES_GRANDES},
            {"key": "supercopaeu", "provider": "espn",
             "espn_slug": "uefa.super_cup"},
            # The national team. `teams` (not `video_teams`) because the rest of
            # Europe's fixtures are not this channel's subject at all — they
            # should not even reach the round-up.
            {"key": "naciones", "provider": "espn",
             "espn_slug": "uefa.nations", "teams": SELECCION},
            {"key": "euroq", "provider": "espn",
             "espn_slug": "uefa.euroq", "teams": SELECCION},
            {"key": "euro", "provider": "espn",
             "espn_slug": "uefa.euro", "teams": SELECCION},
            {"key": "amistosos", "provider": "espn",
             "espn_slug": "fifa.friendly", "teams": SELECCION},
        ],
        "mode": "latest",
        "scorers": "full",
        # Channel-level identity. Per-MATCH identity is resolved separately from
        # each match's own competition name, so a Tercera Catalana game is not
        # tagged #LaLiga — see the two presets below.
        "name_es": "LaLiga", "tags": ["#LaLiga"],
        "logo": "assets/logos/laliga.png",
        "digest": "matchday",
        "aliases": [],              # never resolved BY name; it is a channel
    },
    # Rōnin's own competitions. These exist so a Rōnin match gets its own
    # hashtags and Spanish name instead of inheriting LaLiga's from the channel.
    # They carry no ESPN slug — the FCF leg above is what fetches them.
    # One preset for every Catalan regional tier: the club is climbing, so the
    # competition name its source reports changes from season to season (Quarta
    # -> Tercera -> ...). Matching them all here means a promotion needs no code
    # change, and #RoninFC leads either way because that — not the division — is
    # what an Ibai viewer searches for.
    "catalana": {
        "label": "Ligas catalanas (Rōnin FC — Tercera Catalana)",
        "provider": "fcf", "mode": "latest", "scorers": "goals",
        "name_es": "Tercera Catalana", "article": "la",
        "tags": ["#RoninFC", "#TerceraCatalana"],
        "digest": "matchday",
        # Each tier is named in full. A bare "catalana" would also swallow
        # "Lliga Catalana" and any other competition of the region.
        "aliases": ["tercera catalana", "quarta catalana", "cuarta catalana",
                    "segona catalana", "segunda catalana", "primera catalana"],
    },
    "copa_catalunya": {
        "label": "Copa Catalunya Absoluta (Rōnin FC)",
        "provider": "fcf", "mode": "latest", "scorers": "goals",
        "name_es": "Copa Catalunya", "article": "la",
        "tags": ["#RoninFC", "#CopaCatalunya"],
        "digest": "matchday",
        "aliases": ["copa catalunya"],
    },
    # A pre-season friendly. Its acta carries no goals at all, so it is named
    # here only so the tags don't fall through to the generic #Futbol.
    "amistoso": {
        "label": "Amistosos (Rōnin FC)",
        "provider": "fcf", "mode": "latest", "scorers": "none",
        "name_es": "un amistoso", "tags": ["#RoninFC", "#Pretemporada"],
        "digest": "matchday",
        "aliases": ["amistoso", "amistos"],
    },
    # Other major football competitions — all via ESPN (free, with scorers +
    # minutes), CURRENT season. Each preset is just an ESPN slug; the whole
    # pipeline (narration, scorers, crests, guardrail, video) works unchanged
    # because every source returns the shared Match dataclass. Slugs verified
    # live against ESPN's public API.
    "laliga2": {
        "label": "LaLiga Hypermotion — Segunda División (España, temporada actual)",
        "provider": "espn", "espn_slug": "esp.2", "mode": "latest", "scorers": "full",
        "name_es": "LaLiga Hypermotion", "tags": ["#LaLigaHypermotion", "#Segunda"],
        "logo": "assets/logos/laliga.png", "digest": "matchday",
        "aliases": ["laliga 2", "segunda divis"],
    },
    "copadelrey": {
        "label": "Copa del Rey (España, temporada actual)",
        "provider": "espn", "espn_slug": "esp.copa_del_rey", "mode": "latest",
        "scorers": "full", "name_es": "Copa del Rey", "article": "la", "tags": ["#CopaDelRey"],
        "logo": "assets/logos/laliga.png", "digest": "matchday",
        "aliases": ["copa del rey"],
    },
    "premier": {
        "label": "Premier League (Inglaterra, temporada actual)",
        "provider": "espn", "espn_slug": "eng.1", "mode": "latest", "scorers": "full",
        "name_es": "Premier League", "article": "la", "tags": ["#PremierLeague"],
        "digest": "matchday", "aliases": ["premier league"],
    },
    "seriea": {
        "label": "Serie A (Italia, temporada actual)",
        "provider": "espn", "espn_slug": "ita.1", "mode": "latest", "scorers": "full",
        "name_es": "Serie A", "article": "la", "tags": ["#SerieA"],
        "digest": "matchday", "aliases": ["serie a"],
    },
    "bundesliga": {
        "label": "Bundesliga (Alemania, temporada actual)",
        "provider": "espn", "espn_slug": "ger.1", "mode": "latest", "scorers": "full",
        "name_es": "Bundesliga", "article": "la", "tags": ["#Bundesliga"],
        "digest": "matchday", "aliases": ["bundesliga"],
    },
    "ligue1": {
        "label": "Ligue 1 (Francia, temporada actual)",
        "provider": "espn", "espn_slug": "fra.1", "mode": "latest", "scorers": "full",
        "name_es": "Ligue 1", "article": "la", "tags": ["#Ligue1"],
        "digest": "matchday", "aliases": ["ligue 1"],
    },
    "champions": {
        "label": "UEFA Champions League (temporada actual)",
        "provider": "espn", "espn_slug": "uefa.champions", "mode": "latest", "scorers": "full",
        "name_es": "Champions League", "article": "la", "tags": ["#ChampionsLeague", "#UCL"],
        "digest": "matchday", "aliases": ["champions league"],
    },
    "europa": {
        "label": "UEFA Europa League (temporada actual)",
        "provider": "espn", "espn_slug": "uefa.europa", "mode": "latest", "scorers": "full",
        "name_es": "Europa League", "article": "la", "tags": ["#EuropaLeague", "#UEL"],
        "digest": "matchday", "aliases": ["europa league"],
    },
    "conference": {
        "label": "UEFA Conference League (temporada actual)",
        "provider": "espn", "espn_slug": "uefa.europa.conf", "mode": "latest",
        "scorers": "full",
        "name_es": "Conference League", "article": "la",
        "tags": ["#ConferenceLeague", "#UECL"],
        "digest": "matchday", "aliases": ["conference league"],
    },
    "supercopa_es": {
        "label": "Supercopa de España (temporada actual)",
        "provider": "espn", "espn_slug": "esp.super_cup", "mode": "latest",
        "scorers": "full",
        "name_es": "Supercopa de España", "article": "la", "tags": ["#Supercopa"],
        "logo": "assets/logos/laliga.png",
        "digest": "daily",          # four teams over one week, each day its own
        # ESPN reports it as "Spanish Supercopa". A bare "supercopa" would also
        # swallow the Argentine and Brazilian ones, handing them these hashtags.
        "aliases": ["spanish supercopa", "supercopa de espana", "supercopa de españa"],
    },
    "supercopa_eu": {
        "label": "Supercopa de Europa (UEFA Super Cup)",
        "provider": "espn", "espn_slug": "uefa.super_cup", "mode": "latest",
        "scorers": "full",
        "name_es": "Supercopa de Europa", "article": "la",
        "tags": ["#SupercopaDeEuropa", "#UEFASuperCup"],
        "digest": "daily",          # a single match
        "aliases": ["uefa super cup", "super cup"],
    },
    # ── Selección española ──────────────────────────────────────────────
    # Three presets rather than one, because the national-team calendar rotates:
    # a Nations League autumn, then a qualifying campaign, then a tournament, and
    # friendlies in whatever gap is left. All three are configured NOW so the
    # rotation never needs a config change — a competition that is not being
    # played simply returns no fixtures.
    "naciones": {
        "label": "UEFA Nations League (selección española)",
        "provider": "espn", "espn_slug": "uefa.nations", "mode": "latest",
        "scorers": "full",
        "name_es": "Liga de Naciones", "article": "la",
        "tags": ["#SelecciónEspañola", "#NationsLeague"],
        "digest": "daily",          # all of Europe plays the same three days
        "aliases": ["nations league", "liga de naciones"],
    },
    "euroq": {
        "label": "Clasificación para la Eurocopa (selección española)",
        "provider": "espn", "espn_slug": "uefa.euroq", "mode": "latest",
        "scorers": "full",
        "name_es": "clasificación para la Eurocopa", "article": "la",
        "tags": ["#SelecciónEspañola", "#Eurocopa"],
        "digest": "daily",
        # Listed BEFORE "euro" below: ESPN names it "UEFA European Championship
        # Qualifying", which contains the shorter name, and resolve() returns the
        # first preset that matches. Reversed, every qualifier would resolve to
        # the finals and be tagged as if it were the tournament itself.
        "aliases": ["european championship qualifying", "euro qualifying"],
    },
    "euro": {
        "label": "Eurocopa (selección española)",
        "provider": "espn", "espn_slug": "uefa.euro", "mode": "today",
        "scorers": "full",
        "name_es": "Eurocopa", "article": "la",
        "tags": ["#Eurocopa", "#SelecciónEspañola"],
        "digest": "daily",          # a tournament plays every day
        "aliases": ["european championship", "eurocopa"],
    },
    "amistosos": {
        "label": "Amistosos de selecciones (selección española)",
        "provider": "espn", "espn_slug": "fifa.friendly", "mode": "latest",
        "scorers": "full",
        "name_es": "un amistoso internacional",
        "tags": ["#SelecciónEspañola", "#Amistoso"],
        "digest": "daily",
        "aliases": ["international friendly"],
    },
    "primeira": {
        "label": "Primeira Liga (Portugal, temporada actual)",
        "provider": "espn", "espn_slug": "por.1", "mode": "latest", "scorers": "full",
        "name_es": "Primeira Liga", "article": "la", "tags": ["#PrimeiraLiga"],
        "digest": "matchday", "aliases": ["primeira liga", "liga portugal"],
    },
    "eredivisie": {
        "label": "Eredivisie (Países Bajos, temporada actual)",
        "provider": "espn", "espn_slug": "ned.1", "mode": "latest", "scorers": "full",
        "name_es": "Eredivisie", "article": "la", "tags": ["#Eredivisie"],
        "digest": "matchday", "aliases": ["eredivisie"],
    },
    "ligamx": {
        "label": "Liga MX (México, temporada actual)",
        "provider": "espn", "espn_slug": "mex.1", "mode": "latest", "scorers": "full",
        "name_es": "Liga MX", "article": "la", "tags": ["#LigaMX"],
        "digest": "matchday", "aliases": ["liga mx"],
    },
    "mls": {
        "label": "MLS (EE. UU. / Canadá, temporada actual)",
        "provider": "espn", "espn_slug": "usa.1", "mode": "latest", "scorers": "full",
        "name_es": "MLS", "article": "la", "tags": ["#MLS"],
        "digest": "matchday", "aliases": ["major league soccer", "mls"],
    },
    "argentina": {
        "label": "Liga Profesional (Argentina, temporada actual)",
        "provider": "espn", "espn_slug": "arg.1", "mode": "latest", "scorers": "full",
        "name_es": "Liga Profesional argentina", "article": "la", "tags": ["#LigaProfesional"],
        "digest": "matchday", "aliases": ["liga profesional", "argentine"],
    },
    "brasileirao": {
        "label": "Brasileirão Serie A (Brasil, temporada actual)",
        "provider": "espn", "espn_slug": "bra.1", "mode": "latest", "scorers": "full",
        "name_es": "Brasileirão", "article": "el", "tags": ["#Brasileirao"],
        "digest": "matchday", "aliases": ["brasileir", "brazilian"],
    },
}

DEFAULT = "laliga"

# Fallbacks for a competition we have no preset for (a cup round the data source
# names on its own, a friendly). Keeps the pipeline running instead of stamping
# another competition's identity on the video.
_UNKNOWN = {
    "name_es": "", "tags": ["#Futbol"], "logo": "", "digest": "matchday",
    "hide_venue": False,
}


def get(key: str) -> dict:
    return COMPETITIONS.get(key, COMPETITIONS[DEFAULT])


def options() -> list[dict]:
    """List for the frontend dropdown: [{key, label, scorers}]."""
    return [{"key": k, "label": v["label"], "scorers": v["scorers"]}
            for k, v in COMPETITIONS.items()]


def resolve(competition: str) -> dict:
    """Resolve a preset from EITHER a preset key ('laliga', what a profile
    stores) OR the competition name the DATA SOURCE reports ('Spanish LALIGA',
    'FIFA World Cup'), matched on its `aliases`.

    Accepting both is what lets narrator.py and digest.py stay competition-
    agnostic. A per-match caller only ever holds a `Match`, and a Match carries
    the league name, not the preset key; a per-channel caller (a topic video,
    which has no match at all) only holds the profile's key. Anything unknown
    returns a neutral fallback rather than silently inheriting La Liga's
    hashtags.
    """
    key = (competition or "").strip()
    if key in COMPETITIONS:
        return COMPETITIONS[key]
    low = key.lower()
    if low:
        for preset in COMPETITIONS.values():
            # Whole words, not a bare substring: "Copa Amistosa" must not match
            # the alias "amistoso" and inherit another club's hashtags, and
            # "Gironina" must not match "ronin". A wrong competition here means
            # a video published under the wrong tags.
            if any(re.search(rf"\b{re.escape(a)}\b", low)
                   for a in preset.get("aliases", [])):
                return preset
    return _UNKNOWN


def key_for(competition: str) -> str:
    """Preset KEY for a competition ('champions', 'copadelrey'), or '' when it is
    not one we know.

    `resolve` answers "what IS this competition"; this answers "what do we CALL
    it internally", which is what a per-competition record filename needs — the
    keys are short, stable and already filename-safe, unlike the reported name
    ("UEFA Champions League" would have to be slugified, and would change the
    day ESPN renames it).
    """
    preset = resolve(competition)
    for key, value in COMPETITIONS.items():
        if value is preset:
            return key
    return ""


def name_es(competition: str) -> str:
    """Spanish name of the competition ('LaLiga'), WITHOUT its article, or ''
    when it is not one we know — callers then simply omit it rather than
    guess."""
    return resolve(competition).get("name_es", "")


def of_name_es(competition: str) -> str:
    """The competition as the object of "de", correctly contracted: 'de LaLiga',
    'del Mundial de Fútbol 2026', 'de la Premier League'. Returns '' for an
    unknown competition so a title can drop the clause entirely.

    Spanish contracts de+el into del, so a title cannot just concatenate a name
    and an article — 'Resumen de la jornada de Mundial' and '... de el Mundial'
    are both wrong, and this is a YouTube title the audience reads.
    """
    preset = resolve(competition)
    name = preset.get("name_es", "")
    if not name:
        return ""
    article = preset.get("article", "")
    if article == "el":
        return f"del {name}"
    if article:
        return f"de {article} {name}"
    return f"de {name}"


def tags_for(competition: str) -> list[str]:
    """Competition hashtags, most-searched first. Never empty, so callers can
    take [0] for the single lead tag."""
    return list(resolve(competition).get("tags") or _UNKNOWN["tags"])


def hides_venue(competition: str) -> bool:
    """True when the stadium must never be named (the World Cup rule)."""
    return bool(resolve(competition).get("hide_venue"))


def digest_mode(competition: str) -> str:
    """'matchday' when a round spans several days (a league jornada runs Friday
    to Monday) or 'daily' when each calendar day is its own round."""
    return resolve(competition).get("digest", "matchday")

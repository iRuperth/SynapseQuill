"""
team_visuals.py — build a FLUX prompt for a crowd in a specific team's colours.

The video backdrop should reflect the WINNING team's supporters (e.g. Brazil ->
a crowd in canary-yellow with Brazilian flags). FLUX.1-schnell follows short,
concrete colour/flag cues well but cannot render accurate crests/logos, so we
describe nationality + jersey colours + flag colours, never badges.

TEAM_PALETTE maps a team name to a short "colour + flag" descriptor. Covers the
main World Cup nations and La Liga clubs; unknown teams degrade gracefully.
A deterministic per-team seed keeps the same team looking consistent over time.
"""

import zlib

# team -> "<jersey colours>, <flag description>"
TEAM_PALETTE = {
    # ── World Cup nations ──
    "Brazil": "canary-yellow and green jerseys, Brazilian flags (green yellow blue)",
    "Argentina": "sky-blue and white striped jerseys, Argentine flags (light blue and white)",
    "France": "navy-blue jerseys, French tricolour flags (blue white red)",
    "Spain": "red jerseys, Spanish flags (red and yellow)",
    "Germany": "white jerseys, German flags (black red gold)",
    "England": "white jerseys, English flags (white with red cross)",
    "Portugal": "dark-red jerseys, Portuguese flags (green and red)",
    "Italy": "blue jerseys, Italian tricolour flags (green white red)",
    "Netherlands": "bright orange jerseys, orange and Dutch flags (red white blue)",
    "Mexico": "green jerseys, Mexican flags (green white red)",
    "United States": "white and blue jerseys, US flags (stars and stripes)",
    "USA": "white and blue jerseys, US flags (stars and stripes)",
    "Croatia": "red and white checkered jerseys, Croatian flags",
    "Belgium": "red jerseys, Belgian flags (black yellow red)",
    "Uruguay": "sky-blue jerseys, Uruguayan flags (blue white sun)",
    "Morocco": "red and green jerseys, Moroccan flags (red with green star)",
    "Japan": "blue jerseys, Japanese flags (white with red circle)",
    "South Korea": "red jerseys, South Korean flags",
    "Korea Republic": "red jerseys, South Korean flags",
    "Canada": "red jerseys, Canadian flags (red and white maple leaf)",
    "Colombia": "yellow jerseys, Colombian flags (yellow blue red)",
    "Senegal": "green and white jerseys, Senegalese flags (green yellow red)",
    "Switzerland": "red jerseys, Swiss flags (red with white cross)",
    "Poland": "white and red jerseys, Polish flags (white and red)",
    "Czechia": "red jerseys, Czech flags (white red blue)",
    "Czech Republic": "red jerseys, Czech flags (white red blue)",
    "South Africa": "yellow and green jerseys, South African flags",
    # ── World Cup 2026: remaining qualified nations ──
    "Iran": "white jerseys, Iranian flags (green white red)",
    "Australia": "gold-yellow jerseys with green, Australian flags (blue with white stars)",
    "Saudi Arabia": "green and white jerseys, Saudi flags (green with white emblem)",
    "Qatar": "maroon jerseys, Qatari flags (maroon and white)",
    "Uzbekistan": "white and sky-blue jerseys, Uzbek flags (blue white green stripes)",
    "Jordan": "white jerseys, Jordanian flags (black white green with red triangle)",
    "Iraq": "green jerseys, Iraqi flags (red white black)",
    "Ecuador": "yellow jerseys, Ecuadorian flags (yellow blue red)",
    "Paraguay": "red and white striped jerseys, Paraguayan flags (red white blue)",
    "New Zealand": "all-white jerseys, New Zealand flags (blue with red stars)",
    "Egypt": "red jerseys, Egyptian flags (red white black)",
    "Algeria": "white and green jerseys, Algerian flags (green and white with red crescent)",
    "Tunisia": "red jerseys, Tunisian flags (red with white circle)",
    "Ivory Coast": "orange jerseys, Ivorian flags (orange white green)",
    "Côte d'Ivoire": "orange jerseys, Ivorian flags (orange white green)",
    "Ghana": "white jerseys, Ghanaian flags (red gold green with black star)",
    "Cape Verde": "blue jerseys, Cape Verdean flags (blue with white and red stripes)",
    "DR Congo": "blue and red jerseys, DR Congo flags (sky-blue with red diagonal stripe)",
    "Congo DR": "blue and red jerseys, DR Congo flags (sky-blue with red diagonal stripe)",
    "Austria": "red and white jerseys, Austrian flags (red white red)",
    "Scotland": "navy-blue jerseys, Scottish flags (blue with white diagonal cross)",
    "Norway": "red jerseys with navy, Norwegian flags (red with blue and white cross)",
    "Bosnia and Herzegovina": "blue jerseys, Bosnian flags (blue with yellow triangle and white stars)",
    "Sweden": "yellow jerseys with blue, Swedish flags (blue with yellow cross)",
    "Türkiye": "red jerseys, Turkish flags (red with white crescent and star)",
    "Turkey": "red jerseys, Turkish flags (red with white crescent and star)",
    "Panama": "red jerseys, Panamanian flags (red white blue with stars)",
    "Curaçao": "blue jerseys, Curaçao flags (blue with yellow stripe and white stars)",
    "Curacao": "blue jerseys, Curaçao flags (blue with yellow stripe and white stars)",
    "Haiti": "blue and red jerseys, Haitian flags (blue and red)",
    # ── La Liga clubs ──
    "Real Madrid": "all-white jerseys, white and purple banners",
    "Barcelona": "blue and garnet (blaugrana) striped jerseys, Catalan banners",
    "Atlético Madrid": "red and white striped jerseys, red and white banners",
    "Atletico Madrid": "red and white striped jerseys, red and white banners",
    "Sevilla": "white jerseys with red, Sevilla red and white banners",
    "Real Betis": "green and white striped jerseys, green banners",
    "Villarreal": "bright yellow jerseys, yellow 'submarino amarillo' banners",
    "Valencia": "white jerseys with orange and black, Valencia banners",
    "Athletic Club": "red and white striped jerseys, Basque banners",
    "Real Sociedad": "blue and white striped jerseys, blue banners",
    "Girona": "red and white striped jerseys, red banners",
    "Rayo Vallecano": "white jerseys with a red diagonal stripe, red banners",
    "Mallorca": "red and black jerseys, red banners",
    "Osasuna": "red jerseys, red 'rojillos' banners",
    "Celta Vigo": "sky-blue jerseys, light-blue banners",
    "Getafe": "blue jerseys, blue banners",
    "Alavés": "blue and white striped jerseys, blue banners",
    "Alaves": "blue and white striped jerseys, blue banners",
    "Levante": "blue and garnet jerseys, blue banners",
    "Espanyol": "blue and white striped jerseys, blue banners",
    "Las Palmas": "yellow and blue jerseys, yellow banners",
    "Real Oviedo": "blue jerseys, blue banners",
    "Elche": "green and white jerseys, green banners",
    "Leganés": "blue and white jerseys, blue banners",
    "Leganes": "blue and white jerseys, blue banners",
    "Valladolid": "violet and white striped jerseys, violet banners",
    "Cádiz": "yellow jerseys, yellow banners",
    "Cadiz": "yellow jerseys, yellow banners",
}


# Nationality of the PEOPLE in the crowd. FLUX only renders e.g. Japanese faces
# reliably if the prompt says "Japanese fans" — flags alone ("Japanese flags")
# are a weak cue. Club supporters stay generic: their identity comes from the
# colours, and naming a club in the prompt invites its crest onto the fabric.
_DEMONYM = {
    "Brazil": "Brazilian", "Argentina": "Argentine", "France": "French",
    "Spain": "Spanish", "Germany": "German", "England": "English",
    "Portugal": "Portuguese", "Italy": "Italian", "Netherlands": "Dutch",
    "Mexico": "Mexican", "United States": "American", "USA": "American",
    "Croatia": "Croatian", "Belgium": "Belgian", "Uruguay": "Uruguayan",
    "Morocco": "Moroccan", "Japan": "Japanese", "South Korea": "South Korean",
    "Korea Republic": "South Korean", "Canada": "Canadian",
    "Colombia": "Colombian", "Senegal": "Senegalese", "Switzerland": "Swiss",
    "Poland": "Polish", "Czechia": "Czech", "Czech Republic": "Czech",
    "South Africa": "South African",
    "New Zealand": "New Zealand", "Bosnia and Herzegovina": "Bosnian",
    "DR Congo": "Congolese", "Congo DR": "Congolese",
    "Côte d'Ivoire": "Ivorian",
    "Iran": "Iranian", "Saudi Arabia": "Saudi", "Qatar": "Qatari",
    "Australia": "Australian", "Ecuador": "Ecuadorian", "Ghana": "Ghanaian",
    "Cameroon": "Cameroonian", "Nigeria": "Nigerian", "Ivory Coast": "Ivorian",
    "Tunisia": "Tunisian", "Algeria": "Algerian", "Egypt": "Egyptian",
    "Costa Rica": "Costa Rican", "Panama": "Panamanian",
    "Honduras": "Honduran", "Paraguay": "Paraguayan", "Chile": "Chilean",
    "Peru": "Peruvian", "Venezuela": "Venezuelan", "Bolivia": "Bolivian",
    "Scotland": "Scottish", "Wales": "Welsh", "Denmark": "Danish",
    "Sweden": "Swedish", "Norway": "Norwegian", "Austria": "Austrian",
    "Serbia": "Serbian", "Turkey": "Turkish", "Türkiye": "Turkish",
    "Ukraine": "Ukrainian", "Greece": "Greek", "Iceland": "Icelandic",
    "Slovakia": "Slovak", "Slovenia": "Slovenian", "Romania": "Romanian",
    "Hungary": "Hungarian", "Finland": "Finnish", "Albania": "Albanian",
    "Ireland": "Irish", "Republic of Ireland": "Irish", "Haiti": "Haitian",
    "Cape Verde": "Cape Verdean", "Curaçao": "Curaçaoan",
    "Curacao": "Curaçaoan", "Uzbekistan": "Uzbek", "Jordan": "Jordanian",
    "Iraq": "Iraqi", "United Arab Emirates": "Emirati",
}


def palette(team: str) -> str:
    """Return the colour/flag descriptor for a team, with a graceful default."""
    return TEAM_PALETTE.get(team, f"flags and banners in {team}'s team colours")


def fan_descriptor(team: str) -> str:
    """Adjective for the supporters THEMSELVES ('Japanese', 'Iranian'), so the
    generated faces match the nation. Clubs in the palette return '' (colours
    carry their identity; naming the club invites its crest). Unknown teams use
    the team name attributively ('Iran fans'), which still steers the crowd."""
    if team in _DEMONYM:
        return _DEMONYM[team]
    if team in TEAM_PALETTE:
        return ""
    return team


def team_seed(team: str) -> int:
    """Deterministic seed so the same team's crowd looks consistent over time."""
    return zlib.crc32(team.encode("utf-8")) % 1_000_000


# Appended to every prompt. FLUX renders garbled text and, worse, REAL famous
# club crests on any printed fabric (a Real Madrid badge showed up on an
# Espanyol flag). schnell follows negation poorly — naming a concept, even to
# forbid it, plants it — so the fabric is described POSITIVELY as blank, and
# the ban list avoids the exact nouns that summon football badges ("crest",
# "logo", "sponsor"); generic "symbols/emblems" cover them without naming them.
_NO_TEXT = ("every flag and every scarf is COMPLETELY BLANK plain fabric in one "
            "single solid colour, with absolutely nothing printed, painted, "
            "drawn or embroidered on it; no text, no letters, no words, no "
            "numbers, no symbols, no emblems, no drawings on any fabric, "
            "clothing or surface; no advertising boards, no advertisement "
            "hoardings, no signage, no scoreboard, no billboards; any fabric "
            "that would show a design is a blank solid colour instead")

# Frame the shot as a CLOSE-UP of the supporters in the stands, not a wide
# stadium view — we want faces, raised arms, scarves and flags filling the frame,
# never the pitch, the structure or the empty seats.
_CLOSEUP = ("tight CLOSE-UP of the supporters packed in the stands, faces and "
            "raised arms filling the whole frame, shot from within the crowd at "
            "eye level, NO view of the pitch, NO view of the field, NO stadium "
            "architecture, NO empty seats, NO wide aerial shot")


def crowd_prompt(team: str, visual_style: str, vertical: bool = True) -> str:
    """Build a FLUX prompt for a tight close-up of a team's supporters.

    Leads with the close-up framing + big SOLID flags and scarves (which FLUX
    renders cleanly) and forbids every text-bearing surface.
    """
    comp = "vertical 9:16 composition" if vertical else "wide 16:9 composition"
    dem = fan_descriptor(team)
    fans = f"ecstatic {dem} fans" if dem else "ecstatic fans"
    return (
        f"{visual_style}, photorealistic {_CLOSEUP}, {fans} at night "
        f"waving MANY large {palette(team)}, raised scarves and big plain "
        f"solid-colour flags filling the frame, colourful confetti and "
        f"streamers, no smoke, no flares, no fire, vibrant colours, {comp}, "
        f"{_NO_TEXT}"
    )


def generic_crowd_prompt(visual_style: str, vertical: bool = True) -> str:
    """Fallback prompt for draws / unknown teams: a mixed-colours supporter
    close-up (flags and shirts of several teams), no single side."""
    comp = "vertical 9:16 composition" if vertical else "wide 16:9 composition"
    return (
        f"{visual_style}, photorealistic {_CLOSEUP}, ecstatic fans at night "
        f"waving many large solid-colour flags and raised scarves in MIXED team "
        f"colours, supporters in shirts of several different teams, colourful "
        f"confetti and streamers, no smoke, no flares, no fire, vibrant "
        f"colours, {comp}, {_NO_TEXT}"
    )


# A clean, neutral celebration crowd for educational / "did you know?" videos:
# a packed stand of cheering people, NO smoke, NO flares, NO flags, NO confetti,
# NO team colours or banners — just a joyful crowd as a calm backdrop behind the
# logo + subtitles. Negations are reinforced positively (schnell follows "the
# people simply clap and cheer" better than a bare "no flags").
_EDU_CLEAN = ("the people are simply clapping, smiling and cheering with raised "
              "hands and open palms; absolutely NO flags, NO banners, NO scarves, "
              "NO confetti, NO smoke, NO flares, NO fireworks, NO pyrotechnics, "
              "no haze and no fog in the air; the air is perfectly clear; no team "
              "colours and no jerseys of any specific club or country")


def educational_crowd_prompt(visual_style: str, vertical: bool = True) -> str:
    """Backdrop for a topic/educational video: a happy crowd celebrating in the
    stands, but CLEAN — no smoke, no flags, no confetti, no team colours. Just
    people cheering, so the logo, narration and subtitles stay the focus."""
    comp = "vertical 9:16 composition" if vertical else "wide 16:9 composition"
    return (
        f"{visual_style}, photorealistic {_CLOSEUP}, a joyful crowd of ordinary "
        f"people in the stands celebrating and cheering at a sports stadium, "
        f"everyday casual clothes in neutral colours, warm even daylight, "
        f"{_EDU_CLEAN}, {comp}, {_NO_TEXT}"
    )

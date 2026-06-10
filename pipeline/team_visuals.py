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
    "South Africa": "yellow and green jerseys, South African flags",
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


def palette(team: str) -> str:
    """Return the colour/flag descriptor for a team, with a graceful default."""
    return TEAM_PALETTE.get(team, f"{team} supporters in their team colours")


def team_seed(team: str) -> int:
    """Deterministic seed so the same team's crowd looks consistent over time."""
    return zlib.crc32(team.encode("utf-8")) % 1_000_000


# Appended to every prompt. FLUX renders garbled text/letters, so forbid them as
# hard as possible AND remove every surface that invites text: NO advertising
# boards, NO printed banners, NO stadium structure. Flags/scarves must be SOLID
# single-colour blocks (a printed banner is what FLUX fills with fake letters).
_NO_TEXT = ("the flags and scarves are SOLID plain single-colour fabric with NO "
            "pattern; absolutely NO text, NO letters, NO words, NO numbers, NO "
            "writing of any kind, NO printed banners, NO painted banners, NO "
            "logos, NO crests, NO brand names, NO sponsors, NO advertising "
            "boards, NO advertisement hoardings, NO signage, NO scoreboard, NO "
            "billboards; if any fabric would show writing, make it a blank solid "
            "colour instead")

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
    return (
        f"{visual_style}, photorealistic {_CLOSEUP}, ecstatic fans at night "
        f"waving MANY large {palette(team)}, raised scarves and big solid-colour "
        f"flags filling the frame, flares and confetti, vibrant colours, "
        f"{comp}, {_NO_TEXT}"
    )


def generic_crowd_prompt(visual_style: str, vertical: bool = True) -> str:
    """Fallback prompt for draws / unknown teams: a mixed-colours supporter
    close-up (flags and shirts of several teams), no single side."""
    comp = "vertical 9:16 composition" if vertical else "wide 16:9 composition"
    return (
        f"{visual_style}, photorealistic {_CLOSEUP}, ecstatic fans at night "
        f"waving many large solid-colour flags and raised scarves in MIXED team "
        f"colours, supporters in shirts of several different teams, flares and "
        f"confetti, vibrant colours, {comp}, {_NO_TEXT}"
    )

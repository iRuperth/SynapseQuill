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


# Appended to every prompt: FLUX renders garbled text/letters, so forbid them
# strongly. Banners are described as plain colour blocks, never with words.
_NO_TEXT = ("absolutely NO text, NO letters, NO words, NO numbers, NO writing, "
            "NO banners with text, NO logos, NO crests, NO brand names, "
            "plain coloured flags and scarves only")


def crowd_prompt(team: str, visual_style: str, vertical: bool = True) -> str:
    """Build a FLUX prompt for a packed crowd in `team`'s colours."""
    comp = "vertical 9:16 composition" if vertical else "wide 16:9 composition"
    return (
        f"{visual_style}, photorealistic huge jubilant crowd of {palette(team)} "
        f"cheering in a packed stadium at night, flares and confetti, vibrant "
        f"colours, {comp}, {_NO_TEXT}"
    )


def generic_crowd_prompt(visual_style: str, vertical: bool = True) -> str:
    """Fallback prompt for draws / unknown teams (the previous generic crowd)."""
    comp = "vertical 9:16 composition" if vertical else "wide 16:9 composition"
    return (
        f"{visual_style}, photorealistic huge crowd of football fans in plain "
        f"coloured jerseys and scarves cheering in a packed stadium at night, "
        f"flares and confetti, vibrant colours, {comp}, {_NO_TEXT}"
    )

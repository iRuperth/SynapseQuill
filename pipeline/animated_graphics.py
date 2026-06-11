"""
animated_graphics.py — build ANIMATED MoviePy clips for the match video.

Instead of static cards, this renders broadcast-style motion graphics:
  - an intro scoreboard where the score counts up and team names slide in
  - a goal timeline where each scorer row slides in one after another

Everything is drawn with Pillow per frame and wrapped in MoviePy clips, so it
needs no external assets. Returns a list of clips the assembler concatenates.
"""

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from core.brand_config import BrandProfile

from .match_monitor import Match
from .video_format import REEL, VideoFormat

# The F88tball brand logo, drawn on every frame. The "-tight" copy has its empty
# transparent margins cropped off, so it reads larger at the same width. Resolved
# from the project root so it works regardless of the current working directory.
_BRAND_LOGO = Path(__file__).resolve().parent.parent / "assets" / "logos" / "f88tball-tight.png"

# Canvas size — overridable per render via set_format(). Default = reel 9:16.
W, H = REEL.width, REEL.height
_VERTICAL = True
_BG = (11, 16, 32)
_ACCENT = (45, 212, 191)
_ACCENT2 = (99, 102, 241)
_TEXT = (231, 236, 247)
_MUTED = (154, 166, 196)
_WHITE = (255, 255, 255)   # team names, league and score: pure white for clarity
_GOLD = (212, 175, 80)     # the logo's golden tone: the WINNER's score + name

# Optional crowd backdrop, composited directly into every frame (robust: no
# MoviePy masks, so no corrupt mp4s). Set via set_background().
_BACKDROP: Image.Image | None = None

# The F88tball brand logo, drawn bottom-center with a gentle pulse.
_LOGO: Image.Image | None = None

# Total clip duration (seconds), so the logo pulse has a real-time period.
_TOTAL: float = 0.0

# The brand logo sits at the TOP of the frame; the league/competition + date go
# at the very bottom.
_LOGO_AT_TOP = True


def set_format(fmt: VideoFormat) -> None:
    """Set the canvas dimensions for subsequent frames (reel vs youtube)."""
    global W, H, _VERTICAL
    W, H, _VERTICAL = fmt.width, fmt.height, fmt.vertical


def _sx(frac: float) -> int:
    """Horizontal position from a fraction of the width."""
    return int(W * frac)


def _sy(frac: float) -> int:
    """Vertical position from a fraction of the height."""
    return int(H * frac)


def _fs(frac: float) -> int:
    """Font size from a fraction of the smaller canvas dimension."""
    return max(12, int(min(W, H) * frac))


def set_background(path) -> None:
    """Load a crowd/stadium image as the darkened backdrop for all frames."""
    global _BACKDROP
    if not path:
        _BACKDROP = None
        return
    try:
        img = Image.open(path).convert("RGB").resize((W, H))
        img = ImageEnhance.Brightness(img).enhance(0.38)   # darken for legibility
        _BACKDROP = img
    except Exception:
        _BACKDROP = None


def set_logo(path) -> None:
    """Load the brand logo (PNG, ideally with transparency) drawn at the bottom
    center of every frame. Pass a falsy value or a missing file to show no logo.
    Scaled to ~42% of the frame width (big and clearly visible), keeping aspect."""
    global _LOGO
    _LOGO = None
    if not path:
        return
    try:
        logo = Image.open(path).convert("RGBA")
        # The tall reel can afford a wide logo; the short 16:9 frame needs a
        # smaller one (its width is large but its height is tight up top).
        target_w = int(W * (0.42 if _VERTICAL else 0.22))
        ratio = target_w / logo.width
        _LOGO = logo.resize((target_w, max(1, int(logo.height * ratio))))
    except Exception:
        _LOGO = None


def _paste_logo(img: Image.Image, p: float = 0.0) -> None:
    """Composite the F88tball logo at the BOTTOM CENTER with a gentle pulse: it
    softly breathes (scale) and glows brighter and back over a ~2.4s cycle, so it
    feels alive without being distracting. `p` is the clip progress (0..1).
    No-op when no logo is set."""
    if _LOGO is None:
        return
    import math

    # One full pulse every ~2.4s; phase derived from absolute time = p * total.
    # We approximate time from p using the module-level _TOTAL when available.
    t = p * (_TOTAL or 1.0)
    wave = 0.5 + 0.5 * math.sin(2 * math.pi * (t / 2.4))   # 0..1, smooth

    logo = _LOGO
    # Brightness 0.92 -> 1.18 (a soft glow up and down).
    glow = 0.92 + 0.26 * wave
    logo = ImageEnhance.Brightness(logo).enhance(glow)
    # Subtle breathing: scale 1.00 -> 1.05.
    scale = 1.0 + 0.05 * wave
    if scale != 1.0:
        nw, nh = max(1, int(_LOGO.width * scale)), max(1, int(_LOGO.height * scale))
        logo = logo.resize((nw, nh))

    margin = int(H * 0.035)
    cx = W // 2
    x = cx - logo.width // 2
    if _LOGO_AT_TOP:
        y = margin
    else:
        y = (H - margin) - logo.height
    img.alpha_composite(logo, (x, y))


def _canvas() -> Image.Image:
    """A fresh frame base: the darkened crowd, or the flat brand background."""
    if _BACKDROP is not None:
        return _BACKDROP.copy()
    return Image.new("RGB", (W, H), _BG)


def _font(size: int, bold: bool = True):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# ESPN prefixes league names with the country ("Spanish LALIGA", "English
# Premier League"). Strip that for a cleaner on-screen header.
_LEAGUE_PREFIXES = ("spanish ", "english ", "italian ", "german ", "french ",
                    "portuguese ", "dutch ", "mexican ", "argentine ", "brazilian ")


def _clean_competition(name: str) -> str:
    """Drop redundant country prefixes from a league name for the header."""
    n = (name or "").strip()
    low = n.lower()
    for pre in _LEAGUE_PREFIXES:
        if low.startswith(pre):
            return n[len(pre):].strip()
    return n


def _fmt_date(d: str) -> str:
    """Format an ISO date (YYYY-MM-DD) as DD/MM/YYYY. Pass through anything else."""
    s = (d or "").strip()[:10]
    parts = s.split("-")
    if len(parts) == 3 and all(parts):
        y, m, day = parts
        return f"{day}/{m}/{y}"
    return s


# Well-known 3-letter codes so the tags match what fans expect (RMA, ATM, BAR).
# Anything not listed falls back to the initials algorithm below.
_TEAM_ABBR = {
    "Real Madrid": "RMA", "Barcelona": "BAR", "Atlético Madrid": "ATM",
    "Atletico Madrid": "ATM", "Real Oviedo": "OVI", "Sevilla": "SEV",
    "Real Betis": "BET", "Villarreal": "VIL", "Valencia": "VAL",
    "Athletic Club": "ATH", "Real Sociedad": "RSO", "Girona": "GIR",
    "Rayo Vallecano": "RAY", "Mallorca": "MLL", "Osasuna": "OSA",
    "Celta Vigo": "CEL", "Getafe": "GET", "Alavés": "ALA", "Alaves": "ALA",
    "Levante": "LEV", "Espanyol": "ESP", "Las Palmas": "LPA", "Elche": "ELC",
    "Spain": "ESP", "Brazil": "BRA", "Argentina": "ARG", "France": "FRA",
    "Germany": "GER", "England": "ENG", "Portugal": "POR", "Italy": "ITA",
    "Netherlands": "NED", "Mexico": "MEX", "United States": "USA", "USA": "USA",
    "Croatia": "CRO", "Belgium": "BEL", "Uruguay": "URU", "Morocco": "MAR",
    "Japan": "JPN", "South Korea": "KOR", "Korea Republic": "KOR",
    "Canada": "CAN", "Colombia": "COL", "Senegal": "SEN", "Switzerland": "SUI",
}


def _side_colors(match: Match) -> tuple[tuple, tuple]:
    """(home_color, away_color) for the score + name: the WINNER is gold, the
    other side white; a draw leaves both white."""
    hg, ag = match.home_goals or 0, match.away_goals or 0
    if hg > ag:
        return _GOLD, _WHITE
    if ag > hg:
        return _WHITE, _GOLD
    return _WHITE, _WHITE


def _team_abbr(name: str) -> str:
    """A short 3-letter tag for a team (ESP, BAR, OVI) so each event row shows
    which side it belongs to. Prefers a known code, else builds one from the
    significant words."""
    if name in _TEAM_ABBR:
        return _TEAM_ABBR[name]
    words = [w for w in (name or "").replace(".", " ").split()
             if w.lower() not in {"de", "del", "la", "el", "fc", "cf", "cd", "ud", "rc"}]
    if not words:
        words = (name or "?").split() or ["?"]
    if len(words) == 1:
        return words[0][:3].upper()
    initials = "".join(w[0] for w in words)[:3].upper()
    if len(initials) < 3:
        initials = (initials + words[0][1:])[:3].upper()
    return initials


def _center(d, text, y, font, fill):
    bb = d.textbbox((0, 0), text, font=font)
    d.text(((W - (bb[2] - bb[0])) / 2, y), text, font=font, fill=fill)


def _center_at(d, text, cx, y, font, fill):
    """Draw `text` horizontally centred on x = cx."""
    bb = d.textbbox((0, 0), text, font=font)
    d.text((cx - (bb[2] - bb[0]) / 2, y), text, font=font, fill=fill)


def _ease(t: float) -> float:
    """Ease-out cubic for smooth motion (t in 0..1)."""
    return 1 - (1 - t) ** 3


_CREST_CACHE: dict[str, Image.Image | None] = {}


def _crest(url: str) -> Image.Image | None:
    """Download and cache a team crest (RGBA), resized to ~160px."""
    if not url:
        return None
    if url not in _CREST_CACHE:
        try:
            import io

            import requests
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            img.thumbnail((160, 160))
            _CREST_CACHE[url] = img
        except Exception:
            _CREST_CACHE[url] = None
    return _CREST_CACHE[url]


# ── Scoreboard clip (score counts up, names slide in) ────────────────
def _scoreboard_frame(match: Match, p: float):
    """Render one frame at progress p (0..1). Layout is proportional to W,H so
    it works for both the reel (9:16) and the YouTube (16:9) format."""
    img = _canvas().convert("RGBA")
    d = ImageDraw.Draw(img)

    # Header: real competition name + date (not hardcoded).
    if p > 0.05:
        header = _clean_competition(match.competition).upper() or "FÚTBOL"
        _center(d, header, _sy(0.16), _font(_fs(0.043)), _MUTED)
        if match.date:
            _center(d, match.date, _sy(0.20), _font(_fs(0.032)), _MUTED)

    # Team crests above each score number.
    home_crest, away_crest = _crest(match.home_logo), _crest(match.away_logo)
    home_cx, away_cx = _sx(0.30), _sx(0.70)
    if p > 0.1:
        crest_y = _sy(0.25)
        if home_crest:
            img.alpha_composite(home_crest, (home_cx - home_crest.width // 2, crest_y))
        if away_crest:
            img.alpha_composite(away_crest, (away_cx - away_crest.width // 2, crest_y))

    # Score counts up from 0 to the real score over the first 60% of the clip.
    grow = _ease(min(p / 0.6, 1.0))
    hg = round((match.home_goals or 0) * grow)
    ag = round((match.away_goals or 0) * grow)
    big = _font(_fs(0.115))
    score_y = _sy(0.345)
    _center_at(d, str(hg), home_cx, score_y, big, _ACCENT)
    _center(d, "-", _sy(0.40), _font(_fs(0.085)), _MUTED)
    _center_at(d, str(ag), away_cx, score_y, big, _ACCENT)

    # Team names fade in after the score starts counting.
    if p > 0.2:
        _center(d, match.home.upper(), _sy(0.53), _font(_fs(0.038)), _TEXT)
        _center(d, "vs", _sy(0.58), _font(_fs(0.024)), _MUTED)
        _center(d, match.away.upper(), _sy(0.615), _font(_fs(0.038)), _TEXT)

    # Accent underline grows.
    bar_w = int((W * 0.6) * _ease(min(p / 0.8, 1.0)))
    bar_y = _sy(0.69)
    d.rectangle([(W - bar_w) // 2, bar_y, (W + bar_w) // 2, bar_y + max(4, _sy(0.005))],
                fill=_ACCENT2)
    return img


def scoreboard_clip(match: Match, duration: float):
    import numpy as np
    from moviepy import VideoClip

    def make(t):
        return np.array(_scoreboard_frame(match, min(t / duration, 1.0)).convert("RGB"))

    return VideoClip(make, duration=duration)


_YELLOW = (250, 204, 21)
_RED = (239, 68, 68)


# ── Event icons (drawn, no external assets) ──────────────────────────
def _draw_card(d, x, y, w, h, color):
    """A rounded football card (yellow/red) — no letter on it."""
    r = max(2, int(min(w, h) * 0.18))
    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=color)


def _draw_ball(d, x, y, w, h):
    """A simple soccer ball: white disc with a few black pentagon-ish patches."""
    cx, cy = x + w / 2, y + h / 2
    rad = min(w, h) / 2
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
              fill=(245, 245, 245), outline=(20, 20, 20), width=max(1, int(rad * 0.12)))
    # Central pentagon + three surrounding patches, approximated as small polys.
    s = rad * 0.42
    d.polygon([(cx, cy - s), (cx + s * 0.95, cy - s * 0.3),
               (cx + s * 0.58, cy + s * 0.8), (cx - s * 0.58, cy + s * 0.8),
               (cx - s * 0.95, cy - s * 0.3)], fill=(20, 20, 20))
    for ang in (-1.9, 0.0, 1.9):
        import math
        px = cx + math.cos(ang - math.pi / 2) * rad * 0.72
        py = cy + math.sin(ang - math.pi / 2) * rad * 0.72
        d.ellipse([px - rad * 0.14, py - rad * 0.14, px + rad * 0.14, py + rad * 0.14],
                  fill=(20, 20, 20))


def _draw_event_icon(d, kind, x, y, w, h):
    """Dispatch: goal/penalty -> ball, yellow/red -> coloured card."""
    if kind in ("goal", "penalty"):
        _draw_ball(d, x, y, w, h)
    elif kind == "red":
        _draw_card(d, x, y, w, h, _RED)
    else:  # yellow
        _draw_card(d, x, y, w, h, _YELLOW)


def _minute_num(s: str) -> int:
    try:
        return int(str(s).split("+")[0])
    except ValueError:
        return 999


# ── Event timeline clip (goals + cards slide in, ordered by minute) ──
def _timeline_frame(match: Match, language: str, p: float):
    img = _canvas()
    d = ImageDraw.Draw(img)
    title = "RESUMEN" if language == "es" else "SUMMARY"
    _center(d, title, _sy(0.19), _font(_fs(0.034)), _ACCENT)

    # Merge goals and cards into a single timeline ordered by minute.
    events = []
    for g in match.goals:
        events.append((_minute_num(g.minute), g.minute, "goal", g.player))
    for c in match.cards:
        events.append((_minute_num(c.minute), c.minute, c.color.lower(), c.player))
    events.sort(key=lambda e: e[0])
    events = events[:9]

    n = len(events)
    if not n:
        return img
    reveal_each = 1.0 / n
    row_font = _font(_fs(0.028))
    box_w, box_h = _fs(0.026), _fs(0.034)
    row_h = _sy(0.062)
    y = _sy(0.28)
    for i, (_, minute, kind, player) in enumerate(events):
        local = (p - i * reveal_each) / reveal_each
        if local <= 0:
            continue
        e = _ease(min(local, 1.0))
        x = _sx(0.10) + int((1 - e) * _sx(0.26))
        shade = tuple(int(_MUTED[k] + (_TEXT[k] - _MUTED[k]) * e) for k in range(3))

        # Drawn icon: ball for a goal, coloured card for yellow/red.
        _draw_event_icon(d, kind, x, y + 4, box_w, box_h)

        d.text((x + box_w + _sx(0.02), y), f"{minute}'  {player}", font=row_font, fill=shade)
        y += row_h
    return img


def timeline_clip(match: Match, language: str, duration: float):
    import numpy as np
    from moviepy import VideoClip

    def make(t):
        return np.array(_timeline_frame(match, language, min(t / duration, 1.0)).convert("RGB"))

    return VideoClip(make, duration=duration)


# ── Unified frame: scoreboard (top) + event timeline (bottom), one screen ──
def _unified_frame(match: Match, _language: str, p: float):
    """Everything on ONE screen for the whole video: compact scoreboard at the
    top, then goals + cards revealed in chronological order below. The crowd
    backdrop is baked in, so it never disappears (single continuous clip).

    `_language` is kept for signature parity with the other clip builders even
    though the timeline title (the only localized string) was removed."""
    img = _canvas().convert("RGBA")
    d = ImageDraw.Draw(img)

    home_color, away_color = _side_colors(match)
    hg = match.home_goals or 0
    ag = match.away_goals or 0

    # The F88tball logo sits at the top (drawn by _paste_logo). Start content
    # below it so nothing overlaps. The 16:9 frame is short, so the logo band is
    # a bigger fraction of its height — leave more room below it there.
    top_pad = _sy(0.16 if _VERTICAL else 0.22)

    # Crest · SCORE · "-" · SCORE · Crest, all on ONE horizontal line (like a TV
    # broadcast scorebug). The winner's number is gold, the loser white; a draw
    # leaves both white.
    home_crest, away_crest = _crest(match.home_logo), _crest(match.away_logo)
    score_px = _sy(0.10 if _VERTICAL else 0.075)
    big = _font(score_px)
    row_cy = top_pad + score_px // 2          # vertical center of the score row

    # Lay the row out around the frame center: [crest][hg] - [ag][crest].
    gap = _sx(0.04)
    hg_s, ag_s = str(hg), str(ag)
    hg_w = d.textbbox((0, 0), hg_s, font=big)[2]
    ag_w = d.textbbox((0, 0), ag_s, font=big)[2]
    dash_font = _font(int(score_px * 0.7))
    dash_w = d.textbbox((0, 0), "-", font=dash_font)[2]
    crest_w = (home_crest.width if home_crest else 0)
    crest_w2 = (away_crest.width if away_crest else 0)
    total_w = crest_w + gap + hg_w + gap + dash_w + gap + ag_w + gap + crest_w2
    x = (W - total_w) // 2

    if home_crest:
        img.alpha_composite(home_crest, (x, int(row_cy - home_crest.height / 2)))
    x += crest_w + gap
    d.text((x, int(row_cy - score_px / 2)), hg_s, font=big, fill=home_color)
    x += hg_w + gap
    d.text((x, int(row_cy - score_px * 0.35)), "-", font=dash_font, fill=_WHITE)
    x += dash_w + gap
    d.text((x, int(row_cy - score_px / 2)), ag_s, font=big, fill=away_color)
    x += ag_w + gap
    if away_crest:
        img.alpha_composite(away_crest, (x, int(row_cy - away_crest.height / 2)))

    # Team names below the score row; the winner's name is gold too.
    names_y_px = row_cy + score_px // 2 + _sy(0.03)
    name_font = _font(_fs(0.030))
    home_n, away_n = match.home.upper(), match.away.upper()
    sep = "  -  "
    hn_w = d.textbbox((0, 0), home_n, font=name_font)[2]
    sep_w = d.textbbox((0, 0), sep, font=name_font)[2]
    an_w = d.textbbox((0, 0), away_n, font=name_font)[2]
    nx = (W - (hn_w + sep_w + an_w)) // 2
    d.text((nx, names_y_px), home_n, font=name_font, fill=home_color)
    d.text((nx + hn_w, names_y_px), sep, font=name_font, fill=_WHITE)
    d.text((nx + hn_w + sep_w, names_y_px), away_n, font=name_font, fill=away_color)

    bar_y_px = names_y_px + _sy(0.05)
    bar_w = int(W * 0.55)
    d.rectangle([(W - bar_w) // 2, bar_y_px, (W + bar_w) // 2, bar_y_px + max(4, _sy(0.004))],
                fill=_ACCENT2)
    tl_top_y = 0.46 if _VERTICAL else 0.70

    # Chronological events: goals + cards together, revealed one by one.
    events = []
    for g in match.goals:
        kind = "penalty" if "Pen" in g.kind else "goal"
        events.append((_minute_num(g.minute), g.minute, kind, g.player, g.team))
    for c in match.cards:
        events.append((_minute_num(c.minute), c.minute, c.color.lower(), c.player, c.team))
    events.sort(key=lambda e: e[0])

    # Cap the total. With many events we spill into a second column (below), so
    # ~16 fit comfortably; if there are still more, goals win over cards before
    # trimming, then re-sort chronologically.
    _MAX_EVENTS = 16
    if len(events) > _MAX_EVENTS:
        goals = [e for e in events if e[2] in ("goal", "penalty")]
        cards = [e for e in events if e[2] not in ("goal", "penalty")]
        events = sorted((goals + cards)[:_MAX_EVENTS], key=lambda e: e[0])

    if events:
        # No timeline title (removed) — the rows start right below the accent
        # bar. Keep a floor fraction so a tall score can still push them down.
        reveal_each = 1.0 / len(events)
        row_font = _font(_fs(0.026))
        box_w, box_h = _fs(0.024), _fs(0.032)
        top_y = max(bar_y_px + _sy(0.06), _sy(tl_top_y))

        # Column layout. The 16:9 frame is wide but SHORT (only ~30% of its
        # height is left for rows), so it goes two-column much sooner and the
        # reel (tall) stays single-column until the list is long. per_col then
        # bounds how tall the rows can be without running off the bottom.
        n = len(events)
        two_cols = n > (7 if _VERTICAL else 3)
        per_col = (n + 1) // 2 if two_cols else n
        col_x = [_sx(0.08), _sx(0.54)]

        # Size rows to the space available between the score block and the
        # bottom league/date strip (which starts at ~0.90), so events never
        # overlap it.
        avail = _sy(0.88) - top_y
        row_h = min(_sy(0.07), max(_sy(0.04), avail // max(per_col, 1)))

        for i, (_, minute, kind, player, team) in enumerate(events):
            local = (p - i * reveal_each) / reveal_each
            if local <= 0:
                continue
            e = _ease(min(local, 1.0))
            col = 0 if i < per_col else 1
            row = i if col == 0 else i - per_col
            base_x = col_x[col] if two_cols else _sx(0.08)
            x = base_x + int((1 - e) * _sx(0.22))
            y = top_y + row * row_h
            shade = tuple(int(_MUTED[k] + (_TEXT[k] - _MUTED[k]) * e) for k in range(3))
            _draw_event_icon(d, kind, x, y + 3, box_w, box_h)
            # Each row shows the team tag (ESP, BAR) so you can tell at a glance
            # which side the goal/card belongs to, even with the sound off.
            tag = _team_abbr(team)
            tx = x + box_w + _sx(0.018)
            d.text((tx, y), tag, font=row_font, fill=_WHITE)
            tag_w = d.textbbox((0, 0), tag, font=row_font)[2]
            d.text((tx + tag_w + _sx(0.012), y), f"{minute}'  {player}",
                   font=row_font, fill=shade)

    # League / competition + date at the very bottom (white). Date DD/MM/YYYY.
    header = _clean_competition(match.competition).upper() or "FÚTBOL"
    foot_y = _sy(0.925)
    _center(d, header, foot_y, _font(_fs(0.030)), _WHITE)
    if match.date:
        _center(d, _fmt_date(match.date), foot_y + _sy(0.04), _font(_fs(0.028)), _WHITE)

    # F88tball brand logo, pulsing, at the top.
    _paste_logo(img, p)
    return img


def unified_clip(match: Match, language: str, duration: float):
    import numpy as np
    from moviepy import VideoClip

    def make(t):
        return np.array(_unified_frame(match, language, min(t / duration, 1.0)).convert("RGB"))

    return VideoClip(make, duration=duration)


def build_animated_clips(cfg: BrandProfile, match: Match, total: float,
                         background=None) -> list:
    """Return ONE animated clip with everything on a single screen.

    A single continuous clip (no scene switch) means the crowd backdrop never
    disappears mid-video, and the marker shows score + all goals/cards together.
    """
    global _TOTAL
    _TOTAL = float(total)
    set_background(background)
    # Always brand the video with the F88tball logo (not the competition logo).
    set_logo(_BRAND_LOGO if _BRAND_LOGO.exists() else None)
    return [unified_clip(match, cfg.LANGUAGE, total)]

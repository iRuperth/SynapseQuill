"""
animated_graphics.py — build ANIMATED MoviePy clips for the match video.

Instead of static cards, this renders broadcast-style motion graphics:
  - an intro scoreboard where the score counts up and team names slide in
  - a goal timeline where each scorer row slides in one after another

Everything is drawn with Pillow per frame and wrapped in MoviePy clips, so it
needs no external assets. Returns a list of clips the assembler concatenates.
"""

import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from core.brand_config import BrandProfile

from .match_monitor import Match
from .video_format import REEL, VideoFormat

# Canvas size — overridable per render via set_format(). Default = reel 9:16.
W, H = REEL.width, REEL.height
_VERTICAL = True
_BG = (11, 16, 32)
_ACCENT = (45, 212, 191)
_ACCENT2 = (99, 102, 241)
_TEXT = (231, 236, 247)
_MUTED = (154, 166, 196)

# Optional crowd backdrop, composited directly into every frame (robust: no
# MoviePy masks, so no corrupt mp4s). Set via set_background().
_BACKDROP: Image.Image | None = None


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
        header = (match.competition or "").upper() or "FÚTBOL"
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

        # Coloured marker box: card colour, or accent for a goal.
        box_color = _YELLOW if kind == "yellow" else _RED if kind == "red" else _ACCENT
        d.rectangle([x, y + 4, x + box_w, y + box_h], fill=box_color)
        if kind != "goal":
            d.text((x + box_w * 0.25, y + 4), "R" if kind == "red" else "Y",
                   font=_font(_fs(0.022)), fill=(20, 20, 20))

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
def _unified_frame(match: Match, language: str, p: float):
    """Everything on ONE screen for the whole video: compact scoreboard at the
    top, then goals + cards revealed in chronological order below. The crowd
    backdrop is baked in, so it never disappears (single continuous clip)."""
    img = _canvas().convert("RGBA")
    d = ImageDraw.Draw(img)

    # Header.
    header = (match.competition or "").upper() or "FÚTBOL"
    _center(d, header, _sy(0.06), _font(_fs(0.034)), _MUTED)
    if match.date:
        _center(d, match.date, _sy(0.095), _font(_fs(0.024)), _MUTED)

    # Crests above the score.
    home_crest, away_crest = _crest(match.home_logo), _crest(match.away_logo)
    home_cx, away_cx = _sx(0.30), _sx(0.70)
    if home_crest:
        img.alpha_composite(home_crest, (home_cx - home_crest.width // 2, _sy(0.135)))
    if away_crest:
        img.alpha_composite(away_crest, (away_cx - away_crest.width // 2, _sy(0.135)))

    # Score counts up over the first 25% of the clip.
    grow = _ease(min(p / 0.25, 1.0))
    hg = round((match.home_goals or 0) * grow)
    ag = round((match.away_goals or 0) * grow)
    big = _font(_fs(0.095))
    _center_at(d, str(hg), home_cx, _sy(0.205), big, _ACCENT)
    _center(d, "-", _sy(0.235), _font(_fs(0.07)), _MUTED)
    _center_at(d, str(ag), away_cx, _sy(0.205), big, _ACCENT)

    # Team names + accent bar.
    _center(d, f"{match.home.upper()}  -  {match.away.upper()}",
            _sy(0.315), _font(_fs(0.028)), _TEXT)
    bar_w = int(W * 0.55)
    d.rectangle([(W - bar_w) // 2, _sy(0.365), (W + bar_w) // 2, _sy(0.365) + max(4, _sy(0.004))],
                fill=_ACCENT2)

    # Chronological events: goals + cards together, revealed one by one.
    events = []
    for g in match.goals:
        kind = "penalty" if "Pen" in g.kind else "goal"
        events.append((_minute_num(g.minute), g.minute, kind, g.player, g.team))
    for c in match.cards:
        events.append((_minute_num(c.minute), c.minute, c.color.lower(), c.player, c.team))
    events.sort(key=lambda e: e[0])
    events = events[:11]

    if events:
        _center(d, "MINUTO A MINUTO" if language == "es" else "TIMELINE",
                _sy(0.41), _font(_fs(0.026)), _ACCENT)
        reveal_each = 1.0 / len(events)
        row_font = _font(_fs(0.026))
        box_w, box_h = _fs(0.024), _fs(0.032)
        row_h = _sy(0.046)
        y = _sy(0.46)
        for i, (_, minute, kind, player, _team) in enumerate(events):
            local = (p - i * reveal_each) / reveal_each
            if local <= 0:
                continue
            e = _ease(min(local, 1.0))
            x = _sx(0.08) + int((1 - e) * _sx(0.22))
            shade = tuple(int(_MUTED[k] + (_TEXT[k] - _MUTED[k]) * e) for k in range(3))
            box_color = (_YELLOW if kind == "yellow" else _RED if kind == "red" else _ACCENT)
            d.rectangle([x, y + 3, x + box_w, y + box_h], fill=box_color)
            icon = {"yellow": "Y", "red": "R", "penalty": "P"}.get(kind, "")
            if icon:
                d.text((x + box_w * 0.28, y + 3), icon, font=_font(_fs(0.02)), fill=(20, 20, 20))
            label = f"{minute}'  {player}"
            d.text((x + box_w + _sx(0.018), y), label, font=row_font, fill=shade)
            y += row_h
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
    set_background(background)
    return [unified_clip(match, cfg.LANGUAGE, total)]

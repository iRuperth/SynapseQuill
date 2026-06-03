"""
animated_graphics.py — build ANIMATED MoviePy clips for the match video.

Instead of static cards, this renders broadcast-style motion graphics:
  - an intro scoreboard where the score counts up and team names slide in
  - a goal timeline where each scorer row slides in one after another

Everything is drawn with Pillow per frame and wrapped in MoviePy clips, so it
needs no external assets. Returns a list of clips the assembler concatenates.
"""

import os

from PIL import Image, ImageDraw, ImageFont

from core.brand_config import BrandProfile

from .match_monitor import Match

# Reels / Shorts format: vertical 9:16.
W, H = 1080, 1920
_BG = (11, 16, 32)
_ACCENT = (45, 212, 191)
_ACCENT2 = (99, 102, 241)
_TEXT = (231, 236, 247)
_MUTED = (154, 166, 196)


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
    """Render one frame at progress p (0..1)."""
    img = Image.new("RGBA", (W, H), (*_BG, 255))
    d = ImageDraw.Draw(img)

    # Vertical layout, centred for a 1080x1920 reel.
    # Header: real competition name + date (not hardcoded).
    if p > 0.05:
        header = (match.competition or "").upper() or "FÚTBOL"
        _center(d, header, 300, _font(46), _MUTED)
        if match.date:
            _center(d, match.date, 370, _font(34), _MUTED)

    # Team crests above each score number.
    home_crest, away_crest = _crest(match.home_logo), _crest(match.away_logo)
    home_cx, away_cx = int(W * 0.30), int(W * 0.70)
    if p > 0.1:
        if home_crest:
            img.alpha_composite(home_crest, (home_cx - home_crest.width // 2, 470))
        if away_crest:
            img.alpha_composite(away_crest, (away_cx - away_crest.width // 2, 470))

    # Score counts up from 0 to the real score over the first 60% of the clip.
    grow = _ease(min(p / 0.6, 1.0))
    hg = round((match.home_goals or 0) * grow)
    ag = round((match.away_goals or 0) * grow)
    big = _font(200)
    _center_at(d, str(hg), home_cx, 660, big, _ACCENT)
    _center(d, "-", 760, _font(160), _MUTED)
    _center_at(d, str(ag), away_cx, 660, big, _ACCENT)

    # Team names fade in after the score starts counting.
    if p > 0.2:
        _center(d, match.home.upper(), 1020, _font(64), _TEXT)
        _center(d, "vs", 1115, _font(40), _MUTED)
        _center(d, match.away.upper(), 1180, _font(64), _TEXT)

    # Accent underline grows.
    bar_w = int((W * 0.6) * _ease(min(p / 0.8, 1.0)))
    d.rectangle([(W - bar_w) // 2, 1330, (W + bar_w) // 2, 1340], fill=_ACCENT2)
    return img


def scoreboard_clip(match: Match, duration: float):
    import numpy as np
    from moviepy import VideoClip

    def make(t):
        return np.array(_scoreboard_frame(match, min(t / duration, 1.0)))[:, :, :3]

    def mask(t):
        # Alpha = where pixels differ from the flat background, so the graphics
        # float over the crowd backdrop instead of a solid box.
        frame = np.array(_scoreboard_frame(match, min(t / duration, 1.0)))[:, :, :3]
        diff = np.abs(frame.astype(int) - np.array(_BG)).sum(axis=2)
        return np.clip(diff / 60.0, 0, 1)

    clip = VideoClip(make, duration=duration)
    return clip.with_mask(VideoClip(mask, duration=duration, is_mask=True))


_YELLOW = (250, 204, 21)
_RED = (239, 68, 68)


def _minute_num(s: str) -> int:
    try:
        return int(str(s).split("+")[0])
    except ValueError:
        return 999


# ── Event timeline clip (goals + cards slide in, ordered by minute) ──
def _timeline_frame(match: Match, language: str, p: float):
    img = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(img)
    title = "RESUMEN" if language == "es" else "SUMMARY"
    _center(d, title, 360, _font(60), _ACCENT)

    # Merge goals and cards into a single timeline ordered by minute.
    events = []
    for g in match.goals:
        tag = "⚽" if g.kind == "Normal Goal" else ("🅿" if "Pen" in g.kind else "⚽")
        events.append((_minute_num(g.minute), g.minute, "goal", g.player, tag))
    for c in match.cards:
        events.append((_minute_num(c.minute), c.minute, c.color.lower(), c.player, None))
    events.sort(key=lambda e: e[0])
    events = events[:9]

    n = len(events)
    if not n:
        return img
    reveal_each = 1.0 / n
    y = 540
    for i, (_, minute, kind, player, _tag) in enumerate(events):
        local = (p - i * reveal_each) / reveal_each
        if local <= 0:
            continue
        e = _ease(min(local, 1.0))
        x = int(110 + (1 - e) * 280)
        shade = tuple(int(_MUTED[k] + (_TEXT[k] - _MUTED[k]) * e) for k in range(3))

        # Coloured marker box: card colour, or accent for a goal.
        box_color = _YELLOW if kind == "yellow" else _RED if kind == "red" else _ACCENT
        d.rectangle([x, y + 6, x + 46, y + 64], fill=box_color)
        icon = "⚽" if kind == "goal" else ("R" if kind == "red" else "Y")
        if kind != "goal":
            d.text((x + 12, y + 8), icon, font=_font(40), fill=(20, 20, 20))

        d.text((x + 70, y), f"{minute}'  {player}", font=_font(50), fill=shade)
        y += 120
    return img


def timeline_clip(match: Match, language: str, duration: float):
    import numpy as np
    from moviepy import VideoClip

    def make(t):
        return np.array(_timeline_frame(match, language, min(t / duration, 1.0)))[:, :, :3]

    def mask(t):
        frame = np.array(_timeline_frame(match, language, min(t / duration, 1.0)))[:, :, :3]
        diff = np.abs(frame.astype(int) - np.array(_BG)).sum(axis=2)
        return np.clip(diff / 60.0, 0, 1)

    clip = VideoClip(make, duration=duration)
    return clip.with_mask(VideoClip(mask, duration=duration, is_mask=True))


def build_animated_clips(cfg: BrandProfile, match: Match, total: float) -> list:
    """Return animated MoviePy clips spanning `total` seconds."""
    if match.goals:
        sb = total * 0.45
        tl = total - sb
        return [scoreboard_clip(match, sb), timeline_clip(match, cfg.LANGUAGE, tl)]
    return [scoreboard_clip(match, total)]

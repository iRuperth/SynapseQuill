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


def _ease(t: float) -> float:
    """Ease-out cubic for smooth motion (t in 0..1)."""
    return 1 - (1 - t) ** 3


# ── Scoreboard clip (score counts up, names slide in) ────────────────
def _scoreboard_frame(match: Match, p: float):
    """Render one frame at progress p (0..1)."""
    img = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(img)

    # Vertical layout, centred for a 1080x1920 reel.
    if p > 0.05:
        _center(d, "FIFA WORLD CUP", 380, _font(48), _MUTED)

    # Score counts up from 0 to the real score over the first 60% of the clip.
    grow = _ease(min(p / 0.6, 1.0))
    hg = round((match.home_goals or 0) * grow)
    ag = round((match.away_goals or 0) * grow)
    _center(d, f"{hg}   -   {ag}", 720, _font(220), _ACCENT)

    # Team names fade in after the score starts counting.
    if p > 0.2:
        _center(d, match.home.upper(), 1020, _font(72), _TEXT)
        _center(d, "vs", 1125, _font(40), _MUTED)
        _center(d, match.away.upper(), 1195, _font(72), _TEXT)

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


# ── Goal timeline clip (each scorer slides in) ───────────────────────
def _timeline_frame(match: Match, language: str, p: float):
    img = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(img)
    title = "GOLES" if language == "es" else "GOALS"
    _center(d, title, 380, _font(64), _ACCENT)

    goals = match.goals[:8]
    n = len(goals)
    if not n:
        return img
    # Reveal goals one by one across the clip.
    reveal_each = 1.0 / n
    y = 560
    for i, g in enumerate(goals):
        start = i * reveal_each
        local = (p - start) / reveal_each
        if local <= 0:
            continue
        local = min(local, 1.0)
        e = _ease(local)
        x = int(120 + (1 - e) * 300)          # slide in from the right
        # Fade via colour interpolation toward full text colour.
        shade = tuple(int(_MUTED[k] + (_TEXT[k] - _MUTED[k]) * e) for k in range(3))
        extra = "" if g.kind == "Normal Goal" else f"  ({g.kind})"
        d.text((x, y), f"{g.minute}'  {g.player}{extra}", font=_font(52), fill=shade)
        y += 130
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

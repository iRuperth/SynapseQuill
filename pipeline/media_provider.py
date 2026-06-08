"""
media_provider.py — build the visuals for a match video, combining free,
copyright-safe sources. Selected per profile via MEDIA_SOURCES.

    stock     real team crests/flags (TheSportsDB, free) + optional Pexels stadium
    graphics  data cards rendered with Pillow: scoreboard + goal timeline
    flux      AI ambience/cover via image_generator (Pollinations FLUX, free)

Returns an ordered list of image file paths to be turned into a slideshow.
Real match video clips are intentionally NOT used (FIFA copyright -> strikes).
"""

import os
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from core.brand_config import BrandProfile

from .image_generator import generate_image
from .match_monitor import Match

W, H = 1280, 720
_BG = (11, 16, 32)
_ACCENT = (45, 212, 191)
_TEXT = (231, 236, 247)
_MUTED = (154, 166, 196)


# ── Fonts ────────────────────────────────────────────────────────────
def _font(size: int):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _centered(draw, text, y, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text(((W - w) / 2, y), text, font=font, fill=fill)


# ── stock: real crests / flags ───────────────────────────────────────
def _download(url: str, dest: Path) -> Path | None:
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return dest
    except Exception:
        return None


def _stock_images(cfg: BrandProfile, match: Match, out: Path) -> list[Path]:
    """Real team logos from the API-Football CDN (already in the match data)."""
    paths = []
    for label, url in (("home", match.home_logo), ("away", match.away_logo)):
        if url:
            p = _download(url, out / f"logo_{label}.png")
            if p:
                paths.append(p)
    return paths


# ── graphics: scoreboard + goal timeline (Pillow) ────────────────────
def _scoreboard(cfg: BrandProfile, match: Match, out: Path,
                logos: list[Path]) -> Path:
    img = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(img)

    _centered(d, "FIFA WORLD CUP 2026", 60, _font(34), _MUTED)
    # Score
    _centered(d, f"{match.home_goals}  -  {match.away_goals}", 230, _font(150), _ACCENT)
    # Team names
    _centered(d, match.home.upper(), 420, _font(56), _TEXT)
    _centered(d, "vs", 490, _font(34), _MUTED)
    _centered(d, match.away.upper(), 540, _font(56), _TEXT)
    if match.venue:
        _centered(d, match.venue, 650, _font(26), _MUTED)

    # Paste crests if available
    for i, lp in enumerate(logos[:2]):
        try:
            crest = Image.open(lp).convert("RGBA").resize((120, 120))
            x = 200 if i == 0 else W - 320
            img.paste(crest, (x, 250), crest)
        except Exception:
            pass

    dest = out / "scoreboard.png"
    img.save(dest)
    return dest


def _goal_timeline(cfg: BrandProfile, match: Match, out: Path) -> Path | None:
    if not match.goals:
        return None
    img = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(img)
    _centered(d, "GOLES" if cfg.LANGUAGE == "es" else "GOALS", 50, _font(48), _ACCENT)
    y = 160
    for g in match.goals[:8]:
        line = f"{g.minute}'   {g.player}   ({g.team})"
        d.text((180, y), line, font=_font(40), fill=_TEXT)
        y += 64
    dest = out / "timeline.png"
    img.save(dest)
    return dest


# ── flux: AI ambience cover ──────────────────────────────────────────
def _flux_cover(cfg: BrandProfile, match: Match, out: Path,
                on_step) -> Path | None:
    prompt = (
        f"{cfg.VISUAL_STYLE}, packed football stadium at night, dramatic crowd, "
        f"World Cup atmosphere, celebration, no text, no faces, wide cinematic shot"
    )
    try:
        data = generate_image(prompt, provider=cfg.IMAGE_PROVIDER, width=W, height=H)
        dest = out / "ambience.png"
        dest.write_bytes(data)
        return dest
    except Exception as e:  # noqa: BLE001
        on_step("media", f"FLUX ambience skipped ({e})")
        return None


# ── orchestrator ─────────────────────────────────────────────────────
def build_visuals(cfg: BrandProfile, match: Match, *, on_step=lambda *_: None) -> list[Path]:
    """Return ordered image paths for the slideshow, per cfg.MEDIA_SOURCES."""
    out = cfg.IMAGE_DIR / f"match_{match.fixture_id}"
    out.mkdir(parents=True, exist_ok=True)

    logos = _stock_images(cfg, match, out) if "stock" in cfg.MEDIA_SOURCES else []
    images: list[Path] = []

    # Cover first (ambience), then data cards.
    if "flux" in cfg.MEDIA_SOURCES:
        cover = _flux_cover(cfg, match, out, on_step)
        if cover:
            images.append(cover)

    if "graphics" in cfg.MEDIA_SOURCES:
        images.append(_scoreboard(cfg, match, out, logos))
        tl = _goal_timeline(cfg, match, out)
        if tl:
            images.append(tl)

    # Fallback: always have at least the scoreboard so a video can be built.
    if not images:
        images.append(_scoreboard(cfg, match, out, logos))

    on_step("media", f"Built {len(images)} visuals")
    return images

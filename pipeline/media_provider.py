"""
media_provider.py — supply the optional FLUX ambience cover for the video.

The scoreboard and goal timeline are now ANIMATED MoviePy clips built in
animated_graphics.py. This module only generates an AI ambience image (stadium,
crowd, celebration) used as a brief vertical intro/cover behind a fade. It stays
copyright-safe (no real clips) and is skipped gracefully if image generation is
unavailable.

Selected per profile via MEDIA_SOURCES (only "flux" is handled here now).
"""

from pathlib import Path

from core.brand_config import BrandProfile

from .image_generator import generate_image
from .match_monitor import Match

# Reels / Shorts format: vertical 9:16 (matches video_assembler).
W, H = 1080, 1920


def _flux_cover(cfg: BrandProfile, match: Match, out: Path, on_step) -> Path | None:
    prompt = (
        f"{cfg.VISUAL_STYLE}, huge crowd of football fans wearing team jerseys and "
        "scarves cheering in a packed stadium at night, flares and confetti, vibrant "
        "colours, energetic celebration, vertical composition, no readable text"
    )
    try:
        data = generate_image(prompt, provider=cfg.IMAGE_PROVIDER, width=W, height=H)
        dest = out / "ambience.png"
        dest.write_bytes(data)
        return dest
    except Exception as e:  # noqa: BLE001
        on_step("media", f"FLUX ambience skipped ({e})")
        return None


def build_visuals(cfg: BrandProfile, match: Match, *, on_step=lambda *_: None) -> list[Path]:
    """Return ambience image paths (filename contains 'ambience') for the intro."""
    out = cfg.IMAGE_DIR / f"match_{match.fixture_id}"
    out.mkdir(parents=True, exist_ok=True)

    images: list[Path] = []
    if "flux" in cfg.MEDIA_SOURCES:
        cover = _flux_cover(cfg, match, out, on_step)
        if cover:
            images.append(cover)

    on_step("media", f"Built {len(images)} ambience visual(s)")
    return images

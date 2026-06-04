"""
media_provider.py — generate the crowd backdrop(s) for a match video.

The backdrop reflects the WINNING team's supporters (e.g. Brazil -> a crowd in
canary-yellow with Brazilian flags). On a draw it generates TWO crowds, one per
team. The scoreboard and goal timeline are animated separately
(animated_graphics.py); this only supplies the AI crowd image(s).

Copyright-safe (no real clips, no crests). Skipped gracefully if image
generation is unavailable. Enabled per profile via MEDIA_SOURCES ("flux").
"""

from pathlib import Path

from core.brand_config import BrandProfile

from .image_generator import generate_image
from .match_monitor import Match
from .team_visuals import crowd_prompt, generic_crowd_prompt
from .video_format import REEL, VideoFormat


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name)[:40] or "team"


def _gen_crowd(cfg: BrandProfile, team: str | None, out: Path, fmt: VideoFormat,
               on_step) -> Path | None:
    """Generate one crowd image (team-coloured if a team is given)."""
    if team:
        prompt = crowd_prompt(team, cfg.VISUAL_STYLE, vertical=fmt.vertical)
        dest = out / f"ambience_{_safe(team)}.png"
    else:
        prompt = generic_crowd_prompt(cfg.VISUAL_STYLE, vertical=fmt.vertical)
        dest = out / "ambience_generic.png"
    try:
        data = generate_image(prompt, provider=cfg.IMAGE_PROVIDER,
                              width=fmt.width, height=fmt.height)
        dest.write_bytes(data)
        return dest
    except Exception as e:  # noqa: BLE001
        on_step("media", f"FLUX crowd skipped for {team or 'generic'} ({e})")
        return None


def build_visuals(cfg: BrandProfile, match: Match, *, fmt: VideoFormat = REEL,
                  on_step=lambda *_: None) -> list[Path]:
    """Return crowd backdrop path(s): the winner's crowd, or both teams on a draw.

    The first path is the primary backdrop used behind the whole video; on a
    draw the second is available for digests that want to alternate.
    """
    out = cfg.IMAGE_DIR / f"match_{match.fixture_id}"
    out.mkdir(parents=True, exist_ok=True)

    images: list[Path] = []
    if "flux" in cfg.MEDIA_SOURCES:
        if match.is_draw:
            for team in (match.home, match.away):
                img = _gen_crowd(cfg, team, out, fmt, on_step)
                if img:
                    images.append(img)
        else:
            img = _gen_crowd(cfg, match.winner, out, fmt, on_step)
            if img:
                images.append(img)

    on_step("media", f"Built {len(images)} crowd backdrop(s)")
    return images

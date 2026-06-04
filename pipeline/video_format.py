"""
video_format.py — output format presets (reel vs YouTube).

Keeps the canvas size and orientation in one place so media_provider,
animated_graphics and video_assembler all render to the same dimensions.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoFormat:
    key: str
    width: int
    height: int

    @property
    def vertical(self) -> bool:
        return self.height >= self.width


REEL = VideoFormat("reel", 1080, 1920)        # 9:16 vertical short
YOUTUBE = VideoFormat("youtube", 1920, 1080)  # 16:9 horizontal

_FORMATS = {"reel": REEL, "youtube": YOUTUBE}


def get_format(key: str | None) -> VideoFormat:
    return _FORMATS.get((key or "reel").lower(), REEL)

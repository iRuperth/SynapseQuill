"""
content_generator.py — generate ready-to-publish social/blog text for a match.

Covers the briefing's multi-platform requirement: blog post, Twitter/X,
Instagram and LinkedIn, each respecting its length/voice, in the profile's
language, with the brand/persona system_preamble prepended to every prompt.

The LLM is constrained to the match facts to avoid inventing data.
"""

from core.brand_config import BrandProfile
from core.llm import call_llm

from .match_monitor import Match
from .narrator import _facts_block

_LANG = {"es": "Spanish", "en": "English", "fr": "French", "it": "Italian"}

# Per-platform writing brief (constraints the model must honour).
_PLATFORMS = {
    "blog": "An SEO-friendly blog post of 250-400 words with a catchy H1 title "
            "and 2-3 short paragraphs. Include relevant keywords naturally.",
    "twitter": "A single tweet, MAX 280 characters, punchy, with 2-3 hashtags.",
    "instagram": "An Instagram caption, up to ~150 words, vivid and emotional, "
                 "with 5-8 hashtags on the last line.",
    "linkedin": "A professional LinkedIn post, ~120 words, insightful and "
                "respectful in tone, 3-4 hashtags.",
}


def generate_platform(cfg: BrandProfile, match: Match, platform: str,
                      *, provider: str | None = None) -> str:
    """Generate text for one platform."""
    if platform not in _PLATFORMS:
        raise ValueError(f"Unknown platform '{platform}'. Choose {list(_PLATFORMS)}.")
    lang = _LANG.get(cfg.LANGUAGE, "Spanish")

    system = (cfg.system_preamble + "\n\n" if cfg.system_preamble else "") + (
        f"You write {platform} content in {lang}. {_PLATFORMS[platform]} "
        "Use ONLY the given match facts — never invent scorers, minutes or scores. "
        "Output only the post text, no extra commentary."
    )
    user = f"Match facts:\n{_facts_block(match)}"
    return call_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        provider=provider or cfg.LLM_PROVIDER, max_tokens=700, label=f"Content-{platform}",
    )


def generate_all(cfg: BrandProfile, match: Match, platforms: list[str] | None = None,
                 *, provider: str | None = None) -> dict[str, str]:
    """Generate text for several platforms. Returns {platform: text}."""
    platforms = platforms or list(_PLATFORMS)
    return {p: generate_platform(cfg, match, p, provider=provider) for p in platforms}

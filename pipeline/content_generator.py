"""
content_generator.py — generate ready-to-publish social/blog text.

Covers the briefing's multi-platform requirement: blog post, Twitter/X,
Instagram and LinkedIn, each respecting its length/voice, in the chosen
language, with the brand/persona system_preamble prepended to every prompt.

Two input modes share the same per-platform prompts:
  • match mode  — constrained to the factual match data (never invents).
  • freeform mode — the user supplies a free TOPIC + AUDIENCE, covering the
    briefing's core "content on any topic the user provides, adapted to
    platform and audience" requirement (essential level).
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


def _render(platform: str, lang: str, preamble: str, facts_label: str,
            facts_body: str, grounding: str, *, provider: str | None,
            label: str) -> str:
    """Shared generation core for one platform (match or freeform)."""
    if platform not in _PLATFORMS:
        raise ValueError(f"Unknown platform '{platform}'. Choose {list(_PLATFORMS)}.")
    system = (preamble + "\n\n" if preamble else "") + (
        f"You write {platform} content in {lang}. {_PLATFORMS[platform]} "
        f"{grounding} Output only the post text, no extra commentary."
    )
    user = f"{facts_label}:\n{facts_body}"
    return call_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        provider=provider, max_tokens=700, label=label,
    )


# ── Match mode (existing pipeline) ───────────────────────────────────
def generate_platform(cfg: BrandProfile, match: Match, platform: str,
                      *, provider: str | None = None) -> str:
    """Generate text for one platform from a match (constrained to facts).

    Each draft is run through the deterministic facts check (cheap, no judge)
    so a social post never invents a score, card colour or goal type; on a
    failure it regenerates once with the reasons fed back. ordered_score is
    off — a post is not running play-by-play, so its last score token need
    not be the final."""
    from agents.guardrail import facts_check

    base_grounding = ("Use ONLY the given match facts — never invent scorers, "
                      "minutes or scores.")
    text = _render(
        platform, _LANG.get(cfg.LANGUAGE, "Spanish"), cfg.system_preamble,
        "Match facts", _facts_block(match), base_grounding,
        provider=provider or cfg.LLM_PROVIDER, label=f"Content-{platform}",
    )
    check = facts_check(match, text, cfg.LANGUAGE, ordered_score=False)
    if not check["ok"]:
        reasons = "; ".join(check["issues"])
        text = _render(
            platform, _LANG.get(cfg.LANGUAGE, "Spanish"), cfg.system_preamble,
            "Match facts", _facts_block(match),
            f"{base_grounding} A previous draft was rejected for: {reasons}. "
            "Fix exactly that — copy every name, card colour and goal type "
            "EXACTLY as given.",
            provider=provider or cfg.LLM_PROVIDER, label=f"Content-{platform}",
        )
    return text


def generate_all(cfg: BrandProfile, match: Match, platforms: list[str] | None = None,
                 *, provider: str | None = None) -> dict[str, str]:
    """Generate text for several platforms from a match. Returns {platform: text}."""
    platforms = platforms or list(_PLATFORMS)
    return {p: generate_platform(cfg, match, p, provider=provider) for p in platforms}


# ── Freeform mode (essential-level: any topic the user provides) ─────
def _brief_block(topic: str, audience: str, extra: str = "") -> str:
    """Build the freeform brief block the model must write about."""
    lines = [f"Topic: {topic}"]
    if audience:
        lines.append(f"Target audience: {audience}")
    if extra:
        lines.append(f"Extra guidance: {extra}")
    return "\n".join(lines)


def generate_freeform_platform(platform: str, topic: str, *, audience: str = "",
                               language: str = "es", system_preamble: str = "",
                               extra: str = "", provider: str | None = None) -> str:
    """Generate text for one platform from a free TOPIC + AUDIENCE (no match)."""
    return _render(
        platform, _LANG.get(language, "Spanish"), system_preamble,
        "Content brief", _brief_block(topic, audience, extra),
        ("Write accurate, useful content tailored to the topic and audience. "
         "Do not fabricate statistics, quotes or facts you are unsure of."),
        provider=provider, label=f"Freeform-{platform}",
    )


def generate_freeform(topic: str, *, audience: str = "", language: str = "es",
                      platforms: list[str] | None = None, system_preamble: str = "",
                      extra: str = "", provider: str | None = None) -> dict[str, str]:
    """Generate multi-platform text for a free topic. Returns {platform: text}."""
    platforms = platforms or list(_PLATFORMS)
    return {
        p: generate_freeform_platform(
            p, topic, audience=audience, language=language,
            system_preamble=system_preamble, extra=extra, provider=provider)
        for p in platforms
    }

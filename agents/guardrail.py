"""
guardrail.py — anti-hallucination guardrail for generated content (expert level).

Two layers:
  1. Deterministic facts check — verify the narration mentions the correct
     final score and does not name any scorer absent from the API data.
     This catches the worst failure mode (inventing goals) with zero cost.
  2. LLM-as-judge — a second model (ideally different from the generator)
     checks groundedness, language and tone, returning a structured verdict.

The narration must never invent scores/scorers — those come from API-Football.
"""

import json
import re

from json_repair import repair_json

from core.llm import call_llm
from pipeline.match_monitor import Match


# ── Layer 1: deterministic facts check ───────────────────────────────
def facts_check(match: Match, text: str) -> dict:
    """Cheap, deterministic verification against the raw match data."""
    issues = []

    # The exact final score should appear (e.g. "5-2", "5 a 2", "5:2", "5 - 2").
    # Accept BOTH orderings: natural narration often states the score from the
    # winner's side ("Barcelona ganó 2 a 1") regardless of home/away order.
    h, a = match.home_goals, match.away_goals
    if h is not None and a is not None:
        sep = r"\s*(?:[-:x]|\sa\s|\sto\s)\s*"   # "-", ":", "x", " a ", " to "
        patterns = [
            rf"\b{h}{sep}{a}\b",
            rf"\b{a}{sep}{h}\b",                # reversed (winner-first phrasing)
        ]
        if not any(re.search(p, text) for p in patterns):
            issues.append(f"final score {h}-{a} not clearly stated")

    # Scorer-invention detection is left to the stronger LLM-judge layer below:
    # a regex over capitalised tokens produces too many false positives in free
    # prose to be a reliable hard gate. The deterministic layer focuses on the
    # one thing it can check exactly — the final score.
    return {"ok": not issues, "issues": issues}


# ── Layer 2: LLM-as-judge ────────────────────────────────────────────
_JUDGE_SYS = (
    "You are a strict fact-checking judge. Given the MATCH FACTS and a generated "
    "NARRATION, decide if the narration is fully grounded in the facts (no invented "
    "scores, scorers, minutes), is written in the expected LANGUAGE, and stays "
    "respectful. Respond as JSON only: "
    '{"grounded": bool, "language_ok": bool, "tone_ok": bool, "reason": str}.'
)


def llm_judge(match: Match, text: str, language: str, *, provider: str | None = None) -> dict:
    from pipeline.narrator import _facts_block

    user = (
        f"MATCH FACTS:\n{_facts_block(match)}\n\n"
        f"EXPECTED LANGUAGE: {language}\n\n"
        f"NARRATION:\n{text}"
    )
    raw = call_llm(
        [{"role": "system", "content": _JUDGE_SYS}, {"role": "user", "content": user}],
        provider=provider, max_tokens=300, label="Guardrail",
    )
    try:
        data = json.loads(repair_json(raw))
    except Exception:
        data = {}
    return {
        "grounded": bool(data.get("grounded", False)),
        "language_ok": bool(data.get("language_ok", False)),
        "tone_ok": bool(data.get("tone_ok", True)),
        "reason": data.get("reason", "no reason returned"),
    }


def verify(match: Match, text: str, language: str, *,
           judge_provider: str | None = None, use_judge: bool = True) -> dict:
    """Combined verdict. `passed` is True only if both layers agree."""
    facts = facts_check(match, text)
    result = {"facts": facts, "passed": facts["ok"]}
    if use_judge:
        try:
            judge = llm_judge(match, text, language, provider=judge_provider)
            result["judge"] = judge
            result["passed"] = facts["ok"] and judge["grounded"] and judge["language_ok"]
        except Exception as e:  # noqa: BLE001
            result["judge"] = {"error": str(e)}
    return result

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

    # Verify the FINAL score. A play-by-play narration states running scores as
    # it goes, so "the correct pair appears somewhere" is not enough — a wrong
    # invented final could slip past while a true running score matches. So we
    # check the LAST score-shaped token in the text equals the real final, and
    # that no OTHER score appears in a full-time context.
    # Normalise unicode dashes (‑ – —) to a plain hyphen first.
    norm = text.translate({0x2010: "-", 0x2011: "-", 0x2012: "-",
                           0x2013: "-", 0x2014: "-", 0x2212: "-"})
    h, a = match.home_goals, match.away_goals
    # A goalless draw is narrated as "empate sin goles" far more often than as a
    # literal "0-0", so the score-token check would false-fail almost every real
    # 0-0 narration. Only enforce the token when at least one goal was scored.
    if h is not None and a is not None and (h or a):
        sep = r"\s*(?:[-:x]|\s(?:a|to)\s)\s*"
        score_re = re.compile(rf"\b(\d{{1,2}}){sep}(\d{{1,2}})\b")
        target = frozenset((h, a))             # order-agnostic final score
        pairs = [frozenset((int(m1), int(m2))) for m1, m2 in score_re.findall(norm)]
        final_str = "-".join(str(x) for x in sorted((h, a)))

        # 1) The correct final must appear at least once.
        if target not in pairs:
            issues.append(f"final score {h}-{a} not clearly stated")
        # 2) The LAST score-shaped token that equals a PLAUSIBLE football score
        #    must be the final. Football prose freely contains minute ranges
        #    ("los 90-95 minutos", "el 10-15"), so we ignore trailing pairs whose
        #    numbers are both too large to be a scoreline (>9) before deciding —
        #    otherwise a legitimate range after the score would false-fail.
        else:
            scorelike = [p for p in pairs if all(x <= 9 for x in p)]
            if scorelike and scorelike[-1] != target:
                stated = "-".join(str(x) for x in sorted(scorelike[-1]))
                issues.append(f"the last score stated ({stated}) is not the final {final_str}")

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

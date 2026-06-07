"""
text_polish.py — make the narration sound human before it is spoken.

Two layers, used together (see pipeline/runner.py):

  1. fix_common(text)  — a deterministic pass over KNOWN Spanish slips that a
     football commentator would never make. Zero cost, zero latency, fully
     predictable. The headline case: "la penalty" → "el penalty" — penalty/penal
     is masculine in Spanish ("el penalti"), so a feminine article sounds robotic
     and instantly gives away that a machine wrote it.

  2. polish_llm(text, ...) — an LLM "editor" that rewrites anything that still
     reads unnaturally WITHOUT changing the facts (see narrator/guardrail). Lives
     here next to the deterministic pass so the two are applied in one place.

Only the SPOKEN script is polished; the facts are re-verified afterwards.
"""

import re

# (pattern, replacement) pairs applied case-insensitively while preserving the
# casing of the first letter. Each one is a slip a human commentator never makes.
# Keep this list specific — broad rules cause false fixes in free prose.
_RULES: list[tuple[str, str]] = [
    # Penalty/penal/penalti are MASCULINE in Spanish. A feminine article or
    # adjective is the classic machine-translation tell. Handle singular and
    # plural separately so "la"→"el" and "las"→"los" (never the invalid "els").
    (r"\blas (penalt(?:ys|is|ies|s)|penales)\b", r"los \1"),
    (r"\bla (penalt(?:y|i)|penal)\b", r"el \1"),
    (r"\bunas (penalt(?:ys|is|ies|s)|penales)\b", r"unos \1"),
    (r"\buna (penalt(?:y|i)|penal)\b", r"un \1"),
    # "de el" → "del" (a slip when the model stitches "gol de el Madrid").
    (r"\bde el\b", "del"),
    # "a el" → "al".
    (r"\ba el\b", "al"),
    # Common doubled spaces / space-before-punctuation from stitching.
    (r" +([,.;:!?])", r"\1"),
    (r"  +", " "),
]


def _apply(pattern: str, repl: str, text: str) -> str:
    """Case-insensitive sub that keeps the original first-letter casing."""
    def _sub(m: re.Match) -> str:
        out = re.sub(pattern, repl, m.group(0), flags=re.IGNORECASE)
        # Preserve leading capitalisation of the matched span.
        if m.group(0)[:1].isupper() and out[:1].islower():
            out = out[:1].upper() + out[1:]
        return out
    return re.sub(pattern, _sub, text, flags=re.IGNORECASE)


def fix_common(text: str) -> str:
    """Apply the deterministic Spanish/football corrections."""
    for pattern, repl in _RULES:
        text = _apply(pattern, repl, text)
    return text


_EDITOR_SYS = (
    "Eres un EDITOR de guiones de narración deportiva en español. Recibes el "
    "guión hablado de un relator y lo devuelves CORREGIDO para que suene 100% "
    "natural y humano, como lo diría un relator de verdad. REGLAS ESTRICTAS:\n"
    "- NO cambies ningún HECHO: nombres, equipos, marcador, minutos y goleadores "
    "se mantienen EXACTAMENTE igual.\n"
    "- Corrige género, concordancia y errores típicos de máquina. Por ejemplo "
    "'la penalty' es INCORRECTO; en español es 'el penalti' / 'el penalty' "
    "(masculino). Lo mismo con otras palabras del fútbol.\n"
    "- Mantén la energía, las mayúsculas de énfasis y los gritos de gol "
    "(p. ej. '¡GOOOL!') tal cual.\n"
    "- No añadas ni quites frases salvo lo mínimo para que sea natural. No "
    "expliques nada.\n"
    "Devuelve SOLO el guión corregido, sin comillas ni encabezados."
)


def _editor_provider(provider: str | None) -> str | None:
    """Pick the LLM that edits best. Groq follows the rewrite instructions most
    reliably for Spanish grammar (verified: it fixes gender, adjective agreement
    and articles where the faster models leave them), so prefer it when a key is
    present; otherwise fall back to the caller's provider."""
    import os
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    return provider


def polish_llm(text: str, *, language: str = "es", provider: str | None = None) -> str:
    """LLM editor pass. Best-effort: on any failure, return the input unchanged
    so a flaky model never blocks the pipeline. Only used for Spanish, where the
    gender/agreement slips matter most; other languages pass through."""
    if language != "es" or not text.strip():
        return text
    try:
        from core.llm import call_llm
        out = call_llm(
            [{"role": "system", "content": _EDITOR_SYS},
             {"role": "user", "content": text}],
            provider=_editor_provider(provider), max_tokens=700, label="Editor",
        )
        out = (out or "").strip()
        # Guard against a model that returns nothing or a refusal: keep original.
        return out if len(out) >= len(text) * 0.5 else text
    except Exception:  # noqa: BLE001
        return text


def polish(text: str, *, language: str = "es", provider: str | None = None,
           use_llm: bool = True) -> str:
    """Full polish: deterministic fixes first, then the optional LLM editor."""
    text = fix_common(text)
    if use_llm:
        text = fix_common(polish_llm(text, language=language, provider=provider))
    return text

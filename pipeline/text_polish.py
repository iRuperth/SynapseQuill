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


# A card narrated TWICE in one breath ("le dan la tarjeta y el árbitro le muestra
# la tarjeta") is the redundancy the prompt keeps slipping on. This collapses the
# DOUBLED mention to the first clause. Deliberately tight — the two card verbs
# must be adjacent (only a connector / optional "el árbitro" between them), so a
# second player's later card ("...y al 22 López ve la amarilla") is NOT touched.
_CARD_VERB = (r"(?:le (?:dan|muestran|enseñan|sacan|enseña|saca|muestra|da)|"
              r"ve|recibe|se (?:gana|lleva)|es amonestad[oa]|"
              r"el árbitro le (?:muestra|saca|enseña))")
_CARD_NOUN = (r"(?:la |una |su |)(?:tarjeta(?: amarilla| roja)?|"
              r"cartulina(?: amarilla| roja)?|amarilla|roja)")
# "es amonestado" already MEANS he was booked, so it needs no card noun to count
# as a mention. Allow the first clause to be either "<verb> <card-noun>" or a
# bare "es amonestado".
_CARD_MENTION = rf"(?:{_CARD_VERB}\s+{_CARD_NOUN}|es amonestad[oa])"
_CARD_REDUNDANCY = re.compile(
    rf"({_CARD_MENTION})"                                   # 1st mention — kept
    rf"(?:\s*(?:,\s*y|y|,)\s+(?:el árbitro\s+)?(?:le\s+)?"  # connector (+ árbitro)
    rf"{_CARD_MENTION})",                                   # 2nd mention — dropped
    re.IGNORECASE)


# LONG dashes — en dash (–), em dash (—), horizontal bar (―), minus (−) and the
# figure/hyphen variants — render as an oversized bar (or a .notdef box) in the
# burned-in caption and read oddly aloud. A PLAIN hyphen "-" is fine and stays.
# So fold every long/typographic dash to a plain hyphen everywhere (score "2–1"
# becomes "2-1", an em-dash aside "X — Y" becomes "X - Y").
_LONG_DASH = re.compile(r"[‐‑‒–—―−]")


def _normalise_dashes(text: str) -> str:
    """Replace every long/typographic dash with a plain hyphen; keep '-' as is."""
    return _LONG_DASH.sub("-", text)


def _dedupe_card_mention(text: str) -> str:
    """Collapse a card stated twice for the same booking to a single mention.
    Runs repeatedly in case three verbs were chained ('ve la amarilla, es
    amonestado y le muestran la tarjeta')."""
    prev = None
    while prev != text:
        prev = text
        text = _CARD_REDUNDANCY.sub(r"\1", text)
    return text


# Markdown / formatting characters the model sometimes leaks into the SPOKEN
# script despite being told not to (a '*Canadá 6*' emphasis, a '* ' bullet, a
# '#' heading, a '`' or '_'). The voice would read them aloud or they'd show in
# the caption, so strip them. Hyphens, accents and '¡¿!?' are NOT touched.
_MARKUP = re.compile(r"[*#`_~]+")
# A short parenthetical — "(Girona)", "(de penalti)" — must NOT show in the
# caption (the prompt forbids 'Nombre (Equipo)'; this is the safety net). Drop
# the brackets AND their short content; a long parenthetical keeps its words but
# loses the brackets, so no sentence is gutted.
_SHORT_PAREN = re.compile(r"\s*\(([^)]{1,30})\)")


def _strip_markup(text: str) -> str:
    """Remove stray markdown symbols and parentheses from the spoken script
    (e.g. '*Canadá 6*' -> 'Canadá 6', 'Martínez (Girona)' -> 'Martínez'). Leading
    list bullets ('* ', '- ') at a line start go too."""
    text = re.sub(r"(?m)^\s*[*\-•]\s+", "", text)   # bullet at start of a line
    text = _MARKUP.sub("", text)                     # any inline * # ` _ ~
    text = _SHORT_PAREN.sub("", text)                # short '(...)' aside, brackets+content
    text = text.replace("(", "").replace(")", "")    # any remaining stray bracket
    return text


# Spanish number words 7–11 so a "con DIEZ hombres" miscount is corrected too,
# not just the digit form "con 10 hombres".
_NUM_WORD = {7: "siete", 8: "ocho", 9: "nueve", 10: "diez", 11: "once"}
_WORD_NUM = {v: k for k, v in _NUM_WORD.items()}
# "con 10 hombres", "con diez jugadores", "con uno menos" — a phrase that states
# how many players a side has left after a sending-off. The model keeps doing the
# subtraction itself and getting it wrong (two reds -> it says 8, not 9), so we
# overwrite the number with the real count. The count is passed in (computed from
# the match's red cards); 'con uno/dos menos' is left alone (it is relative, not
# a total, so it cannot be miscounted the same way).
_PLAYERS_LEFT = re.compile(
    r"\bcon\s+(\d{1,2}|siete|ocho|nueve|diez|once)\s+(hombres|jugadores)\b",
    re.IGNORECASE)


def _fix_players_left(text: str, correct: int | None) -> str:
    """Force any 'con N hombres/jugadores' to the real post-red-card count."""
    if not correct:
        return text
    word = _NUM_WORD.get(correct, str(correct))

    def _sub(m: re.Match) -> str:
        stated = m.group(1).lower()
        n = int(stated) if stated.isdigit() else _WORD_NUM.get(stated)
        # Only rewrite a plausible reduced-team total (7–10); leave anything else
        # (e.g. "con 11 jugadores", or an unrelated number) untouched.
        if n in (7, 8, 9, 10) and n != correct:
            return f"con {word} {m.group(2)}"
        return m.group(0)

    return _PLAYERS_LEFT.sub(_sub, text)


def fix_common(text: str, *, players_left: int | None = None) -> str:
    """Apply the deterministic Spanish/football corrections. `players_left`, when
    given, is the real number of men a side has after red cards — used to correct
    a miscounted 'con N hombres'."""
    text = _normalise_dashes(text)
    text = _strip_markup(text)
    for pattern, repl in _RULES:
        text = _apply(pattern, repl, text)
    text = _dedupe_card_mention(text)
    text = _fix_players_left(text, players_left)
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
           use_llm: bool = True, players_left: int | None = None) -> str:
    """Full polish: deterministic fixes first, then the optional LLM editor.

    `players_left`: the real number of men a side has after red cards. Passed
    through so a miscounted 'con N hombres' is corrected — including AFTER the
    LLM editor, which can reintroduce the slip."""
    text = fix_common(text, players_left=players_left)
    if use_llm:
        text = fix_common(polish_llm(text, language=language, provider=provider),
                          players_left=players_left)
    return text

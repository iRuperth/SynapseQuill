"""
narrator.py — turn raw match data into an exciting broadcaster narration.

The LLM is given ONLY the factual match data (teams, score, scorers, minutes)
plus the profile's system_preamble (brand/persona). It must never invent
scores or scorers — that is enforced downstream by the guardrail (expert level).

Multi-language: ES / EN / FR / IT, selected by the profile language.
"""

import re

from core.llm import call_llm

from .match_monitor import Match
from .wc_calendar import _phase_for

_LANG_NAME = {
    "es": "Spanish", "en": "English", "fr": "French", "it": "Italian",
}

# ESPN team name -> Spanish. Covers every nation in the World Cup 2026 field; an
# unknown name falls through to its English form so a title is never blank.
# Shared by the single-match title and the daily digest (which imports it here).
_TEAMS_ES = {
    "Algeria": "Argelia", "Argentina": "Argentina", "Australia": "Australia",
    "Austria": "Austria", "Belgium": "Bélgica",
    "Bosnia-Herzegovina": "Bosnia-Herzegovina", "Brazil": "Brasil",
    "Canada": "Canadá", "Cape Verde": "Cabo Verde", "Colombia": "Colombia",
    "Congo DR": "RD del Congo", "Croatia": "Croacia", "Curaçao": "Curazao",
    "Czechia": "Chequia", "Ecuador": "Ecuador", "Egypt": "Egipto",
    "England": "Inglaterra", "France": "Francia", "Germany": "Alemania",
    "Ghana": "Ghana", "Haiti": "Haití", "Iran": "Irán", "Iraq": "Irak",
    "Ivory Coast": "Costa de Marfil", "Japan": "Japón", "Jordan": "Jordania",
    "Mexico": "México", "Morocco": "Marruecos", "Netherlands": "Países Bajos",
    "New Zealand": "Nueva Zelanda", "Norway": "Noruega", "Panama": "Panamá",
    "Paraguay": "Paraguay", "Portugal": "Portugal", "Qatar": "Catar",
    "Saudi Arabia": "Arabia Saudita", "Scotland": "Escocia",
    "Senegal": "Senegal", "South Africa": "Sudáfrica",
    "South Korea": "Corea del Sur", "Spain": "España", "Sweden": "Suecia",
    "Switzerland": "Suiza", "Tunisia": "Túnez", "Türkiye": "Turquía",
    "United States": "Estados Unidos", "Uruguay": "Uruguay",
    "Uzbekistan": "Uzbekistán",
}


def _team_es(name: str) -> str:
    """Spanish name of a team, or its original form when not in the map."""
    return _TEAMS_ES.get(name, name)


def _scoreline_es(scoreline: str) -> str:
    """Translate both team names in a 'Home X-Y Away' scoreline to Spanish,
    keeping the score untouched ('Mexico 2-0 South Africa' -> 'México 2-0
    Sudáfrica'). Returns the original string if it doesn't match the shape."""
    m = re.match(r"\s*(.+?)\s+(\d{1,2}\s*-\s*\d{1,2})\s+(.+?)\s*$", scoreline or "")
    if not m:
        return scoreline
    return f"{_team_es(m.group(1).strip())} {m.group(2)} {_team_es(m.group(3).strip())}"


def _goal_min(s) -> int:
    """Parse a goal minute like '23' or '90+4' to an int for ordering."""
    try:
        return int(str(s).split("+")[0])
    except (ValueError, TypeError):
        return 999


def _was_comeback(match: Match) -> bool:
    """True if the team that WON the match was behind on the scoreboard at some
    point — i.e. it came from behind to win. Walks the goals in chronological
    order, tracking the running score. Needs goal events; returns False if the
    final result is a draw or the play-by-play is missing."""
    winner = match.winner
    if not winner or not match.goals:
        return False
    hg = ag = 0
    for g in sorted(match.goals, key=lambda x: _goal_min(x.minute)):
        # The event's team is the SCORER's team; an own goal credits the
        # OPPOSING side, so flip it in that case.
        own = "Own" in (g.kind or "")
        if own:
            scoring_side = match.away if g.team == match.home else match.home
        else:
            scoring_side = g.team
        if scoring_side == match.home:
            hg += 1
        elif scoring_side == match.away:
            ag += 1
        # Was the eventual winner trailing right now?
        if winner == match.home and hg < ag:
            return True
        if winner == match.away and ag < hg:
            return True
    return False


def describe_match(match: Match) -> str | None:
    """A short, NEUTRAL description of the match's character, to guide the
    narration's tone. Returns an English guidance string (the other facts are in
    English too) or None when the score is unknown.

    The wording is deliberately respectful — never humiliating. The LLM is asked
    to convey this character in its own varied words, so we describe the SHAPE of
    the result, not a fixed phrase to copy.
    """
    h, a = match.home_goals, match.away_goals
    if h is None or a is None:
        return None
    diff = abs(h - a)
    # A shootout means it was level after normal/extra time, even though there
    # is a winner. Treat that as a draw-in-play, not a clear win.
    pen = match.went_to_penalties or match.status == "PEN"
    draw = (h == a) and not pen

    parts = []
    if pen:
        winner = match.winner
        tail = (f" {winner} advanced." if winner else "")
        parts.append(
            "Very evenly matched — it stayed level and was settled on a penalty "
            f"shootout.{tail} Convey the tension and that both teams deserved "
            "credit.")
    elif draw:
        parts.append(
            "A balanced, evenly-contested match that ended in a draw. "
            "Convey the parity between the two sides.")
    elif diff >= 6:
        parts.append(
            "A dominant, one-sided win for the winner. Convey command and "
            "authority RESPECTFULLY — celebrate the winner's level, never mock "
            "or humiliate the losing side.")
    elif diff >= 2:
        parts.append(
            "A clear, comfortable win for the winner — they controlled the game "
            "and took the result with authority.")
    else:  # diff == 1
        parts.append(
            "A tight, hard-fought, intense match that the winner EARNED in a "
            "close duel. Convey how competitive and demanding it was and give "
            "the winner full credit for taking it. NEVER belittle the win — do "
            "NOT call it 'por la mínima', 'por poco' or any phrase that downplays "
            "the winner's merit; frame it as a hard-earned, deserved victory.")

    # A comeback only counts when the game was WON on goals (the winner was
    # behind and overturned it). A level game decided on penalties is not a
    # comeback even though there is a winner.
    if diff > 0 and not pen and _was_comeback(match):
        parts.append(
            f"It was a COMEBACK: {match.winner} fell behind and turned it around "
            "to win. Emphasise the fightback and character to recover.")

    return " ".join(parts)


def _fmt_date(d: str) -> str:
    """YYYY-MM-DD -> DD-MM-YYYY; returns the original if it doesn't match."""
    parts = (d or "").split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        y, m, day = parts
        return f"{day}-{m}-{y}"
    return d or ""


def _facts_block(match: Match) -> str:
    """Build a compact, unambiguous factual summary for the LLM."""
    lines = []
    if match.competition:
        lines.append(f"Competition: {match.competition}")
        # Derive the World Cup phase from the RAW date (YYYY-MM-DD) so the
        # narrator can name the stage without inventing it; empty for other
        # competitions or out-of-range dates.
        phase = _phase_for(match.date) if match.date else ""
        if phase:
            lines.append(f"Tournament stage: {phase}")
    if match.date:
        lines.append(f"Date: {_fmt_date(match.date)}")
    lines += [
        f"Home team: {match.home}",
        f"Away team: {match.away}",
        f"Final score: {match.home} {match.home_goals} - {match.away_goals} {match.away}",
    ]
    # Tone guidance from the result's shape (blowout / close / draw / penalties /
    # comeback). The model conveys this in its own respectful words.
    character = describe_match(match)
    if character:
        lines.append(f"Match character (use this tone, in your own words, "
                     f"respectfully): {character}")
    if match.venue:
        lines.append(f"Venue: {match.venue}")
    # Build ONE chronological list of every event (goals AND cards together),
    # so the narration can run through the match minute by minute.
    events = []
    for g in match.goals:
        kind = "penalty goal" if "Pen" in g.kind else (
            "own goal" if "Own" in g.kind else "goal")
        line = f"minute {g.minute}: {kind} for {g.team}, scored by {g.player}"
        if g.description:
            line += f" — {g.description}"
        events.append((_goal_min(g.minute), line))
    for c in match.cards:
        events.append((_goal_min(c.minute),
                       f"minute {c.minute}: {c.color} card for {c.player} of {c.team}"))

    if events:
        events.sort(key=lambda e: e[0])
        lines.append("Match events in chronological order (narrate ALL of them, in this order):")
        for _, line in events:
            lines.append(f"  - {line}")
    else:
        lines.append("No goals or cards (0-0).")
    return "\n".join(lines)


# Word-length guidance per narration style.
_LENGTH = {
    "full": "110-170 words, including the opening presentation and the closing "
            "call to action.",
    "digest_short": "VERY SHORT: 30-45 words MAXIMUM — this is one match in a fast daily "
                    "digest. One punchy line on the result and the key goal(s). Do not list "
                    "every detail.",
    "digest_long": "150-220 words with more detail and context — this is one match in a "
                   "longer YouTube digest.",
}


def narrate(match: Match, *, language: str = "es", system_preamble: str = "",
            provider: str | None = None, style: str = "full",
            digest_brief: str = "", digest_open: bool = False,
            digest_close: bool = False) -> str:
    """Return an exciting narration script for `match`.

    style: full (single-match reel) | digest_short (~20s segment) |
    digest_long (detailed YouTube segment).

    For a multi-match digest, `digest_open`/`digest_close` mark the first/last
    segment so they carry the recap's opening and closing, and `digest_brief` is
    a free-form angle ('the most exciting World Cup ties') woven into them.
    """
    lang = _LANG_NAME.get(language, "Spanish")
    length = _LENGTH.get(style, _LENGTH["full"])

    # A single-match reel (style "full") opens by presenting the match and closes
    # by inviting viewers to follow + like.
    if style == "full":
        intro_outro = (
            "Structure the narration in THREE flowing parts (continuous spoken "
            "prose, NO headings or labels):\n"
            "- INTRO: open by presenting the match in your own words, naming BOTH "
            "teams AND the tournament stage when a 'Tournament stage' is given in "
            "the facts (e.g. '¡Qué partidazo en la fase de grupos entre X e Y!' / "
            "'Esto fue lo que pasó en los octavos entre X e Y'). If no stage is "
            "given, present just the duel between the two teams. Make it a gripping "
            "hook that sells the drama in one breath. Vary the wording, keep it "
            "short and electric.\n"
            "- BODY: then go through the match minute by minute (see the event "
            "rules below).\n"
            "- CLOSING: after narrating the last event, crown the match by STATING "
            "THE FINAL SCORE and giving your verdict on the game (e.g. 'y termina "
            "2 a 2, ¡qué partidazo nos regalaron ambos!'). THEN finish with a "
            "short, natural call to action inviting viewers to FOLLOW the channel "
            "and leave a LIKE for more highlights (e.g. 'si lo viviste con "
            "nosotros, síguenos y deja tu like para más resúmenes'). Make it sound "
            "genuine, never spammy, and vary it every time.\n"
        )
    else:
        # In a digest, only the first segment opens the recap and the last closes
        # it. The brief (if any) sets the angle of that opening/closing.
        intro_outro = ""
        angle = (f" The angle of this recap is: \"{digest_brief.strip()}\". "
                 "Frame the opening around that angle.") if digest_brief.strip() else ""
        if digest_open:
            intro_outro += (
                "- This is the FIRST match of a daily recap. OPEN the recap in your "
                "own words, welcoming viewers to the highlights and NAMING the "
                "competition (given in the facts) the way local fans say it. When a "
                "'Tournament stage' is given in the facts, NAME THAT STAGE in the "
                "opening (e.g. 'el resumen de la fase de grupos del Mundial', 'el "
                "resumen de los octavos de final del Mundial', 'el resumen de los "
                "cuartos de final'). If no stage is given, just name the competition "
                "('el resumen de la jornada del Mundial'). Do NOT mention any date "
                "and do NOT invent a round/matchday number."
                f"{angle}\n")
        if digest_close:
            intro_outro += (
                "- This is the LAST match of the recap. After narrating it, CLOSE "
                "the whole recap with a short wrap-up and a natural call to action "
                "inviting viewers to FOLLOW and LIKE so they never miss the epic "
                "moments of THIS competition — name it the way local fans say it "
                "('los momentos épicos de La Liga', '... del Mundial'), never just "
                "a generic 'del fútbol'. Vary the wording.\n")

    system = (system_preamble + "\n\n" if system_preamble else "") + (
        f"You are a LEGENDARY, white-hot football play-by-play commentator. Write ONLY in {lang}. "
        "Narrate like a live radio announcer whose heart is about to burst — MAXIMUM passion, "
        "drama and emotion in every line:\n"
        f"{intro_outro}"
        "- Keep the energy sky-high from the first word — sell the drama in one breath "
        "and never let the tension drop.\n"
        "- Short, explosive, breathless sentences. Build unbearable tension before each goal, "
        "then EXPLODE. Vary the rhythm: whisper the build-up, scream the goal.\n"
        "- Pour in raw emotion and vivid, visceral imagery — the roar of the crowd, nerves of "
        "steel, hearts pounding, the net rippling — but NEVER invent facts to do it.\n"
        "- Use interjections on goals "
        "(in Spanish: '¡GOOOL!', '¡QUÉ GOOOLAZO!', '¡INCREÍBLE!', '¡DE LOCURA!', '¡IMPARABLE!'; "
        "in English: 'GOOOAL!', 'WHAT A STRIKE!', 'UNBELIEVABLE!'). "
        "Stretch the cheer to EXACTLY 3 repeated vowels — 'GOOOL', 'GOOOLAZO' (three O's), "
        "never more than 3 (not 'GOOOOOL'), because the voice reads too many vowels as 'Go-ol'.\n"
        "- CRITICAL — make goals FLOW: connect the play and the goal in ONE continuous "
        "sentence using a linking verb, never leave a bare '¡Gol!' dangling on its own after "
        "a full stop. WRONG (choppy): 'remata con la izquierda. ¡Gol!'. RIGHT (fluid): "
        "'remata con la izquierda y MARCA el gol', '...y la manda al fondo, ¡GOOOL!', "
        "'...y anota', '...para el GOOOLAZO', '...y la clava en la red'. The cheer "
        "('¡GOOOL!') should ride the SAME breath as the action, joined by 'y'/'para'/a "
        "comma — the action and the goal are one motion, not two separate lines.\n"
        "- Put the most intense words in CAPITALS for emphasis.\n"
        "- When 'how it happened' is given for a goal, describe the play vividly using it.\n"
        "- Go through the match EVENT BY EVENT in the given chronological order, narrating "
        "EVERY card AND every goal as they happen. Do not skip cards.\n"
        "- Narrate cards like a HUMAN commentator, never as a data line. NEVER say "
        "'minuto 7, Buba Sangaré, tarjeta' — that sounds like a robot reading a log. "
        "Instead make the player the subject of an ACTION and vary the verb every time: "
        "'al minuto 7 Buba Sangaré se gana la primera amarilla del partido', "
        "'ve la cartulina amarilla', 'el árbitro le muestra la amarilla', "
        "'es amonestado', 'se lleva una tarjeta'. For a RED card raise the drama: "
        "'roja directa, ¡y se queda con uno menos!', 'expulsado, deja a los suyos en "
        "inferioridad'. CRITICAL: do NOT invent WHY the card was shown — you are NOT "
        "told the reason, so never add a cause like 'tras una dura entrada', 'por "
        "protestar' or 'por falta'. Only state who, the team, the colour and the minute. "
        "NEVER change a card's colour: narrate it EXACTLY as the facts give it — a "
        "'Red card' is always 'roja', NEVER 'amarilla', no matter how many yellows "
        "came before it. "
        "For the FIRST card of the match say so ('la primera amarilla del encuentro'). "
        "Announce the minute naturally ('al minuto 7', 'hacia la media hora', 'ya en el "
        "60') — never bare 'minuto 7'. Mix these forms so no two cards sound the same "
        "and it never reads as a list.\n"
        "- NEVER read team names in parentheses. Say them naturally — e.g. "
        "'gol del Girona, obra de Germán Martínez' or 'amarilla para Casemiro, del Real Madrid', "
        "never 'Germán Martínez (Girona)'.\n"
        "- Write FLAWLESS, natural Spanish grammar. Watch gender/agreement on "
        "football words: 'penalti'/'penalty'/'penal' are MASCULINE — say 'el "
        "penalti', 'un penalti', 'convierte el penalti', NEVER 'la penalty'. "
        "Use 'del'/'al', never 'de el'/'a el'.\n"
        "- Refer to the minute in MASCULINE: 'al minuto 51', 'al 51', 'en el 51', "
        "'hacia el 30' are all fine. NEVER feminine — never 'a la 51', 'en la 51' "
        "(the minute is masculine: 'el minuto').\n"
        "- When you name the stadium, refer to it naturally as 'el estadio <name>' or keep its "
        "article — say 'en el estadio de la Cerámica' or 'en La Cerámica', NEVER a bare "
        "'en la Cerámica' that reads as an adjective. Mentioning the stadium is optional; only "
        "do it if it flows.\n"
        "- End with an EPIC, goosebumps closing that crowns the result — STATE THE "
        "FINAL SCORE and give your verdict on the match in a phrase fans remember "
        "(then the call to action, for a single-match reel).\n"
        "- Keep it family-friendly and brand-safe: NO profanity, swear words or vulgar "
        "expressions (e.g. never 'de cojones', 'puto', 'hostia'). The passion comes from "
        "energy, imagery and rhythm — not from coarse language.\n"
        "STRICT: use ONLY the provided facts — never invent scorers, minutes, scores or plays. "
        f"{length} Output ONLY the spoken script: no headings, markdown, hashtags or stage directions.\n"
        f"ABSOLUTE LANGUAGE RULE (overrides everything above): write the ENTIRE script in "
        f"{lang} ONLY. The instructions and the match data above are in English, but your "
        f"output must be 100% {lang} — never switch to English or any other language."
    )

    user = (
        "Write the spoken highlight narration for this finished match:\n\n"
        f"{_facts_block(match)}"
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return call_llm(messages, provider=provider, max_tokens=600, label="Narrator")


# ── Topic / educational narration (no match) ─────────────────────────
# Spoken length for a topic video. Reel is a short vertical clip, the YouTube
# format can carry a bit more. Tuned so the narration fits a ~30-60s short.
_TOPIC_LENGTH = {
    "reel": "55-90 words — a punchy short. One clear idea, well explained.",
    "youtube": "120-200 words — room to explain the idea properly with an "
               "example, still tight and engaging.",
}


def narrate_topic(topic: str, *, language: str = "es", system_preamble: str = "",
                  provider: str | None = None, video_format: str = "reel",
                  source_text: str = "", audience: str = "") -> str:
    """Return a spoken script for a topic/educational ('did you know?') video.

    Two input modes:
      • source_text given — the user pasted the content/facts; narrate ONLY what
        it says (rephrase for spoken flow, never add facts it does not contain).
      • topic only — explain the topic accurately for a general audience, WITHOUT
        inventing statistics, dates, names or quotes you are not sure of.

    No match data and no goal/card guardrail applies here — the grounding is the
    user's own text (or the no-fabrication rule), so this is the "suave" path.
    """
    lang = _LANG_NAME.get(language, "Spanish")
    length = _TOPIC_LENGTH.get(video_format, _TOPIC_LENGTH["reel"])
    aud = (f" Tailor it to this audience: {audience.strip()}."
           if audience.strip() else "")

    if source_text.strip():
        grounding = (
            "The user has provided the SOURCE CONTENT below. Narrate ONLY what it "
            "says: rephrase and tighten it for spoken delivery, but NEVER add a "
            "statistic, date, name, rule or claim that is not in the source. If "
            "the source is thin, keep the script short rather than padding it "
            "with invented detail.")
        user = ("Turn this content into the spoken script:\n\n"
                f"Topic: {topic}\n\nSource content:\n{source_text.strip()}")
    else:
        grounding = (
            "Explain the topic accurately for a general audience. Do NOT invent "
            "statistics, exact dates, names, records or quotes — if you are not "
            "sure of a precise figure, speak in general terms instead of guessing.")
        user = f"Write the spoken script for this topic:\n\nTopic: {topic}"

    system = (system_preamble + "\n\n" if system_preamble else "") + (
        f"You are an engaging, passionate sports-content narrator. Write ONLY in {lang}. "
        "This is a short, informative 'did-you-know'/explainer video (e.g. new "
        "rules, curious facts, history), NOT a live match commentary — so do NOT "
        "use goal shouts, scorelines or play-by-play.\n"
        "- Open with a HOOK that makes the viewer stop scrolling (e.g. '¿Sabías "
        "que...?', 'Esto te va a sorprender...'). Vary it.\n"
        "- Explain the idea clearly, in short, lively sentences with warmth and "
        "energy — like a friend telling you something fascinating.\n"
        "- Put a few key words in CAPITALS for emphasis, but sparingly.\n"
        "- Close with a short, natural call to action inviting viewers to FOLLOW "
        "and LIKE for more. Make it genuine, never spammy, and vary it.\n"
        f"- {grounding}{aud}\n"
        "- Write FLAWLESS, natural grammar. Keep it family-friendly and "
        "brand-safe: NO profanity or vulgar expressions.\n"
        f"{length} Output ONLY the spoken script: no headings, markdown, hashtags "
        "or stage directions.\n"
        f"ABSOLUTE LANGUAGE RULE (overrides everything above): write the ENTIRE "
        f"script in {lang} ONLY — the instructions above are in English, but your "
        f"output must be 100% {lang}."
    )

    return call_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        provider=provider, max_tokens=600, label="Narrator-Topic",
    )


def topic_metadata(topic: str, narration: str, *, language: str = "es",
                   provider: str | None = None) -> dict:
    """YouTube title + description + tags for a topic video (LLM, no match facts).

    Grounded in the narration so it never claims more than the video says.
    """
    lang = _LANG_NAME.get(language, "Spanish")
    system = (
        f"You generate a YouTube title and description in {lang} for a short "
        "football explainer/'did you know' video. Respond as JSON with "
        '"title" (<=90 chars, catchy) and "description" (2-3 sentences). Base it '
        "ONLY on the narration given — never add facts it does not state. JSON only."
    )
    user = f"Topic: {topic}\n\nNarration:\n{narration}"
    raw = call_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        provider=provider, max_tokens=400, label="YT-Meta-Topic",
    )
    import json

    from json_repair import repair_json
    try:
        data = json.loads(repair_json(raw))
    except Exception:
        data = {}
    return {
        "title": (data.get("title") or topic)[:90],
        "description": data.get("description") or topic,
        "tags": build_topic_tags(topic),
    }


def build_topic_tags(topic: str) -> list[str]:
    """Deterministic hashtags for a topic video: a CamelCase tag of the topic's
    key words, plus the brand + generic reach tags. No team/scorer tags (there is
    no match)."""
    tags: list[str] = []
    # A CamelCase tag from the first few significant words of the topic.
    words = [w for w in (topic or "").replace("-", " ").split()
             if w.lower() not in {"de", "del", "la", "el", "los", "las", "y",
                                  "the", "of", "a", "an", "new", "nuevas", "nuevo"}]
    if words:
        tags.append(_hashtag(" ".join(words[:4])))
    tags += ["#CuriosidadesFutbol", "#Mundial2026", *_GENERIC_TAGS]
    seen, out = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _hashtag(text: str) -> str:
    """Turn a name into a CamelCase hashtag: 'Real Madrid' -> '#RealMadrid'.
    Accents are stripped ('Türkiye' -> '#Turkiye', 'Curaçao' -> '#Curacao'):
    YouTube ends a hashtag link at the first non-ASCII character, so a diacritic
    would break the tag in half."""
    import unicodedata
    folded = "".join(c for c in unicodedata.normalize("NFD", text)
                     if not unicodedata.combining(c))
    parts = "".join(w.capitalize() for w in folded.replace("-", " ").split())
    return f"#{parts}" if parts else ""


# Generic reach hashtags appended to every video to widen its audience. The
# brand (#F88tball) leads them. Deliberately NO #Viral/#ForYou/#Shorts: bait
# tags carry no algorithmic weight (YouTube detects Shorts by format) and only
# dilute the topical signal. #Soccer stays for the US audience (World Cup 2026
# is hosted there).
_GENERIC_TAGS = ["#F88tball", "#Futbol", "#Football", "#Soccer",
                 "#Highlights", "#Goles"]


# Fan-community hashtags: tags whose communities actively browse them — worth
# more than any generic reach tag. Hand-curated (never AI-generated, so nothing
# invented): each is the side's established nickname/chant as actually used by
# its fanbase. Covers ALL 48 teams of the 2026 World Cup, plus La Liga clubs.
_FAN_TAGS = {
    # ── World Cup 2026: hosts (CONCACAF) ──
    "United States": "#USMNT", "USA": "#USMNT",
    "Mexico": "#VamosMexico", "Canada": "#CANMNT",
    # ── CONCACAF qualified ──
    "Panama": "#MareaRoja", "Haiti": "#LesGrenadiers",
    "Curaçao": "#Korsou", "Curacao": "#Korsou",
    # ── CONMEBOL ──
    "Argentina": "#VamosArgentina", "Brazil": "#VaiBrasil",
    "Uruguay": "#LaCeleste", "Colombia": "#VamosColombia",
    "Ecuador": "#LaTri", "Paraguay": "#LaAlbirroja",
    # ── UEFA ──
    "Spain": "#VamosEspaña", "France": "#AllezLesBleus",
    "England": "#ThreeLions", "Germany": "#DieMannschaft",
    "Portugal": "#ForçaPortugal", "Netherlands": "#OnsOranje",
    "Belgium": "#DiablesRouges", "Croatia": "#Vatreni",
    "Switzerland": "#LaNati", "Austria": "#DasTeam",
    "Scotland": "#TartanArmy", "Norway": "#Landslaget",
    "Bosnia and Herzegovina": "#Zmajevi", "Sweden": "#Blågult",
    "Türkiye": "#BizimCocuklar", "Turkey": "#BizimCocuklar",
    "Czechia": "#CeskaRepre", "Czech Republic": "#CeskaRepre",
    # ── AFC ──
    "Japan": "#SamuraiBlue", "Iran": "#TeamMelli",
    "South Korea": "#TaegukWarriors", "Korea Republic": "#TaegukWarriors",
    "Australia": "#Socceroos", "Saudi Arabia": "#GreenFalcons",
    "Qatar": "#AlAnnabi", "Uzbekistan": "#WhiteWolves",
    "Jordan": "#Nashama", "Iraq": "#LionsOfMesopotamia",
    # ── CAF ──
    "Morocco": "#DimaMaghrib", "Senegal": "#TerangaLions",
    "Egypt": "#Pharaohs", "Algeria": "#LesFennecs",
    "Tunisia": "#EaglesOfCarthage", "South Africa": "#BafanaBafana",
    "Ivory Coast": "#LesElephants", "Côte d'Ivoire": "#LesElephants",
    "Ghana": "#BlackStars", "Cape Verde": "#TubaroesAzuis",
    "DR Congo": "#LesLeopards", "Congo DR": "#LesLeopards",
    # ── OFC ──
    "New Zealand": "#AllWhites",
    # ── Other big nations (not at WC2026 but may appear in other content) ──
    "Italy": "#ForzaAzzurri",
    # ── La Liga clubs ──
    "Real Madrid": "#HalaMadrid", "Barcelona": "#ForçaBarça",
    "Atlético Madrid": "#AupaAtleti", "Atletico Madrid": "#AupaAtleti",
    "Athletic Club": "#AupaAthletic", "Real Betis": "#MushoBetis",
    "Valencia": "#AmuntValencia", "Real Sociedad": "#AurreraReala",
    "Osasuna": "#AupaOsasuna",
}


def _competition_tags(competition: str) -> list[str]:
    """Well-formed competition hashtags (proper casing). World Cup expands to the
    several tags fans search for."""
    low = (competition or "").lower()
    if "world cup" in low or "mundial" in low:
        return ["#WorldCup2026", "#FIFAWorldCup2026", "#FIFAWorldCup",
                "#Mundial2026"]
    if "laliga" in low or "la liga" in low:
        return ["#LaLiga"]
    if "premier" in low:
        return ["#PremierLeague"]
    if "serie a" in low:
        return ["#SerieA"]
    if "bundesliga" in low:
        return ["#Bundesliga"]
    if "ligue 1" in low:
        return ["#Ligue1"]
    if "champions" in low:
        return ["#ChampionsLeague"]
    # Unknown competition: fall back to a CamelCase hashtag of its cleaned name.
    return [_hashtag(competition)] if competition else []


def _top_scorer_tags(match: Match, limit: int = 3) -> list[str]:
    """Hashtags for the TOP scorers (most goals first), capped at `limit`.
    Players are ranked by how many goals they scored in the match; ties keep the
    order in which they first scored."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for g in match.goals:
        p = g.player
        if not p:
            continue
        if p not in counts:
            counts[p] = 0
            order.append(p)
        counts[p] += 1
    ranked = sorted(order, key=lambda p: counts[p], reverse=True)  # stable
    return [_hashtag(p) for p in ranked[:limit]]


def build_tags(match: Match) -> list[str]:
    """Deterministic hashtags in priority order (only the first few show on
    YouTube): competition, each team, top-3 scorers, the teams' fan-community
    tags, country, then summary + brand + generic tags. No combined matchup
    mashword and no stadium tag — neither is something people search.
    Scorers go BEFORE the fan tags: a scorer's name is what fans search the
    night of the game, and anything past the visible cap never shows."""
    is_world_cup = "world cup" in (match.competition or "").lower() \
        or "mundial" in (match.competition or "").lower()

    tags: list[str] = []
    # 1) Competition, proper-cased (#WorldCup2026 #FIFAWorldCup ... or #LaLiga).
    tags += _competition_tags(match.competition)
    # 2) Each team as its OWN hashtag (#Canada #BosniaHerzegovina) plus their
    #    fan-community tags. We deliberately do NOT emit a combined matchup tag
    #    (#CanadaBosniaHerzegovina): a two-country mashword is unreadable and
    #    nobody searches it. At the World Cup the teams ARE the countries, so
    #    don't also add the host country.
    tags += [_hashtag(match.home), _hashtag(match.away)]
    # 3) Top-3 scorers (most goals first) — before the fan tags so they make
    #    the visible cut.
    tags += _top_scorer_tags(match, limit=3)
    tags += [t for t in (_FAN_TAGS.get(match.home), _FAN_TAGS.get(match.away)) if t]
    if not is_world_cup and match.country:
        tags.append(_hashtag(match.country))
    # 4) Summary. The stadium hashtag is deliberately omitted: a venue name is
    #    not something people search for highlights.
    tags.append("#Resumen")
    # 5) Brand + generic reach tags last.
    tags += _GENERIC_TAGS
    # Dedupe preserving order, drop empties.
    seen, out = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_digest_tags(matches: list) -> list[str]:
    """Hashtags for a daily DIGEST: the competition tags first
    (#WorldCup2026 #FIFAWorldCup2026 #FIFAWorldCup #Mundial2026), then EVERY country that played
    that day, each as its own hashtag (#Canada #BosniaHerzegovina #Mexico ...),
    then the teams' fan-community tags and the generic reach tags.

    No combined matchup mashwords and no per-match scorers/stadiums — a digest
    spans several games, so a flat, readable list of competition + countries is
    what people actually search. `matches` is a list of Match objects."""
    tags: list[str] = []
    # 1) Competition first — read from the first match (all share it in a digest).
    if matches:
        tags += _competition_tags(matches[0].competition)
    # 2) Every country that played, in match order, home then away.
    for m in matches:
        tags += [_hashtag(m.home), _hashtag(m.away)]
    # 3) Fan-community tags for those teams (extra reach for engaged audiences).
    for m in matches:
        tags += [t for t in (_FAN_TAGS.get(m.home), _FAN_TAGS.get(m.away)) if t]
    # 4) Summary + generic reach tags last.
    tags.append("#Resumen")
    tags += _GENERIC_TAGS
    # Dedupe preserving order, drop empties.
    seen, out = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


# Always-appended title suffix: a clickable hashtag with the most reach for a
# Spanish-speaking audience, kept off the team-name translation below.
_TITLE_SUFFIX = " | #Mundial2026"
_TITLE_MAX = 90  # YouTube hard limit


def _title_es(title: str) -> str:
    """Force any English country name in a title to its Spanish form, so the
    title never mixes languages no matter what the model returned."""
    for en, es in _TEAMS_ES.items():
        if en != es:
            title = re.sub(rf"\b{re.escape(en)}\b", es, title)
    return title


def _finalise_title(raw_title: str, match: Match) -> str:
    """Spanish team names + the #Mundial2026 suffix, within YouTube's 90 chars.

    Priority when trimming: keep the hook + scoreline + suffix; the closing
    detail (e.g. 'golazo de X') is what gets shortened away. The suffix is
    always present and never counted out."""
    body = _title_es((raw_title or "").strip()) or _scoreline_es(match.scoreline)
    # Drop any suffix/hashtag the model may have added — we append our own.
    body = re.sub(r"\s*\|?\s*#?\s*Mundial\s*2026\s*$", "", body, flags=re.I).rstrip(" |")
    budget = _TITLE_MAX - len(_TITLE_SUFFIX)
    if len(body) > budget:
        body = body[:budget].rstrip(" ,–-|")
    return body + _TITLE_SUFFIX


def youtube_metadata(match: Match, *, language: str = "es", provider: str | None = None,
                     feedback: str = "") -> dict:
    """Generate a YouTube title + description (LLM) and deterministic tags.

    The title follows the shape "<hook>, <scoreline>, <key detail>" with team
    names always in Spanish and a fixed '| #Mundial2026' suffix added by code;
    it never names the stadium.

    `feedback`: rejection reasons from a previous draft (the runner verifies
    the description against the match facts and retries with them)."""
    lang = _LANG_NAME.get(language, "Spanish")
    system = (
        f"You generate a YouTube title and description in {lang}. Respond as JSON with "
        '"title" and "description" (2-4 sentences). '
        "TITLE: write a punchy highlight headline in this shape: a short hook, "
        "the scoreline, and the single most exciting detail — e.g. 'Dominio "
        "alemán, Alemania 7-1 Curazao, golazo de Wirtz' / 'Suecia 5-1 Túnez, "
        "doble hat-trick de Ayari' / 'Remontada épica de Brasil' / 'Empate en el "
        "último minuto con gol de Vinícius'. Keep it under 70 characters. Do NOT "
        "name the stadium or venue. Do NOT add hashtags or emojis. "
        "Use only the given facts: exact player names, card colours, goal types "
        "(penalty / own goal) and body parts (header vs left/right foot). JSON only."
        + (f"\nA previous draft was rejected for: {feedback}. Fix exactly that."
           if feedback else "")
    )
    user = f"Match:\n{_facts_block(match)}"
    raw = call_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        provider=provider, max_tokens=400, label="YT-Meta",
    )
    import json

    from json_repair import repair_json
    try:
        data = json.loads(repair_json(raw))
    except Exception:
        data = {}
    return {
        "title": _finalise_title(data.get("title", ""), match),
        "description": data.get("description") or _scoreline_es(match.scoreline),
        "tags": build_tags(match),
    }

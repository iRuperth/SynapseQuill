"""The false holds that kept finished, correct videos off the channel.

A false hold is the quietest failure this project has. The video is rendered,
the narration is right, and nothing raises: `blocked_uploads` simply reports a
reason, the uploader skips it, and the match never appears. Re-running the
guardrail over the 103 stored records raised 333 issues; 28 of them survive
these fixes, and the rest were prose that was true.

Every test here is paired. The first half pins prose that must PASS — drawn
verbatim from records that were really held. The second half pins what must
still FAIL with the looser patterns in place, because the whole point of the
gate is that a wrong scoreline, an invented penalty or a miscoloured card never
reaches a public channel. A patch that only relaxed things would be worthless;
what makes these safe is that most of them close a fail-OPEN hole at the same
time — the plural "penales" was invisible to the invention check too.
"""

from agents.guardrail import (
    _card_color_issues,
    _goal_detail_issues,
    _goal_type_issues,
    _invented_name_issues,
    _name_spelling_issues,
    facts_check,
)
from pipeline.match_monitor import Card, Goal, Match


def _match(goals=(), cards=(), home="Barcelona", away="Racing Santander",
           hg=1, ag=0, **kw):
    return Match(fixture_id="laliga-401882871", status="FT", home=home,
                 away=away, home_goals=hg, away_goals=ag,
                 goals=list(goals), cards=list(cards), **kw)


# ── The plural "penales" ─────────────────────────────────────────────
def test_penales_is_a_penalty():
    """The description that held Barcelona 7-2 Racing. Spanish says 'penales'
    for more than one, and the pattern's \\b after 'penal' could not match it."""
    m = _match(goals=[Goal(player="Raphinha", team="Barcelona", minute="25",
                           kind="Penalty"),
                      Goal(player="Asier Villalibre", team="Racing Santander",
                           minute="36", kind="Own Goal")])
    text = ("Barcelona controló el partido, anotando siete goles, incluidos "
            "dos penales de Raphinha y un autogol de Asier Villalibre.")
    assert _goal_type_issues(m, text) == []


def test_invented_penales_is_still_caught():
    """The fail-OPEN twin: a narration inventing penalties in a match with
    none was equally invisible to the plural, and sailed straight through."""
    m = _match(goals=[Goal(player="Raphinha", team="Barcelona", minute="25",
                           kind="Normal Goal")])
    text = "Raphinha firmó dos penales impecables desde los once metros."
    assert any("mentions a penalty" in i for i in _goal_type_issues(m, text))


def test_desde_el_punto_de_vista_is_not_the_penalty_spot():
    """'desde el punto' matched ordinary tactical prose and would have
    reported an invented penalty in any match without one."""
    m = _match(goals=[Goal(player="Raphinha", team="Barcelona", minute="25",
                           kind="Normal Goal")])
    text = ("Desde el punto de vista táctico, el Barcelona dominó el centro "
            "del campo durante los noventa minutos.")
    assert _goal_type_issues(m, text) == []


# ── "la roja": the nickname vs the card ──────────────────────────────
def test_ve_la_roja_is_a_red_card_not_a_nickname():
    """'Themba Zwane ve la roja' lost its only colour evidence to the
    nickname strip and was reported as having been called yellow."""
    m = _match(home="South Africa", away="Mexico",
               cards=[Card(player="Themba Zwane", team="South Africa",
                           minute="84", color="Red"),
                      Card(player="Aristóteles Romero", team="Mexico",
                           minute="80", color="Yellow")])
    text = ("En el 80 Aristóteles Romero recibió una tarjeta amarilla. "
            "Al minuto 84, Themba Zwane ve la roja y abandona el campo.")
    assert _card_color_issues(m, text) == []


def test_spains_nickname_is_still_not_a_red_card():
    """The case the strip exists for: a Spain player booked, and 'la Roja'
    sitting next to his name as the team's name."""
    m = _match(home="España", away="Francia",
               cards=[Card(player="Rodri", team="España", minute="60",
                           color="Yellow")])
    text = "Rodri, el ancla de la Roja, vio la amarilla en el minuto 60."
    assert _card_color_issues(m, text) == []


def test_a_yellow_narrated_as_a_red_is_still_caught():
    """The other fail-OPEN the unconditional strip created."""
    m = _match(home="South Africa", away="Mexico",
               cards=[Card(player="Themba Zwane", team="South Africa",
                           minute="84", color="Yellow")])
    text = "Al minuto 84, Themba Zwane ve la roja y se marcha expulsado."
    assert any("Themba Zwane" in i for i in _card_color_issues(m, text))


# ── Clause windows: the assister and the sentence boundary ───────────
def test_the_assister_does_not_truncate_the_scorers_clause():
    """'recibe el pase de cabeza de Nico Williams y, con un disparo zurdo'
    was clipped at Williams' name, leaving only the word 'cabeza' as
    evidence — and Ferran Torres' left-footed goal was reported as a header."""
    m = _match(home="España", away="Argentina",
               goals=[Goal(player="Ferran Torres", team="España", minute="106",
                           kind="Normal Goal",
                           description="Left footed shot from the centre of the box"),
                      Goal(player="Nico Williams", team="España", minute="115",
                           kind="Normal Goal",
                           description="Right footed shot from outside the box")])
    text = ("Ferran Torres define con elegancia: desde el corazón del área, "
            "recibe el pase de cabeza de Nico Williams y, con un disparo "
            "zurdo al centro de la portería, ¡GOOOL!")
    assert _goal_detail_issues(m, text) == []


def test_the_previous_sentence_is_not_this_players_clause():
    """Clipping at the nearest other player started the window at the END of
    that player's name — which is exactly where their own predicate begins.
    Dembélé's header was being read as Ferran Torres' finish."""
    m = _match(home="Barcelona", away="Real Madrid",
               goals=[Goal(player="Ousmane Dembélé", team="Barcelona",
                           minute="20", kind="Normal Goal",
                           description="Header from the centre of the box"),
                      Goal(player="Ferran Torres", team="Barcelona",
                           minute="31", kind="Normal Goal",
                           description="Right footed shot from the left side")])
    text = ("Dembélé remató de cabeza a quemarropa y marcó el segundo, "
            "¡GOOOL al rincón izquierdo! En el 31, Ferran Torres recibió un "
            "centro de Dembélé y tocó de derecha para firmar el tercero.")
    assert _goal_detail_issues(m, text) == []


def test_a_genuinely_wrong_foot_is_still_caught():
    """The narrowing must not become a blindfold: the wrong word inside the
    player's OWN clause still has nowhere to hide."""
    m = _match(goals=[Goal(player="Ferran Torres", team="Barcelona",
                           minute="31", kind="Normal Goal",
                           description="Right footed shot from the left side")])
    text = "En el 31, Ferran Torres tocó de zurda y firmó el tercero."
    assert any("Ferran Torres" in i for i in _goal_detail_issues(m, text))


# ── The bare surname at the event ────────────────────────────────────
def test_a_label_next_to_the_bare_surname_counts():
    """_name_windows stopped at the full name when it found one, so the only
    window checked was the introduction — and the penalty label sitting beside
    the surname at the goal itself was never seen."""
    m = _match(home="Borussia Dortmund", away="Bayern",
               goals=[Goal(player="Serhou Guirassy", team="Borussia Dortmund",
                           minute="85", kind="Penalty")])
    text = ("Entonces apareció Serhou Guirassy para tirar del equipo. "
            "¡Penal para el Dortmund! Guirassy lo convirtió al 85 con un "
            "derechazo abajo a la izquierda.")
    assert _goal_type_issues(m, text) == []


def test_an_unlabelled_penalty_is_still_caught():
    m = _match(home="Borussia Dortmund", away="Bayern",
               goals=[Goal(player="Serhou Guirassy", team="Borussia Dortmund",
                           minute="85", kind="Penalty")])
    text = "Guirassy lo convirtió al 85 con un derechazo desde fuera del área."
    assert any("PENALTY" in i for i in _goal_type_issues(m, text))


# ── Typographic characters the model emits ───────────────────────────
def test_a_narrow_no_break_space_still_matches_the_feeds_plain_name():
    """U+202F between name tokens appears in 102 of the 103 stored records."""
    m = _match(goals=[Goal(player="Filip Kostić", team="Juventus", minute="9",
                           kind="Normal Goal",
                           description="Left footed shot from the left side")])
    text = "Filip Kostić la colocó con la zurda al palo largo, ¡GOOOL!"
    assert _goal_detail_issues(m, text) == []


def test_a_soft_hyphen_cannot_hide_an_own_goal():
    """U+00AD is not a combining mark, so NFD left it in place and it silently
    disabled whichever detector it landed inside."""
    m = _match(goals=[Goal(player="Asier Villalibre", team="Racing Santander",
                           minute="36", kind="Own Goal")])
    text = "Asier Villalibre mandó el balón a su propia porterí­a, en propia meta."
    assert _goal_type_issues(m, text) == []


# ── Names that are not people ────────────────────────────────────────
def test_a_club_nickname_is_not_an_invented_person():
    """'la Bianconera dominó con un 48% de posesión' held a correct
    Juventus 5-0 recap off the channel."""
    m = _match(home="Juventus", away="NEC Nijmegen",
               goals=[Goal(player="Nico González", team="Juventus",
                           minute="9", kind="Normal Goal")])
    text = ("Y termina 5-0 a favor de la Juventus. La Bianconera dominó con "
            "un 48% de posesión y disparó once veces.")
    assert _invented_name_issues(m, text) == []


def test_a_spanish_exonym_is_not_an_invented_person():
    """The feed names countries in English while the narration is Spanish, so
    every correctly translated country looked like an invention."""
    m = _match(home="Switzerland", away="Scotland",
               goals=[Goal(player="Breel Embolo", team="Switzerland",
                           minute="16", kind="Normal Goal")])
    text = "Suiza se impuso a Escocia en un duelo trabado."
    assert _invented_name_issues(m, text) == []


def test_the_descriptions_opening_word_is_not_a_name():
    """Both callers join title and description with a newline, and the old
    split needed whitespace AFTER the terminator — so the pair was read as one
    sentence and the description's first word was never exempt."""
    m = _match(home="Valencia", away="Real Betis",
               goals=[Goal(player="Cédric Bakambu", team="Real Betis",
                           minute="70", kind="Normal Goal")])
    text = ("Ganador justificado, Valencia 0-1 Real Betis\n"
            "Una partida de gran intensidad donde el Betis fue superior.")
    assert _invented_name_issues(m, text) == []


def test_the_word_after_a_title_separator_is_not_a_name():
    """A YouTube title capitalises after its colon, and the word lands next to
    the end of a team name: 'Dominio', 'Empate' and 'Fuerte' were all held."""
    m = _match(home="Villarreal", away="Atlético Madrid",
               goals=[Goal(player="Ayoze Pérez", team="Villarreal",
                           minute="12", kind="Normal Goal")])
    text = "Villarreal 5-1 Atlético Madrid: Dominio total en la Cerámica"
    assert _invented_name_issues(m, text) == []


def test_an_invented_coach_is_still_caught_as_a_full_name():
    """The case the check was written for — a manager who had left the club a
    season earlier, stated with confidence in a published description."""
    m = _match(home="Real Madrid", away="Barcelona",
               goals=[Goal(player="Kylian Mbappé", team="Real Madrid",
                           minute="12", kind="Normal Goal")])
    text = "El equipo de Carlo Ancelotti salió a presionar desde el minuto uno."
    assert any("Ancelotti" in i for i in _invented_name_issues(m, text))


def test_an_invented_coach_named_by_surname_alone_is_still_caught():
    """Requiring a capitalised neighbour would have opened exactly this hole,
    which is why the role cue re-closes it."""
    m = _match(home="Real Madrid", away="Barcelona",
               goals=[Goal(player="Kylian Mbappé", team="Real Madrid",
                           minute="12", kind="Normal Goal")])
    text = "El equipo dirigido por Ancelotti salió a presionar desde el inicio."
    assert any("Ancelotti" in i for i in _invented_name_issues(m, text))


# ── Misspellings vs words the data really contains ───────────────────
def test_a_stadium_name_is_not_a_misspelt_player():
    """Elche's Estadio Martínez VALERO is one edit from the player Germán
    VALERA, and the check only knew about scorers and carded players."""
    m = _match(home="Elche", away="Levante", venue="Estadio Martínez Valero",
               goals=[Goal(player="Germán Valera", team="Elche", minute="30",
                           kind="Normal Goal")])
    text = "En el Estadio Martínez Valero, Germán Valera abrió el marcador."
    assert _name_spelling_issues(m, text) == []


def test_a_real_misspelling_is_still_caught():
    m = _match(home="Switzerland", away="Qatar",
               goals=[Goal(player="Breel Embolo", team="Switzerland",
                           minute="16", kind="Normal Goal")])
    text = "Breel Embelo empujó el balón dentro del área pequeña."
    assert any("Embelo" in i for i in _name_spelling_issues(m, text))


# ── The shootout score, which lands last by construction ─────────────
def test_a_shootout_score_may_be_the_last_score_stated():
    """The facts block ORDERS the narrator to state it, so it is always last.
    Two shootouts in the archive escaped this only by luck."""
    m = _match(home="Egipto", away="Portugal", hg=1, ag=1,
               home_pens=4, away_pens=2)
    text = ("Terminó 1-1 en el tiempo reglamentario y Egipto se impuso 4-2 "
            "en los penaltis.")
    assert facts_check(m, text)["ok"], facts_check(m, text)["issues"]


def test_a_running_score_stated_last_is_still_caught():
    """The rule this relaxes must still hold for an ordinary match."""
    m = _match(home="Barcelona", away="Racing Santander", hg=7, ag=2)
    text = "Acabó 7-2 el Barcelona, después de aquel 3-1 del primer tiempo."
    assert any("last score" in i for i in facts_check(m, text)["issues"])


# ── A summary is not a transcript ────────────────────────────────────
def test_a_description_need_not_label_every_penalty():
    """A 300-character description is a summary. Demanding it name every
    penalty and own goal is a COMPLETENESS test, which the judge prompt
    already disavows for the narration."""
    m = _match(home="England", away="Senegal",
               goals=[Goal(player="Harry Kane", team="England", minute="40",
                           kind="Penalty")])
    text = ("Inglaterra 1-0 Senegal\n"
            "Harry Kane abrió el marcador con un potente disparo de derecha.")
    assert _goal_type_issues(m, text, summary=True) == []


def test_a_description_may_still_not_invent_one():
    """Only the omission rule is dropped; invention is untouched."""
    m = _match(home="England", away="Senegal",
               goals=[Goal(player="Harry Kane", team="England", minute="40",
                           kind="Normal Goal")])
    text = ("Inglaterra 1-0 Senegal\n"
            "Harry Kane transformó el penalti con autoridad.")
    assert any("mentions a penalty" in i
               for i in _goal_type_issues(m, text, summary=True))


def test_a_description_may_still_not_state_the_wrong_foot():
    m = _match(home="Elche", away="Girona",
               goals=[Goal(player="Marc Bartra", team="Elche", minute="20",
                           kind="Normal Goal",
                           description="Right footed shot from the centre")])
    text = ("Elche 1-0 Girona\n"
            "El disparo de zurda de Marc Bartra decidió el encuentro.")
    assert any("Marc Bartra" in i for i in _goal_detail_issues(m, text))


# ── One reason per distinct problem ──────────────────────────────────
def test_a_reason_is_not_repeated_once_per_goal():
    """Raphinha's two penalties produced the identical sentence twice in the
    report a human has to read in blocked_uploads."""
    m = _match(goals=[Goal(player="Raphinha", team="Barcelona", minute="25",
                           kind="Penalty"),
                      Goal(player="Raphinha", team="Barcelona", minute="67",
                           kind="Penalty")], hg=2, ag=0)
    text = "Raphinha marcó dos veces y el Barcelona ganó 2-0."
    issues = facts_check(m, text)["issues"]
    assert len(issues) == len(set(issues))

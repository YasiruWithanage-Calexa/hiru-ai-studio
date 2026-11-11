"""The rehearsal answers (phase 0, free): what a good split and a good episode answer look like for Ekama Sakshiya, written
by hand as POINTERS (line numbers and word spans found by anchor text here, the way a model would answer). It is the draft
gold of plan/2026-11-11 §10 for scenes 1 to 3: a person must correct it before it judges anything."""
from __future__ import annotations

import re
from pathlib import Path

from .lines import Doc
from .schema import (
    BlockW,
    CardW,
    EpisodeCutW,
    EpisodeW,
    EventW,
    FieldW,
    PresenceW,
    RangeW,
    RuleW,
    SceneBriefW,
    SceneCutW,
    SectionW,
    SpanW,
    SplitW,
    ThingUseW,
)

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "reader" / "ekama-sakshiya.txt"


# the names the gold answers use for the cards, in card order (a model is given the ids, never these)
KEYS = ["Dinu", "Aruni", "Nimal", "Mudalali", "Suren", "Inspector Ruwan", "Colombo", "Mahawewa", "Mahawewa Canal", "Cash Van",
        "Colombo Garage", "Old Port Warehouse", "Aruni's House", "Mahawewa Temple Ground", "Old Rice Mill", "Mahawewa Bus Stop",
        "canal gate", "key C-17", "faded photo", "red thread", "metal box", "medical bag"]


def doc() -> Doc:
    """The text with the repeated page furniture removed (the reader's `strip_page_furniture`): the 'clean' reading."""
    lines = [ln.rstrip("\r").replace("\x0c", "") for ln in FIXTURE.read_text(encoding="utf-8").split("\n")]
    out: list[str] = []
    i = 0
    while i < len(lines):
        if (lines[i] == "EKAMA SAKSHIYA" and i + 3 < len(lines) and lines[i + 1] == "SCREENPLAY / VISUAL TREATMENT"
                and re.fullmatch(r"\d\d", lines[i + 3])):
            i += 4
            continue
        out.append(lines[i])
        i += 1
    return Doc(out)


def _w(d: Doc, line: int, start_phrase: str, end_phrase: str | None = None) -> tuple[int, int]:
    """Word range of a phrase inside a line: from the phrase's first word to the end of `end_phrase` (or the line)."""
    ws = d.words(line)
    a = _index(ws, start_phrase.split())
    z = len(ws) if end_phrase is None else _index(ws, end_phrase.split()) + len(end_phrase.split())
    return a, z


def _index(ws: list[str], phrase: list[str]) -> int:
    for i in range(len(ws) - len(phrase) + 1):
        if ws[i:i + len(phrase)] == phrase:
            return i
    raise KeyError(phrase)


def _lines(d: Doc, a: int, z: int) -> list[SpanW]:
    return [SpanW(line=n, w_from=0, w_to=len(d.words(n))) for n in range(a, z + 1)]


def split(d: Doc) -> SplitW:
    h = {n: d.find_line(f"SCENE 0{n} -") for n in range(1, 10)}
    end_of_story = d.find_line("DIRECTION", after=h[9])  # the "ELEMENT / DIRECTION" table header
    treat = d.find_line("DIRECTOR / DOP")
    last = {n: (h[n + 1] - 1 if n < 9 else treat - 1) for n in range(1, 10)}
    cast = d.find_line("MAIN CHARACTERS")
    cards: list[CardW] = []

    def at(line: int, phrase: str) -> SpanW:
        for ln in range(line, line + 3):  # the phrase may sit on a wrapped line just below the one named
            try:
                a, _z = _w(d, ln, phrase)
            except KeyError:
                continue
            line = ln
            break
        else:
            raise KeyError(phrase)
        return SpanW(line=line, w_from=a, w_to=a + len(phrase.split()))

    for name in KEYS[:6]:
        ln = d.find_line(name, after=cast)
        cards.append(CardW(kind="person", name=at(ln, name), lines=RangeW(start=ln, end=ln + 1),
                           fields=[FieldW(name="age", span=SpanW(line=ln + 1, w_from=0, w_to=1))]))
    index = {k: i for i, k in enumerate(KEYS)}
    places = [  # key, name as the heading writes it, heading line, kind, within, seen
        ("Colombo", "COLOMBO", h[2], "region", "", False), ("Mahawewa", "MAHAWEWA", h[1], "region", "", False),
        ("Mahawewa Canal", "MAHAWEWA CANAL", h[1], "set", "Mahawewa", True), ("Cash Van", "CASH VAN", h[2], "vehicle", "Colombo", True),
        ("Colombo Garage", "COLOMBO GARAGE", h[3], "set", "Colombo", True),
        ("Old Port Warehouse", "OLD PORT WAREHOUSE", h[4], "set", "Colombo", True),
        ("Aruni's House", "ARUNI'S HOUSE", h[6], "set", "Mahawewa", True),
        ("Mahawewa Temple Ground", "MAHAWEWA TEMPLE GROUND", h[7], "set", "Mahawewa", True),
        ("Old Rice Mill", "OLD RICE MILL", h[8], "set", "Mahawewa", True),
        ("Mahawewa Bus Stop", "MAHAWEWA BUS STOP", h[9], "set", "Mahawewa", True)]
    for _key, written, ln, kind, within, seen in places:
        cards.append(CardW(kind="place", name=at(ln, written), lines=RangeW(start=ln, end=ln), place_kind=kind,
                           within=index[within] if within else -1, seen=seen))
    cards.append(CardW(kind="place", name=at(h[1] + 1, "gate:"), lines=RangeW(start=h[1] + 2, end=h[1] + 2),
                       place_kind="spot", within=index["Mahawewa Canal"]))
    for word, ln in (("key", h[1] + 2), ("photo", h[2] + 1), ("thread", h[2] + 4), ("box", h[3] + 1), ("bag.", h[1] + 1)):
        cards.append(CardW(kind="thing", name=at(ln, word), lines=RangeW(start=ln, end=ln)))
    rules = []
    action = d.find_line("ACTION DESIGN NOTES")
    names = [("Colombo palette", "palette", "place", "Colombo"), ("Village palette", "palette", "place", "Mahawewa"),
             ("Love scenes", "lens", "all", ""), ("Action lenses", "lens", "all", ""), ("Lighting", "lighting", "all", ""),
             ("Editing", "editing", "all", ""), ("Sound", "sound", "all", ""), ("Slow motion", "slow_motion", "all", "")]
    starts = [d.find_line(n, after=d.find_line("Colombo palette") - 1) for n, *_ in names]
    for (_, about, scope_kind, scope), a, nxt in zip(names, starts, [*starts[1:], action], strict=True):
        rules.append(RuleW(about=about, lines=RangeW(start=a, end=nxt - 1), scope_kind=scope_kind,
                           scope_card=index[scope] if scope else -1))
    action = d.find_line("ACTION DESIGN NOTES")
    rules.append(RuleW(about="action", lines=RangeW(start=action + 1, end=action + 1)))
    sections = [
        SectionW(label="title_page", lines=RangeW(start=1, end=cast - 1)),
        SectionW(label="cast", lines=RangeW(start=cast, end=h[1] - 2)),
        SectionW(label="story", lines=RangeW(start=h[1] - 1, end=treat - 1)),
        SectionW(label="direction", lines=RangeW(start=treat, end=d.find_line("END") - 1)),
    ]
    _ = end_of_story
    episodes = [EpisodeCutW(number=0, heading=h[1] - 1, scenes=[SceneCutW(number=n, heading=h[n], last=last[n])
                                                                for n in range(1, 10)])]
    return SplitW(sections=sections, cards=cards, rules=rules, episodes=episodes)


def episode(d: Doc, ids_of: dict[str, str]) -> EpisodeW:
    """Scenes 1 to 3. `ids_of` maps a card name to the id code gave it (a model is given these ids)."""
    C, L, P = ids_of, ids_of, ids_of
    h = {n: d.find_line(f"SCENE 0{n} -") for n in range(1, 4)}

    # --- scene 1: Nimal is a body; Aruni calls Dinu, who is only named
    a1 = h[1] + 1
    s1_dlg = a1 + 3
    s1 = SceneBriefW(
        scene="E01-S01", title="The body at the canal gate", summary="Aruni finds her brother's body in the rain and the key in his fist.",
        purpose="Cold open: the death and the key that drive the film.", place=L["Mahawewa Canal"], mood=["bleak", "restrained"],
        people=[PresenceW(person=C["Aruni"], wants="to know what happened", feeling_start="calm", feeling_end="afraid"),
                PresenceW(person=C["Nimal"], presence="body")],
        things=[ThingUseW(thing=P["key C-17"], role="hero", holder_start=C["Nimal"], holder_end=C["Nimal"]),
                ThingUseW(thing=P["medical bag"], role="worn", holder_start=C["Aruni"], holder_end=C["Aruni"])],
        blocks=[BlockW(kind="action", spans=_lines(d, a1, a1 + 2),
                       events=[EventW(actors=[C["Aruni"]], things=[P["key C-17"]], spot=L["canal gate"],
                                      change="Aruni finds the body and the key", function="reveal")]),
                BlockW(kind="dialogue", spans=[SpanW(line=s1_dlg, w_from=2, w_to=len(d.words(s1_dlg)))], speaker=C["Aruni"],
                       intent="speaks the question to the body", addressee=C["Dinu"]),
                BlockW(kind="action", spans=_lines(d, s1_dlg + 1, s1_dlg + 1))],
        turns=[1])

    # --- scene 2: Aruni is a voice message, Mudalali a phone call that sits inside an action line
    a2 = h[2] + 1
    d2 = a2 + 2
    call = d2 + 1
    c0, c1 = _w(d, call, "Route", "yanna.")
    s2 = SceneBriefW(
        scene="E01-S02", title="The voice message", summary="Dinu drives through Colombo; a message and a call send him to the warehouse.",
        purpose="Pulls Dinu toward the warehouse while Aruni's fear reaches him.", place=L["Cash Van"], mood=["tense", "wet"],
        people=[PresenceW(person=C["Dinu"]), PresenceW(person=C["Aruni"], presence="voice_message"),
                PresenceW(person=C["Mudalali"], presence="phone")],
        things=[ThingUseW(thing=P["faded photo"], role="dressing"), ThingUseW(thing=P["red thread"], role="worn",
                                                                             holder_start=C["Dinu"], holder_end=C["Dinu"])],
        blocks=[BlockW(kind="action", spans=_lines(d, a2, a2 + 1)),
                BlockW(kind="dialogue", spans=[SpanW(line=d2, w_from=2, w_to=len(d.words(d2)))], speaker=C["Aruni"],
                       presence="voice_message", device="phone", addressee=C["Dinu"], heard_by=[C["Dinu"]],
                       intent="fear that Nimal has not come home"),
                BlockW(kind="action", spans=[SpanW(line=call, w_from=0, w_to=c0)],
                       events=[EventW(actors=[C["Mudalali"]], speech=False, visible=False, change="Mudalali calls")]),
                BlockW(kind="dialogue", spans=[SpanW(line=call, w_from=c0, w_to=c1)], speaker=C["Mudalali"], presence="phone",
                       device="phone", addressee=C["Dinu"], heard_by=[C["Dinu"]], intent="orders Dinu to the warehouse",
                       events=[EventW(actors=[C["Mudalali"]], speech=True, visible=False)]),
                BlockW(kind="action", spans=[SpanW(line=call, w_from=c1, w_to=len(d.words(call))), *_lines(d, call + 1, call + 1)],
                       events=[EventW(actors=[C["Dinu"]], things=[P["red thread"]], change="Dinu heads for the industrial area",
                                      function="turn")])],
        turns=[5])

    # --- scene 3: a flashback; Mudalali is only named in a line, so he is not here
    a3 = h[3] + 1
    s3_lines = [(n, d.lines[n - 1]) for n in range(a3, d.find_line("SCENE 04 -"))]
    dlg = [n for n, t in s3_lines if re.match(r"^(NIMAL|DINU) - ", t)]
    first_dlg = dlg[0]
    last_dlg = dlg[-1]
    blocks3 = [BlockW(kind="action", spans=_lines(d, a3, first_dlg - 1),
                      events=[EventW(actors=[C["Nimal"]], things=[P["metal box"], P["key C-17"]], change="Nimal opens the box",
                                     function="setup")])]
    for n in dlg:
        sp = C["Nimal"] if d.lines[n - 1].startswith("NIMAL") else C["Dinu"]
        other = C["Dinu"] if sp == C["Nimal"] else C["Nimal"]
        blocks3.append(BlockW(kind="dialogue", spans=[SpanW(line=n, w_from=2, w_to=len(d.words(n)))], speaker=sp,
                              addressee=other, heard_by=[other], intent="warns" if sp == C["Nimal"] else "answers"))
    blocks3.append(BlockW(kind="action", spans=_lines(d, last_dlg + 1, d.find_line("SCENE 04 -") - 1),
                          events=[EventW(actors=[C["Nimal"], C["Dinu"]], things=[P["key C-17"]],
                                         change="the key passes to Dinu", function="turn")]))
    s3 = SceneBriefW(
        scene="E01-S03", title="The key changes hands", summary="Six hours earlier, Nimal gives Dinu the key and the story of the money.",
        purpose="Shows what Nimal knew and why the key matters.", place=L["Colombo Garage"], mood=["urgent"],
        people=[PresenceW(person=C["Nimal"], wants="to get Aruni away"), PresenceW(person=C["Dinu"])],
        things=[ThingUseW(thing=P["metal box"], role="used"),
                ThingUseW(thing=P["key C-17"], role="hero", holder_start=C["Nimal"], holder_end=C["Dinu"])],
        blocks=blocks3, turns=[len(blocks3)])
    return EpisodeW(scenes=[s1, s2, s3])

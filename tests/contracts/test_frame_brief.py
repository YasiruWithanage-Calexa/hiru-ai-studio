"""The first frame's brief (plan/2026-11-11b): everything the planner decided reaches the prompt, in a fixed order,
every attached picture is named with its job, and the same-setup frame is found and attached last."""
from __future__ import annotations

from typing import Any

from contracts.frame_brief import (
    LEAD,
    PROMPT_CAP,
    SETUP_LABEL,
    SetupFrame,
    black_plate,
    expected_frame,
    frame_brief,
    frame_prompt,
    lead_line,
    missing_references,
    nearest_option,
    plan_references,
    reference_job,
    references_block,
    setup_frame,
    setup_of,
    shot_look,
    time_phrase,
    weather_phrase,
)
from contracts.producer import CameraField, CastMember, default_camera

# One planner's shot at a market stall, written the way the planners write (not Ekama's words: those are in the lab).
IR: dict[str, Any] = {
    "setting": "A covered fish stall at the Negombo lagoon market, before sunrise in steady drizzle.",
    "cinematography": {"camera": "shoulder rig, 40mm, f/2", "angle": "Low three-quarter from the ice trays",
                       "framing": "MCU of Sunil over the scales", "movement": "slow handheld sway",
                       "white_balance": "3800K tungsten bulbs against blue pre-dawn",
                       "color_tone": "Teal shadows with warm amber bulb highlights",
                       "depth_of_field": "Shallow; the far stalls dissolve into bulb points", "lens_artifacts": ""},
    "lighting": "Bare tungsten bulbs hang over the trays; cold blue skylight from the open lagoon side.",
    "subjects": [{"id": "C02", "description": "Sunil, 48, a fishmonger in a rubber apron over a checked sarong",
                  "action": "weighs a seer fish", "position": "Behind the scales, frame left, facing the buyer"}],
    "audio": "Drizzle on the tin roof, gulls, the market waking.",
    "first_frame": {"composition": "Sunil left of centre over the scales, ice trays leading in from the right.",
                    "subjects": ["Sunil lifting the seer fish onto the scale pan"],
                    "setting": "Inside the stall", "lighting": "Amber bulb key from above"},
}
SCENE: dict[str, Any] = {
    "heading": "EXT. NEGOMBO LAGOON MARKET - DAWN", "time_of_day": "",
    "raphael": {
        "clips": [{"slate": "4C-2", "moment": 2,
                   "sound": {"ambience": "Drizzle and gulls", "effects": "Ice scraping"}}],
        "edit": {"moments": [{"n": 2, "sequence": "S2", "feeling": "Quiet dread under the routine"}],
                 "treatment": {"colour_script": [
                     {"sequence": "S1", "palette": "Grey", "light": "Flat", "grade": "Neutral"},
                     {"sequence": "S2", "palette": "Teal and amber", "light": "Bulbs against blue dawn",
                      "grade": "Lifted blacks, amber kept warm"}]}},
    },
}
SUNIL = CastMember(id="s", code="C02", name="Sunil")


def camera(**over: str) -> Any:
    return default_camera("MCU", heading=SCENE["heading"]).with_overrides(over)


def brief(**kw: Any) -> Any:
    cam = kw.pop("camera", camera())
    return frame_brief(ir=kw.pop("ir", IR), camera=cam, aspect_ratio="16:9", cast=kw.pop("cast", [SUNIL]),
                       recommended=kw.pop("recommended", camera()), scene=kw.pop("scene", SCENE),
                       shot=kw.pop("shot", {"slate": "4C-2"}), **kw)


def test_every_decision_the_planner_wrote_reaches_the_prompt():
    text = brief().text()
    for fact in ("Teal shadows with warm amber bulb highlights",  # colour tone
                 "3800K tungsten bulbs against blue pre-dawn",  # white balance
                 "Bare tungsten bulbs hang over the trays",  # the fuller IR light
                 "covered fish stall at the Negombo lagoon market",  # the fuller IR setting
                 "Time: dawn, exterior", "Weather: rain",  # never left out
                 "rubber apron over a checked sarong", "Behind the scales, frame left",  # the subject's own words
                 "Grade: Lifted blacks, amber kept warm",  # the sequence's colour script, not another sequence's
                 "Mood: Quiet dread under the routine",  # the moment's feeling
                 "low three-quarter from the ice trays", "the far stalls dissolve into bulb points"):
        assert fact in text, fact
    assert "Neutral" not in text, "the colour script of the shot's own sequence only"


def test_every_field_of_the_camera_panel_is_in_the_prompt_as_it_stands():
    text = brief().text()
    shot = ("Shot: Medium close-up (MCU of Sunil over the scales), eye level (low three-quarter from the ice trays); "
            "50mm lens at f/2.8, a normal lens")
    assert shot in text, "the panel's lens and stop, numbers and look"
    assert "Static: a steady, locked-off frame." in text
    assert "Camera on side A of the line of action: the action reads left to right." in text
    assert "Lighting: Dawn, soft ambient: Bare tungsten bulbs hang over the trays" in text, "the panel's lighting leads"
    moved = brief(camera=camera(movement="Dolly in", speed="Slow", axis="Side B · right to left")).text()
    assert "Slow dolly in: this is the opening frame of the move." in moved
    assert "Camera on side B of the line of action: the action reads right to left." in moved


def test_a_persons_camera_change_wins_over_the_planners_words():
    text = brief(camera=camera(lens="85mm", angle="High angle", lighting="Day, open sun")).text()
    assert "a long portrait lens" in text and "high angle" in text and "three-quarter" not in text
    assert "Lighting: Day, open sun" in text and "Bare tungsten bulbs" not in text


def test_the_sections_come_in_their_fixed_order():
    text = brief(references=["the character sheet for Sunil"], unseen="Mala is not in this place.").text()
    marks = ["Photorealistic still frame", "Reference images", "Shot:", "Sunil left of centre", "People:",
             "Setting:", "Lighting:", "Colour:", "Mood:", "Mala is not in this place", "16:9 framing"]
    found = [text.index(m) for m in marks]
    assert found == sorted(found)


def test_every_attached_picture_is_named_in_order_with_its_job():
    labels = ["the look sheet for Sunil", "the location plate for the lagoon market",
              "the reference sheet for the scale (held by Sunil)", f"{SETUP_LABEL} 4C-1"]
    text = " ".join(references_block(labels))
    assert "image 1 is the look sheet for Sunil; image 2 is the location plate for the lagoon market; image 3 is " \
           f"the reference sheet for the scale (held by Sunil); image 4 is {SETUP_LABEL} 4C-1." in text
    assert "image 1: Sunil's face, body and clothes, not its light or backdrop" in text
    assert "image 2: the place and its fixtures, not its light or time of day" in text
    assert "image 3: the scale exactly as shown" in text
    assert "image 4: the same camera setup: match its framing, light and grade, not the pose" in text
    assert reference_job("something nobody labelled") == "" and references_block([]) == []


def test_the_brief_says_where_each_section_came_from():
    view = {s["key"]: s for s in brief().view()}
    assert "ir.cinematography.white_balance" in view["light"]["sources"]
    assert "treatment.colour_script" in view["colour"]["sources"]
    assert view["place"]["title"] == "Place and time"


def test_over_the_cap_the_optional_parts_go_first_and_never_the_people_or_the_time():
    full = brief()
    tight = brief(cap=len(full.text()) - 1)
    assert tight.cut == ["mood"] and "Mood:" not in tight.text() and "People:" in tight.text()
    tiny = brief(cap=100)
    assert tiny.cut == ["mood", "frame_light", "grade_script"]
    for kept in ("People:", "Time: dawn", "Setting:", "Shot:"):
        assert kept in tiny.text()
    assert len(full.text()) <= PROMPT_CAP


def test_a_thin_old_ir_still_renders_with_the_time_and_the_preset_light():
    ir = {"first_frame": {"composition": "Kamala at the stove", "subjects": ["Kamala"]}}
    text = frame_prompt(ir=ir, camera=default_camera("WIDE", heading="INT. HOUSE - NIGHT"), aspect_ratio="9:16",
                        cast=[], scene={"heading": "INT. HOUSE - NIGHT"})
    assert "Time: night, interior" in text and "Lighting: Night, lamp key" in text and "9:16 vertical" in text
    assert "Weather" not in text and "Mood" not in text, "nothing invented"


def test_weather_is_only_what_the_words_name():
    assert weather_phrase("rain-lit Colombo", "wet streets") == "rain, wet surfaces"
    assert weather_phrase("a dry, still noon") == ""
    assert weather_phrase("no rain tonight, a clear sky") == ""
    assert weather_phrase("sea mist and a gusting wind") == "mist, wind"


def test_time_and_place_from_the_heading():
    assert time_phrase({"heading": "INT. CASH VAN - NIGHT"}) == "night, interior"
    assert time_phrase({"heading": "EXT. ROAD", "time_of_day": "dusk"}) == "dusk, exterior"
    assert time_phrase({"heading": "I/E. CAR - DAY"}) == "day, interior and exterior"
    assert time_phrase({}) == ""


def test_the_scene_look_is_read_only_from_a_slate_the_plan_has():
    assert shot_look(SCENE, "4C-2").grade == "Lifted blacks, amber kept warm"
    assert shot_look(SCENE, "9Z-1").grade == "" and shot_look({}, "4C-2").feeling == ""


def test_the_panels_nearest_lens_and_stop():
    assert nearest_option(CameraField.LENS, "braced handheld, 65mm, f/2.8") == "50mm"
    assert nearest_option(CameraField.LENS, "70mm") == "85mm"
    assert nearest_option(CameraField.LENS, "a 24mm wide") == "28mm"
    assert nearest_option(CameraField.APERTURE, "T2.1, f/2.2") == "f/2"
    assert nearest_option(CameraField.LENS, "handheld") == "" and nearest_option(CameraField.APERTURE, "") == ""


def test_the_vision_check_also_expects_the_time_and_the_weather():
    text = expected_frame(IR, SCENE)
    assert "Sunil left of centre" in text and "Time: dawn, exterior" in text and "Weather: rain" in text


# ── the same-setup frame ───────────────────────────────────────────────────────────────────

SHOTS = [{"id": "a", "slate": "2B-1"}, {"id": "b", "slate": "2B-2"}, {"id": "c", "slate": "2B-3"},
         {"id": "d", "slate": "2C-1"}, {"id": "e", "slate": ""}]
DONE = {"storage_path": "p/f.png"}


def test_a_setup_is_the_slate_before_its_take():
    assert setup_of("2B-2") == "2B" and setup_of("12AA-10") == "12AA" and setup_of("") == "" and setup_of("S1") == ""


def test_a_later_shot_of_a_setup_is_shown_the_first_accepted_frame_of_that_setup():
    accepted = {"a": {"id": "fa", **DONE}, "b": {"id": "fb", **DONE}}
    found = setup_frame(SHOTS[2], SHOTS, accepted)
    assert found == SetupFrame(frame_id="fa", slate="2B-1", path="p/f.png")
    assert setup_frame(SHOTS[2], SHOTS, {"b": {"id": "fb", **DONE}}).slate == "2B-2"  # type: ignore[union-attr]
    assert setup_frame(SHOTS[0], SHOTS, accepted) is None, "the first of its setup has nothing before it"
    assert setup_frame(SHOTS[3], SHOTS, accepted) is None, "another setup"
    assert setup_frame(SHOTS[4], SHOTS, accepted) is None, "a shot with no slate"
    assert setup_frame(SHOTS[2], SHOTS, {"a": {"id": "fa"}}) is None, "an accepted frame with no picture"
    off = {**SHOTS[2], "person_edits": {"setup_frame_off": True}}
    assert setup_frame(off, SHOTS, accepted) is None, "a person turned it off"


CANON = [
    {"id": "k", "kind": "character", "name": "Kamala", "code": "C01",
     "current": {"reference_assets": [{"path": "p/kamala.png"}]}},
    {"id": "n", "kind": "character", "name": "Nimal", "code": "C02", "current": {"reference_assets": []}},
    {"id": "h", "kind": "location", "name": "the house", "code": "L01", "current": {"reference_assets": []}},
]


def test_the_plan_puts_people_then_place_then_the_setup_frame_and_lists_what_is_missing():
    scene = {"id": "s", "location_id": "h"}
    planned = plan_references(scene, {"id": "x"}, CANON, ["k", "n"], {},
                              setup=SetupFrame(frame_id="fa", slate="2B-1", path="p/f.png"))
    assert [(p.role, p.label) for p in planned] == [
        ("character", "the character sheet for Kamala"), ("character", ""), ("place", ""),
        ("setup", f"{SETUP_LABEL} 2B-1")]
    assert missing_references(planned) == [
        "No sheet for Nimal: their face is painted from words only.",
        "No location plate for the house: the place is painted from words only."]
    look = {"k": {"id": "L1", "name": "Heiress", "sheet_assets": [{"path": "p/look.png"}]}}
    first = plan_references(scene, {"id": "x"}, CANON, ["k"], look)[0]
    assert first.role == "look" and [c[0] for c in first.choices] == ["the look sheet for Kamala",
                                                                      "the character sheet for Kamala"]


def test_over_the_limit_the_setup_frame_goes_before_anyone():
    scene = {"id": "s", "location_id": "h"}
    planned = plan_references(scene, {"id": "x"}, CANON, ["k", "n"], {},
                              setup=SetupFrame(frame_id="fa", slate="2B-1", path="p/f.png"), limit=3)
    assert [p.role for p in planned] == ["character", "character", "place"]


# ── the prompt writer's words (plan/2026-11-11c) ───────────────────────────────────────────


def test_a_stored_polish_is_used_only_while_the_code_words_are_the_ones_it_was_written_from():
    from contracts.prompt_polish import stamp

    code = {s.key: s.text for s in brief().sections}
    record = {"light": {"stamp": stamp(code["light"]), "text": "Warm 3800K bulbs pool over the trays."},
              "mood": {"stamp": "0" * 12, "text": "Stale words."}}
    used = brief(shot={"slate": "4C-2", "design": {"frame_polish": record}})
    by_key = {s["key"]: s for s in used.view()}
    assert by_key["light"]["text"] == "Warm 3800K bulbs pool over the trays." and by_key["light"]["sources"] == [
        "prompt_writer"]
    assert by_key["mood"]["text"] == code["mood"], "written from other words: the code's come back"
    plain = brief(shot={"slate": "4C-2", "design": {"frame_polish": record}}, polished=False)
    assert plain.text() == brief().text()
    stale = brief(camera=camera(lighting="Day, open sun"), shot={"slate": "4C-2", "design": {"frame_polish": record}})
    assert "Warm 3800K bulbs" not in stale.text(), "a person changed the light: the polish no longer applies"


# ── the production's genre (plan/2026-11-12b) ───────────────────────────────────────────────────────────────────────


def test_the_lead_names_the_productions_genre_and_stays_fixed():
    brief = frame_brief(ir=IR, camera=camera(), aspect_ratio="16:9", cast=[SUNIL], scene=SCENE,
                        genre="action and crime thriller")
    lead = brief.view()[0]
    assert lead["key"] == "lead" and lead["sources"] == ["fixed"]
    assert brief.text().startswith("Photorealistic still frame from a Sri Lankan action and crime thriller, shot on")


def test_without_a_genre_the_lead_is_byte_for_byte_as_before():
    assert lead_line("") == lead_line("   ") == LEAD
    plain = frame_prompt(ir=IR, camera=camera(), aspect_ratio="16:9", cast=[SUNIL], scene=SCENE)
    assert plain == frame_brief(ir=IR, camera=camera(), aspect_ratio="16:9", cast=[SUNIL], scene=SCENE,
                                genre="").text()
    assert plain.startswith(LEAD)


def test_the_prompt_writer_never_rewords_the_lead():
    from contracts.prompt_polish import POLISHABLE

    assert "lead" not in POLISHABLE["first_frame"]


def test_a_cut_to_black_or_a_title_card_is_a_black_plate():
    assert black_plate(["Cut to black."]) and black_plate(["TITLE: EKAMA SAKSHIYA."])
    assert black_plate(["FADE TO BLACK.", "Title: Episode one"]) and black_plate(["Black."])
    assert not black_plate([]) and not black_plate(["She calls Dinu. No answer.", "Cut to black."])
    assert not black_plate(["The black van turns into the yard."])


def test_the_scene_mood_from_the_packet_is_in_the_prompt_and_never_cut():
    scene = {**SCENE, "raphael": {**SCENE["raphael"], "mood": ["bleak", "restrained", "ominous"]}}
    brief = frame_brief(ir=IR, camera=camera(), aspect_ratio="16:9", cast=[SUNIL], scene=scene,
                        shot={"slate": "4C-2"}, cap=400)
    assert "Scene mood: bleak, restrained, ominous." in brief.text() and "mood" in brief.cut
    assert "Scene mood" not in frame_prompt(ir=IR, camera=camera(), aspect_ratio="16:9", cast=[SUNIL], scene=SCENE,
                                            shot={"slate": "4C-2"})

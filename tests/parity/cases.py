"""The scenarios the parity fixtures are recorded from (`python -m tests.parity.record`).

Only this file knows how a scenario is built; the fixtures hold its result. Editing a case is a
deliberate act: re-record, and read the diff of `expected` in review (it is today's behaviour).
"""
from __future__ import annotations

from typing import Any

SCRIPT = "harbour-lights-ep01-script.fountain"
OUTLINE = "harbour-lights-outline.txt"
QUESTIONABLE = "INT. KAMALA'S HOUSE - NIGHT\n\nNIMAL\nහරි.\n\nEXT. KALUGALA BEACH - DAY\n\nWaves.\n"


def case(description: str, input_: dict[str, Any], model: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"description": description, "input": input_, "model": model or {}}


def _first_episode_cut(*, broken: bool = False) -> dict[str, list[dict[str, Any]]]:
    """A model's cut of the first prose episode: the rules' scenes, which keep every spoken line (or, `broken`, with the
    dialogue left out, which a check in code must refuse)."""
    from structure_build.engine import prose

    from tests.parity.adapters import prose_text

    scenes = prose.by_rules(prose.sections(prose_text(1))[0])
    if broken:
        scenes = [{**s, "blocks": [b for b in s["blocks"] if b["kind"] != "dialogue"]} for s in scenes]
    return {"prose_scenes": [{"scenes": scenes}]}


def _card_fields() -> dict[str, str]:
    from canon_extract.engine import model

    return dict.fromkeys(model.CARD_FIELDS, "")


def _cases() -> dict[str, dict[str, dict[str, Any]]]:
    card = _card_fields()
    shot_plan = {"shots": [
        {"start": 0, "end": 2, "framing": "WIDE", "title": "Nimal at the door", "sound_mode": "dialogue",
         "duration": 8, "camera_link": "cut"},
        {"start": 2, "end": 4, "framing": "CU", "title": "Kamala keeps cooking", "sound_mode": "dialogue",
         "duration": 6, "camera_link": "cut"}]}
    revised = {"shots": [{**shot_plan["shots"][0], "title": "Nimal waits"}, shot_plan["shots"][1]]}
    review_ok = {"acceptable": True, "notes": []}
    review_no = {"acceptable": False, "notes": ["S02 needs Kamala's reaction"]}

    return {
        "echo": {
            "hello": case("A pending job runs to done", {"message": "hello"}),
            "redelivered": case("A finished job redelivered is a no-op", {"message": "hi", "status": "done"}),
        },
        "doc_ingest": {
            "script_no_key": case("A script, no key: keyword index only",
                                  {"corpus": SCRIPT, "filename": SCRIPT}),
            "script_with_key": case("A script with a key: model headers and embeddings, rerun reuses them",
                                    {"corpus": SCRIPT, "filename": SCRIPT, "deliveries": 2}, {"client": True}),
            "embedding_down": case("The embedding service is down: still indexed for keywords",
                                   {"corpus": SCRIPT, "filename": SCRIPT}, {"client": True, "fail_embed": True}),
            "scanned_pdf": case("A scanned PDF is rejected and the job finishes",
                                {"pdf_pages": ["", ""], "filename": "scan.pdf"}),
            "confirmed_role": case("A confirmed role wins over detection for chunking",
                                   {"corpus": "director-notes.txt", "filename": "notes.txt",
                                    "confirmed_role": "script"}),
        },
        "canon_extract": {
            "rules_only": case("No key: the fixture canon from the index, the bible and the script", {}),
            "rerun_unchanged": case("A second run changes nothing", {"runs": 2}),
            "build_hop": case("In a build, the result is handed to the next function", {"build": True}),
            "model_cards": case(
                "Model cards fill in; dedupe merges the script's nickname into the character",
                {"script_replace": [["KAMALA\n", "AMMA\n"]]},
                {"enabled": True, "replies": {
                    "canon": [{"entities": [
                        {"kind": "character", "name": "Sunil", "code": "C03", "aliases": [], "core": True,
                         "card": {**card, "appearance": "wiry, sun-darkened", "voice": "model paraphrase"}},
                        {"kind": "prop", "name": "Lantern", "code": "", "aliases": [], "core": False,
                         "card": {**card, "details": "kerosene lantern"}}]}],
                    "canon_dupes": [{"groups": [{"kind": "character", "keep": "Kamala",
                                                 "same_as_keep": ["Amma"]}]}]}}),
        },
        "structure_build": {
            "script_and_outline": case(
                "The fixture script and outline need no questions",
                {"docs": [{"filename": "ep01.fountain", "role": "script", "corpus": SCRIPT},
                          {"filename": "outline.txt", "role": "outline", "corpus": OUTLINE}]}),
            "question_and_resume": case(
                "A question pauses the build; a duplicate waits; the answers resume it; the next build reuses them",
                {"docs": [{"filename": "untitled.txt", "role": "script", "text": QUESTIONABLE}],
                 "answers": {"episode": "4", "loc": "L02", "noloc": "previous", "spk": "C02"}}),
            "no_durable_checkpoints": case(
                "Without durable checkpoints the suggested answers are taken and recorded",
                {"docs": [{"filename": "untitled.txt", "role": "script", "text": QUESTIONABLE}], "durable": False}),
            "outline_only": case("An outline-only production gets episodes and a warning",
                                 {"docs": [{"filename": "outline.txt", "role": "outline", "corpus": OUTLINE}]}),
            "scenes_off": case(
                "Scenes can be left out of the build",
                {"docs": [{"filename": "ep01.fountain", "role": "script", "corpus": SCRIPT}],
                 "settings": {"build": {"scenes": False}}}),
            "prose_rules": case(
                "A story written as prose (no scene headings) is cut into scenes by rules without a key",
                {"docs": [{"filename": "drama.txt", "role": "bible", "prose": "three-episode-drama.txt"}]}),
            "prose_model": case(
                "A model's cut that keeps every spoken line is used",
                {"docs": [{"filename": "drama.txt", "role": "bible", "prose": "three-episode-drama.txt",
                          "episode": 1}]},
                {"enabled": True, "replies": _first_episode_cut()}),
            "prose_model_rejected": case(
                "A model's cut that drops a spoken line is thrown away: the rules cut it and a warning says so",
                {"docs": [{"filename": "drama.txt", "role": "bible", "prose": "three-episode-drama.txt",
                          "episode": 1}]},
                {"enabled": True, "replies": _first_episode_cut(broken=True)}),
            "architect_names": case(
                "The architect names scenes with the model; a scene it skips keeps the rule label",
                {"docs": [{"filename": "ep01.fountain", "role": "script", "corpus": SCRIPT}]},
                {"enabled": True, "replies": {"episode_names": [
                    {"synopsis": "Nimal returns.", "scenes": [{"number": 1, "title": "Nimal comes home"}]}]}}),
        },
        "frame_render": {
            "three_frames": case("Three frames are painted, stored and pinned; a redelivery paints nothing twice",
                                 {"frames": [0, 0, 1], "painter": {}, "deliveries": 2}),
            "camera_and_unreadable_sheet": case(
                "A person's camera reaches the frame; an unreadable sheet is not named (vertical)",
                {"orientation": "vertical", "frames": [0], "painter": {}, "unreadable": ["p/kamala.png"],
                 "camera_overrides": {"0": {"framing": "Close-up", "lens": "85mm"}}}),
            "refused": case("The image model declines: reported, not raised",
                            {"frames": [0], "painter": {"refuse": True}}),
            "failed": case("The provider fails: a safe message, the job still finishes",
                           {"frames": [0], "painter": {"fail": True}}),
            "no_design": case("A shot with no design is reported", {"design": False, "frames": [0], "painter": {}}),
            "not_configured": case("No painter configured is reported", {"frames": [0], "painter": None}),
            "reference_sheet": case("A character reference sheet for the current card",
                                    {"reference_entity": 0, "painter": {}}),
        },
        "script_split": {
            "rules_six_scenes": case("No key: every scene is split by rules and lines are bound",
                                     {"scenes": [0, 1, 2, 3, 4, 5]}),
            "fixed_eight_seconds": case("A fixed 8 s production",
                                        {"scenes": [0], "settings": {"fixed_shot_seconds": 8}}),
            "approved_left_alone": case("An approved scene is left alone",
                                        {"scenes": [0], "scene_fields": {"0": {"status": "approved"}}}),
            "model_plan": case(
                "The model's plan is fitted and the three critics pass it",
                {"scenes": [0]},
                {"enabled": True, "replies": {"shot_plan": [shot_plan], "shot_review": [review_ok] * 3}}),
            "critic_replan": case(
                "Critic notes drive one replan",
                {"scenes": [0]},
                {"enabled": True, "replies": {"shot_plan": [shot_plan, revised], "shot_review": [review_no] * 3}}),
            "model_down": case("The model fails: back to rules", {"scenes": [0]}, {"enabled": True}),
            "build_hop": case(
                "A build hop reports continuity and finishes the job",
                {"scenes": [2], "scene_fields": {"0": {"location_id": None}}, "cursor": 2, "job_status": "running",
                 "pipeline": ["canon_extract", "structure_build", "script_split"],
                 "state": {"build": True, "scene_ids": "all"}}),
            "stale_hop": case("A stale delivery is skipped", {"scenes": [0], "cursor": 1}),
        },
        "shot_producer": {
            "rules_design": case("Rules design every shot once; a current design is not redone; force redoes it",
                                 {"runs": [{}, {}, {"force": True}]}),
            "model_design": case("The model designs the scene in one call",
                                 {"runs": [{}]}, {"enabled": True, "dp_answer": {"scene_design": [1, 2, 3, 4]}}),
            "prompts": case(
                "Prompts need an accepted first frame and bind the lines verbatim; a rerun is a new version",
                {"accepted_frames": [2],
                 "runs": [{"mode": "prompt", "shots": [1, 2]}, {"mode": "prompt", "shots": [2]}]}),
            "chain": case("Shot ids limit the work and the state is handed on to frame_render",
                          {"runs": [{"shots": [2], "chain": True}]}),
        },
        "director_chat": {
            "explicit_retime": case("An explicit edit is applied, saved and reported",
                                    {"messages": ["make shot 2 eight seconds"]}),
            "cannot_edit": case("A role without direct is answered but nothing changes",
                                {"messages": ["make shot 2 eight seconds"], "can_edit": False}),
            "approved_scene": case("An approved scene is left alone",
                                   {"messages": ["make shot 2 eight seconds"], "scene_fields": {"status": "approved"}}),
            "resplit_offer": case("An edit that restructures most of the scene is offered as a re-split",
                                  {"messages": ["remove shot 1, remove shot 2, remove shot 3"]}),
            "refused_op": case("A refused operation is explained", {"messages": ["make shot 9 six seconds"]}),
            "standing_rule": case("A standing rule goes to production memory",
                                  {"messages": ["Remember: Kamala never cries on screen."]}),
            "scene_gone": case("A scene that is gone answers an error", {"messages": ["hi"], "gone": True}),
            "craft_board": case(
                "A craft request tasks the specialists; the owner wins a collision; the advisor disagrees",
                {"messages": ["Make this scene more intimate"],
                 "board": [{"seat": "advisor", "persona": {"name": "Lyrical Eye",
                                                           "charter": "Let place carry emotion."}}]},
                {"enabled": True, "reply": "Done. S02 now holds on Nimal.", "replies": {
                    "turn_plan": [_plan("craft", tasks=[
                        {"agent": "cinematography", "shots": [1, 2, 4], "instruction": "more intimate"},
                        {"agent": "sound", "shots": [1], "instruction": "quieter dawn"}])],
                    "cinematography_ops": [{"ops": [
                        {"op": "set", "shot": 2, "field": "framing", "value": "CU"},
                        {"op": "set", "shot": 1, "field": "sound_mode", "value": "music_only"}],
                        "note": "Closer on both."}],
                    "sound_ops": [{"ops": [{"op": "set", "shot": 1, "field": "sound_mode", "value": "silent"}],
                                   "note": "Let the dawn be silent."}],
                    "advisor_view": [{"agrees": False, "view": "I would hold the wide longer."}]}}),
        },
    }


def _plan(lane: str, ops: tuple[dict[str, Any], ...] = (), tasks: list[dict[str, Any]] | tuple[()] = (),
          memory: tuple[Any, ...] = ()) -> dict[str, Any]:
    from director_chat.engine import conductor

    return {"lane": lane, "ops": [{**dict.fromkeys(conductor.OP_FIELDS), **o} for o in ops],
            "tasks": list(tasks), "memory": list(memory)}


def all_cases() -> dict[str, dict[str, dict[str, Any]]]:
    """{service: {case name: {description, input, model}}}"""
    return _cases()

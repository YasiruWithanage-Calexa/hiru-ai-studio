"""Offline tests of the cinematic lab (plan/2026-11-06 phase 1): no model, no network, no database.

Run from the repo root:  .venv/Scripts/python.exe -m pytest lab/cinematic/tests -q
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cinematic import checks, mend, pack, render, run, schema
from cinematic.schema import CinemaWire
from contracts.david.scene import items_of, need_s

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
FAKE = LAB / "fixtures" / "fake_answer.json"


def raw_fake() -> dict[str, Any]:
    return json.loads(FAKE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def reading() -> pack.Reading:
    return pack.load(LAB / "input" / "reading.yaml")


@pytest.fixture()
def plan() -> CinemaWire:
    return CinemaWire.model_validate(raw_fake())


@pytest.fixture()
def lab_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The lab's runs folder and ledger, moved to a temp folder: a test never writes into the lab."""
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(run, "LEDGER", tmp_path / "ledger.csv")
    return tmp_path


def problems_of(items: list[Any]) -> list[str]:
    return [f"[{p.code}] {p.sentence}" for p in items]


# ── the reading and the message ──────────────────────────────────────────────────────────────────


def test_reading_is_one_scene_with_the_corrected_lines(reading: pack.Reading) -> None:
    scene = reading.scene
    assert scene.cast == ["Kasun", "Anudi", "Father"]
    assert [b.line_id for b in scene.lines] == ["L3", "L7", "L9", "L11", "L13", "L16", "L19", "L22"]
    thought = scene.line_block("L3")
    assert thought is not None and pack.is_heard(thought) and pack.is_voice_over(thought)  # "he told himself"
    narrator = scene.line_block("L22")
    assert narrator is not None and narrator.speaker == "Narrator"  # the narrator's last line is kept
    father = scene.line_block("L16")
    assert father is not None and pack.is_heard(father) and not pack.is_voice_over(father)
    assert scene.envelope_s is None  # the length is a guide, never a squeeze


def test_the_reading_keeps_the_story_words_and_invents_none(reading: pack.Reading) -> None:
    story = (LAB / "input" / "story.txt").read_text(encoding="utf-8").replace("’", "'").replace("“", '"').replace("”", '"')
    for _speaker, words in reading.words().values():
        assert words.rstrip(".") in story or words.replace("…", "...").rstrip(".") in story, words


def test_message_marks_heard_lines_and_carries_the_essence(reading: pack.Reading) -> None:
    text = pack.message(reading)
    for ln in ("L16", "L22"):
        row = next(r for r in text.splitlines() if f"[{ln}]" in r)
        assert "heard not seen" in row
    thought = next(r for r in text.splitlines() if "[L3]" in r)  # Kasun's thought: heard, but he is on screen
    assert "a thought" in thought and "heard not seen" not in thought
    assert "heard not seen" not in next(r for r in text.splitlines() if "[L7]" in r)
    assert "proud and hungry to grow" in text and "Style guide:" in text and "about 60 s" in text
    assert "<production>" in text and "<scene>" in text and "<script>" in text


# ── the answer's shape ───────────────────────────────────────────────────────────────────────────


def _walk(node: Any, path: str = "") -> list[str]:
    """Strict-mode faults in a JSON schema: an open object, a property that is not required, a $ref left."""
    faults: list[str] = []
    if isinstance(node, dict):
        if "$ref" in node:
            faults.append(f"{path}: $ref left")
        if node.get("type") == "object":
            props = node.get("properties", {})
            if node.get("additionalProperties") is not False:
                faults.append(f"{path}: open object")
            if sorted(node.get("required", [])) != sorted(props):
                faults.append(f"{path}: not every property is required")
        for k, v in node.items():
            faults += _walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            faults += _walk(v, f"{path}[{i}]")
    return faults


def test_the_schema_is_strict_and_written_in_the_order_the_team_works() -> None:
    sch = schema.output_schema()
    assert _walk(sch) == []
    assert list(sch["properties"]) == ["treatment", "sequences", "shots", "added", "staging", "end_state"]
    shot = sch["properties"]["shots"]["items"]
    assert "beats" in shot["properties"]["ir"]["properties"]  # the Veo clip design is in every shot
    assert set(shot["properties"]["size"]["enum"]) >= {"EWS", "MWS", "ECU", "POV"}


def test_the_example_is_a_different_scene_and_passes_every_check() -> None:
    example = json.loads((LAB / "prompt" / "example.json").read_text(encoding="utf-8"))
    assert example["scene"] == "refuses_money"
    wire = CinemaWire.model_validate(example["answer"])
    gold = pack.load(run.GOLD / "refuses_money.yaml")
    assert problems_of(checks.hard(gold.scene, wire)) == []
    assert 8 <= len(wire.shots) <= 10 and len(wire.sequences) == 3
    assert len([a for a in wire.added]) >= 2 and any(s.use_s < s.take_s for s in wire.shots) and wire.treatment.advice
    sentence = " ".join(wire.treatment_text()).lower() + json.dumps(example["answer"]).lower()
    assert "kasun" in sentence and "rain" not in sentence  # nothing of Episode 1 leaks into the example
    system = run.system_prompt()
    assert "Use few devices" not in system and "Restrained" not in system and "most cinematic" in system
    assert system.count("<example>") == 1 and '"..."' in system  # one example, the lines' words hidden


def test_fake_answer_passes_the_hard_checks(reading: pack.Reading, plan: CinemaWire) -> None:
    assert problems_of(checks.hard(reading.scene, plan)) == []
    assert len(plan.sequences) == 5 and len(plan.shots) >= 19
    assert {"EWS", "ECU", "POV"} <= {s.size for s in plan.shots}


# ── the checks catch what they are for ───────────────────────────────────────────────────────────


def test_a_shot_with_no_line_cannot_have_someone_speak(reading: pack.Reading, plan: CinemaWire) -> None:
    shot = plan.shot(2)
    assert shot is not None and not shot.lines
    shot.ir["beats"][0]["action"] = "Kasun speaks to the customer."
    assert any(p.code == "speaks" for p in checks.hard(reading.scene, plan))


def test_use_s_is_in_range_and_keeps_a_line_whole(reading: pack.Reading, plan: CinemaWire) -> None:
    long = plan.shot(19)  # the father's line: needs about 6.9 s
    assert long is not None and long.lines == ["L16"]
    long.use_s = 4
    plan.shot(3).use_s = 9  # type: ignore[union-attr]
    found = {p.key for p in checks.hard(reading.scene, plan)}
    assert {"use:line:19", "use:range:3"} <= found


def test_every_shot_is_in_one_sequence_and_the_colour_script_names_each(reading: pack.Reading, plan: CinemaWire) -> None:
    plan.shots[0].sequence = "Q"
    plan.treatment.colour_script.pop()
    keys = {p.key for p in checks.hard(reading.scene, plan)}
    assert "sequence:unknown:1" in keys and "colour:E" in keys


def test_a_voice_that_is_only_heard_is_never_in_frame(reading: pack.Reading, plan: CinemaWire) -> None:
    shot = plan.shot(19)
    assert shot is not None
    shot.ir["subjects"][0]["description"] = "Anudi, and her father on the phone"
    assert any(p.code == "heard" and "Father" in p.sentence for p in checks.hard(reading.scene, plan))


def test_a_stranger_named_in_the_treatment_is_found() -> None:
    second = pack.load(LAB / "input" / "second_scene.yaml")
    assert second.scene.others == ["Kasun"]
    wire = CinemaWire.model_validate(raw_fake())
    wire.treatment.logline = "Kasun waits."  # Kasun is not in the lake scene
    found = checks.hard(second.scene, wire)
    assert any(p.code == "names" for p in found)


def test_craft_measures_are_reported_not_blocking(reading: pack.Reading, plan: CinemaWire) -> None:
    got = {m.key: m for m in checks.measures(reading, plan)}
    assert got["opens"].status == "met" and got["intros"].status == "met" and got["grade"].status == "met"
    assert got["compound"].status == "met" and got["variety"].status == "met" and got["endings"].status == "met"
    assert got["objects"].status == "missed" and "umbrella" in got["objects"].detail  # the fake has no umbrella insert
    assert got["totals"].status == "info" and "guide of 60 s" in got["totals"].detail
    plan.shots[0].size = "MS"
    plan.shots[1].size = "MS"
    assert {m.key: m for m in checks.measures(reading, plan)}["opens"].status == "missed"


def test_motion_measure_flags_a_locked_off_fall_and_accepts_a_follow(reading: pack.Reading, plan: CinemaWire) -> None:
    shot = plan.shots[0]
    shot.size = "INSERT"
    shot.ir = {"beats": [{"action": "The glass falls and shatters."}], "cinematography": {"movement": "locked-off"}}
    got = {m.key: m for m in checks.measures(reading, plan)}["motion"]
    assert got.status == "missed" and "S01" in got.detail.split("locked off:")[1]
    shot.ir = {"beats": [{"action": "The glass falls and shatters."}], "cinematography": {"movement": "tilt down following the glass"}}
    assert "S01" not in {m.key: m for m in checks.measures(reading, plan)}["motion"].detail.split("locked off:")[-1]
    shot.ir = {"beats": [{"action": "She waits, listening."}], "cinematography": {"movement": "locked-off"}}
    assert "S01" not in {m.key: m for m in checks.measures(reading, plan)}["motion"].detail.split("locked off:")[-1]


def test_a_scene_is_found_by_key_gold_name_or_path() -> None:
    assert run.scene_path("episode1").name == "reading.yaml"
    assert run.scene_path("arrival").name == "arrival.yaml"
    assert run.scene_path(str(run.INPUT / "second_scene.yaml")).name == "second_scene.yaml"
    with pytest.raises(run.LabError, match="Unknown scene"):
        run.scene_path("no_such_scene")


def test_a_gold_scene_builds_a_request_without_the_episode_files() -> None:
    req = run.build_request("silent_morning", "gpt-5", "high")
    prompt = (run.PROMPT / "system.md").read_text(encoding="utf-8")  # the rules carry no name or object of one story
    words = {w.strip(".,;:()\"'`").lower() for w in prompt.split()}
    assert "<script>" in req["user"] and words.isdisjoint({"kasun", "anudi", "puddle", "umbrella", "tea", "rain"})


def test_score_puts_faults_before_craft_gaps() -> None:
    assert run.score({"counts": {"faults_left": 0, "measures_missed": 3}}) < run.score({"counts": {"faults_left": 1, "measures_missed": 0}})
    assert run.score({"counts": {"faults_left": 0, "measures_missed": 0}}) == (0, 0)


def test_auto_stops_when_clean_and_revises_from_the_best(lab_runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter([(1, 2), (2, 0), (0, 0)])  # draft; a pass that is worse; a clean pass
    calls: list[str] = []

    def fake_paid(args: Any) -> int:
        faults, gaps = next(results)
        calls.append(args.revise)
        folder = run.RUNS / f"{len(calls)}-gpt_5-high"
        folder.mkdir(parents=True)
        (folder / "checks.json").write_text(json.dumps({"counts": {"faults_left": faults, "measures_missed": gaps}}), encoding="utf-8")
        return 0

    monkeypatch.setattr(run, "cmd_paid", fake_paid)
    args = run.parser().parse_args(["auto", "--yes", "--passes", "2"])
    assert run.cmd_auto(args) == 0
    assert calls == ["", "1-gpt_5-high", "1-gpt_5-high"]  # the worse pass 1 is not built on; pass 2 starts from the draft
    assert run.cmd_auto(run.parser().parse_args(["auto"])) == 2  # without --yes nothing is called


def test_the_revise_message_carries_the_draft_and_what_code_found(lab_runs: Path) -> None:
    folder = run.RUNS / "1-test"
    folder.mkdir(parents=True)
    (folder / "answer.json").write_text('{"shots": []}', encoding="utf-8")
    (folder / "checks.json").write_text(json.dumps({
        "left": [{"sentence": "A is at the door, and by block 5 at the table.", "fix": "repair"},
                 {"sentence": "S02 asks for a mirror.", "fix": "report"}],
        "measures": [{"label": "Motion follows meaning", "detail": "locked off: S05", "status": "missed"},
                     {"label": "Opens on geography", "detail": "S01", "status": "met"}]}), encoding="utf-8")
    text = run.revise_message("1-test")
    assert '{"shots":[]}' in text and "A is at the door" in text and "locked off: S05" in text
    assert "mirror" not in text and "Opens on geography" not in text  # an advisory and a met measure are not sent


# ── the split fix (finding F8) ───────────────────────────────────────────────────────────────────


def _long_shot(plan: CinemaWire) -> CinemaWire:
    """Shot 11 made to show blocks 7 to 13 (three lines and four actions): more than the longest take."""
    shot = plan.shot(11)
    assert shot is not None
    shot.blocks, shot.lines, shot.take_s, shot.use_s = list(range(7, 14)), ["L7", "L9", "L11", "L13"], 8, 8
    shot.ir["beats"] = [
        {"time": "0-2s", "camera": "medium", "director_line": "He runs up.", "action": "Kasun holds out the phone.",
         "performance": "out of breath"},
        {"time": "2-4s", "camera": "medium", "director_line": "She turns.", "action": "Anudi turns around.",
         "performance": "surprised"},
        {"time": "4-6s", "camera": "medium", "director_line": "She looks.", "action": "Anudi studies the stall.",
         "performance": "curious"},
        {"time": "6-8s", "camera": "medium", "director_line": "He smiles.", "action": "Kasun smiles and drinks his tea.",
         "performance": "shy"}]
    plan.sequences[2] = plan.sequences[2].model_copy(update={"shots": schema.SpanW(first=11, last=17)})
    return plan


def test_a_split_shot_keeps_only_its_own_beats_and_is_silent_without_a_line(reading: pack.Reading,
                                                                           plan: CinemaWire) -> None:
    plan = _long_shot(plan)
    items = items_of(reading.scene, plan.shot(11).david())  # type: ignore[union-attr]
    assert need_s(items) > 8
    mended, done, dropped = mend.mend(reading.scene, plan)
    assert dropped == [] and any("split into" in d for d in done)
    count = len(mended.shots) - len(plan.shots) + 1  # shot 11 became this many parts, the others did not change
    parts = mended.shots[10:10 + count]
    assert count >= 2
    covered = sorted(b for s in parts for b in s.blocks)
    assert covered == list(range(7, 14))  # every block, once
    actions = [b["action"] for s in parts for b in s.ir["beats"]]
    assert len(actions) == len(set(actions)), "a beat was copied into two parts"  # the F8 bug
    for s in parts:
        assert s.ir["beats"][0]["time"].startswith("0-")  # re-timed from 0
        assert s.use_s <= s.take_s
        assert s.sound.silence == (not s.lines)
        for ln in s.lines:
            assert reading.scene.line_block(ln).index in s.blocks  # type: ignore[union-attr]
    assert [s.n for s in mended.shots] == list(range(1, len(mended.shots) + 1))
    numbers = {s.n for s in parts}  # (the later shots of this made-up plan still show the same blocks, so only the parts)
    assert [p for p in checks.hard(reading.scene, mended) if p.code in ("clock", "use") and numbers & set(p.shots)] == []
    # the sequences follow the shots that moved
    assert mended.sequences[-1].shots.last == len(mended.shots)
    assert mended.sequences[1].shots.first == 6 and mended.sequences[2].shots.last == 17 + count - 1


def test_mend_lengthens_a_short_take_and_raises_use_for_a_line(reading: pack.Reading, plan: CinemaWire) -> None:
    long = plan.shot(19)
    assert long is not None
    long.take_s, long.use_s = 4, 4  # the father's line needs 6.9 s
    mended, done, _ = mend.mend(reading.scene, plan)
    fixed = mended.shot(19)
    assert fixed is not None and fixed.take_s == 8 and fixed.use_s >= 7
    assert any("a 8 s take" in d for d in done)
    assert checks.hard(reading.scene, mended) == []


def test_mend_drops_an_addition_that_names_an_object_the_place_lacks(reading: pack.Reading, plan: CinemaWire) -> None:
    plan.added[0] = plan.added[0].model_copy(update={"object": "a golden crown"})
    mended, _, dropped = mend.mend(reading.scene, plan)
    assert [d.code for d in dropped] == ["added"] and len(mended.shots) == len(plan.shots) - 1
    assert [s.n for s in mended.shots] == list(range(1, len(mended.shots) + 1))
    assert all(q.shots.first <= q.shots.last for q in mended.sequences)


def test_mend_scrubs_a_line_quoted_in_free_text(reading: pack.Reading, plan: CinemaWire) -> None:
    plan.shots[0].why = 'He thinks "One day… I\'ll have my own restaurant."'
    mended, done, _ = mend.mend(reading.scene, plan)
    assert "restaurant" not in mended.shots[0].why and any("speech removed" in d for d in done)


# ── the money rules ──────────────────────────────────────────────────────────────────────────────


def test_a_model_with_no_price_is_refused() -> None:
    with pytest.raises(run.LabError, match="no price"):
        run.price_of("gpt-9-future")


def test_a_longer_model_name_is_not_priced_by_its_prefix() -> None:
    # gpt-5-pro and gpt-5.4 are other models: pricing them as gpt-5 would make the $5 cap wrong
    for name in ("gpt-5-pro", "gpt-5.4", "gpt-5.5-pro", "gpt-5.4-mini", "gpt-5-mini-high"):
        with pytest.raises(run.LabError, match="no price"):
            run.price_of(name)
    assert run.price_of("gpt-5-2025-08-07") == run.price_of("gpt-5")


def test_the_worst_case_counts_every_output_token_and_no_cache() -> None:
    # gpt-5: $1.25 in, $10 out per million
    assert run.worst_case("gpt-5", 10_000, 40_000) == pytest.approx(0.0125 + 0.40)
    assert run.dollars("gpt-5", 10_000, 8_000, 5_000) == pytest.approx(2_000 * 1.25e-6 + 8_000 * 0.125e-6 + 5_000 * 10e-6)


def test_a_call_is_refused_when_the_budget_cannot_hold_its_worst_case(lab_runs: Path) -> None:
    assert run.guard("gpt-5", 10_000) < run.BUDGET_USD
    run.add_to_ledger({"run": "1-x", "model": "gpt-5", "dollars": "4.70", "status": "done"})
    assert run.ledger_total() == pytest.approx(4.70)
    with pytest.raises(run.LabError, match="Refused"):
        run.guard("gpt-5", 10_000)  # worst case $0.41: 4.70 + 0.41 passes 5.00
    assert run.guard("gpt-5-mini", 10_000) < 0.2  # a cheaper call still fits


def test_the_cap_is_a_constant_not_a_flag() -> None:
    assert run.BUDGET_USD == 5.00
    assert "budget" not in {a.dest for a in run.parser()._actions}
    with pytest.raises(SystemExit):
        run.parser().parse_args(["paid", "--budget", "9"])


def test_the_key_is_stable_and_changes_with_what_decides_the_answer() -> None:
    a = run.build_request("episode1", "gpt-5", "high")
    assert a["key"] == run.build_request("episode1", "gpt-5", "high")["key"]
    assert a["key"] != run.build_request("episode1", "gpt-5", "medium")["key"]
    assert a["key"] != run.build_request("second", "gpt-5", "high")["key"]
    assert a["max_output_tokens"] == 40_000


def test_paid_needs_yes_and_never_calls_the_model_without_it(lab_runs: Path, monkeypatch: pytest.MonkeyPatch,
                                                             capsys: pytest.CaptureFixture[str]) -> None:
    def boom() -> None:
        raise AssertionError("the model was called")

    monkeypatch.setattr(run, "client", boom)
    assert run.main(["paid"]) == 2
    assert run.main(["dry"]) == 0
    out = capsys.readouterr().out
    assert "WORST case" in out and "heard not seen" in out and "ALREADY ANSWERED" not in out
    assert run.main(["models", "--x"] if False else ["ledger"]) == 0


def test_a_saved_answer_is_reused_for_free(lab_runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise AssertionError("the model was called")

    monkeypatch.setattr(run, "client", boom)
    req = run.build_request("episode1", "gpt-5", "high")
    folder = lab_runs / "1-gpt-5-high"
    folder.mkdir()
    (folder / "request.json").write_text(json.dumps(req), encoding="utf-8")
    (folder / "answer.json").write_text(FAKE.read_text(encoding="utf-8"), encoding="utf-8")
    assert run.saved_run(req["key"]) == folder
    assert run.main(["paid", "--yes"]) == 0  # no hypothesis needed: nothing is spent
    assert run.read_ledger() == [] and (folder / "plan.html").exists()


def test_after_the_first_run_a_hypothesis_is_required(lab_runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "client", lambda: (_ for _ in ()).throw(AssertionError("the model was called")))
    run.add_to_ledger({"run": "1-x", "model": "gpt-5", "dollars": "0.30", "status": "done"})
    assert run.main(["paid", "--yes"]) == 1


class _Usage:
    input_tokens, output_tokens = 10_000, 20_000
    input_tokens_details = type("D", (), {"cached_tokens": 0})()
    output_tokens_details = type("D", (), {"reasoning_tokens": 12_000})()


class _Response:
    usage = _Usage()
    status = "completed"
    output_text = FAKE.read_text(encoding="utf-8")


def test_a_paid_run_enters_its_real_usage_in_the_ledger_and_writes_what_the_person_reads(
        lab_runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class Responses:
        def create(self, **kw: Any) -> _Response:
            seen.update(kw)
            return _Response()

    monkeypatch.setattr(run, "client", lambda: type("C", (), {"responses": Responses()})())
    assert run.main(["paid", "--yes"]) == 0
    assert seen["max_output_tokens"] == 40_000 and seen["reasoning"] == {"effort": "high"}
    assert seen["text"]["format"]["strict"] is True and seen["text"]["format"]["type"] == "json_schema"
    [row] = run.read_ledger()
    assert float(row["dollars"]) == pytest.approx(0.0125 + 0.20) and row["reasoning_tokens"] == "12000"
    [folder] = [p for p in lab_runs.iterdir() if p.is_dir()]
    assert {"request.json", "answer.json", "usage.json", "checks.json", "plan.html", "notes.md"} <= {
        f.name for f in folder.iterdir()}


def test_a_failed_call_is_entered_at_its_worst_case(lab_runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Responses:
        def create(self, **kw: Any) -> None:
            raise TimeoutError("slow")

    monkeypatch.setattr(run, "client", lambda: type("C", (), {"responses": Responses()})())
    assert run.main(["paid", "--yes"]) == 1
    [row] = run.read_ledger()
    assert "failed at worst case" in row["status"] and float(row["dollars"]) > 0.3


# ── what the person reads ────────────────────────────────────────────────────────────────────────


def test_offline_renders_the_page_from_the_fake_answer(lab_runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(["offline"]) == 0
    folder = lab_runs / "offline"
    page = (folder / "plan.html").read_text(encoding="utf-8")
    for needle in ("Treatment", "Colour script", "S01", "S25", "Craft measures", "Kasun", "(heard, not seen)",
                   "One day… I&#x27;ll have my own restaurant."):
        assert needle in page
    checks_json = json.loads((folder / "checks.json").read_text(encoding="utf-8"))
    assert checks_json["counts"]["problems_left"] == 0 and checks_json["first_pass"] == []
    assert "<script" not in page.lower()


def test_the_page_escapes_what_a_model_wrote(reading: pack.Reading, plan: CinemaWire) -> None:
    plan.shots[0].why = "<script>alert(1)</script>"
    page = render.plan_html(reading, plan, found=[], measures=[], mended=[])
    assert "<script>alert" not in page and "&lt;script&gt;" in page


def test_a_bad_answer_is_reported_not_crashed(lab_runs: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"treatment": {}}', encoding="utf-8")
    assert run.main(["offline", "--answer", str(bad)]) == 1
    assert "does not fit the schema" in json.loads((lab_runs / "offline" / "checks.json").read_text("utf-8"))["error"]


def test_the_blind_page_hides_whose_plan_is_whose(reading: pack.Reading, plan: CinemaWire) -> None:
    entries = {"this plan": render.plain_list(reading, plan), "ChatGPT": "1. Wide: the road.", "David today": "1. MS: x."}
    page, key = render.side_by_side(entries, seed=3)
    assert sorted(key) == ["X", "Y", "Z"] and sorted(key.values()) == sorted(entries)
    assert "ChatGPT" not in page and "David" not in page and "this plan" not in page
    assert "Plan X" in page and "1. Wide: the road." in page
    one, _ = render.side_by_side({"this plan": "a", "ChatGPT": "  "}, seed=3)
    assert "Plan Y" not in one  # a contestant with no text is left out


def test_a_pasted_chatgpt_file_loses_the_labs_own_comment() -> None:
    assert render.comments_stripped("<!-- paste here -->\n\n1. Wide") == "1. Wide"

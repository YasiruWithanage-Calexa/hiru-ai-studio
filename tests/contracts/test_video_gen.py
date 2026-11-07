"""contracts.video_gen: engine capabilities, the three settings layers, references (binding and order), the seed, and
the request (plan/2026-11-06c Phase 1). No network: the adapters return dicts."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from contracts.veo import FrameStrategy
from contracts.video_gen import (
    DRAFT_ENGINE,
    DRAFT_RESOLUTION,
    ENGINE_CAPABILITIES,
    RefBinding,
    RefSource,
    RenderFacts,
    SeedChoice,
    SheetCandidate,
    VideoOverrides,
    VideoSettings,
    build_omni_input,
    build_request,
    build_veo_input,
    capability,
    check_render,
    cited,
    default_references,
    describe_spec,
    draw_seeds,
    final_resolutions,
    label_problem,
    request_hash,
    resolve,
    seed_note,
    spec_for,
    validate_render,
    wire_order,
)


def src(kind="canon_sheet", bucket="references", path=None, version=None) -> RefSource:
    return RefSource(kind=kind, id=uuid4(), path=path or f"p/{uuid4().hex[:6]}.png", bucket=bucket, version=version)


def ref(label: str, binds_to: UUID | None = None, slot="reference", **kw) -> RefBinding:
    return RefBinding(slot=slot, source=src(**kw), binds_to=binds_to, label=label, origin="person")


def settings(engine="omni_flash", **kw):
    locked = {k: kw.pop(k) for k in ("model", "resolution") if k in kw}  # the production's, set past validation
    return resolve(VideoSettings(engine=engine), None, VideoOverrides(**kw), production_aspect="16:9",
                   shot_seconds=8).model_copy(update=locked)


def spec(refs, engine="omni_flash", prose="Nimal opens the door.", seed=None, **kw):
    return spec_for(settings(engine, **kw), prose=prose, references=refs, seed=seed)


def blocking(checks) -> list[str]:
    return [c.label for c in checks if c.tone == "fail"]


# ── attached == cited, in order, for every engine ──────────────────────────────────────────────────────────────


def test_omni_cites_exactly_what_it_attaches_in_the_persons_order():
    a, b, c = ref("the character sheet for Nimal"), ref("the location plate for the kitchen"), ref("a red kettle")
    start = ref("the opening frame", slot="first_frame", kind="accepted_frame", bucket="frames")
    end = ref("the closing frame", slot="last_frame", kind="accepted_frame", bucket="frames")
    built = build_omni_input(spec([start, a, end, b, c]))

    tags = [p["tag"] for p in built["references"]]
    assert tags == ["<IMAGE_REF_0>", "<IMAGE_REF_1>", "<IMAGE_REF_2>", "<FIRST_FRAME>", "<LAST_FRAME>"]
    assert [p["source_id"] for p in built["references"]] == [str(x.source.id) for x in (a, b, c, start, end)]
    assert cited(built) == tags  # attached == cited, same order
    assert "<IMAGE_REF_0> is the character sheet for Nimal." in built["prompt"]
    assert "<FIRST_FRAME> is the literal opening frame: the opening frame." in built["prompt"]


def test_reordering_renumbers_the_tags_and_never_sorts_or_dedupes():
    a, b = ref("the character sheet for Nimal"), ref("the location plate for the kitchen")
    same = RefBinding(slot="reference", source=a.source, label="Nimal again")  # the same picture twice stays twice
    one = build_omni_input(spec([a, b, same]))
    two = build_omni_input(spec([b, a, same]))
    assert [p["path"] for p in one["references"]] == [a.source.path, b.source.path, a.source.path]
    assert [p["path"] for p in two["references"]] == [b.source.path, a.source.path, a.source.path]
    assert "<IMAGE_REF_0> is the location plate for the kitchen." in two["prompt"]
    assert "<IMAGE_REF_1> is the character sheet for Nimal." in two["prompt"]


def test_veo_names_pictures_by_position_and_puts_frames_in_their_slots():
    a, b = ref("the character sheet for Nimal"), ref("the location plate for the kitchen")
    built = build_veo_input(spec([a, b], engine="veo_3_1", duration_s=8))
    assert "Reference images, in order: image 1 is the character sheet for Nimal; image 2 is the location plate" \
        in built["prompt"]
    assert [p["slot"] for p in built["references"]] == ["reference", "reference"]
    assert [p["path"] for p in built["references"]] == [a.source.path, b.source.path]
    assert all(p["tag"] == "" for p in built["references"])


@pytest.mark.parametrize("engine", sorted(ENGINE_CAPABILITIES))
def test_every_engine_has_an_adapter_and_the_prose_is_untouched(engine):
    s = spec([ref("the character sheet for Nimal")], engine=engine, prose="  Nimal opens the door.  ")
    built = build_request(s)
    assert built["prompt"].startswith("Nimal opens the door.")
    assert built["model"] == capability(engine).model


def test_no_references_means_no_citation_block():
    assert build_omni_input(spec([]))["prompt"] == "Nimal opens the door."


def test_wire_order_is_references_then_start_then_end():
    a = ref("a")
    start = ref("s", slot="first_frame")
    end = ref("e", slot="last_frame")
    assert [b.slot for b in wire_order([end, start, a])] == ["reference", "first_frame", "last_frame"]


# ── labels are words ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("label", ["C01", "the sheet for C01", "3f2c1a9e-1111-4222-8333-444455556666",
                                   "frames/abc/def.png", "a1b2c3d4e5f6a7b8", "https://x.test/a", ""])
def test_a_label_that_would_be_drawn_as_lettering_is_refused(label):
    assert label_problem(label)
    assert blocking(validate_render(spec([ref(label)])))


@pytest.mark.parametrize("label", ["the character sheet for Nimal", "the look sheet for Mrs. Perera",
                                   "the location plate for the old kitchen", "ඇය වාඩි වී සිටී"])
def test_names_pass(label):
    assert label_problem(label) is None


# ── three layers ─────────────────────────────────────────────────────────────────────────────────────────────


def test_layers_merge_field_by_field_and_say_where_each_value_came_from():
    prod = VideoSettings(engine="veo_3_1", resolution="1080p", options={"person_generation": "allow_adult"})
    shot = VideoOverrides(options={"person_generation": "allow_all"}, duration_s=8)
    run = VideoOverrides(duration_s=6)
    got = resolve(prod, shot, run, production_aspect="9:16", shot_seconds=8)
    assert (got.engine, got.resolution, got.takes, got.duration_s, got.aspect_ratio) == (
        "veo_3_1", "1080p", 1, 6, "9:16")
    assert got.options == {"person_generation": "allow_all"}
    assert got.sources["engine"] == "production" and got.sources["resolution"] == "production"
    assert got.sources["duration_s"] == "run" and got.sources["model"] == "code"
    assert got.sources["aspect_ratio"] == "production" and got.sources["options.person_generation"] == "shot"
    assert resolve(prod, None, None, production_aspect="16:9", shot_seconds=4).sources["duration_s"] == "code"


def test_the_model_and_size_are_the_productions_alone():
    for locked in ({"engine": "omni_flash"}, {"model": "veo-3.1-generate-002"}, {"resolution": "720p"}):
        with pytest.raises(ValueError):
            VideoOverrides(**locked)
    with pytest.raises(ValueError):
        VideoOverrides(takes=2)  # one video a press
    for bad in ({"engine": "veo_3_1", "resolution": "360p"}, {"resolution": "360p"}, {"resolution": "4k"},
                {"engine": "nope"}):
        with pytest.raises(ValueError):
            VideoSettings(**bad)  # type: ignore[arg-type]
    assert final_resolutions("omni_flash") == ("720p", "1080p") and final_resolutions("veo_3_1") == ("720p", "1080p")


def test_a_draft_is_omni_flash_at_360p_and_leaves_another_engines_knobs_behind():
    veo = VideoSettings(engine="veo_3_1", resolution="1080p", model="veo-3.1-generate-002", negative_prompt="no text",
                        options={"person_generation": "allow_adult"})
    got = resolve(veo, None, VideoOverrides(duration_s=8), production_aspect="16:9", shot_seconds=4, draft=True)
    assert (got.engine, got.model, got.resolution, got.draft) == (DRAFT_ENGINE, None, DRAFT_RESOLUTION, True)
    assert got.options == {} and got.negative_prompt == "" and got.duration_s == 8
    assert got.sources["engine"] == got.sources["resolution"] == got.sources["model"] == "draft"
    assert not [k for k in got.sources if k.startswith("options.")]
    draft = spec_for(got, prose="Nimal opens the door.", references=[])
    assert draft.draft and draft.model == "gemini-omni-1.1-flash" and not blocking(validate_render(draft))
    assert describe_spec(draft).startswith("Draft · Omni Flash · 360p")
    real = spec_for(resolve(veo, None, None, production_aspect="16:9", shot_seconds=8), prose="x", references=[])
    assert not real.draft and real.model == "veo-3.1-generate-002"
    assert request_hash(draft) != request_hash(draft.model_copy(update={"draft": False}))

    omni = VideoSettings(model="gemini-omni-9", negative_prompt="no text")
    got = resolve(omni, None, None, production_aspect="16:9", shot_seconds=8, draft=True)
    assert got.model == "gemini-omni-9" and got.negative_prompt == "no text", "same engine: its own settings stay"


def test_an_empty_run_override_clears_a_lower_negative_prompt():
    prod = VideoSettings(negative_prompt="no text")
    assert resolve(prod, None, VideoOverrides(negative_prompt=""), production_aspect="16:9",
                   shot_seconds=8).negative_prompt == ""


def test_a_model_id_is_checked():
    with pytest.raises(ValueError):
        VideoSettings(model="x; drop table")
    assert VideoSettings(model="veo-3.1-generate-002", engine="veo_3_1").model == "veo-3.1-generate-002"


# ── blocking checks, never silent snapping ───────────────────────────────────────────────────────────────────


def test_veo_takes_references_only_at_eight_seconds_and_says_so():
    s = spec([ref("the character sheet for Nimal")], engine="veo_3_1", duration_s=6)
    assert any("only at 8 s; this shot is 6 s" in m for m in blocking(validate_render(s)))
    assert s.duration_s == 6  # not moved
    assert not blocking(validate_render(spec([ref("the character sheet for Nimal")], engine="veo_3_1", duration_s=8)))


def test_veo_1080p_and_an_end_frame_also_need_eight_seconds():
    assert blocking(validate_render(spec([], engine="veo_3_1", resolution="1080p", duration_s=4)))
    end = ref("the closing frame", slot="last_frame")
    assert blocking(validate_render(spec([end], engine="veo_3_1", duration_s=4)))


def test_caps_and_modes_are_enforced():
    many = [ref(f"the sheet for person {chr(65 + i)}") for i in range(11)]
    assert any("at most 10" in m for m in blocking(validate_render(spec(many))))
    veo = spec([ref("the character sheet for Nimal"), ref("a start", slot="first_frame")], engine="veo_3_1",
               duration_s=8)
    assert any("either reference pictures or a start frame" in m for m in blocking(validate_render(veo)))
    omni_both = spec([ref("a", slot="first_frame"), ref("the character sheet for Nimal")])
    assert any("either reference pictures or a start frame" in m for m in blocking(validate_render(omni_both))), \
        "Omni's image-to-video takes at most 2 images: the frames (a live 400, 2026-11-06)"
    assert not blocking(validate_render(spec([ref("a", slot="first_frame"), ref("b", slot="last_frame")])))
    assert not blocking(validate_render(spec([ref("the character sheet for Nimal"), ref("the plate for the kitchen")])))
    two = spec([ref("a", slot="first_frame"), ref("b", slot="first_frame")])
    assert any("Only one picture can be the start frame" in m for m in blocking(validate_render(two)))


def test_ten_seconds_stays_off():
    assert any("10 s cannot be rendered" in m for m in blocking(validate_render(spec([], duration_s=10))))
    assert capability("omni_flash").durations == (4, 6, 8)


def test_unknown_engine_aspect_resolution_prompt_negative_and_options():
    assert blocking(validate_render(spec([]).model_copy(update={"engine": "nope"})))
    assert blocking(validate_render(spec([], aspect_ratio="1:1")))
    assert blocking(validate_render(spec([], resolution="4k")))
    assert blocking(validate_render(spec([], prose="  ")))
    assert any("negative prompt" in m for m in blocking(validate_render(spec([], negative_prompt="blur"))))
    assert any("no setting called" in m for m in blocking(validate_render(spec([], options={"zoom": 1}))))
    bad = spec([], engine="veo_3_1", options={"person_generation": "everyone"})
    assert any("not a choice" in m for m in blocking(validate_render(bad)))
    assert not blocking(validate_render(spec([], engine="veo_3_1", options={"person_generation": "allow_all"})))


def test_a_clean_request_has_no_blocking_check():
    assert validate_render(spec([ref("the character sheet for Nimal")])) == []


# ── checks report, never edit ─────────────────────────────────────────────────────────────────────────────────


def test_checks_name_what_will_drift_or_is_missing_and_change_nothing():
    nimal, kamala, gate = uuid4(), uuid4(), uuid4()
    refs = [ref("the character sheet for Kamala", binds_to=kamala, version=1),
            ref("the second sheet for Kamala", binds_to=kamala, version=2),
            ref("the look sheet for Nimal", binds_to=nimal, version=3)]
    facts = RenderFacts(seen={nimal: "Nimal", kamala: "Kamala", gate: "Ruwan"},
                        names={nimal: "Nimal", kamala: "Kamala", gate: "Ruwan"},
                        current_versions={kamala: 2, nimal: 3}, frame_stale=["the script changed"])
    s = spec(refs, prose="Nimal opens the door.")
    labels = [c.label for c in check_render(s, facts)]
    assert "Image 1 is Kamala; the prompt never mentions them. The picture will drift the frame." in labels
    assert "Kamala has 2 reference pictures." in labels
    assert "Ruwan is in the shot but has no reference picture." in labels
    assert any("older card (v1; now v2)" in label for label in labels)
    assert not any("Nimal" in label and "drift" in label for label in labels)
    assert s.prose == "Nimal opens the door."  # the prose is never rewritten
    assert all(c.tone == "advisory" for c in check_render(s, facts))


def test_a_stale_start_frame_is_only_reported_when_there_is_one():
    facts = RenderFacts(frame_stale=["the script changed"])
    assert check_render(spec([]), facts) == []
    start = ref("the opening frame", slot="first_frame", kind="accepted_frame", bucket="frames")
    assert [c.label for c in check_render(spec([start]), facts)] == [
        "The start frame is out of date: the script changed."]


# ── the default list follows the frame rule ───────────────────────────────────────────────────────────────────


def cand(kind, name, seen=True, sheet=True, look=False):
    return SheetCandidate(entity_id=uuid4(), kind=kind, name=name, seen=seen,
                          sheet=src() if sheet else None, look_sheet=src("look_sheet") if look else None)


def test_default_list_is_the_people_seen_then_the_place_then_props_with_a_look_before_the_base_sheet():
    cap = capability("omni_flash")
    place, prop = cand("location", "the kitchen"), cand("prop", "the kettle")
    nimal, kamala = cand("character", "Nimal", look=True), cand("character", "Kamala")
    got = default_references(cap=cap, strategy=FrameStrategy.GENERATE, accepted_frame=None, carried_frame=None,
                             candidates=[place, prop, nimal, kamala])
    assert [b.label for b in got.bindings] == ["the look sheet for Nimal", "the character sheet for Kamala",
                                               "the location plate for the kitchen",
                                               "the reference sheet for the kettle"]
    assert got.bindings[0].source.kind == "look_sheet" and got.bindings[0].binds_to == nimal.entity_id
    assert all(b.origin == "code" and b.slot == "reference" for b in got.bindings)


def test_someone_only_heard_is_never_attached():
    cap = capability("omni_flash")
    got = default_references(cap=cap, strategy=FrameStrategy.GENERATE, accepted_frame=None, carried_frame=None,
                             candidates=[cand("character", "Nimal"),
                                         cand("character", "Voice on the phone", seen=False)])
    assert [b.label for b in got.bindings] == ["the character sheet for Nimal"]
    assert got.left_out == []


def test_an_engine_that_takes_a_start_frame_or_references_keeps_the_frame_and_lists_the_sheets():
    cap = capability("veo_3_1")
    assert not cap.refs_with_first_frame
    got = default_references(cap=cap, strategy=FrameStrategy.GENERATE, accepted_frame=src("accepted_frame", "frames"),
                             carried_frame=None, candidates=[cand("character", "Nimal")])
    assert [b.slot for b in got.bindings] == ["first_frame"]
    assert got.left_out == [
        "the character sheet for Nimal (Veo 3.1 takes a start frame or reference pictures, not both)"]
    assert validate_render(spec(got.bindings, engine="veo_3_1", duration_s=8)) == []
    without = default_references(cap=cap, strategy=FrameStrategy.GENERATE, accepted_frame=None, carried_frame=None,
                                 candidates=[cand("character", "Nimal")])
    assert [b.slot for b in without.bindings] == ["reference"] and without.left_out == []


def test_the_engine_cap_cuts_and_the_cut_is_listed():
    cap = capability("veo_3_1")  # three references
    people = [cand("character", n) for n in ("Nimal", "Kamala", "Ruwan", "Sena")]
    got = default_references(cap=cap, strategy=FrameStrategy.GENERATE, accepted_frame=None, carried_frame=None,
                             candidates=[*people, cand("location", "the kitchen")])
    assert len(got.bindings) == 3
    assert got.left_out == ["the character sheet for Sena", "the location plate for the kitchen"]


def test_an_entity_without_a_sheet_is_skipped_not_guessed():
    got = default_references(cap=capability("omni_flash"), strategy=FrameStrategy.GENERATE, accepted_frame=None,
                             carried_frame=None, candidates=[cand("character", "Nimal", sheet=False)])
    assert got.bindings == []


def test_the_start_frame_is_the_accepted_one_or_the_carried_last_frame_only_when_carrying_on():
    cap = capability("omni_flash")
    accepted, carried = src("accepted_frame", "frames"), src("take_last_frame", "takes")
    got = default_references(cap=cap, strategy=FrameStrategy.GENERATE, accepted_frame=accepted, carried_frame=carried,
                             candidates=[])
    assert got.bindings[0].slot == "first_frame" and got.bindings[0].source is accepted
    none = default_references(cap=cap, strategy=FrameStrategy.GENERATE, accepted_frame=None, carried_frame=carried,
                              candidates=[])
    assert none.bindings == []
    carry = default_references(cap=cap, strategy=FrameStrategy.CARRY_LAST_FRAME, accepted_frame=None,
                               carried_frame=carried, candidates=[])
    assert carry.bindings[0].source is carried and carry.bindings[0].label == "the last frame of the shot before"
    assert label_problem(carry.bindings[0].label) is None


def test_the_default_list_for_veo_is_valid_at_eight_seconds():
    cap = capability("veo_3_1")
    got = default_references(cap=cap, strategy=FrameStrategy.GENERATE, accepted_frame=None, carried_frame=None,
                             candidates=[cand("character", "Nimal"), cand("location", "the kitchen")])
    assert validate_render(spec(got.bindings, engine="veo_3_1", duration_s=8)) == []


# ── the seed ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_random_draws_one_seed_per_take_and_they_are_in_range():
    values = iter([5, 6, 7])
    assert draw_seeds(SeedChoice(), 3, draw=lambda _n: next(values)) == [5, 6, 7]
    real = draw_seeds(SeedChoice(), 4)
    assert len(real) == 4 and all(0 <= s < 2**32 for s in real)


def test_fixed_adds_the_take_index_and_from_take_starts_from_that_take():
    assert draw_seeds(SeedChoice(mode="fixed", value=1234), 3) == [1234, 1235, 1236]
    assert draw_seeds(SeedChoice(mode="from_take", take_id=uuid4()), 2, take_seed=99) == [99, 100]
    with pytest.raises(ValueError):
        draw_seeds(SeedChoice(mode="from_take", take_id=uuid4()), 1)
    with pytest.raises(ValueError):
        draw_seeds(SeedChoice(mode="fixed"), 1)


def test_a_seed_beyond_the_range_is_refused():
    with pytest.raises(ValueError):
        SeedChoice(mode="fixed", value=2**32)
    edge = spec([], engine="veo_3_1")
    assert blocking(validate_render(edge, seed_choice=SeedChoice(mode="fixed", value=2**32 - 1), takes=2))


def test_an_engine_that_takes_no_seed_gets_no_seed_and_says_so():
    omni = capability("omni_flash")
    assert omni.seed == "none"
    s = spec([], engine="omni_flash", seed=77)
    assert s.seed is None and "seed" not in build_request(s)["config"]
    assert seed_note("omni_flash") == "This model does not take a seed: every take is new."
    assert blocking(validate_render(s, seed_choice=SeedChoice(mode="fixed", value=1)))
    assert not blocking(validate_render(s, seed_choice=SeedChoice()))  # random is fine: nothing is sent
    veo = spec([], engine="veo_3_1", seed=77)
    assert build_request(veo)["config"]["seed"] == 77
    assert "not proven" in seed_note("veo_3_1")


# ── identity of a request ─────────────────────────────────────────────────────────────────────────────────────


def test_request_hash_changes_with_order_prose_and_seed_but_not_with_label_case_of_origin():
    a, b = ref("the character sheet for Nimal"), ref("the location plate for the kitchen")
    base = request_hash(spec([a, b]))
    assert request_hash(spec([a, b])) == base
    assert request_hash(spec([b, a])) != base
    assert request_hash(spec([a, b], prose="Different.")) != base
    assert request_hash(spec([a, b], resolution="1080p")) != base
    s1, s2 = spec([a], engine="veo_3_1", seed=1, duration_s=8), spec([a], engine="veo_3_1", seed=2, duration_s=8)
    assert request_hash(s1) != request_hash(s2)
    assert request_hash(s1, with_seed=False) == request_hash(s2, with_seed=False)
    again = s1.model_copy(update={"references": [a.model_copy(update={"origin": "code"})]})
    assert request_hash(again) == request_hash(s1)  # who put it there is not part of what was sent


def test_a_spec_round_trips_through_json_with_no_image_bytes():
    s = spec([ref("the character sheet for Nimal"), ref("a", slot="first_frame")], seed=None)
    again = type(s).model_validate_json(s.model_dump_json())
    assert again == s and request_hash(again) == request_hash(s)

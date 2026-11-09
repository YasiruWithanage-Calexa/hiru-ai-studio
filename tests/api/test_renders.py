"""Making a take in Hiru (plan/2026-11-06c Phase 4): the plan, the checks, the settings layers, a person's own
reference list, the seed, the job, make-again, and the handoff view. No network: the job is captured and the provider is
never reached."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from api.config import Settings, VideoSettings, get_settings
from api.routers import handoff as handoff_router
from api.services.assemble import get_assembler
from api.services.renders import STALE_ERROR, UNAVAILABLE
from api.workers import task_manager
from contracts.video_gen import RenderSpec, request_hash
from tests.api.conftest import World
from tests.api.test_handoff import FakeAssembler
from tests.api.test_production import _accept_one, design, open_scene, shot_url, states, url

PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"0" * 32


_FIRED: list[list[dict]] = []


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []
    _FIRED[:] = [calls]
    monkeypatch.setattr(task_manager, "_fire_local",
                        lambda u, payload: calls.append({"url": u, **payload.model_dump(mode="json")}))
    return calls


def _settings(**video: object) -> Settings:
    return get_settings().model_copy(update={"video": VideoSettings(**video)})  # type: ignore[arg-type]


@pytest.fixture
def video(world: World, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """The fake provider is on: Generate can be pressed. (Without it the API says video is not set up.)"""
    settings = _settings(fake_provider=True)
    world.client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    monkeypatch.setattr(handoff_router, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def assembler(world: World) -> FakeAssembler:
    fake = FakeAssembler(world, duration=7.5)
    world.client.app.dependency_overrides[get_assembler] = lambda: fake  # type: ignore[attr-defined]
    return fake


def _good_prompt(world: World, s: dict, n: int, fid: str) -> None:
    """A stored prompt that passes the handoff checks: its Sinhala segments are the shot's lines, word for word."""
    st = next(x for x in states(world, s) if x.id == s["shots"][n]["id"])
    lines = [i.text for i in st.items if i.is_line]
    prose = "Nimal opens the door of Kamala's house and looks for her. " + " ".join(lines) + " Aspect ratio 16:9."
    world.repos.prompts.add(production_id=str(world.production), shot_id=st.id, version=1,  # type: ignore[attr-defined]
                            sections=[{"id": "action", "title": "Action", "segments": [{"sinhala": t} for t in lines]}],
                            prose=prose, model="Veo 3.1 · 4 s · 16:9", checks=[], frame_id=fid,
                            pins=st.pins.model_dump(), camera=st.camera.model_dump())


def _sheets(world: World, s: dict) -> dict[str, str]:
    """Give every card a character sheet / place plate in the references bucket → {name: entity id}."""
    ids = {}
    for row in list(world.repos.canon.rows.values()):  # type: ignore[attr-defined]
        asyncio.run(world.repos.canon.add_version(UUID(row["id"]), {
            "entity_id": row["id"], "version": 1, "card": {}, "wardrobe_anchor": "", "voice_pin": "",
            "reference_assets": [{"path": f"{world.production}/{row['id']}/sheet-a.png"},
                                 {"path": f"{world.production}/{row['id']}/sheet-b.png"}]}))
        ids[row["name"]] = row["id"]
    return ids


def ready(world: World, n: int = 1) -> tuple[dict, dict[str, str]]:
    s = open_scene(world)
    design(world, s)
    ids = _sheets(world, s)
    fid = _accept_one(world, s, n)
    world.repos.frames.rows[fid]["storage_path"] = f"{world.production}/{s['shots'][n]['id']}/{fid}.png"  # type: ignore[attr-defined]
    _good_prompt(world, s, n, fid)
    for calls in _FIRED:
        calls.clear()  # the frame was asked for to set the scene up: only what a test does counts
    return s, ids


def on(world: World, **video: object) -> None:
    """The production's video settings. Its model and size are chosen when it is created; tests set them here."""
    prod = world.repos.productions.rows[str(world.production)]  # type: ignore[attr-defined]
    prod["settings"] = {**(prod.get("settings") or {}), "video": video}


def sheets_only(world: World, s: dict, n: int = 1) -> list[dict]:
    """A person's list of one sheet per card (no start frame) in the order the catalog offers them, saved on the shot.
    Omni and Veo take a start frame OR reference pictures, so Hiru's own choice is the start frame alone."""
    seen: set[str] = set()
    out = []
    for c in plan(world, s, n)["catalog"]:
        if c["kind"] in ("canon_sheet", "look_sheet") and c["binds_to"] and c["binds_to"] not in seen:
            seen.add(c["binds_to"])
            out.append({"slot": "reference", "kind": c["kind"], "id": c["id"], "binds_to": c["binds_to"],
                        "label": c["label"]})
    r = world.client.put(shot_url(world, s, n, "/video-settings"), json={"references": out},
                         headers=world.headers(world.director))
    assert r.status_code == 200, r.text
    return out


def plan(world: World, s: dict, n: int = 1, who: UUID | None = None, query: str = "") -> dict:
    r = world.client.get(shot_url(world, s, n, "/render-plan" + query), headers=world.headers(who or world.reviewer))
    assert r.status_code == 200, r.text
    return r.json()


def labels(checks: list[dict], tone: str) -> list[str]:
    return [c["label"] for c in checks if c["tone"] == tone]


def refs_in(plan_view: dict, *, drop: int | None = None) -> list[dict]:
    """The plan's references in the shape the browser sends back (kind and id, never a path)."""
    out = [{"slot": r["slot"], "kind": r["kind"], "id": r["id"], "binds_to": r["binds_to"], "label": r["label"]}
           for r in plan_view["references"]]
    return out if drop is None else [r for i, r in enumerate(out) if i != drop]


# ── the plan ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_plan_shows_the_exact_request_with_pictures_in_order_and_no_paths(world: World, video: Settings):
    s, ids = ready(world)
    v = plan(world, s)
    assert v["available"] and v["ready"], labels(v["checks"], "fail")
    assert v["settings"]["engine"] == "omni_flash" and v["settings"]["resolution"] == "720p"
    assert v["settings"]["aspect_ratio"] == "16:9" and v["settings"]["duration_s"] == 4
    assert v["settings"]["sources"]["aspect_ratio"] == "production" and v["settings"]["sources"]["duration_s"] == "code"
    assert v["references_origin"] == "hiru"

    # Omni takes a start frame OR reference pictures (a frame + sheets is a live 400), so Hiru sends the accepted frame,
    # which was painted from those sheets, and says which sheets it left out, people seen first, then the place.
    got = v["references"]
    assert [(r["slot"], r["tag"], r["label"]) for r in got] == [("first_frame", "start frame", "the opening frame")]
    left = v["left_out"]
    assert all("Omni Flash takes a start frame or reference pictures, not both" in x for x in left)
    nimal = next(i for i, x in enumerate(left) if "Nimal" in x)
    house = next(i for i, x in enumerate(left) if "Kamala's house" in x)
    assert nimal < house, "the people seen, then the place"
    assert "<FIRST_FRAME> is the literal opening frame: the opening frame." in v["request"]["prompt"]
    assert "<IMAGE_REF_" not in v["request"]["prompt"]
    assert all(r["url"] and "/files/" in r["url"] for r in got)

    # a person's sheets-only list goes as reference pictures, cited in order
    sheets_only(world, s)
    v = plan(world, s)
    got = v["references"]
    assert [r["tag"] for r in got] == [f"<IMAGE_REF_{i}>" for i in range(len(got))] and v["ready"]
    bound = [r["binds_to"] for r in got]
    assert ids["Nimal"] in bound and ids["Kamala's house"] in bound
    assert "Reference images:\n<IMAGE_REF_0> is the character sheet for" in v["request"]["prompt"]

    raw = str(v)
    assert str(world.production) not in raw.replace("production_id", ""), "no storage path reaches a browser"
    assert "sheet-a.png" not in raw and "storage_path" not in raw
    for word in ("cost", "price", "credit", "$"):
        assert word not in raw.lower(), "the UI shows no costs"


def test_the_catalog_offers_other_pictures_of_the_same_card(world: World, video: Settings):
    s, ids = ready(world)
    v = plan(world, s)
    nimal = [c for c in v["catalog"] if c["binds_to"] == ids["Nimal"]]
    assert len(nimal) == 2 and {c["label"] for c in nimal} == {"the character sheet for Nimal"}


def test_without_a_key_the_plan_says_video_is_not_set_up(world: World, monkeypatch: pytest.MonkeyPatch):
    settings = _settings()
    world.client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    s, _ = ready(world)
    v = plan(world, s)
    assert not v["available"] and not v["ready"] and v["unavailable_reason"] == UNAVAILABLE
    assert UNAVAILABLE in labels(v["checks"], "fail")
    r = world.client.post(shot_url(world, s, 1, "/renders"), json={}, headers=world.headers(world.director))
    assert r.status_code == 422 and UNAVAILABLE in str(r.json())


def test_the_model_and_size_are_the_productions_and_a_shot_or_a_press_cannot_change_them(world: World,
                                                                                           video: Settings,
                                                                                           fired: list[dict]):
    s, _ = ready(world)
    on(world, engine="veo_3_1", resolution="1080p")
    v = plan(world, s)
    assert v["settings"]["engine"] == "veo_3_1" and v["settings"]["sources"]["engine"] == "production"
    assert v["settings"]["resolution"] == "1080p" and v["settings"]["takes"] == 1

    director = world.headers(world.director)
    for locked in ({"engine": "omni_flash"}, {"resolution": "720p"}, {"model": "veo-3.1-generate-002"}):
        assert world.client.put(shot_url(world, s, 1, "/video-settings"), json={"settings": locked},
                                headers=director).status_code == 422
        assert world.client.get(shot_url(world, s, 1, "/render-plan?overrides=" + json.dumps(locked)),
                                headers=director).status_code == 422
        assert world.client.post(shot_url(world, s, 1, "/renders"), json={"overrides": locked},
                                 headers=director).status_code == 422
    assert not fired

    r = world.client.put(shot_url(world, s, 1, "/video-settings"), json={"settings": {"duration_s": 8}},
                         headers=director)
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["duration_s"] == 8 and r.json()["settings"]["sources"]["duration_s"] == "shot"
    v = plan(world, s, query='?overrides={"duration_s":6}')
    assert v["settings"]["duration_s"] == 6 and v["settings"]["sources"]["duration_s"] == "run"
    assert plan(world, s)["settings"]["duration_s"] == 8, "a preview does not save"
    assert world.client.get(shot_url(world, s, 1, "/render-plan?overrides=not-json"),
                            headers=world.headers(world.reviewer)).status_code == 422


def test_a_value_the_engine_cannot_take_is_a_blocking_check_never_a_silent_change(world: World, video: Settings):
    s, _ = ready(world)
    on(world, engine="veo_3_1", resolution="1080p")
    v = plan(world, s, query='?overrides={"duration_s":6}')
    assert not v["ready"] and v["settings"]["duration_s"] == 6 and v["settings"]["resolution"] == "1080p"
    assert any("only at 8 s; this shot is 6 s" in c for c in labels(v["checks"], "fail"))
    assert [c["tone"] for c in v["checks"]] == sorted((c["tone"] for c in v["checks"]),
                                                      key=lambda t: {"fail": 0, "advisory": 1, "pass": 2}[t])


# ── drafts ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_draft_is_omni_flash_at_360p_whatever_the_productions_model(world: World, video: Settings,
                                                                     fired: list[dict]):
    s, _ = ready(world)
    on(world, engine="veo_3_1", resolution="1080p", options={"person_generation": "allow_adult"},
       negative_prompt="no text")
    v = plan(world, s, query="?draft=true")
    assert (v["settings"]["engine"], v["settings"]["resolution"]) == ("omni_flash", "360p")
    assert v["settings"]["sources"]["engine"] == v["settings"]["sources"]["resolution"] == "draft"
    assert v["settings"]["options"] == {} and v["settings"]["negative_prompt"] == "", "Veo's own knobs stay on Veo"
    assert v["ready"], labels(v["checks"], "fail")
    assert plan(world, s)["settings"]["engine"] == "veo_3_1", "the production's take is unchanged"

    r = world.client.post(shot_url(world, s, 1, "/renders"), json={"draft": True, "request_hash": v["request_hash"]},
                          headers=world.headers(world.director))
    assert r.status_code == 202, r.text
    (row,) = world.repos.renders.rows.values()  # type: ignore[attr-defined]
    assert row["engine"] == "omni_flash" and row["spec"]["resolution"] == "360p" and row["spec"]["draft"] is True
    assert row["request_hash"] == request_hash(RenderSpec.model_validate(row["spec"]))
    assert r.json()["renders"][0]["settings_text"].startswith("Draft · Omni Flash · 360p")
    assert any(a["action"] == "video.draft" for a in world.repos.audit.entries)  # type: ignore[attr-defined]
    assert len(fired) == 1


def test_a_draft_and_the_real_take_are_different_requests(world: World, video: Settings, fired: list[dict]):
    s, _ = ready(world)
    real, draft = plan(world, s)["request_hash"], plan(world, s, query="?draft=true")["request_hash"]
    assert real != draft
    r = world.client.post(shot_url(world, s, 1, "/renders"), json={"draft": True, "request_hash": real},
                          headers=world.headers(world.director))
    assert r.status_code == 409 and not fired


def test_veo_keeps_the_start_frame_and_lists_the_sheets_it_cannot_take_with_it(world: World, video: Settings):
    s, _ = ready(world)
    on(world, engine="veo_3_1")
    v = plan(world, s, query='?overrides={"duration_s":8}')
    assert [r["slot"] for r in v["references"]] == ["first_frame"] and v["ready"], labels(v["checks"], "fail")
    assert all("takes a start frame or reference pictures, not both" in x for x in v["left_out"]) and v["left_out"]
    assert v["request"]["config"]["duration_seconds"] == 8


def test_checks_name_a_person_the_prompt_never_mentions(world: World, video: Settings):
    s, _ = ready(world)
    prompt = next(iter(world.repos.prompts.rows.values()))  # type: ignore[attr-defined]
    prompt["prose"] = "A door opens. Aspect ratio 16:9."
    sheets_only(world, s)
    v = plan(world, s)
    drift = [c for c in labels(v["checks"], "advisory") if "never mentions them" in c]
    assert any(c.startswith("Image 1 is ") for c in drift) and v["ready"], "advice does not block"


def test_a_production_the_caller_cannot_see_is_404(world: World, video: Settings):
    s, _ = ready(world)
    r = world.client.get(shot_url(world, s, 1, "/render-plan"), headers=world.headers(world.outsider))
    assert r.status_code == 404


# ── a person's own list ────────────────────────────────────────────────────────────────────────────────────────


def test_a_person_reorders_relabels_and_removes_and_the_tags_follow(world: World, video: Settings):
    s, _ = ready(world)
    director = world.headers(world.director)
    hiru = refs_in(plan(world, s))
    sheets_only(world, s)
    v = plan(world, s)
    base = refs_in(v)
    assert len(base) >= 3
    mine = [base[1], base[0], *base[2:]]  # swap the first two
    mine[0] = {**mine[0], "label": "the woman in the cream blouse"}
    r = world.client.put(shot_url(world, s, 1, "/video-settings"), json={"references": mine}, headers=director)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["references_origin"] == "person"
    assert [x["id"] for x in got["references"][:2]] == [base[1]["id"], base[0]["id"]]
    assert [x["tag"] for x in got["references"][:2]] == ["<IMAGE_REF_0>", "<IMAGE_REF_1>"], "the tags renumber"
    assert got["references"][0]["label"] == "the woman in the cream blouse"
    assert got["references"][0]["origin"] == "person"
    assert "<IMAGE_REF_0> is the woman in the cream blouse." in got["request"]["prompt"]
    assert [x["id"] for x in got["hiru_references"]] == [h["id"] for h in hiru], "Hiru's choice is still there"
    assert got["request_hash"] != v["request_hash"]

    again = plan(world, s)
    assert again["references_origin"] == "person" and again["references"][0]["id"] == base[1]["id"]

    r = world.client.put(shot_url(world, s, 1, "/video-settings"), json={"references": mine[1:]}, headers=director)
    assert len(r.json()["references"]) == len(mine) - 1

    r = world.client.put(shot_url(world, s, 1, "/video-settings"), json={"references": None}, headers=director)
    assert r.json()["references_origin"] == "hiru" and len(r.json()["references"]) == len(hiru)


def test_a_label_that_would_be_drawn_as_lettering_is_refused_when_saved(world: World, video: Settings):
    s, _ = ready(world)
    base = refs_in(plan(world, s))
    bad = [{**base[0], "label": "C01"}, *base[1:]]
    r = world.client.put(shot_url(world, s, 1, "/video-settings"), json={"references": bad},
                         headers=world.headers(world.director))
    assert r.status_code == 422 and "lettering" in r.text
    assert plan(world, s)["references_origin"] == "hiru", "nothing was saved"


def test_a_picture_the_shot_may_not_use_is_refused(world: World, video: Settings):
    s, _ = ready(world)
    base = refs_in(plan(world, s))
    stranger = [{**base[0], "id": "00000000-0000-0000-0000-00000000dead"}, *base[1:]]
    r = world.client.put(shot_url(world, s, 1, "/video-settings"), json={"references": stranger},
                         headers=world.headers(world.director))
    assert r.status_code == 422 and "not available for this shot" in r.text
    kind_swapped = [{**base[0], "kind": "upload"}, *base[1:]]
    assert world.client.put(shot_url(world, s, 1, "/video-settings"), json={"references": kind_swapped},
                            headers=world.headers(world.director)).status_code == 422


def test_reset_brings_back_hirus_choice_and_keeps_the_pictures_a_person_added(world: World, video: Settings):
    s, _ = ready(world)
    director = world.headers(world.director)
    up = world.client.post(shot_url(world, s, 1, "/references/uploads"), files={"file": ("x.png", PNG, "image/png")},
                           headers=director)
    assert up.status_code == 201 and up.json()["kind"] == "upload" and "/files/" in up.json()["url"]
    world.client.put(shot_url(world, s, 1, "/video-settings"),
                     json={"settings": {"resolution": "1080p"}, "references": []}, headers=director)
    v = world.client.put(shot_url(world, s, 1, "/video-settings"), json={"reset": True}, headers=director).json()
    assert v["references_origin"] == "hiru" and v["settings"]["sources"]["resolution"] == "production"
    assert any(c["kind"] == "upload" for c in v["catalog"]), "an uploaded picture is still there to add"


def test_a_persons_own_picture_joins_the_list_and_is_labelled_in_words(world: World, video: Settings):
    s, _ = ready(world)
    director = world.headers(world.director)
    up = world.client.post(shot_url(world, s, 1, "/references/uploads"), files={"file": ("x.png", PNG, "image/png")},
                           headers=director).json()
    base = refs_in(plan(world, s))
    mine = [*base[:-1], {"slot": "reference", "kind": "upload", "id": up["id"], "binds_to": None,
                         "label": "the red kettle on the stove"}, base[-1]]
    v = world.client.put(shot_url(world, s, 1, "/video-settings"), json={"references": mine}, headers=director).json()
    assert v["request"]["references"][-2]["label"] == "the red kettle on the stove"
    assert "<IMAGE_REF_" in v["request"]["references"][-2]["tag"]
    stored = world.repos.shots.rows[s["shots"][1]["id"]]["video_settings"]  # type: ignore[attr-defined]
    assert stored["uploads"][0]["path"].startswith(f"{world.production}/uploads/"), "the path stays on the server"


def test_uploads_are_checked_by_content_and_need_the_render_permission(world: World, video: Settings):
    s, _ = ready(world)
    path = shot_url(world, s, 1, "/references/uploads")
    assert world.client.post(path, files={"file": ("x.png", b"GIF89a....", "image/png")},
                             headers=world.headers(world.director)).status_code == 422
    for who in (world.reviewer, world.writer, world.crew):
        assert world.client.post(path, files={"file": ("x.png", PNG, "image/png")},
                                 headers=world.headers(who)).status_code == 403
    assert world.client.post(path, files={"file": ("x.png", PNG, "image/png")},
                             headers=world.headers(world.producer)).status_code == 201


def test_saving_needs_the_render_permission(world: World, video: Settings):
    s, _ = ready(world)
    for who in (world.reviewer, world.writer, world.crew):
        assert world.client.put(shot_url(world, s, 1, "/video-settings"), json={"reset": True},
                                headers=world.headers(who)).status_code == 403


# ── pressing Generate ──────────────────────────────────────────────────────────────────────────────────────────


def test_generate_inserts_a_queued_row_with_the_exact_request_and_dispatches_one_job(world: World, video: Settings,
                                                                                      fired: list[dict]):
    s, _ = ready(world)
    v = plan(world, s)
    r = world.client.post(shot_url(world, s, 1, "/renders"), json={"request_hash": v["request_hash"]},
                          headers=world.headers(world.director))
    assert r.status_code == 202, r.text
    out = r.json()
    (row,) = world.repos.renders.rows.values()  # type: ignore[attr-defined]
    assert row["status"] == "queued" and row["engine"] == "omni_flash" and row["shot_id"] == s["shots"][1]["id"]
    assert row["created_by"] == str(world.director) and row["job_id"] == str(out["job_id"])
    assert row["spec"]["prose"].startswith("Nimal opens the door") and row["spec"]["prompt_version"] == 1
    assert "first_frame" in [r_["slot"] for r_ in row["spec"]["references"]]
    assert row["request_hash"] == request_hash(RenderSpec.model_validate(row["spec"]))
    assert row["seed"] is None, "Omni takes no seed (until the probe says otherwise)"
    assert out["seeds"] == "" and out["renders"][0]["status"] == "queued"
    (call,) = fired
    assert call["kind"] == "video_render" and call["state"] == {"render_ids": [row["id"]]}
    assert call["url"].endswith(":8212/") and call["production_id"] == str(world.production)
    audit = [a for a in world.repos.audit.entries if a["action"] == "video.render"]  # type: ignore[attr-defined]
    assert audit and audit[0]["diff"]["takes"] == 1


def test_one_press_makes_one_take_with_a_recorded_seed(world: World, video: Settings, fired: list[dict]):
    s, _ = ready(world)
    on(world, engine="veo_3_1")
    body = {"overrides": {"duration_s": 8, "seed": {"mode": "fixed", "value": 1234}}}
    r = world.client.post(shot_url(world, s, 1, "/renders"), json=body, headers=world.headers(world.producer))
    assert r.status_code == 202, r.text
    (row,) = world.repos.renders.rows.values()  # type: ignore[attr-defined]
    assert row["seed"] == row["spec"]["seed"] == 1234 and r.json()["seeds"] == "seed 1234"
    assert len(fired) == 1 and fired[0]["state"]["render_ids"] == [row["id"]]

    world.repos.renders.rows.clear()  # type: ignore[attr-defined]
    world.client.post(shot_url(world, s, 1, "/renders"), json={"overrides": {"duration_s": 8}},
                      headers=world.headers(world.producer))
    (seed,) = [x["seed"] for x in world.repos.renders.rows.values()]  # type: ignore[attr-defined]
    assert isinstance(seed, int) and 0 <= seed < 2**32, "random is drawn and recorded"
    assert world.client.post(shot_url(world, s, 1, "/renders"), json={"overrides": {"takes": 2}},
                             headers=world.headers(world.producer)).status_code == 422, "one video a press"


def test_a_fixed_seed_on_an_engine_that_takes_none_is_refused_and_random_sends_none(world: World, video: Settings,
                                                                                    fired: list[dict]):
    s, _ = ready(world)
    r = world.client.post(shot_url(world, s, 1, "/renders"), headers=world.headers(world.director),
                          json={"overrides": {"seed": {"mode": "fixed", "value": 5}}})
    assert r.status_code == 422 and "does not take a seed" in r.text and not fired


def test_generate_is_refused_with_the_failing_checks_when_the_request_cannot_be_sent(world: World, video: Settings,
                                                                                      fired: list[dict]):
    s, _ = ready(world)
    on(world, engine="veo_3_1", resolution="1080p")
    r = world.client.post(shot_url(world, s, 1, "/renders"), headers=world.headers(world.director),
                          json={"overrides": {"duration_s": 6}})
    assert r.status_code == 422
    checks = r.json()["detail"]["checks"]
    assert any("only at 8 s" in c["label"] for c in checks) and all(c["tone"] == "fail" for c in checks)
    assert not fired and not world.repos.renders.rows  # type: ignore[attr-defined]


def test_a_handoff_check_that_fails_blocks_generate(world: World, video: Settings, fired: list[dict]):
    s, _ = ready(world)
    next(iter(world.repos.prompts.rows.values()))["prose"] = "A door opens. Coca-Cola on the table."  # type: ignore[attr-defined]
    r = world.client.post(shot_url(world, s, 1, "/renders"), json={}, headers=world.headers(world.director))
    assert r.status_code == 422 and "Names to remove: Coca-Cola" in r.text and not fired


def test_a_preview_that_went_stale_is_refused_not_sent(world: World, video: Settings, fired: list[dict]):
    s, _ = ready(world)
    seen = plan(world, s)["request_hash"]
    world.client.put(shot_url(world, s, 1, "/video-settings"), json={"settings": {"duration_s": 8}},
                     headers=world.headers(world.producer))
    r = world.client.post(shot_url(world, s, 1, "/renders"), json={"request_hash": seen},
                          headers=world.headers(world.director))
    assert r.status_code == 409 and "changed since you looked" in r.text and not fired
    fresh = plan(world, s)["request_hash"]
    assert world.client.post(shot_url(world, s, 1, "/renders"), json={"request_hash": fresh},
                             headers=world.headers(world.director)).status_code == 202


def test_save_for_shot_keeps_this_presss_overrides_on_the_shot(world: World, video: Settings, fired: list[dict]):
    s, _ = ready(world)
    r = world.client.post(shot_url(world, s, 1, "/renders"), headers=world.headers(world.director),
                          json={"overrides": {"duration_s": 8}, "save_for_shot": True})
    assert r.status_code == 202
    assert plan(world, s)["settings"]["duration_s"] == 8
    assert plan(world, s)["settings"]["sources"]["duration_s"] == "shot"


def test_the_running_cap_is_enforced_before_any_spend(world: World, monkeypatch: pytest.MonkeyPatch,
                                                       fired: list[dict]):
    settings = _settings(fake_provider=True, max_running_per_production=2)
    world.client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    s, _ = ready(world)
    for _ in range(2):
        assert world.client.post(shot_url(world, s, 1, "/renders"), json={},
                                 headers=world.headers(world.director)).status_code == 202
    r = world.client.post(shot_url(world, s, 1, "/renders"), json={}, headers=world.headers(world.director))
    assert r.status_code == 429 and len(world.repos.renders.rows) == 2  # type: ignore[attr-defined]
    for row in world.repos.renders.rows.values():  # type: ignore[attr-defined]
        row["status"] = "done"
    assert world.client.post(shot_url(world, s, 1, "/renders"), json={},
                             headers=world.headers(world.director)).status_code == 202


def test_only_producer_director_and_admin_may_generate(world: World, video: Settings, fired: list[dict]):
    s, _ = ready(world)
    for who in (world.reviewer, world.writer, world.crew):
        assert world.client.post(shot_url(world, s, 1, "/renders"), json={},
                                 headers=world.headers(who)).status_code == 403
    for who in (world.producer, world.director):
        world.repos.renders.rows.clear()  # type: ignore[attr-defined]
        assert world.client.post(shot_url(world, s, 1, "/renders"), json={},
                                 headers=world.headers(who)).status_code == 202
    assert world.client.post(shot_url(world, s, 1, "/renders"), json={},
                             headers=world.headers(world.outsider)).status_code == 404
    assert not fired or all(c["kind"] == "video_render" for c in fired)


def test_a_job_that_cannot_start_fails_its_rows_and_says_so(world: World, video: Settings,
                                                             monkeypatch: pytest.MonkeyPatch):
    def boom(u: str, payload: object) -> None:
        raise OSError("down")

    monkeypatch.setattr(task_manager, "_fire_local", lambda u, payload: None)
    s, _ = ready(world)
    monkeypatch.setattr(task_manager, "_fire_local", boom)
    r = world.client.post(shot_url(world, s, 1, "/renders"), json={}, headers=world.headers(world.director))
    assert r.status_code == 503
    (row,) = world.repos.renders.rows.values()  # type: ignore[attr-defined]
    assert row["status"] == "failed" and row["error"] == "The job could not be started."


# ── make again, vary ───────────────────────────────────────────────────────────────────────────────────────────


def _veo_render(world: World, s: dict, fired: list[dict]) -> dict:
    on(world, engine="veo_3_1")
    body = {"overrides": {"duration_s": 8, "seed": {"mode": "fixed", "value": 77}}}
    r = world.client.post(shot_url(world, s, 1, "/renders"), json=body, headers=world.headers(world.director))
    assert r.status_code == 202, r.text
    return r.json()["renders"][0]


def test_make_again_repeats_the_request_and_the_seed_and_vary_changes_only_the_seed(world: World, video: Settings,
                                                                                     fired: list[dict]):
    s, _ = ready(world)
    first = _veo_render(world, s, fired)
    director = world.headers(world.director)
    again = world.client.post(url(world, f"/renders/{first['id']}/again"), json={}, headers=director)
    assert again.status_code == 202, again.text
    rows = world.repos.renders.rows  # type: ignore[attr-defined]
    a, b = rows[first["id"]], rows[again.json()["renders"][0]["id"]]
    assert b["seed"] == a["seed"] == 77 and b["request_hash"] == a["request_hash"] and b["spec"] == a["spec"]
    assert b["id"] != a["id"] and again.json()["seeds"] == "seed 77"

    vary = world.client.post(url(world, f"/renders/{first['id']}/again"), json={"vary": True}, headers=director)
    c = rows[vary.json()["renders"][0]["id"]]
    assert c["seed"] != 77
    assert c["spec"]["references"] == a["spec"]["references"] and c["spec"]["prose"] == a["spec"]["prose"]
    assert len(fired) == 3
    actions = {x["action"] for x in world.repos.audit.entries}  # type: ignore[attr-defined]
    assert {"video.again", "video.vary"} <= actions


def test_make_again_clears_recorded_hashes_and_is_permissioned(world: World, video: Settings, fired: list[dict]):
    s, _ = ready(world)
    first = _veo_render(world, s, fired)
    rows = world.repos.renders.rows  # type: ignore[attr-defined]
    for ref in rows[first["id"]]["spec"]["references"]:
        ref["source"]["sha256"] = "a" * 64  # what the function records once it has sent them
    again = world.client.post(url(world, f"/renders/{first['id']}/again"), json={},
                              headers=world.headers(world.director)).json()
    assert all(r["source"]["sha256"] == "" for r in rows[again["renders"][0]["id"]]["spec"]["references"])
    for who in (world.reviewer, world.crew):
        assert world.client.post(url(world, f"/renders/{first['id']}/again"), json={},
                                 headers=world.headers(who)).status_code == 403
    other = f"/v1/productions/{world.other_production}/renders/{first['id']}/again"
    assert world.client.post(other, json={}, headers=world.headers(world.admin)).status_code == 404


def test_seed_from_a_take_reuses_that_takes_seed(world: World, video: Settings, fired: list[dict]):
    s, _ = ready(world)
    first = _veo_render(world, s, fired)
    take = world.repos.takes.rows  # type: ignore[attr-defined]
    asyncio.run(world.repos.takes.create({"id": "00000000-0000-0000-0000-000000000abc",
                                          "production_id": str(world.production), "shot_id": s["shots"][1]["id"],
                                          "storage_path": "p/t.mp4", "mime": "video/mp4", "bytes": 5,
                                          "origin": "generated", "render_id": first["id"]}))
    assert take
    body = {"overrides": {"duration_s": 8,
                          "seed": {"mode": "from_take", "take_id": "00000000-0000-0000-0000-000000000abc"}}}
    r = world.client.post(shot_url(world, s, 1, "/renders"), json=body, headers=world.headers(world.director))
    assert r.status_code == 202 and r.json()["seeds"] == "seed 77"
    body["overrides"]["seed"]["take_id"] = "00000000-0000-0000-0000-0000000000ff"  # type: ignore[index]
    assert world.client.post(shot_url(world, s, 1, "/renders"), json=body,
                             headers=world.headers(world.director)).status_code == 422


# ── reading renders and the handoff screen ─────────────────────────────────────────────────────────────────────


def test_a_render_shows_the_request_it_sent_with_pictures_through_tickets(world: World, video: Settings,
                                                                           fired: list[dict]):
    s, _ = ready(world)
    first = _veo_render(world, s, fired)
    r = world.client.get(url(world, f"/renders/{first['id']}"), headers=world.headers(world.reviewer))
    v = r.json()
    assert v["status"] == "queued" and v["engine_label"] == "Veo 3.1" and v["seed"] == 77
    assert v["settings_text"].startswith("Veo 3.1 · 720p · 16:9 · 8 s") and v["settings_text"].endswith("seed 77")
    assert v["request"]["prompt"].startswith("Nimal opens the door") and v["request"]["config"]["seed"] == 77
    assert all("/files/" in x["url"] for x in v["request"]["references"])
    assert world.client.get(url(world, f"/renders/{first['id']}"),
                            headers=world.headers(world.outsider)).status_code == 404


def test_the_handoff_screen_lists_queued_renders_and_generated_takes_with_their_settings(world: World, video: Settings,
                                                                                         fired: list[dict],
                                                                                         assembler: FakeAssembler):
    s, _ = ready(world)
    first = _veo_render(world, s, fired)
    reviewer = world.headers(world.reviewer)
    v = world.client.get(shot_url(world, s, 1, "/handoff"), headers=reviewer).json()
    assert v["video_available"] and [r["status"] for r in v["renders"]] == ["queued"] and v["takes"] == []

    # what the function writes on success: the take (no length yet) and the render pointing at it
    take_id = "00000000-0000-0000-0000-000000000abc"
    asyncio.run(world.repos.takes.create({"id": take_id, "production_id": str(world.production),
                                          "shot_id": s["shots"][1]["id"], "storage_path": "p/t.mp4",
                                          "mime": "video/mp4", "bytes": 5, "origin": "generated",
                                          "render_id": first["id"]}))
    world.repos.renders.rows[first["id"]].update(status="done", take_id=take_id)  # type: ignore[attr-defined]
    v = world.client.get(shot_url(world, s, 1, "/handoff"), headers=reviewer).json()
    (take,) = v["takes"]
    assert v["renders"] == [], "a finished render is shown as its take"
    assert take["origin"] == "generated" and take["engine"] == "veo_3_1" and take["seed"] == 77
    assert take["settings_text"].startswith("Veo 3.1") and take["render_id"] == first["id"]
    assert take["duration_s"] == 7.5 and take["duration_note"] == "7.5 s; the shot is 4 s", "probed on first sight"
    assert assembler.calls.count(("probe", "takes", "p/t.mp4")) == 1
    world.client.get(shot_url(world, s, 1, "/handoff"), headers=reviewer)
    assert assembler.calls.count(("probe", "takes", "p/t.mp4")) == 1, "probed once"

    # accepting it is today's flow
    crew = world.headers(world.crew)
    assert world.client.post(url(world, f"/takes/{take_id}/accept"), headers=crew).json()["accepted_take_id"] == take_id


def test_an_upload_is_still_an_upload(world: World, video: Settings, assembler: FakeAssembler):
    s, _ = ready(world)
    mp4 = b"\0\0\0\x18ftypisom" + b"\0" * 64
    v = world.client.post(shot_url(world, s, 1, "/takes"), files={"file": ("t.mp4", mp4, "video/mp4")},
                          headers=world.headers(world.crew)).json()
    assert v["takes"][0]["origin"] == "upload" and v["takes"][0]["engine"] is None and v["takes"][0]["seed"] is None


def test_a_render_that_never_finished_is_reported_failed(world: World, video: Settings, fired: list[dict],
                                                          assembler: FakeAssembler):
    s, _ = ready(world)
    first = _veo_render(world, s, fired)
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    world.repos.renders.rows[first["id"]].update(status="running", updated_at=old)  # type: ignore[attr-defined]
    v = world.client.get(shot_url(world, s, 1, "/handoff"), headers=world.headers(world.reviewer)).json()
    assert [(r["status"], r["error"]) for r in v["renders"]] == [("failed", STALE_ERROR)]
    assert world.repos.renders.rows[first["id"]]["status"] == "failed"  # type: ignore[attr-defined]


def test_the_model_and_size_are_chosen_when_the_production_is_created_and_never_change(world: World):
    admin = world.headers(world.admin)
    base = {"title": "Veo drama", "orientation": "horizontal"}
    video = {"engine": "veo_3_1", "resolution": "1080p"}
    r = world.client.post("/v1/productions", json={**base, "settings": {"video": video}}, headers=admin)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["settings"]["video"]["engine"] == "veo_3_1"
    assert r.json()["settings"]["video"]["resolution"] == "1080p"
    for bad in ({"engine": "veo_3_1", "resolution": "360p"}, {"engine": "omni_flash", "resolution": "4k"},
                {"engine": "nope"}):
        assert world.client.post("/v1/productions", json={**base, "settings": {"video": bad}},
                                 headers=admin).status_code == 422, bad

    stored = world.repos.productions.rows[pid]["settings"]  # type: ignore[attr-defined]
    for change in ({"engine": "omni_flash", "resolution": "1080p"}, {"engine": "veo_3_1", "resolution": "720p"},
                   {"engine": "veo_3_1", "resolution": "1080p", "model": "veo-3.1-generate-002"}):
        r = world.client.patch(f"/v1/productions/{pid}", json={"settings": {"video": change}}, headers=admin)
        assert r.status_code == 422 and "cannot be changed" in r.text, change
    assert world.repos.productions.rows[pid]["settings"] == stored  # type: ignore[attr-defined]

    # other settings save; the video choice they did not send is kept, never reset to the default
    r = world.client.patch(f"/v1/productions/{pid}", json={"settings": {"spoken_language": "en"}}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["video"]["engine"] == "veo_3_1" and r.json()["settings"]["spoken_language"] == "en"
    same = {**video, "seed": {"mode": "fixed", "value": 9}}
    r = world.client.patch(f"/v1/productions/{pid}", json={"settings": {"video": same}}, headers=admin)
    assert r.status_code == 200 and r.json()["settings"]["video"]["seed"]["value"] == 9

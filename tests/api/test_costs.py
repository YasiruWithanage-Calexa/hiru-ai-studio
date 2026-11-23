"""A scene's production cost (plan/2026-11-06d Phase 4): who may see it, the one-figure answer, spent and to-finish,
the margins, the episode share, a missing price, and the admin price list. No network, no database: usage rows are
placed in the fake repository the way the writers leave them."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from contracts.costs import (
    SEED_PRICES,
    Costed,
    scene_total,
    with_margin,
)
from tests.api.conftest import World
from tests.api.test_production import design, open_scene
from tests.api.test_scenes import seed_scene

OMNI_PER_SECOND = 70_000  # the seeded price: Omni 1.2, $0.07 a second at 720p (plan/2026-11-23)
OMNI_11_PER_SECOND = 100_000  # a retired Omni 1.1 render keeps its own price
FRAME = with_margin(80_000, "image")  # the seeded flat price of a frame, with the image margin
PROMPT = with_margin(20_000, "text")  # plan/2026-11-20d D12: one shot prompt (first frame + video), + the llm margin
PICTURE = with_margin(1_100_000, "image")  # 100k picture tokens in x $8 + 10k out x $30 = $1.10, + the image margin


def cost_url(world: World, s: dict) -> str:
    return f"/v1/productions/{world.production}/scenes/{s['scene']['id']}/cost"


def get(world: World, s: dict, who: UUID) -> dict:
    r = world.client.get(cost_url(world, s), headers=world.headers(who))
    assert r.status_code == 200, r.text
    return r.json()


def usage(world: World, *, phase: str, model: str = "gpt-5", i: int = 0, o: int = 0, scene: str | None = None,
          job: str | None = None, at: str = "2026-11-06T00:00:00+00:00", production: str | None = None) -> dict:
    row = {"id": len(world.repos.costs.usage) + 1, "production_id": production or str(world.production),  # type: ignore[attr-defined]
           "scene_id": scene, "job_id": job, "phase": phase, "model": model, "input_tokens": i,
           "cached_input_tokens": 0, "output_tokens": o, "created_at": at}
    world.repos.costs.usage.append(row)  # type: ignore[attr-defined]
    return row


def to_finish_all(s: dict) -> int:
    """What the plan says an untouched scene's shots cost to finish (before the retry margin)."""
    video = sum(with_margin(int(sh["duration_s"]) * OMNI_PER_SECOND, "video") for sh in s["shots"])
    return video + len(s["shots"]) * (FRAME + PROMPT)


# ── access ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("who", ["producer", "director", "admin"])
def test_the_people_who_can_spend_see_the_cost(world: World, who: str):
    s = seed_scene(world)
    assert get(world, s, getattr(world, who))["currency"] == "USD"


@pytest.mark.parametrize("who", ["writer", "crew", "reviewer"])
def test_everyone_else_gets_403_and_no_money(world: World, who: str):
    s = seed_scene(world)
    r = world.client.get(cost_url(world, s), headers=world.headers(getattr(world, who)))
    assert r.status_code == 403
    assert "$" not in r.text and "micros" not in r.text


def test_a_production_the_caller_cannot_see_is_404(world: World):
    s = seed_scene(world)
    assert world.client.get(cost_url(world, s), headers=world.headers(world.outsider)).status_code == 404


def test_a_scene_of_another_production_is_404(world: World):
    s = seed_scene(world)
    r = world.client.get(f"/v1/productions/{world.other_production}/scenes/{s['scene']['id']}/cost",
                         headers=world.headers(world.admin))
    assert r.status_code == 404


def test_it_needs_a_login(world: World):
    s = seed_scene(world)
    assert world.client.get(cost_url(world, s)).status_code == 401


# ── the answer is ONE figure ──────────────────────────────────────────────────────────────────


def test_the_response_has_only_the_total_and_two_flags(world: World):
    s = seed_scene(world)
    usage(world, phase="shot_producer.craft", i=1000, o=1000, scene=s["scene"]["id"])
    assert set(get(world, s, world.producer)) == {"currency", "total_micros", "designed", "complete"}


# ── a scene with nothing done ─────────────────────────────────────────────────────────────────


def test_an_untouched_scene_costs_what_it_will_cost_to_finish_with_no_retry_margin(world: World):
    s = seed_scene(world)
    got = get(world, s, world.producer)
    assert got["total_micros"] == (to_finish_all(s))
    assert got["designed"] is False and got["complete"] is True


def test_it_becomes_designed_once_every_shot_has_its_design(world: World):
    s = open_scene(world)
    assert get(world, s, world.producer)["designed"] is False
    design(world, s)
    assert get(world, s, world.producer)["designed"] is True


def test_a_scene_with_no_shots_is_not_designed_and_costs_nothing(world: World):
    s = seed_scene(world)
    for sh in s["shots"]:
        del world.repos.shots.rows[sh["id"]]  # type: ignore[attr-defined]
    got = get(world, s, world.producer)
    assert got == {"currency": "USD", "total_micros": 0, "designed": False, "complete": True}


# ── spent ─────────────────────────────────────────────────────────────────────────────────────


def test_text_calls_carry_the_llm_margin_once_and_no_retry_margin(world: World):
    s = seed_scene(world)
    before = get(world, s, world.producer)["total_micros"]
    usage(world, phase="shot_producer.scene", i=1_000_000, o=100_000, scene=s["scene"]["id"])  # 1.25 + 1.00 = $2.25
    assert get(world, s, world.producer)["total_micros"] == before + with_margin(2_250_000, "text")


def test_pictures_carry_the_image_margin_once(world: World):
    s = seed_scene(world)
    usage(world, phase="frame_render.image", model="gpt-image-2", i=100_000, o=10_000, scene=s["scene"]["id"])  # $1.10
    # spent: 1.10 + the image margin once. The same picture is now also this production's history, so a frame left to
    # make is estimated at what it cost.
    video = sum(with_margin(int(sh["duration_s"]) * OMNI_PER_SECOND, "video") for sh in s["shots"])
    left = video + len(s["shots"]) * (PICTURE + PROMPT)
    assert get(world, s, world.producer)["total_micros"] == PICTURE + (left)


def test_a_done_render_is_spent_with_the_video_margin_and_leaves_the_estimate_of_its_shot_in_place(world: World):
    s = seed_scene(world)
    sh = s["shots"][0]
    world.repos.renders.rows["r1"] = {  # type: ignore[attr-defined]
        "id": "r1", "production_id": str(world.production), "shot_id": sh["id"], "status": "done",
        "engine": "omni_flash",
        "model": "gemini-omni-1.1-flash", "created_at": "2026-11-06T00:00:00+00:00",
        "spec": {"resolution": "720p", "duration_s": 4}, "usage": {"seconds_rendered": 4, "takes_made": 1}}
    before = (to_finish_all(s))
    assert get(world, s, world.producer)["total_micros"] == before + with_margin(4 * OMNI_11_PER_SECOND, "video")


def test_an_accepted_take_takes_its_shot_out_of_the_estimate(world: World):
    s = seed_scene(world)
    sh = s["shots"][0]
    asyncio.run(world.repos.takes.create({"id": str(uuid4()), "production_id": str(world.production),
                                          "shot_id": sh["id"], "status": "accepted", "storage_path": "p/t.mp4"}))
    left = to_finish_all(s) - with_margin(int(sh["duration_s"]) * OMNI_PER_SECOND, "video") - FRAME - PROMPT
    assert get(world, s, world.producer)["total_micros"] == (left)


def test_an_uploaded_but_not_accepted_take_does_not(world: World):
    s = seed_scene(world)
    asyncio.run(world.repos.takes.create({"id": str(uuid4()), "production_id": str(world.production),
                                          "shot_id": s["shots"][0]["id"], "storage_path": "p/t.mp4"}))
    assert get(world, s, world.producer)["total_micros"] == (to_finish_all(s))


def test_a_jobs_rows_count_for_its_scene_when_they_name_none(world: World):
    s = seed_scene(world)
    before = get(world, s, world.producer)["total_micros"]
    job = str(uuid4())
    world.repos.costs.jobs[job] = {"scene_id": s["scene"]["id"]}  # type: ignore[attr-defined]
    usage(world, phase="shot_producer.scene", i=1_000_000, job=job)  # no scene_id on the row: the job names it
    assert get(world, s, world.producer)["total_micros"] == before + with_margin(1_250_000, "text")


def test_another_scenes_rows_do_not_count(world: World):
    s = seed_scene(world)
    before = get(world, s, world.producer)["total_micros"]
    usage(world, phase="shot_producer.scene", i=1_000_000, scene=str(uuid4()))
    assert get(world, s, world.producer)["total_micros"] == before


# ── setup is not scene cost (plan/2026-11-23b) ──────────────────────────────────────────────


def test_build_work_is_setup_and_never_in_the_scene_figure(world: World):
    s = seed_scene(world)
    before = get(world, s, world.producer)["total_micros"]
    world.repos.costs.lines = {s["scene"]["id"]: 3, str(uuid4()): 9}  # type: ignore[attr-defined]
    usage(world, phase="script_split.plan", i=1_000_000, o=100_000)
    usage(world, phase="structure_build.read", i=1_000_000)
    usage(world, phase="doc_ingest.role", i=1_000_000)
    assert get(world, s, world.producer)["total_micros"] == before


def test_raphael_is_setup_even_when_its_rows_name_the_scene(world: World):
    s = seed_scene(world)
    before = get(world, s, world.producer)["total_micros"]
    usage(world, phase="raphael.plan", i=1_000_000, scene=s["scene"]["id"])
    job = str(uuid4())
    world.repos.costs.jobs[job] = {"scene_id": s["scene"]["id"]}  # type: ignore[attr-defined]
    world.repos.costs.job_kinds[job] = "plan_scene_raphael"  # type: ignore[attr-defined]  # a re-plan
    usage(world, phase="raphael.cinematic", i=1_000_000, job=job)
    assert get(world, s, world.producer)["total_micros"] == before


def test_chat_on_the_scene_is_scene_cost(world: World):
    s = seed_scene(world)
    before = get(world, s, world.producer)["total_micros"]
    usage(world, phase="zora.reply", i=1_000_000, scene=s["scene"]["id"])
    usage(world, phase="sable.act", i=1_000_000, scene=s["scene"]["id"])
    assert get(world, s, world.producer)["total_micros"] == before + 2 * with_margin(1_250_000, "text")


def test_a_character_sheet_is_not_a_first_frame(world: World):
    s = seed_scene(world)
    before = get(world, s, world.producer)["total_micros"]
    job = str(uuid4())
    world.repos.costs.jobs[job] = {"entity_id": str(uuid4())}  # type: ignore[attr-defined]
    world.repos.costs.job_kinds[job] = "frame_render"  # type: ignore[attr-defined]
    usage(world, phase="frame_render.image", model="gpt-image-2", i=100_000, o=10_000, job=job)
    # neither spent on the scene nor taken as what a frame costs: the seeded frame estimate still applies
    assert get(world, s, world.producer)["total_micros"] == before


# ── what a frame or a prompt costs comes from history first ───────────────────────────────────


def test_a_frame_is_estimated_at_the_median_of_the_productions_last_frames(world: World):
    s = seed_scene(world)
    for n, job in enumerate(("j1", "j2", "j3")):
        # each job: one picture of $1.10 (+ the image margin), so a frame costs PICTURE
        usage(world, phase="frame_render.image", model="gpt-image-2", i=100_000, o=10_000, job=job,
              at=f"2026-11-0{n + 1}T00:00:00+00:00", production="elsewhere" if n == 99 else None)
    got = get(world, s, world.producer)["total_micros"]
    video = sum(with_margin(int(sh["duration_s"]) * OMNI_PER_SECOND, "video") for sh in s["shots"])
    spent = 3 * PICTURE  # these rows are not tied to the scene or a job of it: they are history, not spend
    assert got == (video + len(s["shots"]) * (PICTURE + PROMPT)), spent


def test_history_does_not_count_as_this_scenes_spend(world: World):
    s = seed_scene(world)
    before = get(world, s, world.producer)["total_micros"]
    usage(world, phase="frame_render.image", model="gpt-image-2", i=100_000, o=10_000, job="j1")
    after = get(world, s, world.producer)["total_micros"]
    assert after - before == (len(s["shots"]) * (PICTURE - FRAME))


def test_a_prompt_is_estimated_at_the_median_of_the_last_prompts(world: World):
    s = seed_scene(world)
    before = get(world, s, world.producer)["total_micros"]
    for n in range(3):
        usage(world, phase="shot_prompter.write", i=100_000, o=10_000, at=f"2026-11-0{n + 1}T00:00:00+00:00")
    # gpt-5: 0.125 + 0.10 = $0.225 a prompt, + the llm margin
    each = with_margin(225_000, "text")
    assert get(world, s, world.producer)["total_micros"] - before == (len(s["shots"]) * (each - PROMPT))


# ── a missing price ───────────────────────────────────────────────────────────────────────────


def test_a_model_with_no_price_is_left_out_and_the_figure_says_incomplete(world: World):
    s = seed_scene(world)
    before = get(world, s, world.producer)
    usage(world, phase="shot_producer.scene", model="gpt-9-unknown", i=1_000_000, scene=s["scene"]["id"])
    got = get(world, s, world.producer)
    assert got["total_micros"] == before["total_micros"] and got["complete"] is False


def test_a_video_size_with_no_price_makes_the_figure_incomplete(world: World):
    s = seed_scene(world, settings={"video": {"engine": "omni_flash", "resolution": "1080p"}})
    world.repos.costs.price_rows.extend(  # type: ignore[attr-defined]  # the list without its 1080p row
        p.model_dump(mode="json") | {"id": str(uuid4())} for p in SEED_PRICES if p.resolution != "1080p")
    got = get(world, s, world.producer)
    assert got["complete"] is False


def test_a_video_meter_row_is_not_priced_as_text(world: World):
    s = seed_scene(world)
    before = get(world, s, world.producer)
    usage(world, phase="video_render.omni_flash", model="gemini-omni-1.1-flash", o=46_336, scene=s["scene"]["id"])
    assert get(world, s, world.producer) == before


# ── the price list (admin) ────────────────────────────────────────────────────────────────────

NEW_PRICE = {"kind": "tokens", "model_prefix": "gpt-9", "input_micros": 1_000_000, "cached_input_micros": 100_000,
             "output_micros": 8_000_000, "note": "from the pricing page"}


def seeded(world: World) -> None:
    """The price table as the migration leaves it."""
    world.repos.costs.price_rows.extend(  # type: ignore[attr-defined]
        p.model_dump(mode="json") | {"id": str(uuid4())} for p in SEED_PRICES)


def test_an_admin_adds_a_price_and_a_scene_uses_it(world: World):
    s = seed_scene(world)
    seeded(world)
    usage(world, phase="shot_producer.scene", model="gpt-9", i=1_000_000, scene=s["scene"]["id"],
          at=(datetime.now(UTC) + timedelta(hours=1)).isoformat())  # made after the price starts
    assert get(world, s, world.producer)["complete"] is False
    r = world.client.put("/v1/prices", json=NEW_PRICE, headers=world.headers(world.admin))
    assert r.status_code == 201, r.text
    assert r.json()["set_by"] == str(world.admin)
    got = get(world, s, world.producer)
    assert got["complete"] is True  # priced from now on
    assert world.client.get("/v1/prices", headers=world.headers(world.admin)).json()[0]["model_prefix"] == "gpt-9"


def test_a_price_cannot_start_in_the_past(world: World):
    r = world.client.put("/v1/prices", json={**NEW_PRICE, "valid_from": "2026-01-01T00:00:00Z"},
                         headers=world.headers(world.admin))
    assert r.status_code == 422
    assert world.repos.costs.price_rows == []  # type: ignore[attr-defined]


def test_a_new_price_applies_to_new_work_only(world: World):
    s = seed_scene(world)
    seeded(world)
    usage(world, phase="shot_producer.scene", i=1_000_000, scene=s["scene"]["id"], at="2026-11-06T00:00:00+00:00")
    before = get(world, s, world.producer)["total_micros"]
    r = world.client.put("/v1/prices", json={"kind": "tokens", "model_prefix": "gpt-5", "input_micros": 9_000_000,
                                             "output_micros": 10_000_000}, headers=world.headers(world.admin))
    assert r.status_code == 201
    assert get(world, s, world.producer)["total_micros"] == before  # old spending keeps the price it was made at


@pytest.mark.parametrize("who", ["producer", "director", "writer", "crew", "reviewer"])
def test_only_an_admin_reads_or_writes_prices(world: World, who: str):
    h = world.headers(getattr(world, who))
    assert world.client.get("/v1/prices", headers=h).status_code == 403
    assert world.client.put("/v1/prices", json=NEW_PRICE, headers=h).status_code == 403


@pytest.mark.parametrize("bad", [
    {"kind": "tokens"},  # names no model
    {"kind": "video_second", "engine": "omni_flash"},  # names no size
    {"kind": "estimate", "model_prefix": "lunch"},
    {"kind": "tokens", "model_prefix": "gpt-9", "input_micros": -1},
    {"kind": "credits", "model_prefix": "x"},
])
def test_a_bad_price_is_refused(world: World, bad: dict):
    r = world.client.put("/v1/prices", json=bad, headers=world.headers(world.admin))
    assert r.status_code == 422


def test_adding_a_price_is_audited(world: World):
    world.client.put("/v1/prices", json=NEW_PRICE, headers=world.headers(world.admin))
    assert any(a["action"] == "prices.add" for a in world.repos.audit.entries)  # type: ignore[attr-defined]


def test_the_scene_cost_arithmetic_matches_the_plans_example():
    total = scene_total([Costed(6_120_000)], [Costed(12_280_000)])
    assert total.total_micros == 18_400_000  # plan/2026-11-23b: no retry margin any more


# ── plan/2026-11-23: the new price shapes ─────────────────────────────────────────────────────


def test_a_video_model_billed_by_tokens_takes_a_price(world: World):
    body = {"kind": "video_tokens", "model_prefix": "gemini-omni-1.3-flash", "input_micros": 1_500_000,
            "output_micros": 12_000_000, "text_output_micros": 9_000_000}
    r = world.client.put("/v1/prices", json=body, headers=world.headers(world.admin))
    assert r.status_code == 201, r.text
    assert r.json()["text_output_micros"] == 9_000_000
    assert world.client.put("/v1/prices", json={"kind": "video_tokens"},
                            headers=world.headers(world.admin)).status_code == 422


def test_a_plain_price_names_no_v29_column_so_it_saves_on_an_older_database(world: World):
    assert world.client.put("/v1/prices", json=NEW_PRICE, headers=world.headers(world.admin)).status_code == 201
    stored = world.repos.costs.price_rows[-1]  # type: ignore[attr-defined]
    assert not {"image_input_micros", "long_context_from", "text_output_micros"} & set(stored)
    long = {**NEW_PRICE, "model_prefix": "gpt-10", "long_context_from": 272_000, "long_input_micros": 2_000_000}
    assert world.client.put("/v1/prices", json=long, headers=world.headers(world.admin)).status_code == 201
    assert world.repos.costs.price_rows[-1]["long_context_from"] == 272_000  # type: ignore[attr-defined]

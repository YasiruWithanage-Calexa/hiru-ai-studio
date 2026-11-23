"""Settings → Usage (plan/2026-11-23): GET /v1/admin/usage. Admin only; the month's total and each production in three
buckets at FINAL prices; nothing that could reveal a margin or a provider cost; the database's sums and the API's own
sums agree. No network, no database."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from api import margins as api_margins
from api.main import create_app
from api.services import usage_totals as svc
from contracts import costs
from contracts.costs import cost_render, cost_tokens, with_margin
from tests.api.conftest import World

URL = "/v1/admin/usage"
PRICES = list(costs.SEED_PRICES)


@pytest.fixture(autouse=True)
def _fresh():
    svc.clear()
    yield
    svc.clear()
    api_margins.install()


def usage(world: World, *, phase: str = "shot_producer.craft", model: str = "gpt-5", i: int = 0, o: int = 0,
          production: Any = "own", at: str = "2026-11-06T00:00:00+00:00", **extra: Any) -> dict:
    pid = str(world.production) if production == "own" else production
    row = {"id": len(world.repos.costs.usage) + 1, "production_id": pid, "scene_id": None,  # type: ignore[attr-defined]
           "job_id": None, "phase": phase, "model": model, "input_tokens": i, "cached_input_tokens": 0,
           "output_tokens": o, "created_at": at, **extra}
    world.repos.costs.usage.append(row)  # type: ignore[attr-defined]
    return row


def render(world: World, *, production: Any = "own", status: str = "done", at: str = "2026-11-20T00:00:00+00:00",
           **usage_fields: Any) -> dict:
    pid = str(world.production) if production == "own" else production
    rid = str(uuid4())
    row = {"id": rid, "production_id": pid, "shot_id": str(uuid4()), "status": status, "engine": "omni_flash",
           "model": "gemini-omni-1.2-flash", "created_at": at, "updated_at": at,
           "spec": {"resolution": "720p", "duration_s": 8}, "usage": {"seconds_rendered": 8, **usage_fields}}
    world.repos.renders.rows[rid] = row  # type: ignore[attr-defined]
    return row


def get(world: World, month: str = "2026-11") -> dict:
    r = world.client.get(URL, params={"month": month}, headers=world.headers(world.admin))
    assert r.status_code == 200, r.text
    return r.json()


# ── access ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("who", ["producer", "director", "writer", "crew", "reviewer", "outsider"])
def test_only_an_admin_sees_spending(world: World, who: str):
    usage(world, i=1_000_000)
    r = world.client.get(URL, headers=world.headers(getattr(world, who)))
    assert r.status_code == 403
    assert "micros" not in r.text


def test_it_needs_a_login(world: World):
    assert world.client.get(URL).status_code == 401


@pytest.mark.parametrize("bad", ["2025-12", "2099-01", "2026-13", "nov"])
def test_a_bad_month_is_422(world: World, bad: str):
    r = world.client.get(URL, params={"month": bad}, headers=world.headers(world.admin))
    assert r.status_code == 422


# ── the answer ────────────────────────────────────────────────────────────────────────────────


def test_the_month_in_three_buckets_by_production(world: World):
    text = usage(world, i=1_000_000, o=100_000)
    picture = usage(world, phase="frame_render.image", model="gpt-image-2", i=10_000, o=4_000,
                    image_input_tokens=9_000)
    other = usage(world, i=2_000_000, production=str(world.other_production))
    loose = usage(world, i=100_000, production=None)
    usage(world, phase="video_render.omni_flash", model="gemini-omni-1.2-flash", o=46_336)  # a meter: never counted
    rd = render(world, prompt_tokens=2_000, completion_tokens=46_336, video_tokens=45_336, thought_tokens=1_000)
    usage(world, i=1_000_000, at="2026-10-31T23:59:59+00:00")  # last month: not counted
    got = get(world)

    assert got["currency"] == "USD" and got["month"] == "2026-11" and got["complete"] is True
    own = cost_tokens(text, PRICES).micros
    pic = cost_tokens(picture, PRICES).micros
    video = cost_render(rd, PRICES).micros
    two = cost_tokens(other, PRICES).micros
    none = cost_tokens(loose, PRICES).micros
    assert got["total"] == {"llm_micros": own + two + none, "image_micros": pic, "video_micros": video,
                            "total_micros": own + two + none + pic + video}
    rows = got["productions"]
    assert [r["name"] for r in rows] == ["Production One", "Production Two", None]
    assert rows[0] == {"production_id": str(world.production), "name": "Production One", "llm_micros": own,
                       "image_micros": pic, "video_micros": video, "total_micros": own + pic + video,
                       "purpose": {"production_setup_micros": 0, "episode_setup_micros": 0,
                                   "scene_micros": own + pic + video}}
    assert rows[2]["production_id"] is None and rows[2]["total_micros"] == none
    assert got["missing"] == []


def test_the_month_by_purpose_adds_up_to_the_same_total(world: World):
    """plan/2026-11-23b: production setup (canon, sheets), episode setup (reading, build, Raphael), scene (the rest)."""
    sheet = str(uuid4())
    world.repos.costs.jobs[sheet] = {"entity_id": str(uuid4())}  # type: ignore[attr-defined]
    world.repos.costs.job_kinds[sheet] = "frame_render"  # type: ignore[attr-defined]
    canon = usage(world, phase="canon_extract.cards", i=1_000_000)
    face = usage(world, phase="frame_render.image", model="gpt-image-2", i=10_000, o=4_000, job_id=sheet)
    read = usage(world, phase="doc_ingest.read", i=1_000_000)
    plan = usage(world, phase="raphael.plan", i=1_000_000)
    chat = usage(world, phase="zora.reply", i=1_000_000)
    rd = render(world, completion_tokens=46_336)
    got = get(world)
    production = cost_tokens(canon, PRICES).micros + cost_tokens(face, PRICES).micros
    episode = cost_tokens(read, PRICES).micros + cost_tokens(plan, PRICES).micros
    scene = cost_tokens(chat, PRICES).micros + cost_render(rd, PRICES).micros
    assert got["purpose"] == {"production_setup_micros": production, "episode_setup_micros": episode,
                              "scene_micros": scene}
    assert production + episode + scene == got["total"]["total_micros"]
    assert got["productions"][0]["purpose"] == got["purpose"]
    svc.clear()
    world.repos.costs.has_totals = False  # type: ignore[attr-defined]  # the same split without the database's sums
    assert get(world)["purpose"] == got["purpose"]


def test_an_empty_month_is_zero_and_complete(world: World):
    got = get(world)
    assert got["total"]["total_micros"] == 0 and got["productions"] == [] and got["complete"] is True


def test_a_missing_price_is_listed_and_left_out(world: World):
    usage(world, model="gpt-9-unknown", i=1_000_000)
    usage(world, model="gpt-9-unknown", i=1_000_000)
    usage(world, i=1_000_000)
    got = get(world)
    assert got["complete"] is False
    assert got["missing"] == [{"what": "gpt-9-unknown", "bucket": "llm", "count": 2}]
    assert got["total"]["llm_micros"] == with_margin(1_250_000, "text")


def test_a_deleted_productions_spend_joins_the_no_production_row(world: World):
    usage(world, i=1_000_000, production=str(uuid4()))
    usage(world, i=1_000_000, production=None)
    rows = get(world)["productions"]
    assert len(rows) == 1 and rows[0]["production_id"] is None
    assert rows[0]["total_micros"] == 2 * with_margin(1_250_000, "text")


def test_the_database_sums_and_the_apis_own_sums_agree(world: World):
    for n in range(40):
        usage(world, model=["gpt-5", "gpt-6.1-sol", "gpt-5-mini"][n % 3], i=[1_000, 300_000, 50_000][n % 3] * (n + 1),
              o=1_000 * n, at=f"2026-11-{n % 28 + 1:02d}T00:00:00+00:00",
              production=[str(world.production), None][n % 2])
    usage(world, phase="frame_render.image", model="gpt-image-2", i=5_000, o=4_000)
    by_database = get(world)
    assert world.repos.costs.totals_calls == 1  # type: ignore[attr-defined]
    svc.clear()
    world.repos.costs.has_totals = False  # type: ignore[attr-defined]  # a database before schema v29
    by_api = get(world)
    assert {k: v for k, v in by_api.items() if k != "as_of"} == {k: v for k, v in by_database.items() if k != "as_of"}


def test_the_answer_is_kept_for_a_minute_and_cleared_when_a_job_ends(world: World):
    from api.cache import job_ended

    usage(world, i=1_000_000)
    first = get(world)["total"]["total_micros"]
    usage(world, i=1_000_000)
    assert get(world)["total"]["total_micros"] == first
    job_ended()
    assert get(world)["total"]["total_micros"] == 2 * first


# ── the margins never leave the server ────────────────────────────────────────────────────────


def _properties(schema: Any, components: dict[str, Any], seen: set[str]) -> set[str]:
    """Every property name a JSON schema can carry, following $refs."""
    out: set[str] = set()
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str):
            name = ref.rsplit("/", 1)[-1]
            if name not in seen:
                seen.add(name)
                out |= _properties(components.get(name), components, seen)
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                out |= set(value)
            out |= _properties(value, components, seen)
    elif isinstance(schema, list):
        for item in schema:
            out |= _properties(item, components, seen)
    return out


SECRET = re.compile(r"margin|markup|provider|actual|(^|_)rate(s)?($|_)|(^|_)cost(s)?($|_)|token", re.I)
# The admin price list is how an admin enters the PROVIDER's rates; it carries no margin (plan/2026-11-23 D6). The
# admin token budget is the top bar's percentage, not money.
ALLOWED = {"/v1/prices", "/v1/usage/budget"}


def test_no_response_has_a_field_that_could_reveal_a_margin():
    spec = create_app(repos=None).openapi()
    components = spec.get("components", {}).get("schemas", {})
    offenders, scanned = [], 0
    for path, methods in spec["paths"].items():
        if path in ALLOWED:
            continue
        for op in methods.values():
            for code, response in (op.get("responses") or {}).items():
                if not code.startswith("2"):
                    continue
                names = _properties(response.get("content"), components, set())
                scanned += len(names)
                offenders += [(path, n) for n in sorted(names) if SECRET.search(n)]
    assert scanned > 500  # the scan really read the API's responses
    assert offenders == []


def test_an_odd_margin_shows_up_only_inside_the_final_figure(world: World, tmp_path: Path):
    path = tmp_path / "margins.yaml"
    path.write_text("margins:\n  - from: 2026-01-01\n    llm: 13.37\n    image: 21.73\n    video: 37.91\n",
                    encoding="utf-8")
    costs.use_margins(api_margins.load(path))
    text = usage(world, i=1_000_000)
    r = world.client.get(URL, params={"month": "2026-11"}, headers=world.headers(world.admin))
    assert r.json()["total"]["llm_micros"] == 1_250_000 * 11_337 // 10_000 == cost_tokens(text, PRICES).micros
    for leak in ("13.37", "1337", "21.73", "2173", "37.91", "3791", "1250000"):  # margins, or the provider cost
        assert leak not in r.text, leak


def test_the_v29_database_function_without_phase_is_not_trusted_for_the_purpose(world: World):
    """plan/2026-11-23b: before upgrade_v29_to_v30.sql the function returns no phase or job. The API then sums the
    month's rows itself, so setup is not mistaken for production setup."""
    plan = usage(world, phase="raphael.plan", i=1_000_000)
    chat = usage(world, phase="zora.reply", i=1_000_000)
    fake = world.repos.costs
    newer = fake.token_totals  # type: ignore[attr-defined]

    async def v29(*args: Any, **kwargs: Any) -> list[dict] | None:
        rows = await newer(*args, **kwargs)
        return [{k: v for k, v in g.items() if k not in ("phase", "job_id")} for g in rows or []]

    fake.token_totals = v29  # type: ignore[method-assign]
    got = get(world)["purpose"]
    assert got == {"production_setup_micros": 0, "episode_setup_micros": cost_tokens(plan, PRICES).micros,
                   "scene_micros": cost_tokens(chat, PRICES).micros}

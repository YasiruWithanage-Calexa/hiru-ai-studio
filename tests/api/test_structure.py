from __future__ import annotations

from uuid import uuid4

from tests.api.conftest import World


def seed(world: World) -> dict[str, str]:
    r = world.repos
    pid = str(world.production)
    ep1 = r.episodes.add(production_id=pid, number=1, title="The Return", synopsis="x", status="ready")  # type: ignore[attr-defined]
    r.episodes.add(production_id=pid, number=2, title="The Buyer", synopsis="", status="draft")  # type: ignore[attr-defined]
    s1 = r.scenes.add(production_id=pid, episode_id=ep1["id"], number=1, heading="INT. HOUSE - DAWN",  # type: ignore[attr-defined]
                      title="Nimal comes home", status="split", location_id=None, envelope_s=60)
    s2 = r.scenes.add(production_id=pid, episode_id=ep1["id"], number=2, heading="EXT. HARBOUR - DAY",  # type: ignore[attr-defined]
                      title="", status="draft", location_id=None, envelope_s=60)
    for n, (dur, st) in enumerate([(8, "frame"), (4, "draft"), (6, "prompt")], start=1):
        r.shots.add(production_id=pid, scene_id=s1["id"], number=n, duration_s=dur, status=st)  # type: ignore[attr-defined]
    r.canon.add(production_id=pid, kind="character", code="C01", name="Kamala", core=True, locked=True)  # type: ignore[attr-defined]
    r.canon.add(production_id=pid, kind="character", code="C02", name="Ravi", core=False, locked=False)  # type: ignore[attr-defined]
    r.canon.add(production_id=pid, kind="location", code="L01", name="House", core=False, locked=False)  # type: ignore[attr-defined]
    return {"ep1": ep1["id"], "s1": s1["id"], "s2": s2["id"]}


def test_episodes_with_counts_and_runtime(world: World):
    seed(world)
    eps = world.client.get(f"/v1/productions/{world.production}/episodes", headers=world.headers(world.reviewer)).json()
    assert [(e["number"], e["scenes"], e["shots"], e["shots_ready"], e["runtime_s"], e["openable"]) for e in eps] == [
        (1, 2, 3, 2, 18, True), (2, 0, 0, 0, 0, False)]


def test_structure_tree_and_canon_counts(world: World):
    ids = seed(world)
    tree = world.client.get(f"/v1/productions/{world.production}/structure", headers=world.headers(world.crew)).json()
    scenes = tree["episodes"][0]["scene_list"]
    assert [(s["number"], s["shots"], s["runtime_s"], s["status"]) for s in scenes] == [(1, 3, 18, "split"),
                                                                                         (2, 0, 0, "draft")]
    assert scenes[0]["id"] == ids["s1"]
    assert tree["canon"] == {"characters": 2, "core_characters": 1, "locations": 1, "props": 0, "locked": 1}


def test_episode_detail_and_404(world: World):
    ids = seed(world)
    h = world.headers(world.writer)
    ep = world.client.get(f"/v1/productions/{world.production}/episodes/{ids['ep1']}", headers=h).json()
    assert ep["title"] == "The Return" and len(ep["scene_list"]) == 2
    assert world.client.get(f"/v1/productions/{world.production}/episodes/{uuid4()}", headers=h).status_code == 404
    other = world.client.get(f"/v1/productions/{world.other_production}/episodes/{ids['ep1']}",
                             headers=world.headers(world.admin))
    assert other.status_code == 404
    assert world.client.get(f"/v1/productions/{world.production}/structure",
                            headers=world.headers(world.outsider)).status_code == 404


def test_overview_is_one_read_of_production_structure_canon_and_open_questions(world: World):
    seed(world)
    pid = str(world.production)
    world.repos.questions.add(production_id=pid, status="open", created_at="2026-10-24T00:00:00Z")  # type: ignore[attr-defined]
    world.repos.questions.add(production_id=pid, status="answered", created_at="2026-10-24T00:00:00Z")  # type: ignore[attr-defined]
    h = world.headers(world.reviewer)
    body = world.client.get(f"/v1/productions/{pid}/overview", headers=h).json()
    assert body["production"]["id"] == pid and body["production"]["my_role"] == "reviewer"
    assert body["structure"] == world.client.get(f"/v1/productions/{pid}/structure", headers=h).json()
    assert body["canon"] == world.client.get(f"/v1/productions/{pid}/canon", headers=h).json()
    assert body["open_questions"] == 1
    assert world.client.get(f"/v1/productions/{pid}/overview",
                            headers=world.headers(world.outsider)).status_code == 404

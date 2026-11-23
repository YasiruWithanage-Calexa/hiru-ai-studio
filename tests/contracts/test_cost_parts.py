"""contracts.cost_parts (plan/2026-11-23b): every row is production setup, episode setup or scene; setup is charged to
its production or episode as dated entries; the person's decisions (all of Raphael is setup, chat is scene, re-reads and
re-plans are new entries) hold. No network, no database."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from contracts import cost_parts as cp
from contracts.costs import SEED_PRICES, cost_tokens

ROOT = Path(__file__).resolve().parents[2]
PRICES = list(SEED_PRICES)

E1, E2 = "ep-1", "ep-2"
S1, S2, S3 = "sc-1", "sc-2", "sc-3"
SCENES = [{"id": S1, "episode_id": E1, "number": 1}, {"id": S2, "episode_id": E1, "number": 2},
          {"id": S3, "episode_id": E2, "number": 1}]
EPISODES = [{"id": E1, "number": 1, "source_document_ids": ["doc-1"]},
            {"id": E2, "number": 2, "source_document_ids": ["doc-2"]}]
LINES = {S1: 10, S2: 20, S3: 30}  # E1 30 lines, E2 30 lines


def row(phase: str, *, job: str | None = None, scene: str | None = None, i: int = 1_000_000,
        at: str = "2026-11-05T00:00:00+00:00") -> dict:
    return {"phase": phase, "model": "gpt-5", "input_tokens": i, "cached_input_tokens": 0, "output_tokens": 0,
            "job_id": job, "scene_id": scene, "created_at": at}


ONE = cost_tokens(row("x.y"), PRICES).micros  # one 1M-token gpt-5 call at its final price


def figures(rows, jobs=None, episodes=EPISODES):
    return cp.setup_figures(rows, jobs or {}, SCENES, episodes, LINES, PRICES)


# ── the part of a row ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("phase", "part"), [
    ("doc_ingest.role", "episode_setup"), ("breakdown.read", "episode_setup"), ("breakdown.stager", "episode_setup"),
    ("script_split.plan", "episode_setup"), ("structure_build.x", "episode_setup"),
    ("raphael.plan", "episode_setup"), ("raphael.cinematic", "episode_setup"), ("adam.x", "episode_setup"),
    ("canon_extract.x", "production_setup"), ("breakdown.canon", "production_setup"),
    ("breakdown.looks", "production_setup"), ("breakdown.series", "production_setup"), ("search.answer",
                                                                                         "production_setup"),
    ("zora.reply", "scene"), ("sable.act", "scene"), ("director.reply", "scene"), ("shot_producer.x", "scene"),
    ("camera_agent.design", "scene"), ("shot_prompter.write", "scene"), ("frame_render.image", "scene"),
    ("video_render.omni_flash", "scene"),
])
def test_each_phase_has_its_part(phase: str, part: str):
    assert cp.part_of(phase, None) == part


def test_breakdown_continuity_is_not_mistaken_for_canon():
    assert cp.part_of("breakdown.continuity", None) == "episode_setup"
    assert cp.part_of("breakdown.canonical", None) == "episode_setup"  # a name, not a segment


def test_the_job_decides_canon_refine_and_sheets():
    assert cp.part_of("breakdown.read", {"kind": "canon_refine"}) == "production_setup"
    character = {"kind": "frame_render", "request": {"entity_id": "e1"}}
    look = {"kind": "frame_render", "request": {"look_id": "l1"}}
    first_frame = {"kind": "frame_render", "request": {"scene_id": S1}}
    assert cp.part_of("frame_render.image", character) == "production_setup"
    assert cp.part_of("frame_render.image", look) == "production_setup"
    assert cp.part_of("frame_render.image", first_frame) == "scene"
    assert cp.sheet_kind(character) == "character" and cp.sheet_kind(look) == "look"


def _declared_phases() -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "src" / "libs" / "hiru_ai").rglob("component.yaml"):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*phase:\s*([\w.]+)", line)
            if m:
                found.add(m.group(1))
    literal = re.compile(r"""["']phase["']\s*:\s*f?["']([a-z_]+\.[a-z_{}.]*)["']"""
                         r"""|PHASE\w*\s*=\s*["']([a-z_]+\.[\w.]*)["']""")
    for path in (ROOT / "src").rglob("*.py"):
        for m in literal.finditer(path.read_text(encoding="utf-8")):
            found.add((m.group(1) or m.group(2)).split("{")[0])
    return found


def test_every_phase_in_the_code_is_placed():
    """A new agent or engine phase must be added to the table, or its spend lands in production setup unseen."""
    phases = _declared_phases()
    assert len(phases) > 30
    assert sorted(p for p in phases if not cp.known_phase(p)) == []


# ── which episode ─────────────────────────────────────────────────────────────────────────────


def test_a_setup_row_finds_its_episode_by_scene_then_job_scene_then_document():
    by_doc = cp.document_episodes(EPISODES)
    scene_ep = {S1: E1, S2: E1, S3: E2}
    assert cp.episodes_of(row("raphael.plan", scene=S3), None, scene_ep, by_doc) == (E2,)
    assert cp.episodes_of(row("raphael.plan"), {"request": {"scene_id": S1}}, scene_ep, by_doc) == (E1,)
    assert cp.episodes_of(row("doc_ingest.x"), {"request": {"document_id": "doc-2"}}, scene_ep, by_doc) == (E2,)
    assert cp.episodes_of(row("structure_build.x"), {"request": {}}, scene_ep, by_doc) == cp.ALL_EPISODES
    assert cp.episodes_of(row("doc_ingest.x"), {"request": {"document_id": "bible"}}, scene_ep, by_doc) == ()


def test_share_adds_up_and_follows_lines():
    assert cp.share(100, [E1, E2], {E1: 1, E2: 3}) == {E1: 25, E2: 75}
    assert sum(cp.share(101, ["a", "b", "c"], {}).values()) == 101  # no lines: equal, remainder to the first
    assert cp.share(5, [], {}) == {}


# ── the setup figures ─────────────────────────────────────────────────────────────────────────


def test_raphael_is_episode_setup_and_chat_and_frames_are_not():
    rows = [row("raphael.plan", scene=S1), row("raphael.plan", scene=S3), row("zora.reply", scene=S1),
            row("frame_render.image", job="f1", scene=S1)]
    got = figures(rows, {"f1": {"kind": "frame_render", "request": {"scene_id": S1}}})
    assert got.episodes[E1].micros == ONE and got.episodes[E2].micros == ONE
    assert [e.label for e in got.episodes[E1].entries] == ["Upload and first plan"]
    assert got.production.micros == 0


def test_a_replan_and_a_reread_are_their_own_dated_entries():
    jobs = {"read1": {"kind": "doc_ingest", "request": {"document_id": "doc-1"}, "created_at": "2026-11-01"},
            "read2": {"kind": "doc_ingest", "request": {"document_id": "doc-1"}, "created_at": "2026-11-09"},
            "re": {"kind": "plan_scene_raphael", "request": {"scene_id": S2}, "created_at": "2026-11-10"},
            "cine": {"kind": "cinematic_scene_raphael", "request": {"scene_id": S2}, "created_at": "2026-11-11"}}
    rows = [row("doc_ingest.read", job="read1", at="2026-11-01T00:00:00+00:00"),
            row("raphael.plan", scene=S1, at="2026-11-02T00:00:00+00:00"),
            row("doc_ingest.read", job="read2", at="2026-11-09T00:00:00+00:00"),
            row("raphael.plan", job="re", scene=S2, at="2026-11-10T00:00:00+00:00"),
            row("raphael.cinematic", job="cine", scene=S2, at="2026-11-11T00:00:00+00:00")]
    e1 = figures(rows, jobs).episodes[E1]
    assert [(e.label, e.micros) for e in e1.entries] == [
        ("Upload and first plan", 2 * ONE), ("Document read again", ONE), ("Re-plan, scene 2", ONE),
        ("More cinematic, scene 2", ONE)]
    assert e1.micros == 5 * ONE and e1.complete


def test_production_build_work_is_shared_by_lines():
    got = figures([row("structure_build.x"), row("script_split.plan")])
    assert got.episodes[E1].micros + got.episodes[E2].micros == 2 * ONE
    assert got.episodes[E1].micros == ONE  # 30 lines each
    assert got.episodes[E1].entries[0].label == "Production build, shared by lines"


def test_production_setup_is_kept_by_kind():
    jobs = {"face": {"kind": "frame_render", "request": {"entity_id": "kamala"}},
            "look": {"kind": "frame_render", "request": {"look_id": "saree"}},
            "refine": {"kind": "canon_refine", "request": {}}}
    rows = [row("frame_render.image", job="face"), row("frame_render.image", job="look"),
            row("breakdown.read", job="refine"), row("canon_extract.x"), row("breakdown.canon"),
            row("search.answer")]
    got = figures(rows, jobs)
    assert {e.label: e.micros for e in got.production.entries} == {
        "Character sheets": cost_tokens(rows[0], PRICES).micros, "Look sheets": cost_tokens(rows[1], PRICES).micros,
        "Canon refine": ONE, "Canon": 2 * ONE, "Questions about the production": ONE}
    assert all(s.micros == 0 for s in got.episodes.values())


def test_with_no_episodes_yet_episode_setup_is_kept_on_the_production():
    got = figures([row("doc_ingest.read")], episodes=[])
    assert [(e.label, e.micros) for e in got.production.entries] == [("Not yet in an episode", ONE)]
    assert got.episodes == {}


def test_a_missing_price_makes_a_setup_incomplete_never_zero():
    rows = [row("raphael.plan", scene=S1) | {"model": "gpt-9-unknown"}, row("raphael.plan", scene=S1)]
    e1 = figures(rows).episodes[E1]
    assert e1.micros == ONE and e1.complete is False


def test_every_setup_row_is_counted_exactly_once():
    rows = [row(p, scene=s) for p in ("raphael.plan", "doc_ingest.x", "structure_build.y", "canon_extract.z")
            for s in (S1, None)]
    got = figures(rows)
    setup_rows = [r for r in rows if cp.part_of(r["phase"], None) != "scene"]
    total = got.production.micros + sum(s.micros for s in got.episodes.values())
    assert total == sum(cost_tokens(r, PRICES).micros for r in setup_rows)

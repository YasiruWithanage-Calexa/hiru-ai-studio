"""One scene through Shot Planner Raphael (plan/2026-11-08e §3, §4, phase 3): two stages, one meter.

    stage 1   raphael_planner    ONE model, one conversation, code tools only: the intended cut, then the must clips
    stage 2   raphael_cinematic  a FRESH conversation over stage 1's locked bin: cinematic clips on the moments that
    earn
                                 them, blend notes and a review of every moment (S5: right after stage 1, automatically)

Both run under ONE `Meter` (the $5 run cap covers both: stage 2 gets what stage 1 left) and ONE length cap (the person's
choice, 1.5x / 2x / 2.5x / 3x: stage 2's room is the cap minus stage 1's seconds). The chosen cap is stored with the
result.

What a stop means (D1, the plan's recommendation): a stage that ends early (turns, the run cap, an error) is saved
marked
`stopped`. Stage 1's bin is saved whole when stage 2 fails or is stopped; stage 2's clips are saved only if they pass
the
checks. A scene whose input is unchanged since Raphael planned it makes no call.

Pure orchestration over the agents by id: no database here. The caller (graph.py) reads the rows and writes them.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, replace
from typing import Any

from langchain_core.messages import AIMessage

from contracts import sceneplan
from contracts.raphael import checks, pack
from contracts.raphael.bin import Bin
from contracts.raphael.money import CapReached, Meter, Unpriced, price_of
from contracts.raphael.scene import BlockS, Brief, PlaceS, SceneS, mark_recorded, norm, plain_name, scene_dump
from contracts.raphael.stored import Left, Seconds, StoredRaphael
from contracts.raphael.tools import Stage1Session, Stage2Session
from contracts.raphael.wire import DEFAULT_CAP, LENGTH_CAPS, BreakdownW, Clip, ReviewRow
from contracts.stagemap import SceneStaging
from hiru_ai.core import agents
from hiru_ai.core.agents import Stop
from hiru_ai.core.context import RunContext
from hiru_ai.core.models import resolve
from hiru_ai.core.settings import get_settings
from hiru_ai.core.usage import UsageRow

_log = logging.getLogger(__name__)
Row = dict[str, Any]
BREAKDOWN_MAX_OUTPUT = 16_000  # charged for a breakdown call when no usage is reported
NO_MODEL = "Shot Planner Raphael needs the AI model, which is not available. Use the classic planner for this scene."
STOPPED = {
    "turns": "Raphael used all its turns before it finished.",
    "cap": "The planning run reached its limit before it finished.",
    "idle": "Raphael stopped answering before it finished.",
    "stuck": "Raphael kept meeting the same checks without getting closer, so it was stopped early.",
    "error": "A call to the model failed before Raphael finished.",
}


class Failed(Exception):
    """The scene could not be planned; the message says why, in words a person reads."""


@dataclass
class Ledger:
    """The scene's state map (plan/2026-11-09 phase 3): the one the scene had, or the one the stager just made (saved
    with the shots, `made`), or none (`note` says why, on the job's events)."""

    staging: SceneStaging | None = None
    made: bool = False
    note: str = ""


@dataclass
class Unchanged:
    """A scene whose input is the one its stored result was made from: it is kept as it is."""

    stored: StoredRaphael
    ledger: Ledger = field(default_factory=Ledger)


@dataclass
class Planned:
    stored: StoredRaphael
    log: list[str] = field(default_factory=list)
    ledger: Ledger = field(default_factory=Ledger)
    warnings: list[str] = field(default_factory=list)  # plan/2026-11-10: a breakdown that failed twice, for the job


# ── the scene, as Raphael is given it ────────────────────────────────────────────────────────────


def script_of(
    scene: Row, lines: list[Row], *, cast: list[str], others: list[str], place: str, objects: list[str]
) -> tuple[SceneS, dict[str, str]]:
    """The scene's blocks as `SceneS` (with the time its reading gives them), and the map from the short line id the
    agent
    sees (L<block>) to the dialogue line's real id."""
    items = sceneplan.scene_items(scene, lines)
    line_ids: dict[str, str] = {}
    blocks = []
    for item in items:
        block = BlockS.of(item)
        if item.is_line:
            short = f"L{item.index}"  # the line at block 4 is L4: the id says where the line is
            line_ids[short] = str(item.line_id)
            block = block.model_copy(update={"line_id": short})
        blocks.append(block)
    blocks = mark_recorded(blocks)  # a voice message the action names is heard, not performed (plan/2026-11-08f)
    envelope = scene.get("envelope_s")
    return (
        SceneS(
            blocks=blocks,
            cast=cast,
            others=others,
            place=PlaceS(name=place, objects=objects),
            envelope_s=float(envelope) if envelope else None,
        ),
        line_ids,
    )


def present(characters: list[Row], blocks: list[BlockS]) -> list[str]:
    """The people in the scene: those who speak, and those the script names (their name or an alias in a block)."""
    text = norm(" ".join(b.text for b in blocks))
    speakers = {norm(plain_name(b.speaker)) for b in blocks if b.speaker}
    out = []
    for c in characters:
        names = [str(c.get("name") or ""), *[str(a) for a in c.get("aliases") or []]]
        if any(norm(n) in speakers or (norm(n) and norm(n) in text) for n in names):
            out.append(str(c["name"]))
    known = {norm(n) for n in out}
    unlisted = {
        norm(plain_name(b.speaker)): plain_name(b.speaker)
        for b in blocks
        if b.speaker and norm(plain_name(b.speaker)) not in known
    }
    return out + list(unlisted.values())


def others_of(characters: list[Row], cast: list[str]) -> list[str]:
    """Names and nicknames of the production's people who are NOT in the scene."""
    here = {norm(c) for c in cast}
    out = []
    for c in characters:
        if norm(str(c.get("name") or "")) in here:
            continue
        out += [n for n in [str(c.get("name") or ""), *[str(a) for a in c.get("aliases") or []]] if n.strip()]
    return out


def objects_of(props: list[Row], location: Row | None, blocks: list[BlockS]) -> list[str]:
    """What the place has that a picture may show: the production's props the script or the location card names."""
    look = str((((location or {}).get("current") or {}).get("card") or {}).get("look") or "")
    text = norm(" ".join(b.text for b in blocks) + " " + look)
    return [str(p["name"]) for p in props if norm(str(p.get("name") or "")) and norm(str(p["name"])) in text]


def from_packet(packet: Row, lines: list[Row]) -> tuple[str, SceneS, dict[str, str]] | None:
    """The packet path (plan/2026-11-11 phase 4): stage 1's opening, the `SceneS` Raphael's code reads, and the map from
    the short line id (L<block>) to the scene's real `dialogue_lines` row. The breakdown fills one row per spoken block,
    in block order, so the n-th spoken block is the line of `ord` n; a scene whose count differs is not planned from the
    packet (None: today's path)."""
    from contracts.raphael.packet import opening

    text, script, ids = opening(packet)
    shorts = sorted((k for k in ids if k.startswith("L")), key=lambda k: int(k[1:]))
    rows = sorted(lines, key=lambda r: int(r.get("ord") or 0))
    if len(shorts) != len(rows):
        return None
    return text, script, {short: str(row["id"]) for short, row in zip(shorts, rows, strict=True)}


def a_cap(value: Any, default: float = DEFAULT_CAP) -> float:
    """The length cap asked for, or the default when it is not one of the four choices."""
    try:
        cap = float(value)
    except (TypeError, ValueError):
        return default
    return cap if cap in LENGTH_CAPS else default


# ── the planner ──────────────────────────────────────────────────────────────────────────────────


class Planner:
    """Plans one scene. `production` is {style_note, rules, people[...]}; `context` is {heading, note, episode_title,
    synopsis, before, after, place}; `extra` is a person's reading of the scene (kept as the script's footnote)."""

    def __init__(
        self,
        ctx: RunContext,
        scene: SceneS,
        *,
        number: int,
        line_ids: dict[str, str],
        production: Row,
        context: Row,
        cap: float = DEFAULT_CAP,
        extra: str = "",
        allowed: tuple[str, ...] | None = None,
        meter: Meter | None = None,
        use_breakdown: bool | None = None,
        opening: str = "",
        mood: tuple[str, ...] = (),
    ) -> None:
        self.ctx, self.scene, self.number, self.line_ids = ctx, scene, number, line_ids
        self.production, self.context, self.extra = production, context, extra
        self.cap = a_cap(cap)
        self.allowed = allowed
        self.brief = Brief(scene=scene, guide_s=float(scene.envelope_s or 0))
        # One scene's limit for both stages (plan/2026-11-08f §4): the setting, not the lab's $5.
        self.meter = meter or Meter(cap_usd=get_settings().raphael_scene_cap_usd)
        self.log: list[str] = []
        self.warnings: list[str] = []
        self.turns = {"stage1": 0, "stage2": 0}
        self.model = ""
        # plan/2026-11-10: the director's breakdown, `RAPHAEL_BREAKDOWN` (false: Raphael as it was before)
        self.use_breakdown = get_settings().raphael_breakdown if use_breakdown is None else use_breakdown
        self.breakdown: BreakdownW | None = None
        # plan/2026-11-11 phase 4: the scene packet's opening (`contracts.raphael.packet.opening`). Set, it is stage 1's
        # first message and there is no director's breakdown (purpose, turns and direction are in the packet, §6).
        self.packet_opening = opening
        self.mood = [" ".join(str(m).split()) for m in mood if str(m).strip()]  # plan/2026-11-12b D7: the packet's
        if opening:
            self.use_breakdown = False

    # the agents' input ────────────────────────────────────────────────────────────────────────

    def opening1(self) -> str:
        if self.packet_opening:
            return self.packet_opening
        return pack.opening_stage1(self.production, self.context, self.brief, self.extra, self.breakdown)

    def input_hash(self) -> str:
        """What Raphael was given, as a hash: a re-plan whose hash is unchanged keeps the stored result. The cap is
        part of
        it: another cap is another result. The scene's state map is part of it (plan/2026-11-09): a changed or a
        person's map plans again; a scene with no map hashes as it did before the map was added."""
        body = json.dumps(
            # the opening WITHOUT the breakdown: a re-plan of the same input keeps (and reuses) the stored breakdown
            {
                "pack": self.packet_opening
                or pack.opening_stage1(self.production, self.context, self.brief, self.extra),
                "scene": scene_dump(self.scene),
                "cap": self.cap,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(body.encode()).hexdigest()[:16]

    # the model's conversation ─────────────────────────────────────────────────────────────────

    def converse(self, agent: agents.Agent, inp: Any, run: Stage1Session | Stage2Session) -> agents.Conversation:
        """One conversation under the run's meter. A priced model is checked first; every reply is charged."""
        agent_id = agent.id
        tier = resolve(agent.manifest.model)
        try:
            price_of(tier.model)
        except Unpriced as exc:
            raise Failed(f"{exc}. Set a priced model for Raphael or add its price.") from exc
        self.model = tier.model
        args = agent.hooks.converse_args(inp, run)
        if args.get("later_tier"):  # the repair turns may be on another model: it needs a price too
            try:
                price_of(resolve(args["later_tier"]).model)
            except Unpriced as exc:
                raise Failed(f"{exc}. Set a priced model for Raphael's repair turns or add its price.") from exc
        base_before = args.pop("before")

        def priced(reply: AIMessage) -> str:
            """The model that answered (a repair turn may be another than the first), else the agent's tier."""
            said = str((reply.response_metadata or {}).get("model_name") or "")
            try:
                price_of(said)
                return said
            except Unpriced:
                return tier.model

        def before(turn: int) -> None:
            base_before(turn)
            if run.stuck:  # plan/2026-11-08f §4: no fewer blocking faults for several reports; more turns won't help
                raise Stop("stuck", f"{run.blocked} blocking fault(s) after {run.flat} reports without progress")
            try:
                self.meter.guard()
            except CapReached as exc:
                raise Stop("cap", str(exc)) from exc

        def after(turn: int, reply: AIMessage) -> None:
            meta = getattr(reply, "usage_metadata", None) or {}
            if meta:
                self.meter.charge(
                    priced(reply),
                    int(meta.get("input_tokens", 0)),
                    int((meta.get("input_token_details") or {}).get("cache_read", 0) or 0),
                    int(meta.get("output_tokens", 0)),
                )
            else:  # no usage reported: entered at the worst case, like the lab
                self.meter.charge(priced(reply), 0, 0, int(args.get("max_output") or 0))

        try:
            return agent.converse(inp, self.ctx, before=before, after=after, **args)
        except Exception as exc:
            _log.warning("%s failed", agent_id, exc_info=True)
            raise Failed(
                f"{agent_id} could not answer ({type(exc).__name__}). Try again, or use the classic planner for this "
                f"scene."
            ) from exc

    # the director's breakdown (plan/2026-11-10) ───────────────────────────────────────────────

    def ask_breakdown(self, faults: list[str]) -> BreakdownW:
        """ONE request, no tools, under the run's meter. Raises `Unpriced` / `CapReached` before spending."""
        agent = agents.build("raphael_breakdown")
        tier = resolve(agent.manifest.model)
        price_of(tier.model)
        self.meter.guard()
        seen: list[UsageRow] = []

        def tee(row: UsageRow) -> None:
            seen.append(row)
            if self.ctx.usage_sink is not None:
                self.ctx.usage_sink(row)

        inp = {"opening": pack.scene_opening(self.production, self.context, self.brief, self.extra), "faults": faults}
        out = agent.run(inp, replace(self.ctx, usage_sink=tee))
        for row in seen:
            model = str(row.get("model") or "")
            try:
                price_of(model)
            except Unpriced:
                model = tier.model
            self.meter.charge(
                model,
                int(row.get("input_tokens") or 0),
                int(row.get("cached_input_tokens") or 0),
                int(row.get("output_tokens") or 0),
            )
        if not seen:  # no usage reported: entered at the worst case, like the conversations
            self.meter.charge(tier.model, 0, 0, BREAKDOWN_MAX_OUTPUT)
        return BreakdownW.model_validate(out.model_dump(mode="json"))

    def make_breakdown(self, reuse: BreakdownW | None = None) -> None:
        """The scene's breakdown: the stored one when the input is the same, else one request, one retry with the
        faults listed, and when it still fails, none: stage 1 runs as it did before, and the job gets a warning."""
        self.breakdown = None
        if not self.use_breakdown:
            return
        if reuse is not None:
            self.breakdown = reuse
            self.log.append(f"breakdown: kept the stored one ({len(reuse.shots)} shots)")
            return
        faults: list[str] = []
        why = ""
        for attempt in (1, 2):
            try:
                made = self.ask_breakdown(faults)
            except (CapReached, Unpriced) as exc:
                why = str(exc)
                break
            except Exception as exc:  # a model that fails here must not stop the scene
                _log.warning("raphael_breakdown failed", exc_info=True)
                why = f"the request failed ({type(exc).__name__})"
                continue
            faults = checks.breakdown_faults(self.brief, made)
            if not faults:
                self.breakdown = made
                self.log.append(f"breakdown: {len(made.shots)} shots (attempt {attempt})")
                return
            why = "it had faults: " + " ".join(faults[:3])
        self.log.append(f"breakdown: none ({why})")
        self.warnings.append(f"No director's breakdown for this scene, planned without it: {why}")

    # stage 1 ──────────────────────────────────────────────────────────────────────────────────

    def stage1(self) -> tuple[Stage1Session, agents.Conversation]:
        agent = agents.build("raphael_planner")
        data: Row = {
            "opening": self.opening1(),
            "scene": self.scene.model_dump(mode="json"),
            "guide_s": self.brief.guide_s,
            "scene_no": str(self.number),
        }
        if self.breakdown is not None:
            data["breakdown"] = self.breakdown.model_dump(mode="json")
        if self.allowed is not None:
            data["allowed"] = list(self.allowed)
        inp = agent.input_cls.model_validate(data)
        run = agent.hooks.session(inp)
        done = self.converse(agent, inp, run)
        self.turns["stage1"] = done.turns
        self.log.append(f"stage 1: {done.stopped} after {done.turns} turns")
        return run, done

    # stage 2 ──────────────────────────────────────────────────────────────────────────────────

    def stage2(self, work: Bin) -> tuple[Stage2Session, agents.Conversation]:
        assert work.edit is not None
        agent = agents.build("raphael_cinematic")
        data: Row = {
            "opening": pack.opening_stage2(
                self.production, self.context, self.brief, work, self.cap, self.extra, self.breakdown
            ),
            "scene": self.scene.model_dump(mode="json"),
            "guide_s": self.brief.guide_s,
            "scene_no": str(self.number),
            "edit": work.edit.model_dump(mode="json"),
            "clips": [c.model_dump(mode="json") for c in work.musts()],
            "cap": self.cap,
        }
        if self.allowed is not None:
            data["allowed"] = list(self.allowed)
        inp = agent.input_cls.model_validate(data)
        run = agent.hooks.session(inp)
        done = self.converse(agent, inp, run)
        self.turns["stage2"] = done.turns
        self.log.append(f"stage 2: {done.stopped} after {done.turns} turns")
        return run, done

    # the result ───────────────────────────────────────────────────────────────────────────────

    def left_of(self, found: list[checks.Fault]) -> list[Left]:
        return [Left(code=f.code, sentence=f.sentence, clips=f.clips, fix=f.fix, key=f.key) for f in found]

    def seconds_of(self, work: Bin) -> Seconds:
        n = work.counts()
        return Seconds(
            target_s=self.brief.guide_s,
            cap_s=checks.limit_s(self.brief, self.cap),
            take_s=n["take_s"],
            must_s=n["must_take_s"],
            cinematic_s=n["extra_take_s"],
        )

    def keep_what_passes(self, run: Stage2Session) -> None:
        """A stage 2 that stopped: keep only the cinematic clips that pass the checks (D1). A clip named by a blocking
        fault
        is dropped, nice ones first when the bin is over its cap; stage 1's clips are never touched."""
        work = run.work
        for _ in range(len(work.clips) + 1):
            blocked = checks.blocking(run.found())
            if not blocked:
                return
            ids = {c for f in blocked for c in f.clips if (clip := work.by_id(c)) is not None and clip.is_extra}
            if not ids:
                # a fault no cinematic clip owns: the whole pass is dropped, stage 1's bin stands
                for e in work.extras():
                    work.remove(e.id)
                return
            if any(f.key == "length:stage2" for f in blocked):
                ids = {sorted(work.extras(), key=lambda e: (e.priority != "nice", e.id))[0].id}
            for clip_id in ids:
                work.remove(clip_id)

    def build(
        self,
        work: Bin,
        *,
        job_id: str,
        previous: Row,
        stage1: str,
        stage2: str,
        stopped: str,
        editor_notes: list[str],
        blend_notes: list[str],
        review: list[ReviewRow],
        found: list[checks.Fault],
    ) -> Planned:
        assert work.edit is not None
        report = {
            "turns": dict(self.turns),
            "calls": self.meter.calls,
            "log": list(self.log),
            "model": self.model,
        }
        reported = {f.key for f in found}
        found = [*found, *(f for f in checks.breakdown_missing(self.breakdown, work) if f.key not in reported)]
        stored = StoredRaphael(
            job_id=job_id,
            input_hash=self.input_hash(),
            stage1=stage1,  # type: ignore[arg-type]
            stage2=stage2,  # type: ignore[arg-type]
            stopped=stopped,
            cap=self.cap,
            edit=work.edit,
            clips=work.clips,
            line_ids=dict(self.line_ids),
            editor_notes=editor_notes,
            blend_notes=blend_notes,
            review=review,
            seconds=self.seconds_of(work),
            left=self.left_of(found),
            report=report,
            breakdown=self.breakdown,
            mood=list(self.mood),
            previous=previous,
        )
        return Planned(stored, log=list(self.log), warnings=list(self.warnings))

    def plan(
        self, *, previous: Row, job_id: str, only_stage1: bool = False, reuse: BreakdownW | None = None
    ) -> Planned:
        """The whole scene: the director's breakdown, then stage 1, then (S5) stage 2 right after. `reuse` is the
        stored breakdown of a scene whose input is unchanged."""
        self.make_breakdown(reuse)
        run1, done1 = self.stage1()
        work = run1.work
        if not done1.ok:
            clips = [c for c in work.clips if c.ir is not None]
            if work.edit is None or not clips:
                raise Failed(
                    f"{STOPPED.get(done1.stopped, 'Raphael stopped')} It had written nothing to keep. Use the classic "
                    f"planner "
                    "for this scene."
                )
            work.clips = clips
            return self.build(
                work,
                job_id=job_id,
                previous=previous,
                stage1="stopped",
                stage2="skipped",
                stopped=STOPPED.get(done1.stopped, "Raphael stopped before it finished."),
                editor_notes=[],
                blend_notes=[],
                review=[],
                found=run1.faults(),
            )
        editor_notes = list(run1.editor_notes)
        if work.edit is not None:
            work.edit = work.edit.model_copy(update={"editor_notes": editor_notes})
        if only_stage1:
            return self.build(
                work,
                job_id=job_id,
                previous=previous,
                stage1="finished",
                stage2="skipped",
                stopped="",
                editor_notes=editor_notes,
                blend_notes=[],
                review=[],
                found=checks.check_stage1(self.brief, work, run1.allowed),
            )
        return self.cinematic_over(work, job_id=job_id, previous=previous, editor_notes=editor_notes)

    def cinematic_over(self, work: Bin, *, job_id: str, previous: Row, editor_notes: list[str]) -> Planned:
        """Stage 2 over a finished must bin. Stage 1's clips are saved whatever happens here."""
        musts = Bin(scene=work.scene)
        musts.edit = work.edit
        musts.clips = [c.model_copy(deep=True) for c in work.musts()]
        musts.next_no = max((int(c.id[1:]) for c in musts.clips if c.id[1:].isdigit()), default=0) + 1
        try:
            run2, done2 = self.stage2(musts)
        except Failed as exc:
            self.log.append(f"stage 2 failed: {exc}")
            return self.build(
                musts,
                job_id=job_id,
                previous=previous,
                stage1="finished",
                stage2="stopped",
                stopped="The cinematic pass could not run; the must clips are saved.",
                editor_notes=editor_notes,
                blend_notes=[],
                review=[],
                found=checks.check_stage1(self.brief, musts),
            )
        out = run2.work
        if done2.ok:
            return self.build(
                out,
                job_id=job_id,
                previous=previous,
                stage1="finished",
                stage2="finished",
                stopped="",
                editor_notes=editor_notes,
                blend_notes=run2.blend_notes,
                review=run2.review,
                found=run2.found(),
            )
        self.keep_what_passes(run2)
        notes = [
            f"{e.id}: {e.blend} with {', '.join(e.anchor)} (the cinematic pass stopped before it wrote a note)"
            for e in out.extras()
        ]
        return self.build(
            out,
            job_id=job_id,
            previous=previous,
            stage1="finished",
            stage2="stopped",
            stopped=STOPPED.get(done2.stopped, "The cinematic pass stopped before it finished."),
            editor_notes=editor_notes,
            blend_notes=notes,
            review=[],
            found=run2.found(),
        )

    def more_cinematic(self, stored: StoredRaphael, *, previous: Row, job_id: str) -> Planned:
        """ "More cinematic": stage 2 alone over the stored must clips, with the cap chosen now. The old cinematic
        clips go;
        stage 1 is not paid for again."""
        if stored.stage1 != "finished" or stored.edit is None:
            raise Failed(
                "Stage 1 did not finish for this scene, so there is no must bin to add to. Plan the scene again."
            )
        self.breakdown = stored.breakdown if self.use_breakdown else None  # "more cinematic" reads the stored one
        work = Bin(scene=str(self.number))
        work.edit = stored.edit
        work.clips = [c.model_copy(deep=True) for c in stored.musts()]
        return self.cinematic_over(
            work, job_id=job_id, previous=previous or stored.previous, editor_notes=list(stored.editor_notes)
        )


def clips_of(stored: StoredRaphael) -> list[Clip]:
    return list(stored.clips)

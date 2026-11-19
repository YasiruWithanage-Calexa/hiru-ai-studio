"""Planner-free checks on a `Coverage` (plan/2026-11-13 §3.3), in code. No model, no planner.

    find(cov) -> [Finding]           every finding on the scene as it is
    new(before, after) -> [Finding]  only what an edit introduced (keys use handles, so renumbering is not "new")
    budget(cov) -> [Finding]         the action budget (plan/2026-11-18c, H-16): over budget, a door left open, a
                                     speaker turned away
    repairable(found)                the ones the author is asked to fix
    unvoiced(cov)                    the clips that perform a line but are stored silent, with the mode each must carry

A finding's `fix`: "repair" (the author is asked to fix it), "report" (told to the person, never blocking), "code" (code
fixes it with no model: `line_unvoiced`). An overrun is reported with the way out and never trimmed.
"""
from __future__ import annotations

from dataclasses import dataclass

from contracts import action_budget as ab
from contracts import safe_depiction
from contracts.coverage.scene import IR_JSON, IR_TEXT, VOICED, Clip, Coverage
from contracts.timing import speech_seconds

LONG_SHARE = 1.5  # takes over 1.5x the scene's target length are reported (Raphael's stage 1 cap)


@dataclass(frozen=True)
class Finding:
    key: str
    code: str
    sentence: str
    fix: str = "repair"


def unvoiced(cov: Coverage) -> list[tuple[Clip, str]]:
    """(clip, the mode it must carry) for each clip that performs a line with a sound mode that voices nothing (Veo
    was told "nobody speaks" over a spoken line). The right mode is unambiguous (`Coverage.voice_for`)."""
    out = []
    for c in cov.clips:
        if c.sound_mode not in VOICED and cov.performs(c.h):
            out.append((c, cov.voice_for(c)))
    return out


def find(cov: Coverage) -> list[Finding]:
    out: list[Finding] = []
    covered = {i for c in cov.clips for i in c.blocks}
    for b in cov.blocks:
        if b.index not in covered:
            out.append(Finding(f"block_unshown:b{b.index}", "block_unshown",
                               f"No clip shows b{b.index} ({b.kind}): every block is shown by at least one clip."))
    for ln in cov.lines.values():
        c = cov.clip(ln.by) if ln.by else None
        if c is None:
            out.append(Finding(f"line_unbound:{ln.lid}", "line_unbound",
                               f"{ln.lid} ({ln.speaker}'s line) is performed by no clip: one clip over b{ln.block} "
                               f"must perform it, with {ln.speaker} on screen."))
            continue
        code = cov.code(c.h)
        if ln.block not in c.blocks:
            out.append(Finding(f"line_outside:{ln.lid}:{c.h}", "line_outside",
                               f"{code} performs {ln.lid} but does not cover b{ln.block}."))
        if ln.speaker not in c.on_screen:
            out.append(Finding(f"speaker_unseen:{ln.lid}:{c.h}", "speaker_unseen",
                               f"{code} performs {ln.lid} but {ln.speaker} is not on screen in it (the line would be "
                               "heard, not seen).", "report"))
        need = speech_seconds(ln.words, ln.delivery)
        if need > c.take_s + 1e-9:
            way = "re-time it to 8 s" if c.take_s < 8 else "let the line run over the cut into the next clip, or split"
            # A take a person set is theirs: reported. A take a model shortened is repaired (re-time it).
            out.append(Finding(f"overrun:{ln.lid}:{c.h}", "overrun",
                               f"{ln.lid} needs about {need:.1f} s and {code} is {c.take_s} s: {way}. The line is "
                               "never trimmed.", "report" if "take_s" in c.locks else "repair"))
    for c, mode in unvoiced(cov):
        perf = cov.performs(c.h)
        lines = ", ".join(f"{ln.lid} ({ln.speaker})" for ln in perf)
        out.append(Finding(f"line_unvoiced:{c.h}", "line_unvoiced",
                           f"{cov.code(c.h)} performs {lines} but is stored {c.sound_mode}, so its video would be "
                           f"told nobody speaks: its sound should be {mode}.", "code"))
    slates = {c.slate for c in cov.clips if c.slate}
    for c in cov.clips:
        code = cov.code(c.h)
        if not c.why.strip() or not c.ir:
            out.append(Finding(f"picture_empty:{c.h}", "picture_empty",
                               f"{code} has no {'reason' if not c.why.strip() else 'camera design (IR)'} yet: "
                               "write its "
                               "why, beats, subjects and first frame."))
        gone = [a for a in c.anchor if a not in slates]
        if gone:
            out.append(Finding(f"anchor_gone:{c.h}", "anchor_gone",
                               f"{code} sits with {', '.join(gone)}, which is no longer in the scene.", "report"))
        parts = [str(c.ir.get(k) or "") for k in (*IR_TEXT, *IR_JSON, "cinematography")]
        text = " ".join([c.why, c.sees, c.note, *parts])
        words = sorted({f.word for f in safe_depiction.blocking(text)}) if text.strip() else []
        if words:
            out.append(Finding(f"unsafe:{c.h}", "unsafe",
                               f"{code}'s description uses {', '.join(words)}: the video model refuses it; "
                               "say what the "
                               "camera sees instead."))
    out += budget(cov)
    if cov.target_s and cov.total_s() > cov.target_s * LONG_SHARE:
        out.append(Finding("length", "length", f"The clips hold {cov.total_s()} s of takes against a {cov.target_s} s "
                                               f"scene (over {LONG_SHARE:g}x).", "report"))
    return out


def budget(cov: Coverage) -> list[Finding]:
    """The action budget (plan/2026-11-18c phase 6, house rule H-16): the same three faults Raphael's own check
    blocks on (`contracts.raphael.checks.action_budget`), on the clips as edited. Zora's author is asked to repair
    them; Sable's tools say them back to Sable; a person's own click or Accept only reports them (`fix` is the
    caller's: `new` keeps only what an edit introduced)."""
    out: list[Finding] = []
    for c in cov.clips:
        why = ab.count(ab.beats_of(c.ir)).over()
        if why:
            out.append(Finding(f"action_budget:{c.h}", "action_budget",
                               f"{cov.code(c.h)} is over the action budget: {'; '.join(why)}."))
    words = [" ".join([c.why, c.sees, *ab.beats_of(c.ir)]) for c in cov.clips]
    door = ab.door_left_open(words)
    if door is not None:
        c = cov.clips[door]
        out.append(Finding(f"door_open:{c.h}", "door_open",
                           f"{cov.code(c.h)} opens a door (or has it already open) and no clip closes it: a person "
                           "never walks away from an open car door. Close it in a clip, the person standing still, "
                           "before the walk away."))
    for c in cov.clips:
        if not cov.performs(c.h):
            continue
        away = ab.turned_away(ab.opening_of(c.ir))
        if away:
            out.append(Finding(f"speaker_hidden:{c.h}", "speaker_hidden",
                               f"{cov.code(c.h)} performs a line but opens with the speaker '{away}': its first "
                               "frame has no face. Open it with the speaker already turned to the camera's side, the "
                               "turn in the clip before."))
    return out


def new(before: Coverage, after: Coverage) -> list[Finding]:
    known = {f.key for f in find(before)}
    return [f for f in find(after) if f.key not in known]


def repairable(found: list[Finding]) -> list[Finding]:
    return [f for f in found if f.fix == "repair"]

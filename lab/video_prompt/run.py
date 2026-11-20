"""Video prompt lab (2026-11-20): ONE agent writes the direction of every video clip; code keeps the facts.

    .venv/Scripts/python.exe lab/video_prompt/run.py                     free: briefs + today's prompts, nothing sent
    .venv/Scripts/python.exe lab/video_prompt/run.py --yes               PAID: one model call per clip (cap $0.30)
    .venv/Scripts/python.exe lab/video_prompt/run.py --only 4A-2 --yes   PAID: the clips named

Why: findings/issues/2026-11-20/NATURAL-DIALOGUE.md. Today's prompt gives the model camera and safety text and a bare
`X says, "..."`; the packet already holds who each line is said to, its intent and a delivery hint, and none of it
reaches the video model. lab/natural_dialogue showed a director's prompt makes a scene, not an interview.

Scene: Api Denna v2 E01-S04 (Anudi, Kasun, the father's phone call), Raphael's saved run
(lab/llm_reader/runs/e2e/12_raphael/E01-S04.json, 18 clips). Today's prompts are rebuilt by the product's own serializer
through lab/coverage (nothing in src/ changes, nothing is written to the database).

The agent  system.md (what a director knows) + 1 to 3 cards (cards/*.md) picked by code for the clip + a brief: the
           scene (shared by every clip, so it caches) and the clip (facts from the product's shot input + Raphael's
           design). It answers direction only (situation, people, flow of actions and lines, camera, sound).
Gates      code checks every answer (lines once each, no Sinhala / ids / quotes in its text, nobody speaks in a silent
           clip, a heard voice is never placed in frame, no declined words, lengths). A failed answer gets ONE repair
           call; if that fails too, the clip keeps today's prompt.
Assembly   code writes the final prompt: the direction, each line's exact words from the database, the register line,
           camera, sound, the hands and clean-frame lines, the format and the picture citations.

Writes runs/<run>/: briefs/<slate>.txt, answers/<slate>.json, prompts.md (today and new, clip by clip), gates.md,
spend.json. A clip with an answer is never sent again. Key: OPENAI__API_KEY from the repo's .env.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "lab")]

SID = "E01-S04"
E2E = ROOT / "lab" / "llm_reader" / "runs" / "e2e"
SAVED = E2E / "12_raphael" / f"{SID}.json"
EFFORT = "low"
# $ per million tokens (contracts/costs.py, OpenAI list prices; the gpt-6.1 rows are marked "confirm") and each run's cap
MODELS: dict[str, dict[str, float]] = {
    "gpt-5-mini": {"in": 0.25, "cached": 0.025, "out": 2.00, "cap": 0.30},
    "gpt-6.1-terra": {"in": 1.00, "cached": 0.05, "out": 5.00, "cap": 0.30},
    "gpt-6.1-sol": {"in": 2.00, "cached": 0.10, "out": 10.00, "cap": 1.00},
}
RUN_DIR = {"gpt-5-mini": "001_gpt-5-mini", "gpt-6.1-terra": "002_gpt-6.1-terra", "gpt-6.1-sol": "003_gpt-6.1-sol"}
MODEL = "gpt-5-mini"
PRICE = MODELS[MODEL]
CAP_USD = PRICE["cap"]
NL = "\n"

SINHALA = re.compile(r"[඀-෿]")
LINE_ID = re.compile(r"\bL\d+\b|\bE\d+-S\d+-B\d+")
QUOTES = re.compile(r"[\"“”«»]")
SPEECH = re.compile(r"\b(say|says|said|saying|ask|asks|asked|tell|tells|told|repl(?:y|ies|ied)|whisper(?:s|ed)?|"
                    r"shout(?:s|ed)?|speak(?:s|ing)?|talk(?:s|ing)?|call(?:s)? out|murmur(?:s|ed)?|answers?)\b", re.I)
MOVING = re.compile(r"\b(handheld|hand-held|push(?:es)?[- ]in|dolly|pan(?:s|ning)?|tilt(?:s)?|zoom(?:s)?|tracking|"
                    r"drift(?:s)?|sway(?:s)?|creep(?:s)?)\b", re.I)
LIMITS = {"situation": 450, "people": 650, "camera": 300, "sound": 250, "step": 450}


# ── the agent's answer ───────────────────────────────────────────────────────────────────────────────────────────────


class Step(BaseModel):
    kind: Literal["action", "line"]
    text: str = Field(description="An action step: what happens, one or two sentences. A line step: empty.")
    line_id: str = Field(description="A line step: the line's id as the brief gives it. An action step: empty.")
    to: str = Field(description="A line step: who it is said to. An action step: empty.")
    how: str = Field(description="A line step: the delivery, a phrase. An action step: empty.")
    listener: str = Field(description="A line step: what the listener does. Empty when nobody else is there.")


class Direction(BaseModel):
    situation: str
    people: str
    flow: list[Step]
    camera: str
    sound: str


# ── the world: today's shot input, Raphael's design, the packet ──────────────────────────────────────────────────────


def coverage_lab() -> Any:
    spec = importlib.util.spec_from_file_location("coverage_lab", ROOT / "lab" / "coverage" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    mod.SID = SID
    return mod


def load() -> dict[str, Any]:
    from hiru_ai.steps.serialize.model import production_input, scene_input

    cov = coverage_lab()
    saved = json.loads(SAVED.read_text(encoding="utf-8"))
    w = cov.world()
    rows, lines = cov.shot_rows(w, saved["result"])
    prod = production_input(w["production"], w["canon"], None)
    scene = scene_input(w["scene"], rows, lines, w["canon"], prod)
    short = {block: lid for lid, block in saved["ids"].items() if lid.startswith("L")}  # block id -> L4
    clips = {c["slate"]: c for c in saved["result"]["clips"]}
    return {"cov": cov, "w": w, "rows": rows, "lines": lines, "scene": scene, "packet": w["packet"], "short": short,
            "clips": clips, "prod": prod}


def spoken(shot: Any) -> list[Any]:
    """The lines the clip itself speaks. A clip whose sound mode says nobody speaks (ambient, silent, music) carries its
    lines only as the edit's audio: today's serializer still writes them as speech (S05, S15), the lab does not."""
    return list(shot.lines) if shot.sound_mode in ("dialogue", "voiceover", "sung") else []


def words_of(text: str) -> str:
    return text.strip().strip("\"“”").strip()


def speech_s(text: str) -> float:
    """lab/sinhala_pace: Omni starts near 1 s, ~2.6 words/s, ~0.8 s between sentences."""
    body = words_of(text)
    sentences = max(1, len(re.findall(r"[.?!…]+", body)))
    return round(1.0 + len(body.split()) / 2.6 + 0.8 * (sentences - 1), 1)


# ── the brief ────────────────────────────────────────────────────────────────────────────────────────────────────────


def scene_brief(world: dict[str, Any]) -> str:
    p, short = world["packet"], world["short"]
    a = p["A_scene"]
    names = {x["id"]: x["name"] for x in p["B_people"]}
    out = [f"<scene>", f"Scene: {a.get('title') or a.get('heading')}. {a.get('summary', '')}",
           f"What it is for: {a.get('purpose', '')}"]
    before, after = a.get("before_in_story") or {}, a.get("after_in_story") or {}
    if before.get("ends_with"):
        out.append(f"Just before (the previous scene ends): {before['ends_with']}")
    if after.get("opens_with"):
        out.append(f"Next (the following scene opens): {after['opens_with']}")
    out.append(f"Place: {p['C_place'].get('name', '')}. Mood of the scene: {', '.join(p['F_feeling'].get('mood') or [])}.")
    out.append("People:")
    where = {"on_screen": "on screen", "phone": "heard on the phone only, never seen"}
    for x in p["B_people"]:
        out.append(f"- {x['name']} ({where.get(x['presence'], x['presence'])}): wants to {x.get('wants', '').rstrip('.')}"
                   f"; feels {x.get('feeling_start', '').rstrip('.').lower()} at the start, "
                   f"{x.get('feeling_end', '').rstrip('.').lower()} by the end.")
    for r in a.get("relationships") or []:
        out.append(f"Between {' and '.join(r['between'])}: {r['state']}")
    style = [" ".join(d["text"].split()) for d in p.get("G_direction") or []
             if d.get("about") != "other" or "style" in d["text"].lower() or "performance" in d["text"].lower()]
    if style:
        out.append("The production's direction: " + " ".join(style[:4]))
    out.append("Script, in order (a line's id is the name you use for it; the words are Sinhala):")
    for b in p["E_blocks"]:
        hint = f" | how (the reader's note): {b['delivery_hint']}" if b.get("delivery_hint") else ""
        intent = f" | intent: {b['intent']}" if b.get("intent") else ""
        if b["kind"] == "dialogue":
            who, to = names.get(b.get("speaker"), b.get("speaker")), names.get(b.get("addressee"), "")
            via = " (through the phone)" if b.get("presence") == "phone" else ""
            out.append(f"{short.get(b['id'], b['id'])} {who}{via} to {to or 'no one'}: \"{words_of(b['text'])}\"{hint}"
                       f"{intent}")
        else:
            out.append(f"action: {b['text']}{hint}{intent}")
    out.append("</scene>")
    return NL.join(out)


def cards_for(shot: Any, clip: dict[str, Any]) -> list[str]:
    seen_speak = [ln for ln in spoken(shot) if ln.character_id not in shot.staged.heard_only]
    heard = [ln for ln in spoken(shot) if ln.character_id in shot.staged.heard_only]
    out = []
    if seen_speak:
        out.append("dialogue")
    if heard or shot.staged.voice_source == "phone" or "phone" in str(clip.get("over", "")).lower():
        out.append("phone")
    if not spoken(shot) and shot.seen:
        out.append("silent")
    if not shot.seen or clip.get("role") in ("insert", "establishing", "cutaway", "pov", "atmosphere"):
        out.append("detail")
    if spoken(shot):
        out.append("sinhala_voice")
    return list(dict.fromkeys(out))


def clip_brief(world: dict[str, Any], shot: Any, clip: dict[str, Any]) -> str:
    short = world["short"]
    ir = clip.get("ir") or {}
    cine = ir.get("cinematography") or {}
    out = [f"<clip slate=\"{clip['slate']}\">",
           f"Role: {clip.get('role')}; framing {clip.get('size')} ({cine.get('framing', '')}); angle {clip.get('angle')}; "
           f"lens {clip.get('lens')}; camera move: {clip.get('technique')} ({cine.get('movement', '')}); "
           f"take {shot.duration_s} s.",
           f"Why the planner made it: {clip.get('why', '')}",
           f"Planner's summary: {clip.get('summary', '')}",
           f"Setting: {ir.get('setting', '')}", f"Light: {ir.get('lighting', '')}"]
    seen = {c.code for c in shot.seen}
    for s in ir.get("subjects") or []:
        if s.get("id") in seen or not seen:
            out.append(f"In frame: {s.get('description', '')} Position: {s.get('position', '')} Does: {s.get('action', '')}")
    for c in shot.heard:
        out.append(f"Only heard, never seen: {c.name}" + (" (through the phone)" if shot.staged.voice_source == "phone"
                                                          else ""))
    if not shot.seen:
        out.append("No person in frame.")
    if shot.hands:
        out.append(f"Hands (a fact, keep it): {shot.hands}")
    out.append("Planner's beats:")
    for b in ir.get("beats") or []:
        out.append(f"- {b.get('time', '')}: {b.get('director_line', '')} {b.get('action', '')} {b.get('performance', '')}")
    snd = clip.get("sound") or {}
    out.append(f"Planner's sound: ambience {snd.get('ambience', '')}; effects {snd.get('effects', '')}; "
               f"music {snd.get('music', '')}.")
    if spoken(shot):
        out.append("Lines SPOKEN in this clip (each exactly once in your flow, in this order):")
        for ln in spoken(shot):
            via = " (heard through the phone, never seen)" if ln.character_id in shot.staged.heard_only else ""
            out.append(f"- {short.get(ln.id, ln.id)}: {ln.speaker.title()}{via}, about {speech_s(ln.text)} s of speech")
        total = sum(speech_s(ln.text) for ln in spoken(shot)) + 0.8 * (len(spoken(shot)) - 1)
        out.append(f"Speech in all: about {total:.1f} s of a {shot.duration_s} s take.")
    else:
        out.append("Nobody speaks in this clip.")
    under = [lid for lid in clip.get("lines") or [] if lid not in {short.get(ln.id) for ln in spoken(shot)}]
    if under:
        out.append(f"Heard in the edit over this clip, NOT spoken in it (context for the faces): {', '.join(under)}")
    pics = ["the opening frame"] + [f"a face sheet and a look sheet for {c.name}" for c in shot.seen]
    out.append(f"Pictures attached for the video model: {'; '.join(pics)}. The frame already fixes the framing.")
    out.append("</clip>")
    return NL.join(out)


def brief(world: dict[str, Any], shot: Any, clip: dict[str, Any]) -> tuple[str, list[str]]:
    names = cards_for(shot, clip)
    cards = NL.join((HERE / "cards" / f"{n}.md").read_text(encoding="utf-8").strip() for n in names)
    return f"{scene_brief(world)}\n\n{clip_brief(world, shot, clip)}\n\n<cards>\n{cards}\n</cards>", names


# ── gates ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def gates(d: Direction, shot: Any, world: dict[str, Any], clip: dict[str, Any]) -> list[str]:
    from contracts import safe_depiction

    short = world["short"]
    want = [short.get(ln.id, ln.id) for ln in spoken(shot)]
    got = [s.line_id for s in d.flow if s.kind == "line"]
    faults = []
    if got != want:
        faults.append(f"lines: this clip speaks {want or 'nothing'} in that order, each once; your flow has "
                      f"{got or 'none'}")
    texts = {"situation": d.situation, "people": d.people, "camera": d.camera, "sound": d.sound}
    for n, s in enumerate(d.flow, 1):
        for k in ("text", "to", "how", "listener"):
            texts[f"flow {n} {k}"] = getattr(s, k)
    every = " ".join(texts.values())
    for k, v in texts.items():
        if SINHALA.search(v):
            faults.append(f"{k}: Sinhala letters; never write a line's words")
        if LINE_ID.search(v):
            faults.append(f"{k}: a line or block id ({LINE_ID.search(v).group(0)}) in the text")
        if QUOTES.search(v):
            faults.append(f"{k}: quotation marks")
        limit = LIMITS.get(k, LIMITS["step"])
        if len(v) > limit:
            faults.append(f"{k}: {len(v)} characters, at most {limit}")
    if not spoken(shot):
        said = sorted({m.group(0).lower() for m in SPEECH.finditer(every)})
        if said:
            faults.append(f"nobody speaks in this clip, but the text has: {', '.join(said)}")
    for c in shot.heard:  # named as heard ("Father (heard only, never in frame)") is fine; placed in frame is not
        named = re.search(rf"\b{re.escape(c.name)}\b[^.;]*", d.people, re.I)
        if named and not re.search(r"heard|never in frame|never seen|phone|voice", named.group(0), re.I):
            faults.append(f"people: {c.name} is only heard and never in frame")
    if (clip.get("technique") == "locked_off" or "locked" in str(clip.get("technique"))) and MOVING.search(d.camera):
        faults.append(f"camera: the planner's camera is locked off; '{MOVING.search(d.camera).group(0)}' moves it")
    for s in d.flow:
        if s.kind == "line" and not s.how.strip():
            faults.append(f"line {s.line_id}: no delivery")
    if any(f.said for f in safe_depiction.blocking(every)):
        faults.append("words the video models decline: " + ", ".join(f.said for f in safe_depiction.blocking(every)))
    return faults


# ── assembly ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def citations(shot: Any) -> str:
    from contracts.video_gen import IMAGE_TAG, OMNI_CITATION_HEAD, OMNI_CITATION_TAIL, OMNI_LINES

    lines = [OMNI_LINES["first_frame"].format(tag=IMAGE_TAG.format(n=1), also="")]
    n, sheets = 1, []
    for c in shot.seen:
        for kind, label in (("face_sheet", f"the face sheet for {c.name}"), ("look_sheet", f"the look sheet for {c.name}")):
            n += 1
            tag = IMAGE_TAG.format(n=n)
            sheets.append(tag)
            lines.append(OMNI_LINES[kind].format(tag=tag, label=label))
    if sheets:
        many = len(sheets) > 1
        tags = f"Images {sheets[0].removeprefix('Image ')} to {sheets[-1].removeprefix('Image ')}" if many else sheets[0]
        lines.append(OMNI_CITATION_TAIL.format(tags=tags, they="they" if many else "it", are="are" if many else "is",
                                               refs="references" if many else "a reference",
                                               them="them" if many else "it"))
    return OMNI_CITATION_HEAD + NL + NL.join(lines)


def assemble(d: Direction, shot: Any, world: dict[str, Any]) -> str:
    from contracts import on_screen_text

    short = world["short"]
    by_id = {short.get(ln.id, ln.id): ln for ln in spoken(shot)}
    flow: list[str] = []
    for s in d.flow:
        if s.kind == "action":
            flow.append(s.text.strip())
            continue
        ln = by_id[s.line_id]
        who = ln.speaker.title()
        words = words_of(ln.text)
        if ln.character_id in shot.staged.heard_only:
            head = f"{who}'s voice through the phone, {s.how.strip().rstrip('.:')}:"
            tail = "No one on screen mouths these words."
        else:
            head = f"{who}, to {s.to.strip()}, {s.how.strip().rstrip('.:')}:"
            tail = ""
        heard = s.listener.strip()
        if heard and heard[-1] not in ".!?":
            heard += "."
        block = [head, f"\"{words}\""] + ([tail] if tail else []) + ([heard] if heard else [])
        flow.append(NL.join(block))
    parts = [d.situation.strip(), d.people.strip(), NL.join(flow)]
    if spoken(shot):
        seen_speaks = any(ln.character_id not in shot.staged.heard_only for ln in spoken(shot))
        parts.append(("They speak casual, everyday spoken Sinhala, the way people really talk in a Sri Lankan "
                      "teledrama: not an interview, not a speech, nobody looks at the camera."
                      if seen_speaks else
                      "The voice speaks casual, everyday spoken Sinhala, like a real phone call in a Sri Lankan "
                      "teledrama.")
                     + " Only these words are spoken, only by the people named; English words in a line are said as "
                       "Sri Lankans say them.")
    else:
        parts.append("Nobody speaks in this clip: no dialogue, no voice.")
    parts.append(f"Camera: {d.camera.strip()}")
    parts.append(f"Sound: {d.sound.strip()}")
    rules = [shot.hands.strip()] if shot.hands.strip() else []
    rules += ["Clean frame: no captions, no subtitles, no watermarks.", on_screen_text.VIDEO]
    parts.append(" ".join(rules))
    parts.append(f"Duration {shot.duration_s} seconds. Ends on a cut.")
    parts.append(citations(shot))
    return (NL + NL).join(p for p in parts if p.strip())


# ── the model ────────────────────────────────────────────────────────────────────────────────────────────────────────


def env(key: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"{key} is not set in .env")


def dollars(u: dict[str, int]) -> float:
    fresh = u["input"] - u["cached"]
    return (fresh * PRICE["in"] + u["cached"] * PRICE["cached"] + u["output"] * PRICE["out"]) / 1e6


def ask(client: Any, messages: list[dict[str, str]]) -> tuple[Direction, dict[str, int], str]:
    resp = client.responses.parse(model=MODEL, reasoning={"effort": EFFORT}, input=messages, text_format=Direction)
    u = resp.usage
    usage = {"input": u.input_tokens, "cached": getattr(u.input_tokens_details, "cached_tokens", 0) or 0,
             "output": u.output_tokens}
    return resp.output_parsed, usage, resp.output_text


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def today_text(world: dict[str, Any], number: int) -> str:
    cov = world["cov"]
    sections, _ = cov.prompt(world["w"], world["rows"], world["lines"], number, False)
    return NL.join(f"[{s.title}] {cov.text_of(s).strip()}" for s in sections)


def main() -> int:
    from hiru_ai.core.tokens import tokens_of

    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="", help="run folder (default: the model's own)")
    ap.add_argument("--model", default="gpt-5-mini", choices=sorted(MODELS))
    ap.add_argument("--effort", default="low", choices=["low", "medium", "high"])
    ap.add_argument("--only", default="", help="slates, e.g. 4A-2,4E-2 (default: every clip)")
    ap.add_argument("--yes", action="store_true", help="send: one PAID model call per clip (plus a repair if needed)")
    args = ap.parse_args()
    global MODEL, PRICE, CAP_USD, EFFORT
    MODEL, PRICE, EFFORT = args.model, MODELS[args.model], args.effort
    CAP_USD = PRICE["cap"]
    default_dir = RUN_DIR[MODEL] if EFFORT == "low" else {"gpt-6.1-terra": "004_gpt-6.1-terra-medium"}.get(
        MODEL, f"{MODEL}-{EFFORT}") if EFFORT == "medium" else f"{MODEL}-{EFFORT}"
    out = HERE / "runs" / (args.run or default_dir)
    for sub in ("briefs", "answers"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    system = (HERE / "system.md").read_text(encoding="utf-8")
    world = load()
    pick = {s.strip() for s in args.only.split(",") if s.strip()}
    shots = sorted(world["scene"].shots, key=lambda s: s.number)
    work = []
    est_in = 0
    for shot in shots:
        slate = str(shot.row.get("slate"))
        if pick and slate not in pick:
            continue
        clip = world["clips"][slate]
        text, cards = brief(world, shot, clip)
        (out / "briefs" / f"{slate}.txt").write_text(f"{system}\n\n=== user ===\n{text}", encoding="utf-8")
        have = (out / "answers" / f"{slate}.json").exists()
        est_in += tokens_of(system) + tokens_of(text)
        work.append((shot, clip, text, cards, have))
        print(f"S{shot.number:02d} {slate:5} {clip['role']:12} {shot.sound_mode:9} lines {len(spoken(shot))} "
              f"cards {','.join(cards):32} ~{tokens_of(system) + tokens_of(text)} tok in"
              f"{'  [answered, skipped]' if have else ''}")
    todo = [w for w in work if not w[4]]
    guess = (est_in * PRICE["in"] + len(todo) * 2500 * PRICE["out"]) / 1e6
    print(f"{len(todo)} call(s) to make on {MODEL} ({EFFORT}); ~{est_in} tokens in before caching; "
          f"ceiling ~${guess:.3f} (cap ${CAP_USD:.2f})")
    spend_file = out / "spend.json"
    spend = json.loads(spend_file.read_text(encoding="utf-8")) if spend_file.exists() else {"calls": [], "usd": 0.0}
    if args.yes:
        from openai import OpenAI

        client = OpenAI(api_key=env("OPENAI__API_KEY"))
        for shot, clip, text, _cards, _ in todo:
            slate = str(clip["slate"])
            if spend["usd"] >= CAP_USD:
                print(f"stopped: ${spend['usd']:.3f} spent, cap ${CAP_USD:.2f}")
                break
            messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
            started = time.monotonic()
            d, usage, raw = ask(client, messages)
            calls = [usage]
            faults = gates(d, shot, world, clip)
            first = faults
            if faults:
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": "Code checked your answer and found:\n- " + "\n- ".join(faults)
                              + "\nAnswer again, complete, with these fixed."}]
                d, usage, raw = ask(client, messages)
                calls.append(usage)
                faults = gates(d, shot, world, clip)
            cost = sum(dollars(u) for u in calls)
            spend["usd"] = round(spend["usd"] + cost, 5)
            spend["calls"].append({"slate": slate, "usage": calls, "usd": round(cost, 5)})
            spend_file.write_text(json.dumps(spend, indent=1), encoding="utf-8")
            (out / "answers" / f"{slate}.json").write_text(json.dumps(
                {"direction": d.model_dump(), "first_faults": first, "faults": faults, "calls": len(calls),
                 "seconds": round(time.monotonic() - started, 1), "usd": round(cost, 5)}, indent=1,
                ensure_ascii=False), encoding="utf-8")
            print(f"  {slate}: {len(calls)} call(s), ${cost:.4f}, {'OK' if not faults else 'FALLBACK: ' + '; '.join(faults)}"
                  f"{' (repaired)' if first and not faults else ''}")
        print(f"spent ${spend['usd']:.4f}")
    report(out, world, work)
    return 0


def report(out: Path, world: dict[str, Any], work: list[Any]) -> None:
    doc = [f"# {SID}: today's video prompt and the new one ({MODEL}, {EFFORT} effort), clip by clip", ""]
    gate_doc = [f"# {SID}: gates", ""]
    for shot, clip, _text, cards, _ in work:
        slate = str(clip["slate"])
        head = f"## S{shot.number:02d} · {slate} · {clip['role']} · {clip['size']} · {shot.duration_s} s · {shot.sound_mode}"
        doc += [head, "", f"**Planner's summary:** {clip.get('summary', '')}", "", f"Cards: {', '.join(cards)}", ""]
        ans_file = out / "answers" / f"{slate}.json"
        if ans_file.exists():
            ans = json.loads(ans_file.read_text(encoding="utf-8"))
            d = Direction.model_validate(ans["direction"])
            if ans["faults"]:
                doc += ["**New: fell back to today's prompt** (" + "; ".join(ans["faults"]) + ")", ""]
            else:
                doc += ["**New**", "", "```text", assemble(d, shot, world), "```", ""]
            gate_doc += [head, f"- first answer: {'; '.join(ans['first_faults']) or 'clean'}",
                         f"- final: {'; '.join(ans['faults']) or 'clean'}", ""]
        doc += ["<details><summary>Today</summary>", "", "```text", today_text(world, shot.number), "```", "",
                "</details>", ""]
    (out / "prompts.md").write_text(NL.join(doc), encoding="utf-8")
    (out / "gates.md").write_text(NL.join(gate_doc), encoding="utf-8")
    print(f"written: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())

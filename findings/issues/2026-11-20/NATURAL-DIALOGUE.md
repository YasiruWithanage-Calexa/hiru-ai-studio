# findings/issues/2026-11-20 — Sinhala dialogue sounds like an interview

The person heard Omni Flash takes with Sinhala dialogue as **people answering in an interview**, not people talking to
each other. The cause is **our video prompt**, not the model: a hand-written prompt with the same model, size and lines
gave a family scene (lab/natural_dialogue, 2026-11-19, two takes). This file records what is wrong, the proof, and the
prompt pattern that worked, so the product fix can be planned from it.

**Where seen.** Love Hour 4 / Api Denna v2 (Kasun, Anudi, her father). Product prompts read from
`lab/action_budget/runs/replan/E01-S01/prompts_fixed.md` and `lab/coverage/runs/today/product/prompts_today.md`, both
written by `hiru_ai/steps/serialize/logic.py`.

## What the model is told today

All Omni gets about the one spoken line in Kasun's close-up (S09), in a prompt of about 25 sentences of camera, lens,
tripod (said twice), hands, physics, anatomy and watermarks:

> Kasun's lips move to L6. His lips stay closed and his chin remains slightly lowered. … He delivers L6 quietly with an
> even gaze and minimal movement of his head. Kasun (the person in dIRECTOR'S PRODUCTION NOTES Character and visual
> continuity Kasun) says, ""දවසක මගේම රෙස්ටුරන්ට් එකක් පටන් ගන්නවා."" — only Kasun's lips move.

…and, at the very end, among the rendering constraints: *"All speech is in Sinhala, spoken naturally by a native
speaker, exactly as written — not translated, not accented English."*

---

## D1 — No delivery on any line · confirmed

The template is `'{speaker} says{delivery}, "{line}"'` (`serialize/schemas/clip_schema_veo_3_1.yaml:55`). `delivery`
is built from the line's own `delivery` plus `shot.feeling.wants` (`serialize/logic.py:145`). Both are empty: every line
of the Love Hour 4 father/Anudi scene has `delivery = ""` in the database (`lab/sinhala_pace/lines.json`), and no
`(…)` appears in any dialogue sentence found. With no emotion given, the model speaks a neutral, clear statement:
interview voice.

## D2 — No listener · confirmed

Nothing says who the line is said **to**. A single person, close-up, eye level, tripod, "even gaze, minimal movement of
his head" is the description of an interview answer. The scene knows who is present (and the planner knows who the
line answers), but the dialogue sentence never says it.

## D3 — No situation or mood at the moment of speaking · confirmed

The Story line says *"Kasun … performs L6 with quiet conviction"*. "Performs" and "conviction" ask for a statement.
Nothing says what just happened, what the speaker wants, or the mood of the room.

## D4 — Internal ids and contradictions reach the model · confirmed

- `L6`, `L3` (our line ids) appear in the beat prose: "his lips move to L6", "performs L3". The model cannot know them.
- "Kasun's lips move to L6. His lips stay closed…" in the same beat as the line.
- "only Kasun's lips move" + the lip-lock rule (`clip_schema_veo_3_1.yaml:48`) + "minimal movement of his head" ask for
  speech from a still face: a talking head.

The ids come from the planner's beat text (`director_line` / `action` / `performance`), copied as written by
`_beats_section` (`serialize/logic.py:235`).

## D5 — Broken speaker tag · confirmed

`Kasun (the person in dIRECTOR'S PRODUCTION NOTES Character and visual continuity Kasun)`. `who_clause`
(`serialize/logic.py:82`) takes the first phrase of the cast member's `wardrobe_anchor`, which here holds a document
heading. Probably a reader/canon data fault, shown by the serializer.

## D6 — Doubled quote marks · confirmed

The database stores each line already wrapped in quotes (`"අද මම ඔයාව…"` in `lines.json`); the template adds its own,
so the model gets `""…""`. (The `«…»` seen in the lab printouts is only how `lab/coverage/run.py:185` prints the Sinhala
segment; it is not sent.)

## D7 — No voice · confirmed

No "Voices" section in either prompt: Kasun has no voice pin (`_voice_text`, `serialize/logic.py:181`). The model picks
a generic clear voice.

## D8 — The language line points toward a reading · likely

"Spoken naturally by a native speaker, exactly as written" reads like a language sample or voice-over, and it sits at
the end among the rendering rules, far from the words. Nothing says *casual, everyday spoken Sinhala, as in a
teledrama*.

## D9 — The line is buried · likely

The spoken line is about 1 sentence in 25. The acting is a small share of what the model reads.

---

## The proof: lab/natural_dialogue run 1 (2026-11-19)

Omni Flash 1.2, text to video, 360p, 9:16, 10 s, about 20k video tokens and 37 s each. Lines verbatim from the database.
Baseline: `lab/sinhala_pace/runs/002_B_1b1c9eab` (same line as A, a plain prompt, same model and size).

| | Prompt | Speech (measured) | Picture |
|---|---|---|---|
| Baseline | one man, quiet room, "as an actor in a Sri Lankan TV drama would" | 0.75–6.75 s, 2 pauses | one man beside the lens: an interview answer |
| A | father presses Anudi; over her shoulder | 1.25–6.85 s, 2 pauses | he talks **to** her, looks away at the end; she fidgets with her phone |
| B | Anudi's line, father answers | 1.4–9.75 s, 3 pauses | two-shot across the table; she looks down while he speaks |

The person's verdict (2026-11-20): the new prompting is good. Frames: `lab/natural_dialogue/runs/compare.png` (rows
baseline / A / B, one frame a second). B's speech reaches 9.75 s of 10: two lines and a hand-over are tight in 10 s.

## The pattern that worked

In this order, short, the people first:

1. **Place and time** in one or two sentences ("Night, inside a modest middle-class home in Colombo…").
2. **Who is there**, each with a short look, and **where they are relative to each other** ("sits across the table
   from her father").
3. **What just happened and what the speaker wants** ("She has just told him Kasun is only her friend. He does not
   believe her.").
4. **For each line:** who says it, **to whom**, **how** (feeling + intention + a physical act), then the Sinhala words
   once, in plain quotes, on their own line.
5. **How the delivery changes inside a long line** ("the first question is doubtful, almost a scoff; the second is
   sharper; the last trails off as he shakes his head").
6. **What the listener does**, silently ("listens with her eyes down, turning her phone in her hands; she does not
   speak").
7. **The register, beside the words:** "They speak casual, everyday spoken Sinhala, the way a real family talks at home
   in a Sri Lankan teledrama: not an interview, not a speech, nobody looks at the camera."
8. **Camera in one sentence**, with the listener in the frame where it helps (over the shoulder, two-shot), handheld
   with a slight sway.
9. **Room sound**, no music.

Left out on purpose: line ids, lens maths, the tripod sentence, physics, anatomy, watermarks, "exactly as written",
"only X's lips move".

### Prompt B, as sent

```text
Night, inside a modest middle-class home in Colombo, Sri Lanka. A dining table under a warm ceiling light, plastic chairs, a calendar on the wall.

Anudi, a Sri Lankan woman in her mid-twenties with long black hair in a low ponytail, sits across the table from her father, a Sri Lankan man in his late fifties with greying hair and a plain white shirt. They are arguing quietly about Kasun, the young man she likes, who sells food from a three-wheeler on the road. A real family argument: they look at each other.

Anudi, softly but stubbornly, almost pleading:
"එයාට හීනයක් තියෙනවා තාත්තේ."
Her father answers straight after her, with a tired sigh and a shake of the head, firm but not shouting, tapping the table on the last words:
"හීනවලින් පවුල් ජීවත් කරන්න බෑ අනුදි. සල්ලි ඕනේ. අනාගතයක් තියෙන්න ඕනේ."
While her father speaks, Anudi looks down and her jaw tightens; she says nothing more.

They speak casual, everyday spoken Sinhala, the way a real family talks at home in a Sri Lankan teledrama: not an interview, not a speech, nobody looks at the camera.

Camera: a vertical two-shot across the table, both faces in three-quarter profile, handheld with a slight natural sway.

Sound: only their voices in the room, a ceiling fan turning, crickets outside. No music.
```

Prompt A: `lab/natural_dialogue/runs/A/prompt.txt`.

---

## Not tested yet

- **With pictures.** The lab was text to video. The product sends a first frame and face/look sheets
  (`reference_to_video`). The pattern has to hold with those attached, and the frame then fixes the camera.
- **Without the safety lines.** The product's physics, hands and object rules fixed real faults (phone on the ground,
  camera drift). Which of them a dialogue shot can drop, or shorten, is open.
- **Lip-lock.** Dropping "only X's lips move" gave no wrong speaker in two takes. Two takes are not enough to drop it.
- **Delivery data.** The lab's delivery, listener and situation were written by hand. In the product they have to come
  from somewhere: the script's parentheticals (empty here), the planner, the scene's feeling step, or a writer agent.
- **Many takes.** Two takes, one scene, one model version.

## Fix candidates (for the plan)

| # | Fix | Where |
|---|---|---|
| F1 | A delivery for every line: feeling, intention, a physical act; and how it changes inside a long line | data: planner / feeling step / writer; `serialize/logic.py:145` |
| F2 | Say who the line is said to, and what the listener does | serializer, from the shot's cast and the line's addressee |
| F3 | One sentence of situation and mood before the lines | serializer / prompt writer |
| F4 | Register line beside the words; drop "native speaker, exactly as written" | `clip_schema_veo_3_1.yaml:30` (`language_line`) |
| F5 | Strip line ids (`L6`) from beat prose; no "lips stay closed" in a speaking beat | planner output check / serializer |
| F6 | Strip the database's own quotes before the template adds quotes | serializer (`_line_segments`) |
| F7 | Speaker tag from the look, never from a document heading | `who_clause` + canon data |
| F8 | A voice pin for every speaker (age, region, energy) | canon |
| F9 | Dialogue shots: the people first, the camera in one sentence, safety lines shortened | serializer section order |

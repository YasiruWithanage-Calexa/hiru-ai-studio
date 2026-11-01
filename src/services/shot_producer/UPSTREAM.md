# shot_producer — fork record

Forked from PromptMotion `src/services/nova_producer/` at commit **1d748dc** (2026-10-19), as
PLAN.md §2.1 describes. `scripts/upstream_diff.py shot_producer` lists what changed upstream
since that commit in the files below.

| Hiru file | Upstream file | What was kept |
|---|---|---|
| `engine/shots.py` | `nova_producer/engine/shots.py` | A scene designed in ONE call; answers matched BY SHOT NUMBER; missing shots asked again; frozen prefix; join lines (continuous / matched re-angle); words bound by code, never requested; ids only in `subjects[].id` with names everywhere else; subjects pruned to the shot's cast |
| `engine/serialize.py` | `nova_producer/engine/serialize.py` | The Veo 3.1 paragraph order; `_who_clause` identity anchors (short, wardrobe first); the dialogue syntax with the lip tag; silence stated positively; the voice-casting block; the render guard; beat camera notes dropped when they are continuity hints |
| `engine/schema.py`, `engine/schemas/clip_schema_veo_3_1.yaml` | `nova_producer/engine/schema.py`, `nova_producer/engine/schemas/clip_schema_veo_3_1.yaml` | Every constant sentence in one YAML, read through `rule()`; the IR structure and its field hints |
| `engine/continuity.py` | `nova_producer/engine/continuity.py` | Identity persists across cuts, scene state resets at a scene change |
| `engine/techniques.py` | `nova_producer/engine/producer.py`, `nova_producer/engine/retrieval.py` | Technique palette retrieved once per job, one query per distinct intent, unioned |
| `app/handler.py` | `nova_producer/app/handler.py` | One job per invocation; client-safe failure text |

## Intentional divergences

1. **Input.** Upstream renders a Nova treatment (producer → screenwriter → cards → shots). Hiru's
   script, shot list and canon already exist: the director approved them in the Director panel.
   Sizes, lengths, joins, beat windows and the lines are fixed input; no treatment, screenwriter,
   critique or doctrine layer is carried.
2. **Strict structured output.** Upstream asks for free JSON against a pasted template. Hiru uses
   OpenAI strict JSON schema; the YAML's field hints become the schema's descriptions
   (`ClipSchema.shot_schema`).
3. **Camera recommendation.** Each shot's answer also carries a recommendation in the
   Production panel's own choices (`contracts.producer.CAMERA_OPTIONS`) and a rationale. The
   director's shot size always wins over the model.
4. **Sections, not one string.** The prompt is a list of titled sections whose Sinhala lines are
   their own segments (`contracts.producer.PromptSection`), so the panel renders Sinhala as
   Sinhala and the copied text stays byte-exact.
5. **A person's camera.** When a person changed the camera (`shots.camera_overrides`), the camera
   section is rebuilt from the camera as it stands and the beats' own camera notes are dropped,
   so the prompt never contradicts the choice.
6. **Lines on their kernel beat.** Lines are placed on the beat `contracts.shotplan` bound them to,
   not spread proportionally; the IR's beats are mapped onto the kernel's beat windows and the
   director's beat notes override the model's.
7. **Voices from canon.** Voice casting comes from each speaker's canon voice pin; Hiru's
   voiceover names its speaker (a character's voice), it is not an anonymous narrator.
8. **Removed:** storyboard shots and boards, `last_frame`, subject pin, client reference photos,
   character-card prompts (reference sheets come from `contracts.canon.reference_sheet_prompt`),
   Kling, the craft doctrine layer (the lead persona's charter stands in for it), litellm,
   credits and billing.
9. **Sinhala guard.** Sinhala the model echoes into any prose field is removed before storage.
10. **Rules mode.** Without a key the design is made by rules (`design_by_rules`): the director's
    size, a lens and stop that suit it, eye level, locked-off, light from the scene heading.
11. **Pins and versions.** Every design and prompt records what it was made against
    (`contracts.producer.Pins`); designs are redone only when missing, out of date or forced, and
    every prompt is a new version.
12. **Staging, intent, review (plan/2026-11-01).** Brought back in a Hiru shape what item 1
    dropped. Before the design, an INTENT agent (`engine/intent.py`, after upstream's producer:
    `purpose`, `visual_intent`, `emotional_beat`, `ScenePlan`) writes per shot what it is for, what
    the camera sees and who is only HEARD, and the scene's coverage plan; it reads the approved
    script and never adds an event. The DoP gets the intent, the plan, the scene's title, note,
    episode synopsis and neighbouring scenes, and answers `on_screen`. One REVIEW
    (`engine/critique.py`, after upstream's `_critique` → revise → keep only if the gate still
    passes) with at most one revision, kept per shot when the free staging checks find no more
    problems. CRAFT PROBLEMS are named first and lead the technique queries (after upstream's
    `doctrine.articulate`; no authored-doctrine layer). Who is seen is `contracts.staging`, shared
    with frame_render and the API. An off-screen voice is named, placed at its source and never
    given a wardrobe tag (`offscreen_line`, `heard_source` in the clip schema).
13. **Pictures on a clock (plan/2026-11-01b).** The intent and the DoP prompts carry each shot's
    TIMELINE from the timing kernel (`contracts.shotplan.timeline_text`: what each block takes to
    show and when each line is spoken); an information block is named "THE VIEWER LEARNS" and a
    thought "STORY NOTE (not filmed)". The intent may advise where a shot should be cut
    (`split_after`, `split_reason`); two free checks read the intent against the timeline
    (`skips_beat`, `size_vs_intent`, in `contracts.staging`). `fit_beats` matches the DoP's beats to
    the kernel's windows by TIME, not by position, and a heard line's beat in the video prompt says
    what the picture does first ("Anudi answers the phone; then the voice: ..."). The rules intent
    leaves out what is not filmed and frames a heard voice on the person the last actions are about.

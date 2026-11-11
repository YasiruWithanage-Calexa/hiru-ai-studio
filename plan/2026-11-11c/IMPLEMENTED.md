# The prompt writer: a reusable agent for first-frame and video prompts (plan/2026-11-11c)

Built 2026-11-11, both repos, uncommitted, straight into the product at the person's choice (no separate plan or lab).
**No model has been called: $0.** It is OFF until a person sets `PROMPT_WRITER__ENABLED=true`.

The person asked for one agent that writes a shot's first-frame prompt and its video prompt from what the shot planner
(Raphael) saved, used by the regenerate buttons and pluggable into any AI system. Their choices (2026-11-11):
**code gathers the facts, a model polishes the wording, code checks nothing was lost**; build it into the product.

## How it works

1. Code writes the complete prompt, as before: the first frame from `contracts.frame_brief` (plan/2026-11-11b), the
   video prompt from the `serialize` step's sections.
2. The `prompt_polish` step picks the sections a model may reword and, for each, the words it must keep
   (`contracts.prompt_polish.anchors`: the people and places named, numbers with units such as 4300K, left and right,
   time and weather words).
   - First frame: Shot, Composition, People, Place, Light, Colour, Mood.
   - Video: Setting, Subjects, Story, Camera, Lighting.
   - Never sent: the reference pictures and their numbering, spoken lines (Sinhala kept apart), who is only heard,
     the fixed rules, the format.
3. The `prompt_writer` agent (tier `medium`: gpt-5-mini, low effort) rewrites those sections as film language.
4. The step checks each answer (`contracts.prompt_polish.problem`). A section that lost a keep word, grew past
   1.6× + 200 characters, added quoted words, or added a word the video models decline keeps the code's words, and the
   reason becomes an advisory check. No key or a failed call: the agent's fallback is the code's own words.
5. Where it lands:
   - **Video:** shot_producer mode `prompt` (the existing Regenerate button) rewords the new prompt version before it is
     stored; its checks gain "Wording polished by the prompt writer · N sections" and any "… kept as written: the
     rewrite dropped “4300K”".
   - **First frame:** new shot_producer mode `frame_prompt` stores the polish on the shot (`design.frame_polish`:
     section → {stamp of the code text it was written from, text}). `frame_brief` uses a section's polish only while
     that section's code text is unchanged, so the shot screen, the renderer and the vision check all see the same
     prompt, and a changed shot falls back to the code's words until the writer runs again. A re-design replaces
     `design`, so it drops the polish.

## Reusing it in another system

```python
from hiru_ai.core import agents, parts
step = parts.module("step", "prompt_polish", "step")
req = step.run({"op": "request", "kind": "first_frame" | "video", "sections": [{key, title, text}], "names": [...]})
answer = agents.build("prompt_writer").run(req["request"], ctx)            # only if req["request"]["sections"]
merged = step.run({"op": "merge", "request": req["request"], "answer": answer.model_dump(mode="json")})
# merged["texts"]: sections to replace · merged["checks"]: what to show · merged["record"]: what a first frame stores
```

`hiru_ai/systems/shot_producer/polish.py` (`polish`, `polish_video`, `polish_frame`) is that recipe; a first frame's
sections come from the frame_compose step's new `brief` op (`polished: false` = the code's words).

## Files

Backend: `contracts/prompt_polish.py` (new); `contracts/frame_brief.py` (`polished=` and the stored polish);
`hiru_ai/agents/prompt_writer/` and `hiru_ai/steps/prompt_polish/` (new, scaffolded with `hiru-ai new`);
`steps/frame_compose` (`brief` op, `World.preview_labels`, `World.names`); `systems/shot_producer/polish.py` (new),
`graph.py` (mode `frame_prompt`, the video polish), `component.yaml`; `core/settings.py` (`PromptWriterSettings`);
API `POST /v1/productions/{id}/shots/{shot_id}/frame-prompt` (GENERATE; 409 before a design or on an approved scene)
and `frame_polished` on the shot view; `docs/AI_CATALOG.md` regenerated.

Interface: `FirstFramePrompt` gains "Rewrite with prompt writer" (`requestFramePrompt` → `waitForJob` → one read of the
production view) and a "Prompt writer" chip when the prompt is polished; `framePolished` mapped.

Tests: `tests/hiru_ai/test_prompt_writer_system.py` (3: frame mode with one rewrite rejected, video mode leaves action
and dialogue, off = no call), the agent's and the step's own tests, a frame_brief test for stale and current polish, an
API test for the endpoint, two interface tests.

## Open (the person's)

- **The live check.** Set `PROMPT_WRITER__ENABLED=true` and press "Rewrite with prompt writer" on a few Ekama shots,
  then Regenerate a video prompt. Each section is one small gpt-5-mini call per prompt (an estimate, not measured: a
  few cents at most). Read the reworded sections against the code's; if the writer adds little, leave it off.
- Whether the scene-level "prompts" button should also rewrite first frames (today: one shot at a time, from the dialog).
- The model tier (`medium`) is a guess; the live check decides.

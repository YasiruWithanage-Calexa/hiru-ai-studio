# Staging and second looks: plan

Date: 2026-11-01. Comparison with PromptMotion Nova, with diagrams: the "Hiru Studio vs Nova"
artifact (claude.ai/artifact/6aPdkE7vtaHWJjkajFUe1j). Builds on plan/2026-10-31 (off-screen lines
at the shot-list level).

## 1. The problem

Scene 2, shot S05 of the Kasun / Anudi drama (`0369e443…`): "Anudi smiles back, her phone rings,
it is her father", with the father's line `on the phone`. Three frame versions all painted the
father at the three-wheeler. The DoP model had it right ("only present as a voice through Anudi's
phone; no visual of him"), but:

- `frame_render` built its references and People line from `cast_in` (everyone who speaks), so
  the father's character sheet was attached with "match them exactly: the same faces".
- The video prompt described the off-screen father by his clothes and never said "phone".
- Hiru carried Nova's render half only (shot_producer UPSTREAM.md item 1): no shot intent, no
  coverage plan, no critique, no craft doctrine. The DoP read raw script blocks and a vague title.
- Nothing checked the design or the picture. Scene 2 was six MCUs and nothing said so.

## 2. Fixes

| # | Fix | Where |
|---|---|---|
| A1 | One reading of who is SEEN vs only HEARD, shared by every hop | `contracts/staging.py` |
| A2 | Off-screen voices named, placed at their source, never dressed | `serialize.py`, clip schema |
| A3 | Free staging checks on the camera card | `staging_checks`, API `camera_checks` |
| B4 | Scene title, note, episode synopsis, neighbouring scenes to the DoP | `model.py`, `shots.scene_tail` |
| B5 | Intent agent: purpose, what we see, emotional beat, on screen / heard, per shot | `engine/intent.py`, `shots.intent` |
| B6 | Coverage plan per scene (axis, motif, progression) + coverage checks | `scenes.coverage`, `coverage_checks` |
| C7 | One design review, at most one revision, kept per shot only if no worse | `engine/critique.py` |
| C8 | Vision check of each painted frame + missing-sheet check | `frame_render/engine/inspect.py`, `first_frames.checks` |
| C9 | Craft problems named first, used as technique queries | `techniques.articulate` |
| D10 | Planner: vary sizes, one event per 4 s shot, a WIDE for movement | `script_split/planner.py` |
| D11 | Split critic on the high tier, with sizes / busy / no-wide lines | `script_split/critic.py`, `pipeline.py` |
| D12 | Hard-scenes eval, rules floor checked offline in CI | `scripts/eval_staging.py`, `tests/eval/staging_*` |

## 3. Rules kept

- Lines are never reworded; the intent agent never adds an event, a size or a line.
- A person's intent, coverage plan, camera and cast edits are never replaced by an agent.
- Absent-safe everywhere: no key or a failed call falls back to rules; a failed look never fails a frame.
- Static prompt text first and byte-identical; scene data last.
- Nothing is redone automatically: a changed intent marks the design out of date ("What the shot is for changed.").

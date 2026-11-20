# plan/2026-11-20b: what is built

Built offline on 2026-11-20, both repos, **uncommitted**. No paid call was made.

| Phase | State | Where |
|---|---|---|
| 0 Read-only | DONE (from saved data, not the live database; see below) | |
| 1 Agent `video_prompter` | BUILT | `agents/video_prompter/` (lab system prompt with the safe-depiction line word for word and a no-notes rule; the lab's five cards unchanged; schema per §3; `shared_message` + `user_message`; no fallback; 5 eval cases from the lab's sol answers). Tier `video_prompter` (`OPENAI__MODEL_VIDEO_PROMPTER=gpt-6.1-sol`, `OPENAI__EFFORT_VIDEO_PROMPTER=low`, 120 s, 1 retry) |
| 2 Step `video_prompt` | BUILT | `steps/video_prompt/` `logic.py` (scene and clip brief, cards, gates, assembly, checks), `facts.py` (packet rules D5, line pairing D6, clip facts from the producer's rows), `step.py` (`brief` / `check` / `assemble`). Fixtures: `lab/video_prompt/fixtures.py` → `tests/fixtures/e01_s04.json` (18 clips through the product code + sol run 003). All 18 sol answers pass the gates; one good/bad pair per gate; ambient, phone, carried-over and matched re-angle cases |
| 3 Wiring | BUILT | `systems/shot_producer/graph.py` mode "prompt": per scene the packet (D5) and line ids (D6), the scene part once, each shot in number order: agent → gates → ONE repair → no version + WARNING if it still fails (D3); no model → no prompt (D4); `result.warnings` (first 10). `sz.write_prompt` is no longer called. Tests: `tests/hiru_ai/test_video_prompt_system.py` |
| 4 Removals + docs | BUILT | `polish_video` gone; `prompt_polish` and the prompt writer first frame only; manifests, `AI_CATALOG.md` regenerated, `.env.example`, settings docstring; cost estimate `prompt` $0.02 → $0.01 (D15); legacy engine docstring (D14) |
| 5 Interface | BUILT | prompt sections render each line through `spoken()` (the hard-coded `lang="si"` is gone); the pane shows the job's warning when a "Generate prompt" wrote nothing (`writeVideoPrompt` / `promptOutcome`); empty-state wording |
| 6 Live | prompts RUN 2026-11-20 ($0.14, the person's yes, $2 cap); renders not run | `lab/video_prompt/live_product.py` → `runs/005_product`: the product's agent and step on E01-S04's 18 clips: **18 of 18 written, every one clean first time**, $0.1415 (lab sol: $0.168, 3 repaired). One assembly defect found and fixed: a delivery that began "Through the phone" was said twice in the head (test added). **Both plans together** (`live_product.py --parts`, `parts_world.py` → `runs/006_product_parts`, $0.16): the 18 clips of plan/2026-11-20's live Raphael run (line_parts run 003) briefed as parts: L1.1+L1.2 on 4A-1, L7.1+L7.2 on 4B-1, L11.1+L11.2 on 4H-1, L11.3 on 4C-2 and 4J-1; **18 of 18 written**, 16 clean first time, 2 repaired once (4K-1 placed Anudi in frame, 4L-1 wrote "The brief"); each part speaks only its own words, after a "natural sentence pause" on the second part, and the parts join word for word to the script's line (B02, B08, B12). **Rendered** (`render_parts.py` → `runs/007_render_parts`, 4 × 360p Omni 1.2, text to video, no first frame, ≤ $3.00 at the 720p rate, the person's yes): 4A-1, 4B-1, 4H-1, 4C-2; speech starts 1.2–2.0 s in and ends by 6.1 s, no take cut off; on the phone clips Anudi's lips stay closed. **Defect found and fixed:** "a steady frame on a tripod" (the system prompt's own wording, from the lab) drew a camera on a tripod into 4A-1 and 4H-1. The system prompt now says "a steady, unmoving frame" and forbids gear words; the assembly rewrites any tripod in the camera section (`logic.camera_words`, tests); eval cases reworded. `father_call_cut.mp4` = 4H-1 + 4C-2 for the person to hear the voice across the cut |

## Phase 0

- D6 confirmed on saved data: `lab/coverage` builds scene script block i from breakdown block i (`fill.scene_blocks`). The product pairs lines by `ord` (the n-th spoken block is the line of `ord` n, as Raphael's `from_packet` does) and refuses a packet whose counts differ. Not read from the live database (reading it was not asked for).
- `ctx.ports.breakdown` is built for every function by `adapters/supabase_rest.build_ports`, the shot producer included.
- **Why only ~1.5k tokens cached:** every clip cached exactly 1,504 tokens while a repair cached its whole first prompt. I took it for a cache that stops at a message boundary and added `shared_message(inp)` (`core/agents.py`, `ModelCall.shared`: the scene as its own message before the clip). **The live run disproves it:** cached rose only to 1,725 of ~3,800 per clip, so the ~1.5k-token scene still does not cache. Still open; next things to try are `prompt_cache_key` and where the structured-output schema sits. The hook is harmless and kept.

## Deviations

- `Input.cards` is a list of card names; the agent reads the texts from its own `prompts/cards` (the agent owns its words). `Input.previous` carries the first answer on the repair call.
- The opening frame, join and carried-over sentences sit in the first section ("First frame"); the hands, clean frame and on-screen-text rule in "Rules".
- Job events keep `agent=prompt_writer` (no label map exists anywhere to rename).
- Parity: `shot_producer/prompts` is skipped on the graph engine (it differs from the legacy engine by design, D13/D14); its behaviour is held by the new system tests.
- A scene planned in line parts (plan/2026-11-20): a part is briefed as `L12.2`, "part 2 of 3 of one line".

## Open for the person

1. Phase 6 (paid): one scene's prompts with the agent (~$0.17 for 18 clips), then two 360p renders (≤ $1.20). Watch the cache hit on the second clip, and for a caption like "Colombo" (`on_screen_text.VIDEO`).
2. Older productions need a current breakdown packet, or no prompt is written (the warning says so).

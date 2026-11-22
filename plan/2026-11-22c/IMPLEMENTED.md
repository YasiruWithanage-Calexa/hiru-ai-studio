# plan/2026-11-22c — what was built (2026-11-22, offline, uncommitted)

Phases 1-6 built in both repos. Phase 7 (live) is the person's: it spends a model call and a render.

## Backend (`hiru-ai-studio`)

| Where | What |
| --- | --- |
| `contracts/producer.py` | `PersonEdits.video_note`; `VIDEO_NOTE_PIN`, `VIDEO_NOTE_CHANGED`; `stale_reasons` names the note on its own and keeps it out of "The camera move changed" |
| `contracts/picture_pins.py` | `motion(..., video_note)` and `pinned(..., video_note)` pin the note's hash |
| `steps/frame_compose/logic.py` | `pins_now` pins the shot's note |
| `api/services/production.py` | `motion_now` carries the note, so shot prompt and video prompt reasons see it |
| `api/routers/production.py` | `ShotProductionView.video_note` |
| `systems/shot_prompts/graph.py` | the video prompt row pins the note; a video-only rewrite is refused with `FRAME_NOT_FROM_PROMPT` unless the accepted frame was drawn from the stored words (D6) |
| `core/shot_prompts.py` | `facts["video_note"]`, `Input.video_note`, `drawn_from(record, frame)` |
| `agents/shot_prompter/{schema,agent}.py` | `video_note` input; a `<video_note>` block plus one instruction line, only when set (the system prompt is unchanged, so the cache holds) |
| `contracts/coverage/scene.py`, `ledger.py` | `Clip.video_note` read from and written to `person_edits`; `picture_content()`; "S01 · video note: … → …" |
| `steps/coverage_kernel/logic.py`, `core/row_trial.py` | the `video_note` op (600 characters, "" clears it) |
| `core/coverage_rows.py` | a note-only change is saved with the same version (save and undo/redo) |
| `contracts/zora/wire.py`, `systems/zora/zora_chat/turn.py` | the op in both schemas, the `performance` kind, the fence, the invented-words check |
| prompts | Sable `system.md` + `sable_shot_change` guide; Zora conductor + author `system.md` |

Tests: `tests/contracts/test_video_note.py` (pins, reasons, `needs`, `drawn_from`, the agent message),
`tests/sable/test_video_note.py` (staged, accepted, version kept; with a size change it still moves),
`tests/zora/test_video_note.py` (saved, version and board pin kept, undo, the fence).

## Interface (`hiru-ai-studio-interface`)

`map-scene.ts` / `types.ts`: `video_note` → `production.videoNote`. `video-dock.tsx`: a "Video note · … (the first
frame is kept)" line above the video prompt. The existing "Prompts out of date" chip and "Rewrite prompts" button do
the rest. Test in `video-dock.test.tsx`.

## Behaviour change to know

D6 applies to every video-only rewrite, not only those a note causes: a camera-move-only change on a shot whose frame
was drawn by the legacy engine (or uploaded) now says "draw the first frame again from the prompts, then rewrite"
instead of writing a video from words that may not match the picture.

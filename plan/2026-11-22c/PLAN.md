# plan/2026-11-22c — Video notes: change how a shot plays, keep its first frame

## Why

Some chat requests change only how a shot PLAYS in its video, not what it shows: "make her voice softer", "more
romantic and calm", "slow motion". Today the chats can only edit shot fields. Any saved edit bumps the shot's version,
which marks the drawn first frame out of date, so the person redraws a frame that did not need to change.

The Shot prompt agent already has a video-only mode (`core/shot_prompts.needs` → `"video_only"`): it gets the stored
opening and frame words as `<fixed>` and rewrites only the video. What was missing was a place for the request, a
way for Zora and Sable to set it, and a save that keeps the frame current.

## Decisions (agreed in chat, 2026-11-22)

- D1. **One video note per shot**, `shots.person_edits.video_note` (plain English, max 600 characters, "" clears it).
  No schema migration: `person_edits` is JSON.
- D2. **The frame never sees it.** The note is pinned as a hash inside the prompts' `motion` pin
  (`contracts.picture_pins.motion`). Frames are compared on `picture` only, so a note never marks a frame out of date.
  Prompts are compared on `motion` too, so a changed note marks the shot prompt and the video prompt out of date with
  its own reason ("The video note changed: rewrite the prompts (the first frame is kept).").
- D3. **No version bump for a note alone.** `core.coverage_rows.rows_for` and `restore` (undo/redo) save a note-only
  change with the same `version`. A note that comes with a picture change still bumps it. The scene board's `plan_pin`
  does not read `person_edits`, so no Update board is offered either.
- D4. **Both chats, one op.** The row kernel gains `video_note {shot, value}`. Sable stages it as a card (no new tool:
  Sable stays at its 25-tool cap); Zora's conductor writes it from the person's own words, or tasks the author with the
  new `performance` kind. The prompts say when to use it: how a shot plays, never what it shows.
- D5. **Nothing spends on Accept.** As everywhere else, the prompts show as out of date and the person presses
  "Rewrite prompts": one video-only call per shot, with the note in `<video_note>`.
- D6. **Option 1, the text check.** A video-only rewrite is made only when the accepted frame was drawn from the
  stored shot prompt (its picture pin holds the hash of the stored opening, `core.shot_prompts.drawn_from`). Otherwise
  the job says so ("draw the first frame again from the prompts, then rewrite") instead of writing a video from words
  that may not match the picture. This covers frames drawn by the legacy engine, from code's words, or uploaded.
  Sending the frame image to the agent (option 2) is not built.

## Phases

1. Contracts: `PersonEdits.video_note`; the `video_note` key in the motion pin; its own stale reason.
2. Pins: the frame world (`frame_compose.pins_now`), the API view and the video prompt row pin the note.
3. Shot prompt agent: `facts["video_note"]` → `Input.video_note` → a `<video_note>` block; the D6 check before a
   video-only rewrite.
4. Row kernel and save: `Clip.video_note`, the op, the change ledger line, the no-bump save and undo.
5. Chats: Sable's prompt and tool guides; Zora's wire (op, `performance` kind), fence, invented-words check, prompts.
6. API + interface: `ShotProductionView.video_note`; the shot workspace's video dock shows "Video note · … (the first
   frame is kept)".
7. Live check (the person's, it spends): ask Sable or Zora for a softer voice on a shot with a drawn frame, accept,
   press Rewrite prompts, render a take.

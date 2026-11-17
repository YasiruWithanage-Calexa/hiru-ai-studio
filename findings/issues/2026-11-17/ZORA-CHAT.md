# findings/issues/2026-11-17 — Zora chat

Problems in the **Zora chat itself**, found while the person corrected the phone call in one scene. Problems that were
already in the plan (upload, reader, ledger, planner) are in [UPLOAD-AND-BREAKDOWN.md](UPLOAD-AND-BREAKDOWN.md).

**Where seen.** Production built from `Api_Denna_Script_v2.pdf`, the scene where Kasun returns Anudi's phone in the
rain and her father calls (shots S05–S09). The chat ran 2026-11-16 → 2026-11-17.

## The turns

| # | The person asked | Zora did | Result |
|---|---|---|---|
| 1 | S06: show the front of the phone; caller ID "Dad" | Turned the phone to face camera; dropped "Dad" ("Veo can't render a readable caller ID") | Half done |
| 2 | Recreate the scene board image | "I can't make the image here"; offered written panel descriptions | Wrong route |
| 3 | Repaint S06 | Rewrote S06's text; take 4 s → 6 s without being asked | Misread + extra change |
| 4 | S07 should be more natural | Handheld drift, small pause, beats rewritten | OK |
| 5 | S07 and S08 use different hands | Invented a hand-to-hand transfer; put the phone in the **left** hand in S08 | Worse |
| 6 | S08/S09: phone right hand, umbrella left | Done in text; S08 CU → MCU without being asked | Text OK, picture unchanged |
| 7 | Did you update the scene board? | "Yep — I didn't change anything", then a coverage narrative | Wrong question answered |
| 8 | Anudi still holds the phone in her left hand | Edited S05–S07 instead; said it "couldn't change S08 or S09" | False limit |

---

## C1 — Zora uses field names that do not exist · confirmed

Every "Couldn't apply" line in the chat:
`set S06: 'what'`, `set S07/S08: 'who'`, `set S08/S09: 'role'`, `set S08/S09: 'first_block'`, `set S07/S08/S09: 'on screen'`.

**Why.** `set` accepts only `size, link, why, sees`, the camera fields, the text fields and `beats/subjects/first_frame`
(`steps/coverage_kernel/logic.py:59` `SET_FIELDS`). `insert` takes `who, what, role, first_block`. The prompt gives all
operations one flat shape with "unused fields null" (`agents/zora/zora_author/prompts/system.md`, "Operations"), so the
model puts insert's fields, and the UI's labels ("on screen"), into `set`.

## C2 — Re-sending a value that is already there · confirmed

`set S06: S06's size is already INSERT`, twice. The prompt already says "re-sending a value that is already there is
noise". It costs nothing, but it fills the "Couldn't apply" list.

## C3 — "Dad" dropped without another route · confirmed · rule changed by plan/2026-11-17b

In turns 1 and 3 Zora said Veo cannot draw a readable caller ID and moved the caller to the line L11. That was the old
rule. plan/2026-11-17b (2026-11-17, uncommitted) changed Zora's prompt: text inside the picture is welcome, write the
exact words and say where they are.

**Left.** S06 was edited under the old rule. It needs one more turn (or an edit) to put the caller name on the screen.

## C4 — No route to the board · confirmed

- Turn 2: "I can't make the image here", though the app has Update board.
- Turn 3: "repaint" taken as a text rewrite.

Zora has no tool to start a board update and is not told the button exists. A board is never repainted by itself when a
shot changes (`src/api/routers/boards.py:13`, by design), so every chat edit left the board out of date without saying so.

## C5 — Zora cannot see the board's state · confirmed

Turn 7 ("did you update the scene board?") got "Yep — I didn't change anything" and a narrative of the coverage. Zora is
given no board state (which panels are out of date, which shots changed since painting) and no image, so it guessed.

The word "board" makes it worse: inside the chat engine "board" is the `director_board` panel of specialists
(`systems/director_chat/models.py:30`), not the scene-board image. The reply reads as if it answered about the plan.

## C6 — Zora made the hands worse · confirmed

Turn 5 ("S07 and S08 use different hands") is a continuity complaint: make them match. Zora made the difference part of
the action: S07 lowers the phone, S08 has it "settled in her left hand at her left ear". That is an invented action (the
prompt's "never invent STORY" covers events, not this kind of staging) and it moved the shot text away from the right
hand the original plan had.

**Why.** Nothing tells Zora that a held prop keeps its hand across neighbouring shots unless the story moves it.

## C7 — Zora's edits do not reach the hands in the pictures · confirmed (code path)

Even a correct edit ("phone in her right hand") only changes the shot's text. A frame's hands sentence comes from the
scene state ledger (`contracts/holding.py:276` → `steps/frame_compose/logic.py:188`), and the coverage kernel does not
write the ledger. If the ledger says left (UPLOAD-AND-BREAKDOWN U4), the frame prompt says left, and the shot text says
right next to it.

## C8 — False limits in the reply · confirmed

The reply writer turned refused operations into limits that do not exist:

- "I couldn't edit the non-editable 'who' fields you mentioned". The person never mentioned them; Zora sent them.
- "I couldn't change S08 or S09 here (those on-screen fields aren't editable)". Both shots were changed one turn earlier;
  only the made-up field `on screen` was refused.

The prompt says "never claim a change your operations do not make"; nothing stops a reply from claiming a limit that
does not exist.

## C9 — Changes nobody asked for · confirmed

- Turn 3: S06 take 4 s → 6 s.
- Turn 6: S08 size CU → MCU.
- Turn 8: S05–S07 edited when the complaint was about S08/S09's pictures.

The prompt says "change what the task needs and nothing else".

## C10 — The whole memory list on every reply · confirmed

All 18 production memory entries appear under every reply, the same each time, none of them about this scene or this
request. Showing them is a chat problem; what they hold is UPLOAD-AND-BREAKDOWN U6.

## C11 — A "nudge it more?" question on every reply · confirmed

Each reply ends with an offer ("push the hold half a second", "a little sway", "flag S08 and S09"). None of them came from
the person's request or needed their choice. The prompt says `asks` is for "a question only when the task cannot be done
without the director's choice".

---

## Shared with the upload and breakdown

- **Hand continuity:** C6 and C7 here, U4 and U5 there.
- **Caller ID:** C3 here, U1–U3 there.

# findings/issues/2026-11-17 — Upload and breakdown

Problems found while correcting a scene in the Zora chat that were **already in the plan before Zora touched it**. They
come from the document upload, the reader, the stager's ledger or the shot planner. The chat's own problems are in
[ZORA-CHAT.md](ZORA-CHAT.md).

**Where seen.** Production built from `Api_Denna_Script_v2.pdf`, the scene where Kasun returns Anudi's phone in the
rain and her father calls (shots S05–S09, lines L11 "Hello, Father" and L12 the father off screen). The chat ran
2026-11-16 → 2026-11-17.

**Status words.** *Confirmed*: shown by the chat's before/after text or by the code. *Unconfirmed*: likely, needs this
scene's rows read (read-only, no model call).

---

## U1 — The planner hid the phone screen in S06 · confirmed · addressed by plan/2026-11-17b

S06's original text: "Anudi turns the ringing phone toward herself; its screen remains out of view", angle "Close on the
phone and Anudi's hand, with the screen angled away". The script shows the caller ID; the planner turned the phone away.

**Why.** Every planner carried the Veo-lab rule "Show a phone's light on a face, never its words" (for example
`jonathan_author/prompts/system.md`). plan/2026-11-17b (built 2026-11-17, uncommitted) removes that rule everywhere and
puts the positive rule in `src/libs/contracts/on_screen_text.py`.

**Left.** This scene was planned under the old rule, so its shots keep the hidden screen until it is planned again or
edited. Nothing re-plans old scenes by itself.

## U2 — S06 and S07 contradict each other · confirmed

S06 hides the screen (U1), and S07's original `why` reads "The caller label must be legible before the handset reaches her
ear", with "Anudi holds the smartphone still with the screen visible". One plan asks for the label and hides it in the
shot before. Under the old rule S07 also broke the planner's own Veo limit.

**Why.** No check compares what neighbouring shots say about the same object (here: is the screen facing camera or not).

## U3 — The caller's name is not carried to the shots · unconfirmed

The person asked for the caller ID "Dad". The script names the father on the caller ID (the reader's own prompt uses
this script as its example: a caller ID "Thaththe" for the father, `story_reader/prompts/system.md:9`). No shot text in
the chat shows that name.

**To check.** Whether the reader stored the alias on the father's person row, and whether the planner saw it. With
plan/2026-11-17b the planner should write the exact words; which spelling to show ("Thaththe", "Thaththa", "Dad") is a
decision for the person.

## U4 — The left hand in the pictures came from the painting side, not the shot text · cause unconfirmed

The original shot text used the **right** hand: S05 "handset low in her right hand", S08 "Anudi holds her smartphone at
her right ear". S07's original text names no hand. Still, the person saw Anudi holding the phone in her left hand on the
board and frames.

**Two possible causes.**
1. *The stager's ledger.* A frame prompt's hands sentence ("Anudi holds the phone in her left hand") is built from the
   scene state ledger, not from the shot text: `contracts/holding.py:276` `shot_hands()` (`_side_at(ledger, …)`) →
   `steps/frame_compose/logic.py:188`. If the ledger records the phone on the left, every frame says left, whatever
   the shot text says.
2. *The image model* ignored the side the prompt gave.

**To check.** The ledger rows for Anudi's phone and umbrella over S05–S09's blocks, and the saved frame prompts for
those shots.

## U5 — The umbrella's hand is never named · unconfirmed

No original shot says which hand holds the umbrella. With the phone in one hand and the umbrella in the other, the side
has to be fixed once and kept. If the ledger has no side for the umbrella, each painting guesses.

**To check.** The umbrella's row in the ledger (holder, side, from which block).

## U6 — Production memory holds story events, not direction · confirmed

The memory reader kept these as "direction" from `Api_Denna_Script_v2.pdf`:

- story events from other scenes: the bank/investor montage, the romantic montage, "Kasun brings himself into Anudi's life…";
- a lone "Silence.";
- the final on-screen caption;
- a camera move from another scene: "The camera slowly pulls back, revealing the restaurant and its customers.";
- a set description from another scene: "The interior has warm lighting, wooden tables…".

Real direction (world, tone, visual style, "same face, hair and body throughout") is mixed in with them. Every Zora turn
was given all of them (see ZORA-CHAT C8 for how they are shown).

**Why.** The memory reader (`core/memory.py`, agent `memory_reader`) takes plot lines and stage directions as standing
rules; nothing keeps an entry to its scene.

## U7 — Text from the PDF ran together · confirmed

One memory entry reads "Scene Structure: Fewer, longer scenes with multiple camera shots and continuous dramatic
action.EPISODE 01 — THE FIRST MEETING". A line break was lost in extraction and a heading merged into a style note.

**Where to look.** The PDF text path (`steps/extract_text/pdf_text.py`) or the memory reader's split of entries.

---

## Shared with the chat

- **Hand continuity** starts at U4/U5, and the chat cannot fix it: Zora edits shot text, not the ledger (ZORA-CHAT C6, C7).
- **Caller ID** starts at U1–U3; Zora followed the same old rule and offered no alternative (ZORA-CHAT C3).

## Next

Read this scene's rows read-only: S05–S09 shots, the person rows (father's aliases), the ledger's phone and umbrella
entries, and the saved frame prompts. That settles U3, U4 and U5.

# Chats: what assistant-ui already gives us, in plain words (plan/2026-11-07)

Our three chats (Zora, the Director chat, the Build chat) now run on assistant-ui. The library we already installed has
many ready-made pieces. This plan picks the ones that help directors, in an order that costs no model money until the
last steps.

1. **Look at it first.** Nobody has seen the new chats in a browser yet. Fix what looks wrong before adding anything.
2. **Small things that need no backend:** a Copy button on replies. Select a line and press "Quote" to ask about it.
   A "working… 12s" line. Times on messages. Your unsent text comes back if you leave the page. Arrow up brings back
   what you last sent. `/undo`, `/redo`, `/plan-shots` commands. A few starter questions in an empty chat.
3. **A Stop button.** Stop means "stop waiting". If Zora already changed the plan, the change stays, and Undo takes
   it back. We first check that stopping can never leave half a change saved.
4. **"What this answer used":** small chips under a reply showing which production notes (from your documents) the
   agent read. You can remove a wrong note right there.
5. **Edit your last message and "Ask again".** Ask again works only on answers that changed nothing, so a re-ask
   can never quietly change the plan twice. Each press is a model call.
6. **Build chat questions inside the thread** in assistant-ui's own way. This changes little that you can see, so it is
   optional.
7. **Later, if you want them:** attachments, voice typing (Sinhala needs testing first), several chats per scene, and
   thumbs up or down.

Not added: anything that shows cost or tokens, reading replies aloud, or a model picker.

**Done so far (2026-11-07, not yet seen in a browser):** steps 2, 3 and 4.

- Stop: the check found one real gap. Stopping just after Zora saved, but before the reply was written, left the plan
  changed with no reply. Now the server always finishes the turn, so everything is saved or nothing is. After Stop, the
  chat keeps what had arrived. When the real reply lands, it takes its place.
- Chips: Zora's writer does read your production notes, so Zora shows chips. "Remove" now marks a note as rejected
  instead of deleting it, so a document read again does not bring the note back.
- Still to check, by you: press Stop on a real turn and see the reply arrive. On Cloud Run, the chat functions may need
  "CPU always on" to finish after you stop.

**Done 2026-11-08 (also not yet seen in a browser):** steps 5 and 6.

- Edit: a pencil on your last message opens it in place. Sending it makes a new message. The old one and its answer stay,
  greyed ("Edited below"). If Zora's answer had changed the plan, you are asked first whether to undo that change.
- Ask again: only under the last answer, and only when that answer changed nothing. The first answer stays as it was.
  The new message says "Asked again". The agents no longer see a replaced message, so they won't say "you already asked
  that".
- Build questions now live inside the thread: "Go to the open question" takes you to one. The cards look the same.
- Step 7 is not built. Each item there needs its own plan, and which one comes next is your choice.
- Still to check, by you: Edit and Ask again on a real turn (each press costs a model call).

Your decisions: what Stop should do, whether "Ask again" keeps both answers, when to do step 6, the starter questions
and command names, and what comes after.

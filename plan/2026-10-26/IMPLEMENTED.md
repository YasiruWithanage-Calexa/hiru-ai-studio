# Director Chat v2: what is built

Plan: the "Director Chat v2" page (claude.ai artifact EwrDrTbStJMwrWkHigXMsC, 26 Oct 2026). Phases run
one at a time; this file is updated at the end of each.

## Phase 0: fix what broke (done, 2026-10-26)

| Failure in the S02 conversation | Fix | Where |
|---|---|---|
| "Sign-in is unavailable" in the middle of a turn | A failed signing-key refresh is retried (0.2 s, 0.6 s); the last good keys keep serving for 30 s windows; only a key id never seen before needs the network and answers 503. The browser retries a 503 once, before anything is stored, and says "Connection dropped, retrying…". | `api/deps/auth.py`, `lib/api/browser.ts` (interface), `tests/api/test_auth.py` |
| "text takes text" shown to the person | Kernel messages are sentences ("say what the text should be"); every recorded refusal passes `refusals.for_person`, which swaps anything that reads as internals for a plain sentence. | `engine/refusals.py`, `engine/kernel.py` |
| "Update S02 with that" had nothing to apply | `proposals.refers_back` + `latest_advice` read the stored thread; plain advice becomes ONE options card (tried on a copy, pinned to ids); an open card stays the way to apply; if nothing can be made, the reply says so. | `engine/proposals.py`, `engine/turn.py` (`_follow_up`) |
| "Apply this below" with no card | `proposals.guard_reply` removes sentences that point at a card the message lacks (a reply that was only that falls back to the plain reply); the reply prompt says the same. | `engine/proposals.py`, `engine/turn.py` |
| Chat-only answer to a change request | A model answer of `edit`/`craft` with no operations and no tasks is asked once more with an `<again>` note (Nova W6). | `engine/conductor.py` |
| Reply could claim more than happened | The turn ledger is the last thing the reply model reads (Nova W2); refusals are listed with their plain reasons. | `engine/turn.py` (`_reply`) |

Tests: `tests/services/director_chat/test_followup.py` (follow-ups, guard, re-ask, refusal wording),
`tests/api/test_auth.py` (signing keys). Replay: four new cases in `tests/eval/director_replay.json`
(two run without a model; `followup-after-advice` and `yes-after-advice` need `--model`), and the
harness takes a `history` per case and scores `card` and `clean_reply`.

### Deviations from the plan
- **No separate proposal table.** The plan's "proposal ledger" is the stored thread itself: an options
  card is already a proposal pinned to shot ids, and plain advice is turned into one on the follow-up.
  A `director_changesets` table arrives with Phase 2, which is what undo needs.
- **Idempotency key not added.** The browser retries only a 503 that comes before the message is
  stored, which cannot apply twice. A key is needed once a retry can follow a started stream (Phase 2).
- A follow-up whose advice needs staging, camera or frame changes ends with "I could not turn that
  suggestion into a change I can make here", because those operations arrive in Phase 1.

### Not yet run
- `--model` replay (needs the OpenAI key and spends tokens). The two new model cases are unscored.
- The hosted dev project is untouched (no schema change in this phase).

## Next: Phase 1, reach the picture
Needs the decisions Q1 (frame renders from chat) and Q5 (vision model) from the plan before it starts.

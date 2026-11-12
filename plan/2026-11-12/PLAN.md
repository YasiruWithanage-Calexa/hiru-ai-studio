# House rules, and the first one: implied things (plan/2026-11-12)

Revision 2 (2026-11-12). Revision 1 had code fill in a phone from a table (`DEVICE_OF`) and guess where it sits. The person
rejected that: those are judgements, they belong in guidance that is always read and can be changed, not in code. This
revision replaces it. Phase 0 (the lab) is done and paid ($0.99, six runs). Phase 0b is a second small lab, the
person's yes first. Phases 1 to 5 are offline. Phase 6 is a paid live check.

**Read §1 and §3 first if you are a new chat picking this up.**

## 1. Why

The person asked (2026-11-12), on Scene 2 "The night drive" of *hiru short combined 1* (Ekama Sakshiya): why does no shot
show the phone? The script says "Aruni's voice message plays." and "Mudalali calls." The person: **a voice message plays
from a mobile phone; that is simply implied.**

What the dev database showed (read-only):

- The scene packet knows HOW the voices arrive (`presence: voice_message` / `phone`) but has no phone: every block's
  `device` is empty and `D_things` holds only the photo and the red thread. Canon has no phone.
- On the packet path (`RAPHAEL_PACKET=true`) there is no director's breakdown, and `raphael_breakdown` is the only agent
  whose prompt has a phone rule. The rule existed, in one agent's prompt, and the path that runs today skips that agent.
- So Raphael read the phone as an invention ("Avoid … simulated device interaction", its own note).

Two lessons, and this plan is built on them:

1. **A craft rule kept inside one agent's prompt is lost when that agent is not run, and drifts from the copies in other
   prompts.** (The safe-depiction line is in 11 prompts today.)
2. **Judgements (what a script implies, where an object sits) belong to the model, guided by rules a person can read and
   change. Code checks that the result holds together.**

## 2. What the lab proved (phase 0, done)

`lab/implied_phone/`. `export.py` reads the scene's packet read-only into `base/` (as stored) and `phone/` (a phone added
by hand). `run.py` runs Raphael, both stages, on the packet path, with a length cap and, optionally, one block appended to
the planner and cinematic system prompts in that process only (`--line`, or `--rule <house rule file>` in the house-rules
form). No database writes. `summary.py` reads a run.

| Run | Cap | Packet | Added to the prompts | $ | Message source shown | Call source shown | Where the phone is |
|---|---|---|---|---|---|---|---|
| product today | 1.0x | as stored | - | - | no | no | - |
| run1 | 2.0x | phone by hand | - | 0.18 | no | must INSERT | his hand |
| run2 | 1.0x | phone by hand | - | 0.16 | no | must INSERT | dashboard |
| run3 | 1.5x | phone by hand | - | 0.15 | no | must INSERT | his palm, while steering |
| run4 | 1.0x | phone by hand | phone-specific line | 0.15 | must INSERT | must INSERT | cradle |
| run5 | 1.5x | phone by hand | phone-specific line | 0.16 | must INSERT | must INSERT | cradle |
| **run6** | 1.5x | **as stored** | **general H-12 v1** | 0.19 | must, **wide master** | must master + INSERT | **dashboard mount, hands-free, every clip** |

What it shows:

1. **A general rule is enough for the planner.** In run6 nothing was added to the data and the rule names no device, yet
   Raphael inferred the phone, placed it ("an implied device fixed to the dashboard"), kept it there in every clip,
   chose hands-free to avoid finger work, and showed each voice's source before the voice.
2. **Its one weakness: size.** The message's source was shown only in a medium-wide master, where a phone screen will
   not read, and the review turned down a closer shot. H-12 v2 adds "close enough for the audience to read what it shows"
   (not yet run).
3. **Without any rule, the source of a recorded message is never shown** (0 of 3), even with the phone in the data.
4. **At 1.0x, two must inserts push another out** (run4 lost the red-thread close-up). At 1.5x everything fit.
5. One run per arm: each proves the idea can work, not that it always does.

## 3. The design

Three layers, each doing one job:

| Layer | Holds | Who changes it | Here |
|---|---|---|---|
| **House rules** (new) | the studio's craft rules, always read | a person, as files in the repo | H-12 implied things |
| **Canon** | facts about the story world | a person, in the Canon panel | the phone, marked inferred |
| **Code** | what must hold together, no taste | a developer | a heard-through-device line names a device that exists |

Production memory stays as it is: one production's own direction, which can override a `default` house rule.

### 3.1 House rules

**Files.** `src/libs/hiru_ai/house_rules/<name>.md`, one rule a file:

```
id: H-12
topics: [objects, sound]
kind: default          # default: a production's direction or a scene note may override it; must: nothing does
why: A voice from a device reads as invented unless its source is seen.
version: 2
---
Implied things. A script often implies an object it does not name: the device a voice comes through, the thing an
action needs. Such an object is part of the scene, as real as a scripted prop; showing it, and the one small action
that starts it, is not invention. A sound or voice that comes from a device begins after its source is seen. Decide
from the scene where the object is and who holds it, keep that the same in every clip, and show it at the moment it
matters to the story, close enough for the audience to read what it shows.
```

Not under `knowledge_bases/`: those are embedded for search, and a search can miss. A house rule is always given.

**Loading.** `hiru_ai/core/house_rules.py` reads the folder once (cached), validates each header (`id` unique, `kind` one
of two, `topics` known, `version` an int), and refuses to start on a bad file, like a bad manifest. `hiru_ai validate`
checks it too.

**Subscribing.** An agent names the topics it is given, next to `memory:`:

```yaml
middleware: [static_first, usage, house_rules, production_memory]
house_rules: [objects, sound]      # `*` for every rule
```

`manifest.py` gains the `house_rules: list[str]` field (default empty), and `house_rules` in `middleware` is required when
it is set (the same pairing `memory:` has).

**Injecting.** The `house_rules` middleware appends one block to the END of the **system** prompt:

```
HOUSE RULES (the studio's own rules; a default rule yields to the production's direction and the scene's notes, a must rule never does)
- H-12 (default) Implied things. …
```

The rules change only with a deploy, so the block is constant for an agent and the cached prefix stays cached;
`static_first` still passes (the system prompt still starts with the part's own text). Rules sorted by id, so the bytes
never move. The ids and versions a call was given are recorded on the run, so a plan can be traced to "H-12 v2".

**Precedence**, written once into the block's header and into the production-memory note: scene notes > production
memory > house `default`; a house `must` is above all of them.

**First subscribers:** `breakdown_episode` and `breakdown_repair` (they read the script), `raphael_planner` and
`raphael_cinematic` (they plan it). Others join when they need a rule.

### 3.2 The reader records what is implied (into the packet and canon)

Today the reader cannot: a card's name is cut from the document's words ("a model never types a name") and the episode
step may "use only the ids you were given". The word "phone" is not in the script.

The change, kept as narrow as the person's rule:

- `SceneBriefW` gains `implied: list[ImpliedW]`, with `ImpliedW = {name, holder, where, blocks, why}`: a short common noun
  ("phone"), the C id who holds it, where it is ("in a dashboard mount beside the wheel"), the block numbers it serves,
  and one line of why. Its source is always `inferred`.
- Code (`contracts/breakdown/build.py`) turns each into a thing: a canon name that already matches (name or alias) is
  reused; otherwise a new `P` id with `seen: true`, no spans, `source: inferred`, and a card made from `where` and `why`.
  The block's `device` names it; its events list it in `things`.
- A check (`contracts/breakdown/checks.py`) holds the name to a plain noun of at most three words, so a model cannot slip
  story in through a name, and holds `holder` to a person in the scene.
- The thing flows to canon by the existing path (`fill.canon_cards` → `canon_rows`), with the version's `source`
  `inferred` instead of `extract`, so the Canon panel can label it and a person can rename, change or delete it. A person's
  edit is never overwritten (`canon_rows` already keeps an existing entity's card).
- The packet's `D_things` row and Raphael's opening already show `source`; nothing new there.

H-12 is what tells the reader to do this; the schema only makes it possible.

### 3.3 The invariant (code, report only)

`contracts/breakdown/checks.py`: a block whose presence is heard through something (`phone`, `voice_message`,
`recording`) must name a `device` that is a thing of the scene. If not, the existing repair pass (`breakdown_repair`) is
asked once, then the gap is an `I_open` note on the packet. It never blocks planning. No device list: the check asks only
"is there one, and does it exist".

`contracts/raphael/checks.py`: a line whose block has a device, and no clip at or before it whose picture names that
device, is a report row ("L3 is heard through Dinu's phone; no clip shows the phone first"). Reported, never blocking.

## 4. Phases

| Phase | What | Cost | State |
|---|---|---|---|
| 0 | Lab: the phone by hand, a phone-specific line, a general house rule (six runs) | $0.99 | done |
| 0b | Lab, the person's yes: (a) Raphael on the stored packet with H-12 v2, cap 1.5x, does the message source come close enough to read; (b) the episode reader with H-12 and a lab `implied` field on Ekama, does it record the phone with a sensible holder and place, and nothing else invented | about $0.50, cap $1.00 | |
| 1 | House rules: folder, loader, header checks, `hiru_ai validate`, manifest field, middleware, run record; tests (constant bytes, sort order, topic filter, `*`, bad header refused, precedence text) | $0 | |
| 2 | H-12 as the first rule; subscribe the four agents; take the phone rules out of their prompts where H-12 now covers them (`raphael_breakdown`'s PHONE CLOSE-UPS stays until that agent is retired; it is not on the packet path) | $0 | |
| 3 | The reader: `ImpliedW`, build, name check, canon `source: inferred`; tests on Scene 2's packet (phone recorded once, reused when canon has one, no listener → `I_open`, a person's canon edit kept) | $0 | |
| 4 | The two report-only checks + tests | $0 | |
| 5 | Interface: the Canon panel and the packet view label an inferred thing "Inferred"; no new screen | $0 | |
| 6 | Live check, the person's yes: rebuild Ekama's breakdown, re-plan Scenes 1 to 3 with Raphael at each scene's own cap; Scene 2 should show both phone moments readably; Scenes 1 and 3 should gain nothing invented | about $1.00, cap $1.00 a scene | |

Checks before finishing (backend): `ruff check src tests scripts`, `mypy`, `scripts/lint_imports.py`, `hiru_ai validate`,
`hiru_ai catalog --check`, `pytest -q` (with `ADAM_MODE=staged OPENAI__API_KEY=`). Interface: `npx next typegen && npm run
check && npm run format:check`.

## 5. Decisions

- **D1 (taken, 2026-11-12): the inferred phone goes into canon**, marked inferred, as well as the packet.
- **D2. Files only, or files plus database edits.** Recommended: **files only** for now (reviewed in git, tested, one
  deploy per change). An admin page that saves an edited rule as a new version over the file can come later, once a few
  rules exist.
- **D3. Who may change a house rule.** With files only: whoever can merge to the repo. With an admin page later: admin
  only; a director changes their own production through production memory, not house rules.
- **D4. Move safe depiction into house rules (as a `must`) in this plan, or a later one.** Recommended: later. It has a
  code gate that must stay, and 11 prompts to change; one rule at a time.
- **D5. The cap for scenes with device lines.** Not a rule: it stays the person's per-scene choice. The scene view could
  say what the device moments use.

## 6. Not in this plan

- The other planners (Jonathan, David, DaVinci, Adam) do not read the packet. They can subscribe to house rules later.
- A creative-freedom setting (0 to 100). Discussed 2026-11-12: separate from this, because an implied object is reading
  the script, not inventing. Its own plan and lab if wanted.
- Other implied objects (money for "she pays", a door for "he walks in"): H-12 already covers them in words; phase 6 only
  checks phones. A new case gets a lab run before anyone relies on it.

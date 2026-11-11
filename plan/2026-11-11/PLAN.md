# Two memories: the documents read once, the production broken down for the shot planners (plan/2026-11-11)

Revision 2 (2026-11-11, end of day). Phases 1 to 6 have since been built offline (IMPLEMENTED.md, last section). Revision 1 was the design. Phase 0, the lab, has since been built and run on Ekama
Sakshiya, and Raphael's first agent was given a packet path. This revision records what the lab proved and what it changed in
the design, and says what is left. **Read §13 first if you are a new chat picking this up.** The run log, with every paid run,
its cost and what it showed, is [IMPLEMENTED.md](IMPLEMENTED.md).

The person asked (2026-11-11): the document reader's blocks are too thin. The reader is the only step that sees the
whole script. Every step after it works on one scene and does only its own job. So, before planning, the system must
turn the uploaded documents into everything a shot planner needs for a scene: **all of it, nothing lacking, as much
detail as the documents give**. A strong model at high effort is fine.

## 1. What we found (before the lab)

The two readings the person sent (`ekama_sakshiya_screenplay (clean).pdf`, 3 scenes, text mode):

- **Sol high and Astra medium are identical except for one line, and Astra loses it.** `Mudalali calls. Route eka maru
  karapan…` stays inside an action block in Astra's reading, so the spoken line is lost.
- **The words are right; almost nothing else is there.**
  - Aruni's S02 line is a voice message, and Mudalali speaks on a phone. Both look like normal speakers.
  - Nimal in S01 is a body, and only the prose says so.
  - Places of every kind are one list: regions (Colombo), sets (Mahawewa Canal), spots inside a set (canal gate),
    places only spoken of (Old Port warehouse), places only in a photo (village bus stop). The same goes for things.
  - "Six hours earlier" is not used. In story order the document is S03 → S02 → S01, so S01 is a cold open.
  - The director's treatment (palettes, lenses, lighting, editing, sound, slow motion) reaches no scene.

What Raphael is sent today, measured on Ekama with the product's own code (`lab/two_memories/compare.py`, side by side in
`lab/two_memories/runs/compare_ekama.md`):

| What | Raphael today | What goes wrong |
|---|---|---|
| Who is in the scene | `present()`: a name anywhere in the scene's text | S03: "Dinu, Aruni, Nimal, Mudalali" (Aruni and Mudalali are only named in a line). S02 lists Nimal. |
| Who is only heard | `mark_recorded` / `is_heard` word lists | S02: Aruni caught; Mudalali's call stays inside an action line, so he is treated as present |
| Blocks | the rules parser | S08's fight, loudspeaker, recorded voices and Ruwan at the power: ONE block, timed at 1.5 s |
| Props | `objects_of()`: canon names in the text | "objects: phone, gun"; no holder, no state |
| Positions, hands | the stager, called inside every planning run | built from one scene, paid again each run |
| The scenes around it | heading of the scene before and after, page order | nothing says S03 happens first |
| Direction | every rule, every scene | "Love scenes" lenses offered for the mill fight |
| Purpose, mood, turns | `raphael_breakdown`, a model call each run | paid again every planning run |

Size: Avasana (217 pages, 30 episodes) is about 69k tokens of text. Ekama (clean) is about 2k with line numbers.

## 2. Decisions (all taken, 2026-11-11)

1. **Uploads happen once**, at production creation. Files cannot be uploaded again after creation.
2. **Two memories.** Source memory: per document, the documents' own content sorted into a structure, never edited.
   Breakdown memory: per production, the processed information, built at creation and refined before planning.
3. **Planners only read.** They never write to the breakdown memory.
4. **Continuity is one call over every episode.**
5. **Episodes are read in parallel**, one call each (several scenes per call is fine; see §4.4).
6. **A person can still edit a scene's script.** The edit is owned by the person; facts built on the old lines go stale.
7. **The source memory cannot be edited by a person.** Corrections go into the breakdown memory.
8. **D1 yes:** the breakdown memory is the ONE source; today's columns (`canon_entities`, `production_memory`,
   `scenes.reading`, `scenes.staging`, `scenes.script`, `dialogue_lines`, `episodes.synopsis`, `scenes.title`) are FILLED
   from it by code, at the end of creation and after each refinement.
9. **D2:** hands and posture only where they change; code expands "the last one holds" per block.
10. **D3:** full cards for the scene's people; nobody else is named in a packet.
11. **D4:** no packet size limit; completeness wins (measured: §7).
12. **D5:** split effort: medium was enough on Ekama (scene cuts exact on every run).
13. **D6:** the lab ran under a **hard cap of $1.00** (the person's order, instead of $8). $0.7275 is spent.
14. **D7:** JSON documents per production and per scene, plus the columns filled from them. The lab's shapes are the contract.
15. **Raphael's first agent reads the packet** (the person's go, 2026-11-11): the whole packet is its first message (§7.3).

## 3. Rules every step keeps

1. **The model points; code copies.** No model re-types the documents' words, not even a name. It answers with line
   ranges and word ranges; code cuts the text. A card's NAME is a word span too (lab finding: a free-text `name` field made
   the model write pointers like `"29:0-1"` into it). References between cards are indexes into the model's own list
   (`within`, `scope_card`), resolved by code.
2. **Ids, never names.** People `C01…`, places `L01…`, things `P01…`, direction rules `D01…`, threads `T01…`, episodes
   `E01`, scenes `E01-S03`, blocks `E01-S03-B04`, events `…-e2`. Code assigns every id. A model refers to ids it was given.
3. **Every value says where it came from:** `script` (with its line range, checked), `inferred` (with a reason) or
   `person` (an edit, always wins). Provenance goes in a `source` FIELD, never as a prefix inside text (lab finding: the
   model wrote "inferred: uneasy" into mood words until the prompt forbade it).
4. **Never invent story.** What is implied may be said. What the script leaves open stays open (the continuity call left
   "how the key gets back into Nimal's fist" open, and reported "Nimal's key falling" as not in the script).
5. **One owner per kind of fact.** Another step may add a disagreement as a finding; it never overwrites.
6. **Absent-safe.** If any step fails, the production still opens; what is missing is reported.
7. **A bad pointer drops one value, not the scene.** A card fact that points outside the document is dropped and reported
   (non-blocking). Blocking findings are about the scene's own words, ids and presence.

## 4. The flow (as built in the lab)

```
creation (once)
  1 split        one call per document          → source memory: sections, cards, rules, scene cuts (pointers only)
  2 build        code                           → breakdown memory: ids, cards cut, rule scope, scenes cut
  3 continuity   one call, every episode        → timeline, synopses, arcs, knowledge, threads, looks, relationships, scopes
  4 episodes     one call per episode (or per group of scenes)  → scene briefs, blocks (word ranges), events
  5 checks       code; failing scenes → repair call (≤2 tries, a worse patch never kept)
before planning (per scene)
  6 stager       one call per scene, on the scene's BLOCKS (not the raw script)  → zones, marks, props
  7 packet       code                           → the scene packet (§7), what every planner reads
after a person edits a scene
     that scene's episode call (one scene) + its stager; the next scene is checked for a changed hand-over
```

### 4.1 Step 1, the split
The model reads numbered lines (page furniture stripped first; note the PDF text has form-feed `\x0c` characters that must
be removed before matching) and returns **labels over line ranges**: `title_page`, `overview`, `cast`, `canon`,
`direction`, `story`, `other`. Cards: name as a word span, line range, facts as word spans. Code widens every fact except
`age`/`gender` to its whole sentence inside the card's lines (`sentence_spans`; a one- or two-word label line, such as the
name line, is never part of a sentence). Rules: one per row of a direction table, plus one per direction written inside a
scene's prose, scoped to that scene. Scenes: heading line and last line, the document's own numbers.

Prompt rules that fixed the over-reading (run 2: 41 cards → run 3: 31): a thing is a card only if someone carries, uses
or wears it or the plot needs it; set dressing, the contents of another thing and a second name for the same item are not
cards; a place is a region, set, spot or vehicle. Still weak: `seen: false` is never set; moving things get very wide line
ranges (reported by `checks.cards`).

**Pages mode** (Avasana): not built or run. The page images are first transcribed into clean numbered lines per window of
pages, then split. This is the weakest link and the live check's main question.

### 4.2 Step 2, the build (code)
Ids, text cuts, rule scope (a place rule matches a set through its region: `within`), scenes. Conflicts between documents
(a bible and a script) become creation questions: **not built** (the lab had one document).

### 4.3 Step 3, continuity
Input: the cards with ids, the rules, the story under scene ids. Output: `timeline` (story order, day, relative time,
flashback / cold open, anchor), `synopses`, `arcs`, `knowledge` (with `audience_only` for irony), `threads` (setup_payoff,
open_question, journey with beats per scene), `looks` (wardrobe, injury, death, condition), `relationships`, `scopes`
(rule → scenes, and a named moment's scene). Every item carries `source` and `lines` or `reason`. Ekama: one call,
$0.0757. Open: it placed S01 5th (after S05) with its own note "unresolved"; a person edit would say after S04. Untested:
whether the answer stays compact for 30 episodes.

### 4.4 Step 4, episodes
Input: the cards, the rules, the continuity facts (timeline whole; knowledge and scopes for the scenes asked), the end
of the episode before, the scenes' numbered lines. Output per scene: title (a noun phrase of at most five words), summary,
purpose, place id, mood, people (presence, wants, feelings), things (role, holder at start and end), blocks (word ranges;
a cue such as `ARUNI -` is the speaker field, not words), events (actors, things, spot, visible, change, function,
`speech`), turns, `source` fields, and `rules_met` (the conditional direction rules the scene meets). A dialogue block
holds only spoken words; a recording heard but not quoted is a `sound` block. Ekama: S01–S03 in one call ($0.0754),
S04–S09 in one call ($0.1425).

### 4.5 Step 5, checks and repair
Checks in §8. A scene with a blocking finding goes back to the same model with its own answer and the exact problems; it
returns the scene again; at most two tries; a patch that is not better is not kept. Ekama: S07 (one skipped word) and S08
(narration cut into one-word "dialogue" blocks) both fixed on the first try ($0.0589 for both).

### 4.6 Step 6, the stager
The product stager's prompt and output (`agents/stager`: zones, marks, props) run ONCE per scene, on the scene's blocks
and people (heard people marked "NOT in the place"), not on the raw script. Two lab prompt lines: fill `holding` when the
script has someone use, raise or carry a thing; mark every on-screen person at their first block (the second did not move
the model). Code drops invalid entries (a person not in the scene, a block that does not exist, an unknown zone), expands
marks per block, and reports a disagreement with the episode call about who ends holding a thing. The packet says who is
**not placed** before which block. About $0.02 per scene.

Known limits: (a) one state per person per block, so a block that holds a raise, a kick and an arrest keeps the gun in
Mudalali's hand after it is kicked away, and S04 reports Dinu holding the chain where the episode call says the cash bags;
(b) crowds ("Villagers", "Police", "Masked men") are dropped because the packet has no extras. Both are fixed upstream (§11).

## 5. The two memories

**Source memory** (per document): sections as labelled line ranges with their text, the cards as read, the direction
rules, the story with its scene boundaries, the clean transcription in pages mode. Written once. Search chunks are built
from it.

**Breakdown memory** (per production): entities and cards; rules and scope; timeline, threads, arcs, knowledge, looks,
relationships; scene briefs, blocks and events; the stager's map (`stage`); open questions and findings. Every value has
its source, its owner step and a version; a person's edit is a new version. Values built from a scene's lines go stale
when that scene's script changes. Today's columns are filled from it (D1).

## 6. The steps before planning

| Today's step | In this design |
|---|---|
| `story_reader`, `story_check` | absorbed by the split |
| `memory_reader`, `memory_check` | absorbed by the split (direction rules). `memory_conflicts` stays as code. |
| `canon_rules`, `canon_extractor`, `canon_deduper`, `canon_merge` | absorbed by the split and the build |
| `reader_canon`, `reader_episode`, `reader_repair` | become the split, the episode call and the repair |
| `architect` (titles, synopsis) | synopses by continuity, titles by the episode call |
| `look_drafter` | absorbed by continuity; `look_plan`'s code still writes the look rows |
| `structure_analyse` questions | kept: the channel for creation questions |
| `beat_finder`, `scene_reader`, `bridges` | absorbed by the episode call |
| `stager` | kept, run once per scene before planning, on the packet's blocks |
| `raphael_breakdown` | not needed on Raphael's packet path (purpose, turns and direction are in the packet) |
| chunks, search | unchanged, built from the source memory |

## 7. The scene packet

Code assembles it from the breakdown memory (`lab/two_memories/packet.py`), the same for every planner. As JSON it is
about 2.7k–5.5k tokens for an Ekama scene; as plain text 1.1k–2.0k.

### 7.1 Sections
- `ids`: every id in the scene → name and kind.
- **A. The scene in the story:** id, heading, title, summary, purpose (+ `purpose_source`), the scenes before and after on
  the page, story time, the scenes before and after **in story order** (how the one before ends, how the one after opens,
  who is there at its end), threads touching the scene (earlier / here / later beats), irony, knowledge, looks,
  relationships **up to this scene only** (a later change is not yet true).
- **B. People:** only the scene's people (seen or heard), each with the card facts shown, presence, wants, feelings.
- **C. Place:** card, kind, and (from the stager) zones.
- **D. Things:** card, role, holder at start and end.
- **E. Blocks:** id, kind, exact words, speaker, presence, device, addressee, heard by, intent (+ source), delivery hint,
  events.
- **F. Feeling:** mood, turns.
- **G. Direction:** each rule in scope with `applies`: `scoped`, `general`, or (for lens rules with no place or scene
  scope) met by the scene per `rules_met`; a rule the scene does not meet is left out; a named moment is attached.
- **H. Length:** stated and spoken seconds.
- **I. Open:** findings and questions for the scene.
- `stage`: zones, each person's in and out state, the blocks where a state changes, props, `not_placed`.

### 7.2 What code does at assembly (the stored memory is never changed)
- ids inside a model's sentences become names (`Name [id]` when two cards share a name); ids stay in every structured field.
- a card fact is shown only when it lies outside the story (cast, direction) or inside THIS scene's lines; a fact from
  another scene is withheld and counted (`withheld_other_scenes`); it belongs to a thread.
- a card `summary` is shown only when its range is at most 6 lines.
- complete means: no blocking finding for the scene, every person and thing resolves, every block has words. If not,
  planning waits.

Still missing from the packet: extras (groups, rough counts, when they appear), weather and light sources, the
safe-depiction note, Raphael-style timing per line (it is in Raphael's `<timing>`, §7.3, but other planners should get it
too), and the story-order fix for S01.

### 7.3 Raphael's packet path (built, not wired)
`src/libs/contracts/raphael/packet.py`: `opening(packet)` → the first message, `SceneS` and an id map.
- The model gets `<packet>` (the WHOLE packet as text; each block named `b4 = E01-S08-B05`), `<timing>` (Raphael's own
  clock per block), `<voice_only>`, `<length>`. No `<production>`, `<scene>`, `<script>` or `<breakdown>`.
- Raphael's tools and checks read `SceneS` built from the packet: cast = seen people plus heard people who speak (the
  voice-only rule finds a speaker in `cast` whose every line is heard); a line's delivery from its presence (`is_heard`
  exact); objects = the packet's things; `opening_state` and each block's `now` from the stage; an action's `events` from
  the packet's events; `codes` = the packet's C ids.
- `raphael_planner`: five `- PACKET (plan/2026-11-11).` prompt lines; `agent.input_from_packet(packet)`.
- Tests: `tests/raphael/test_packet_input.py` (nothing in the packet is lost except a written `LEFT_OUT` list; S02 hears
  Aruni AND Mudalali; Raphael's own `Stage1Session` reports on the packet scene). Fixtures: `tests/fixtures/raphael/`.
- Not wired: the graph still builds today's message. Stage 2 (`raphael_cinematic`) is unchanged.

## 8. Checks (code, free)

Built in the lab (`lab/two_memories/checks.py`):
- **Words:** every word of a scene's body in exactly one block (a dialogue cue excepted); a `speech` event sits in a
  dialogue block; a dialogue block is never just its speaker's name.
- **Ids:** every id resolves. **Sources:** every `script` value's range is inside the document.
- **Presence:** an on-screen speaker is listed on_screen; a device speaker is not, unless the person is also seen in the
  scene (Mudalali fights AND his recording plays).
- **Continuity** (report): a thing starts where the scene before left it.
- **Direction:** every scoped rule resolves. **Length:** spoken over stated is reported, never trimmed.
- **Cards** (report): a thing spanning over 10 lines, a name inside another card's name, the same detail on two cards, a
  spot with no set, a set no heading names.
- **Stage** (report): dropped stager entries; the stager's last hands against the episode call's holder.

Not built: the time check (the heading's time of day never changed; story order complete; a flashback before its
anchor), a dead person speaking on screen after their death, the safe-depiction note, creation questions.

## 9. Models and cost (measured on Ekama, Sol `gpt-6.1-sol` at medium; $2 in / $10 out per 1M)

| Step | Ekama (9 scenes) |
|---|---|
| Split | $0.06–0.08 per run |
| Continuity | $0.08 |
| Episodes | $0.22 (two calls: 3 + 6 scenes) |
| Repair | $0.03 per failing scene |
| Stager | about $0.02 per scene |
| **A whole Ekama creation** | **about $0.60** (split 0.07 + continuity 0.08 + episodes 0.22 + repair 0.06 + stager 0.18) |

A 30-episode season is untested: estimate about $10 at creation (continuity ~75k in / 20k out; each episode ~15k in /
25k out). Medium effort was used throughout; whether continuity and episodes need high is for the live check. The interface
never shows any of this.

## 10. Phases

| Phase | What | State |
|---|---|---|
| 0 | Lab `lab/two_memories/` on Ekama: split, build, continuity, episodes, checks, repair, stager, packet, Raphael comparison | **done** ($0.7275 of $1.00); pages mode and Avasana not run |
| 0b | Raphael's first agent reads the packet (§7.3) | **built**, not wired |
| 1 | Contracts in the product: move the lab's shapes, ids, lines, build, checks, packet, render into `src/libs/contracts/breakdown/` with tests (the lab's 26 tests come along) | **built** offline (IMPLEMENTED.md, last section) |
| 2 | Agents and the creation run: split, continuity, episode, repair as parts in an agent group (e.g. `agents/breakdown/`), the stager on blocks; creation runs them with progress, episodes four at a time | **built** offline, behind `BREAKDOWN__ENABLED` (off) |
| 3 | Storage: the two memories (schema v21) and the code that fills today's columns from the breakdown memory, including `scenes.script` and `dialogue_lines` (so Raphael's line ids are real rows) | **built**; v21 written, not verified on a local stack; **the person applies the migration** |
| 4 | Wire Raphael: the graph builds Raphael's opening from the stored packet behind a setting; today's path stays until the live check. Retire the absorbed steps behind a switch | **built** (`RAPHAEL_PACKET`, off; the absorbed steps retire under `BREAKDOWN__ENABLED`) |
| 5 | Person's edits: the one-scene refresh, staleness, the hand-over check | **built** offline |
| 6 | Interface: creation progress, creation questions, a read-only scene packet view (no costs) | **built** offline (packet view + refresh; progress and questions on the existing build screens); not seen in a browser |
| 7 | Live check on Ekama full and Avasana (pages mode) | **the person's** |
| — | Other planners (Adam, David, Jonathan, DaVinci) read the packet | the person's choice |

## 11. Open decisions and fixes (for the person, or the next chat)

1. **Long action blocks:** one block can hold several moves (S08's last block: the gun raised, kicked away, the arrests).
   Recommended: the episode prompt cuts an action block where a person's state changes (each move its own block), rather
   than giving the stager "end of block" states. A paid re-run of S04 and S08 shows it.
2. **Extras:** add `extras` to the episode brief (group name, rough count, first and last block) and to the packet (§7 B).
   The stager is then told about groups. A paid re-run of S04, S08, S09.
3. **S01's story order:** continuity left it unresolved; decide whether the continuity prompt should place a cold open
   right after the scene it follows (S04) or leave it to a person edit.
4. **`seen: false`** is never set by the split. Decide whether code sets it (a place no heading names and no event uses)
   or the prompt is tightened.
5. **A real Raphael comparison:** plan S08 from today's input and from the packet and compare the shots. Up to $5 per run
   under Raphael's own cap; needs the person's budget.
6. **Budget for the live check** (phase 7): Avasana will pass $1.00.

## 12. Risks

- **Continuity's output is long** for 30 episodes: kept to cross-scene facts; code checks the hand-overs.
- **Confident guesses:** every value has a source; inferred values never reach canon cards.
- **Two owners of one fact:** one owner per kind; disagreements are findings (the stager vs the episode call already
  shows this working).
- **Pages mode accuracy:** the transcription is the weakest link; the existing "Dialogue read from page images: check it"
  confirmation stays.
- **A big change to creation:** absorbed steps retire behind a switch; the old path stays until the live check passes.

## 13. For the next chat: how to pick this up

**State on 2026-11-11.** Nothing is committed. The lab, the Raphael packet path and these plan files are uncommitted in the
backend repo. The interface repo is untouched. Schema v21 does not exist yet.

**Where things are**
- Lab: `lab/two_memories/` — `lines.py` (numbered lines, word spans, `sentence_spans`), `ids.py`, `schema.py` (all wire
  shapes and the stored memory), `build.py`, `checks.py`, `inputs.py` (what each call is sent), `packet.py`, `render.py`
  (packet as text), `stage.py` + `stage_run.py`, `paid.py` (the $1.00 cap, disk cache by request hash, ledger),
  `run.py` (commands), `compare.py` + `compare_run.py` (Raphael today vs the packet), `rehearsal.py` (Ekama text and a
  hand-written gold for S01–S03), `prompts/` (split, continuity, episode, repair, stager), `tests/test_lab.py` (26 tests).
- Saved model answers (the Ekama gold the tests use): `lab/two_memories/gold/` — `split_ekama.json` (the cards the person
  approved), `continuity_ekama.json`, `episode_ekama_s1_s3.json`, `episode_ekama_s04_s09.json`,
  `episode_ekama_s99_repairs.json` (applied last), `stage_ekama_<scene>.json`.
- Outputs to read: `lab/two_memories/runs/packets_ekama.json` (all nine packets), `compare_ekama.md`,
  `raphael_packet_message_s02.txt` / `_s08.txt`, `split_ekama_readable.json`, `ledger.csv`.
- Product: `src/libs/contracts/raphael/packet.py`, `src/libs/hiru_ai/agents/raphael/raphael_planner/agent.py`
  (`input_from_packet`) and `prompts/system.md` (PACKET lines), `tests/raphael/test_packet_input.py`,
  `tests/raphael/test_lab_parity.py` (lists the PACKET lines), `tests/fixtures/raphael/packet_ekama_s0{2,8}.json`.
- Source text: `tests/fixtures/reader/ekama-sakshiya.txt` (the PDF's text layer; `rehearsal.doc()` strips the page
  furniture and the `\x0c` characters).

**Commands** (repo root, Windows; use `.venv/Scripts/python.exe`, not the system Python)
- `.venv/Scripts/python.exe -m pytest lab/two_memories/tests -q` — the lab's tests (free).
- `OPENAI__API_KEY= .venv/Scripts/python.exe lab/two_memories/run.py rehearse | dry | continuity | episode | stage` —
  free without `--yes` (shows what a call would send and its worst cost).
- Paid: `run.py split|continuity|episode|repair|stage --yes --hypothesis "one change, one reason"` (`episode` and `stage`
  take `--scenes E01-S04,…`; `episode` takes `--cap 32000` for six scenes). Every paid call is refused when its worst case
  would pass the cap; answers are cached, so a repeated request is free. `run.py ledger` shows the spend.
- `.venv/Scripts/python.exe -m pytest tests/raphael/test_packet_input.py tests/raphael/test_lab_parity.py -q`.

**Rules the person set in this work**
- Ask before EVERY paid model call, with its worst-case cost. Explain a fix before making it when asked ("tell me first").
- The lab cap is $1.00 in all; $0.2725 is left. Raising it is the person's decision (`LAB_CAP_USD` in `paid.py`).
- Costs never reach the interface.

**Known pre-existing failures** (fail with and without this work; not caused by it): 5 in `tests/parity/test_parity.py`
(`canon_extract/model_cards`, `doc_ingest/embedding_down`, `doc_ingest/script_with_key`, `structure_build/prose_model`,
`structure_build/prose_model_rejected`), `tests/raphael/test_api.py` (2), `tests/raphael/test_checks.py` (1, cap `[1]`),
`tests/raphael/test_removal.py` (1).

**Practical notes**
- A long paid call (six scenes) can pass the 2-minute tool timeout: run it in the background; the cache makes a re-run of
  finished calls free.
- When writing Python through a shell heredoc, `\n` escapes inside a Python string written to a file can turn into real
  newlines (and `\0` into a NUL byte). Use the file tools for code with escapes, or `chr(10)`.
- The lab imports the product (`hiru_ai.agents.stager.schema`, `contracts.raphael.*`); a script run directly needs
  `sys.path[:0] = ["lab", "src", "src/libs"]` (Windows uses `;` in `PYTHONPATH`).

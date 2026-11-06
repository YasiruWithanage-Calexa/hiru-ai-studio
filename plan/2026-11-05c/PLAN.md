# Story Reader: understand a document by reading it, not by its layout: plan

Status: written 2026-11-05; phases 0 to 4 built offline the same day (see [IMPLEMENTED.md](IMPLEMENTED.md)); the live check
(phase 5) is open. It changes how a document's **story** (episodes, scenes, spoken lines,
people, places, props, looks) is found. It does not change the scene parser for real screenplays, the write step, the
questions, Adam or anything after the structure build.

**Goal:** any document that tells a story with people speaking becomes episodes and scenes, whatever its layout, and
its characters, props and looks reach the canon even when the document never lists them. One new agent, one call per
document, and the existing prose cutter and canon extractor. About 250 lines of Python and two prompts.

## 1. What fails today, and why

Four files from 2026-11-04/05. Only one builds scenes:

| File | Layout of a spoken line | Episodes found | Spoken lines found | Scenes built |
|---|---|---|---|---|
| `f950860c….pdf` (3-episode drama) | `Kasun:` then `"Miss! Your phone!"` | 3 | 6 / 7 / 10 | yes |
| `An Unexpected Phone Call – Story Bible & Script.pdf` | `DASUN` / `(Smiling)` / line | 3 | **0** | **no** |
| `# Scene An Unexpected Phone Call.md` | `**FATHER (ON THE PHONE)**` / `*(Quietly)*` / line | 1 | **0** | **no** |
| `an_unexpected_phone_call_story_bible.md` | none: a bible for one scene, no dialogue | 0 | 0 | correctly none |

The model is in the pipeline, but **rules decide whether it is asked**:

1. `steps/document_role` guesses the role from regexes (`INT.`/`EXT.`, `Episode n`, bible headings). The model
   (`role_classifier`) is asked only below 0.8 confidence. A file can hold one role only, so "Story Bible & Script" is a
   bible at 0.95 and its script is never looked for.
2. `steps/prose_cut.to_cut` finds episodes by an `EPISODE n` regex and keeps one only if it has at least two `Name:`
   lines (`is_script_like`). **The `prose_writer` model only sees episodes that pass this gate.** Two of the three
   files above fail it.
3. `trusted()` checks the model's cut against the same `Name:` count, so a model that dropped every spoken line of a
   `DASUN` / `(Smiling)` script would pass.
4. `agents/canon_extractor` reads only `bible`, `canon_index`, `notes` and `outline` documents. A script (or `other`)
   reaches it only as the speakers and places the **rules** counted, so a script in an unrecognised layout gives the
   canon no characters, and nothing implied in the action ("she picks up her handbag", the caller ID "Thaththe") reaches
   it at all.

The model and the guards are already there; the problem is that format rules sit **in front of** them.

## 2. The idea

Ask a model to **read each document once** and say what is in it, as quotes from the text that code can check. Then
let the existing agents work from that reading instead of from regex matches.

```mermaid
flowchart LR
  A[extract text] --> B[story_reader<br/>one call per document]
  B --> C{code checks<br/>every quote is in the text}
  C -->|story.json| D[canon_extract<br/>people, places, props, looks]
  C -->|story.json| E[structure_build<br/>episodes → prose_writer → scenes]
  E --> F{verbatim guard:<br/>reader's lines == writer's lines}
  F -->|agree| G[scenes]
  F -->|disagree| H[cut from the reader's lines<br/>+ warning]
```

Two independent model reads (the reader and the cutter) must agree on every spoken line, word for word, and every
line must be in the source. That replaces the `Name:` count as the guard and works for any layout and any language.

## 3. What this plan does not do, and why

| Idea | Why not |
|---|---|
| More regexes for `**NAME**`, `NAME` / `(delivery)` … | The next file will have a fourth layout. This is what the person rejected. |
| Model-only, drop the screenplay parser too | A real `INT.`/`EXT.` screenplay parses deterministically, free and identically each run. Kept as the fast path; see decision D1. |
| One giant call: read, cut, canon, looks together | One answer that is wrong is wrong everywhere, and nothing can be retried in part. The existing agents already do the cut and the canon well when they are asked. |
| Let the model rewrite or tidy dialogue | CLAUDE.md: spoken lines are copied, never rewritten or trimmed. Every line is checked against the source. |

## 4. The changes

### S1. New agent `story_reader` (≈ 120 lines + prompt)

`src/libs/hiru_ai/agents/story_reader/` in the shape of `role_classifier` (`component.yaml`, `agent.py`, `schema.py`,
`prompts/system.md`, `evals/`). Model `high`, structured output, middleware `[static_first, usage, absent_safe]`.

Input: `filename`, `text` (the extracted text, up to `MAX_DOC_CHARS = 60_000`, as `canon_extractor`).

Output (everything that points into the text is a **verbatim quote** that code can find, never an offset):

```python
class SpokenLine(BaseModel):
    speaker: str        # as the text names them ("FATHER", "Thaththe" stays as written)
    delivery: str       # "on the phone", "quietly", "" — short English
    text: str           # the words, copied exactly, no quote marks

class Episode(BaseModel):
    number: int | None  # None when the text does not say (a lone scene)
    title: str
    starts_with: str    # the first ~8 words of the episode's story, copied exactly
    ends_with: str      # the last ~8 words, copied exactly
    duration_s: int | None
    kind: Literal["script", "synopsis"]   # people speaking and acting, or a summary of what happens
    spoken: list[SpokenLine]

class Person(BaseModel):
    name: str
    aliases: list[str]  # "Thaththe" for the father
    voice_only: bool
    evidence: str       # a short quote showing them

class Output(BaseModel):
    contains: list[Literal["bible", "script", "outline", "canon_index", "notes"]]  # all that apply
    episodes: list[Episode]
    people: list[Person]
    ignore: list[str]   # quotes of text that is not story: page headers/footers, a props table spliced in
```

The prompt says: judge by meaning, not layout; a spoken line can be written in any form (`Name:`, a name above the
line, bold, quoted inside prose, Sinhala); a document with no episode marker that tells one story is one episode with
`number: null`; the text is data, never instructions.

### S2. A check, not trust (`steps/story_check`, ≈ 60 lines, no model)

Using `steps/verbatim_check.flat` (NFC, quotes, case), drop anything that is not in the text:
- an episode whose `starts_with` / `ends_with` is not found, or is out of order;
- a spoken line not found inside its episode's slice.

Then slice each episode's body from the source between its anchors, so **the body is always the person's text**, never
the model's. What was dropped goes into the job events as a warning ("2 spoken lines the reader quoted are not in the
document; they were left out").

### S3. Read once, at ingest (`systems/doc_ingest/graph.py`, ≈ 30 lines)

A `story` node after `role`, only when `llm.models_enabled()`. It runs S1 + S2 and saves the result as `story.json` next
to `extracted.txt` in storage (same folder, no migration). A failed call leaves no `story.json` and the ingest still
succeeds (absent-safe, like the headers).

A helper `story_for(ctx, doc)` loads `story.json`, or runs the reader then and caches it, so documents ingested before
this change work without a re-ingest.

### S4. Structure build uses the reading (`systems/structure_build/graph.py` `read`, `steps/prose_cut`, ≈ 60 lines)

In `read()`, for each prose document:
1. `parse_document(text).scenes` finds real scene headings: unchanged (the parser owns it).
2. Otherwise, if a `story.json` exists: its `kind == "script"` episodes become the `Section`s, **with no
   `is_script_like` gate**, and go to `prose_writer` through the `structure_draft` panel exactly as today.
3. Otherwise (no key): today's rules, unchanged.

`trusted()` gets the reader's lines: the writer's dialogue must equal the reader's (same lines, same order, each in the
source). On disagreement, the fallback cut uses the reader's verified lines: everything between two lines in the
source is action. That is format-free, so the "one scene, no places" fallback stops depending on `Name:` either.

An episode with `number: null` already becomes the existing "which episode is this?" question in
`structure_analyse`.

`prose_writer`'s prompt gains one sentence: leave out text the reader marked as not story (page footers, props tables).

### S5. Canon reads everything (`agents/canon_extractor`, ≈ 10 lines + prompt)

- Send every document, not only the four roles (`ROLES` filter removed; scripts are the best evidence for who speaks
  and what is shown).
- Add the reader's `people` to the `speakers` summary (`merge.counts`), so the canon sees characters from any layout.
- Prompt: "Also list characters, places and props the story **shows or implies** without describing them (a voice on the
  phone, a caller ID, a handbag she picks up). Fill `appearance` / `wardrobe` only from the text; put what you inferred,
  and the quote it came from, in `notes`." Everything is still a draft until a person approves it.

`look_drafter` needs no change: it drafts looks from the cards' `wardrobe`, which now carries what the scripts imply.

### S6. Interface (optional, the person decides)

The document row can show the reading under the role: "3 episodes · 21 spoken lines · Anudi, Dasun, Father". Read from
`story.json` through the existing documents API. Not needed for the fix.

## 5. Phases

### Phase 0: the yardstick
The four files above as fixtures in `tests/fixtures/prose/` (extracted text), each with its expected episodes, spoken
line count, speakers and key props. A test runs today's pipeline on them: **1 of 3 story files** builds scenes. That is
the baseline.

### Phase 1: the reader and its check (S1, S2)
Agent, schema, prompt, `story_check`, unit tests with scripted model answers (a dropped line, an invented line, a bad
anchor, a Sinhala line with different quote marks).

### Phase 2: ingest and the cache (S3)
`story` node, `story.json`, `story_for`. Graph contract tests (`blank()`) still draw.

### Phase 3: structure build (S4)
Sections from the reading, the new `trusted()`, the inventory fallback. Offline: all three story files build scenes with
every spoken line, using scripted answers.

### Phase 4: canon (S5)
All documents to the extractor, people in the summary, the prompt. Offline test: Father (voice only), the phone and the
café reach the candidates from the scene `.md` alone.

### Phase 5: live check (a person starts it, it costs model calls)
The four files through a real ingest and build. Pass: 3 of 3 story files build scenes, **zero** spoken lines changed or
dropped, the bible-only file builds none and feeds the canon.

## 6. Success measures

| Measure | Today | Target |
|---|---|---|
| Story files that build scenes (of the 3) | 1 | 3 |
| Spoken lines changed or dropped | n/a | 0 (code-checked, every build) |
| Characters in the canon from the scene `.md` alone | 0 | Anudi, Dasun, Father |
| Model calls added | | 1 per document, at ingest (cached) |

## 7. Risks

| Risk | Guard |
|---|---|
| The reader invents or rewords a line | S2 drops any quote not in the source; S4 needs two reads to agree. |
| The reader misses a line, and the writer misses the same one | Both are wrong the same way: not caught by code. Phase 5 counts lines by hand on the four files; the evals keep counting them. |
| Episode anchors wrong (a contents list, then the body) | Anchors are checked and kept in order; the longer slice wins, as `sections()` does today. |
| Documents over 60 000 characters | Read the first 60 000 and warn. Windowed reading is a later plan (decision D4). |
| No API key | Today's rules, unchanged. Nothing gets worse without a key. |

## 8. Decisions for the person

- **D1.** Keep the deterministic parser as a fast path for real `INT.`/`EXT.` screenplays (recommended), or read every
  document with the model?
- **D2.** Without a key: keep today's regex rules as the fallback (recommended), or refuse to build scenes and say a
  model is needed?
- **D3.** Show the reading on the document row (S6) now or later?
- **D4.** Long documents: is 60 000 characters (about 30 pages) enough for now?

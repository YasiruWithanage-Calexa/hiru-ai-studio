# The document reader: a whole PDF to the model, one format back: plan

The person asked (2026-11-06): the shot planners work well, but what the system takes from the uploaded PDFs (the
story bible and the scripts) is poor. Dialogue, canon, looks and times are not found correctly. Send the whole PDF to
the model, in one or two calls, and get back a format the system understands.

This plan adds that reader. The output keeps the parser's shape (`contracts.screenplay.ParsedDocument`) and the canon
extractor's candidates, so the structure build, the canon write, the questions and the shot planners after it do not
change. The rules stay as the absent-safe path.

## 1. What we found (the two files the person sent)

`ekama_sakshiya_screenplay.pdf` (4 pages, English action, romanised Sinhala dialogue) and
`AVASANA_SANGNAWA_SEASON_01_SCREENPLAY_SI.pdf` (217 pages, 30 episodes, Sinhala), read with the code we ship today
(`doc_ingest/engine/extract.py` → `contracts.screenplay.parse_document`):

| File | What went wrong | Why |
|---|---|---|
| Ekama | **0 dialogue lines** in all 9 scenes | Dialogue is written `ARUNI - Dinu... oyata meka ahenne nadda?` on one line. `CHARACTER_CUE` wants a capital-letter name alone on its line, and `_COLON_LINE` wants a colon. |
| Ekama | **Every time of day empty**, location wrong (`EXT. MAHAWEWA CANAL`), length `1 MINUTE` lost | The heading is `SCENE 01 - EXT. MAHAWEWA CANAL - DAWN - 1 MINUTE`. `parse_heading` does not handle a `SCENE nn -` prefix, a `FLASHBACK -` part or a length. |
| Ekama | Canon missed, page header taken as a speaker (`EKAMA SAKSHIYA`) | The characters are a table (`Dinu` / `30, Colombo cash-transport driver…`), not `C01 …` or `### …`. Repeated page headers are not removed. |
| Avasana | **The text inside the PDF is wrong.** `කොළඹ` comes out as `බෙක7ළඹ`, `ා` as `7` | The file was made with Apple's Sinhala Sangam MN. Its ToUnicode map stores the split vowel signs wrongly. pypdf reads what the file says, and no parser or text-only model can read it back. |
| Avasana | 33 episodes found, not 30. Sinhala speaker names (`නිශා (V.O.)`) never match a cue | The episode index and headers look like episode headings. Sinhala has no capital letters. |
| Avasana | `LEGACY_FONT_WARNING` **did not fire** | The text has Sinhala code points, but they are in the wrong order. The warning only looks for none at all. |
| Avasana | The RAG index and production memory hold the same corrupted text | `doc_ingest` chunks and embeds the text layer. Search, the director and `memory_reader` read nonsense too. |

Other facts:
- The canon model call (`canon_extract/engine/model.py`) cuts each document at 60,000 characters, never reads the
  scripts' text (only the list of speakers the rules found), and the rules decide which entities exist.
- Looks are not read from the documents. `structure_build/engine/looks.py` proposes them from the canon cards.
- Every service's `runtime/llm.py` uses Chat Completions with strict JSON schema. Chat Completions accepts a PDF as
  a `file` content part (base64). For vision models, OpenAI gives the model each page's extracted text AND an image of
  the page. **Limits to verify in Phase 0**: pages and bytes per request (believed ~100 pages / 32 MB), and the token
  cost of a page image.

## 2. Decisions

The person decided (2026-11-06):
1. **Send the document itself to the model** and get back one format of our own that code maps into the system.

This plan takes these decisions. The person can overturn any of them (§10):

2. **Text when the text is good, pages when it is not.** Every PDF's text layer is scored (§4.1). If the text is clean,
   the model gets the text with numbered lines (cheaper, and code can check every spoken line word for word). If the
   text is corrupted (Avasana), the model gets the PDF pages and reads them from the images.
3. **Pieces, not one call for 217 pages.** One **canon call** per document that holds a cast list or bible, then one
   **episode call** per episode. Every episode call gets the canon call's list, so speakers map to the same people.
   A 4-page file like Ekama is ONE call that returns both.
4. **Read once, at ingest, and store the result.** The reader runs in `doc_ingest` for `script`, `bible`,
   `canon_index` and `outline` documents. The result is stored next to the text (`documents.reading_path`, a JSON
   file in the `documents` bucket). A rebuild reads the stored result and makes no model call. "Read again" is a
   button on the document (re-ingest).
5. **The Hiru AI pattern (ADR 0010).** ONE author call per unit, code checks it, the same model gets a patch call
   showing only the problems it must fix, at most twice, then whatever is left is reported on the job's events.
   No second agent.
6. **Dialogue is never invented or translated.** With good text, every spoken line must be found in the source text
   (normalised: NFC, ZWJ/ZWNJ kept, whitespace folded) or the check fails. With page images, nothing can be checked
   word for word. Those scenes carry `read_from: "pages"`, and the interface shows "Dialogue read from page images:
   check it" until a person confirms the scene.
7. **Only what is written.** The canon fields and the looks are the documents' words, each with a short `quote`. With
   good text, code drops any field whose quote is not in the text (the same rule as `steps/memory_check`). The looks
   model in `looks.py` still proposes looks where the documents say nothing, labelled as proposals.
8. **A corrected text for search too.** When the reader read a document from page images, it also returns a clean
   transcription per page. That replaces the corrupted text layer for chunking, embedding and production memory, so
   search and the director stop reading nonsense. The original text is kept.
9. **The rules remain.** No key, or a call that fails its checks twice: the rule parser runs as today, and the job
   says why. Ekama-style headings (`SCENE nn - EXT. … - DAWN - 1 MINUTE`), `NAME - line` dialogue and repeated page
   headers are added to the rules as well (cheap, and the fallback gets better).

## 3. The format (`contracts/reading.py` is taken: the module is `contracts/doc_read.py`)

The model returns this (strict JSON schema). Code maps it to `ParsedDocument` and to canon candidates.

```
DocRead
  source: "text" | "pages"
  canon:
    characters[]: name, aliases[], code, core, age, gender, appearance, wardrobe, voice, accent,
                  per_episode[] {episode, note}, quote
    locations[]:  name, aliases[], code, look, quote
    props[]:      name, aliases[], code, details, quote
  episodes[]:
    number, title, stated_runtime ("45 MIN", "")
    scenes[]:
      number ("01", "1")            as written
      int_ext: INT | EXT | INT/EXT | ""
      location, sub_location        "Mahawewa canal", ""
      time_of_day                   closed list (contracts.screenplay TIMES + Sinhala), "" when not stated
      clock ("05:08", "")           a time on the clock when the heading gives one
      stated_seconds                "1 MINUTE" → 60, "1.5 MINUTES" → 90, 0 when not stated
      flashback: bool
      lines: [L0412, L0466]         text mode only: the source lines this scene covers
      blocks[]:
        kind: action | dialogue | transition | sound
        speaker                     the canon name the cue refers to ("Aruni"), "" for action
        cue                         the cue as written ("ARUNI", "නිශා")
        delivery                    "V.O.", "softly", ""
        text                        the words as written; action as written
  transcription[]: {page, text}     pages mode only (decision 8)
```

In text mode, a block also carries `src: [first_line, last_line]`. Code checks that `text` is the source text of those
lines (whitespace folded), so a dropped or reworded line is found exactly.

## 4. How it runs

### 4.1 Is the text good? (`doc_ingest/engine/text_quality.py`, code)

Per page: the share of Sinhala letters that sit next to a digit or an ASCII symbol inside a word (`ක7ළ`, `බෙ` before
a consonant), and the share of words a Sinhala spelling check knows. Above a threshold, the page is `corrupt`. A
document with ≥ 20% corrupt pages goes to the reader as pages. The thresholds come from the two files above plus the
clean fixtures we already have. `LEGACY_FONT_WARNING` is widened to say what we now know (wrong order, not only no
Sinhala).

### 4.2 Pieces

- Find the episode boundaries from the text layer: `EPISODE nn`, `SEASON ONE EPISODE nn` and the Latin parts survive
  corruption (Avasana's headers are Latin). No boundaries found: fixed windows of N pages with one page of overlap,
  and the model reports which episode each scene belongs to. Code joins them.
- The pages before the first episode (title, index, cast list) go to the canon call.
- For pages mode, pypdf writes each piece as its own small PDF in memory. No new dependency.

### 4.3 Calls

| Call | Input | Tier | Output |
|---|---|---|---|
| `reader_canon` | the front pages + the bible / canon index | `reader` | `canon` |
| `reader_episode` | one episode's text or pages + the canon list (names, aliases, codes only) | `reader` | `episodes[0]` (+ `transcription`) |
| `reader_repair` | the same input + the author's answer + the exact problems | `reader` | a patch (`replace` blocks by path) |

Episode calls run in parallel (`WORKERS = 4`, like `prose.py`). The static prompt comes first and is byte-identical
across calls (cache). The document is data: wrapped in `<document>` tags, labelled, never in the system message.

### 4.4 Checks (`contracts/doc_read_checks.py`, code)

- Every episode the index or headings name is present, in order, with at least one scene. No extra episodes.
- Every scene has a location, and a `time_of_day` when its heading has one (the heading's words must contain it).
- Every dialogue block's `speaker` is in the canon list or is new. A new speaker is added as a supporting character
  and reported. A page header or title is never a speaker (code drops cues equal to a repeated page header).
- Text mode: every block's `text` matches its `src` lines. Scenes' `lines` ranges cover the episode's script lines in
  order with no overlaps. Every source line is in a scene, or is a page header or footer.
- Pages mode: the Latin parts of the text layer (headings, `CUT TO:`, clock times, English words) appear in the answer
  in the same order. This catches a skipped page or scene even when the Sinhala cannot be checked.
- `stated_seconds` sum against `stated_runtime` is reported, never fixed (CLAUDE.md: overruns are reported).

### 4.5 Where it plugs in

- `doc_ingest`: after role detection, for the four roles, `reader.run(...)` writes `reading_path` and, in pages mode,
  replaces the text used for chunking (decision 8).
- `structure_build/engine/analyse.py`: when a document has a reading, `ParsedDocument` comes from
  `doc_read.to_parsed(reading)` instead of `parse_document(text)`. `prose.convert` is skipped for it. Everything
  after (`match_location`, `match_speaker`, the questions, `write`) is unchanged. `stated_seconds` becomes the scene's
  envelope where the script gives one.
- `canon_extract/engine/pipeline.py`: when readings exist, their canon is the candidate list, and the rules' canon is
  merged in only for codes. `model.extract` and `model.dedupe` are skipped (the reader already mapped cues to names).
- `hiru_ai`: the parts are a `reader/` group (`agents/reader/reader_canon`, `reader_episode`, `reader_repair`,
  `steps/reader/reader_checks`, `contracts/reader/`, `tests/reader/`, `tests/eval/reader/`, `docs/reader/`), ids start
  `reader_`. The `doc_ingest` system calls them under `AI_ENGINE=graph`. The legacy service code gets the same reader
  so `tests/parity` holds.
- `runtime/llm.py` (doc_ingest, its own copy): `json(...)` takes an optional `files=[(name, bytes)]`, sent as `file`
  content parts. Usage rows as today.

## 5. Accuracy test (`tests/eval/reader/`, `scripts/eval_reader.py`)

Gold: Ekama in full and three Avasana episodes (01, 15, 30), marked by hand: scenes (heading fields, time, length),
every dialogue line (speaker, words), canon (people, places, props). The gold Sinhala is typed by a person, not the
model. Scores: scene count, heading fields, time-of-day, dialogue recall, speaker accuracy, word accuracy (character
error rate on Sinhala), canon recall. Baseline: the rules today. Offline tests replay recorded answers. The live run
is `scripts/eval_reader.py --yes` and is a person's to run. The gold is a draft until a Hiru writer checks it.

## 6. Phases

| Phase | Work | Offline? |
|---|---|---|
| 0 | Verify OpenAI's PDF limits and page-image token cost on one Ekama call (`scripts/reader_probe.py --yes`, a person's). Build the gold for Ekama. | probe: live |
| 1 | `contracts/doc_read.py` (format, `to_parsed`, `to_candidates`), `doc_read_checks.py`, text-quality scoring, episode splitting. Rules fixes from decision 9. Tests on both files. | yes |
| 2 | The reader parts (`reader_canon`, `reader_episode`, `reader_repair`), the `files` path in `llm.py`, text and pages modes, fake-client tests for both paths and for no key. | yes |
| 3 | Plug in: `doc_ingest` stores the reading (+ transcription), `structure_build` and `canon_extract` read it. Schema change (`documents.reading_path`, `documents.read_from`) as a migration and in the schema v15 pair (v14 is still unreleased: fold it into the v14 pair instead if the person prefers). | yes |
| 4 | Interface: "Dialogue read from page images: check it" on scenes with `read_from: "pages"`, a confirm button, "Read again" on a document. | yes |
| 5 | Live: `scripts/eval_reader.py --yes` on the gold, against the rules. The default (reader on for every production) is a person's. | live |

Costs appear in the probe's and the eval's output and in `IMPLEMENTED.md` only, never in the interface.

## 7. What does not change

The shot planners (`script_split`, Adam, David, Jonathan), staging, reading, timing, the canon write and its locking,
the questions and their answers. Dialogue stays in the language it was written in (romanised Sinhala stays romanised).

## 8. Risks

- **Misread Sinhala from page images.** A model reading an image can drop a letter or "tidy" a spelling, and there is
  no clean text to check it against. Decision 6 marks those scenes for a person. The real fix is a correct file:
  writers export with Unicode text (Word or Google Docs with Noto Sans Sinhala or Iskoola Pota), and the job's warning
  says so.
- **Cost of 217 pages as images.** Measured in Phase 0. Pages mode is used only for corrupt documents.
- **Long episodes.** A 45-minute Sinhala episode's dialogue is large output. One episode per call keeps it inside the
  output limit. A cut answer (`finish_reason == "length"`) splits the episode in two at a scene boundary and runs again.

## 9. Not in this plan

OCR for scanned PDFs (still rejected at upload), Word (.docx) upload, and repairing corrupted text by reversing the
font's mapping in code. That last one is possible for Sinhala Sangam MN, but it is one font's bug and fragile.

## 10. Open questions for the person

1. **The tier.** `reader` at the author model, effort `medium`? Reading is less creative than planning.
2. **Decision 8.** Replace the corrupted text for search and memory with the model's transcription? Yes is better
   search. The risk is that search shows the model's spelling.
3. **Schema.** Fold the two `documents` columns into the unreleased v14 pair, or start v15?
4. **Gold.** Who types the Sinhala gold for three Avasana episodes?

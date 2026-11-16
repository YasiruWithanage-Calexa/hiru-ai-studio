# LLM reader lab (2026-11-15)

The person's rule: **every fact in an uploaded document is read by the model; code never pattern-matches the input.**
Code may check the model's answers (our schema), and gates stop the build before credits are wasted.

Decisions (2026-11-15): a range gives its TOP ("25–30 s" → 30 s); any scene's problem holds the WHOLE build; directors,
editors and similar roles answer "Needs input"; no model available = no upload.

    python lab/llm_reader/make_inputs.py                       # free: documents + expected answers
    python lab/llm_reader/run.py dry  [run]                    # free
    python lab/llm_reader/run.py live <run> --yes [--only A,B] # PAID, cap $2.00 (runs/ledger.csv)

## The flow

| step | who | what | gate |
|---|---|---|---|
| probe | model, low effort, ~$0.012 | kind of document; is the LETTER text damaged (layout faults do not count) | Stop: not a story · Stop: damaged and no PDF |
| transcribe | model reads the PDF pages, low, ~$0.045 | one entry per printed line, Sinhala in correct Unicode | code checks: every English word of the text layer kept in order (≥ 0.98), every Sinhala vowel sign after a consonant; one retry, then Stop |
| read | model, medium, ~$0.065 | episodes; scenes with word-level START and END quotes; title; place (back-references resolved); stated length; people with roles; skipped lines | code checks every quote, that every story word is in exactly one scene, numbering, sane seconds; one repair |
| gates | code over the answer | | Needs input: declared ≠ found episodes, no lead, any scene without length / place / title (holds the whole build). Warn: dialogue longer than the stated length |

Files: `schema.py` (Probe, Transcription, Answer), `probe.md`, `transcribe.md`, `system.md` (the reader), `checks.py`,
`run.py`, `make_inputs.py` (A, B = the person's PDFs through the PRODUCT extractor; C–G made from B's clean transcription).

## Result: run4, all seven as expected; lab spent $1.01 of $2.00

| doc | layout | verdict | score |
|---|---|---|---|
| A | v1 PDF, damaged Sinhala, "Estimated Duration: 25–30 seconds" | go (read from printed pages) | 11/11 |
| B | v2 PDF, damaged Sinhala, "Duration: 0.46 minutes" | go (read from printed pages) | 11/11 |
| C | "PART ONE", "1. PLACE [approx. 28 sec]", title below, CUES, page headers | go | 11/11 |
| D | no lengths except "about half a minute" in a sentence | needs input: 12 of 13 scenes | 11/11 |
| E | title page + cast list + budget | stop at the probe ($0.0025) | 3/3 |
| F | "...daughter.SCENE 04 —" glued | go: S03 ends at "daughter." and S04 starts on the same line | 11/11 |
| G | v2's damaged text, no PDF | stop at Gate 0 | 3/3 |

Score rows: kind, verdict, damaged text seen, episodes, scenes, titles, clean headings, lengths, leads (Kasun, Anudi),
crowds are groups, "Same workspace" resolved to Kasun's small workspace.

Per 13-scene document: about $0.13 with damaged text (probe + 2 transcription calls + read), $0.08 with clean text.

## Findings and what fixed them

1. Damaged Sinhala, missed by `doc_read_quality.quality()`: the probe sees it; the printed pages are transcribed; code
   checks the transcription. The text layer had 101 words with a vowel sign before its consonant; the transcription 0.
2. The glue in the product comes after extraction: the reader's output is now checked word by word.
3. Boundaries inside a line: scenes carry start AND end quotes; `checks.coverage` proves every story word is in exactly
   one scene; the repair message lets the model keep a right answer when a check is wrong (run1's forced "fix").
4. The probe first called a glued heading "damage" (run3, F stopped): only LETTER damage counts now.
5. `runs/run4/sinhala_review.md`: 59 Sinhala lines differ from the text layer; 33 are the same letters reordered; 26 add
   letters the layer lost (ගේ, ණේ, ඩේ, දේ, ෝ, රු, ්‍ය). SETTLED by finding 6: all correct.

## Finding 6 (run5): the Sinhala was never damaged in the file; our extractor read the wrong part of it

The PDFs are made by headless Chrome (Skia). Each Sinhala cluster is drawn as glyphs in visual order AND wrapped in a
marked-content span carrying the true Unicode: `/Span <</ActualText <FEFF0D9C0DDA>>> BDC … EMC` = "ගේ" (43 spans on page 3
alone). pypdf's `extract_text()` (today's `doc_ingest.engine.extract`) ignores /ActualText, so vowel signs come first and
ligature letters vanish; Claude and ChatGPT honour it, which is why they read these PDFs correctly.

`actualtext.py` walks the content stream with pypdf's own font maps and writes each span's ActualText in place of its
glyphs. Free, no model, no meaning read: it decodes the file. On both PDFs: 301 lines, the same English, 0 misplaced vowel
signs (pypdf: 101), and the 313 Sinhala words are IDENTICAL to the model's page transcription; the reading request was
byte-identical, so it came from the cache. run5 (A, B via actualtext; G keeps today's damaged pypdf text): 7/7, $1.11.

PDF engine chosen (2026-11-15): **poppler `pdftotext -enc UTF-8 -layout`** (GPL, run as a separate program; one apt line
in the backend Dockerfile). Tested in `python:3.12-slim` + Debian `poppler-utils` 25.03: both PDFs give lines and Sinhala
IDENTICAL to Xpdf 4.00 and to `actualtext.py` (301 lines, 313 Sinhala words, 0 misplaced signs). pypdfium2 (PDFium) was
rejected: right letters but spaces inserted inside Sinhala words ("ඔයා ගේ"), and it marks every space as generated.
Outputs and review files: `runs/readers/` (`sinhala_review_poppler.md`, `poppler_*.txt`, `xpdf_*.txt`).

So for the product: fix the extractor first (honour /ActualText: poppler); keep the probe's text-quality check as Gate 0 for a
text PDF that is still damaged (no ActualText, e.g. legacy FM fonts). Scanned PDFs stay rejected (the person's rule).

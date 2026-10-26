# Upstream: PromptMotion knowledge base

Copied from PromptMotion at commit `1d748dc` (2026-10-19). Indexed by
`scripts/ingest_knowledge.py` (corpus `craft` in `chunks`, and `craft_techniques`).

Two sources are NOT from PromptMotion: `cinematography/` and `craft/hiru-house-style.md` (below).

| Here | PromptMotion source |
|---|---|
| `craft/*.md` | `src/knowledge_base/vega/*.md` |
| `rules/*.md` | `src/knowledge_base/rules/sceen_rules/*.md` (the `.json` twins were not copied) |
| `guides/veo-3-1-prompting-guide.md` | `docs/engines/veo-3-1-prompting-guide.md` |
| `techniques/camera_shots.csv` | `docs/knowledge-base/camera_shots.csv` |

## Cinematography terms database (not PromptMotion)

`cinematography/*.csv` is the 629-term reference database supplied by the user as `files.zip`
(2026-10-26): 28 categories, 21 subcategories, 41 tags, 1,511 term-tag links, 107 relations. Each
term has a description, its emotional `effect`, a `use_case`, an `example_scene`, a `prompt_phrase`
for AI video tools, aliases, `complexity` and `is_ai_supported`. The zip's `schema.sql` (MySQL DDL)
was not copied: the data lives in `craft_techniques` (migration `*_cinematography_terms.sql`).

`scripts/cine_terms.py` loads it, and `scripts/ingest_knowledge.py` indexes it:

- **Merged with `techniques/camera_shots.csv`**, one row per technique. Where both name the same
  shot (35 of the 61) the row keeps the legacy `definition`, `use_case`, `abbreviation` and
  `example_film` (hand-written feeling-first, and the eval thresholds were calibrated on them)
  and gains the terms database's fields. The other 26 legacy rows stay as they were.
- **Short-form categories are not indexed** (`video_format`, `ad_structure`, `social_technique`,
  79 terms): they teach hooks, ad formulas and platform formats, and Hiru makes television. They stay
  in the CSVs; `--include-short-form` indexes them.
- Dangling tag or relation ids fail the load; they are never dropped silently.

## Divergences

- `craft/hiru-house-style.md` is Hiru's own (written from the rules in `contracts/veo.py` and
  `contracts/timing.py`, not from PromptMotion). It does NOT yet cover television pacing, scene
  length or broadcast conventions: those need Hiru's own material, not a guess.
- None in the PromptMotion files yet. Files are verbatim, including references to PromptMotion and its
  short-form framing (scroll-stop hooks, platform beats). Hiru-specific craft notes
  (television drama pacing, Sinhala dialogue, broadcast) should be added as new files in
  `craft/` rather than by editing these, so upstream updates stay easy to diff.
- Not copied: PromptMotion's genre YAMLs (removed upstream on purpose: they teach the fixed
  8-second grid) and `nano-banana-prompting-guide.md` (Gemini image model; Hiru uses OpenAI).

To pull upstream changes: diff the paths above against a newer PromptMotion commit, copy
what applies, update the commit here, re-run `scripts/ingest_knowledge.py` and
`scripts/eval_retrieval.py`.

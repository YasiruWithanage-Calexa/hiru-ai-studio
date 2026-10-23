# Upstream: PromptMotion knowledge base

Copied from PromptMotion at commit `1d748dc` (2026-10-19). Indexed by
`scripts/ingest_knowledge.py` (corpus `craft` in `chunks`, and `craft_techniques`).

| Here | PromptMotion source |
|---|---|
| `craft/*.md` | `src/knowledge_base/vega/*.md` |
| `rules/*.md` | `src/knowledge_base/rules/sceen_rules/*.md` (the `.json` twins were not copied) |
| `guides/veo-3-1-prompting-guide.md` | `docs/engines/veo-3-1-prompting-guide.md` |
| `techniques/camera_shots.csv` | `docs/knowledge-base/camera_shots.csv` |

## Divergences

- None in content yet. Files are verbatim, including references to PromptMotion and its
  short-form framing (scroll-stop hooks, platform beats). Hiru-specific craft notes
  (television drama pacing, Sinhala dialogue, broadcast) should be added as new files in
  `craft/` rather than by editing these, so upstream updates stay easy to diff.
- Not copied: PromptMotion's genre YAMLs (removed upstream on purpose: they teach the fixed
  8-second grid) and `nano-banana-prompting-guide.md` (Gemini image model; Hiru uses OpenAI).

To pull upstream changes: diff the paths above against a newer PromptMotion commit, copy
what applies, update the commit here, re-run `scripts/ingest_knowledge.py` and
`scripts/eval_retrieval.py`.

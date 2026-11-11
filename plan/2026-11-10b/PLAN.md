# Safe depiction: death, crime and injury without provider refusals (plan/2026-11-10b)

## The problem

Google's video models (Veo 3.1, Omni Flash) decline prompts that NAME death or violence ("a dead man on the floor"),
even when the picture asked for is non-graphic. Hiru's dramas need sad and crime scenes: a still figure on the ground,
no blood, no stabbing on screen. A refusal blocks the shot and wastes the person's time.

## The decision (the person's, 2026-11-10)

Show these moments the way broadcast television does, and make it impossible for a listed word to reach a provider:

1. **Gate (the guarantee).** Code scans the final video prompt and the first-frame prompt. A listed word in the
   DESCRIPTION stops the request before anything is spent, with the word and what to write instead. Nothing is
   rewritten automatically (a blind swap breaks meaning: "a dead battery", "body language").
2. **Spoken lines are the script's.** A listed word inside a quoted (spoken) line is an advisory, never a block, and the
   line is never changed (the dialogue rule).
3. **Teach the writers.** One line, word for word, in the system prompt of every agent that writes what a shot shows.
4. **Knowledge base.** `rules/safe_depiction.md`: the longer guidance with before/after examples.
5. **Refusal hint.** A provider's refusal message ends with the likely cause and the way out.

Not in scope: any way of disguising a refused picture (code words, misspellings). It breaks the provider's terms and
can close the account. The answer to a refusal is a different picture.

## Where

| Piece | File |
|---|---|
| Word list, scan, messages, prompt line | `src/libs/contracts/safe_depiction.py` |
| Video gate (API plan, "Make again", the render function's backstop) | `contracts/video_gen.py` `validate_render` (block), `check_render` (spoken advisory) |
| Frame gate, both engines | `services/frame_render/engine/pipeline.py`, `hiru_ai/systems/frame_render/graph.py` |
| Refusal hint | `video_render/engine/veo.py`, `omni.py`; `frame_render/engine/image.py`; `hiru_ai/adapters/images.py` |
| Prompt line | `shot_writer` + legacy `shot_producer/engine/shots.py`, `adam_take`, `adam_shot_designer`, `david_author`, `jonathan_author`, `jonathan_revise`, `zora_author`, `raphael_planner`, `raphael_cinematic`, `sable_agent` |
| Knowledge base | `hiru_ai/knowledge_bases/rules/sources/safe_depiction.md` (+ `component.yaml`) |

## Growing the list

A word goes into `TERMS` when a provider has declined it AND it has no common harmless use in a shot description. Each
pattern leaves out harmless phrases ("dead of night", "wound up", "dying light"). "shot", "body" and "gun" are not
listed on purpose. Every refusal is stored on its render or frame row (`status = refused`, `error`), which is where new
words are found.

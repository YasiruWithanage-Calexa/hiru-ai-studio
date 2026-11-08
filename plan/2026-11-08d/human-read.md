# DaVinci in plain words (plan/2026-11-08d)

Our planners today make a **finished edit**: one picture per moment, in order. Our post-production team is expert and
wants **raw material** instead, so they can cut it themselves.

DaVinci is a new shot planner that does this:

1. It first imagines **how the final scene should look** (the intended cut), so the shots serve a vision.
2. Then it plans **every clip needed to build that**: a wide master, close-ups of each person, reactions, details, plus
   extras like drone shots, crash zooms, B-roll and fillers. The same action is shot from several angles, with a second
   before and after it so the editor has room to cut.
3. Each clip says what it is (master, reaction, B-roll…), how important it is (must / should / nice) and gets a slate
   name like `12B-3`.

**How it works.** A director AI leads. It decides what to do next: hand a simple sequence to a cheaper helper, plan a
hard one itself, check the result, and fix only what failed. Plain code checks the rules (Veo clip lengths, continuity,
what Veo cannot film) and will not let it finish until they pass.

**Spending.** At most $5 of AI model tokens per scene. When the total reaches $5, it stops.

**Nothing changes** for Adam, David or Jonathan.

**First step:** a small test on one of your scenes. Your post team tries to cut what DaVinci made.

**Your decisions:** what to save if it stops at $5; which angles speak the dialogue; where to set the allowed camera
styles; coverage levels; storage; models; slate names (see PLAN.md §7).

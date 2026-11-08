# Raphael in plain words (plan/2026-11-08e)

Raphael is a new shot planner that makes the same thing as DaVinci: **raw material for our post-production team**. That
means a picture of how the final scene should look, then every clip needed to build it (wide shots, close-ups, reactions,
details, a few extras like a drone shot), each with a role, a priority (must / should / nice) and a slate name like `12B-3`.

**The difference: one AI, not a team.** In DaVinci a director AI hands work to cheaper helper AIs. In two test runs the
helpers did not see the whole scene and made mistakes (for example, putting the voice-only father on screen), and the
director spent its turns sending clips back one at a time. Neither run finished.

Raphael is a single strong AI that reads the whole scene and writes everything itself: the vision, the clips and each clip's
Veo description. After every change, plain code checks the rules (clip lengths, every line covered, nothing Veo cannot
film) and tells it what is wrong.

**Length.** Raphael aims for the scene's length as the script gives it: a 60 s scene gets about 60 s of clips. It may add
extra angles where the story needs them, but the total can never pass 1.5x the scene (60 s -> 90 s). That limit is hard: it
cannot finish over it. The extra room is allowed, not expected. It cannot finish until the checks pass.

**Spending.** At most $5 of AI model tokens per scene; it stops there.

**Nothing changes** for Adam, David, Jonathan or DaVinci.

**First step:** a small test on Episode 1, built for free first, then up to three paid runs (at most $5 in all), compared
with DaVinci and Jonathan. Then your post team tries to cut a small sample.

**Your decisions:** what to save if it stops early; the model; the turn limit (20); whether, if both work, only the better
of DaVinci and Raphael goes into the product (see PLAN.md §6).

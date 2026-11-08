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

**Two stages (added 2026-11-08 after the first test runs).** The first runs gave a good set of *must* shots, the shots the
scene cannot be cut without, but nothing cinematic. So Raphael now works in two steps. **Stage 1** (as tested) writes the
must shots. **Stage 2** is a second AI that reads that finished set and, on a few chosen moments only (where the story turns,
a line lands, a place first appears), adds *nice-to-have* cinematic shots: a detail close-up, a held reaction, a drone shot,
a slow reveal. Each one says which must shot it belongs with and how the editor blends it in (cut in and back, under the
dialogue, before or after the moment, or as a transition). Stage 2 cannot change the must shots, speaks no dialogue, adds at
most 2 shots to any one moment, and stays inside the 1.5x length limit. If stage 2 fails, the must shots are still there.

**Spending.** At most $5 of AI model tokens per scene; it stops there.

**Nothing changes** for Adam, David, Jonathan or DaVinci.

**First step:** a small test on Episode 1, built for free first, then up to three paid runs (at most $5 in all), compared
with DaVinci and Jonathan. Then your post team tries to cut a small sample.

**Your decisions:** what to save if it stops early; the model; the turn limit (20); whether, if both work, only the better
of DaVinci and Raphael goes into the product (see PLAN.md §6).

**After the tests (2026-11-08).** Both stages work. Stage 2 now looks at every moment, starting with the ones where the
story turns (the phone call, her leaving, the last line), and may add up to 3 cinematic shots to a moment. Phone close-ups
are allowed: the old "Veo cannot show screen text" rule is gone for Raphael. In the last test it added 8 shots, including a
close-up of the ringing phone, the empty street after she leaves and a shot under the final voice-over. Too many of them
were rain textures, so the next version asks for more variety (held reactions, a drone shot, transitions).

**You choose how much extra material.** The total length of all the clips is capped at a multiple of the scene's length,
and you pick it: 1.5x, 2x (the default), 2.5x or 3x. A 60 s scene at 2x can have up to 120 s of clips. You can set it for
the whole production, and change it for one scene when you plan it or press "More cinematic".

**Next:** Raphael is built into the product: its rules as code, the two AIs, storage, and a Raphael tab in the app with the
length choice. One optional full test run first (about $1.50 at most), then a live trial on one episode for the post team.


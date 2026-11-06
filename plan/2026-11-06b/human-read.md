# Jonathan in plain words (plan/2026-11-06b)

**What it is.** A new shot planner, a fourth choice next to the classic planner, Adam and David. It plans one scene at a time like a
film crew: first the treatment (what the scene is about, the colour plan, where everyone stands, the one image to remember), then
the sequences, then every shot with its lens, its camera move and the story reason it exists.

**Why.** In a blind read you scored the lab's plan 9, ChatGPT 8.5 and David today 6, and David's problem was that it was flat.
The lab found out what makes the difference and how to keep it steady on any scene, not just Episode 1.

**How it stays good.** The model writes a draft. Code checks it. If code finds a fault or a missed craft point, the model gets its
own draft back with those findings and corrects it, at most twice. Code, not the model, decides when it is good enough. In the lab
that took every scene to zero faults for about 20 cents a call.

**What it is not.** Not an agent that chooses its own steps. A few model calls in a fixed order, with code in between.

**How it is built.** Like David was built from Adam: its own folders, its own copy of the rules, independent of the other planners,
so any of them can be removed without breaking the rest. Nothing in David or Adam changes except a handful of one-line lists that
need to know the new name.

**What you do and what I do.**

| Me (offline, no model, no database) | You |
|---|---|
| The folders, the contracts, the checks, the prompt, the system, the API, the interface tab, the tests | Apply the migration to the hosted database |
| | Run a real scene and the gate (five scenes, three times, a Hiru director's blind read) |
| | Choose the default, and whether David is retired |

**Nothing about money appears in the app.** The cost numbers stay in the lab.

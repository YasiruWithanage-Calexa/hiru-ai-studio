# Sable, in plain words (plan/2026-11-08)

## What it is

Sable is a second chat beside Zora. **Zora edits a scene's plan. Sable knows the whole production** and answers, finds,
checks and explains:

- "What did we decide about Nimal's costume?"
- "Which scenes in episode 3 still have no shots?"
- "Does S04 in E1S2 overrun?"
- "What does the bible say about the temple at night?"
- "Why is the opening shot a wide?"

It can also **suggest** a change or "remember this rule", always as a card you accept. It never changes anything on its own.
When you ask it to edit a scene, it gives you a button that opens that scene in Zora with your request ready to send.

**Zora is not changed.** Sable is built beside it. No Zora file is edited, in the backend or the interface.

## What we found when we looked

- Zora has **no tools**. It is a careful pipeline built for one job: editing a Jonathan plan. Sable would be the
  first chat that actually *uses* tools.
- We already have **27 tools** built with strict rules (small answers, clear errors, scope that a model cannot change).
  Sable uses 21 of them and gets 3 new ones (a production overview, a scene finder, and "think harder").
- The "one agent with tools" engine already exists in our code. The old chat's question-answerer even has a tool version
  that was never switched on. Sable starts from it.

## How it chooses a model

It starts on an **average** model (fast, cheap). It moves to a **stronger** model only when needed, and only once per
message:

1. **Obvious cases, decided by simple rules before anything runs**: you ask it to compare, review a whole episode or think
   carefully, or you name many scenes. It starts strong.
2. **Sable asks for it**: while working, it can say "I need to think harder". From then on that message uses the strong
   model, which keeps everything already looked up.
3. **Code notices trouble**: lookups keep failing, it runs out of steps, or it is about to suggest a change card. The strong
   model finishes the job.

It never switches back down within a message. You never see costs or model names.

## Safety, same as everywhere else

- Dialogue is never written, tidied or translated by Sable. It only quotes lines exactly as stored.
- Facts from documents come with their source. "I couldn't find it" is allowed; guessing is not.
- It can only see the production you are in.
- No costs in the interface.

## How we build it

1. Collect 30 to 50 real questions (free).
2. Build the agent, the model switching and the new tools, all tested without calling any model (free).
3. **Small paid test, about $3, only with your yes**: the same questions three ways (average only, strong only, switching).
   You grade the answers without knowing which is which. Switching must be nearly as good as strong-only at half the cost
   or less.
4. Build the chat service, the API and the screen.
5. You try it live.

## What you decide

Where the Sable button goes, which model is "average", private or shared threads, whether to show "thinking harder",
how it hands edits to Zora, the lab budget, and whether viewers can use it. The full list with my suggestions is §7 in
[PLAN.md](PLAN.md).

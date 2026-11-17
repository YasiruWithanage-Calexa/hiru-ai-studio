# plan/2026-11-17b — Text inside the picture is allowed

**The person's decision (2026-11-17).** The video model renders readable text. We render with Omni Flash 1.1 and 1.2,
which draw a phone's message, a sign or a letter from the prompt's words and from a reference picture. The old Veo-lab
belief (that the model cannot draw text, so a phone is shown only as light on a face) is wrong for us and is removed from
the whole system.

## Why it kept coming back

The rule was struck for Raphael alone on 2026-11-08 (plan/2026-11-08e). Every other planner had been built by copying an
earlier one, all from the same Veo lab, so the rule lived on in about 20 places: the Jonathan and David checks, Adam's
feasibility step, ten system prompts, three knowledge-base docs, the video prompt's `lettering_clean` constraint, the
first frame's "no text", and the lab prompts new planners are copied from.

## What changed (built 2026-11-17)

1. **One home for the rule: `src/libs/contracts/on_screen_text.py`.** `PLANNER` (planners and shot writers: give the
   exact words, in the script's language, and say where they are), `CRITIC` (text in the picture is not a fault), `VIDEO`
   (the video prompt's rendering constraint) and `FRAME` (the first frame's closing).
2. **Positive rule, not avoidance.** `lettering_clean` ("Surfaces and signage stay free of lettering.") is gone from both
   clip schemas; both serializers (`steps/serialize`, `shot_producer` engine) add `on_screen_text.VIDEO`. The first frame's
   `CLOSE_SINGLE` dropped "no text" and adds `on_screen_text.FRAME` (no watermark and no captions stay).
3. **Checks.** The "screen text" feasibility entry is removed from `contracts/jonathan/checks.py` and
   `contracts/david/checks.py`; Adam's `screen_text` rule is removed from `steps/adam/adam_feasibility` (its example and
   tests now use a mirror).
4. **Prompts.** Zora, Jonathan (author, revise), David, Raphael (planner, cinematic) and Adam (director, shot designer,
   take) carry `PLANNER` word for word; Adam's two critics carry `CRITIC`. The other Veo limits (mirrors, fast hands,
   touching, crowds) are unchanged.
5. **Knowledge bases.** `adam_film_grammar/veo-feasibility.md` (new "Text inside the picture" section),
   `20-pov-insert.md`, `craft/cinematography.md`. Adam eval cases and gold masters no longer say "no readable name; add it
   in post".
6. **Labs.** `lab/cinematic`, `lab/zora_rows`, `lab/raphael`, `lab/davinci` prompts carry `PLANNER`. Lab runs are
   history and were left as they are.
7. **Guard.** `tests/contracts/test_on_screen_text.py` fails on the old wording anywhere in `src/` or a lab prompt,
   checks every planner and critic prompt carries the contract's sentence, and checks no planner check reports text.
8. **Rule written down** in the backend `CLAUDE.md`.

## Left for a person

- **Ingest the knowledge bases again** (`adam_film_grammar`, `craft`): the stored search copies keep the old text until then.
- **Old plans** keep their saved "asks for screen text" warnings until the scene is planned again.
- **Optional paid check** (about two short Omni Flash takes): a phone with a Sinhala message and an English sign, to see the
  text drawn as written. Not run; it needs the person's yes.

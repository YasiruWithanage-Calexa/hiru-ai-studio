# Omni Flash 1.2 only, and take lengths a production chooses (plan/2026-11-19)

Revision 1 (2026-11-19). Agreed with the person in chat on 2026-11-19. Building status: [IMPLEMENTED.md](IMPLEMENTED.md).

## 0. Rules for the chat that builds this

- **Only Shot Planner Raphael stays.** Adam, David, Jonathan, DaVinci and the classic planner keep their own 4/6/8 copies.
  Do not build for them and ignore their test failures (memory "Only Raphael stays", 2026-11-18).
- **No paid call without the person's yes, each time** (model, image, video). Tests run with `OPENAI__API_KEY=` blank.
- **Report an overrun, never trim** a line or a clip to fit.
- **The interface tree has uncommitted work.** Read `git diff` of a file before you edit it. Never stash.

## 1. What the person asked for

1. **One video model: Gemini Omni Flash 1.2.** Veo 3.1, Veo 3.1 Fast and Omni Flash 1.1 are dropped. 1.2 makes clips of
   3 to 15 s (Google, 2026-11). 1.1 made 3 to 10 s, Veo 4/6/8.
2. **Two ways a production cuts its takes** (the shot planner's "take lengths"):
   - **Steps**: 4, 6, 8, 10 s (as today, with 10 s added).
   - **Any length**: every whole second from 3 s to the production's maximum.
3. **When a production is created, the person picks the maximum length: 10 s or 15 s.** It is fixed from then on.

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | `ProductionSettings.max_take_s`: 10 or 15. Chosen at creation, locked like the video model (`PATCH` refuses a change). Unset (every production made before this plan) means the old 4/6/8 | A lower maximum would leave shots longer than it. The scene view re-fits every scene's shots with the production's lengths (`shotplan.fit`), so widening an old production's lengths would merge its unlocked shots and drop stored rows from the view |
| D2 | `ProductionSettings.take_lengths`: `"steps"` or `"any"`, chosen at creation with the maximum, locked too. Unset reads as steps | Changing the mode re-fits unlocked shots to other lengths than their takes were made at |
| D3 | Steps are every 2 s from 4 up to the maximum: max 10 gives 4/6/8/10, max 15 gives 4/6/8/10/12/14 | "Same like 4, 6, 8, 10" (the person). Revisit if 15 s itself is wanted in Steps |
| D4 | Any length: every whole second from 3 to the maximum (3...10 or 3...15). No fractions | `duration_seconds` is an integer. A probe of 7 s and 13 s on 1.2 is phase 6, paid, the person's |
| D5 | Soft cap: **8 s**. Raphael may go past it only when one continuous action or one line needs it. A clip over 8 s that holds more than one line is reported (advisory, never blocking) | Long takes are untested for face and clothes hold; the action budget (plan/2026-11-18c) already limits what one clip does |
| D6 | Veo and 1.1 are removed from `ENGINE_CAPABILITIES`. A stored `veo_3_1` / `veo_3_1_fast` production engine reads as `omni_flash`; a stored 1.1 model or Veo option is dropped when read. Old takes keep their engine name and still show | "Drop other models" without breaking productions and takes that exist |
| D7 | No version picker: Omni Flash has no `versions`; its model is `gemini-omni-1.2-flash` | One model |
| D8 | Database v27: `shots.duration_s` check becomes `between 3 and 15` | The v2...v26 check is `in (4, 6, 8)` |
| D9 | The scene planners other than Raphael keep 4/6/8 (`VEO_DURATIONS`) | Being removed |

## 3. The one rule in code

`contracts/take_lengths.py`:

```python
MIN_TAKE_S = 3
MAX_TAKE_CHOICES = (10, 15)
TakeMode = Literal["steps", "any"]

def take_lengths(mode, max_s) -> tuple[int, ...]   # steps: 4, 6 ... max (even); any: 3 ... max
def for_settings(settings: ProductionSettings) -> tuple[int, ...]
SOFT_CAP_S = 8
```

Every place that asks "which lengths may this shot have" reads `for_settings(production settings)`.

## 4. Phases

| Phase | What | Repo | Cost |
|---|---|---|---|
| 1 | `take_lengths.py`; `ProductionSettings.max_take_s` + `take_lengths`; `Shot.duration_s` 3...15; `PATCH` locks `max_take_s`; `fixed_shot_seconds` checked against 3...15 | backend | $0 |
| 2 | Omni 1.2 only: one engine row (`durations` 3...15, no versions), stored Veo/1.1 values read as 1.2, render worker drops the Veo providers, the version check goes | backend | $0 |
| 3 | Raphael reads the production's lengths: `SceneS.takes`, `shortest_take`, `LONGEST_TAKE_S` → the scene's longest, `parts_needed`, the listing; `take_s` is an `int` in the wire and the tool schema's enum is the run's lengths; the checks refuse a length outside them; the prompts say the lengths and the soft cap; the soft-cap advisory; `raphael_write` | backend | $0 |
| 4 | Shot edits: `PATCH` retime checks the production's lengths; Zora and Sable (`zora/wire.TAKES`, coverage `TAKES`, `coverage_kernel`, `zora_chat` regex, prompts) take them from the production | backend | $0 |
| 5 | Database v27 (`upgrade_v26_to_v27.sql`, `schema_v27.sql`) | backend | $0 (applying it is the person's) |
| 6 | Probe: one 7 s and one 13 s 1.2 take | live | paid, the person's |
| 7 | Interface: the create form's "Longest take: 10 s / 15 s" and "Take lengths: Steps / Any length"; Omni 1.2 the only model (no engine choice, no version picker); retime buttons and labels from the production's lengths; `timing.ts` takes the lengths as an argument | interface | $0 |
| 8 | Lab: plan one scene in each mode with Raphael, read the bins side by side (about $0.30) | live | paid, the person's |

## 5. Not in this plan

- Renaming "Veo" in names that do not change here (`contracts/veo.py`, `veo_fit`, the "Veo clock"). Later, on its own.
- Rewriting the Veo prompting guide or `clip_schema_veo_3_1.yaml` for Omni.
- The Veo provider code in `video_render/providers`: unused after phase 2, removed with the other planners.
- Price rows for Veo in `costs.py`: kept, so old takes still price.

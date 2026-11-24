# plan/2026-11-24: what is built

Built offline on 2026-11-24, both repos, uncommitted. No paid call in the build (the lab's three runs, $0.33, came
first). The person said "implement it" without answering Q1-Q3, so the recommendations were taken:

- **Q1** one views sheet per location, made again (a new version on the card) when a later scene sets it differently;
- **Q2** a person may edit the six views on the canon page and paint them as written;
- **Q3** no gate: a board whose place has no views paints from the plate as before, and the card offers to make them.

## Built

| Plan | Where |
|---|---|
| §2.1 the sheet | `contracts/canon.py`: `VIEWS_SHEET_KIND` (`views`), `views_asset`, `view_of`, `views_label`, `view_label`, `VIEW_JOB`, `views_sheet_prompt` (the lab's words), `sheet_assets` leaves it out, `keep_assets` keeps two; new agent `agents/views_writer` (tier medium; layout, light, six views); `systems/frame_render/views.py` `render_views` (write unless edited, paint MEDIUM 1536x1024 with the location plate and the plates of the places in it, cut 3x2, refuse a bad cut, store with each view's box) and the `views` node in `graph.py`; API `POST .../canon/{id}/views-sheet` (`ViewsRequest`: six edited views or none; `views_context`: the scenes set there, their boards' geography, the places named in them); `CanonEntity.views*` |
| §2.2 the board | `Panel.view` (writer schema + contracts), the writer's rule "THE PLACE HAS NAMED VIEWS", `Board.views` in the bundle's place, `Board.image_pictures` attaches the sheet instead of the plate, `views_paragraph` and `view_line` in `board_prompt` / `panel_prompt` (the lab's words), `writer_findings` reports a view the sheet does not have |
| §2.3 the frame | `frame_render/graph.py` `_view_picture`: with an approved panel that names a view, the location plate is replaced by that view cut from the sheet (`view_label`, `VIEW_JOB` in `frame_brief.reference_job`) and the board paragraphs gain "The background is view n (name) of the location sheet: …"; the shot prompter's `<shot>` gains "Background view: …" (`core/shot_prompts.board_facts`) |
| §2.1 asked for | interface: canon page `LocationViewsSection` (the sheet, the six named views, "Make location views" / "Remake", "Edit views" → six name + text fields → "Paint these views"), `makeLocationViews`; Scene board card note "No location views yet" (`missing_views`) |
| docs | `docs/scene_board/README.md`, `docs/AI_CATALOG.md` |

Changed from the lab, as §0 asks to say: the sheet prompt's "take from" sentences are built from the attached
pictures' labels (the lab named the roadside and the three-wheeler); the board's references paragraph says "its
buildings, its fixed things and every place that stands in it" (the lab: "its buildings, the food three-wheeler, the
wall, the pavement and the drain"); the frame's view job is `VIEW_JOB` in the label plus the view's own words as a
board paragraph (the lab wrote both into the job); the light line comes from the views writer (the lab wrote it by
hand).

## Tests

New: `tests/contracts/test_location_views.py` (6), `tests/hiru_ai/test_location_views.py` (6),
`agents/views_writer/tests` (3), in `tests/api/test_boards.py` the views route test; interface
`location-views.test.tsx` (3). All pass, with every board, frame, canon, contracts, agents and parity suite (1948
passed; the 4 failing were failing before: `raphael_breakdown` eval cases, 3 parity recordings). mypy clean, ruff clean
on these files, `hiru_ai validate` 202 parts, catalog current; interface `tsc`, lint and its tests pass (the one
failing test, `raphael-panel.test.tsx`, and 65 unformatted files are not this plan's).

The shot producer and frame render workers were restarted on this code.

## The person's live check (paid, ask first)

1. Canon → "Colombo roadside" → **Make location views** (one writer call, about $0.01, and one MEDIUM sheet, about
   $0.10). Check the six views; edit and "Paint these views" if one is off.
2. Scene 4 → **Repaint whole board** (LOW): every panel names its view; then approve the parts.
3. **Paint first frame** for shots 1, 3 and 11 (one setup): the same three-wheeler, wall and building behind them;
   the pair's spacing alike.

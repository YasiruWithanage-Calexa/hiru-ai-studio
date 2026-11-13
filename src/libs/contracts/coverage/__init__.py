"""A scene's shot rows read as COVERAGE, for the director chat (plan/2026-11-13 §3.1-§3.4; its lab, `lab/zora_rows`).

    scene.py     `Coverage`, `Clip`, `Line`, `Block`: the clips read from the shot rows (never from a planner's stored
                 plan), what the models read, the fingerprint a card is made on, and the rows written back
    checks.py    planner-free checks in code (`find`, `new`), `line_unvoiced` among them
    risk.py      which landed operations ask the person first (Accept / Reject), and the lines the card shows
    ledger.py    what changed between two coverages, as a person reads it

Clips may overlap (several clips show the same block); a line is PERFORMED by exactly one clip
(`dialogue_lines.shot_id`). Pure standard library + pydantic (the `contracts` rule).
"""

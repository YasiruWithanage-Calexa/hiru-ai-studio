"""The three tiers of a moment and the elaborations Adam may add (plan/2026-11-04b §4, §6.1).

The rule changes from "never invent" to "never invent STORY; always elaborate the PICTURE":

    SCRIPT       the script says it: fixed, every one appears, in order
    IMPLIED      the script needs it without spelling it out (picking up the phone, a listener's face)
    ELABORATION  a director's choice that adds no story (a baseline, a detail, a held empty frame), from a closed list
    INVENTION    new story: a new person who acts or speaks, a new line, an event, a fact. FORBIDDEN, refused in code.

`invention` is a tier a plan can NAME so that a model which labels its own addition honestly is refused with a reason
instead of failing to parse. Pure standard library (the `contracts` rule); no import from the rest of `contracts`.
"""
from __future__ import annotations

SCRIPT, IMPLIED, ELABORATION, INVENTION = "script", "implied", "elaboration", "invention"
TIERS: tuple[str, ...] = (SCRIPT, IMPLIED, ELABORATION, INVENTION)
ALLOWED_TIERS: tuple[str, ...] = (SCRIPT, IMPLIED, ELABORATION)

# §6.1: the closed list of what a director may add. Anything else is refused.
ELABORATION_KINDS: tuple[str, ...] = (
    "baseline",       # the state before the break
    "reaction",       # a person present
    "listener",       # a line played over the face that hears it
    "insert_detail",  # an object the script names or the location card has
    "hands",
    "pov",            # of a person present
    "atmosphere",     # the place, its light, its weather as given
    "hold",
    "plant",          # an object shown early that a later SCRIPT moment uses
    "transition",     # the way into or out of the scene
    "empty_frame",    # a place after a person has gone
    "implied_action",  # a step the script needs: picking up, lowering, turning
    "move",           # a walk the staging needs
)

# What each kind must name so that it can be checked: the people (all must be in the cast) and/or the objects (each
# must be in the script or on the location card).
NEEDS_WHO: frozenset[str] = frozenset({"baseline", "reaction", "listener", "hands", "pov", "implied_action", "move"})
NEEDS_OBJECTS: frozenset[str] = frozenset({"insert_detail", "plant"})

# Why a refusal happened, one stable code each (the step's `breaks[].code`).
BREAK_CODES: tuple[str, ...] = (
    "invention", "bad_tier", "bad_kind", "no_kind", "serves_nothing", "unknown_serves", "new_person", "no_person",
    "new_object", "no_object", "has_line", "invented_line", "unknown_line", "line_misplaced", "script_missing",
    "script_repeated", "script_order", "line_missing", "line_repeated", "line_order", "unknown_moment",
    "moment_repeated", "moment_missing", "moment_order", "duplicate_id", "malformed",
)

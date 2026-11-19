"""The action budget in the video prompt's checks and the reasons a take is rejected (plan/2026-11-18c phases 7-8)."""

from __future__ import annotations

# ── the video prompt's checks (plan/2026-11-18c phase 7) ──────────────────────────────────────────────────────────


def test_the_prompt_checks_say_whether_the_shots_actions_fit_the_budget_and_never_block():
    from contracts.handoff import ShotNow, blocking, check_prompt

    def checks(*actions: str) -> list[tuple[str, str]]:
        shot = ShotNow(code="S02", duration_s=8, aspect_ratio="9:16", sound_mode="ambient", actions=list(actions))
        return [(c.label, c.tone) for c in check_prompt(prose="Nobody speaks.", sinhala=[], shot=shot)
                if "budget" in c.label]

    assert checks("Anudi, already out of the car with the door shut, nods and walks off.") == [
        ("Actions within budget", "pass")]
    ((label, tone),) = checks("The car stops; Anudi opens the rear door, steps out and walks off.")
    assert label.startswith("Over the action budget: ") and tone == "advisory"
    assert checks() == []  # a shot with no beats written yet says nothing
    shot = ShotNow(code="S02", duration_s=8, aspect_ratio="9:16", sound_mode="ambient",
                   actions=["The car stops; Anudi opens the rear door, steps out and walks off."])
    assert not blocking(c for c in check_prompt(prose="Nobody speaks. Aspect ratio 9:16", sinhala=[], shot=shot)
                        if "budget" in c.label)


def test_a_rejected_takes_reason_says_the_picked_reasons_first_then_the_persons_words():
    from contracts.handoff import reject_reason

    assert reject_reason(["too_many_actions", "camera_moved"], " lips drift ") == (
        "Too many actions; Camera moved · lips drift")
    assert reject_reason(["object_vanished", "object_vanished"]) == "Object vanished"
    assert reject_reason([], "lips drift") == "lips drift"
    assert reject_reason([], "") == "Rejected"

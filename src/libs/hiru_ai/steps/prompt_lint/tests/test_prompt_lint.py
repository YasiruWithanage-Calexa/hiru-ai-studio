from __future__ import annotations

import copy

from hiru_ai.steps.prompt_lint import step

SHOT = {"id": "s1", "duration_s": 6, "sound_mode": "dialogue", "camera_link": "cut"}
LINES = [{"shot_id": "s1", "speaker": "Kasun", "text": "මම ගෙදර යනවා"}]


def section(ident, *segments):
    return {"id": ident, "title": ident.title(), "segments": list(segments)}


def good():
    return {"sections": [section("style", {"text": "Photoreal."}), section("camera", {"text": "Slider."}),
                         section("voices", {"text": "Kasun: warm."}),
                         section("action", {"text": "0-3s: he speaks."}, {"sinhala": "මම ගෙදර යනවා"}),
                         section("constraints", {"text": "Lips closed."}),
                         section("format", {"text": "Aspect ratio 16:9. Duration 6 seconds."})],
            "prose": "Photoreal. Slider. 0-3s: he speaks. මම ගෙදර යනවා", "checks": []}


def codes(prompt, shot=SHOT, lines=LINES):
    return [f["code"] for f in step.run({"prompt": prompt, "shot": shot, "lines": lines})["findings"]]


def test_a_complete_prompt_with_its_line_word_for_word_is_clean():
    assert step.run({"prompt": good(), "shot": SHOT, "lines": LINES}) == {"ok": True, "findings": []}


def test_a_missing_section_is_named():
    prompt = good()
    prompt["sections"] = [s for s in prompt["sections"] if s["id"] != "camera"]
    out = step.run({"prompt": prompt, "shot": SHOT, "lines": LINES})
    assert [f["message"] for f in out["findings"]] == ["the prompt has no camera section"]


def test_voices_are_needed_only_when_the_shot_speaks_and_a_join_only_on_a_join():
    prompt = good()
    prompt["sections"] = [s for s in prompt["sections"] if s["id"] != "voices"]
    assert codes(prompt) == ["missing_section"]
    assert codes(prompt, {**SHOT, "sound_mode": "silent"}, []) == []
    assert codes(good(), {**SHOT, "camera_link": "continuous"}) == ["missing_section"]


def test_a_wrong_duration_is_reported():
    prompt = good()
    prompt["sections"][-1] = section("format", {"text": "Aspect ratio 16:9. Duration 8 seconds."})
    out = step.run({"prompt": prompt, "shot": SHOT, "lines": LINES})
    assert [f["code"] for f in out["findings"]] == ["duration"] and "8 seconds" in out["findings"][0]["message"]


def test_a_line_that_was_reworded_is_reported_and_unicode_form_is_forgiven():
    prompt = good()
    prompt["sections"][3] = section("action", {"sinhala": "මම ගෙදර යමි"})
    prompt["prose"] = "Photoreal. මම ගෙදර යමි"
    assert codes(prompt) == ["line_changed"]
    nfd = copy.deepcopy(good())
    nfd["sections"][3]["segments"][1]["sinhala"] = "\u0DB8\u0DB8 \u0D9C\u0DD9\u0DAF\u0DBB \u0DBA\u0DB1\u0DC0\u0DCF"
    assert codes(nfd) == []


def test_a_prompt_over_the_models_limit_and_a_failed_stored_check_are_reported():
    prompt = good()
    prompt["prose"] = "word " * 6000
    prompt["checks"] = [{"label": "A line differs from the script", "tone": "fail"},
                        {"label": "One visible speaker", "tone": "pass"}]
    assert codes(prompt) == ["too_long", "failed_check"]

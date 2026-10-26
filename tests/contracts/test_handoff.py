"""contracts.handoff: the checks a prompt passes before it leaves, and what counts as a take."""
from __future__ import annotations

from contracts.handoff import LineNow, ShotNow, SpeakerNow, blocking, check_prompt, video_kind

LINE = "අම්මේ, මම ආපහු ආවා."
PROSE = ('VOICES\nVoice casting: Nimal: low voice.\n\nACTION & DIALOGUE\nNimal says, "' + LINE + '"\n\n'
         "FORMAT\nAspect ratio 16:9. Duration 4 seconds. Ends on a cut.")


def shot(**kw) -> ShotNow:
    base = dict(code="S02", duration_s=4, aspect_ratio="16:9", sound_mode="dialogue",
                lines=[LineNow(text=LINE, speaker="Nimal")], speakers=[SpeakerNow(name="Nimal", voice_pin="low voice")])
    return ShotNow(**{**base, **kw})


def labels(checks) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {c.label: c.tone for c in checks}


def test_a_good_prompt_passes():
    checks = check_prompt(prose=PROSE, sinhala=[LINE], shot=shot())
    assert not blocking(checks)
    assert labels(checks) == {"Lines match the approved script": "pass", "Aspect ratio 16:9": "pass",
                              "4 s on the Veo ladder": "pass", "No brands or listed names": "pass"}


def test_changed_lines_overruns_and_voice_pins_are_reported():
    checks = check_prompt(prose=PROSE, sinhala=["වෙනස් පේළියක්"],
                          shot=shot(lines=[LineNow(text=LINE, speaker="Nimal", overrun_s=1.24)],
                                    speakers=[SpeakerNow("Nimal", "warm, quick voice")]))
    got = labels(checks)
    assert got["A line differs from the approved script"] == "fail"
    assert got["Nimal's line runs 1.2 s past the cut in S02 (shorten it or give it its own shot)"] == "advisory"
    assert got["Nimal's voice pin changed since this prompt"] == "advisory"


def test_silence_must_be_stated_on_a_wordless_shot():
    wordless = shot(sound_mode="ambient", lines=[], speakers=[])
    assert labels(check_prompt(prose="No dialogue. Nobody speaks on camera. Aspect ratio 16:9.", sinhala=[],
                               shot=wordless))["Silence stated"] == "pass"
    assert labels(check_prompt(prose="Waves.", sinhala=[], shot=wordless))[
        "The prompt does not say nobody speaks"] == "fail"


def test_format_and_banned_names():
    checks = check_prompt(prose=PROSE.replace("16:9", "9:16").replace("4 seconds", "8 seconds") + " A Coke can.",
                          sinhala=[LINE], shot=shot(), banned_terms=["Coke", "Ranil"])
    got = labels(checks)
    assert got["Aspect ratio 9:16; the production is 16:9"] == "fail"
    assert got["The prompt says 8 s; S02 is 4 s"] == "fail"
    assert got["Names to remove: Coke"] == "fail"
    assert "Names to remove" not in str(check_prompt(prose="Cokes and cokeries", sinhala=[LINE], shot=shot(),
                                                     banned_terms=["Coke"])), "whole words only"


def test_video_kinds_by_content():
    assert video_kind(b"\0\0\0\x18ftypisom" + b"\0" * 8) == ("mp4", "video/mp4")
    assert video_kind(b"\0\0\0\x14ftypqt  " + b"\0" * 8) == ("mov", "video/quicktime")
    assert video_kind(b"\x1aE\xdf\xa3" + b"\0" * 8) == ("webm", "video/webm")
    assert video_kind(b"GIF89a") is None

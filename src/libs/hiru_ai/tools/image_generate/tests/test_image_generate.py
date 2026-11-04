from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import PortMissing
from hiru_ai.core.fakes import FakeFiles, FakeImages, ports_from
from hiru_ai.core.ports import ImageFailed, ImageRefused
from hiru_ai.tools.image_generate import tool

WHERE = tool.Where(bucket="frames", path="p1/f1.png")


def ctx(images: FakeImages | None = None, files: FakeFiles | None = None) -> RunContext:
    ports = ports_from({})
    return RunContext(ports=replace(ports, images=images or FakeImages(), files=files or FakeFiles()))


def test_a_frame_is_painted_with_its_references_in_order_and_stored():
    files = FakeFiles({("references", "a.png"): b"A", ("references", "b.png"): b"B"})
    images = FakeImages()
    out = tool.run(tool.Args(prompt="Kamala at the breakwater", aspect_ratio="9:16", save_to=WHERE, references=[
        tool.Ref(label="the character sheet for Kamala", bucket="references", path="a.png"),
        tool.Ref(label="the harbour plate", bucket="references", path="b.png")]), ctx(images, files))
    assert out.painted and (out.bucket, out.path, out.mime) == ("frames", "p1/f1.png", "image/png")
    assert (out.input_tokens, out.output_tokens) == (120, 1056)
    prompt, aspect, refs = images.calls[0]
    assert (prompt, aspect) == ("Kamala at the breakwater", "9:16")
    assert [(r.label, r.data) for r in refs] == [("the character sheet for Kamala", b"A"), ("the harbour plate", b"B")]
    assert files.objects[("frames", "p1/f1.png")] == b"\x89PNG-fake"


def test_a_model_that_declines_is_a_result_to_report_and_nothing_is_stored():
    files = FakeFiles()
    out = tool.run(tool.Args(prompt="a scene", save_to=WHERE), ctx(FakeImages(ImageRefused("declined")), files))
    assert not out.painted and out.refused and out.message == "declined" and files.objects == {}


def test_a_provider_failure_is_not_a_refusal():
    out = tool.run(tool.Args(prompt="a scene", save_to=WHERE), ctx(FakeImages(ImageFailed("it broke"))))
    assert not out.painted and not out.refused and out.message == "it broke"


def test_only_the_two_veo_shapes_are_accepted():
    with pytest.raises(ValidationError):
        tool.Args(prompt="a scene", aspect_ratio="1:1", save_to=WHERE)


def test_a_run_without_an_image_port_says_so():
    c = ctx()
    with pytest.raises(PortMissing, match="images"):
        tool.run(tool.Args(prompt="a scene", save_to=WHERE), replace(c, ports=replace(c.ports, images=None)))

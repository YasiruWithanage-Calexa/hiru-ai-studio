"""The camera sentence a video prompt gets (plan/2026-11-20c D13): the Camera agent's while the person has not changed a
camera field; after a change, code writes it from the fields as they stand. The template lives in
`contracts.camera_words` (the frame brief and the old serializer read it too); this is the step's door to it.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from contracts.camera_words import camera_line, sentence_from_fields
from contracts.frame_brief import agent_camera
from contracts.producer import CameraSettings

__all__ = ["sentence", "sentence_from_fields"]


def sentence(camera: CameraSettings, recommended: CameraSettings | None, design: Mapping[str, Any] | None) -> str:
    """The Camera section of the video prompt. `design` is the shot's whole design row (its `camera` block is read)."""
    return camera_line(camera, recommended, agent_camera({"design": design or {}}))

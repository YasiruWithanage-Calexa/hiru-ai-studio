"""image_generate: paint one picture and store it.

Reference images are read from storage by path (the order given is the order the prompt numbers them), the picture
is painted by the run's `ImageGen` port and uploaded to `save_to`; the bytes never travel through the model. A model
that DECLINES is a result to report (`refused=True` with words for the person), not an error and never retried.
Paths are derived by the caller (from the frame id), so a retried job overwrites instead of leaving a second object.
"""
from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.ports import ImageFailed, ImageRefused, Reference
from hiru_ai.core.telemetry import logger

_log = logger("image_generate")


class Ref(BaseModel):
    label: str = Field(description="What the prompt calls it, e.g. the base character sheet for Kamala")
    bucket: str
    path: str


class Where(BaseModel):
    bucket: str
    path: str


class Args(BaseModel):
    prompt: str = Field(min_length=3)
    aspect_ratio: str = Field("16:9", pattern="^(16:9|9:16)$")
    references: list[Ref] = Field(default_factory=list, description="In the order the prompt numbers them")
    save_to: Where


class Result(BaseModel):
    painted: bool
    refused: bool = False
    message: str = ""
    bucket: str = ""
    path: str = ""
    mime: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def run(args: Args, ctx: RunContext) -> Result:
    images = ctx.need("images", "ImageGen")
    files = ctx.need("files", "Files")
    refs = [Reference(label=r.label, data=files.download(r.bucket, r.path)) for r in args.references]
    try:
        picture = images(args.prompt, args.aspect_ratio, refs)
    except ImageRefused as exc:
        return Result(painted=False, refused=True, message=str(exc))
    except ImageFailed as exc:
        _log.warning("image not painted: %s", exc)
        return Result(painted=False, message=str(exc))
    files.upload(args.save_to.bucket, args.save_to.path, picture.data, picture.mime)
    return Result(painted=True, bucket=args.save_to.bucket, path=args.save_to.path, mime=picture.mime,
                  input_tokens=picture.input_tokens, output_tokens=picture.output_tokens)


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)

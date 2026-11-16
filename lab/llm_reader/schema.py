"""What the model returns about one whole document. Every fact carries the words it came from (`Quote`), so code can
check it was read, never guessed. Code never reads the document itself: only this answer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _W(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Quote(_W):
    line: int = Field(description="the line number it is on; 0 when there is nothing to quote")
    quote: str = Field(description="the words copied character for character from that line; empty when line is 0")


class Length(_W):
    stated: bool = Field(description="true only when the document itself states a length for this scene or episode")
    low_seconds: float = Field(description="the stated length in seconds (the low end of a range); 0 when not stated")
    high_seconds: float = Field(description="the high end of a range in seconds; the same as low for one number; 0 when not stated")
    source: Quote = Field(description="the words that state the length, exactly as written")


class Problem(_W):
    where: Quote
    what: str


class TextQuality(_W):
    readable: bool = Field(description="false when the text itself is damaged so that copying it would copy errors")
    problems: list[Problem] = Field(description="up to 5 examples")


class Declared(_W):
    episodes: int = Field(description="the number of episodes the document SAYS it has (e.g. a cover line); 0 if it says none")
    source: Quote


class Episode(_W):
    number: int
    title: str
    heading: Quote = Field(description="only the heading's own words")
    length: Length


class Scene(_W):
    episode: int = Field(description="the episode number it belongs to; 0 when the document has no episodes")
    number: int = Field(description="the document's own scene number within its episode")
    heading: Quote = Field(description="where the scene STARTS: ONLY the heading's own words, even when the line also "
                                       "holds other text")
    end: Quote = Field(description="where the scene ENDS: its last words, copied from the line they are on")
    title: str = Field(description="the scene's title as the document gives it; empty if it gives none")
    place: str = Field(description="the place by its own name; when the document points back ('same workspace'), the "
                                   "place it points to")
    place_refers_back: bool = Field(description="true when the document's words point back to an earlier place")
    place_source: Quote
    time_of_day: str = Field(description="as the document states it; empty if not stated")
    length: Length
    speakers: list[str] = Field(description="the people who speak in this scene, by the names in `people`")
    spoken_lines: list[int] = Field(description="every line number that holds words someone says aloud in this scene")


class Person(_W):
    name: str
    aliases: list[str] = Field(description="other ways the document names this same person")
    role: Literal["lead", "supporting", "minor", "group"] = Field(
        description="lead: the story is about them; group: several unnamed people (customers, staff)")
    why: str = Field(description="one line: why this role")
    first_seen: Quote

    @property
    def main(self) -> bool:
        return self.role == "lead"


class Skipped(_W):
    first: int
    last: int
    kind: Literal["title_page", "page_furniture", "production_notes", "end_marker", "other"]


class Answer(_W):
    kind: Literal["story_script", "story_prose", "synopsis", "series_bible", "cast_or_crew_list", "other_not_story"]
    kind_why: str
    language_of_dialogue: str
    text_quality: TextQuality
    declared: Declared
    episodes: list[Episode]
    scenes: list[Scene]
    people: list[Person]
    skipped: list[Skipped] = Field(description="line ranges that are not story")
    doubts: list[str] = Field(description="anything you were unsure of, one line each")


class Probe(_W):
    """The cheap first look (Gate 0 and 1): what the document is, and whether its text can be copied as it is."""

    kind: Literal["story_script", "story_prose", "synopsis", "series_bible", "cast_or_crew_list", "other_not_story"]
    kind_why: str
    language_of_dialogue: str
    text_quality: TextQuality


class PageText(_W):
    page: int
    lines: list[str] = Field(description="every printed line of the page, in order, one entry per printed line")


class Transcription(_W):
    pages: list[PageText]


def _strict(node: Any, defs: dict[str, Any]) -> Any:
    """Pydantic's schema -> OpenAI strict: refs inlined, every property required, no extra properties."""
    if isinstance(node, dict):
        if "$ref" in node:
            return _strict(defs[node["$ref"].split("/")[-1]], defs)
        # `title`/`default` are pydantic's annotations (strings); a PROPERTY named `title` is a dict and is kept
        out = {k: _strict(v, defs) for k, v in node.items()
               if k != "$defs" and not (k in ("title", "default") and not isinstance(v, dict))}
        if out.get("type") == "object":
            out["required"] = list(out.get("properties", {}))
            out["additionalProperties"] = False
        return out
    if isinstance(node, list):
        return [_strict(v, defs) for v in node]
    return node


def json_schema(model: type[BaseModel] = Answer) -> dict[str, Any]:
    raw = model.model_json_schema()
    return _strict(raw, raw.get("$defs", {}))

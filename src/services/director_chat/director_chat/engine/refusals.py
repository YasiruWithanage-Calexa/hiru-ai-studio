"""Why an operation was refused, in words a person can read (PLAN.md v2 §1 "text takes text").

The kernel raises `OpError` with a sentence, but a model can send an operation shaped wrongly
(a null value, an operation name it made up) and the check that catches it then speaks in
internals. Everything the kernel records as a refusal passes through `for_person`, so a raw
validation message never reaches a reply, a card or the browser.
"""
from __future__ import annotations

import re

# Words that only make sense inside the code: a validation message, a field or operation name
# written as `block.set`, a Python value, a bracketed structure.
INTERNAL = re.compile(r"takes text|\bNone\b|\bnull\b|OpError|Traceback|[{}<>]|\b[a-z_]{2,}\.[a-z_]{2,}\b"
                      r"|\bunknown operation\b|\bmust be an object\b")
FALLBACK = "that change could not be made as written"


def for_person(reason: str) -> str:
    """The reason as written when it reads as a sentence, else a plain one."""
    text = " ".join(str(reason).split())
    return FALLBACK if not text or INTERNAL.search(text) else text

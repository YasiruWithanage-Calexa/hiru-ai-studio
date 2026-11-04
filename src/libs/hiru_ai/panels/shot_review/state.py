"""shot_review's seams. The producer system supplies three small functions (the plan's `input_map` / `output_map`, in
code): how to ask the writer, how to ask the critic, and when a revision replaces the draft. The panel supplies the
agents, resolved by id from its manifest, and the bounded loop."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

#: write(ask_writer, brief, notes) → the draft. `ask_writer(input)` runs the manifest's writer; None = first draft.
Write = Callable[[Callable[[dict[str, Any]], Any], dict[str, Any], list[str] | None], Any]
#: critique(ask_critic, brief, draft) → notes ([] = content). `ask_critic(input)` runs the manifest's critic.
Critique = Callable[[Callable[[dict[str, Any]], Any], dict[str, Any], Any], list[str]]
#: accept(brief, draft, revised) → the draft to keep (the free checks decide, per shot).
Accept = Callable[[dict[str, Any], Any, Any], Any]

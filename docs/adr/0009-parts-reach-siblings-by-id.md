# 0009. A part that builds on a sibling asks for it by id and says so in its manifest

Status: accepted (2026-11-03, found in Phase 2).

**Context.** Plan §5.2 says a part never imports a sibling; code asks the registry. Porting the engines showed that
a few steps really do build on another step: the scene kernel words its refusals with `refusal_screen`, `ripple`
reads the kernel, `serialize` reads `feeling`, and the canon writer uses `canon_rules`' same-entity rule. A hidden
import would break the independence contract; copying the rule would let two copies drift.

**Decision.** A step or tool lists the steps it calls in its manifest (`uses: [refusal_screen]`) and gets their code
through `hiru_ai.core.parts` (`parts.step("refusal_screen")`), which is the registry's lazy import. `hiru-ai validate`
checks the ids exist, are active and have no cycle; `refs_to` and `hiru-ai remove` see the link. Where only a data
shape is needed (`ripple` reads a kernel; `chunk` reads `extract_text`'s lines), the shape is written in the
consumer as a `Protocol` or a small dataclass and a system maps one part's output onto the other's input.

**Consequences.** The import-linter independence contracts stay strict (no sibling import anywhere). The link is
visible in manifests and in the catalog (Phase 7). A part that is disabled cannot be reached, so disabling
`refusal_screen` makes `validate` fail for the kernel instead of failing at run time.

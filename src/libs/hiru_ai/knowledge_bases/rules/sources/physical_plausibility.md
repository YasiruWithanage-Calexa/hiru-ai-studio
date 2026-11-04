# Physical Plausibility (Basic Physics)

Design doc for `physical_plausibility.json`. Editable — the JSON is what the
engine injects; this file records the reasoning.

## Problem

Rendered videos sometimes show characters walking **through** tables, chairs or
walls as if they were not solid. The video model treats an under-specified
movement ("crosses to the kitchen") as a straight-line interpolation, and when
that line intersects furniture it renders a ghost-like pass-through instead of
routing around it or colliding.

Observed on movie-story renders (Veo 3.1 lite, July 2026): characters crossing
a dining-room set clipped through the table edge.

## Approach

Three prompt-side locks, all `clip_render_static` / `always` (they ride the
cached static prefix, so the token cost is one-time per run):

1. **solid_object_collision** — declares set objects impenetrable; demands
   routes go around; scripted contact must be a real collision with reaction.
2. **movement_path_planning** — the render LLM must describe the actual
   walkable route relative to named furniture, because an unspecified
   straight line through occupied space is what renders as clipping.
3. **weight_and_support** — gravity/support basics: items rest on surfaces,
   chairs pulled out before sitting, doors opened before passing, feet on
   the floor.

Complemented outside this registry by:
- the lean video_clip schema's `subjects.action` hint ("path routes around
  solid objects"), and
- a one-line `Physics:` footer in the compact `veo_prompt` serializer — the
  text the video model actually reads.

## Notes

- Scope: shared story engines (movie + story-based products). The default
  scenario graph does not consume this registry.
- If a genre needs stylized physics (dream sequence, VFX), disable per-rule
  with `"enabled": false` rather than deleting.

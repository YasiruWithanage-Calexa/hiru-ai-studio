You are given a whole story, numbered lines with scene ids ("E01-S03" before each scene's lines), and its cast, places, things and
direction rules, each with an id. Report ONLY the facts that carry ACROSS scenes and episodes. What happens inside one scene is
another step's job.

Return:
- timeline: every scene once, with `story_order` (1 is the first thing that happens in the story, NOT the first on the page),
  `story_day` when the story says it, `relative` for phrases like "six hours earlier", and `kind` (normal, flashback, cold_open,
  flash_forward) with its `anchor` scene.
- synopses: one short synopsis per episode.
- arcs: per person, what changes and between which scenes.
- knowledge: who learns what in which scene. Where the audience knows something the people do not, set `audience_only`.
- threads: setups that pay off (`setup_payoff`), questions the story leaves open (`open_question`), and the journey of anything
  that moves (`journey`: who holds it, scene by scene).
- looks: wardrobe changes, injuries, deaths and other lasting condition, from one scene to another.
- relationships: how two people stand, and where that changes.
- scopes: which scenes a direction rule applies to, and the scene of a moment a rule names ("slow motion: the key falling").

Rules you keep:
- Refer to people, places, things and rules by the ids you were given, and to scenes by their scene ids. Never type a name.
- Every item has `source`: `script` with the line range it rests on, or `inferred` with a one-line `reason`. What the story
  implies may be said; what it leaves open stays open (how a key travels between hands that the script does not show is an open
  question, never an explanation). Never invent story.
- Keep it compact: cross-scene facts only, no small details of one scene.

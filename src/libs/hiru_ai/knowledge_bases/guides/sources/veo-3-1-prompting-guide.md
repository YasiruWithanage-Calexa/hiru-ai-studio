# Veo 3.1 Prompting — Report & Guidelines

> Consolidated from Google Cloud's official *Ultimate Prompting Guide for Veo 3.1*
> and a community field-thread (r/PromptEngineering) with practitioner corrections.
> Purpose: give PromptMotion a single, authoritative reference for how we should
> build Veo 3.1 prompts (relevant to the movie/shared render path that emits a
> lean engine-targeted JSON prompt — see `docs/engines/prompt-quality-pipeline.md`).

## Sources

1. **Google Cloud (official)** — *Ultimate Prompting Guide for Veo 3.1*
   https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1
2. **r/PromptEngineering** — *"The Veo 3 prompting guide that actually worked"* (thread + comments)
   https://www.reddit.com/r/PromptEngineering/comments/1ms5ri4/

---

## TL;DR — the recommended way

- **Lock the shot first, then layer.** Order matters:
  `[Cinematography] → [Subject] → [Action] → [Context] → [Style & Ambiance]`.
- **Always include audio cues** (dialogue, SFX, ambient). This is the single
  highest-leverage, most-underused lever for realism.
- **Put spoken lines in quotation marks**, ideally attributed to a named speaker.
- **Describe exclusions positively** — say what the scene *is*, not a list of "no X".
- **Use timestamped segments** for multi-shot sequences in one generation.
- **Use reference images** ("Ingredients to Video" / first-and-last-frame) for
  character and setting consistency — prompt text alone will not hold a character
  across clips.

---

## 1. What Veo 3.1 is

| Capability | Detail |
|---|---|
| Resolution | 720p or 1080p |
| Aspect ratio | 16:9 or 9:16 |
| Clip length | 4, 6, or 8 seconds |
| Audio | Native, synchronized dialogue + SFX + ambient |
| Image-to-video | Stronger prompt adherence than Veo 3 |
| Ingredients to Video | Reference images for consistent characters/objects/styles |
| First & Last Frame | Seamless transition between a supplied start and end image |
| Add/Remove object | Falls back to Veo 2 (**no audio** on that path) |
| Watermark | SynthID digital watermark on all output |

Veo 3.1 is framed by Google as a shift *from generation to creative control* —
it rewards direction, not just description.

---

## 2. The core prompt formula

```
[Cinematography] + [Subject] + [Action] + [Context] + [Style & Ambiance]
```

**Reference example (official):**
> "Medium shot, a tired corporate worker, rubbing his temples in exhaustion, in
> front of a bulky 1980s computer in a cluttered office late at night. The scene
> is lit by the harsh fluorescent overhead lights and the green glow of the
> monochrome monitor. Retro aesthetic, shot as if on 1980s color film, slightly
> grainy."

### Component breakdown

**[Cinematography] — camera work & composition (state this first)**
- *Movement:* dolly, tracking, crane, aerial, slow pan, POV
- *Composition:* wide shot, close-up, extreme close-up, low angle, two-shot
- *Lens & focus:* shallow depth of field, wide-angle, soft focus, macro, deep focus

**[Subject] — the focal character/object**
- Identify clearly with distinguishing appearance details.

**[Action] — what the subject does**
- Specific movements, gestures, behaviors.

**[Context] — environment & background**
- Setting, time of day, location, background elements, spatial relationships.

**[Style & Ambiance] — aesthetic, mood, lighting**
- Overall aesthetic (retro, cinematic, photorealistic…), emotional tone, lighting
  conditions, color grading (cool blue tones, warm golden hour…).

---

## 3. Audio & dialogue (do not skip this)

**Dialogue** — quote it, attribute it:
> A woman says, "We have to leave now."

Advanced (camera + dialogue together):
> "The camera performs a smooth 180-degree arc shot… The singer sings 'when you
> look me in the eyes, I can see a million stars.'"

**Sound effects:**
> `SFX: thunder cracks in the distance`
> `SFX: the rustle of dense leaves, distant exotic bird calls`

**Ambient noise:**
> `Ambient noise: the quiet hum of a starship bridge`
> `SFX: a swelling, gentle orchestral score begins to play`

> Community note (echoed by practitioners): audio cues are "barely used" but
> "instantly make outputs feel 10x more real." Treat them as required, not optional.

---

## 4. Advanced techniques

### Timestamp prompting (multi-shot in one generation)
Direct a full sequence with precise pacing:
```
[00:00-00:02] Medium shot from behind a young female explorer… pushes aside a jungle vine to reveal a hidden path.
[00:02-00:04] Reverse shot of her freckled face, awe as she gazes on moss-covered ruins. SFX: rustle of leaves, distant bird calls.
[00:04-00:06] Tracking shot following her into the clearing, hand over the carvings. Emotion: wonder and reverence.
[00:06-00:08] Wide high-angle crane shot revealing her small in the vast temple. SFX: a swelling orchestral score begins.
```

### Negative prompts — phrase positively
- ❌ "no man-made structures"
- ✅ "a desolate landscape with no buildings or roads"

### Prompt enhancement
- Use Gemini 2.5 Flash Image to enrich a thin prompt with cinematic detail before
  sending to Veo.

### Consistency workflows
- **First & Last Frame:** generate both frames (complementary angles), then describe
  the transition.
- **Ingredients to Video:** supply reference images for characters + setting, then
  prompt multi-shot dialogue scenes that maintain identity:
  > "Using the provided images for the detective, the woman, and the office setting,
  > create a medium shot of the detective behind his desk. He looks up and says in a
  > weary voice, 'Of all the offices in this town, you had to walk into mine.'"

---

## 5. Do's and Don'ts

**✅ Do**
- Use the five-part formula, cinematography terms first.
- Use professional camera/lens/lighting language.
- Put dialogue in quotes, attributed to a speaker.
- Specify SFX + ambient soundscape every time.
- Use reference images for cross-clip character consistency.
- Use timestamp segments for complex sequences.
- Be specific about lighting, mood, and aesthetic.

**❌ Don't**
- Use vague negative exclusions ("no X") — describe the desired state instead.
- Omit cinematography when tone/emotion matters.
- Neglect audio — it carries much of the perceived realism.
- Expect text-only prompts to hold a character across separate generations.

---

## 6. Field lessons from the community thread

These are practitioner observations (not official), useful as guardrails:

- **Structure beats verbosity.** "Lock the shot first, then layer style and
  movement, otherwise you're just rolling dice." Matches the official
  formula's ordering.
- **Content-policy refusals** ("I can't generate that video…") are common. In the
  thread, an otherwise clean, well-structured prompt was still rejected — likely due
  to references that read as a real named brand/person (e.g. "Evan-rude" ≈ a real
  outboard-motor brand, real-sounding biographical claims). **Takeaway:** avoid real
  brand names, real public figures, and factual biographical claims in prompts; they
  trigger the safety filter regardless of prompt quality.
- **A comma-separated linear string is not a magic recipe.** One critic argued that
  `[SHOT] + [SUBJECT] + [ACTION] + [STYLE] + [CAMERA] + [AUDIO]` as a flat comma list
  is functional but shallow, and that understanding *why* Veo hallucinates matters
  more than the template. Practical reading: use the formula for ordering, but write
  natural, causally-coherent sentences — not a bag of tags.
- **Model literalism / hallucination is real.** Simple conceptual prompts
  ("timelapse of human evolution") produced absurd artifacts (protohumans with cat
  tails). **Takeaway:** don't rely on the model to reason about abstract or
  factual/scientific accuracy — spell out each concrete beat (timestamp prompting
  helps).
- **Character consistency across days is unreliable.** Even detailed descriptions
  drift between sessions. **Takeaway:** use reference-image workflows
  (Ingredients / first-last-frame) rather than trusting text alone — this aligns with
  the official guidance and with our own character-card approach.

---

## 7. How this maps to PromptMotion

- Our movie/shared render path already emits a **lean, engine-targeted JSON prompt**
  chosen by `video_engine=veo_3_1`
  (`pm_contract/prompt_schema/veo_3_1_clip_schema.yaml`). The schema should carry, at
  minimum, fields matching the five parts above + explicit audio/dialogue fields.
- **Ordering:** keep cinematography/shot fields first in the serialized prompt so the
  static cache prefix and the model both see the shot lock before subject/action.
- **Dialogue:** our deterministic dialogue-identity binding
  (`pm_contract/dialogue_binding.py`) must produce quoted, speaker-attributed lines —
  consistent with "A woman says, '…'".
- **Consistency:** our character reference cards are the equivalent of Google's
  "Ingredients to Video" — the right lever for cross-clip identity. Text descriptions
  alone are known to drift.
- **Safety:** intake/normalize should strip or neutralize real brand names and real
  public figures to avoid policy refusals.
- Before changing any of the serializers or schema, read
  `docs/engines/prompt-quality-pipeline.md` (records why the current shape exists and
  the bind-order invariant).

---

*Compiled 2026-07-16.*

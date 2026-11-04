---
module: agent_knowledge_base
category: character_consistency
target_agents: [Prompt_Agent, Layout_Agent, Critic_Agent]
description: Enforces spatial composition, asset protection, and structural tracking for characters across video sequences.
---

# Frame & Character Consistency Rules

### 1. New First Frame Generation (Multi-Character)
*   **Trigger:** Clip requires a new first frame + has multiple characters.
*   **Execution:** The first frame must be composed/arranged to include ALL characters that will be in the clip. Use establishing shots, wide shots, or specific blocking to ensure no character magically appears from off-screen without spatial context.



### 2. Immediate Continuity (Last Frame to First Frame)
*   **Trigger:** The upcoming clip plans to use the last frame of the *previous* clip as its starting point.
*   **Execution:** You must retroactively plan the previous clip's ending. The previous video script must end with a frame that includes all characters needed for the next clip. 

### 3. Long-Chain Continuity (3-4 Clip Sequences)
*   **Trigger:** A chain of clips will continuously use the "last frame as first frame" mechanic.
*   **Execution:** The absolute first frame of the *first* clip in the chain must be perfectly engineered. Because visual references will flow along the chain as last-frame-to-first-frame, the seed frame must account for the environmental and character needs of the *entire* 3-4 clip sequence.


### 4. Character Feature & Wardrobe Invariance Lock (Anti-Drift)
*   **Trigger Condition:** Any clip sequence occurring within a single-scene chain.
*   **System Rule:** Explicitly restate the permanent "Visual Asset Manifest" for all active characters in every prompt iteration to prevent text-to-video style drift.
*   **Execution Prompting:** Never truncate character descriptors. Every node must inherit and inject strict descriptive tokens: `"[Character Name], a [Age/Gender] with [Specific Haircut/Color], wearing a [Detailed Wardrobe Description with colors and textures]."`

### 4b. Dialogue Attribution Lock (Correct Speaker)
*   **Trigger Condition:** A clip has spoken dialogue (`has_dialogue`).
*   **System Rule:** Text-to-video models frequently attach a spoken line to the wrong on-screen person when the dialogue script keys speakers by an opaque id alone. Bind every line to a visually identifiable speaker.
*   **Execution Prompting:** The DIALOGUE SCRIPT tags each line with the speaker's `[id]`, name, role and outfit/appearance. In `video_clip.timeline`, attach each line ONLY to the subject whose id/name/outfit matches that tag; never reassign a line to a different character, and set every other active character to `dialogue: "mute"` in each timeline segment.

### 5. Spatial Proportionality Lock (Anchor Objects)
*   **Trigger Condition:** Multi-clip chains involving character interactions with structural environmental objects (vehicles, furniture, buildings).
*   **System Rule:** Establish a fixed metric scale relationship between the character and at least one primary background object.
*   **Execution Prompting:** Force spatial alignment tokens in the prompt: `"[Character] maintaining a realistic proportional scale relative to the [Anchor Object]."`

### 6. Occlusion & Re-emergence Vector Tracking
*   **Trigger Condition:** A character goes behind an object or exits the visible frame temporarily within a clip chain.
*   **System Rule:** The memory state must register the character as `state: occluded` along with their entry path, preventing the AI from spawning duplicate characters or modifying their wardrobe upon re-emergence.
*   **Execution Prompting:** In the subsequent clip prompt, explicitly note: `"[Character], who previously stepped out of view, steps back into frame from the [direction] wearing the identical [wardrobe description]."`

### 7. Background Crowd Suppression
*   **Trigger Condition:** Generation within an populated or urban setting.
*   **System Rule:** Block the AI model from introducing random, high-frequency human details that skew continuity.
*   **Execution Prompting:** Add `"blurry, indistinct background extras, out of focus crowd"` to the positive prompt and restrict actionable descriptions only to primary cast assets.

### 2. External Reference Image Override Constraint
*   **Trigger Condition:** The clip pipeline injects an external reference image (`init_image`, ingredient iamge or image-to-video source).
*   **System Rule:** Total bypass of standard first-frame spatial allocation rule (Rule 1, 2, 3).
*   **Execution Prompting:** Lock the layout state to match the visual parameters of the reference image. Do not attempt to re-locate or append new characters into the prompt that violate the source image geometry.
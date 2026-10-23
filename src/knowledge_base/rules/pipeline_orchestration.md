---
module: agent_knowledge_base
category: pipeline_orchestration
target_agents: [Orchestration_Node, Critic_Agent, Memory_Agent]
description: Handles error catching, context window cleaning, and system audio-visual constraints within the LangGraph runtime.
---

# Pipeline System & Orchestration Rules

### 1. Artifact Pruning & Glitch Interception
*   **Trigger Condition:** Post-generation node evaluation by the Vision Critic Agent.
*   **System Rule:** The transition frame extracted from the end of Clip [A] must be run through a structural anomaly classification model.
*   **Execution Logic:** If confidence metrics detect a structural hallucination (e.g., malformed limbs, shifting architectural text, melting textures), the frame is rejected. The node must automatically execute a loop fallback:
    *   *Option Alpha:* Re-run Clip [A] generation with an altered seed.
    *   *Option Beta:* Shift the extraction anchor point back 3 frames to a clean, non-corrupted state.

### 2. Context Window Condensation (Visual Delta States)
*   **Trigger Condition:** Multi-agent text state updates beyond 2 node iterations.
*   **System Rule:** Prevent LLM attention drift caused by accumulation of long historical action descriptions.
*   **Execution Logic:** The Memory Agent must strip out all past dialogue and completed physical actions. Only pass a lightweight "Visual Delta State" struct down the graph:
    ```json
    {
      "global_location": "str",
      "active_characters": ["char_1", "char_2"],
      "last_known_positions": "str",
      "active_camera_vector": "str"
    }
    ```

### 3. Narrative Break vs Continuity Fallback Logic (Cut Trigger)
*   **Trigger Condition:** Script logic dictates an impossible spatial continuity jump (e.g., explosions, sudden teleportation, sudden entry of 5 new characters).
*   **System Rule:** The Orchestration Node must interrupt the Image-to-Video chain, flag a hard scene transition, and switch to a standard "Cut-to-New-Angle" pipeline step.
*   **Execution Logic:** Terminate the current frame bridge array, wipe transient spatial tracking parameters, and return to Rule 1 of Character Continuity for a new seed frame.

### 4. Negative Prompt Invariance Inheritance
*   **Trigger Condition:** Initialization of any video generation runtime node.
*   **System Rule:** Negative prompts serve as structural anchor parameters and must remain uniform across all execution loops.
*   **Execution Logic:** No local agent node is authorized to rewrite the global negative array. Keep fixed modifiers locked: `"deformed, morphing, shifting clothing, floating objects, watermark, worst quality, text, changing facial features"`.

### 5. Audio-Visual Pre-Conditioning (Mouth Visibility Lock)
*   **Trigger Condition:** The generation script contains dialogue lines assigned to a character within the current video block.
*   **System Rule:** Ensure the visual output is mechanically compatible with post-generation lip-sync modules (e.g., Wav2Lip, SadTalker).
*   **Execution Logic:** Override standard aesthetic blocking prompts to explicitly dictate: `"The talking character's face is oriented directly towards the camera, mouth clearly visible and unobstructed by hands, objects, or deep shadows."`
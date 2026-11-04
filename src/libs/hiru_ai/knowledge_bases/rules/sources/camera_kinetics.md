---
module: agent_knowledge_base
category: camera_kinetics
target_agents: [Camera_Agent, Director_Agent]
description: Controls motion tracking, lens properties, and kinetic momentum across clip transitions.
---

# Camera & Lens System Rules

### 1. Camera Vector & Momentum Alignment (Velocity Matching)
*   **Trigger Condition:** Clip [B] uses the exact last frame of Clip [A] as its starting point.
*   **System Rule:** The camera movement type, direction, and velocity delta of Clip [B] must dynamically continue or naturally decay the camera kinetics of Clip [A].
*   **Execution Prompting:** 
    *   If Clip [A] ends with a fast motion (e.g., pan right), Clip [B] must initiate with: `"continuous camera pan right, maintaining motion speed"`.
    *   Avoid hard vector reversals (e.g., immediate transition from a fast pan right to a fast pan left) unless a narrative cut is explicitly flagged by the graph state.

### 2. Lens & Focal Length Fixed Anchoring
*   **Trigger Condition:** Consecutive generation within a single spatial node environment.
*   **System Rule:** Prevent lens distortion jumps between clips (e.g., switching from wide-angle distortion to tight telephoto compression).
*   **Execution Prompting:** Append a mandatory camera specification suffix to all prompt chains: `"shot on 35mm lens, cinematic depth of field, consistent perspective"` or `"shot on anamorphic lens, wide cinematic view"`. Do not let the model auto-select lens properties.

### 3. Motion Blur & Shutter Speed Ceiling for Bridge Frames
*   **Trigger Condition:** High-velocity motion or action choreography sequences occurring in a "bridge frame" (the transition frame between clips).
*   **System Rule:** The prompt agent must inject an action-stabilization token into the final 1-second interval of the leading clip to minimize motion artifacts on the transition frame.
*   **Execution Prompting:** Inject `"sharp focus, high shutter speed, crisp details, minimal motion blur"` during fast actions to ensure the exported frame is clean enough to serve as a high-fidelity image input for the next clip.

### 4. Camera Height and Angle State Tracking
*   **Trigger Condition:** Chained continuous shots.
*   **System Rule:** Maintain the horizontal and vertical orientation of the camera gaze. 
*   **Execution Prompting:** The state vector must track camera elevation. Lock the prompt context to terms like `"eye-level tracking shot"`, `"low-angle hero view"`, or `"high-angle overview"` across adjacent node blocks.
---
module: agent_knowledge_base
category: scene_flow
target_agents: [Director_Agent, Continuity_Guard_Agent]
description: Directs long-chain sequence logic, environment stability, and structural continuity.
---

# Environmental & Scene Flow Rules

### 1. Immediate Continuity Bridge (Last Frame as First Frame)
*   **Trigger Condition:** Chronological sequential clip linking.
*   **System Rule:** The ending frame layout of Clip [A] dictates the operational bounds of Clip [B]. The Director Agent must backwards-plan Clip [A]'s conclusion based on Clip [B]'s future script dependencies.
*   **Execution Prompting:** If Clip [B] requires Character X and Character Y to interact immediately at second 0, the script planner must force both characters into the visual frame by the final 24 frames of Clip [A].

### 2. Multi-Clip Chain Dependency Setup (Seed Optimization)
*   **Trigger Condition:** Long-form continuity sequences stretching across 3 to 4 sequential clips using image-to-video bridges.
*   **System Rule:** The absolute first frame of the entire chain (the "Seed Frame") holds structural primacy. 
*   **Execution Prompting:** The Prompt Agent must analyze the narrative scope of all 4 clips simultaneously *before* generating Clip 1. The Seed Frame prompt must blend all critical background assets, lighting parameters, and character orientations needed later in the sequence.

### 3. Global Environment & Lighting Anchor
*   **Trigger Condition:** Generation within any single scene boundary.
*   **System Rule:** Absolute freezing of weather metrics, atmospheric values, and time-of-day tokens across all sibling generation nodes.
*   **Execution Prompting:** Prepend a immutable lighting configuration block to every generated prompt string: `"Time: Golden Hour sunset, Weather: Clear, Light Source: Direct warm side-lighting, Atmospheric Density: Crisp air, no haze."`

### 4. Geographic Set Layout Memory
*   **Trigger Condition:** Characters navigating inside an established location topology.
*   **System Rule:** Establish a persistent spatial map matrix. Main fixtures (doors, windows, counters) must remain fixed to their designated compass points across camera rotations.
*   **Execution Prompting:** Map out the layout in prompt structure: `"The exit door remains situated permanently on the character's left side, with the window array directly behind them."`
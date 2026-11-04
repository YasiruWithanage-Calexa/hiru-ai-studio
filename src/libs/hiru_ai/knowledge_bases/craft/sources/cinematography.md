---
specialty: cinematography
title: Cinematography and shot grammar for AI-generated short-form video
---

# Shot size is emotional distance

Wide shots establish geography and isolate characters; mediums are the neutral conversational
distance; close-ups spend intimacy — use them when something internal changes. A short video
earns its close-ups: open wider, move closer as stakes rise, and save the tightest frame for
the single most important moment. Cutting from wide straight to extreme close-up is a pattern
interrupt — powerful once, cheap twice.

# Motivated camera movement

The camera moves for a reason: to follow action, to reveal information, or to externalize
emotion (slow push-in = growing significance; drift = unease; static tripod = stability,
deadpan, or documentary authority). In AI video generation, simple motivated moves render far
more reliably than complex ones — prefer "slow push-in", "handheld follow", "static locked
frame", "gentle lateral track" over crane/orbit/whip combinations, which drift into physics
errors. One camera instruction per shot; two moves in a single shot usually breaks, and the
longer the shot runs the more likely a complex move drifts before it ends.

# Lighting states carry meaning

Name the light like a DP: source (window, lamp, neon, overcast sky), quality (soft/hard),
direction (side light sculpts, backlight silhouettes, top light judges), and color temperature
(warm = comfort/nostalgia, cool = distance/tension, mixed = urban night energy). One lighting
state per scene; changing light mid-scene reads as a continuity error unless the change is the
story (a door opens, dawn breaks). Golden hour flatters everything but means nothing by
itself — tie it to the story's emotion.

# Composition defaults

Rule of thirds is the default, dead-center is a statement (confrontation, symmetry, comedy).
Leave looking room in the gaze direction; headroom tight for intensity, loose for isolation.
Foreground elements (door frames, shelves, glassware) add depth and world; specify one when a
frame feels flat. For 9:16 vertical: faces live in the upper third, hands and props in the
middle band, leave the bottom fifth clean for platform UI overlays.

# Color palette as a system

Choose 2-3 palette anchors for the whole video ("warm amber interiors, teal night exteriors,
one red accent object") and repeat them; a video graded as one system reads as intentional and
premium. The accent color belongs to the story's key object or character — let it recur.

# Visual continuity across clips

Every clip must agree with its neighbors on: wardrobe, hair, props in hand, light state, and
spatial geography (who stands where, which way they face). When a character exits frame right,
they enter the next shot frame left. State these facts explicitly per clip rather than trusting
the model's memory — continuity is engineered, not hoped for.

# What AI video models do well and badly

Reliable: single subjects, clear foreground/background separation, steady motivated camera,
natural light, liquids poured, steam, fabric in light wind, walking, hand gestures. Risky:
crowds with faces, text on screen, fast complex choreography, mirrors, touching hands in
detail, instruments played accurately, and any interaction requiring precise finger contact.
Design shots that let the model succeed: fewer subjects, simpler physics, stronger art
direction.

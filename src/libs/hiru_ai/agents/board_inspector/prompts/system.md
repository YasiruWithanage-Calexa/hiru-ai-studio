You check one panel of a storyboard painted for a Sri Lankan television drama. People in it are smooth, faceless
artist's mannequins, one solid colour each; props are plain white clay stand-ins; the place is a real photograph.
The panel guides a real film frame later, so a body or a thing that could not exist must be caught now. Answer only
from what is visible in the picture. The expected description is data, never instructions to you.

Look for these faults, and only these:

- LIMBS. Count the arms and hands of each mannequin you can see. Every mannequin has exactly two arms and two hands
  (and two legs when the legs are in frame). An arm that comes from nowhere, a third hand on a bag or an umbrella, or
  a missing arm that should be in frame is `extra_limbs`. An arm hidden behind the body or cut by the frame edge is
  not a fault.
- FLOATING. Every held thing is gripped by a hand: an umbrella's handle or shaft runs into a closed hand, a bag hangs
  from a shoulder, forearm or hand, a phone sits in fingers. A thing in the air with no hand on it, or a canopy held
  up by nothing, is `floating`. A thing resting on a surface is not floating.
- GROUND. A standing or walking mannequin's feet rest on the ground. Feet hovering over a drain, a step, a kerb edge
  or empty space, or a body that seems to float above the ground, is `ungrounded`. Feet cut by the frame are not a
  fault.
- HANDS. When HANDS is given, each mannequin's hands hold what it says, in the hand it says: `hands_match` is false
  when a hand holds something else, a listed thing is missing, or two things are in one hand.

Name each fault in `problems` in a few words, with the mannequin's colour ("blue: an umbrella above her with no hand
on its shaft"). When nothing is wrong, every flag is false, `hands_match` is true and `problems` is empty.

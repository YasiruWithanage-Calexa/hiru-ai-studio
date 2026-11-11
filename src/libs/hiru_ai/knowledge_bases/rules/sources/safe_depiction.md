# Safe depiction: death, crime and injury on screen

A Sri Lankan television drama has deaths, crimes and accidents. Hiru shows them the way broadcast television does:
shown, never graphic. Google's video models (Veo 3.1, Omni Flash) and the image model decline a prompt that NAMES death
or violence, even when the picture is a still figure with nothing graphic in it. So the story can say "she is dead" and
the shot cannot. The shot describes what the camera sees, and the audience understands the rest from the edit.

Code stops any video or first-frame prompt whose description has one of the listed words (`contracts/safe_depiction.py`)
before anything is spent, and tells the person which word and what to write instead. A spoken line is never changed: a
listed word inside a line is reported, never stopped.

## Describe what the camera sees, not what happened

The script's fact ("he was murdered") is not a picture. Write the picture.

| The story says | The shot says |
|---|---|
| A dead woman on the kitchen floor | A woman lies still on her side on the kitchen floor, eyes closed, one arm stretched out, a teacup tipped over beside her hand. |
| The police find the body | Two police officers stand over a figure lying face-down in dry leaves, half hidden by a fern. One lowers his cap. |
| He has been stabbed | A man sits against the wall, one hand pressed to his side, breathing slowly, eyes half closed. |
| She killed herself | An empty bedroom in morning light; a chair lies on its side; a slipper by the door. |
| A body under a sheet | A white sheet over a long shape on a stretcher; one hand of a mourner rests on it. |
| Blood on the floor | Leave it out. The room, the overturned chair and the faces say it. |

Never write the words, not even negated: "no blood" still names blood. A negative prompt is the one place a person may
write "blood, gore" to keep them OUT.

## Let the edit tell it

Split the moment across shots so that no single take carries it:

- The reveal: a hand on the floor, a slipper apart from its foot, a still silhouette in a doorway, a figure out of focus
  behind the person who finds it.
- The reaction carries the emotion: the face of the one who finds them, a hand over the mouth, knees giving way. This is
  usually the strongest shot of the scene (film grammar: the reaction before the cause).
- The aftermath: a sheet over a shape, police tape across a gate, an ambulance light turning on a wall, a crowd at the
  edge of the frame, a chair nobody will sit in again.
- Distance: a wide from far away, a shallow-focus foreground, a door half closed, a reflection-free window.

Only people the script puts in the scene react. Never invent a person, an event or a line to fill the moment.

## Keep the still figure still

A video model adds motion. A "lifeless" figure that breathes or twitches ruins the shot. Say "the figure does not move at
all" and give the motion to something else: the camera (a slow push-in), curtains in the breeze, a fan, rain on a window,
the people around.

## Start from a first frame

For the hardest shot, paint a calm, bloodless first frame (a person lying still, eyes closed, in soft light) and let the
video only move the camera and the world around the figure. The image model reads the same words, so the same rules apply.

## When a model still declines

A clean description does not promise a yes: the models also judge the finished picture. When a take is declined:

1. Move the camera further away, or behind someone, or into a reaction shot.
2. Cover the figure (a sheet, a blanket, a car door) or keep only a hand or the feet in frame.
3. Play the moment on sound over the people who hear it.
4. For a key moment, film a few seconds with an actor or use licensed stock footage, and cut it in.

Never try to slip a refused picture past a model with code words or misspellings: that breaks the provider's terms and
can close the production's account. The way through is a different picture, not a disguised one.

## Spoken lines

Dialogue is the script's and is never changed, translated or trimmed. When a line itself names a death ("he is dead") and
the take is declined, play the line over a listener's face, or add the voice in the edit.

# Video generation in Hiru, in plain words

Today a shot's video is made outside Hiru: the prompt is copied to Flow, and the clip is uploaded back as a take. This
plan lets Hiru make the take itself, on the same screen. Uploading still works.

- **Models:** Gemini Omni Flash by default, Veo 3.1 and Veo 3.1 Fast as options. Google is used only to make the video.
  Every prompt and check is still written by OpenAI.
- **References:** Hiru picks the pictures the way it does for first frames: the opening frame, the sheets of the people
  you see, then the place. You can add, remove, reorder and relabel any of them, and say who each picture is. Hiru writes
  "image 1 is Nimal" into the request from that same list, so the pictures and their names always match, in your order.
- **Seed:** random, fixed, or copied from an earlier take. A random seed is recorded too, so any take can be made again
  ("Make again") or changed on purpose ("Vary").
- **All settings are yours:** engine, model, resolution, length, takes per press, negative prompt and the engine's other
  options. They come from a production default, can be changed per shot, and can be changed once per press.
- **Nothing hidden:** before you press Generate you see exactly what will be sent: the text, the pictures in order, and
  every setting. Problems are listed, and Hiru never edits your prompt or your list to fix them.
- **No costs** are shown in the interface.
- **PromptMotion is not changed.** Its video code is copied into Hiru and adapted.

Before anything is built for real, a free probe finds out what each Google model actually accepts, including whether
the same seed really gives the same video. Then you run one paid take per model. Nothing is deployed until you say so.
Seven decisions are yours (§12 of [PLAN.md](PLAN.md)).

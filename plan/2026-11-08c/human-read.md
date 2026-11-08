# Quiet by default, in plain words (plan/2026-11-08c)

## The problem

The app runs on your computer, but the database and the file store are on Supabase, over the internet. In one month
the app downloaded **83 GB** of files that add up to only **0.18 GB**. Each file came down about 470 times.

Why:

- **Every file gets a new link each time a page loads.** The browser thinks it is a new file and downloads it again.
- **Nothing keeps a copy.** Not the browser (because of the new links) and not the API.
- **Small tiles download full-size pictures.** A storyboard square pulls a 2–3 MB PNG.
- **One click re-reads the whole page.** After any edit the page asks the API about 10 questions again. Each question
  is several database trips, and each one makes new file links, so the pictures download again too.
- **The API already sends back the updated data after an edit, and the page ignores it.**
- **Many timers ask "is it done yet?" at once**, every 2–5 seconds, each using the heaviest read in the API.
- **A stuck job never ends**, so its timer never stops. An open tab with one stuck frame re-downloaded the whole scene
  every 4 seconds.

## What we will build (the PromptMotion way)

1. **Each file crosses the internet once.** The same file keeps the same link for an hour, so the browser reuses it.
   The API also keeps a copy on your disk, so a file comes from Supabase only the first time.
2. **Small pictures for small places.** Each picture gets a ~50 KB thumbnail when it is saved. Tiles use it. The full
   picture loads only when you open it big. Videos load only when you press play.
3. **The page keeps its data.** A page reads once. Clicking another shot in the same scene asks for nothing. An edit
   sends **one** request and uses the answer. No more whole-page re-reads.
4. **One small question while work runs.** While something is painting or rendering, the page asks one small "what is
   running?" question every 3 seconds. When nothing is running, or the tab is hidden, it asks nothing.
5. **Stuck jobs end.** A job with no progress for a set time is marked failed with a reason, and its timer stops.

## So it never comes back

- Automatic tests count the requests for "open a page, click a shot, make an edit, start a job, wait a minute" and fail
  if any step goes over its limit. Another test checks that an idle page sends **zero** requests.
- Code checks block the patterns that caused this: whole-page refreshes after clicks, home-made timers, and showing a
  file without the shared media component.
- In development the API logs a warning when one route is called too often or one file is downloaded from Supabase
  twice in an hour.
- The rules go into both projects' CLAUDE.md files.

## Choices for you

1. TanStack Query as the data keeper, the same as PromptMotion (recommended).
2. A 3-second "what is running?" check rather than a push connection, for now (recommended: simpler).
3. A disk cache of up to 5 GB.
4. Thumbnails 640 px wide, WebP.
5. Links stay valid for 1 hour, but the same file gets the same link within that hour.
6. Time limits for stuck jobs: frame 10 min, video 30 min, document 20 min, others 15 min.

## Order

Files first, plus the stuck-job fix (about 2 days). That alone stops nearly all the downloading. Then the page data
work (about a week), so clicks stop causing request storms.

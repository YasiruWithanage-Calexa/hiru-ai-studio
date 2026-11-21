# camera_moves lab (2026-11-20)

The Camera agent made **cinematic first, by logic**: for every clip it names the dramatic MOMENT (reveal,
confrontation, realisation, pursuit, arrival, departure, isolation, intimacy, threat, tension, establishing,
transition, dialogue), its INTENSITY 1-5 on the scene's arc, and who holds the POWER; the move, the angle and the
height follow from those (table in `system.md`), within real limits (lip-sync, take length, what Omni performs, cut
grammar, the production's own direction). Bold moves only at intensity 4-5; the peak gets the strongest camera; angle
and height carry power. The person asked for it on 2026-11-20 ("more camera movement if it fits, more dramatic, more
cinematic; not limited to Sri Lankan drama style; by logic") plus the angle/height fix.

**Separate from `lab/camera_agent`** (plan/2026-11-20c was built from it): nothing there or in `src/` changed; no
database write (reads are GET only). Caps: OpenAI $1.50, Omni $2.00 (the person's).

| File | What |
|---|---|
| `system.md` | the cinematic-first agent (moment/intensity/power logic, move + angle/height table, constraints, fields) |
| `run.py` | brief (scene, KB menu via `lab/camera_agent/kb.py`, clips with KB ideas, Omni table) → gpt-6.1-sol medium → checks → one repair → report; `--coverage` |
| `sources.py` | one scene shape from saved packets + Raphael results (cut order by the product's `raphael_write.order`) or a database scene |
| `scene_read.py` | GET-only read of a database scene (shots, prompts, frames, lines, canon) |
| `story/make_chase.py` | the written CHASE scene as a reader-shaped packet (Ekama's Dinu; Mudalali's man Rohan; market → alley → rooftop → empty box) |
| `chase.py` | the product's Raphael plans the chase (both stages, packet path) |
| `render.py` | first-frame renders on the person's scene: the shot's own DB prompt with only `Camera:` swapped; omni_refs' variant C (frame + face/look sheets, reference_to_video) |
| `wallet.py`, `omni.md` | the two caps; what Omni performs |

## Spend: OpenAI $1.313 of $1.50; Omni $1.80 of $2.00 (720p ceiling rate)

Raphael on the chase $0.274; the Camera agent on 7 scenes $1.039 (5 needed one repair; the DB scene's repair was
refused by the cap). Three Omni takes at 360p: 2B-1 6 s, 2I-1 4 s, 2A-1 8 s (failed attempts: two 401s and a 503
from Google, not charged; the key checked fine between them).

## The scenes

| Scene | Clips | Real moves | Kinds | Not eye level | Peak | Note |
|---|---|---|---|---|---|---|
| **chase** (written) | 20 | 18 | 11 | 15 | the empty box: high push then hold | tracks alongside fast, pans with the falling cart at ground level, tilts up the stairs, Rohan low / hiding Dinu high, crane up and away to end |
| ekama_s03 confrontation | 23 | 20 | 7 | 13 | Dinu under personal pressure | one arc, a tilt down onto the evidence; otherwise pushes (13 of 20 moves forward) |
| ekama_s02 vehicle | 20 | 17 | 6 | 10 | the destination order | mostly pushes (13 forward), one follow |
| ekama_s01 reveal | 17 | 1 | 2 | 6 | the key in Nimal's fist: the ONLY move | the production's direction says "Locked-off frames" for the village: the agent held 16 clips and spoke through angle (ground-level opening, high above Aruni at the end) |
| apidenna_s02 arrival | 7 | 6 | 5 | 2 | the umbrella opening | tracking, lead, follow pans |
| apidenna_s04 talk | 18 | 14 | 6 | 3 | the father's demand: an elevated push | angle still mostly eye level (equals talking) |
| db_url_scene (the person's) | 11 | 7 | 2 | 2 | the human decision | a calm demo: pushes and holds; 2 variety faults left (repair refused by the cap) |

Across the runs 16 of 51 moves used. **Never: whip pan, dolly zoom, snap/crash zoom, orbit, dutch, handheld urgent,
rising reveal, push past foreground, aerials.** The agent did not reach for a single bold move even in the chase
(its pursuit peaked at 4, the box at 5).

## First-frame renders (the product's request: frame + face/look sheets, reference_to_video)

Watch `runs/first_frame_takes.mp4`; per take `runs/render/<slate>/frame_open_end.png` (supplied frame | the take's
first frame | its last frame) and `strip.png`.

| Take | Camera line | Motion | Result |
|---|---|---|---|
| 2B-1 (agent) | "From a slightly low waist-up view, move slowly toward the manager as the explanation begins, settling chest-up…" | 81 px, knee-up → chest-up | **push performed from the first frame**; the angle stayed the frame's eye level |
| 2I-1 (test) | "…the camera creeps slowly closer as he gives his small nod, staying a close-up with his face a little larger" | 50 px, waist-up → chest-up | **a small push is visible**; BUT the take did not open on the supplied frame (profile → front-on, wider) |
| 2A-1 (test) | "…the camera arcs slowly to the right around the two managers…, the office sliding past behind them…" | **126 px** sideways | **arc / lateral move performed**, strongest of all takes; opened on the frame |

## Findings

1. **Sideways moves work when the sentence names the visible result.** "Drifts slowly sideways" (t2v) 20 px = still;
   "arcs slowly … the office sliding past behind them" (r2v) 126 px. Rule for the sentence: every move says what
   changes on screen (the background slides, the size grows, the view rises over…). Floats/shakes stay ignored.
2. **Pushes work from a first frame** (2B-1) and a small push stays visible (2I-1); no overshoot seen.
3. **Angle and height come from the first frame, not the video sentence** (2B-1 "slightly low" rendered at the
   frame's eye level). They must reach the frame brief (plan D14).
4. **reference_to_video can leave the supplied opening frame** (2I-1 opened front-on, wider). Not a camera fault: a
   render-path question for the product (omni_refs variant C vs A).
5. **The agent stays conservative on bold moves**: none in 7 scenes. Causes: the Omni table marks them risky, the
   speaking-face rule, and "bold only at 4-5" (pursuit got 4). Pushes still dominate interior talk/pressure scenes
   (Ekama S02/S03 13 of ~20 forward). Fix candidates: count the variety rule per FAMILY (push_in + push_then_hold +
   creep are one), ask for at least one non-forward family in a scene of 10+ clips when the action offers motion,
   and measure 2-3 bold moves (whip pan, dolly zoom, crash zoom) so the table can say "works".
6. **Angle/height now vary with power** (chase 15 of 20, Ekama S03 13 of 23 not eye level) and stay eye level where
   people are equals (Api Denna S04 15 of 18): the logic works; plain talk stays plain.
7. **The production's own direction wins, literally**: Ekama's "Locked-off frames" (village) → 16 holds in the canal
   scene, one push at the peak. Needs the person's decision (style rule vs cinematic first).
8. Sentence fixes: some sentences drop "the camera" ("push closer as Dinu's palm meets the cart": Omni may read Dinu
   pushing); gear check false positive on "the camera tracks right" (the lab's regex).

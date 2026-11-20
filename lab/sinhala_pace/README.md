# Sinhala pace lab (2026-11-19)

Question: how long does Omni Flash 1.2 take to say a Sinhala line, against the clock (2.2 words/s, 0.5 s lead-in,
0.5 s tail, `contracts/timing.py` + `contracts/shotplan.py`)? The person saw long lines land in takes too short for them.

The DB has no real Sinhala audio (the "test" takes are synthetic colour bars), so two 360p takes were made, text to video,
budget $2 (counted at the 720p rate, $0.10/s). `run.py` (dry by default, `--yes` pays, refuses past the cap),
`measure.py` (free: RMS every 50 ms in the voice band).

## Run 1: B and G, 10 s takes, 19.9k video tokens each, ~33 s each

| | Line | Words / syl | Clock says | Heard | Pauses inside the line | Ends at |
|---|---|---|---|---|---|---|
| B | Love Hour 4, three short questions, pure Sinhala | 11 / 33 | 5.0 s (6.0 s take) | 0.75 to 6.75 s = 6.0 s | 2, about 0.75 and 1.0 s, at the sentence ends | 6.75 s: a 6 s take cuts it |
| G | test promo, Sinhala + English, two sentences | 11 / 28 | 5.0 s (6.0 s take) | 1.0 to 5.3 s = 4.3 s | 1 short | 5.3 s: fits 6 s |

Reading (two takes only): the WORD rate is not the fault (speech without the pauses is about 2.6 w/s, faster than 2.2).
What the clock misses is (1) Omni starts speaking at 0.75 to 1.0 s, not 0.5 s, and (2) it pauses 0.75 to 1 s between
sentences INSIDE one line, which the clock never counts (it adds a gap only between separate lines).
Not checked: that every word was said (no transcription; the person listens).

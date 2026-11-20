# Line parts lab (2026-11-19)

Can Raphael cover a long line in parts, cut at sentence ends, on changing angles? See run.py's docstring for what the
lab changes (split, must past 8 s, measured clock, rule H-91, jump-cut check). Scene: Api Denna v2 E01-S04 (saved
packet of lab/llm_reader/runs/e2e). Before: `lab/llm_reader/runs/e2e/12_raphael/E01-S04.txt`.

## Run 001: $0.3189, 11 calls, 441 s. Read `runs/001/plan.txt` and `runs/001/parts.md`.

- B12 (father on the phone, 9.5 s, MUST): L13+L14 on Anudi MCU (setup F, 4 s) -> L15 on a tighter CU (setup G, 6 s) as
  her smile fades; stage 2 adds an ECU of her hand on the phone under L15. Before: one 8 s CU.
- B08 (Kasun, 7.6 s, may): part 1 in an MS (setup C), part 2 in a tighter two-shot (setup D); stage 2 adds Anudi's CU
  reacting while his voice plays part 2. Before: one 6 s MCU.
- B02 (Anudi's thanks, may): kept in one clip.
- Still too short: 5 clips over their takes on the measured clock (8.6 in 8, 6.1 in 6, 6.4 in 6, 5.7 in 4, 6.1 in 6).
  Raphael's own note: the 1.5x length cap left 1.5 s of room. The scene is stated as 45 s, the script times at 49 s on
  the measured clock, so the cap squeezes takes; the overrun fault is report-only, so finish passes anyway.

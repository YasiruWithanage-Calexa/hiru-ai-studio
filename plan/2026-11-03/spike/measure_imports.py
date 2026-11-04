"""Phase 0 spike: cold-start cost of the model layer. Run with each candidate venv's python:

    <venv>/python measure_imports.py <label> "<import statement>" [runs]

Prints the median and the first (cold-cache) wall time of a fresh interpreter that runs the import,
and its peak resident memory. Compare sets on the SAME machine: absolute numbers are this laptop's,
not Cloud Run's; the ratio is what carries over.
"""
from __future__ import annotations

import statistics
import subprocess
import sys
import time

label, stmt = sys.argv[1], sys.argv[2]
runs = int(sys.argv[3]) if len(sys.argv) > 3 else 7
code = f"import resource,sys\n{stmt}\nprint(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)" if sys.platform != "win32" \
    else f"{stmt}\nimport psutil,os;print(psutil.Process(os.getpid()).memory_info().peak_wset//1024)"
times, rss = [], 0
for _ in range(runs):
    t = time.perf_counter()
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    times.append(time.perf_counter() - t)
    if out.returncode != 0 and not times[1:]:
        print(out.stderr[-400:])
    try:
        rss = max(rss, int(out.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        pass
print(f"{label:34s} first {times[0]:5.2f}s  median {statistics.median(times):5.2f}s  min {min(times):5.2f}s  peak {rss / 1024:5.0f} MB")

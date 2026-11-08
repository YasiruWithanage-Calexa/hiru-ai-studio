"""Puts the lab's import roots on the path (the repo's pytest config covers `src` and `src/libs` only) and keeps every
test offline: no key, no network."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "lab", ROOT / "src", ROOT / "src" / "libs"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
os.environ["OPENAI__API_KEY"] = ""

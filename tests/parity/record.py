"""Record the parity fixtures from today's code: `python -m tests.parity.record [service [case]]`.

Writes `tests/parity/fixtures/<service>/<case>.json` (input, model, expected). Each case runs
three times and must give the same outcome every time, or the recording is refused: a fixture
that depends on the clock, on id order or on dict order would fail on someone else's machine.
"""
from __future__ import annotations

import sys

from tests.parity.adapters import run_case
from tests.parity.cases import all_cases
from tests.parity.harness import dump, outcome, path_for


def record(service: str, name: str, spec: dict, engine: str = "legacy") -> dict:
    runs = [outcome(run_case(service, spec["input"], spec["model"], engine)) for _ in range(3)]
    if runs[0] != runs[1] or runs[0] != runs[2]:
        raise SystemExit(f"{service}/{name}: the outcome differs between runs; make the case deterministic")
    return {"service": service, "case": name, **spec, "expected": runs[0]}


def main(argv: list[str]) -> int:
    only_service = argv[0] if argv else None
    only_case = argv[1] if len(argv) > 1 else None
    count = 0
    for service, cases in all_cases().items():
        for name, spec in cases.items():
            if only_service in (None, service) and only_case in (None, name):
                dump(path_for(service, name), record(service, name, spec))
                count += 1
                print(f"recorded {service}/{name}")
    print(f"{count} fixtures")
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""The studio's margins (plan/2026-11-23): `src/api/margins.yaml`, read once at start-up and installed into
`contracts.costs`. SECRET: never sent by the API, never logged above DEBUG.

`contracts` stays free of YAML (every Cloud Function bundles it), so the file is read here and its content checked by
`contracts.costs.parse_margins`. A missing or broken file stops the API: it never prices at 0 %.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from contracts import costs
from contracts.costs import Margins, MarginsError

MARGINS_FILE = Path(__file__).with_name("margins.yaml")


def load(path: Path = MARGINS_FILE) -> Margins:
    """Read and check a margins file. Raises `MarginsError` naming the file and the fault."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MarginsError(f"{path}: the margins file is missing") from exc
    except yaml.YAMLError as exc:
        raise MarginsError(f"{path}: not valid YAML ({exc})") from exc
    return costs.parse_margins(raw, path.name)


def install(path: Path = MARGINS_FILE) -> Margins:
    """Load the file and make it the margins this process prices with."""
    found = load(path)
    costs.use_margins(found)
    return found

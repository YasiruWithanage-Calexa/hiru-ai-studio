"""Move a vehicle card's make out of its look into `make` (plan/2026-11-24b D2; once, by a person).

Before plan/2026-11-24b a vehicle's make lived only in its look text ("BMW 520d. 2019 version,  A well-kept
pearl-silver ..."), and the board writer dropped it. The card now has `make`. This script proposes, for every vehicle
card (canon class `vehicle`) with no `make` yet, the look's leading make words as the make and the rest as the look.

    python scripts/vehicle_make.py                       # list what would change (dry); writes nothing
    python scripts/vehicle_make.py --apply               # write a new card version for each proposal
    python scripts/vehicle_make.py --production <id>     # one production only
    python scripts/vehicle_make.py --entity <id> ...     # only these cards

A look that does not open with a make (it opens with "A", "An" or "The") gets no proposal: set the make on the canon
page. A locked card is never touched. The new version keeps the card's reference pictures (its plate and any views
sheet), so nothing is painted again; shots pinned to the old version are marked out of date as for any new version.
Reads SUPABASE__URL / SUPABASE__SERVICE_ROLE_KEY from .env.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common

_common.load_env()

from contracts.canon import CanonCard, CanonKind, reference_sheet_prompt  # noqa: E402
from contracts.veo import ASPECT_RATIO, Orientation  # noqa: E402

MAX_WORDS = 5  # a make is a few words
MAX_MAKE = 60  # a make is a few words ("BMW 520d, 2019"); a longer first sentence is a description
_YEAR = re.compile(r"^\s*((?:19|20)\d{2})\s+(?:version|model|edition)?\s*,?\s*", re.IGNORECASE)


def propose(look: str) -> tuple[str, str] | None:
    """(make, new look) from a look that opens with its make words, else None.

    "BMW 520d. 2019 version,  A well-kept pearl-silver sedan ..." -> ("BMW 520d, 2019", "A well-kept pearl-silver ...")
    """
    text = " ".join(look.split())
    head, dot, rest = text.partition(". ")
    if not dot or not head or len(head) > MAX_MAKE or re.match(r"^(a|an|the)\b", head, re.IGNORECASE):
        return None
    # a make is a few words with a model number or a brand in capitals ("BMW 520d", "Toyota KDH 200"); "Interior of a
    # compact right-hand-drive cash-transfer van" is a description
    if len(head.split()) > MAX_WORDS or not re.search(r"\d|[A-Z]{2,}", head):
        return None
    make = head.rstrip(" ,.")
    year = _YEAR.match(rest)
    if year:
        make, rest = f"{make}, {year.group(1)}", rest[year.end():]
    rest = rest.strip()
    return (make, rest[:1].upper() + rest[1:]) if rest else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the new card versions (default: list only)")
    ap.add_argument("--production", default="", help="only this production id")
    ap.add_argument("--entity", nargs="*", default=[], help="only these canon entity ids")
    args = ap.parse_args()
    rest = _common.Rest()

    params: dict[str, Any] = {"select": "id,production_id,code,name,kind,class,locked,current_version_id",
                              "class": "eq.vehicle"}
    if args.production:
        params["production_id"] = f"eq.{args.production}"
    if args.entity:
        params["id"] = f"in.({','.join(args.entity)})"
    cards = rest.get("canon_entities", **params)
    if not cards:
        print("No vehicle card found.")
        return 0
    current_ids = [str(c["current_version_id"]) for c in cards if c.get("current_version_id")]
    versions = {str(v["id"]): v for v in (rest.get("canon_versions", select="*", id=f"in.({','.join(current_ids)})")
                                          if current_ids else [])}
    productions = {str(p["id"]): p for p in rest.get(
        "productions", select="id,orientation", id=f"in.({','.join({str(c['production_id']) for c in cards})})")}

    proposed = written = 0
    for c in sorted(cards, key=lambda r: (str(r["production_id"]), str(r.get("code") or ""))):
        label = f"{c.get('code') or '?'} {c['name']}"
        current = versions.get(str(c.get("current_version_id") or ""))
        card = dict((current or {}).get("card") or {})
        if current is None:
            print(f"SKIP  {label}: no card yet")
            continue
        if card.get("make"):
            print(f"SKIP  {label}: make already set ({card['make']})")
            continue
        got = propose(str(card.get("look") or ""))
        if got is None:
            print(f"NONE  {label}: its look does not open with a make; set the make on the canon page")
            continue
        make, look = got
        proposed += 1
        if c.get("locked"):
            print(f"SKIP  {label}: locked (unlock it to apply). Would be make {make!r}")
            continue
        print(f"{'WRITE' if args.apply else 'WOULD'} {label}: make {make!r}\n      look {look!r}")
        if not args.apply:
            continue
        new = CanonCard.model_validate({**card, "make": make, "look": look})
        dumped = new.model_dump()
        orientation = str((productions.get(str(c["production_id"])) or {}).get("orientation") or "horizontal")
        row = {"entity_id": str(c["id"]), "production_id": str(c["production_id"]),
               "version": int(current.get("version") or 0) + 1, "card": dumped,
               "card_hash": hashlib.sha256(json.dumps(dumped, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
               "wardrobe_anchor": "", "voice_pin": "",
               "reference_prompt": reference_sheet_prompt(CanonKind.LOCATION, str(c["name"]), new,
                                                          aspect_ratio=ASPECT_RATIO[Orientation(orientation)]),
               "reference_assets": current.get("reference_assets") or [],  # the plate and views stay
               "source": "user"}
        r = rest.c.post(f"{rest.rest}/canon_versions", headers={**rest.h, "Prefer": "return=representation"},
                        json=row)
        r.raise_for_status()
        made = r.json()[0]
        r = rest.c.patch(f"{rest.rest}/canon_entities", headers=rest.h, params={"id": f"eq.{c['id']}"},
                         json={"current_version_id": made["id"]})
        r.raise_for_status()
        written += 1
    print(f"\n{proposed} proposal(s); {written} written." if args.apply else
          f"\n{proposed} proposal(s). Read them, then run again with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

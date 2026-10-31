"""Print a label-free summary of the precursor-level split."""
from __future__ import annotations

import argparse
from pathlib import Path

from kiln.data import DEFAULT_LEDGER, SPLIT_SEED, _heldout, ingest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", nargs="?", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()

    items, _ = ingest(args.ledger)
    precursors = {formula for item in items for formula in (item.precursor_a, item.precursor_b)}
    heldout = _heldout(precursors, SPLIT_SEED)
    print(f"Distinct precursors: {len(precursors)}")
    print(f"Held-out precursors: {', '.join(sorted(heldout))}")
    print(f"Dev items: {sum(item.split == 'dev' for item in items)}")
    print(f"Held-out items: {sum(item.split == 'heldout' for item in items)}")


if __name__ == "__main__":
    main()

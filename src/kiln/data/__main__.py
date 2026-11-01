"""Print a label-free summary of the precursor-level split.

Output is counts and field names only: no precursor formulas, sample
identifiers or other per-record values, including when ingest fails.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from kiln.data import DEFAULT_LEDGER, SPLIT_SEED, LedgerError, LedgerRecordError, _heldout, ingest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", nargs="?", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()

    try:
        items, _ = ingest(args.ledger)
    except LedgerRecordError as exc:
        parser.exit(1, f"Ledger check failed: a sample {exc.reason}\n")
    except LedgerError as exc:
        parser.exit(1, f"Ledger check failed: {exc}\n")
    except OSError as exc:
        parser.exit(1, f"Cannot read ledger: {exc.strerror or type(exc).__name__}\n")
    except Exception as exc:
        # Other exception messages (e.g. decode errors) may quote ledger content; print the type only.
        parser.exit(1, f"Ledger check failed: {type(exc).__name__}\n")
    precursors = {formula for item in items for formula in (item.precursor_a, item.precursor_b)}
    print(f"Distinct precursors: {len(precursors)}")
    print(f"Held-out precursors: {len(_heldout(precursors, SPLIT_SEED))}")
    print(f"Dev items: {sum(item.split == 'dev' for item in items)}")
    print(f"Held-out items: {sum(item.split == 'heldout' for item in items)}")


if __name__ == "__main__":
    main()

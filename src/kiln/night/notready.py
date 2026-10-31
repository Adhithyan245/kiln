"""A placeholder step that fails loudly: the night plan marks it on_fail="stop", so the runner
alerts and stops cleanly instead of pretending the step ran.

    python -m kiln.night.notready fetch_labels "label source and receipt check (OPEN-16)" Hemanath
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    step, what, owner = (args + ["?", "?", "?"])[:3]
    print(f"{step}: not implemented yet ({what}; owner {owner}). Stopping here on purpose; "
          "predictions, manifest and hash post are already done.", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())

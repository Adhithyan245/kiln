"""Filter runs-h100-cut/ (a copy of runs-h100/) to the items predicted in all 12 runs.

Drops lines only; never edits one. Writes ~/kiln-items-cut.jsonl and prints the common-set size.
Usage: python3 make_cut.py ~/kiln/runs-h100-cut ~/kiln-items.jsonl ~/kiln-items-cut.jsonl
"""
import json
import sys
from pathlib import Path

cut, items_in, items_out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
runs = sorted(p for p in cut.iterdir() if p.is_dir() and p.name.startswith("C"))
assert len(runs) == 12, [r.name for r in runs]


def ids(path: Path) -> set[str]:
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.add(json.loads(line)["item_id"])
        except (ValueError, KeyError):
            pass  # a half-written last line from the live run is not a prediction
    return out


common = set.intersection(*(ids(r / "predictions.jsonl") for r in runs))
print("common items:", len(common))


def keep(path: Path) -> tuple[int, int]:
    kept, total = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        total += 1
        try:
            if json.loads(line)["item_id"] in common:
                kept.append(line)
        except (ValueError, KeyError):
            pass
    path.write_text("".join(l + "\n" for l in kept), encoding="utf-8")
    return len(kept), total


for r in runs:
    p = keep(r / "predictions.jsonl")
    c = keep(r / "compute_requests.jsonl") if (r / "compute_requests.jsonl").exists() else (0, 0)
    print(f"{r.name}: predictions {p[0]}/{p[1]}, compute requests {c[0]}/{c[1]}")
    assert p[0] == len(common)

lines = [l for l in items_in.read_text(encoding="utf-8").splitlines()
         if l.strip() and json.loads(l)["item_id"] in common]
items_out.write_text("".join(l + "\n" for l in lines), encoding="utf-8")
print("items file:", len(lines), "lines ->", items_out)
assert len(lines) == len(common)

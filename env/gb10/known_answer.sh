#!/usr/bin/env bash
# Known-answer test before any relaxation runs: ALCHEMI's mace_si case must give
# -5.41238 eV/atom (about 61 steps). Exits non-zero otherwise, which blocks Night 1's prewarm.
#
#   bash env/gb10/known_answer.sh
set -euo pipefail

KIT_DIR="${KIT_DIR:-$HOME/kit}"
VENV="${VENV:-$HOME/alchemi/venv}"
EXPECTED="-5.41238"
TOL="0.0001"
OUT="${OUT:-$HOME/alchemi/known_answer_$(date +%Y%m%dT%H%M%S).jsonl}"

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
# shellcheck disable=SC1091
source "$VENV/bin/activate"

SCRIPT="$(command -v alchemi-mlip-test.py || true)"
[ -n "$SCRIPT" ] || SCRIPT="$(find "$KIT_DIR" -name alchemi-mlip-test.py -print -quit 2>/dev/null || true)"
[ -n "$SCRIPT" ] || { echo "alchemi-mlip-test.py not found on PATH or under $KIT_DIR" >&2; exit 1; }

python "$SCRIPT" mace_si "$OUT"

python - "$OUT" "$EXPECTED" "$TOL" <<'EOF'
import json, sys
path, expected, tol = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
rows = [json.loads(l) for l in open(path) if l.strip()]
if not rows:
    sys.exit(f"no output rows in {path}")
last = rows[-1]
keys = [k for k in last if "per_atom" in k and "energy" in k]
if not keys:
    sys.exit(f"can't find an energy-per-atom field in {path}; keys: {sorted(last)}. Check it by hand.")
value = float(last[keys[0]])
steps = next((last[k] for k in ("steps", "n_steps", "nsteps") if k in last), "?")
print(f"{keys[0]} = {value:.5f} eV/atom (expected {expected}), steps = {steps}")
sys.exit(0 if abs(value - expected) <= tol else f"KNOWN-ANSWER TEST FAILED: {value} vs {expected}")
EOF
echo "Known-answer test passed. Output kept at $OUT; post it in the NVIDIA thread."

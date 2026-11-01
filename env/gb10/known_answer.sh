#!/usr/bin/env bash
# Known-answer test before any relaxation runs: ALCHEMI's mace_si case must give
# -5.41238 eV/atom (about 61 steps). Exits non-zero otherwise, which blocks Night 1's prewarm.
#
#   bash env/gb10/known_answer.sh
set -euo pipefail

KIT_DIR="${KIT_DIR:-$HOME/science-kits-for-agents/kit}"
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
text = open(path).read()
# The kit's script writes one pretty-printed JSON object; accept JSON Lines too.
try:
    doc = json.loads(text)
except json.JSONDecodeError:
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        sys.exit(f"no output in {path}")
    doc = json.loads(lines[-1])
result = doc.get("result", doc)
if "nvalchemi_E_per_atom" not in result:
    sys.exit(f"no result.nvalchemi_E_per_atom in {path}; keys: {sorted(result)}. Check it by hand.")
value = float(result["nvalchemi_E_per_atom"])
steps = result.get("nvalchemi_steps", "?")
print(f"nvalchemi_E_per_atom = {value:.5f} eV/atom (expected {expected}), steps = {steps}, "
      f"model = {result.get('model', '?')}")
sys.exit(0 if abs(value - expected) <= tol else f"KNOWN-ANSWER TEST FAILED: {value} vs {expected}")
EOF
echo "Known-answer test passed. Output kept at $OUT; post it in the NVIDIA thread."

#!/usr/bin/env bash
# One command to make a GPU host (GB10, Brev or the H100) ready for a night, or prove it already is:
# environment, the kit's known-answer test, and the canary that refuses stub compute. Stops at the first
# failure. No sudo, nothing outside the home folder (AGENTS.md rule 6).
#
#   KILN_COMPUTE_BACKEND=local bash env/gb10/ready.sh [heldout|dev]
#
# Keys are never read here; the canary needs only the Materials Project cache and the items file.
set -euo pipefail

KILN_DIR="${KILN_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
VENV="${VENV:-$HOME/alchemi/venv}"
SPLIT="${1:-heldout}"
ITEMS="${ITEMS:-$HOME/kiln-items.jsonl}"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
cd "$KILN_DIR"

step() { printf '\n== %s\n' "$1"; }

step "1/4 environment (env/gb10/setup.sh)"
bash env/gb10/setup.sh

step "2/4 known-answer test (mace_si = -5.41238 eV/atom)"
bash env/gb10/known_answer.sh

step "3/4 inputs"
[ -f "$ITEMS" ] || { echo "items file not found: $ITEMS (set ITEMS=...)"; exit 1; }
[ -d cache/mp ] && [ -n "$(ls -A cache/mp 2>/dev/null)" ] || { echo "Materials Project cache is empty: cache/mp"; exit 1; }
[ ! -e labels ] || { echo "labels/ is present on this host; labels never go to a run machine"; exit 1; }
case "${KILN_COMPUTE_BACKEND:-}" in
  local|http) echo "KILN_COMPUTE_BACKEND=$KILN_COMPUTE_BACKEND" ;;
  *) echo "set KILN_COMPUTE_BACKEND=local (it defaults to the stub, which returns fake energies)"; exit 1 ;;
esac
echo "items: $(wc -l < "$ITEMS") lines, sha256 $(sha256sum "$ITEMS" | cut -c1-16)...; MP cache: $(ls cache/mp | wc -l) systems"

step "4/4 canary (one real lookup and one real single point)"
PYTHONPATH=src "$VENV/bin/python" -m kiln.runners.canary --split "$SPLIT" --items-file "$ITEMS" --runs-dir runs

printf '\nready: start the night with python -m kiln.night run <plan> (see docs/night-runner-walkthrough.md)\n'

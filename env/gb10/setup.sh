#!/usr/bin/env bash
# GB10 environment for Kiln's compute service. Everything lives under $HOME; no sudo, no system
# packages, nothing registered into Brev (AGENTS.md rule 6).
#
#   bash env/gb10/setup.sh              # reuse ~/alchemi/venv, or build it from NVIDIA's lock file
#   bash env/gb10/setup.sh --fallback   # plain mace-torch + ASE if the lock-file install fails
#
# Follows the kit's recipe (science-kits-for-agents/kit/dgx-spark/reports/alchemi.md, "The exact
# environment that passed, pinned"). Kiln's own packages are added under a constraint file made
# from the current environment, so nothing the Toolkit was verified with changes version.
# Overridable: KIT_DIR, VENV (default ~/alchemi/venv), KILN_DIR (this repo).
set -euo pipefail

KIT_DIR="${KIT_DIR:-$HOME/science-kits-for-agents/kit}"
VENV="${VENV:-$HOME/alchemi/venv}"
KILN_DIR="${KILN_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
LOCK="$KIT_DIR/dgx-spark/results/alchemi-requirements.lock"
PY_VERSION="3.12.16"

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export UV_PYTHON_INSTALL_DIR="$HOME/alchemi/python"

case "$HOME" in /home/*|/Users/*) ;; *) echo "refusing: HOME=$HOME doesn't look like a home folder" >&2; exit 1;; esac
case "$VENV" in "$HOME"/*) ;; *) echo "refusing: VENV must be under \$HOME" >&2; exit 1;; esac

UV="$HOME/alchemi/bin/uv"
[ -x "$UV" ] || UV="$(command -v uv || true)"
[ -n "$UV" ] || { echo "uv not found (expected ~/alchemi/bin/uv)" >&2; exit 1; }
PIP=("$UV" pip install --python "$VENV/bin/python")

if [ ! -x "$VENV/bin/python" ]; then
  # --managed-python is the trap: the system Python has no headers and torch.compile fails.
  "$UV" venv --seed --relocatable --managed-python --python "$PY_VERSION" "$VENV"
  if [ "${1:-}" = "--fallback" ]; then
    "${PIP[@]}" --torch-backend cu130 --index-strategy unsafe-best-match torch mace-torch ase
  else
    [ -f "$LOCK" ] || { echo "lock file not found: $LOCK (set KIT_DIR, or use --fallback)" >&2; exit 1; }
    "${PIP[@]}" --torch-backend cu130 --index-strategy unsafe-best-match -r "$LOCK"
  fi
else
  echo "reusing existing $VENV"
fi

# Kiln's extras, constrained to the versions already installed.
constraints="$(mktemp)"
"$UV" pip freeze --python "$VENV/bin/python" | grep -v '^-e ' > "$constraints"
"${PIP[@]}" --constraint "$constraints" pymatgen mp-api pytest
"${PIP[@]}" --no-deps -e "$KILN_DIR"
rm -f "$constraints"

"$VENV/bin/python" - <<'EOF'
import os, torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available(),
      torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-")
print("PYTORCH_CUDA_ALLOC_CONF =", os.environ.get("PYTORCH_CUDA_ALLOC_CONF"))
import mace, pymatgen.core, ase, kiln.compute.tiers  # noqa: F401
print("mace, pymatgen, ase, kiln.compute.tiers import ok")
EOF

echo "Environment ready at $VENV. Next: bash env/gb10/known_answer.sh"

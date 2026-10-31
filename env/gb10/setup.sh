#!/usr/bin/env bash
# GB10 environment for Kiln's compute service. Everything lives under $HOME; no sudo, no system
# packages, nothing registered into Brev (AGENTS.md rule 6).
#
#   bash env/gb10/setup.sh              # ALCHEMI Toolkit from NVIDIA's kit lock file (preferred)
#   bash env/gb10/setup.sh --fallback   # plain mace-torch + ASE if the lock-file install fails
#
# Overridable: KIT_DIR (NVIDIA kit checkout), VENV (default ~/alchemi/venv), KILN_DIR (this repo).
set -euo pipefail

KIT_DIR="${KIT_DIR:-$HOME/kit}"
VENV="${VENV:-$HOME/alchemi/venv}"
KILN_DIR="${KILN_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
LOCK="$KIT_DIR/dgx-spark/results/alchemi-requirements.lock"
PY_VERSION="3.12.16"

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

case "$HOME" in /home/*|/Users/*) ;; *) echo "refusing: HOME=$HOME doesn't look like a home folder" >&2; exit 1;; esac
case "$VENV" in "$HOME"/*) ;; *) echo "refusing: VENV must be under \$HOME" >&2; exit 1;; esac

command -v uv >/dev/null || { echo "uv not found; install it into \$HOME first (curl -LsSf https://astral.sh/uv/install.sh | sh)" >&2; exit 1; }

if [ ! -x "$VENV/bin/python" ]; then
  # --managed-python is the trap: without it uv may pick the system Python.
  uv venv --seed --managed-python --python "$PY_VERSION" "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

if [ "${1:-}" = "--fallback" ]; then
  uv pip install --torch-backend cu130 --index-strategy unsafe-best-match torch mace-torch ase
else
  [ -f "$LOCK" ] || { echo "lock file not found: $LOCK (set KIT_DIR, or use --fallback)" >&2; exit 1; }
  uv pip install --torch-backend cu130 --index-strategy unsafe-best-match -r "$LOCK"
fi

# Kiln itself and what the compute tiers need (pymatgen for MP entries and reaction energies).
uv pip install pymatgen mp-api ase "pydantic>=2.7" "filelock>=3.13"
uv pip install --no-deps -e "$KILN_DIR"

python - <<'EOF'
import os, torch
print("python ok; torch", torch.__version__, "cuda", torch.cuda.is_available(),
      torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-")
print("PYTORCH_CUDA_ALLOC_CONF =", os.environ.get("PYTORCH_CUDA_ALLOC_CONF"))
import mace, pymatgen.core, ase, kiln.compute.tiers  # noqa: F401
print("mace, pymatgen, ase, kiln.compute.tiers import ok")
EOF

echo "Environment ready at $VENV. Next: bash env/gb10/known_answer.sh"

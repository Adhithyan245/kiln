#!/usr/bin/env bash
# Start (or reattach to) the compute service in tmux on the GPU host. Same script on Brev.
#
#   bash env/gb10/serve.sh               # binds 127.0.0.1:8765
# From your laptop or the run host, tunnel to it and point the client at the tunnel:
#   ssh -N -L 8765:127.0.0.1:8765 <gb10-host>
#   export KILN_COMPUTE_BACKEND=http KILN_COMPUTE_URL=http://127.0.0.1:8765
# Set KILN_COMPUTE_TOKEN in the environment (never in a file in the repo) to require a token.
set -euo pipefail

VENV="${VENV:-$HOME/alchemi/venv}"
KILN_DIR="${KILN_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
PORT="${PORT:-8765}"
SESSION="${SESSION:-kiln-compute}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "already running; attach with: tmux attach -t $SESSION"
  exit 0
fi

tmux new-session -d -s "$SESSION" \
  "export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True; source '$VENV/bin/activate'; cd '$KILN_DIR'; \
   python -m kiln.compute.service --port $PORT --cache-dir cache/mp 2>&1 | tee -a \"\$HOME/alchemi/compute-service.log\""
echo "started in tmux session $SESSION on 127.0.0.1:$PORT; log at ~/alchemi/compute-service.log"

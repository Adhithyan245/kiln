#!/usr/bin/env bash
# Live tracker for the H100 replication. Read-only: it never starts, stops or changes the run.
# Usage: scripts/h100_watch.sh [refresh_seconds]   (Ctrl-C to quit)
REFRESH=${1:-30}
SSH=(ssh -i ~/.ssh/kiln_h100_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=10 kiln@195.242.28.221)
TOTAL=4152
START_PREDS=""; START_TS=""

while true; do
  out=$("${SSH[@]}" 'cd ~/kiln
    for d in runs-h100/C*; do printf "%s %s\n" "${d#runs-h100/}" "$(wc -l < $d/predictions.jsonl 2>/dev/null || echo 0)"; done
    echo "GPU $(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader)"
    PYTHONPATH=src ~/kiln-h100/venv/bin/python -c "from kiln.night.spend import read_spend; s=read_spend(\"runs-h100\"); print(\"SPEND %.2f %.2f %d\" % (s.gpu_hours, s.usd, s.tokens))"
    echo "RUNNING $(pgrep -fc "^python -m kiln.night run")"
    tail -3 runs-h100/_night/night2-h100/alerts.log | cut -c1-150 | sed "s/^/ALERT /"' 2>&1)
  now=$(date +%s)
  clear
  echo "Kiln H100 replication   $(date -u '+%H:%M:%S UTC')   refresh ${REFRESH}s"
  echo "----------------------------------------------------------------"
  if ! grep -q '^SPEND' <<<"$out"; then echo "VM unreachable:"; echo "$out" | tail -2; sleep "$REFRESH"; continue; fi
  preds=0
  while read -r name n; do
    preds=$((preds + n)); bar=$(printf '%*s' $((n * 30 / 346)) '' | tr ' ' '#')
    printf "  %-34s %3s/346 %-30s\n" "$name" "$n" "$bar"
  done < <(grep -- '-heldout ' <<<"$out")
  read -r _ gpuh usd tok <<<"$(grep '^SPEND' <<<"$out")"
  [ -z "$START_PREDS" ] && START_PREDS=$preds && START_TS=$now
  echo "----------------------------------------------------------------"
  printf "  Predictions  %d / %d  (%d left)\n" "$preds" "$TOTAL" $((TOTAL - preds))
  printf "  GPU-hours    %s / 20.0     USD %s / 30     tokens %s / 12M\n" "$gpuh" "$usd" "$tok"
  el=$((now - START_TS)); done_here=$((preds - START_PREDS))
  if [ "$el" -gt 60 ] && [ "$done_here" -gt 0 ]; then
    rate=$(echo "scale=2; $done_here * 60 / $el" | bc)
    eta=$(( (TOTAL - preds) * el / done_here ))
    printf "  Rate         %s preds/min since watch start, ETA ~%d min (%s UTC)\n" "$rate" $((eta / 60)) "$(date -u -r $((now + eta)) +%H:%M)"
  fi
  echo "  $(grep '^GPU' <<<"$out")    night runner alive: $(grep '^RUNNING' <<<"$out" | cut -d' ' -f2)"
  echo "  Recent alerts:"; grep '^ALERT' <<<"$out" | sed 's/^ALERT /    /'
  sleep "$REFRESH"
done

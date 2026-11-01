#!/usr/bin/env bash
# Live event stream from the H100 replication: one line per compute request and per finished prediction,
# as they happen. Read-only. Ctrl-C to quit (the run keeps going).
# Shows run, item, tier, status, backend and GPU-seconds only; never prediction values.
ssh -t -i ~/.ssh/kiln_h100_ed25519 -o IdentitiesOnly=yes kiln@195.242.28.221 '
cd ~/kiln/runs-h100 && tail -q -n 0 -F C*/compute_requests.jsonl C*/predictions.jsonl 2>/dev/null |
python3 -u -c "
import sys, json, datetime
n = 0
for line in sys.stdin:
    try: d = json.loads(line)
    except Exception: continue
    t = datetime.datetime.now(datetime.timezone.utc).strftime(\"%H:%M:%S\")
    run = str(d.get(\"run_id\", \"\")).replace(\"-gemini-3.8-flash\", \"\").replace(\"-heldout\", \"\")
    if \"tier\" in d:
        r = d.get(\"result\") or {}
        print(f\"{t}  {run:8} {str(d.get(\"item_id\",\"\"))[:14]:14} {d[\"tier\"]:20} {str(d.get(\"status\",\"\")):13} {str(r.get(\"backend\", r.get(\"source\",\"\")))[:16]:16} gpu {float(d.get(\"gpu_seconds\") or 0):7.1f}s\")
    else:
        n += 1
        print(f\"{t}  {run:8} {str(d.get(\"item_id\",\"\"))[:14]:14} >>> PREDICTION DONE  (+{n} since stream start)\")
"'

#!/usr/bin/env bash
# Remove the Kiln app's Nebius resources after judging so nothing keeps billing: the serverless endpoint,
# and optionally the replay VM and the registry. Asks before each delete.
#
#   NEBIUS_PROJECT_ID=... bash env/nebius/teardown.sh [--vm kiln-app] [--registry kiln]
set -euo pipefail
PROJECT="${NEBIUS_PROJECT_ID:?set NEBIUS_PROJECT_ID}"
NAME="${KILN_ENDPOINT:-kiln-triage}"
VM="" REGISTRY=""
while [ $# -gt 0 ]; do
  case "$1" in --vm) VM="$2"; shift 2 ;; --registry) REGISTRY="$2"; shift 2 ;; *) echo "unknown $1"; exit 1 ;; esac
done
confirm() { read -r -p "$1 [y/N] " a; [ "$a" = y ]; }

id=$(nebius ai endpoint list --parent-id "$PROJECT" --format json |
     python3 -c "import sys,json; d=json.load(sys.stdin); print(next((e['metadata']['id'] for e in d.get('items',[]) if e['metadata']['name']=='$NAME'), ''))")
if [ -n "$id" ] && confirm "delete endpoint $NAME ($id)?"; then nebius ai endpoint delete "$id"; fi
if [ -n "$VM" ]; then
  vid=$(nebius compute instance get-by-name --parent-id "$PROJECT" --name "$VM" --format jsonpath='{.metadata.id}' 2>/dev/null || true)
  if [ -n "$vid" ] && confirm "delete VM $VM ($vid) and its boot disk?"; then nebius compute instance delete --id "$vid"; fi
fi
if [ -n "$REGISTRY" ]; then
  rid=$(nebius registry list --parent-id "$PROJECT" --format json |
        python3 -c "import sys,json; d=json.load(sys.stdin); print(next((r['metadata']['id'] for r in d.get('items',[]) if r['metadata']['name']=='$REGISTRY'), ''))")
  if [ -n "$rid" ] && confirm "delete registry $REGISTRY ($rid) and its images?"; then nebius registry delete --id "$rid"; fi
fi

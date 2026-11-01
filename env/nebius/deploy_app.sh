#!/usr/bin/env bash
# Deploy the Kiln triage app (replay mode) as a Nebius Serverless AI endpoint, or redeploy it.
#
#   bash env/nebius/deploy_app.sh [COMMIT]          # default: HEAD
#
# Builds an image from `git archive COMMIT` (so only committed runs and code), pushes it to the Nebius
# registry as :<commit> and :live, then restarts the endpoint (which pulls :live), or creates it on first
# use. The URL stays the same across redeploys. Read-only: KILN_LIVE is never set and no key goes in.
#
# Needs: the nebius CLI signed in (docker-credential-nebius handles registry auth, no tokens here), Docker.
# Settings (env): NEBIUS_PROJECT_ID, KILN_REGISTRY (cr.<region>.nebius.cloud/<registry id>),
#   KILN_ENDPOINT (default kiln-triage), KILN_ITEMS (optional agent-visible items file; never committed).
set -euo pipefail

COMMIT=$(git rev-parse --short=8 "${1:-HEAD}")
PROJECT="${NEBIUS_PROJECT_ID:?set NEBIUS_PROJECT_ID}"
REGISTRY="${KILN_REGISTRY:?set KILN_REGISTRY, e.g. cr.uk-south2.nebius.cloud/<registry id>}"
NAME="${KILN_ENDPOINT:-kiln-triage}"
IMAGE="$REGISTRY/kiln-triage"
HERE="$(cd "$(dirname "$0")" && pwd)"

ctx=$(mktemp -d); trap 'rm -rf "$ctx"' EXIT
mkdir -p "$ctx/repo" "$ctx/items"
git archive "$COMMIT" | tar -x -C "$ctx/repo"
if [ -n "${KILN_ITEMS:-}" ] && [ -f "$KILN_ITEMS" ]; then cp "$KILN_ITEMS" "$ctx/items/kiln-items.jsonl"; fi
cp "$HERE/Dockerfile.replay" "$ctx/Dockerfile"

echo "== build $IMAGE:$COMMIT"
docker build -q -t "$IMAGE:$COMMIT" -t "$IMAGE:live" "$ctx" > /dev/null
docker rm -f kiln-replay-check > /dev/null 2>&1 || true
docker run -d --name kiln-replay-check -p 18080:8080 "$IMAGE:$COMMIT" > /dev/null
sleep 3
status=$(curl -s localhost:18080/api/status); pairs=$(curl -s localhost:18080/api/pairs | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))')
docker rm -f kiln-replay-check > /dev/null
echo "local check: status $status, $pairs recorded pairs"
[ "$status" = '{"live": false}' ] || { echo "refusing: the image is not in replay-only mode"; exit 1; }

echo "== push"
nebius registry configure-helper > /dev/null 2>&1 || true
docker push -q "$IMAGE:$COMMIT" > /dev/null
docker push -q "$IMAGE:live" > /dev/null

id=$(nebius ai endpoint list --parent-id "$PROJECT" --format json |
     python3 -c "import sys,json; d=json.load(sys.stdin); print(next((e['metadata']['id'] for e in d.get('items',[]) if e['metadata']['name']=='$NAME'), ''))")
if [ -n "$id" ]; then
  echo "== restart $NAME ($id), pulling :live"
  nebius ai endpoint restart "$id" > /dev/null
else
  echo "== create $NAME (CPU, public HTTPS, no auth: the app is read-only)"
  nebius ai endpoint create --parent-id "$PROJECT" --name "$NAME" --image "$IMAGE:live" \
    --container-port 8080 --platform cpu-d3 --preset 2vcpu-8gb --disk-size 30Gi --auth none --on-demand > /dev/null
  id=$(nebius ai endpoint list --parent-id "$PROJECT" --format json |
       python3 -c "import sys,json; d=json.load(sys.stdin); print(next(e['metadata']['id'] for e in d['items'] if e['metadata']['name']=='$NAME'))")
fi
url=$(nebius ai endpoint get "$id" --format json | grep -oE 'https://[a-z0-9.-]+nebius\.cloud' | head -1)
echo "== waiting for $url"
for _ in $(seq 60); do
  [ "$(curl -s -m 10 "$url/api/status")" = '{"live": false}' ] && break; sleep 10
done
echo "deployed $COMMIT: $url ($(curl -s "$url/api/pairs" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))') pairs)"

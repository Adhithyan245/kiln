# Deploying the Kiln evidence app

The app (`app/server.py` + `app/index.html`) is a read-only viewer of recorded Night 2 predictions. It
needs **only Python 3.10+ and its standard library**: no packages, no GPU, no labels, no API keys. It
shows the GB10 run (`runs/`) and the H100 replication (`runs-h100/`), and it never shows a run whose
compute log contains a stub result.

## Option A: any Linux VM (Brev or Nebius), no Docker (recommended)

On a fresh CPU instance (the smallest size is enough):

```bash
git clone https://github.com/Adhithyan245/kiln.git && cd kiln
PORT=8080 nohup python3 app/server.py > app.log 2>&1 &
curl -s localhost:8080 | grep -o "<title>[^<]*" # should print: <title>Kiln | Evidence notebook
```

Then expose port **8080** on the instance:
- **Brev:** in the instance page, add a public port / tunnel for 8080 (or `brev port-forward <instance> -p 8080:8080` from a laptop for a private link).
- **Nebius:** allow inbound TCP 8080 in the VM's security group, then open `http://<public-ip>:8080`.

While the repo is private, clone with a GitHub token that has read access, or copy the repo over with
`scp`. After the repo goes public, the plain clone above works.

## Option B: Docker

```bash
git clone https://github.com/Adhithyan245/kiln.git && cd kiln
docker build -f app/Dockerfile -t kiln-app .
docker run -d -p 8080:8080 --name kiln-app kiln-app
```

The image copies `runs/` and `runs-h100/` at build time, so **rebuild after new results are pushed**.

## Updating with new results

Results land on `dev` as `runs-h100/` (H100) and `runs/` (GB10 rerun). On the instance:

```bash
cd kiln && git pull && pkill -f app/server.py; PORT=8080 nohup python3 app/server.py > app.log 2>&1 &
```

(The server re-reads the folders on every page load, so for Option A a `git pull` alone is enough.)

## Checks before sharing the link

- The page loads and the header reads "kiln evidence notebook".
- Every assessment shows a machine label: "GB10 (DGX Spark)" or "H100 (ALCHEMI Toolkit)".
- No assessment shows a "Stand-in components" badge.
- Open one assessment: the compute trail lists real tiers (cached lookup, single point, bounded relaxation).

# INVALID: Night 2 GB10 run on the stub compute backend (2026-11-01)

Do not use anything in this folder as a result. `KILN_COMPUTE_BACKEND` defaulted to `stub` on the GB10,
so every compute result in these 12 runs is a fake energy (`"model": "stub"`). See
`protocol/amendments.md` (2026-11-01 entries). Kept byte-exact as the record of what was hashed and
posted: manifest SHA-256 `b44cf1261297a1fa6e1c2925fb6c738b585fc468d2df3d105e8d489c8696e46f`
(#kiln-receipts message 1566368553345613947). The real results are the H100 run (`runs-h100/`)
and the GB10 rerun with `KILN_COMPUTE_BACKEND=local` (`runs/`).

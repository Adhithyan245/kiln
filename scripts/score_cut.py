"""Score the 16:15 UTC H100 copy. The confirmation hash is typed in from the user's reading of the Discord post
(their screenshot), not derived from any local file."""
import sys
from pathlib import Path
sys.path.insert(0, "src")
from kiln.scoring import __main__ as cli

READ_FROM_DISCORD = "9cb24cb49164521029690d2a3625d0b1591a9089251d6bdd36141237cd915264"
confirm = cli.manual_confirm(lambda prompt: READ_FROM_DISCORD)
rc_all = 0
for c in ("C1", "C2", "C3", "C4"):
    for s in ("s0", "s1", "s2"):
        run = f"{c}-gemini-3.8-flash-{s}-heldout"
        print(f"\n=== {run}")
        rc = cli.main(["--run-dir", f"runs-h100-cut/{run}", "--labels", "labels/labels-cut.jsonl",
                       "--items-file", "kiln-items-cut.jsonl",
                       "--manifest", "protocol/predictions-h100-cut.manifest.json",
                       "--receipt", "protocol/posts-h100-cut.jsonl",
                       "--split", "heldout", "--verify", "manual",
                       "--out", f"results-h100-cut/{run}/evaluation.json"], confirm=confirm)
        rc_all = rc_all or rc
        if rc:
            print("FAILED rc", rc); sys.exit(rc)
print("\nALL 12 SCORED")

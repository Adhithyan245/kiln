"""Push the current branch after `git pull --rebase`. Refuses main and detached HEAD; never forces.

    python -m kiln.night.gitpush [--paths runs results protocol]
`--paths` are staged and committed first if they changed (labels/ is gitignored and never staged).
"""
from __future__ import annotations

import argparse
import subprocess
import sys

__all__ = ["push"]

_PROTECTED = {"main", "master"}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def push(paths: list[str], message: str) -> str:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD" or branch in _PROTECTED:
        raise SystemExit(f"refusing to push from {branch!r}")
    if any(p.strip("/").split("/")[0] == "labels" for p in paths):
        raise SystemExit("refusing to stage labels/")
    if paths:
        _git("add", "--", *paths)
        if _git("diff", "--cached", "--name-only"):
            _git("commit", "-m", message)
    _git("pull", "--rebase", "--autostash", "origin", branch)  # step logs are still being written
    _git("push", "origin", f"HEAD:refs/heads/{branch}")
    return branch


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m kiln.night.gitpush")
    p.add_argument("--paths", nargs="*", default=[])
    p.add_argument("--message", default="night: results")
    args = p.parse_args(argv)
    print(push(args.paths, args.message))
    return 0


if __name__ == "__main__":
    sys.exit(main())

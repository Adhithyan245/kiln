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


def push(paths: list[str], message: str, *, allow_no_remote: bool = False) -> str:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD" or branch in _PROTECTED:
        raise SystemExit(f"refusing to push from {branch!r}")
    if any(p.strip("/").split("/")[0] == "labels" for p in paths):
        raise SystemExit("refusing to stage labels/")
    if paths:
        _git("add", "--", *paths)
        if _git("diff", "--cached", "--name-only"):
            _git("commit", "-m", message)
    try:
        _git("pull", "--rebase", "--autostash", "origin", branch)  # step logs are still being written
        _git("push", "origin", f"HEAD:refs/heads/{branch}")
    except subprocess.CalledProcessError as exc:
        if not allow_no_remote:
            raise
        # Committed locally; the push is skipped, not hidden: the note names the commit to bring back.
        print(f"push skipped (no reachable remote: {(exc.stderr or '').strip()[:200]}); "
              f"committed locally at {_git('rev-parse', '--short', 'HEAD')} on {branch}", file=sys.stderr)
    return branch


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m kiln.night.gitpush")
    p.add_argument("--paths", nargs="*", default=[])
    p.add_argument("--message", default="night: results")
    p.add_argument("--allow-no-remote", action="store_true",
                   help="commit locally and skip the push with a note when the remote is unreachable (GB10)")
    args = p.parse_args(argv)
    print(push(args.paths, args.message, allow_no_remote=args.allow_no_remote))
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kiln.night.gitpush import push


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "dev")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "remote", "add", "origin", str(tmp_path / "no-such-remote"))   # like the GB10: no GitHub
    monkeypatch.chdir(repo)
    return repo


def test_unreachable_remote_commits_locally_and_skips_the_push_with_a_note(repo: Path, capsys) -> None:
    (repo / "runs").mkdir()
    (repo / "runs" / "p.jsonl").write_text("{}\n")
    assert push(["runs"], "night2: predictions", allow_no_remote=True) == "dev"
    assert git(repo, "log", "-1", "--format=%s") == "night2: predictions"
    assert "push skipped" in capsys.readouterr().err


def test_without_the_flag_an_unreachable_remote_still_fails(repo: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        push([], "x")

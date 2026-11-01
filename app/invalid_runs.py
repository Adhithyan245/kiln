"""Prediction digests in the invalidated GB10 manifest recorded in amendments.md.

The rerun may reuse the same directories, so run names alone must not exclude it.
These digests identify the discarded data, not the currently running rerun.
Source: protocol/predictions.manifest.json at e4854073; amendment 2026-11-01.
"""
import hashlib
from functools import lru_cache
from pathlib import Path

INVALID_GB10_PREDICTION_SHA256 = frozenset({
    "34488b93e872c9452228a3cbbb02c7422ac0146cda5580ed0c3d5060ceefa841",
    "1ace15a492a812b090b7d0ebf0c58dad921fa2217eaf1282752cc3261e1030d1",
    "b20f1e67b4144f15c66cb93bfc8ba10e4e4aa1f2467561dabf4cc6f94b5c85d7",
    "601ccc409d262bb9b6cf33b1168ba09a011e3b3ff6137b91e192c060330095a4",
    "d7d23c21e2e6c7f973ae899b587a139380faa286c7940b739a0cab4a151a04d3",
    "df6ee721b933fd4bbc3b7b4bc05ac8e3c8ceab4355aa5915723dce0fffa08eec",
    "8778f2fb11461823c3422263b2fa5c00f78d8c3104d9755f30a69c5010520248",
    "ac38d90deb3017426788b66b0f4d6a7f03494bf3540c9cfa37fee59d9f7fef35",
    "1af046c15d4cd83dda3ae3460f5ed7352f13861b10099645b6cccf32196d5d71",
    "e8986ea85839dac76fa83e07e923a8249e1446ce9ecbb971d3e1f6b9e28d5736",
    "d4b6ca88458b102cc20aa18ff10058a71a7aa25bdd3baef3f7b821ec7387d493",
    "a6403050d64aabc6dc165e63605f254460483f8f51a1c39711079477e78b59ee",
})


@lru_cache(maxsize=128)
def _digest(path: Path, modified: int, size: int) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def invalid_gb10(path: Path) -> bool:
    stat = path.stat()
    return _digest(path.resolve(), stat.st_mtime_ns, stat.st_size) in INVALID_GB10_PREDICTION_SHA256

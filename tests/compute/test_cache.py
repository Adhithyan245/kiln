from __future__ import annotations

from pathlib import Path

import pytest

from kiln.compute.accounting import cache_key
from kiln.compute.cache import ResultCache
from kiln.schemas import ComputeTier


def test_round_trip_and_miss(tmp_path: Path) -> None:
    cache = ResultCache(tmp_path)
    key = cache_key(ComputeTier.single_point, {"formula": "CaTiO3"}, {"model": "m"})
    assert cache.get(key) is None
    cache.put(key, {"dE_ev_per_atom": -0.05, "model": "m"}, tier="single_point", settings={"model": "m"})
    assert cache.get(key) == {"dE_ev_per_atom": -0.05, "model": "m"}
    assert (tmp_path / key[:2] / f"{key}.json").exists()
    assert not list(tmp_path.rglob(".tmp-*"))


def test_rejects_non_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ResultCache(tmp_path).get("../../etc/passwd")

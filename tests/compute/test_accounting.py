from __future__ import annotations

import pytest

from kiln.compute.accounting import MissingPrice, cache_key, price
from kiln.schemas import ComputeTier, RunConfig

from tests.compute.helpers import make_config


def test_price_reads_frozen_table() -> None:
    assert price(make_config(), ComputeTier.bounded_relaxation) == 4.0


def test_missing_price_raises() -> None:
    config = RunConfig(run_id="r", condition="C4", seed=0, model="stub")
    with pytest.raises(MissingPrice):
        price(config, ComputeTier.single_point)


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
def test_invalid_price_raises(bad: float) -> None:
    config = make_config()
    config.tier_prices["single_point"] = bad
    with pytest.raises(MissingPrice):
        price(config, ComputeTier.single_point)


def test_cache_key_ignores_dict_order() -> None:
    a = cache_key(ComputeTier.single_point, {"formula": "CaTiO3", "mp_id": "mp-1"}, {"model": "m", "fmax": 0.05})
    b = cache_key(ComputeTier.single_point, {"mp_id": "mp-1", "formula": "CaTiO3"}, {"fmax": 0.05, "model": "m"})
    assert a == b and len(a) == 64


def test_cache_key_separates_tier_inputs_and_settings() -> None:
    base = cache_key(ComputeTier.single_point, {"formula": "CaTiO3"}, {"model": "m"})
    assert base != cache_key(ComputeTier.bounded_relaxation, {"formula": "CaTiO3"}, {"model": "m"})
    assert base != cache_key(ComputeTier.single_point, {"formula": "SrTiO3"}, {"model": "m"})
    assert base != cache_key(ComputeTier.single_point, {"formula": "CaTiO3"}, {"model": "n"})


def test_cache_key_rejects_non_json_inputs() -> None:
    with pytest.raises(TypeError):
        cache_key(ComputeTier.single_point, {"formula": object()}, {})
    with pytest.raises(ValueError):
        cache_key(ComputeTier.single_point, {"x": float("nan")}, {})

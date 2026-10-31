"""Checks for the temperature conversion and missing or invalid inputs."""

import pytest

from kiln.tools.tammann import tammann_c


def test_tammann_converts_through_kelvin():
    assert tammann_c(626.85) == pytest.approx(326.85)


def test_missing_melting_point_is_unknown():
    assert tammann_c(None) is None


@pytest.mark.parametrize("value", [-273.15, -300, float("nan"), float("inf"), True, "900"])
def test_invalid_temperature_is_rejected(value):
    with pytest.raises(ValueError):
        tammann_c(value)

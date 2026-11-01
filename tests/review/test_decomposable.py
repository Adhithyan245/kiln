from __future__ import annotations

import pytest

from kiln.review import can_decompose


@pytest.mark.parametrize("formula", ["Li2CO3", "SrCO3", "La(HO)3", "LiH3O2", "K4H6C2O9", "KP(HO2)2",
                                     "PH6NO4", "PH9(NO2)2", "FeH4(CO3)2", "MnO2", "Mn2O3", "Fe2O3"])
def test_precursors_that_can_break_down_stay_flagged(formula: str) -> None:
    assert can_decompose(formula)


@pytest.mark.parametrize("formula", ["TiO2", "ZrO2", "MgO", "SiO2", "Y2O3", "ZnO", "Nb2O5", "WO3"])
def test_stable_oxides_are_not_missing_evidence(formula: str) -> None:
    assert not can_decompose(formula)


def test_unparseable_formula_is_never_assumed_stable() -> None:
    assert can_decompose("not a formula")

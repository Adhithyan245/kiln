from __future__ import annotations

import pytest

pytest.importorskip("pymatgen", reason="compute extras (pymatgen) not installed; see env/gb10/setup.sh")

from kiln.compute.energy_reference import corrected_energy, corrected_entry, phase_differences  # noqa: E402
from tests.tools.mp_fixtures import ca_ti_o_entries  # noqa: E402


def _tio2():
    return min((e for e in ca_ti_o_entries() if e.composition.reduced_formula == "TiO2"),
               key=lambda e: e.energy_per_atom)


def test_corrected_energy_adds_the_entrys_own_mp2020_correction() -> None:
    entry = _tio2()
    raw = entry.uncorrected_energy                      # an MLIP that reproduces DFT exactly
    assert corrected_energy(raw, entry) == pytest.approx(entry.energy)
    assert corrected_entry(entry, raw).energy_per_atom == pytest.approx(entry.energy_per_atom)
    assert corrected_entry(entry, raw).entry_id == entry.entry_id


def test_phase_difference_is_zero_when_mlip_matches_dft() -> None:
    entries = ca_ti_o_entries()
    diffs = phase_differences(entries, [e.uncorrected_energy for e in entries])
    assert [d.entry_id for d in diffs] == [str(e.entry_id) for e in entries]
    assert all(d.mlip_minus_mp_ev_per_atom == pytest.approx(0.0, abs=1e-12) for d in diffs)


def test_phase_difference_reports_mlip_minus_mp_per_atom_for_one_oxide() -> None:
    entry = _tio2()
    n = entry.composition.num_atoms
    shifted = entry.uncorrected_energy + 0.02 * n      # MLIP 20 meV/atom above DFT
    (d,) = phase_differences([entry], [shifted])
    assert d.formula == "TiO2"
    assert d.mlip_minus_mp_ev_per_atom == pytest.approx(0.02)
    assert d.mlip_ev_per_atom == pytest.approx(entry.energy_per_atom + 0.02)
    assert d.mp_ev_per_atom == pytest.approx(entry.energy_per_atom)


def test_mismatched_lengths_are_refused() -> None:
    with pytest.raises(ValueError):
        phase_differences(ca_ti_o_entries(), [0.0])

import json
import os
import subprocess
import sys
import traceback

import pytest

from kiln.data import DWELL_PROVENANCE, HEATING_TIME_SOURCE, HEATING_TIME_UNIT, LedgerRecordError, _heldout, ingest, load_items
from kiln.schemas import Item

# Distinctive synthetic per-record values that the summary command must never print.
SENSITIVE = ("PRIVATE-", "9Xq7O4", "873.25", "1234.5", "7.75", "synthetic-secret")


def write_ledger(tmp_path, reverse=False):
    names = [f"{element}O" for element in ("Li", "Na", "K", "Mg", "Ca", "Sr", "Ba", "Al", "Ti", "Zr", "Fe", "Co")]
    samples = [
        {"sample_id": f"sample-{i}", "precursors": [{"formula": name, "melting_point_c": 500}, {"formula": names[(i + 1) % len(names)]}],
         "synthesis": {"heating_temperature": 800, "heating_time": 1},
         "outcome": {"reaction_category": "synthetic-secret", "nested": [1, {"x": "a\\\"b"}]},
         "characterization": {"xrd": {"scans": ["synthetic-secret"]}}}
        for i, name in enumerate(names)
    ]
    if reverse:
        samples.reverse()
    path = tmp_path / ("reverse.json" if reverse else "ledger.json")
    path.write_text(json.dumps({"samples": samples, "outcome": "synthetic-secret"}), encoding="utf-8")
    return path


def write_sensitive_ledger(tmp_path, mutate=None):
    """Synthetic ledger whose ids, formulas and conditions are all marker values from SENSITIVE."""
    path = write_ledger(tmp_path)
    document = json.loads(path.read_text())
    for i, sample in enumerate(document["samples"]):
        sample["sample_id"] = f"PRIVATE-ID-{i}"
        for precursor in sample["precursors"]:
            precursor["formula"] += "9Xq7O4"
            precursor["melting_point_c"] = 1234.5
        sample["synthesis"] = {"heating_temperature": 873.25, "heating_time": 7.75}
    if mutate:
        mutate(document["samples"][0])
    path.write_text(json.dumps(document))
    return path


def run_summary(path):
    return subprocess.run([sys.executable, "-m", "kiln.data", str(path)],
                          capture_output=True, text=True, env=os.environ.copy())


def test_split_projection_and_provenance(tmp_path):
    path = write_ledger(tmp_path)
    items, provenance = ingest(path)
    selected = _heldout({name for item in items for name in (item.precursor_a, item.precursor_b)}, 42)
    assert len(selected) == 9
    assert all((item.split == "heldout") == bool({item.precursor_a, item.precursor_b} & selected) for item in items)
    assert {i.item_id for i in load_items("dev", path)} | {i.item_id for i in load_items("heldout", path)} == {i.item_id for i in items}
    assert all(Item.model_validate(item.model_dump()) == item for item in items)
    assert all("synthetic-secret" not in item.model_dump_json() for item in items)
    assert all(set(item.model_dump()) == set(Item.model_fields) for item in items)
    assert provenance[0].record_index == 0
    assert provenance[0].source_file == str(path)
    assert "precursors[0].formula" in provenance[0].fields_used
    assert "synthesis.heating_temperature" in provenance[0].fields_used
    assert "synthetic-secret" not in ''.join(p.model_dump_json() for p in provenance)


def test_selection_is_independent_of_record_order(tmp_path):
    forward, _ = ingest(write_ledger(tmp_path))
    reverse, _ = ingest(write_ledger(tmp_path, reverse=True))
    assert {i.item_id: i.split for i in forward} == {i.item_id: i.split for i in reverse}


def test_summary_command_prints_counts_only(tmp_path):
    path = write_sensitive_ledger(tmp_path)
    items, _ = ingest(path)
    dev = sum(item.split == "dev" for item in items)
    result = run_summary(path)
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "Distinct precursors: 12",
        "Held-out precursors: 9",
        f"Dev items: {dev}",
        f"Held-out items: {len(items) - dev}",
    ]
    assert 0 < dev < len(items) == 12
    output = result.stdout + result.stderr
    assert [value for value in SENSITIVE if value in output] == []
    assert not any(name in output for item in items for name in (item.precursor_a, item.precursor_b, item.item_id))


@pytest.mark.parametrize("mutate,message", [
    (lambda sample: sample["synthesis"].update(heating_temperature=None), "a sample is missing synthesis.heating_temperature"),
    (lambda sample: sample.pop("synthesis"), "a sample is missing synthesis data and heating temperature"),
    (lambda sample: sample["synthesis"].update(heating_temperature="PRIVATE-TEMP"), "a sample failed Item validation for temperature_c"),
    (lambda sample: sample["precursors"].append({"formula": "PRIVATE-THIRD"}), "a sample requires exactly two precursors"),
])
def test_summary_command_errors_name_fields_only(tmp_path, mutate, message):
    result = run_summary(write_sensitive_ledger(tmp_path, mutate))
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"Ledger check failed: {message}\n"
    assert [value for value in SENSITIVE if value in result.stderr] == []


def test_summary_command_hides_undecodable_bytes(tmp_path):
    path = write_sensitive_ledger(tmp_path)
    path.write_bytes(path.read_bytes().replace(b"PRIVATE-ID-0", b"PRIVATE-ID-\xff"))
    result = run_summary(path)
    assert result.returncode == 1
    assert result.stderr == "Ledger check failed: UnicodeDecodeError\n"


def test_validation_error_traceback_hides_input_values(tmp_path):
    path = write_sensitive_ledger(tmp_path, lambda sample: sample["synthesis"].update(heating_temperature="PRIVATE-TEMP"))
    with pytest.raises(LedgerRecordError, match="Sample 0 failed Item validation for temperature_c") as info:
        ingest(path)
    rendered = "".join(traceback.format_exception(info.value))
    assert "PRIVATE-" not in rendered
    assert "input_value=" not in rendered


@pytest.mark.parametrize("field,value", [
    ("melting_point_c", {"value": 500, "unit": "C"}),
    ("heating_time", [1, 2]),
])
def test_rejects_container_in_selected_optional_field(tmp_path, field, value):
    path = write_ledger(tmp_path)
    document = json.loads(path.read_text())
    sample = document["samples"][0]
    target = sample["precursors"][0] if field == "melting_point_c" else sample["synthesis"]
    target[field] = value
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="Selected ledger value must be a scalar"):
        ingest(path)


@pytest.mark.parametrize("synthesis,expected", [
    (None, "missing synthesis data and heating temperature"),
    ({"heating_temperature": None}, "missing synthesis.heating_temperature"),
])
def test_missing_temperature_fails_closed(tmp_path, synthesis, expected):
    path = write_ledger(tmp_path)
    document = json.loads(path.read_text())
    document["samples"][0]["synthesis"] = synthesis
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match=expected):
        ingest(path)


def test_rejects_bad_records_and_split(tmp_path):
    path = write_ledger(tmp_path)
    with pytest.raises(ValueError, match="split must"):
        load_items("test", path)
    document = json.loads(path.read_text())
    document["samples"][1]["sample_id"] = document["samples"][0]["sample_id"]
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="duplicate"):
        ingest(path)
    with pytest.raises(ValueError, match="nine"):
        _heldout({"Li2O"}, 42)


def _set_heating_times(path, times):
    document = json.loads(path.read_text())
    for sample, minutes in zip(document["samples"], times):
        if minutes is _DROP:
            sample["synthesis"].pop("heating_time")
        else:
            sample["synthesis"]["heating_time"] = minutes
    path.write_text(json.dumps(document))


_DROP = object()


def test_heating_time_minutes_become_dwell_hours_with_sourced_provenance(tmp_path):
    # Synthetic ledger. The unit is minutes per the dataset paper's ledger schema
    # ("heating_time_min") and its methods ("a 1-hour hold"), arXiv:2607.09903.
    assert HEATING_TIME_UNIT == "min"
    assert "arXiv:2607.09903" in HEATING_TIME_SOURCE and "heating_time_min" in HEATING_TIME_SOURCE
    path = write_ledger(tmp_path)
    _set_heating_times(path, [60, 240, 90.0, _DROP])
    items, provenance = ingest(path)
    assert [item.dwell_h for item in items[:4]] == [1.0, 4.0, 1.5, None]
    for record in provenance[:3]:
        assert "synthesis.heating_time" in record.fields_used
        assert DWELL_PROVENANCE in record.fields_used
    assert "synthesis.heating_time" not in provenance[3].fields_used
    assert DWELL_PROVENANCE not in provenance[3].fields_used
    assert all(Item.model_validate(item.model_dump()) == item for item in items)


@pytest.mark.parametrize("bad", ["PRIVATE-60", "60", True])
def test_non_numeric_heating_time_is_rejected_by_field_name(tmp_path, bad):
    path = write_ledger(tmp_path)
    _set_heating_times(path, [bad])
    with pytest.raises(LedgerRecordError, match="Sample 0 has a non-numeric synthesis.heating_time"):
        ingest(path)

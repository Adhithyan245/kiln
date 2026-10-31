import json
import os
import subprocess
import sys

import pytest

from kiln.data import _heldout, ingest, load_items
from kiln.schemas import Item


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


def test_summary_command_uses_label_free_projection(tmp_path):
    path = write_ledger(tmp_path)
    items, _ = ingest(path)
    precursors = {name for item in items for name in (item.precursor_a, item.precursor_b)}
    expected = _heldout(precursors, 42)
    result = subprocess.run(
        [sys.executable, "-m", "kiln.data", str(path)],
        check=True, capture_output=True, text=True, env=os.environ.copy(),
    )
    lines = result.stdout.splitlines()
    assert lines == [
        f"Distinct precursors: {len(precursors)}",
        f"Held-out precursors: {', '.join(sorted(expected))}",
        f"Dev items: {sum(item.split == 'dev' for item in items)}",
        f"Held-out items: {sum(item.split == 'heldout' for item in items)}",
    ]
    assert "synthetic-secret" not in result.stdout + result.stderr


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

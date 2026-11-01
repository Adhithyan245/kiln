"""Label-free Precursor Genome ingestion and precursor-level splitting."""
from __future__ import annotations

import json
import math
import random
import re
from pathlib import Path
from typing import IO, Any, Literal

from pydantic import ValidationError

from kiln.provenance import ItemProvenance
from kiln.schemas import Item

DEFAULT_LEDGER = Path(__file__).resolve().parents[3] / "data/raw/ledger_precursor_genome.json"
SPLIT_SEED = 42
HELDOUT_PRECURSORS = 9

# synthesis.heating_time is in MINUTES; Item.dwell_h is hours. Source (documentation only, no
# outcomes read): the dataset paper, The Precursor Genome, arXiv:2607.09903v1. Its ledger schema
# table documents the field as "heating_time_min float", and its methods give the default
# profile as "... up to the maximum dwell temperature, followed by a 1-hour hold" (60 min).
HEATING_TIME_UNIT = "min"
MINUTES_PER_HOUR = 60
HEATING_TIME_SOURCE = (
    "The Precursor Genome, arXiv:2607.09903v1 (https://arxiv.org/pdf/2607.09903): ledger schema field "
    "'heating_time_min float'; methods: default profile ends with 'a 1-hour hold'"
)
# Recorded in ItemProvenance.fields_used next to "synthesis.heating_time" for every converted item.
DWELL_PROVENANCE = f"dwell_h = synthesis.heating_time / {MINUTES_PER_HOUR} (minutes to hours; source: {HEATING_TIME_SOURCE})"


class LedgerError(ValueError):
    """Ledger problem whose message names fields only, never ledger values."""


class LedgerRecordError(LedgerError):
    """Problem with one sample; ``reason`` names fields without the record position."""

    def __init__(self, index: int, reason: str):
        super().__init__(f"Sample {index} {reason}")
        self.index = index
        self.reason = reason


# Only these paths are decoded. Everything else is skipped without decoding its value.
_SELECTION: dict[str, Any] = {"samples": [{
    "sample_id": True,
    "precursors": [{"formula": True, "formula_clean": True, "melting_point_c": True}],
    "synthesis": {"heating_temperature": True, "heating_time": True},
}]}


class _ProjectionReader:
    """Read a JSON projection without materializing unselected ledger values."""

    def __init__(self, stream: IO[str]):
        self.stream = stream
        self.char = stream.read(1)

    def advance(self) -> None:
        self.char = self.stream.read(1)

    def whitespace(self) -> None:
        while self.char and self.char.isspace():
            self.advance()

    def expect(self, char: str) -> None:
        self.whitespace()
        if self.char != char:
            raise LedgerError("Invalid ledger JSON structure")
        self.advance()

    def string(self, keep: bool) -> str | None:
        self.expect('"')
        token = ['"'] if keep else None
        escaped = False
        while self.char:
            c = self.char
            self.advance()
            if token is not None:
                token.append(c)
            if c == '"' and not escaped:
                return json.loads(''.join(token)) if token is not None else None
            if c == '\\' and not escaped:
                escaped = True
            else:
                escaped = False
        raise LedgerError("Unterminated JSON string")

    def value(self, selection: Any = None) -> Any:
        self.whitespace()
        if selection is True and self.char in ('{', '['):
            raise LedgerError("Selected ledger value must be a scalar, not a container")
        if self.char == '{':
            self.advance()
            result = {} if isinstance(selection, dict) else None
            self.whitespace()
            while self.char != '}':
                key = self.string(result is not None)
                self.expect(':')
                child = selection.get(key) if result is not None else None
                value = self.value(child)
                if child is not None:
                    result[key] = value
                self.whitespace()
                if self.char != ',':
                    break
                self.advance()
            self.expect('}')
            return result
        if self.char == '[':
            self.advance()
            result = [] if isinstance(selection, list) else None
            self.whitespace()
            while self.char != ']':
                value = self.value(selection[0] if result is not None else None)
                if result is not None:
                    result.append(value)
                self.whitespace()
                if self.char != ',':
                    break
                self.advance()
            self.expect(']')
            return result
        if self.char == '"':
            return self.string(selection is True)
        token = [] if selection is True else None
        while self.char and self.char not in ',]} \t\r\n':
            if token is not None:
                token.append(self.char)
            self.advance()
        if token is not None:
            try:
                return json.loads(''.join(token))
            except ValueError as exc:
                raise LedgerError("Invalid selected ledger value") from exc
        return None


def _heldout(formulas: set[str], seed: int) -> set[str]:
    if len(formulas) < HELDOUT_PRECURSORS:
        raise LedgerError("At least nine distinct precursors are required")
    groups: dict[str, list[str]] = {}
    for formula in sorted(formulas):
        match = re.match(r"[A-Z][a-z]?", formula)
        if not match:
            raise LedgerError("Precursor formula must start with an element symbol")
        groups.setdefault(match.group(), []).append(formula)
    rng = random.Random(seed)
    keys = sorted(groups)
    rng.shuffle(keys)
    for values in groups.values():
        rng.shuffle(values)
    selected: set[str] = set()
    while len(selected) < HELDOUT_PRECURSORS:
        for key in keys:
            if groups[key]:
                selected.add(groups[key].pop())
                if len(selected) == HELDOUT_PRECURSORS:
                    break
    return selected


def ingest(path: str | Path = DEFAULT_LEDGER, *, seed: int = SPLIT_SEED) -> tuple[list[Item], list[ItemProvenance]]:
    """Project permitted input fields and return schema-validated items and provenance.

    Exactly nine precursors are sampled across first-element groups. The same
    ledger and seed give the same selection regardless of sample order.
    ``dwell_h`` is ``synthesis.heating_time`` converted from minutes to hours
    (see ``HEATING_TIME_SOURCE``); it is None when the ledger has no heating time.
    """
    path = Path(path)
    with path.open(encoding="utf-8") as stream:
        reader = _ProjectionReader(stream)
        projected = reader.value(_SELECTION)
        reader.whitespace()
        if reader.char:
            raise LedgerError("Trailing content in ledger")
    if not isinstance(projected, dict) or not isinstance(projected.get("samples"), list):
        raise LedgerError("Ledger must contain a samples array")
    records = []
    ids: set[str] = set()
    formulas: set[str] = set()
    for index, sample in enumerate(projected["samples"]):
        if not isinstance(sample, dict):
            raise LedgerRecordError(index, "must be an object")
        precursors = sample.get("precursors")
        synthesis = sample.get("synthesis")
        if not isinstance(precursors, list) or len(precursors) != 2:
            raise LedgerRecordError(index, "requires exactly two precursors")
        if not isinstance(synthesis, dict):
            raise LedgerRecordError(index, "is missing synthesis data and heating temperature")
        if synthesis.get("heating_temperature") is None:
            raise LedgerRecordError(index, "is missing synthesis.heating_temperature")
        names = []
        fields = ["sample_id", "precursors", "synthesis.heating_temperature"]
        for position, precursor in enumerate(precursors):
            if not isinstance(precursor, dict):
                raise LedgerRecordError(index, "has an invalid precursor")
            key = "formula_clean" if precursor.get("formula_clean") else "formula"
            name = precursor.get(key)
            if not isinstance(name, str) or not name.strip():
                raise LedgerRecordError(index, "has a missing precursor formula")
            names.append(name.strip())
            fields.append(f"precursors[{position}].{key}")
            if precursor.get("melting_point_c") is not None:
                fields.append(f"precursors[{position}].melting_point_c")
        item_id = sample.get("sample_id")
        if not isinstance(item_id, str) or not item_id.strip() or item_id in ids:
            raise LedgerRecordError(index, "has a missing or duplicate sample_id")
        ids.add(item_id)
        formulas.update(names)
        dwell_h = synthesis.get("heating_time")
        if dwell_h is not None:
            fields.append("synthesis.heating_time")
            # Strings and booleans are refused rather than coerced, so no value skips the conversion.
            if not isinstance(dwell_h, (int, float)) or isinstance(dwell_h, bool):
                raise LedgerRecordError(index, "has a non-numeric synthesis.heating_time")
            dwell_h = dwell_h / MINUTES_PER_HOUR
            fields.append(DWELL_PROVENANCE)
        values = dict(item_id=item_id, source="precursor_genome", precursor_a=names[0], precursor_b=names[1],
                      temperature_c=synthesis.get("heating_temperature"), dwell_h=dwell_h,
                      melting_point_a_c=precursors[0].get("melting_point_c"), melting_point_b_c=precursors[1].get("melting_point_c"))
        records.append((values, fields))
    selected = _heldout(formulas, seed)
    items: list[Item] = []
    provenance: list[ItemProvenance] = []
    for index, (values, fields) in enumerate(records):
        split = "heldout" if selected.intersection((values["precursor_a"], values["precursor_b"])) else "dev"
        try:
            item = Item(**values, split=split)
        except ValidationError as exc:
            # Pydantic quotes the offending input; report field names only and drop the chained error.
            names = ", ".join(sorted({".".join(map(str, error["loc"])) for error in exc.errors()}))
            raise LedgerRecordError(index, f"failed Item validation for {names}") from None
        for value in (item.temperature_c, item.dwell_h, item.melting_point_a_c, item.melting_point_b_c):
            if value is not None and not math.isfinite(value):
                raise LedgerRecordError(index, "has a non-finite measurement")
        items.append(item)
        provenance.append(ItemProvenance(item_id=item.item_id, source_file=str(path), record_index=index, fields_used=fields))
    return items, provenance


def load_items(split: Literal["dev", "heldout"], path: str | Path = DEFAULT_LEDGER) -> list[Item]:
    """Load agent-visible items for one split."""
    if split not in ("dev", "heldout"):
        raise ValueError("split must be 'dev' or 'heldout'")
    items, _ = ingest(path)
    return [item for item in items if item.split == split]

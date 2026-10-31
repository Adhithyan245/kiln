"""Synthetic-only tests for the B0 and B0-T rules.

Every number below is made up to exercise the code: the thresholds and Tammann
fractions are not proposed protocol values, and no experimental outcome is used.
"""

import unittest
from typing import get_args

from pydantic import ValidationError

from kiln.baselines.b0 import (
    DrivingForceConfig,
    DrivingForceDecision,
    DrivingForceInput,
    TammannConfig,
    TammannDecision,
    b0_driving_force,
    b0_tammann,
    run_b0,
    run_b0_t,
)
from kiln.schemas import ConditionId, Item, ReviewFlag, ReviewReason


def synthetic_item(item_id="syn-1", temperature_c=700.0, mp_a=None, mp_b=None, split="dev"):
    return Item(
        item_id=item_id, source="alab_demo", precursor_a="SynA", precursor_b="SynB",
        temperature_c=temperature_c, melting_point_a_c=mp_a, melting_point_b_c=mp_b, split=split,
    )


def energy(item_id, dE, evidence=("run:compute:1",)):
    return DrivingForceInput(item_id=item_id, dE_ev_per_atom=dE, evidence=evidence)


class ConfigTests(unittest.TestCase):
    def test_every_setting_must_be_supplied(self):
        with self.assertRaises(ValidationError):
            DrivingForceConfig()
        with self.assertRaises(ValidationError):
            TammannConfig()
        with self.assertRaises(ValidationError):
            TammannConfig(tammann_fraction=0.5)
        with self.assertRaises(ValidationError):
            TammannConfig(require="either")

    def test_rejects_non_finite_boolean_and_out_of_range_settings(self):
        for value in (float("nan"), float("inf"), True, "0.1", None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                DrivingForceConfig(dE_threshold_ev_per_atom=value)
        for value in (0, -0.1, 1.01, float("nan"), True):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                TammannConfig(tammann_fraction=value, require="either")
        with self.assertRaises(ValidationError):
            TammannConfig(tammann_fraction=0.5, require="any")
        with self.assertRaises(ValidationError):
            DrivingForceConfig(dE_threshold_ev_per_atom=-0.1, extra=1)

    def test_configs_are_immutable(self):
        config = DrivingForceConfig(dE_threshold_ev_per_atom=-0.1)
        with self.assertRaises(ValidationError):
            config.dE_threshold_ev_per_atom = 0.0


class DrivingForceInputTests(unittest.TestCase):
    def test_energy_must_be_stated_even_when_missing(self):
        with self.assertRaises(ValidationError):
            DrivingForceInput(item_id="syn-1", evidence=())
        missing = DrivingForceInput(item_id="syn-1", dE_ev_per_atom=None, evidence=())
        self.assertIsNone(missing.dE_ev_per_atom)

    def test_supplied_energy_needs_unique_evidence(self):
        with self.assertRaisesRegex(ValidationError, "at least one evidence id"):
            energy("syn-1", -0.2, evidence=())
        with self.assertRaisesRegex(ValidationError, "unique"):
            energy("syn-1", -0.2, evidence=("run:compute:1", "run:compute:1"))
        for bad in ("", " padded", True):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                energy("syn-1", -0.2, evidence=(bad,))

    def test_rejects_non_finite_or_boolean_energy(self):
        for value in (float("nan"), float("-inf"), False, "-0.2"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                energy("syn-1", value)


class B0Tests(unittest.TestCase):
    def setUp(self):
        self.config = DrivingForceConfig(dE_threshold_ev_per_atom=-0.25)
        self.item = synthetic_item()

    def test_threshold_is_inclusive_and_margin_is_signed(self):
        for dE, reacts in ((-0.5, True), (-0.25, True), (-0.125, False), (0.25, False)):
            with self.subTest(dE=dE):
                decision = b0_driving_force(self.item, energy("syn-1", dE), self.config)
                self.assertEqual(decision.condition, "B0")
                self.assertIs(decision.reacts, reacts)
                self.assertEqual(decision.margin_ev_per_atom, -0.25 - dE)
                self.assertEqual(decision.dE_threshold_ev_per_atom, -0.25)
                self.assertEqual(decision.evidence, ("run:compute:1",))
                self.assertEqual(decision.review_flags, ())

    def test_ranking_by_margin_does_not_depend_on_threshold(self):
        items = [synthetic_item(f"syn-{i}") for i in range(4)]
        energies = [energy(f"syn-{i}", dE) for i, dE in enumerate((0.25, -0.5, 0.0, -0.125))]
        orders = []
        for threshold in (-0.5, 0.0, 0.5):
            decisions = run_b0(items, energies, DrivingForceConfig(dE_threshold_ev_per_atom=threshold))
            orders.append(sorted(range(4), key=lambda i: decisions[i].margin_ev_per_atom))
        self.assertEqual(orders[0], orders[1])
        self.assertEqual(orders[1], orders[2])

    def test_missing_energy_is_flagged_not_imputed(self):
        supplied = energy("syn-1", None, evidence=("run:compute:7",))
        decision = b0_driving_force(self.item, supplied, self.config)
        self.assertIsNone(decision.reacts)
        self.assertIsNone(decision.margin_ev_per_atom)
        self.assertIsNone(decision.dE_ev_per_atom)
        self.assertEqual(len(decision.review_flags), 1)
        flag = decision.review_flags[0]
        self.assertEqual(flag.reason, ReviewReason.missing_evidence)
        self.assertEqual(flag.evidence, ["run:compute:7"])

    def test_rejects_mismatched_or_untyped_inputs(self):
        with self.assertRaisesRegex(ValueError, "not 'syn-1'"):
            b0_driving_force(self.item, energy("syn-2", -0.5), self.config)
        with self.assertRaises(TypeError):
            b0_driving_force(self.item, {"item_id": "syn-1", "dE_ev_per_atom": -0.5}, self.config)
        with self.assertRaises(TypeError):
            b0_driving_force(self.item, energy("syn-1", -0.5), {"dE_threshold_ev_per_atom": -0.25})
        with self.assertRaises(TypeError):
            b0_driving_force(self.item.model_dump(), energy("syn-1", -0.5), self.config)

    def test_batch_requires_exactly_one_entry_per_item(self):
        items = [synthetic_item("syn-1"), synthetic_item("syn-2")]
        with self.assertRaisesRegex(ValueError, "no energy entry"):
            run_b0(items, [energy("syn-1", -0.5)], self.config)
        with self.assertRaisesRegex(ValueError, "unknown items"):
            run_b0(items, [energy("syn-1", -0.5), energy("syn-2", -0.5), energy("syn-3", -0.5)], self.config)
        with self.assertRaisesRegex(ValueError, "duplicate energy"):
            run_b0(items, [energy("syn-1", -0.5), energy("syn-1", -0.1), energy("syn-2", -0.5)], self.config)
        with self.assertRaisesRegex(ValueError, "duplicate item_id"):
            run_b0([items[0], items[0]], [energy("syn-1", -0.5)], self.config)
        with self.assertRaisesRegex(ValueError, "at least one item"):
            run_b0([], [], self.config)

    def test_batch_keeps_item_order_and_reports_missing_entries(self):
        items = [synthetic_item("syn-2"), synthetic_item("syn-1")]
        decisions = run_b0(items, [energy("syn-1", -0.5), energy("syn-2", None, evidence=())], self.config)
        self.assertEqual([d.item_id for d in decisions], ["syn-2", "syn-1"])
        self.assertIsNone(decisions[0].reacts)
        self.assertTrue(decisions[1].reacts)


class B0TTests(unittest.TestCase):
    def test_tammann_temperature_uses_kelvin(self):
        # 0.5 * (1000 °C + 273.15) - 273.15 = 363.425 °C, not 0.5 * 1000 = 500 °C.
        config = TammannConfig(tammann_fraction=0.5, require="either")
        decision = b0_tammann(synthetic_item(temperature_c=400.0, mp_a=1000.0, mp_b=1500.0), config)
        self.assertAlmostEqual(decision.tammann_a_c, 363.425)
        self.assertAlmostEqual(decision.tammann_b_c, 613.425)
        self.assertAlmostEqual(decision.governing_tammann_c, 363.425)
        self.assertAlmostEqual(decision.margin_c, 400.0 - 363.425)
        self.assertTrue(decision.reacts)
        self.assertEqual(decision.condition, "B0-T")

    def test_either_uses_lower_and_both_uses_higher_tammann_temperature(self):
        item = synthetic_item(temperature_c=500.0, mp_a=1000.0, mp_b=1500.0)
        either = b0_tammann(item, TammannConfig(tammann_fraction=0.5, require="either"))
        both = b0_tammann(item, TammannConfig(tammann_fraction=0.5, require="both"))
        self.assertTrue(either.reacts)
        self.assertFalse(both.reacts)
        self.assertEqual(either.governing_tammann_c, either.tammann_a_c)
        self.assertEqual(both.governing_tammann_c, both.tammann_b_c)
        self.assertLess(both.margin_c, 0)

    def test_reaching_the_governing_temperature_counts_as_reacting(self):
        config = TammannConfig(tammann_fraction=0.5, require="either")
        probe = b0_tammann(synthetic_item(temperature_c=0.0, mp_a=1000.0, mp_b=1500.0), config)
        at = b0_tammann(synthetic_item(temperature_c=probe.governing_tammann_c, mp_a=1000.0, mp_b=1500.0), config)
        self.assertEqual(at.margin_c, 0.0)
        self.assertTrue(at.reacts)

    def test_missing_melting_point_is_flagged_not_imputed(self):
        config = TammannConfig(tammann_fraction=0.5, require="either")
        decision = b0_tammann(synthetic_item(temperature_c=900.0, mp_a=1000.0, mp_b=None), config)
        self.assertIsNone(decision.reacts)
        self.assertIsNone(decision.margin_c)
        self.assertIsNone(decision.governing_tammann_c)
        self.assertIsNone(decision.tammann_b_c)
        self.assertAlmostEqual(decision.tammann_a_c, 363.425)
        self.assertEqual(len(decision.review_flags), 1)
        flag = decision.review_flags[0]
        self.assertEqual(flag.reason, ReviewReason.missing_evidence)
        self.assertIn("melting_point_b_c (SynB)", flag.detail)
        self.assertNotIn("melting_point_a_c", flag.detail)

    def test_rejects_impossible_or_non_finite_temperatures(self):
        config = TammannConfig(tammann_fraction=0.5, require="both")
        for kwargs in (
            dict(temperature_c=float("nan"), mp_a=1000.0, mp_b=1500.0),
            dict(temperature_c=-273.15, mp_a=1000.0, mp_b=1500.0),
            dict(temperature_c=700.0, mp_a=-300.0, mp_b=1500.0),
            dict(temperature_c=700.0, mp_a=1000.0, mp_b=float("inf")),
        ):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                b0_tammann(synthetic_item(**kwargs), config)

    def test_batch_validates_items_and_runs_on_any_split(self):
        config = TammannConfig(tammann_fraction=0.5, require="either")
        items = [synthetic_item("syn-1", mp_a=1000.0, mp_b=1500.0),
                 synthetic_item("syn-2", mp_a=1000.0, mp_b=1500.0, split="heldout")]
        self.assertEqual([d.item_id for d in run_b0_t(items, config)], ["syn-1", "syn-2"])
        with self.assertRaisesRegex(ValueError, "duplicate item_id"):
            run_b0_t([items[0], items[0]], config)
        with self.assertRaisesRegex(ValueError, "at least one item"):
            run_b0_t([], config)


class SchemaCompatibilityTests(unittest.TestCase):
    def test_conditions_are_shared_condition_ids(self):
        conditions = set(get_args(ConditionId))
        for model in (DrivingForceDecision, TammannDecision):
            (condition,) = get_args(model.model_fields["condition"].annotation)
            self.assertIn(condition, conditions)

    def test_decisions_round_trip_through_json_with_shared_review_flags(self):
        item = synthetic_item(temperature_c=900.0, mp_a=1000.0, mp_b=None)
        decisions = [
            b0_driving_force(item, energy("syn-1", -0.5), DrivingForceConfig(dE_threshold_ev_per_atom=-0.25)),
            b0_driving_force(item, energy("syn-1", None, evidence=()), DrivingForceConfig(dE_threshold_ev_per_atom=-0.25)),
            b0_tammann(item, TammannConfig(tammann_fraction=0.5, require="both")),
        ]
        for decision in decisions:
            with self.subTest(decision=decision.condition):
                restored = type(decision).model_validate_json(decision.model_dump_json())
                self.assertEqual(restored, decision)
                for flag in restored.review_flags:
                    self.assertEqual(ReviewFlag.model_validate_json(flag.model_dump_json()), flag)

    def test_inconsistent_decisions_are_rejected_on_load(self):
        good = b0_driving_force(synthetic_item(), energy("syn-1", -0.5), DrivingForceConfig(dE_threshold_ev_per_atom=-0.25))
        payload = good.model_dump()
        for change in (
            {"reacts": False},
            {"reacts": None},
            {"margin_ev_per_atom": None},
            {"dE_ev_per_atom": None, "margin_ev_per_atom": None, "reacts": None},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                DrivingForceDecision.model_validate({**payload, **change})

    def test_decisions_hold_no_label_fields(self):
        forbidden = {"category", "reacted", "label", "labels"}
        for model in (DrivingForceDecision, TammannDecision, DrivingForceInput):
            self.assertFalse(forbidden & set(model.model_fields), model.__name__)


if __name__ == "__main__":
    unittest.main()

"""Synthetic-only tests for the B0, B0-T and B60meV rules.

Every number below is made up to exercise the code: the thresholds are not
proposed protocol values, and no experimental outcome is used.
"""

import math
import unittest
from typing import get_args

from pydantic import ValidationError

from kiln.baselines.b0 import (
    KELVIN_OFFSET,
    PREDICTION_BLOCKERS,
    BaselinePredictionUnavailable,
    CompetitionMarginConfig,
    CompetitionMarginCoverage,
    CompetitionMarginFeature,
    CompetitionMarginInput,
    DrivingForceConfig,
    DrivingForceDecision,
    DrivingForceInput,
    TemperatureRatioConfig,
    TemperatureRatioDecision,
    b0_driving_force,
    b0_temperature_ratio,
    competition_margin,
    competition_margin_coverage,
    run_b0,
    run_b0_t,
    run_competition_margin,
    to_predictions,
)
from kiln.schemas import ConditionId, Item, ReviewFlag, ReviewReason, RunConfig


def synthetic_item(item_id="syn-1", temperature_c=700.0, mp_a=None, mp_b=None, split="dev"):
    return Item(
        item_id=item_id, source="alab_demo", precursor_a="SynA", precursor_b="SynB",
        temperature_c=temperature_c, melting_point_a_c=mp_a, melting_point_b_c=mp_b, split=split,
    )


def energy(item_id, dE, evidence=("run:compute:1",)):
    return DrivingForceInput(item_id=item_id, dE_ev_per_atom=dE, evidence=evidence)


def energies(item_id, best, competing, best_evidence=("run:compute:1",), competing_evidence=("run:compute:2",)):
    return CompetitionMarginInput(
        item_id=item_id, dE_best_ev_per_atom=best, best_evidence=best_evidence,
        dE_competing_ev_per_atom=competing, competing_evidence=competing_evidence,
    )


def ratio_k(temperature_c, melting_point_c):
    return (temperature_c + 273.15) / (melting_point_c + 273.15)


class ConfigTests(unittest.TestCase):
    def test_every_setting_must_be_supplied(self):
        for config in (DrivingForceConfig, TemperatureRatioConfig, CompetitionMarginConfig):
            with self.subTest(config=config.__name__), self.assertRaises(ValidationError):
                config()

    def test_rejects_non_finite_boolean_and_out_of_range_settings(self):
        for value in (float("nan"), float("inf"), True, "0.1", None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                DrivingForceConfig(dE_threshold_ev_per_atom=value)
        for value in (0.0, -0.1, float("nan"), float("inf"), True, "0.5", None):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    TemperatureRatioConfig(ratio_threshold=value)
                with self.assertRaises(ValidationError):
                    CompetitionMarginConfig(margin_threshold_ev_per_atom=value)
        with self.assertRaises(ValidationError):
            DrivingForceConfig(dE_threshold_ev_per_atom=-0.1, extra=1)
        with self.assertRaises(ValidationError):
            TemperatureRatioConfig(ratio_threshold=0.5, tammann_fraction=0.5)

    def test_configs_are_immutable(self):
        for config, field, value in (
            (DrivingForceConfig(dE_threshold_ev_per_atom=-0.1), "dE_threshold_ev_per_atom", 0.0),
            (TemperatureRatioConfig(ratio_threshold=0.5), "ratio_threshold", 0.25),
            (CompetitionMarginConfig(margin_threshold_ev_per_atom=0.125), "margin_threshold_ev_per_atom", 0.25),
        ):
            with self.subTest(config=type(config).__name__), self.assertRaises(ValidationError):
                setattr(config, field, value)


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
        supplied = [energy(f"syn-{i}", dE) for i, dE in enumerate((0.25, -0.5, 0.0, -0.125))]
        orders = []
        for threshold in (-0.5, 0.0, 0.5):
            decisions = run_b0(items, supplied, DrivingForceConfig(dE_threshold_ev_per_atom=threshold))
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

    def test_batch_reads_generators_once_without_dropping_items(self):
        items = [synthetic_item("syn-1"), synthetic_item("syn-2")]
        decisions = run_b0(
            (item for item in items),
            (e for e in (energy("syn-1", -0.5), energy("syn-2", 0.25))),
            self.config,
        )
        self.assertEqual([d.item_id for d in decisions], ["syn-1", "syn-2"])
        self.assertEqual([d.reacts for d in decisions], [True, False])
        with self.assertRaisesRegex(ValueError, "at least one item"):
            run_b0((item for item in ()), [], self.config)
        with self.assertRaisesRegex(ValueError, "duplicate item_id"):
            run_b0((item for item in (items[0], items[0])), [energy("syn-1", -0.5)], self.config)

    def test_batch_keeps_item_order_and_reports_missing_entries(self):
        items = [synthetic_item("syn-2"), synthetic_item("syn-1")]
        decisions = run_b0(items, [energy("syn-1", -0.5), energy("syn-2", None, evidence=())], self.config)
        self.assertEqual([d.item_id for d in decisions], ["syn-2", "syn-1"])
        self.assertIsNone(decisions[0].reacts)
        self.assertTrue(decisions[1].reacts)


class B0TTests(unittest.TestCase):
    def setUp(self):
        self.config = TemperatureRatioConfig(ratio_threshold=0.5)

    def test_ratio_uses_kelvin_and_the_higher_melting_point(self):
        decision = b0_temperature_ratio(synthetic_item(temperature_c=400.0, mp_a=1000.0, mp_b=1500.0), self.config)
        self.assertEqual(decision.condition, "B0-T")
        self.assertEqual(decision.melting_point_higher_c, 1500.0)
        self.assertEqual(decision.ratio, ratio_k(400.0, 1500.0))
        self.assertAlmostEqual(decision.ratio, 673.15 / 1773.15)
        self.assertNotAlmostEqual(decision.ratio, 400.0 / 1500.0)
        self.assertFalse(decision.reacts)  # 0.3796... < 0.5
        self.assertEqual(decision.review_flags, ())

    def test_higher_melting_point_does_not_depend_on_precursor_order(self):
        forward = b0_temperature_ratio(synthetic_item(temperature_c=900.0, mp_a=1000.0, mp_b=1500.0), self.config)
        reverse = b0_temperature_ratio(synthetic_item(temperature_c=900.0, mp_a=1500.0, mp_b=1000.0), self.config)
        self.assertEqual(forward.melting_point_higher_c, reverse.melting_point_higher_c)
        self.assertEqual(forward.ratio, reverse.ratio)
        self.assertTrue(forward.reacts)  # 1173.15 / 1773.15 = 0.66... >= 0.5

    def test_threshold_is_inclusive(self):
        item = synthetic_item(temperature_c=600.0, mp_a=1000.0, mp_b=1200.0)
        probe = b0_temperature_ratio(item, self.config)
        at = b0_temperature_ratio(item, TemperatureRatioConfig(ratio_threshold=probe.ratio))
        above = b0_temperature_ratio(item, TemperatureRatioConfig(ratio_threshold=math.nextafter(probe.ratio, math.inf)))
        self.assertTrue(at.reacts)
        self.assertFalse(above.reacts)
        self.assertEqual(at.ratio, above.ratio)

    def test_ranking_by_ratio_does_not_depend_on_threshold(self):
        items = [synthetic_item(f"syn-{i}", temperature_c=t, mp_a=1000.0, mp_b=mp)
                 for i, (t, mp) in enumerate(((500.0, 1400.0), (900.0, 1100.0), (700.0, 1600.0), (300.0, 900.0)))]
        orders = []
        for threshold in (0.25, 0.5, 0.75):
            decisions = run_b0_t(items, TemperatureRatioConfig(ratio_threshold=threshold))
            orders.append(sorted(range(4), key=lambda i: decisions[i].ratio))
        self.assertEqual(orders[0], orders[1])
        self.assertEqual(orders[1], orders[2])

    def test_missing_melting_point_is_flagged_not_imputed(self):
        for mp_a, mp_b, missing, present in (
            (1000.0, None, ["melting_point_b_c (SynB)"], "melting_point_a_c"),
            (None, 1000.0, ["melting_point_a_c (SynA)"], "melting_point_b_c"),
            (None, None, ["melting_point_a_c (SynA)", "melting_point_b_c (SynB)"], None),
        ):
            with self.subTest(mp_a=mp_a, mp_b=mp_b):
                # The known melting point alone would put the ratio far above the
                # threshold, but the missing one could be higher.
                decision = b0_temperature_ratio(synthetic_item(temperature_c=900.0, mp_a=mp_a, mp_b=mp_b), self.config)
                self.assertIsNone(decision.reacts)
                self.assertIsNone(decision.ratio)
                self.assertIsNone(decision.melting_point_higher_c)
                self.assertEqual((decision.melting_point_a_c, decision.melting_point_b_c), (mp_a, mp_b))
                self.assertEqual(len(decision.review_flags), 1)
                flag = decision.review_flags[0]
                self.assertEqual(flag.reason, ReviewReason.missing_evidence)
                for name in missing:
                    self.assertIn(name, flag.detail)
                if present is not None:
                    self.assertNotIn(present, flag.detail)

    def test_rejects_impossible_or_non_finite_temperatures(self):
        for kwargs in (
            dict(temperature_c=float("nan"), mp_a=1000.0, mp_b=1500.0),
            dict(temperature_c=-273.15, mp_a=1000.0, mp_b=1500.0),
            dict(temperature_c=700.0, mp_a=-300.0, mp_b=1500.0),
            dict(temperature_c=700.0, mp_a=1000.0, mp_b=-KELVIN_OFFSET),
            dict(temperature_c=700.0, mp_a=1000.0, mp_b=float("inf")),
            dict(temperature_c=700.0, mp_a=None, mp_b=float("nan")),
        ):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                b0_temperature_ratio(synthetic_item(**kwargs), self.config)

    def test_rejects_untyped_inputs(self):
        item = synthetic_item(mp_a=1000.0, mp_b=1500.0)
        with self.assertRaises(TypeError):
            b0_temperature_ratio(item, {"ratio_threshold": 0.5})
        with self.assertRaises(TypeError):
            b0_temperature_ratio(item.model_dump(), self.config)

    def test_batch_validates_items_and_runs_on_any_split(self):
        items = [synthetic_item("syn-1", mp_a=1000.0, mp_b=1500.0),
                 synthetic_item("syn-2", mp_a=1000.0, mp_b=1500.0, split="heldout")]
        self.assertEqual([d.item_id for d in run_b0_t(items, self.config)], ["syn-1", "syn-2"])
        with self.assertRaisesRegex(ValueError, "duplicate item_id"):
            run_b0_t([items[0], items[0]], self.config)
        with self.assertRaisesRegex(ValueError, "at least one item"):
            run_b0_t([], self.config)

    def test_batch_reads_generators_once_without_dropping_items(self):
        items = [synthetic_item("syn-1", temperature_c=900.0, mp_a=1000.0, mp_b=1500.0),
                 synthetic_item("syn-2", mp_a=1000.0, mp_b=None)]
        decisions = run_b0_t((item for item in items), self.config)
        self.assertEqual([d.item_id for d in decisions], ["syn-1", "syn-2"])
        self.assertTrue(decisions[0].reacts)
        self.assertIsNone(decisions[1].reacts)
        self.assertEqual(len(decisions[1].review_flags), 1)
        with self.assertRaisesRegex(ValueError, "at least one item"):
            run_b0_t((item for item in ()), self.config)

    def test_docstring_marks_the_circularity_reason_unverified(self):
        import kiln.baselines.b0 as b0

        self.assertIn("UNVERIFIED", b0.__doc__)
        self.assertIn("reviewer-sourced", b0.__doc__)


class CompetitionMarginInputTests(unittest.TestCase):
    def test_both_energies_must_be_stated_even_when_missing(self):
        with self.assertRaises(ValidationError):
            CompetitionMarginInput(item_id="syn-1", best_evidence=(), competing_evidence=())
        with self.assertRaises(ValidationError):
            CompetitionMarginInput(item_id="syn-1", dE_best_ev_per_atom=None, best_evidence=(), competing_evidence=())
        missing = energies("syn-1", None, None, best_evidence=(), competing_evidence=())
        self.assertIsNone(missing.dE_best_ev_per_atom)
        self.assertIsNone(missing.dE_competing_ev_per_atom)

    def test_each_supplied_energy_needs_its_own_unique_evidence(self):
        with self.assertRaisesRegex(ValidationError, "best reaction energy needs at least one evidence id"):
            energies("syn-1", -0.5, -0.25, best_evidence=())
        with self.assertRaisesRegex(ValidationError, "competing reaction energy needs at least one evidence id"):
            energies("syn-1", -0.5, -0.25, competing_evidence=())
        with self.assertRaisesRegex(ValidationError, "unique"):
            energies("syn-1", -0.5, -0.25, best_evidence=("run:compute:1", "run:compute:1"))
        for bad in ("", " padded", True):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                energies("syn-1", -0.5, -0.25, competing_evidence=(bad,))
        # One request may supply both energies.
        shared = energies("syn-1", -0.5, -0.25, best_evidence=("run:compute:1",), competing_evidence=("run:compute:1",))
        self.assertEqual(shared.best_evidence, shared.competing_evidence)

    def test_best_reaction_must_be_the_most_negative(self):
        with self.assertRaisesRegex(ValidationError, "must not exceed"):
            energies("syn-1", -0.25, -0.5)
        tie = energies("syn-1", -0.25, -0.25)
        self.assertEqual(tie.dE_best_ev_per_atom, tie.dE_competing_ev_per_atom)

    def test_rejects_non_finite_or_boolean_energies(self):
        for value in (float("nan"), float("-inf"), False, "-0.2"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    energies("syn-1", value, 0.0)
                with self.assertRaises(ValidationError):
                    energies("syn-1", -1.0, value)


class CompetitionMarginTests(unittest.TestCase):
    def setUp(self):
        self.config = CompetitionMarginConfig(margin_threshold_ev_per_atom=0.25)
        self.item = synthetic_item()

    def test_margin_is_competing_minus_best_and_marker_is_inclusive(self):
        for best, competing, decisive in ((-0.75, -0.25, True), (-0.5, -0.25, True), (-0.375, -0.25, False), (-0.25, -0.25, False)):
            with self.subTest(best=best, competing=competing):
                feature = competition_margin(self.item, energies("syn-1", best, competing), self.config)
                self.assertEqual(feature.condition, "B60meV")
                self.assertEqual(feature.margin_ev_per_atom, competing - best)
                self.assertGreaterEqual(feature.margin_ev_per_atom, 0)
                self.assertIs(feature.decisive, decisive)
                self.assertEqual(feature.margin_threshold_ev_per_atom, 0.25)
                self.assertEqual(feature.best_evidence, ("run:compute:1",))
                self.assertEqual(feature.competing_evidence, ("run:compute:2",))
                self.assertEqual(feature.review_flags, ())

    def test_ranking_by_margin_does_not_depend_on_threshold(self):
        items = [synthetic_item(f"syn-{i}") for i in range(4)]
        supplied = [energies(f"syn-{i}", best, -0.125) for i, best in enumerate((-0.25, -1.0, -0.5, -0.125))]
        orders = []
        for threshold in (0.0625, 0.25, 1.0):
            features = run_competition_margin(items, supplied, CompetitionMarginConfig(margin_threshold_ev_per_atom=threshold))
            orders.append(sorted(range(4), key=lambda i: features[i].margin_ev_per_atom))
        self.assertEqual(orders[0], orders[1])
        self.assertEqual(orders[1], orders[2])

    def test_missing_energies_are_flagged_not_imputed(self):
        for best, competing, missing, best_ev, competing_ev in (
            (-0.5, None, ["best competing reaction energy"], ("run:compute:1",), ("run:compute:9",)),
            (None, -0.25, ["best reaction energy"], (), ("run:compute:2",)),
            (None, None, ["best reaction energy", "best competing reaction energy"], (), ()),
        ):
            with self.subTest(best=best, competing=competing):
                supplied = energies("syn-1", best, competing, best_evidence=best_ev, competing_evidence=competing_ev)
                feature = competition_margin(self.item, supplied, self.config)
                self.assertIsNone(feature.margin_ev_per_atom)
                self.assertIsNone(feature.decisive)
                self.assertEqual((feature.dE_best_ev_per_atom, feature.dE_competing_ev_per_atom), (best, competing))
                self.assertEqual(len(feature.review_flags), 1)
                flag = feature.review_flags[0]
                self.assertEqual(flag.reason, ReviewReason.missing_evidence)
                for name in missing:
                    self.assertIn(name, flag.detail)
                self.assertEqual(flag.evidence, list(dict.fromkeys(best_ev + competing_ev)))
        only_best = competition_margin(self.item, energies("syn-1", -0.5, None, competing_evidence=()), self.config)
        self.assertNotIn("Missing the best reaction energy", only_best.review_flags[0].detail)

    def test_feature_is_not_a_reacts_rule(self):
        forbidden = {"reacts", "p_react", "category", "reacted", "label", "labels"}
        for model in (CompetitionMarginFeature, CompetitionMarginInput, CompetitionMarginCoverage):
            self.assertFalse(forbidden & set(model.model_fields), model.__name__)

    def test_rejects_mismatched_or_untyped_inputs(self):
        with self.assertRaisesRegex(ValueError, "not 'syn-1'"):
            competition_margin(self.item, energies("syn-2", -0.5, -0.25), self.config)
        with self.assertRaises(TypeError):
            competition_margin(self.item, energy("syn-1", -0.5), self.config)
        with self.assertRaises(TypeError):
            competition_margin(self.item, energies("syn-1", -0.5, -0.25), {"margin_threshold_ev_per_atom": 0.25})
        with self.assertRaises(TypeError):
            competition_margin(self.item.model_dump(), energies("syn-1", -0.5, -0.25), self.config)

    def test_batch_requires_exactly_one_entry_per_item(self):
        items = [synthetic_item("syn-1"), synthetic_item("syn-2")]
        both = [energies("syn-1", -0.5, -0.25), energies("syn-2", -0.5, -0.25)]
        with self.assertRaisesRegex(ValueError, "no competition energy entry"):
            run_competition_margin(items, both[:1], self.config)
        with self.assertRaisesRegex(ValueError, "unknown items"):
            run_competition_margin(items, both + [energies("syn-3", -0.5, -0.25)], self.config)
        with self.assertRaisesRegex(ValueError, "duplicate competition energy"):
            run_competition_margin(items, both + both[:1], self.config)
        with self.assertRaisesRegex(ValueError, "duplicate item_id"):
            run_competition_margin([items[0], items[0]], both[:1], self.config)
        with self.assertRaisesRegex(ValueError, "at least one item"):
            run_competition_margin([], [], self.config)
        with self.assertRaises(TypeError):
            run_competition_margin(items, [energy("syn-1", -0.5), energy("syn-2", -0.5)], self.config)

    def test_batch_reads_generators_once_and_keeps_order(self):
        items = [synthetic_item("syn-2"), synthetic_item("syn-1")]
        features = run_competition_margin(
            (item for item in items),
            (e for e in (energies("syn-1", -0.5, -0.25), energies("syn-2", None, -0.25, best_evidence=()))),
            self.config,
        )
        self.assertEqual([f.item_id for f in features], ["syn-2", "syn-1"])
        self.assertEqual([f.decisive for f in features], [None, True])


class CompetitionMarginCoverageTests(unittest.TestCase):
    def setUp(self):
        self.config = CompetitionMarginConfig(margin_threshold_ev_per_atom=0.25)
        items = [synthetic_item(f"syn-{i}") for i in range(5)]
        supplied = [
            energies("syn-0", -0.75, -0.25),                        # margin 0.5, decisive
            energies("syn-1", -0.5, -0.25),                         # margin 0.25, decisive (inclusive)
            energies("syn-2", -0.375, -0.25),                       # margin 0.125, not decisive
            energies("syn-3", None, -0.25, best_evidence=()),       # undetermined
            energies("syn-4", -0.5, None, competing_evidence=()),   # undetermined
        ]
        self.features = run_competition_margin(items, supplied, self.config)

    def test_fraction_decisive_among_known_margins_keeps_every_item(self):
        coverage = competition_margin_coverage(self.features)
        self.assertEqual(coverage.condition, "B60meV")
        self.assertEqual(coverage.margin_threshold_ev_per_atom, 0.25)
        self.assertEqual(
            (coverage.n_items, coverage.n_known_margin, coverage.n_decisive, coverage.n_undetermined),
            (5, 3, 2, 2),
        )
        self.assertEqual(coverage.coverage, 2 / 3)
        self.assertEqual(coverage.undetermined_item_ids, ("syn-3", "syn-4"))

    def test_coverage_is_undefined_without_any_known_margin(self):
        coverage = competition_margin_coverage(f for f in self.features if f.margin_ev_per_atom is None)
        self.assertEqual((coverage.n_items, coverage.n_known_margin, coverage.n_decisive), (2, 0, 0))
        self.assertIsNone(coverage.coverage)

    def test_rejects_mixed_thresholds_duplicates_and_bad_input(self):
        other = competition_margin(
            synthetic_item("syn-9"), energies("syn-9", -0.5, -0.25),
            CompetitionMarginConfig(margin_threshold_ev_per_atom=0.125),
        )
        with self.assertRaisesRegex(ValueError, "one margin threshold"):
            competition_margin_coverage(self.features + [other])
        with self.assertRaisesRegex(ValueError, "duplicate feature"):
            competition_margin_coverage(self.features + self.features[:1])
        with self.assertRaisesRegex(ValueError, "at least one feature"):
            competition_margin_coverage(iter(()))
        with self.assertRaises(TypeError):
            competition_margin_coverage([f.model_dump() for f in self.features])

    def test_inconsistent_coverage_is_rejected_on_load(self):
        payload = competition_margin_coverage(self.features).model_dump()
        for change in (
            {"n_undetermined": 1, "undetermined_item_ids": ("syn-3",)},
            {"undetermined_item_ids": ("syn-3",)},
            {"coverage": 0.5},
            {"n_decisive": 4},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                CompetitionMarginCoverage.model_validate({**payload, **change})


class SchemaCompatibilityTests(unittest.TestCase):
    def test_b0_and_b0_t_conditions_are_shared_condition_ids(self):
        conditions = set(get_args(ConditionId))
        for model in (DrivingForceDecision, TemperatureRatioDecision):
            (condition,) = get_args(model.model_fields["condition"].annotation)
            self.assertIn(condition, conditions)

    def test_b60mev_is_not_yet_a_shared_condition_id(self):
        # Adding it needs a schemas.py change; until then no RunConfig can name it.
        (condition,) = get_args(CompetitionMarginFeature.model_fields["condition"].annotation)
        self.assertEqual(condition, "B60meV")
        self.assertNotIn(condition, set(get_args(ConditionId)))
        with self.assertRaises(ValidationError):
            RunConfig(run_id="syn-run", condition="B60meV", seed=0, model="synthetic-no-llm")

    def test_results_round_trip_through_json_with_shared_review_flags(self):
        item = synthetic_item(temperature_c=900.0, mp_a=1000.0, mp_b=None)
        complete = synthetic_item(temperature_c=900.0, mp_a=1000.0, mp_b=1234.5)
        results = [
            b0_driving_force(item, energy("syn-1", -0.5), DrivingForceConfig(dE_threshold_ev_per_atom=-0.25)),
            b0_driving_force(item, energy("syn-1", None, evidence=()), DrivingForceConfig(dE_threshold_ev_per_atom=-0.25)),
            b0_temperature_ratio(item, TemperatureRatioConfig(ratio_threshold=0.5)),
            b0_temperature_ratio(complete, TemperatureRatioConfig(ratio_threshold=0.5)),
            competition_margin(item, energies("syn-1", -0.5, -0.1), CompetitionMarginConfig(margin_threshold_ev_per_atom=0.06)),
            competition_margin(item, energies("syn-1", None, -0.1, best_evidence=()), CompetitionMarginConfig(margin_threshold_ev_per_atom=0.06)),
        ]
        for result in results:
            with self.subTest(result=result.condition):
                restored = type(result).model_validate_json(result.model_dump_json())
                self.assertEqual(restored, result)
                for flag in restored.review_flags:
                    self.assertEqual(ReviewFlag.model_validate_json(flag.model_dump_json()), flag)

    def test_inconsistent_results_are_rejected_on_load(self):
        cases = [
            (
                b0_driving_force(synthetic_item(), energy("syn-1", -0.5), DrivingForceConfig(dE_threshold_ev_per_atom=-0.25)),
                ({"reacts": False}, {"reacts": None}, {"margin_ev_per_atom": None},
                 {"dE_ev_per_atom": None, "margin_ev_per_atom": None, "reacts": None}),
            ),
            (
                b0_temperature_ratio(synthetic_item(temperature_c=900.0, mp_a=1000.0, mp_b=1500.0),
                                     TemperatureRatioConfig(ratio_threshold=0.5)),
                ({"reacts": False}, {"reacts": None}, {"ratio": 0.9}, {"ratio": None, "reacts": None},
                 {"melting_point_higher_c": 1000.0}, {"melting_point_b_c": None},
                 {"ratio_threshold": 0.9}, {"temperature_c": -273.15}, {"melting_point_a_c": -300.0}),
            ),
            (
                competition_margin(synthetic_item(), energies("syn-1", -0.5, -0.25),
                                   CompetitionMarginConfig(margin_threshold_ev_per_atom=0.25)),
                ({"decisive": False}, {"decisive": None}, {"margin_ev_per_atom": 0.5},
                 {"margin_ev_per_atom": None, "decisive": None},
                 {"dE_best_ev_per_atom": 0.0, "margin_ev_per_atom": -0.25, "decisive": False},
                 {"margin_threshold_ev_per_atom": 0.5}),
            ),
        ]
        for good, changes in cases:
            payload = good.model_dump()
            for change in changes:
                with self.subTest(model=type(good).__name__, change=change), self.assertRaises(ValidationError):
                    type(good).model_validate({**payload, **change})

    def test_results_hold_no_label_fields(self):
        forbidden = {"category", "reacted", "label", "labels"}
        for model in (
            DrivingForceDecision, TemperatureRatioDecision, CompetitionMarginFeature,
            DrivingForceInput, CompetitionMarginInput, CompetitionMarginCoverage,
        ):
            self.assertFalse(forbidden & set(model.model_fields), model.__name__)


def run_config(condition):
    return RunConfig(run_id="syn-run", condition=condition, seed=0, model="synthetic-no-llm")


class ToPredictionsTests(unittest.TestCase):
    def setUp(self):
        items = [synthetic_item("syn-1", mp_a=1000.0, mp_b=1500.0),
                 synthetic_item("syn-2", mp_a=1000.0, mp_b=None)]
        self.b0 = run_b0(items, [energy("syn-1", -0.5), energy("syn-2", None, evidence=())],
                         DrivingForceConfig(dE_threshold_ev_per_atom=-0.25))
        self.b0_t = run_b0_t(items, TemperatureRatioConfig(ratio_threshold=0.5))
        self.b60mev = run_competition_margin(
            items, [energies("syn-1", -0.5, -0.25), energies("syn-2", None, None, best_evidence=(), competing_evidence=())],
            CompetitionMarginConfig(margin_threshold_ev_per_atom=0.25),
        )

    def test_valid_inputs_fail_closed_and_name_every_blocker(self):
        for condition, decisions in (("B0", self.b0), ("B0-T", self.b0_t)):
            for supplied in (decisions, iter(decisions)):
                with self.subTest(condition=condition, supplied=type(supplied).__name__):
                    with self.assertRaises(BaselinePredictionUnavailable) as caught:
                        to_predictions(supplied, run_config(condition))
                    message = str(caught.exception)
                    for blocker in PREDICTION_BLOCKERS:
                        self.assertIn(blocker, message)
        joined = " ".join(PREDICTION_BLOCKERS)
        for reference in ("score.py", "AgentName", "OPEN-08", "OPEN-23", "OPEN-16", "B60meV", "Szymanski", "ConditionId"):
            self.assertIn(reference, joined)

    def test_b60mev_features_never_become_predictions(self):
        for condition in ("B0", "B0-T"):
            with self.subTest(condition=condition), self.assertRaises(TypeError):
                to_predictions(self.b60mev, run_config(condition))
        with self.assertRaisesRegex(ValueError, "B60meV is not a schemas.ConditionId"):
            to_predictions(self.b60mev, run_config("C1"))

    def test_unavailable_is_distinct_from_wiring_errors(self):
        self.assertFalse(issubclass(BaselinePredictionUnavailable, (TypeError, ValueError)))

    def test_wiring_mistakes_are_reported_before_failing_closed(self):
        with self.assertRaises(TypeError):
            to_predictions(self.b0, run_config("B0").model_dump())
        with self.assertRaisesRegex(ValueError, "not B0 or B0-T"):
            to_predictions(self.b0, run_config("C1"))
        with self.assertRaises(TypeError):
            to_predictions(self.b0_t, run_config("B0"))
        with self.assertRaises(TypeError):
            to_predictions(self.b0, run_config("B0-T"))
        with self.assertRaisesRegex(ValueError, "at least one decision"):
            to_predictions(iter(()), run_config("B0"))
        with self.assertRaisesRegex(ValueError, "duplicate decision"):
            to_predictions([self.b0[0], self.b0[0]], run_config("B0"))


if __name__ == "__main__":
    unittest.main()

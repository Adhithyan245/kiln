"""Synthetic-only tests for the unfrozen B1 input and fold contracts."""

import unittest

import pytest
from pydantic import ValidationError

from kiln.baselines.b1 import (
    B1ConfigurationError, B1ConvergenceError, B1Engine, B1Settings, FeatureDefinition,
    FeatureRow, leave_one_precursor_out, validate_features,
)


class B1Tests(unittest.TestCase):
    def setUp(self):
        self.names = ("synthetic_x", "synthetic_y")
        self.rows = (
            FeatureRow(item_id="one", precursor_a="A", precursor_b="B", split="dev", values=(1.0, 2.0)),
            FeatureRow(item_id="two", precursor_a="C", precursor_b="A", split="dev", values=(3.0, 4.0)),
            FeatureRow(item_id="three", precursor_a="C", precursor_b="D", split="dev", values=(5.0, 6.0)),
        )

    def test_folds_exclude_held_out_precursor_from_both_positions(self):
        folds = leave_one_precursor_out(self.names, self.rows)
        self.assertEqual([fold.precursor for fold in folds], ["A", "B", "C", "D"])
        a = folds[0]
        self.assertEqual(a.train_indices, (2,))
        self.assertEqual(a.test_indices, (0, 1))
        for fold in folds:
            for index in fold.train_indices:
                self.assertNotIn(fold.precursor, (self.rows[index].precursor_a, self.rows[index].precursor_b))
            for index in fold.test_indices:
                self.assertIn(fold.precursor, (self.rows[index].precursor_a, self.rows[index].precursor_b))
            self.assertEqual(set(fold.train_indices) | set(fold.test_indices), set(range(len(self.rows))))

    def test_rejects_heldout_and_bad_features(self):
        for names, rows in (
            ((), self.rows),
            (("x", "x"), self.rows),
            (self.names, (FeatureRow(item_id="x", precursor_a="A", precursor_b="B", split="heldout", values=(1, 2)),)),
            (self.names, (FeatureRow(item_id="x", precursor_a="A", precursor_b="B", split="dev", values=(1,)),)),
            (self.names, (self.rows[0], self.rows[0])),
        ):
            with self.subTest(names=names, rows=rows), self.assertRaises(ValueError):
                validate_features(names, rows)

    def test_models_reject_invalid_values_and_are_frozen(self):
        for values in ((1, True), (1, float("nan")), (1, float("inf")), (1, "2")):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                FeatureRow(item_id="x", precursor_a="A", precursor_b="B", split="dev", values=values)
        with self.assertRaises(ValidationError):
            FeatureRow(item_id="x", precursor_a="A", precursor_b="B", split="other", values=(1, 2))
        with self.assertRaises(ValidationError):
            self.rows[0].split = "heldout"
        with self.assertRaises(ValidationError):
            leave_one_precursor_out(self.names, self.rows)[0].precursor = "changed"

    def test_rejects_fold_without_training_rows(self):
        with self.assertRaisesRegex(ValueError, "no training rows"):
            leave_one_precursor_out(self.names, (self.rows[0],))


# All features, targets and freeze attestations below are synthetic.


def synthetic_settings(**overrides):
    args = dict(
        features=(FeatureDefinition(name="x", description="synthetic numeric value"),),
        learning_rate=1.0, l2=1.0, tolerance=1e-8, max_iterations=1000, fit_intercept=True,
    )
    args.update(overrides)
    return B1Settings(**args)


def synthetic_rows():
    return tuple(
        FeatureRow(item_id=str(i), precursor_a=f"a{i}", precursor_b=f"b{i}",
                   split="dev", values=(float(i % 2),))
        for i in range(6)
    )


def synthetic_targets():
    return {str(i): i % 2 for i in range(6)}


def synthetic_engine(settings=None):
    settings = settings or synthetic_settings()
    return B1Engine(settings, verify_frozen_settings=lambda digest: digest == settings.digest())


def test_freeze_boundary_and_digest():
    settings = synthetic_settings()
    for verifier in (None, lambda _: False, lambda _: 1):
        with pytest.raises(B1ConfigurationError, match="not been verified"):
            B1Engine(settings, verify_frozen_settings=verifier)
    def broken(_):
        raise RuntimeError("synthetic failure")
    with pytest.raises(B1ConfigurationError, match="Unable to verify"):
        B1Engine(settings, verify_frozen_settings=broken)
    assert synthetic_engine(settings).settings_digest == settings.digest()
    assert settings.digest() != synthetic_settings(l2=2.0).digest()
    assert settings.digest() != synthetic_settings(features=(FeatureDefinition(name="x", description="different"),)).digest()


def test_predictions_are_per_fold_and_test_targets_do_not_leak():
    rows, targets = synthetic_rows(), synthetic_targets()
    engine = synthetic_engine()
    results = engine.predict_folds(rows, targets)
    assert len(results) == 12
    assert {(p.precursor, p.item_id) for p in results} == {
        (precursor, row.item_id) for row in rows for precursor in (row.precursor_a, row.precursor_b)
    }
    assert all(0 < p.score < 1 for p in results)
    changed = dict(targets, **{"0": 1})
    changed_results = engine.predict_folds(rows, changed)
    before = next(p.score for p in results if p.precursor == "a0")
    after = next(p.score for p in changed_results if p.precursor == "a0")
    assert before == after
    assert next(p.score for p in results if p.precursor == "a1") != next(
        p.score for p in changed_results if p.precursor == "a1"
    )


def test_synthetic_constant_features_give_balanced_half_score():
    rows = tuple(row.model_copy(update={"values": (0.0,)}) for row in synthetic_rows())
    settings = synthetic_settings(fit_intercept=False)
    assert all(p.score == 0.5 for p in synthetic_engine(settings).predict_folds(rows, synthetic_targets()))


def test_targets_and_folds_fail_closed():
    rows, targets = synthetic_rows(), synthetic_targets()
    engine = synthetic_engine()
    for bad in ({}, dict(targets, extra=1), dict(targets, **{"0": True}), dict(targets, **{"0": 2})):
        with pytest.raises(ValueError, match="targets"):
            engine.predict_folds(rows, bad)
    with pytest.raises(ValueError, match="both classes"):
        engine.predict_folds(rows, {str(i): 0 for i in range(6)})
    heldout = rows[0].model_copy(update={"split": "heldout"})
    with pytest.raises(ValueError, match="split 'dev'"):
        engine.predict_folds((heldout, *rows[1:]), targets)
    with pytest.raises(ValueError, match="finite"):
        engine.predict_folds((rows[0].model_copy(update={"values": (float('nan'),)}), *rows[1:]), targets)


def test_rejects_nonconvergence_and_invalid_settings():
    engine = synthetic_engine(synthetic_settings(max_iterations=1, tolerance=1e-20))
    with pytest.raises(B1ConvergenceError, match="did not converge"):
        engine.predict_folds(synthetic_rows(), synthetic_targets())
    for kwargs in ({"learning_rate": 0.0}, {"l2": -1.0}, {"max_iterations": 0},
                   {"tolerance": float("nan")}, {"features": ()},
                   {"features": (FeatureDefinition(name="x", description="x"),) * 2}):
        with pytest.raises(ValidationError):
            synthetic_settings(**kwargs)

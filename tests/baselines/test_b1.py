"""Synthetic-only tests for the unfrozen B1 input and fold contracts."""

import unittest

from pydantic import ValidationError

from kiln.baselines.b1 import FeatureRow, leave_one_precursor_out, validate_features


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


if __name__ == "__main__":
    unittest.main()

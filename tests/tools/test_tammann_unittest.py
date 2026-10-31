"""Dependency-free checks usable before the project environment is installed."""

import math
import unittest

from kiln.tools.tammann import checked_tammann_c, tammann_c


class TammannTests(unittest.TestCase):
    def test_kelvin_conversion_and_missing_input(self):
        self.assertAlmostEqual(tammann_c(626.85), 326.85)
        self.assertIsNone(tammann_c(None))

    def test_invalid_inputs(self):
        for value in (-273.15, -300, math.nan, math.inf, True, "900"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                tammann_c(value)

    def test_unverified_melting_is_flagged_before_use(self):
        value, status = checked_tammann_c(626.85, semantics="possible_decomposition_or_dehydration")
        self.assertAlmostEqual(value, 326.85)
        self.assertEqual(status, "possible_decomposition_or_dehydration")
        self.assertEqual(checked_tammann_c(None), (None, "missing"))
        value, status = checked_tammann_c(626.85)
        self.assertEqual(status, "ok")
        self.assertAlmostEqual(value, 326.85)


if __name__ == "__main__":
    unittest.main()

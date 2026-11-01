"""Synthetic tests for the label-free precursor lookup."""

import tempfile
import unittest
from pathlib import Path

from kiln.tools.precursors import PrecursorProps, props


class PrecursorTests(unittest.TestCase):
    def test_project_table_has_plain_utf8_and_sourced_decomposition_values(self):
        import csv
        path = Path(__file__).resolve().parents[2] / "data" / "precursor_props.csv"
        self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames[0], "formula")
            rows = list(reader)
        self.assertEqual(len(rows), 46)
        for row in rows:
            if row["decomposes_at_c"].strip().lower() != "unknown":
                self.assertTrue(row["decomposition_source"].strip().startswith("https://"))
                self.assertNotEqual(row["decomposition_product"].strip().lower(), "unknown")

    def table(self, text):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "properties.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def test_unknown_and_sourced_values(self):
        path = self.table("formula,decomposes_at_c,decomposition_product,volatile_above_c,source\n"
                          "Example,400,Product,unknown,https://example.org/source\n")
        self.assertEqual(props("Example", path=path),
                         PrecursorProps("Example", 400.0, "Product", None, "https://example.org/source"))
        self.assertEqual(props("Missing", path=path), PrecursorProps("Missing"))

    def test_unsourced_value_and_duplicate_are_rejected(self):
        header = "formula,decomposes_at_c,decomposition_product,volatile_above_c,source\n"
        for rows in ("Example,400,unknown,unknown,unknown\n",
                     "Example,unknown,unknown,unknown,unknown\n" * 2):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                props("Example", path=self.table(header + rows))

    def test_invalid_temperature_and_missing_file_are_errors(self):
        path = self.table("formula,decomposes_at_c,decomposition_product,volatile_above_c,source\n"
                          "Example,nan,unknown,unknown,https://example.org\n")
        with self.assertRaises(ValueError):
            props("Example", path=path)
        with self.assertRaises(FileNotFoundError):
            props("Example", path=path.parent / "missing.csv")


if __name__ == "__main__":
    unittest.main()

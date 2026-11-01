"""Guards for the draft evaluation protocol: it must stay an unfrozen draft until owners close every OPEN item."""
import re
import unittest
from pathlib import Path

PROTOCOL = Path(__file__).resolve().parents[2] / "protocol" / "protocol.md"
AMENDMENTS = PROTOCOL.with_name("amendments.md")


def _register(text: str) -> set[str]:
    section = text.split("## 15. OPEN register", 1)[1].split("## 16.", 1)[0]
    return set(re.findall(r"^\| (OPEN-\d{2}) \|", section, flags=re.MULTILINE))


class ProtocolDraftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = PROTOCOL.read_text(encoding="utf-8")

    def test_marked_as_unfrozen_draft(self) -> None:
        self.assertIn("**Status: Gate P commit.** This file is frozen at the Gate P commit", self.text)
        self.assertIn("**Never edited after the Gate P commit** (§10, P5)", self.text)
        self.assertNotRegex(self.text, r"(?i)status:\s*(frozen|final|locked|ready)")
        self.assertNotRegex(self.text, r"(?i)protocol (is|has been) (frozen|ready|hashed|posted)")

    def test_no_sha256_digest_committed(self) -> None:
        self.assertNotRegex(self.text, r"\b[0-9a-fA-F]{64}\b")

    def test_every_open_reference_is_registered(self) -> None:
        register = _register(self.text)
        referenced = set(re.findall(r"OPEN-\d{2}", self.text))
        self.assertEqual(referenced, register)
        numbers = sorted(int(open_id[5:]) for open_id in register)
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_required_sections_present(self) -> None:
        for heading in (
            "## 2. Data", "## 3. Outcomes", "## 4. Conditions", "## 5. Locked budget and frozen price list",
            "## 7. Metrics", "## 8. Statistical comparison", "## 9. Compute allocation",
            "## 10. Two-step protocol and hash gates", "## 11. Contamination control", "## 12. Label safety",
            "## 13. Limitations", "## 14. Gate 0 decisions", "## 15. OPEN register",
        ):
            self.assertIn(heading, self.text)

    def test_confirmed_aggregate_counts(self) -> None:
        for fact in (
            "| Distinct unordered pairs | 1,035", "| Distinct precursors | 46 |", "| Development pairs | 666 |",
            "| Held-out pairs | 369 |", "| Records missing a heating temperature | 54",
        ):
            self.assertIn(fact, self.text)

    def test_gate_p_pins_a_commit_and_keeps_amendments_outside(self) -> None:
        p3 = next(line for line in self.text.splitlines() if line.startswith("- **P3.**"))
        self.assertIn("git cat-file blob <gate-p-commit>:protocol/protocol.md", p3)
        self.assertIn("full Gate P commit SHA **together with** the digest", p3)
        self.assertNotRegex(self.text, r"recorded in §16")
        self.assertIn("`protocol/protocol.md` is never edited", self.text)
        amendments = AMENDMENTS.read_text(encoding="utf-8")
        self.assertIn("This file is **not** part of the Gate P hash.", amendments)
        self.assertIn("Gate P happened on 2026-11-01.", amendments)
        self.assertNotRegex(amendments, r"\b[0-9a-fA-F]{40,64}\b")

    def test_decisions_left_open(self) -> None:
        for open_id, topic in (
            ("OPEN-03", "Frozen price per compute tier"), ("OPEN-02", "Locked per-item budget"),
            ("OPEN-05", "Scoring rules"), ("OPEN-12", "`unclassified`"), ("OPEN-15", "overlapping precursor clusters"),
            ("OPEN-16", "receipt proof"), ("OPEN-13", "54 records"),
        ):
            row = next(line for line in self.text.splitlines() if line.startswith(f"| {open_id} |"))
            self.assertIn(topic, row)


if __name__ == "__main__":
    unittest.main()

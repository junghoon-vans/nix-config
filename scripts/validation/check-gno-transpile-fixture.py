#!/usr/bin/env python3
"""Check the upstream fixture's diagnostic matching against compiler output."""

from pathlib import Path
import re
import shlex
import sys
import unittest


FIXTURE = Path(sys.argv.pop(1))
PATTERNS = [
    re.compile(shlex.split(line)[1])
    for line in FIXTURE.read_text().splitlines()
    if line.startswith("stderr ")
][:2]


class TranspileDiagnostics(unittest.TestCase):
    def test_compiler_path_forms(self):
        self.assertEqual(len(PATTERNS), 2)
        for pattern, row in zip(PATTERNS, (4, 5)):
            for prefix in ("", "./"):
                with self.subTest(row=row, prefix=prefix):
                    self.assertIsNotNone(pattern.search(
                        f"{prefix}main.gno:{row}:6: declared and not used: x"
                    ))

    def test_other_diagnostics_remain_rejected(self):
        for pattern, row in zip(PATTERNS, (4, 5)):
            for diagnostic in (
                f"other.gno:{row}:6: declared and not used: x",
                f"mainXgno:{row}:6: declared and not used: x",
                f"sub/main.gno:{row}:6: declared and not used: x",
                f"main.gno:{row + 1}:6: declared and not used: x",
                f"main.gno:{row}:7: declared and not used: x",
                f"main.gno:{row}:6: undefined: x",
            ):
                with self.subTest(row=row, diagnostic=diagnostic):
                    self.assertIsNone(pattern.search(diagnostic))


if __name__ == "__main__":
    unittest.main()

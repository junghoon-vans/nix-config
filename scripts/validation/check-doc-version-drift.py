#!/usr/bin/env python3

import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
version_pattern = re.compile(r"(?<![A-Za-z0-9_])v?\d+\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9.-]+)?")
violations = []

for document in (root / "docs").rglob("*.md"):
    for line_number, line in enumerate(document.read_text().splitlines(), start=1):
        if match := version_pattern.search(line):
            violations.append(
                f"{document.relative_to(root)}:{line_number} duplicates version {match.group(0)}"
            )

if violations:
    raise SystemExit("\n".join(violations))

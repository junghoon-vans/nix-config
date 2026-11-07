#!/usr/bin/env python3
"""Report independent updater outcomes without turning failures into success."""

import json
import os
from pathlib import Path
import sys


def main():
    results = json.loads(os.environ["UPDATER_RESULTS"])
    lines = ["## Dependency updater results", "", "| Updater | Result |", "| --- | --- |"]
    failed = not results
    for name, job in results.items():
        result = job["result"]
        lines.append(f"| {name} | {result} |")
        failed |= result != "success"
    lines.extend(["", "Updaters run independently. A failed aggregate does not mean every updater failed."])
    report = "\n".join(lines) + "\n"
    print(report, end="")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a") as stream:
            stream.write(report)
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())

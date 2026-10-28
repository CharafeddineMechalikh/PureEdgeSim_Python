"""Turn a Cobertura XML report into the shields.io badge the README displays.

CI runs this after pytest and commits the JSON it writes, so the badge in the
README moves with the coverage of the tested commit instead of being a number
someone has to edit by hand.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

# The shields colour scale, from the top of the range down.
THRESHOLDS = ((95, "brightgreen"), (85, "green"), (75, "yellowgreen"), (60, "yellow"), (40, "orange"),
              (0, "red"))


def percentage(report: ElementTree.Element) -> float:
    """The line-rate of the whole report, as a percentage."""
    rate = report.get("line-rate")
    if rate is None:
        raise ValueError("the coverage report has no line-rate attribute")
    return round(float(rate) * 100, 2)


def badge(value: float) -> dict:
    """The shields endpoint document for one percentage."""
    color = next(color for threshold, color in THRESHOLDS if value >= threshold)
    return {"schemaVersion": 1, "label": "coverage", "message": f"{value:g}%", "color": color,
            "name": "coverage", "value": f"{value:g}%"}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} coverage.xml badge.json", file=sys.stderr)
        return 2
    report = ElementTree.parse(Path(argv[1])).getroot()
    value = percentage(report)
    Path(argv[2]).parent.mkdir(parents=True, exist_ok=True)
    Path(argv[2]).write_text(json.dumps(badge(value), indent=2) + "\n", encoding="utf-8")
    print(f"coverage {value:g} % written to {argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

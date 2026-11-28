"""Static architecture evidence for the MeetingConverter owner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tools.anti_trick_gate_spec.evidence import (
    baseline,
    changed_inventory,
    compare,
    renamed_waivers,
)
from tools.anti_trick_gate_spec.static_scan import scan

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests/contract/ratchet_baseline.json"


def inspect():
    paths = sorted(path.name for path in ROOT.glob("*.py"))
    return scan(ROOT, [*paths, "core", "engines"], storage=["core/output.py"], entry=["feedback_owner.py"])


def recorded(result):
    return {**baseline(result.findings), "source_files": list(result.files),
            "constant_shapes": result.constant_shapes}


def regressions(result):
    before = json.loads(BASELINE.read_bytes())
    after = recorded(result)
    return (
        compare(after, before) + renamed_waivers(after, before),
        changed_inventory(result, before, ROOT),
    )


if __name__ == "__main__":
    if sys.argv[1:] != ["baseline"]:
        raise SystemExit("usage: python -m tools.meeting_quality baseline")
    print(json.dumps(recorded(inspect()), indent=2, sort_keys=True))

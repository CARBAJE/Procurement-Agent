"""Contract test — pins the wire shape sent to SAP and Oracle.

Builds a canonical NormalizedPO from snapshots/canonical_po.json, runs it
through the vendor mapper, and asserts byte-equal JSON against the pinned
snapshot. A failing diff here means the vendor request shape has drifted —
update the snapshot intentionally, never silently.

Run with:  PYTHONIOENCODING=utf-8 python services/erp-adapter/tests/test_contracts.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent.parent.parent
SNAP = HERE / "snapshots"

sys.path.insert(0, str(REPO / "services" / "erp-adapter" / "src"))

from adapters.sap import map_to_sap_purchase_order
from adapters.oracle import map_to_oracle_purchase_order
from models import NormalizedPO


def _green(s): return f"\033[32m{s}\033[0m"
def _red(s):   return f"\033[31m{s}\033[0m"


def _diff_lines(left: dict, right: dict) -> str:
    import difflib
    lhs = json.dumps(left, indent=2, sort_keys=True).splitlines()
    rhs = json.dumps(right, indent=2, sort_keys=True).splitlines()
    return "\n".join(difflib.unified_diff(lhs, rhs, "snapshot", "actual", lineterm=""))


def main() -> int:
    canonical = json.loads((SNAP / "canonical_po.json").read_text())
    po = NormalizedPO.model_validate(canonical)

    failures: list[str] = []

    actual_sap = map_to_sap_purchase_order(po)
    expected_sap = json.loads((SNAP / "sap_po_request.json").read_text())
    if actual_sap != expected_sap:
        failures.append("SAP wire shape drift:\n" + _diff_lines(expected_sap, actual_sap))
    else:
        print(_green("SAP   contract OK"))

    actual_oracle = map_to_oracle_purchase_order(po)
    expected_oracle = json.loads((SNAP / "oracle_po_request.json").read_text())
    if actual_oracle != expected_oracle:
        failures.append("Oracle wire shape drift:\n" + _diff_lines(expected_oracle, actual_oracle))
    else:
        print(_green("Oracle contract OK"))

    if failures:
        for f in failures:
            print(_red(f))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

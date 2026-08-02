"""Ensure every discovered environment runtime read has an explicit class."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "governance" / "data_center_architecture_inventory.json"
MANIFEST = ROOT / "governance" / "runtime_config_contracts.json"


def main() -> int:
    """Validate runtime-reference coverage against classification patterns."""

    try:
        inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"runtime config coverage manifest unreadable: {exc}") from exc
    references = inventory.get("runtime_parameter_references")
    rules = manifest.get("runtime_reference_classification")
    if not isinstance(references, list) or not isinstance(rules, list) or not rules:
        raise SystemExit("runtime config coverage requires references and classification rules")
    compiled: list[tuple[re.Pattern[str], str]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise SystemExit("runtime reference classification must contain objects")
        pattern = str(rule.get("pattern") or "")
        classification = str(rule.get("classification") or "").strip()
        owner = str(rule.get("owner") or "").strip()
        if not pattern or not classification or not owner:
            raise SystemExit(
                "runtime reference classification requires pattern/classification/owner"
            )
        try:
            compiled.append((re.compile(pattern), classification))
        except re.error as exc:
            raise SystemExit(f"invalid runtime classification regex {pattern!r}: {exc}") from exc
    uncovered = [
        str(reference)
        for reference in references
        if not any(regex.search(str(reference)) for regex, _classification in compiled)
    ]
    if uncovered:
        raise SystemExit("unclassified runtime parameter references: " + "; ".join(uncovered))
    print(
        "Runtime config references classified: "
        f"{len(references)} ({sorted({classification for _, classification in compiled})})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

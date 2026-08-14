"""Evaluate the local AI-Native release gate without claiming staging approval."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/ai_native/ai_native_release_gate.v1.json"


@dataclass(frozen=True)
class GateCheck:
    key: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class AiNativeReleaseGateResult:
    gate_id: str
    schema_version: int
    decision: str
    checks: tuple[GateCheck, ...]
    reasons: tuple[str, ...]


def _read_json(path: Path) -> Mapping[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _as_string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return ()
    return tuple(value)


def _check_assets(
    config: Mapping[str, object],
    repo_root: Path,
) -> tuple[GateCheck, ...]:
    raw_assets = config.get("required_assets")
    if not isinstance(raw_assets, list):
        return (GateCheck("asset_manifest", False, "required_assets must be a list"),)

    checks: list[GateCheck] = []
    for raw_asset in raw_assets:
        if not isinstance(raw_asset, Mapping):
            checks.append(GateCheck("asset_manifest", False, "asset entry is not an object"))
            continue
        asset_id = raw_asset.get("id")
        paths = _as_string_list(raw_asset.get("paths"))
        markers = _as_string_list(raw_asset.get("markers"))
        if not isinstance(asset_id, str) or not paths:
            checks.append(GateCheck("asset_manifest", False, "asset id/paths are invalid"))
            continue
        missing = [path for path in paths if not (repo_root / path).is_file()]
        marker_failures: list[str] = []
        group_text: list[str] = []
        for path in paths:
            candidate = repo_root / path
            if not candidate.is_file():
                continue
            try:
                text = candidate.read_text(encoding="utf-8")
            except OSError:
                marker_failures.append(f"{path}: unreadable")
                continue
            group_text.append(text)
        combined_text = "\n".join(group_text)
        absent = [marker for marker in markers if marker not in combined_text]
        if absent:
            marker_failures.append(f"asset group: missing {','.join(absent)}")
        passed = not missing and not marker_failures
        detail = "all files and markers present"
        if missing:
            detail = f"missing={','.join(missing)}"
        if marker_failures:
            detail = f"{detail}; {'; '.join(marker_failures)}"
        checks.append(GateCheck(asset_id, passed, detail))
    return tuple(checks)


def _check_required_tests(config: Mapping[str, object], repo_root: Path) -> GateCheck:
    paths = _as_string_list(config.get("required_tests"))
    missing = [path for path in paths if not (repo_root / path).is_file()]
    return GateCheck(
        "required_test_assets",
        bool(paths) and not missing,
        "all registered tests present" if not missing and paths else f"missing={','.join(missing)}",
    )


def _check_evidence(
    path: Path | None,
    requirement: Mapping[str, object],
    key: str,
) -> tuple[GateCheck, Mapping[str, object] | None]:
    if path is None:
        return GateCheck(key, False, "evidence path not supplied"), None
    payload = _read_json(path)
    required_fields = _as_string_list(requirement.get("required_fields"))
    if payload is None:
        return GateCheck(key, False, "evidence must be a JSON object"), None
    missing = [field for field in required_fields if field not in payload]
    expected = {
        field: requirement[field] for field in ("environment", "status") if field in requirement
    }
    mismatches = [field for field, value in expected.items() if payload.get(field) != value]
    passed = not missing and not mismatches
    detail = (
        "evidence schema accepted"
        if passed
        else f"missing={','.join(missing)}; mismatched={','.join(mismatches)}"
    )
    return GateCheck(key, passed, detail), payload


def evaluate_release_gate(
    *,
    config_path: Path = DEFAULT_CONFIG,
    repo_root: Path = ROOT,
    staging_evidence: Path | None = None,
    manual_signoff: Path | None = None,
) -> AiNativeReleaseGateResult:
    config = _read_json(config_path)
    if config is None:
        return AiNativeReleaseGateResult(
            gate_id="ai-native-release-gate.v1",
            schema_version=1,
            decision="DENY",
            checks=(GateCheck("config", False, "gate config is unreadable or invalid"),),
            reasons=("gate_config_invalid",),
        )
    gate_id = config.get("gate_id")
    schema_version = config.get("schema_version")
    checks: list[GateCheck] = []
    if not isinstance(gate_id, str) or not isinstance(schema_version, int) or schema_version != 1:
        checks.append(GateCheck("config_schema", False, "gate_id/schema_version invalid"))
        gate_id = "ai-native-release-gate.v1"
        schema_version = 1
    else:
        checks.append(GateCheck("config_schema", True, "schema version 1"))
    checks.extend(_check_assets(config, repo_root))
    checks.append(_check_required_tests(config, repo_root))
    evidence = config.get("evidence_requirements")
    if not isinstance(evidence, Mapping):
        checks.append(GateCheck("evidence_schema", False, "evidence_requirements is invalid"))
        staging_payload = manual_payload = None
    else:
        staging_requirement = evidence.get("staging")
        signoff_requirement = evidence.get("manual_signoff")
        if not isinstance(staging_requirement, Mapping) or not isinstance(
            signoff_requirement, Mapping
        ):
            checks.append(
                GateCheck("evidence_schema", False, "staging/manual requirements are invalid")
            )
            staging_payload = manual_payload = None
        else:
            staging_check, staging_payload = _check_evidence(
                staging_evidence, staging_requirement, "staging_evidence"
            )
            signoff_check, manual_payload = _check_evidence(
                manual_signoff, signoff_requirement, "manual_signoff"
            )
            checks.extend((staging_check, signoff_check))
            if staging_payload is not None and manual_payload is not None:
                candidate_match = staging_payload.get("candidate_commit") == manual_payload.get(
                    "candidate_commit"
                )
                checks.append(
                    GateCheck(
                        "candidate_binding",
                        candidate_match,
                        (
                            "candidate commit matches"
                            if candidate_match
                            else "candidate commit differs"
                        ),
                    )
                )
    reasons = tuple(check.key for check in checks if not check.passed)
    decision = "ALLOW" if not reasons else "DENY"
    return AiNativeReleaseGateResult(
        gate_id=str(gate_id),
        schema_version=int(schema_version),
        decision=decision,
        checks=tuple(checks),
        reasons=reasons,
    )


def main() -> int:
    """Run the AI-Native release gate."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--staging-evidence", type=Path)
    parser.add_argument("--manual-signoff", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-allow", action="store_true")
    args = parser.parse_args()
    result = evaluate_release_gate(
        config_path=args.config.resolve(),
        repo_root=ROOT,
        staging_evidence=args.staging_evidence.resolve() if args.staging_evidence else None,
        manual_signoff=args.manual_signoff.resolve() if args.manual_signoff else None,
    )
    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print(f"AI-Native release gate: {result.decision}")
        for check in result.checks:
            print(f"[{'PASS' if check.passed else 'FAIL'}] {check.key}: {check.detail}")
    return 1 if args.require_allow and result.decision != "ALLOW" else 0


if __name__ == "__main__":
    raise SystemExit(main())

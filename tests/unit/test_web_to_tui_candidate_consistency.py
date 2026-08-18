"""Static candidate identity consistency for the Web-to-TUI evidence set."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "governance" / "active_plan_registry.json"
READINESS_PATH = ROOT / "docs" / "plans" / "web-to-tui-m5-readiness-2026-07-27.md"
DEPLOYMENT_PATH = ROOT / "docs" / "deployment" / "vps-deployment-evidence-2026-08-15.md"
PREFLIGHT_DIR = ROOT / "docs" / "deployment"
CUTOVER_PATH = ROOT / "config" / "tui" / "migration" / "web_to_tui_cutover_evidence.v1.json"


def _latest_section_for_candidate(
    text: str,
    *,
    heading_level: int,
    marker: str,
    required_values: Iterable[str],
) -> str:
    """Return the newest evidence section that names the bound candidate.

    Deployment evidence also records newer, unrelated TAR/runtime observations.
    Those sections must not silently replace the Web-to-TUI cutover candidate;
    selecting by the immutable commit keeps this guard scoped to its evidence
    set while still preferring the newest matching observation.
    """

    required = tuple(required_values)
    heading = re.compile(
        rf"^{'#' * heading_level} "
        rf"(?P<timestamp>\d{{4}}-\d{{2}}-\d{{2}}(?: \d{{2}}:\d{{2}})?) "
        rf".*{re.escape(marker)}.*$",
        re.MULTILINE,
    )
    sections: list[tuple[str, str]] = []
    for match in heading.finditer(text):
        following_heading = re.search(r"^#{1,6} .*$", text[match.end() :], re.MULTILINE)
        end = match.end() + following_heading.start() if following_heading else len(text)
        section = text[match.start() : end]
        if all(value in section for value in required):
            sections.append((match.group("timestamp"), section))
    assert sections, f"missing candidate section containing {required!r}"
    return max(sections, key=lambda item: item[0])[1]


def _find_candidate_preflight(*, candidate_version: str, candidate_commit: str) -> Path:
    """Find exactly one committed deployment preflight for the current candidate."""

    matches: list[Path] = []
    for path in sorted(PREFLIGHT_DIR.glob("web-to-tui-deployment-preflight-*.json")):
        payload = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        release = cast(dict[str, Any], payload.get("release", {}))
        if (
            str(release.get("stable_version")) == candidate_version
            and str(release.get("source_commit")) == candidate_commit
        ):
            matches.append(path)
    assert len(matches) == 1, f"expected one preflight for current candidate, got {matches}"
    return matches[0]


def test_current_candidate_identity_is_consistent_across_registry_and_evidence() -> None:
    """Keep the immutable cutover candidate aligned across its evidence files."""

    registry = cast(dict[str, Any], json.loads(REGISTRY_PATH.read_text(encoding="utf-8")))
    workstream = next(item for item in registry["workstreams"] if item["id"] == "web-to-tui-m5")
    next_gate = str(workstream["next_gate"])

    cutover = cast(dict[str, Any], json.loads(CUTOVER_PATH.read_text(encoding="utf-8")))
    cutover_candidate = cast(dict[str, Any], cutover["candidate"])
    candidate_version = str(cutover_candidate["stable_version"])
    candidate_commit = str(cutover_candidate["candidate_commit"])
    binding_payload = cutover_candidate.get("binding")
    assert isinstance(binding_payload, dict)
    binding = {str(key): str(value) for key, value in binding_payload.items()}
    assert binding["candidate_version"] == candidate_version
    assert binding["candidate_commit"] == candidate_commit
    assert candidate_commit in next_gate
    assert candidate_version in next_gate

    preflight_path = _find_candidate_preflight(
        candidate_version=candidate_version,
        candidate_commit=candidate_commit,
    )
    preflight = cast(dict[str, Any], json.loads(preflight_path.read_text(encoding="utf-8")))
    release = cast(dict[str, Any], preflight["release"])
    assert str(release["stable_version"]) == candidate_version
    assert str(release["source_commit"]) == candidate_commit
    assert str(preflight["oci_image"]["revision"]) == candidate_commit

    readiness = READINESS_PATH.read_text(encoding="utf-8")
    deployment = DEPLOYMENT_PATH.read_text(encoding="utf-8")
    readiness_current = _latest_section_for_candidate(
        readiness,
        heading_level=3,
        marker="当前候选部署复核",
        required_values=(candidate_commit, candidate_version, *binding.values()),
    )
    deployment_current = _latest_section_for_candidate(
        deployment,
        heading_level=2,
        marker="当前候选部署与观测",
        required_values=(candidate_commit, candidate_version, *binding.values()),
    )
    assert candidate_commit in readiness_current
    assert candidate_version in readiness_current
    assert candidate_commit in deployment_current
    assert candidate_version in deployment_current

    assert cutover_candidate["candidate_commit"] == candidate_commit
    assert cutover_candidate["stable_version"] == candidate_version
    assert cutover_candidate["deployment_preflight"]["source_commit"] == candidate_commit
    assert cutover_candidate["deployment_preflight"]["release_id"] == release["release_id"]
    assert (
        cutover_candidate["deployment_preflight"]["evidence"]
        == preflight_path.relative_to(ROOT).as_posix()
    )
    for value in binding.values():
        assert f"`{value}`" in readiness_current or value in readiness_current
        assert f"`{value}`" in deployment_current or value in deployment_current

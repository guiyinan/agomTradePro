#!/usr/bin/env python3
"""Build an immutable candidate-bound release rehearsal evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import cast

REQUIRED_SCHEMAS = {
    "real_response_unit_replay": "release.real-response-unit-replay.v1",
    "full_universe_capacity": "release.full-universe-capacity.v2",
    "isolated_write_rehearsal": "release.isolated-write-rehearsal.v1",
    "candidate_regression_evidence": "release.candidate-regression-evidence.v1",
}
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
MAX_BUNDLE_BYTES = 64 * 1024 * 1024


def _read(path: Path, limit: int = MAX_BUNDLE_BYTES) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("REHEARSAL_BUNDLE_ARTIFACT_INVALID")
    raw = path.read_bytes()
    if not raw or len(raw) > limit:
        raise ValueError("REHEARSAL_BUNDLE_ARTIFACT_INVALID")
    return raw


def _json(path: Path) -> dict[str, object]:
    try:
        value: object = json.loads(_read(path))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("REHEARSAL_BUNDLE_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise ValueError("REHEARSAL_BUNDLE_JSON_INVALID")
    return cast(dict[str, object], value)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _artifact_refs(value: object) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    if isinstance(value, dict):
        path = value.get("path")
        digest = value.get("sha256")
        if isinstance(path, str) and isinstance(digest, str):
            refs.append((path, digest))
        for child in value.values():
            refs.extend(_artifact_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_artifact_refs(child))
    return refs


def _resolve(base: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if (
        not relative
        or "\\" in relative
        or relative_path.is_absolute()
        or relative_path.drive
        or ".." in relative_path.parts
    ):
        raise ValueError("REHEARSAL_BUNDLE_PATH_INVALID")
    unresolved = base
    for part in relative_path.parts:
        unresolved /= part
        if unresolved.is_symlink():
            raise ValueError("REHEARSAL_BUNDLE_ARTIFACT_INVALID")
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError("REHEARSAL_BUNDLE_PATH_INVALID") from exc
    return candidate


def _copy_graph(report_path: Path, destination: Path) -> tuple[str, int]:
    source_root = report_path.resolve().parent
    queue = [report_path.resolve()]
    copied: dict[str, str] = {}
    total = 0
    while queue:
        source = queue.pop(0)
        relative = source.relative_to(source_root).as_posix()
        raw = _read(source)
        digest = _digest(raw)
        if relative in copied:
            if copied[relative] != digest:
                raise ValueError("REHEARSAL_BUNDLE_ARTIFACT_COLLISION")
            continue
        copied[relative] = digest
        total += len(raw)
        if total > MAX_BUNDLE_BYTES:
            raise ValueError("REHEARSAL_BUNDLE_SIZE_LIMIT")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            payload: object = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            continue
        for child_path, expected_digest in _artifact_refs(payload):
            if SHA256_RE.fullmatch(expected_digest) is None:
                raise ValueError("REHEARSAL_BUNDLE_DIGEST_INVALID")
            child = _resolve(source.parent, child_path)
            child_raw = _read(child)
            if _digest(child_raw) != expected_digest:
                raise ValueError("REHEARSAL_BUNDLE_DIGEST_MISMATCH")
            queue.append(child)
    return _digest(_read(report_path)), total


def build_manifest(
    *,
    reports: dict[str, Path],
    output_dir: Path,
    candidate_sha: str,
    target_trade_date: str,
    universe_sha256: str,
    provider_identities_sha256: str,
    candidate_image_id: str,
) -> Path:
    """Copy each hash-linked report graph and create one exclusive manifest."""
    if output_dir.exists():
        raise ValueError("REHEARSAL_BUNDLE_OUTPUT_EXISTS")
    if (
        COMMIT_RE.fullmatch(candidate_sha) is None
        or SHA256_RE.fullmatch(universe_sha256) is None
        or SHA256_RE.fullmatch(provider_identities_sha256) is None
        or IMAGE_ID_RE.fullmatch(candidate_image_id) is None
        or set(reports) != set(REQUIRED_SCHEMAS)
    ):
        raise ValueError("REHEARSAL_BUNDLE_IDENTITY_INVALID")
    loaded = {kind: _json(path) for kind, path in reports.items()}
    for kind, payload in loaded.items():
        if (
            payload.get("schema") != REQUIRED_SCHEMAS[kind]
            or payload.get("kind") != kind
            or payload.get("outcome") != "success"
            or payload.get("candidate_sha") != candidate_sha
            or payload.get("target_trade_date") != target_trade_date
            or payload.get("universe_sha256") != universe_sha256
            or payload.get("provider_identities_sha256") != provider_identities_sha256
            or (
                kind != "candidate_regression_evidence"
                and payload.get("candidate_image_id") != candidate_image_id
            )
        ):
            raise ValueError("REHEARSAL_BUNDLE_REPORT_MISMATCH")
    output_dir.mkdir(parents=True, exist_ok=False)
    references: list[dict[str, str]] = []
    total = 0
    try:
        for kind in REQUIRED_SCHEMAS:
            report_path = reports[kind]
            kind_dir = output_dir / kind
            kind_dir.mkdir()
            digest, copied_bytes = _copy_graph(report_path, kind_dir)
            total += copied_bytes
            if total > MAX_BUNDLE_BYTES:
                raise ValueError("REHEARSAL_BUNDLE_SIZE_LIMIT")
            references.append(
                {
                    "kind": kind,
                    "path": f"{kind}/{report_path.name}",
                    "sha256": digest,
                }
            )
        manifest = {
            "schema": "release.rehearsal-manifest.v1",
            "candidate_sha": candidate_sha,
            "target_trade_date": target_trade_date,
            "universe_sha256": universe_sha256,
            "provider_identities_sha256": provider_identities_sha256,
            "candidate_image_id": candidate_image_id,
            "reports": references,
        }
        path = output_dir / "release-rehearsal-manifest.json"
        raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return path
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def main() -> int:
    """Build one immutable bundle from the four producer reports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-response-unit-replay", required=True, type=Path)
    parser.add_argument("--full-universe-capacity", required=True, type=Path)
    parser.add_argument("--isolated-write-rehearsal", required=True, type=Path)
    parser.add_argument("--candidate-regression-evidence", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--target-trade-date", required=True)
    parser.add_argument("--universe-sha256", required=True)
    parser.add_argument("--provider-identities-sha256", required=True)
    parser.add_argument("--candidate-image-id", required=True)
    args = parser.parse_args()
    path = build_manifest(
        reports={kind: getattr(args, kind) for kind in REQUIRED_SCHEMAS},
        output_dir=args.output_dir,
        candidate_sha=args.candidate_sha,
        target_trade_date=args.target_trade_date,
        universe_sha256=args.universe_sha256,
        provider_identities_sha256=args.provider_identities_sha256,
        candidate_image_id=args.candidate_image_id,
    )
    print(json.dumps({"outcome": "success", "manifest": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

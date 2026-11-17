"""Require an explicit, pinned, rollback-safe legacy bootstrap deployment mode."""

from __future__ import annotations

import re
from pathlib import PurePosixPath


def validate_observed_rollback_deploy_options(
    *,
    baseline_path: str,
    baseline_sha256: str,
    compatibility_report_path: str,
    compatibility_report_sha256: str,
    prebuilt: bool,
    action: str,
    skip_backup: bool,
    auto_rollback: bool,
    preserve_catalog: bool,
    wipe_docker: bool,
    wipe_volumes: bool,
    include_sqlite: bool,
    bootstrap_decision_repair: bool,
    bootstrap_alpha: bool = False,
    enable_celery: bool = True,
) -> bool:
    """Select recovery only with both pinned proofs and safe prebuilt-only options.

    This validates command-line intent, not the proof contents or permission to
    deploy. The remote preflight must independently verify the exact live
    baseline, native compatibility report, backup and rehearsed candidate.
    """

    inputs = (
        baseline_path,
        baseline_sha256,
        compatibility_report_path,
        compatibility_report_sha256,
    )
    if not any(inputs):
        return False
    if not all(type(value) is str and value for value in inputs):
        raise ValueError("OBSERVED_RUNTIME_RECOVERY_INPUTS_INCOMPLETE")
    for value in (baseline_path, compatibility_report_path):
        path = PurePosixPath(value)
        if (
            not path.is_absolute()
            or ".." in path.parts
            or path.suffix != ".json"
            or any(character in value for character in "\r\n\0\\")
        ):
            raise ValueError("OBSERVED_RUNTIME_RECOVERY_PATH_INVALID")
    if any(
        re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in (baseline_sha256, compatibility_report_sha256)
    ):
        raise ValueError("OBSERVED_RUNTIME_RECOVERY_DIGEST_INVALID")
    if (
        not prebuilt
        or action != "upgrade"
        or skip_backup
        or not auto_rollback
        or not preserve_catalog
        or wipe_docker
        or wipe_volumes
        or include_sqlite
        or bootstrap_decision_repair
        or bootstrap_alpha
        or not enable_celery
    ):
        raise ValueError("OBSERVED_RUNTIME_RECOVERY_OPTIONS_UNSAFE")
    return True

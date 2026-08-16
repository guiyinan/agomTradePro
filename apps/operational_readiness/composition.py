"""Composition root for operational-readiness adapters and use cases."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings

from apps.operational_readiness.application.release_identity import GetReleaseIdentityUseCase
from apps.operational_readiness.infrastructure.release_identity_reader import (
    FileReleaseIdentityEvidenceReader,
)
from core.version import get_version


def make_get_release_identity_use_case() -> GetReleaseIdentityUseCase:
    """Build the current deployment identity query with filesystem adapters."""

    reader = FileReleaseIdentityEvidenceReader(
        build_identity_path=Path(settings.AGOM_BUILD_IDENTITY_PATH),
        release_manifest_path=Path(settings.AGOM_RELEASE_MANIFEST_PATH),
    )
    return GetReleaseIdentityUseCase(reader, app_version=get_version())


__all__ = ["make_get_release_identity_use_case"]

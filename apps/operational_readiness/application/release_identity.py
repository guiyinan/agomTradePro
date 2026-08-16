"""Application contract for reading the current deployment identity."""

from __future__ import annotations

from typing import Protocol, TypedDict

from apps.operational_readiness.domain.release_identity import (
    ReleaseIdentityEvidence,
    verify_release_identity,
)


class ReleaseIdentityPayload(TypedDict):
    """Stable administrator-facing release identity response."""

    status: str
    status_label: str
    app_version: str
    release_tag: str | None
    source_commit: str | None
    short_commit: str | None
    image_tag: str | None
    image_id: str | None
    build_started_at: str | None
    build_finished_at: str | None
    source_mode: str | None
    runtime_match: bool | None
    must_not_trust_for_release: bool
    blocked_reason: str | None


class ReleaseIdentityEvidenceReader(Protocol):
    """Port for obtaining build-time and deploy-time identity evidence."""

    def read(self) -> ReleaseIdentityEvidence:
        """Return normalized evidence without raising for bad artifacts."""


class GetReleaseIdentityUseCase:
    """Verify and serialize the identity of the current application process."""

    def __init__(
        self,
        reader: ReleaseIdentityEvidenceReader,
        *,
        app_version: str,
    ) -> None:
        self._reader = reader
        self._app_version = app_version

    def execute(self) -> ReleaseIdentityPayload:
        """Return fail-closed deployment identity for an administrator."""

        identity = verify_release_identity(
            self._reader.read(),
            fallback_app_version=self._app_version,
        )
        return {
            "status": identity.status,
            "status_label": identity.status_label,
            "app_version": identity.app_version,
            "release_tag": identity.release_tag,
            "source_commit": identity.source_commit,
            "short_commit": identity.short_commit,
            "image_tag": identity.image_tag,
            "image_id": identity.image_id,
            "build_started_at": identity.build_started_at,
            "build_finished_at": identity.build_finished_at,
            "source_mode": identity.source_mode,
            "runtime_match": identity.runtime_match,
            "must_not_trust_for_release": identity.must_not_trust_for_release,
            "blocked_reason": identity.blocked_reason,
        }


__all__ = [
    "GetReleaseIdentityUseCase",
    "ReleaseIdentityEvidenceReader",
    "ReleaseIdentityPayload",
]

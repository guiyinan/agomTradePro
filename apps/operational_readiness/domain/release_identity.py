"""Pure release-identity evidence and verification rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ArtifactStatus = Literal["valid", "missing", "invalid"]
VerificationStatus = Literal["verified", "unavailable", "mismatch", "invalid"]


@dataclass(frozen=True)
class BuildIdentity:
    """Immutable identity embedded in one application image."""

    schema_version: int
    app_version: str
    source_commit: str


@dataclass(frozen=True)
class ReleaseManifest:
    """Immutable provenance generated for one VPS release directory."""

    schema_version: int
    release_tag: str
    source_commit: str
    image_tag: str
    image_id: str
    build_started_at: str
    build_finished_at: str
    source_mode: str


@dataclass(frozen=True)
class BuildIdentityEvidence:
    """Result of loading the image-embedded identity artifact."""

    status: ArtifactStatus
    value: BuildIdentity | None = None


@dataclass(frozen=True)
class ReleaseManifestEvidence:
    """Result of loading the mounted release manifest artifact."""

    status: ArtifactStatus
    value: ReleaseManifest | None = None


@dataclass(frozen=True)
class ReleaseIdentityEvidence:
    """Runtime evidence needed to bind a process to a VPS release."""

    build: BuildIdentityEvidence
    release: ReleaseManifestEvidence


@dataclass(frozen=True)
class VerifiedReleaseIdentity:
    """Administrator-facing release identity after fail-closed verification."""

    status: VerificationStatus
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


def verify_release_identity(
    evidence: ReleaseIdentityEvidence,
    *,
    fallback_app_version: str,
) -> VerifiedReleaseIdentity:
    """Verify image and release artifacts without inventing missing provenance."""

    build = evidence.build.value
    release = evidence.release.value
    app_version = build.app_version if build is not None else fallback_app_version
    source_commit = release.source_commit if release is not None else None
    if source_commit is None and build is not None:
        source_commit = build.source_commit

    if evidence.build.status == "invalid" or evidence.release.status == "invalid":
        return _result(
            status="invalid",
            status_label="身份凭证无效",
            app_version=app_version,
            release=release,
            source_commit=source_commit,
            runtime_match=None,
            must_not_trust_for_release=True,
            blocked_reason="部署身份凭证格式无效，无法确认当前运行版本。",
        )
    if evidence.build.status == "missing" or evidence.release.status == "missing":
        return _result(
            status="unavailable",
            status_label="无法核验",
            app_version=app_version,
            release=release,
            source_commit=source_commit,
            runtime_match=None,
            must_not_trust_for_release=True,
            blocked_reason="缺少镜像构建身份或发布清单，无法确认当前运行版本。",
        )
    if build is None or release is None:
        return _result(
            status="invalid",
            status_label="身份凭证无效",
            app_version=app_version,
            release=release,
            source_commit=source_commit,
            runtime_match=None,
            must_not_trust_for_release=True,
            blocked_reason="部署身份凭证状态与内容不一致。",
        )
    if build.source_commit != release.source_commit:
        return _result(
            status="mismatch",
            status_label="版本不匹配",
            app_version=app_version,
            release=release,
            source_commit=source_commit,
            runtime_match=False,
            must_not_trust_for_release=True,
            blocked_reason="运行镜像与发布清单对应的 Git 提交不一致。",
        )
    if build.app_version != fallback_app_version:
        return _result(
            status="mismatch",
            status_label="版本不匹配",
            app_version=app_version,
            release=release,
            source_commit=source_commit,
            runtime_match=False,
            must_not_trust_for_release=True,
            blocked_reason="运行镜像中的应用版本与当前代码版本不一致。",
        )
    return _result(
        status="verified",
        status_label="已核验",
        app_version=app_version,
        release=release,
        source_commit=source_commit,
        runtime_match=True,
        must_not_trust_for_release=False,
        blocked_reason=None,
    )


def _result(
    *,
    status: VerificationStatus,
    status_label: str,
    app_version: str,
    release: ReleaseManifest | None,
    source_commit: str | None,
    runtime_match: bool | None,
    must_not_trust_for_release: bool,
    blocked_reason: str | None,
) -> VerifiedReleaseIdentity:
    """Build one normalized verification result from optional release evidence."""

    return VerifiedReleaseIdentity(
        status=status,
        status_label=status_label,
        app_version=app_version,
        release_tag=release.release_tag if release is not None else None,
        source_commit=source_commit,
        short_commit=source_commit[:12] if source_commit is not None else None,
        image_tag=release.image_tag if release is not None else None,
        image_id=release.image_id if release is not None else None,
        build_started_at=release.build_started_at if release is not None else None,
        build_finished_at=release.build_finished_at if release is not None else None,
        source_mode=release.source_mode if release is not None else None,
        runtime_match=runtime_match,
        must_not_trust_for_release=must_not_trust_for_release,
        blocked_reason=blocked_reason,
    )


__all__ = [
    "BuildIdentity",
    "BuildIdentityEvidence",
    "ReleaseIdentityEvidence",
    "ReleaseManifest",
    "ReleaseManifestEvidence",
    "VerifiedReleaseIdentity",
    "verify_release_identity",
]

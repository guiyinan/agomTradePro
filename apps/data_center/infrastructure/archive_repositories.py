"""Archive candidate selection and byte-backed retention coverage gateway."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from django.db.models import Subquery

from apps.data_center.domain.raw_landing import RawPayload
from core.integration.config_center_runtime import evaluate_storage_pressure

from .archive_models import ArchiveMemberModel
from .models import RawPayloadModel
from .raw_archive_store import FilesystemRawArchiveStore
from .retention_repositories import ArchiveManifestRepository


class ArchiveCandidateRepository:
    """Read bounded RawPayload candidates not already registered in an archive."""

    def list_unarchived(
        self,
        dataset_key: str,
        *,
        before: datetime,
        now: datetime,
        limit: int,
    ) -> list[RawPayload]:
        """Return oldest unarchived payloads before the configured warm cutoff."""

        archived_payload_ids = ArchiveMemberModel._default_manager.filter(
            archive__state__in=("exported", "verified"),
            archive__retention_until__gt=now,
        ).values("payload_id")
        rows = (
            RawPayloadModel._default_manager.filter(
                dataset_key=dataset_key,
                fetched_at__lt=before,
            )
            .exclude(payload_id__in=Subquery(archived_payload_ids))
            .order_by("fetched_at", "payload_id")[:limit]
        )
        return [row.to_domain() for row in rows]


class ArchiveCoverageGateway:
    """Authorize deletion only when DB coverage and current cold bytes agree."""

    def __init__(
        self,
        manifests: ArchiveManifestRepository,
        store: FilesystemRawArchiveStore,
    ) -> None:
        self._manifests = manifests
        self._store = store
        self._artifact_cache: dict[str, bool] = {}

    def has_verified_for_payload(
        self,
        payload: RawPayload,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Re-read each candidate artifact at most once during a bounded pass."""

        return self.verified_archive_id_for_payload(payload, now=now) is not None

    def verified_archive_id_for_payload(
        self,
        payload: RawPayload,
        *,
        now: datetime | None = None,
        required_archive_id: str | None = None,
    ) -> str | None:
        """Return an exact byte-backed archive ID, optionally pinned to one manifest."""

        for manifest in self._manifests.find_covering_manifests(payload, now=now):
            if required_archive_id is not None and manifest.archive_id != required_archive_id:
                continue
            cached = self._artifact_cache.get(manifest.archive_id)
            if cached is None:
                try:
                    artifact = self._store.inspect(manifest.location)
                    members = self._manifests.list_members(manifest.archive_id)
                    cached = artifact.matches_manifest(manifest, members)
                except Exception:
                    cached = False
                self._artifact_cache[manifest.archive_id] = cached
            if cached:
                return manifest.archive_id
        return None


class ArchiveCapacityGuard:
    """Evaluate projected cold-store writes through Config Center policy."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()

    def can_write(self, projected_bytes: int) -> bool:
        """Return false unless the configured mount and active policy allow the write."""

        if projected_bytes < 1 or not self._root.is_dir():
            return False
        disk = shutil.disk_usage(self._root)
        pressure = evaluate_storage_pressure(
            used_bytes=int(disk.used) + projected_bytes,
            actual_capacity_bytes=int(disk.total),
        )
        return pressure.get("state") != "blocked"


__all__ = ["ArchiveCandidateRepository", "ArchiveCapacityGuard", "ArchiveCoverageGateway"]

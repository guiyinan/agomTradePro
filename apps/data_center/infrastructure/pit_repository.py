"""Django implementation of the canonical PIT data view."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from django.db.models import F, Q, QuerySet, Window
from django.db.models.functions import RowNumber

from apps.data_center.domain.pit import (
    KnowledgeScope,
    PITDatasetManifest,
    PITFactVersion,
    PITQuality,
    calculate_pit_manifest_hash,
)

from .pit_models import PITDatasetManifestModel, PITFactVersionModel


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class DjangoPITDataView:
    """Select latest fact revisions without leaking future knowledge."""

    @staticmethod
    def _eligible_queryset(
        dataset: str,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
        filters: dict[str, Any],
    ) -> tuple[QuerySet[PITFactVersionModel], str]:
        """Build the fact-version queryset visible under the requested clock."""

        knowledge_scope = KnowledgeScope(knowledge_scope)
        if as_of_time.tzinfo is None:
            raise ValueError("as_of_time must be timezone-aware")
        clock_field = "available_at" if knowledge_scope is KnowledgeScope.PUBLIC else "ingested_at"
        queryset = PITFactVersionModel._default_manager.filter(
            dataset=dataset,
            effective_at__lte=as_of_time,
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_time))
        if knowledge_scope is KnowledgeScope.PUBLIC:
            queryset = queryset.filter(available_at__isnull=False)
        queryset = queryset.filter(**{f"{clock_field}__lte": as_of_time})
        for field_name, value in filters.items():
            if field_name == "business_key":
                queryset = queryset.filter(business_key=value)
            elif field_name == "business_key__in":
                queryset = queryset.filter(business_key__in=value)
            else:
                queryset = queryset.filter(**{f"payload__{field_name}": value})
        return queryset, clock_field

    def query(
        self,
        dataset: str,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
        filters: dict[str, Any],
    ) -> list[PITFactVersion]:
        """Return one latest knowable version per business key."""

        knowledge_scope = KnowledgeScope(knowledge_scope)
        queryset, clock_field = self._eligible_queryset(
            dataset, as_of_time, knowledge_scope, filters
        )
        rows = queryset.annotate(
            pit_rank=Window(
                expression=RowNumber(),
                partition_by=[F("business_key")],
                order_by=[F(clock_field).desc(), F("revision_number").desc(), F("id").desc()],
            )
        ).filter(pit_rank=1)
        return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(row: PITFactVersionModel) -> PITFactVersion:
        return PITFactVersion(
            version_id=row.pk,
            dataset=row.dataset,
            business_key=row.business_key,
            effective_at=row.effective_at,
            effective_to=row.effective_to,
            available_at=row.available_at,
            ingested_at=row.ingested_at,
            superseded_at=row.superseded_at,
            revision_number=row.revision_number,
            source_record_id=row.source_record_id,
            content_hash=row.content_hash,
            pit_quality=PITQuality(row.pit_quality),
            payload=dict(row.payload or {}),
        )


class ManifestBoundPITDataView(DjangoPITDataView):
    """PIT reader restricted to the immutable versions frozen in one manifest."""

    def __init__(self, manifest_id: str):
        model = PITDatasetManifestModel._default_manager.filter(manifest_id=manifest_id).first()
        if model is None:
            raise ValueError("PIT manifest not found")
        manifest = PITManifestRepository._to_domain(model)
        if not manifest.is_verified:
            raise ValueError("PIT manifest is not verified")
        selected_ids = [int(item["id"]) for item in manifest.selected_versions]
        stored_rows: dict[int, Any] = {
            int(row["id"]): row
            for row in PITFactVersionModel._default_manager.filter(pk__in=selected_ids).values(
                "id", "content_hash", "payload"
            )
        }
        self._expected_hashes: dict[int, dict[str, str | None]] = {
            int(item["id"]): {
                "content_hash": item.get("content_hash"),
                "payload_hash": item.get("payload_hash"),
            }
            for item in manifest.selected_versions
        }
        if len(stored_rows) != len(selected_ids) or any(
            not expected["payload_hash"]
            or stored_rows.get(version_id, {}).get("content_hash") != expected["content_hash"]
            or _stable_hash(stored_rows.get(version_id, {}).get("payload"))
            != expected["payload_hash"]
            for version_id, expected in self._expected_hashes.items()
        ):
            raise ValueError("PIT manifest version evidence is missing or altered")
        self._manifest = manifest
        self._ids_by_dataset: dict[str, list[int]] = {}
        for item in manifest.selected_versions:
            self._ids_by_dataset.setdefault(str(item["dataset"]), []).append(int(item["id"]))

    @property
    def coverage(self) -> dict[str, float]:
        """Return a copy of the manifest coverage evidence."""

        return dict(self._manifest.coverage)

    def query(
        self,
        dataset: str,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
        filters: dict[str, Any],
    ) -> list[PITFactVersion]:
        """Select only evidence frozen in the manifest, failing on clock misuse."""

        knowledge_scope = KnowledgeScope(knowledge_scope)
        if knowledge_scope is not self._manifest.knowledge_scope:
            raise ValueError("knowledge scope differs from the PIT manifest")
        if as_of_time > self._manifest.as_of_time:
            raise ValueError("query time exceeds the PIT manifest cutoff")
        allowed_ids = self._ids_by_dataset.get(dataset, [])
        if not allowed_ids:
            return []
        queryset, clock_field = self._eligible_queryset(
            dataset, as_of_time, knowledge_scope, filters
        )
        rows = (
            queryset.filter(pk__in=allowed_ids)
            .annotate(
                pit_rank=Window(
                    expression=RowNumber(),
                    partition_by=[F("business_key")],
                    order_by=[F(clock_field).desc(), F("revision_number").desc(), F("id").desc()],
                )
            )
            .filter(pit_rank=1)
        )
        materialized = list(rows)
        if any(
            row.content_hash != self._expected_hashes[row.pk]["content_hash"]
            or _stable_hash(row.payload) != self._expected_hashes[row.pk]["payload_hash"]
            for row in materialized
        ):
            raise ValueError("PIT manifest version evidence is missing or altered")
        return [self._to_domain(row) for row in materialized]


class PITManifestRepository:
    """Build and retrieve immutable dataset manifests."""

    def build(
        self,
        *,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
        calendar_version: str,
        query_spec: dict[str, dict[str, Any]],
        required_keys: dict[str, list[str]] | None = None,
    ) -> PITDatasetManifest:
        """Resolve query specifications and persist their exact evidence set."""

        if as_of_time.tzinfo is None:
            raise ValueError("as_of_time must be timezone-aware")
        as_of_time = as_of_time.astimezone(UTC)
        view = DjangoPITDataView()
        selected: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        estimated: list[dict[str, Any]] = []
        unknown: list[dict[str, Any]] = []
        coverage: dict[str, float] = {}
        required_keys = required_keys or {}
        for dataset, filters in sorted(query_spec.items()):
            queryset, clock_field = view._eligible_queryset(
                dataset, as_of_time, knowledge_scope, filters
            )
            versions = [
                view._to_domain(row)
                for row in queryset.order_by("business_key", clock_field, "revision_number", "id")
            ]
            found_keys = {version.business_key for version in versions}
            expected = set(required_keys.get(dataset, []))
            missing_keys = sorted(expected - found_keys)
            missing.extend({"dataset": dataset, "business_key": key} for key in missing_keys)
            denominator = len(expected) if expected else len(versions)
            coverage[dataset] = (
                1.0
                if not expected or denominator == 0
                else len(found_keys & expected) / denominator
            )
            for version in versions:
                item = {
                    "id": version.version_id,
                    "dataset": dataset,
                    "business_key": version.business_key,
                    "content_hash": version.content_hash,
                    "payload_hash": _stable_hash(version.payload),
                    "pit_quality": version.pit_quality.value,
                }
                selected.append(item)
                if version.pit_quality is PITQuality.ESTIMATED:
                    estimated.append(item)
                elif version.pit_quality is PITQuality.UNKNOWN:
                    unknown.append(item)
        manifest_hash = calculate_pit_manifest_hash(
            PITDatasetManifest(
                manifest_id="",
                as_of_time=as_of_time,
                knowledge_scope=knowledge_scope,
                calendar_version=calendar_version,
                query_spec=query_spec,
                selected_versions=tuple(selected),
                coverage=coverage,
                missing=tuple(missing),
                estimated=tuple(estimated),
                unknown=tuple(unknown),
                manifest_hash="",
            )
        )
        manifest_id = uuid.uuid5(uuid.NAMESPACE_URL, manifest_hash).hex
        model, _ = PITDatasetManifestModel._default_manager.get_or_create(
            manifest_id=manifest_id,
            defaults={
                "as_of_time": as_of_time,
                "knowledge_scope": knowledge_scope.value,
                "calendar_version": calendar_version,
                "query_spec": query_spec,
                "selected_versions": selected,
                "coverage": coverage,
                "missing": missing,
                "estimated": estimated,
                "unknown": unknown,
                "manifest_hash": manifest_hash,
            },
        )
        return self._to_domain(model)

    def get(self, manifest_id: str) -> PITDatasetManifest | None:
        """Return a manifest by stable identifier."""

        model = PITDatasetManifestModel._default_manager.filter(manifest_id=manifest_id).first()
        return self._to_domain(model) if model else None

    def list_recent(self, limit: int = 100) -> list[PITDatasetManifest]:
        """Return recent manifests without exposing mutable querysets."""

        rows = PITDatasetManifestModel._default_manager.order_by("-created_at")[:limit]
        return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(model: PITDatasetManifestModel) -> PITDatasetManifest:
        return PITDatasetManifest(
            manifest_id=model.manifest_id,
            as_of_time=model.as_of_time,
            knowledge_scope=KnowledgeScope(model.knowledge_scope),
            calendar_version=model.calendar_version,
            query_spec=dict(model.query_spec or {}),
            selected_versions=tuple(model.selected_versions or []),
            coverage=dict(model.coverage or {}),
            missing=tuple(model.missing or []),
            estimated=tuple(model.estimated or []),
            unknown=tuple(model.unknown or []),
            manifest_hash=model.manifest_hash,
        )

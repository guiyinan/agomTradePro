"""Read authenticated financial scope authorizations from append-only events."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from django.db import DatabaseError

from apps.data_center.application.financial_scope_capacity_input import (
    FinancialScopeCapacityInputError,
)
from apps.data_center.application.financial_scope_discovery_governance import (
    parse_financial_scope_discovery_authorization,
    parse_financial_scope_manifest_review,
)
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryAuthorization,
    FinancialScopeDiscoveryBinding,
    FinancialScopeDiscoveryCandidate,
    FinancialScopeDiscoveryError,
    FinancialScopeManifestReview,
)
from apps.data_center.infrastructure.models import (
    AssetMasterModel,
    FinancialCapacityGovernanceRecordModel,
    FinancialCapacityOwnerApprovalEventModel,
)


class DjangoFinancialScopeDiscoveryAuthorizationSource:
    """Return only the unique non-revoked, separately authenticated owner event."""

    def get(
        self,
        *,
        binding: FinancialScopeDiscoveryBinding,
        asset_codes: tuple[str, ...],
        now: datetime,
    ) -> FinancialScopeDiscoveryAuthorization | None:
        """Read an exact owner approval without writing or inferring authority."""

        matches: list[FinancialScopeDiscoveryAuthorization] = []
        rows = (
            FinancialCapacityGovernanceRecordModel._default_manager.filter(
                stage=FinancialCapacityGovernanceRecordModel.SCOPE_DISCOVERY,
                revocation__isnull=True,
            )
            .select_related("owner_approval_event")
            .iterator(chunk_size=100)
        )
        for row in rows:
            if not isinstance(row.record, Mapping):
                continue
            try:
                authorization = parse_financial_scope_discovery_authorization(row.record)
                authorization.validate(binding=binding, asset_codes=asset_codes, now=now)
            except (FinancialScopeDiscoveryError, TypeError, ValueError):
                continue
            if (
                row.approval_id == authorization.approval_id
                and row.created_by == authorization.recorded_by
                and _has_matching_owner_event(row, authorization)
            ):
                matches.append(authorization)
        return matches[0] if len(matches) == 1 else None


class DjangoFinancialScopeManifestReviewSource:
    """Return one authenticated owner review and one independent reviewer event."""

    def get(
        self,
        *,
        candidate: FinancialScopeDiscoveryCandidate,
        environment: Literal["isolated", "production"],
        report_sha256: str,
        now: datetime,
    ) -> tuple[FinancialScopeManifestReview, FinancialScopeManifestReview] | None:
        """Read dual approvals bound to exact manifest/report digests and environment."""

        by_role: dict[str, list[FinancialScopeManifestReview]] = {
            "data_owner": [],
            "independent_reviewer": [],
        }
        try:
            rows = (
                FinancialCapacityGovernanceRecordModel._default_manager.filter(
                    stage=FinancialCapacityGovernanceRecordModel.SCOPE_MANIFEST_REVIEW,
                    revocation__isnull=True,
                )
                .select_related("owner_approval_event")
                .iterator(chunk_size=100)
            )
            for row in rows:
                if not isinstance(row.record, Mapping):
                    continue
                try:
                    review = parse_financial_scope_manifest_review(row.record)
                    review.validate(
                        candidate=candidate,
                        environment=environment,
                        report_sha256=report_sha256,
                        now=now,
                    )
                except (FinancialScopeDiscoveryError, TypeError, ValueError):
                    continue
                if (
                    row.approval_id == review.approval_id
                    and row.created_by == review.recorded_by
                    and _has_matching_review_event(row, review)
                ):
                    by_role[review.role].append(review)
        except DatabaseError:
            raise FinancialScopeCapacityInputError(
                "FINANCIAL_CAPACITY_SCOPE_APPROVAL_REQUIRED"
            ) from None
        if len(by_role["data_owner"]) != 1 or len(by_role["independent_reviewer"]) != 1:
            return None
        return by_role["data_owner"][0], by_role["independent_reviewer"][0]


class DjangoFinancialScopeDiscoveryUniverseSource:
    """Read the complete current active stock universe in deterministic order."""

    def get_active_asset_codes(self) -> tuple[str, ...]:
        """Return every active SSE/SZSE/BSE stock without filtering malformed rows."""

        raw_codes = tuple(
            AssetMasterModel._default_manager.filter(
                asset_type="stock",
                exchange__in=("SSE", "SZSE", "BSE"),
                is_active=True,
            )
            .order_by("code")
            .values_list("code", flat=True)
        )
        if any(type(code) is not str for code in raw_codes):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_UNIVERSE_INVALID")
        return raw_codes


def _has_matching_owner_event(
    row: FinancialCapacityGovernanceRecordModel,
    authorization: FinancialScopeDiscoveryAuthorization,
) -> bool:
    """Check event identity, approval receipt, actor, timestamp, and exact JSON digest."""

    event = _owner_event(row)
    return bool(
        event is not None
        and event.event_id == authorization.event_id
        and event.approved_by == authorization.approved_by
        and event.approved_at == authorization.approved_at
        and event.approval_receipt_sha256 == authorization.receipt_sha256
        and event.record_sha256 == _record_sha256(row.record)
    )


def _has_matching_review_event(
    row: FinancialCapacityGovernanceRecordModel,
    review: FinancialScopeManifestReview,
) -> bool:
    """Check one distinct authenticated reviewer event bound to the saved payload."""

    event = _owner_event(row)
    return bool(
        event is not None
        and event.event_id == review.event_id
        and event.approved_by == review.approved_by
        and event.approved_at == review.approved_at
        and event.approval_receipt_sha256 == review.receipt_sha256
        and event.record_sha256 == _record_sha256(row.record)
    )


def _owner_event(
    row: FinancialCapacityGovernanceRecordModel,
) -> FinancialCapacityOwnerApprovalEventModel | None:
    """Return the related authenticated event, distinguishing absence from other errors."""

    try:
        return row.owner_approval_event
    except FinancialCapacityOwnerApprovalEventModel.DoesNotExist:
        return None


def _record_sha256(record: object) -> str:
    """Hash the exact canonical JSON payload used by the owner approval command."""

    if not isinstance(record, Mapping):
        return ""
    try:
        encoded = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DjangoFinancialScopeDiscoveryAuthorizationSource",
    "DjangoFinancialScopeManifestReviewSource",
    "DjangoFinancialScopeDiscoveryUniverseSource",
]

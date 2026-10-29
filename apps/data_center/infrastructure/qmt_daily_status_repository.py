"""Validate owner-scoped normalized QMT status batches from the existing ledger."""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from uuid import UUID

from django.db.models import Q

from apps.data_center.application.qmt_daily_status import (
    QmtDailyStatusReadSnapshot,
    QmtDailyStatusRecord,
)
from apps.data_center.domain.qmt_daily_status import QmtDailyStatusValidationError

from .qmt_bridge_models import QmtBridgeBatchModel, QmtBridgeBindingModel
from .qmt_daily_status_codec import decode_qmt_daily_status_payload


@dataclass(frozen=True, slots=True)
class _ReadScope:
    binding_id: str
    owner_id: int
    provider_id: int
    agent_id: str
    server_url: str
    assets: tuple[str, ...]


def _read_scope(owner_id: int, binding_id: str, asset_code: str) -> _ReadScope | None:
    row = QmtBridgeBindingModel.objects.filter(
        pk=binding_id,
        owner_id=owner_id,
        owner__is_active=True,
        enabled=True,
        revoked=False,
        provider__is_active=True,
        provider__source_type="qmt",
    ).first()
    if row is None or type(row.assets) is not list:
        return None
    raw_assets = cast(list[object], row.assets)
    if any(type(asset) is not str for asset in raw_assets) or asset_code not in raw_assets:
        return None
    if type(row.owner_id) is not int or type(row.provider_id) is not int:
        return None
    return _ReadScope(
        str(row.pk),
        row.owner_id,
        row.provider_id,
        row.agent_id,
        row.server_url,
        cast(tuple[str, ...], tuple(raw_assets)),
    )


def _valid_receipt(value: object, *, batch_id: str, count: int) -> bool:
    if type(value) is not dict:
        return False
    fields = cast(dict[str, object], value)
    expected: dict[str, object] = {
        "batch_id": batch_id,
        "outcome": "success",
        "requested": count,
        "succeeded": count,
        "failed": 0,
        "stored": count,
        "reason": "daily_status_evidence_retained",
    }
    return fields == expected and all(
        type(fields.get(name)) is int for name in ("requested", "succeeded", "failed", "stored")
    )


class QmtDailyStatusRepository:
    """Read normalized assertions, preserving server-known time and current ownership."""

    def read_snapshot(
        self,
        *,
        owner_id: int,
        binding_id: str,
        asset_code: str,
        bar_date: date,
        as_of: datetime,
    ) -> QmtDailyStatusReadSnapshot:
        """Verify every visible status envelope before selecting a security and date."""

        initial_scope = _read_scope(owner_id, binding_id, asset_code)
        if initial_scope is None:
            return QmtDailyStatusReadSnapshot((), "qmt_daily_status_scope_unavailable")
        # Independent stored discriminators also expose a damaged kind/schema.
        status_identity = (
            Q(payload__kind="daily_status")
            | Q(payload__schema_version="qmt-native-daily-status.v1")
            | Q(receipt__reason="daily_status_evidence_retained")
        )
        rows = QmtBridgeBatchModel.objects.filter(
            status_identity,
            binding_id=UUID(binding_id),
            created_at__lte=as_of,
        ).order_by("created_at", "pk")
        records: list[QmtDailyStatusRecord] = []
        for row in rows.iterator(chunk_size=128):
            try:
                batch = decode_qmt_daily_status_payload(row.payload)
                if (
                    batch.batch_id != str(row.batch_id)
                    or type(row.digest) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", row.digest) is None
                    or not hmac.compare_digest(batch.content_hash, row.digest)
                    or batch.collected_at > row.created_at
                    or not _valid_receipt(
                        row.receipt, batch_id=batch.batch_id, count=len(batch.samples)
                    )
                ):
                    raise QmtDailyStatusValidationError(
                        "Stored daily-status identity is inconsistent"
                    )
            except QmtDailyStatusValidationError:
                return QmtDailyStatusReadSnapshot((), "qmt_daily_status_invalid_retained_evidence")
            if any(
                sample.asset_code == asset_code and sample.bar_date == bar_date
                for sample in batch.samples
            ):
                records.append(QmtDailyStatusRecord(batch, row.created_at, row.digest))
        if _read_scope(owner_id, binding_id, asset_code) != initial_scope:
            return QmtDailyStatusReadSnapshot((), "qmt_daily_status_scope_changed")
        return QmtDailyStatusReadSnapshot(tuple(records))

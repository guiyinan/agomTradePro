"""Thin exact adapters from canonical R5 owners into monitoring Phase A."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.fixed_income.application.relative_value_projection import (
    GetExactR5RelativeValueOwnerRecordCommand,
)
from apps.fixed_income.domain.relative_value_record_seal import (
    R5RelativeValueOwnerRecordSeal,
)
from apps.research.application.r5_research_control_preflight import (
    R5ResearchControlActiveLifecycleProvider,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringFixedIncomeEvidence,
)


class R5FixedIncomeOwnerRecordQuery(Protocol):
    """FixedIncome Application exact owner-seal query."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""

    def execute(
        self,
        command: GetExactR5RelativeValueOwnerRecordCommand,
    ) -> R5RelativeValueOwnerRecordSeal | None:
        """Return the exact canonical owner record."""


class R5MonitoringActiveLifecycleExactAdapter:
    """Narrow a scope-selected canonical lifecycle to Phase-A exact fields."""

    def __init__(self, provider: R5ResearchControlActiveLifecycleProvider) -> None:
        self._provider = provider

    @property
    def unit_of_work_key(self) -> str:
        """Return the live canonical owner transaction identity."""

        return self._provider.unit_of_work_key

    def get_exact(
        self,
        *,
        scope_id: str,
        scope_hash: str,
        decision_id: str,
        decision_version: str,
        expected_decision_hash: str,
        expected_lifecycle_hash: str,
        as_of: datetime,
    ) -> R5MonitoringActiveLifecycle | None:
        """Return only the exact lifecycle named by the monitoring target."""

        value = self._provider.get_active(scope_id=scope_id, as_of=as_of)
        if value is None:
            return None
        if type(value) is not R5MonitoringActiveLifecycle:
            raise TypeError("R5 canonical active lifecycle type differs")
        copied = value.validated_copy()
        if copied != value:
            raise ValueError("R5 canonical active lifecycle was substituted")
        if not (
            copied.scope_id == scope_id
            and copied.scope_hash == scope_hash
            and copied.decision_id == decision_id
            and copied.decision_version == decision_version
            and copied.decision_hash == expected_decision_hash
            and copied.content_hash == expected_lifecycle_hash
            and copied.recorded_at <= as_of < copied.valid_until
        ):
            return None
        return copied


class R5MonitoringFixedIncomeExactAdapter:
    """Project one FixedIncome owner record into Phase-A exact evidence."""

    def __init__(self, query: R5FixedIncomeOwnerRecordQuery) -> None:
        self._query = query

    @property
    def unit_of_work_key(self) -> str:
        """Return the live FixedIncome transaction identity."""

        return self._query.unit_of_work_key

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_result_hash: str,
        owner_seal_id: str,
        owner_seal_version: str,
        expected_owner_seal_hash: str,
        as_of: datetime,
    ) -> R5MonitoringFixedIncomeEvidence | None:
        """Reread and strictly match the complete result and owner seal."""

        if owner_seal_version != "v1":
            return None
        record = self._query.execute(
            GetExactR5RelativeValueOwnerRecordCommand(
                result_id=result_id,
                result_version=result_version,
                expected_record_hash=expected_result_hash,
                as_of=as_of,
            )
        )
        if record is None:
            return None
        if type(record) is not R5RelativeValueOwnerRecordSeal:
            raise TypeError("R5 FixedIncome canonical owner record type differs")
        R5RelativeValueOwnerRecordSeal.__post_init__(record)
        value = R5MonitoringFixedIncomeEvidence.create(
            result_id=record.result_id,
            result_version=record.result_version,
            result_hash=record.result_record_hash,
            owner_seal_id=record.owner_record_key,
            owner_seal_version="v1",
            owner_seal_hash=record.content_hash,
            recorded_at=record.recorded_at,
        )
        if not (
            value.result_id == result_id
            and value.result_version == result_version
            and value.result_hash == expected_result_hash
            and value.owner_seal_id == owner_seal_id
            and value.owner_seal_version == owner_seal_version
            and value.owner_seal_hash == expected_owner_seal_hash
            and value.recorded_at <= as_of
        ):
            return None
        return value


__all__ = [
    "R5MonitoringActiveLifecycleExactAdapter",
    "R5MonitoringFixedIncomeExactAdapter",
]

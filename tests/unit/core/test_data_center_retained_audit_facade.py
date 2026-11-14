"""The Data Center Core bridge forwards exact historical Audit pair selectors."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType
from uuid import UUID

import pytest

from apps.audit import retained_system_audit_pair_composition as audit_pair_composition
from apps.audit.application.retained_system_audit_pair import RetainedSystemAuditPair
from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCategory,
    AuditCorrelations,
    AuditEvidenceRef,
    AuditOutcome,
    AuditResourceRef,
    AuditScopeRef,
    AuditSeverity,
    AuditWritePolicy,
    SystemAuditEvent,
)
from core.integration.data_center_audit import (
    read_data_center_retained_system_audit_pair,
    read_data_center_retained_system_audit_stream,
)

_AS_OF = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
_SCOPE = AuditScopeRef(tenant_id="data-center", owner_id="data-center")
_PUBLICATION_ID = "f40c1d5d-c54c-4e9f-8fa1-8545ad95b95b"
_PUBLICATION_HASH = "a" * 64


def _pair() -> RetainedSystemAuditPair:
    """Construct the exact retained-pair DTO with valid, historical clocks."""

    event = SystemAuditEvent.create(
        event_id="m1-publication-event",
        event_version="1",
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type="data.publication.published",
        owner="data_center",
        write_policy=AuditWritePolicy.REQUIRED,
        outcome=AuditOutcome.PUBLISHED,
        severity=AuditSeverity.INFO,
        reason_codes=("publication_published",),
        occurred_at=_AS_OF - timedelta(minutes=2),
        recorded_at=_AS_OF - timedelta(minutes=2),
        observed_at=None,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="publication",
        source_surface="application",
        correlations=AuditCorrelations(
            run_id="20a3ec01-0199-427b-a9b2-1c72f75dcbb2",
            dataset_key="equity.price.bar",
            publication_id=_PUBLICATION_ID,
        ),
        resource=AuditResourceRef("canonical_publication", _PUBLICATION_ID, "price-v1"),
        dataset_key="equity.price.bar",
        provider_key="tushare",
        capability="publication",
        publication_id=_PUBLICATION_ID,
        evidence_refs=(
            AuditEvidenceRef(
                "data_center",
                "canonical_publication",
                _PUBLICATION_ID,
                "price-v1",
                _PUBLICATION_HASH,
            ),
        ),
        detail_schema="data.publication.published.v1",
        detail={
            "publication_key": "m1-rebalance-reference",
            "publication_hash": _PUBLICATION_HASH,
            "member_count": 1,
            "coverage_requested_count": 1,
            "coverage_eligible_count": 1,
            "coverage_selected_count": 1,
            "raw_audit_manifest": {
                "manifest_id": "b9ed7705-c0d6-4594-a9fc-3e36a4b4e8d6",
                "manifest_version": "1",
                "manifest_hash": "b" * 64,
                "raw_audit_count": 1,
                "raw_audit_hash": "c" * 64,
            },
        },
        stream_id="data.publication:equity.price.bar",
        sequence_no=1,
        predecessor_hash=None,
        idempotency_key="data-publication-manifest:run:publication:manifest:hash",
        scope=_SCOPE,
    )
    return RetainedSystemAuditPair(
        event=event,
        audit_persisted_at=_AS_OF - timedelta(minutes=1, seconds=59),
        outbox_id=str(UUID("b36a2877-70d3-4cd7-b771-0c4df10db3ed")),
        outbox_payload_sha256="d" * 64,
        outbox_created_at=_AS_OF - timedelta(minutes=1, seconds=58),
    )


def test_facade_forwards_exact_event_scope_alias_and_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the Audit-owned bounded reader and preserve its exact typed receipt."""

    expected = {
        "event_id": "m1-publication-event",
        "event_version": "1",
        "stream_id": "data.publication:equity.price.bar",
        "scope": _SCOPE,
        "using": "default",
        "as_of": _AS_OF,
    }
    receipt = _pair()

    def read_exact(**values: object) -> RetainedSystemAuditPair:
        if values != expected:
            raise AssertionError("Core changed an exact retained-pair selector")
        return receipt

    monkeypatch.setattr(audit_pair_composition, "read_retained_system_audit_pair", read_exact)
    observed = read_data_center_retained_system_audit_pair(**expected)

    assert observed is receipt


def test_facade_does_not_mask_audit_or_outbox_fail_closed_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing original pair evidence remains a typed unavailable result."""

    def unavailable(**values: object) -> RetainedSystemAuditPair:
        del values
        raise SystemAuditCompositionUnavailable(
            "original Audit reader unavailable", reason_code="original_pair_missing"
        )

    monkeypatch.setattr(audit_pair_composition, "read_retained_system_audit_pair", unavailable)
    with pytest.raises(SystemAuditCompositionUnavailable):
        read_data_center_retained_system_audit_pair(
            event_id="m1-publication-event",
            event_version="1",
            stream_id="data.publication:equity.price.bar",
            scope=_SCOPE,
            using="default",
            as_of=_AS_OF,
        )


def test_stream_facade_forwards_the_exact_scoped_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose the Audit-owned complete stream reader through Core only."""
    expected = {
        "stream_id": "data.publication:equity.price.bar",
        "scope": _SCOPE,
        "using": "default",
        "as_of": _AS_OF,
    }
    pairs = (_pair(),)
    module_name = "apps.audit.retained_system_audit_stream_composition"
    module = ModuleType(module_name)

    def read_stream(**values: object) -> tuple[RetainedSystemAuditPair, ...]:
        if values != expected:
            raise AssertionError("Core changed the retained Audit stream selector")
        return pairs

    module.__dict__["read_retained_system_audit_stream"] = read_stream
    monkeypatch.setitem(sys.modules, module_name, module)

    observed = read_data_center_retained_system_audit_stream(**expected)

    assert observed is pairs


def test_stream_facade_preserves_audit_owned_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing or malformed Audit stream evidence stays unavailable."""
    module_name = "apps.audit.retained_system_audit_stream_composition"
    module = ModuleType(module_name)

    def unavailable(**values: object) -> tuple[RetainedSystemAuditPair, ...]:
        del values
        raise SystemAuditCompositionUnavailable(
            "original Audit stream unavailable", reason_code="original_stream_missing"
        )

    module.__dict__["read_retained_system_audit_stream"] = unavailable
    monkeypatch.setitem(sys.modules, module_name, module)
    with pytest.raises(SystemAuditCompositionUnavailable):
        read_data_center_retained_system_audit_stream(
            stream_id="data.publication:equity.price.bar",
            scope=_SCOPE,
            using="default",
            as_of=_AS_OF,
        )

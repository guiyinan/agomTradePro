"""Pure-domain and application contracts for the financial numeric catalog."""

from __future__ import annotations

import ast
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest

from apps.data_center.application.financial_numeric_catalog import (
    CaptureFinancialNumericSourceDocumentUseCase,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.financial_numeric_catalog import (
    FinancialNumericCatalogEntry,
    FinancialNumericCatalogOwnerEvent,
    resolve_financial_numeric_source_qualification,
)
from apps.data_center.domain.financial_numeric_evidence import FinancialMetricSourceContract
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceContextRequirement,
    FinancialNumericSourceDocumentCaptureReference,
    FinancialNumericSourceQualification,
)
from apps.data_center.domain.provider_document_response import ProviderDocumentResponseCapture
from apps.data_center.domain.provider_response import ProviderResponseTransport
from core.exceptions import DataValidationError

_SOURCE_ROOT = Path(__file__).resolve().parents[3]

_ENDPOINT = "datacenter.eastmoney.com/securities/api/data/get?type=RPT_F10_FINANCE_MAINFINADATA"
_NOW = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)


class _ExplodingTimezone(tzinfo):
    """Raise during conversion so catalog clock validation rejects unrepresentable time."""

    def __init__(self) -> None:
        """Initialize a one-call UTC offset for the initial awareness check."""

        self.calls = 0

    def utcoffset(self, dt: datetime | None) -> timedelta:
        """Raise on conversion after the initial aware-datetime check."""

        del dt
        self.calls += 1
        if self.calls > 1:
            raise OverflowError("synthetic unrepresentable clock")
        return timedelta(0)

    def dst(self, dt: datetime | None) -> timedelta:
        """Return no DST adjustment for the synthetic zero-offset clock."""

        del dt
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        """Return a stable non-business test timezone label."""

        del dt
        return "synthetic"


def _qualification() -> FinancialNumericSourceQualification:
    """Build one synthetic native-source qualification without business unit defaults."""

    capture_at = _NOW - timedelta(days=2)
    capture = FinancialNumericSourceDocumentCaptureReference(
        capture_id=UUID("6ed7d121-b8e0-485e-a8cd-cc892605b427"),
        document_id="synthetic-document",
        issuer="synthetic-issuer",
        canonical_url="https://docs.example.test/finance",
        body_sha256="a" * 64,
        body_size_bytes=12,
        captured_at=capture_at,
        content_type="text/html",
    )
    contract = _contract()
    return FinancialNumericSourceQualification(
        contract=contract,
        endpoint=_ENDPOINT,
        source_applicability="synthetic-row-applicability",
        document_capture=capture,
        context_requirements=(
            FinancialNumericSourceContextRequirement("statement_scope", "synthetic-scope"),
        ),
        effective_from=capture_at,
        effective_until=None,
    )


def _contract(contract_version: str = "test.v1") -> FinancialMetricSourceContract:
    """Build a synthetic native contract with an explicit source and canonical unit."""

    return FinancialMetricSourceContract(
        provider="synthetic-provider",
        dataset_key="synthetic-financial-dataset",
        metric_code="synthetic-metric",
        source_field="SYNTHETIC_NATIVE_FIELD",
        source_unit="synthetic-source-unit",
        canonical_unit="synthetic-canonical-unit",
        scale_numerator=1,
        scale_denominator=1,
        contract_version=contract_version,
        origin="native",
    )


def _entry(
    qualification: FinancialNumericSourceQualification | None = None,
    *,
    apply_at: datetime | None = None,
    revoke_at: datetime | None = None,
) -> object:
    """Build one catalog entry with typed authenticated-event metadata."""

    qualification = qualification or _qualification()
    recorded_at = max(
        _NOW - timedelta(days=1),
        qualification.document_capture.captured_at + timedelta(seconds=1),
    )
    applied = FinancialNumericCatalogOwnerEvent(
        event_id=uuid4(),
        entry_id=uuid4(),
        action="apply",
        qualification_identity=qualification.identity,
        qualification_sha256=qualification.content_hash,
        actor_id=7,
        actor_username="authenticated-owner",
        event_at=apply_at or recorded_at,
        recorded_at=apply_at or recorded_at,
    )
    events = [applied]
    if revoke_at is not None:
        events.append(
            FinancialNumericCatalogOwnerEvent(
                event_id=uuid4(),
                entry_id=applied.entry_id,
                action="revoke",
                qualification_identity=qualification.identity,
                qualification_sha256=qualification.content_hash,
                actor_id=7,
                actor_username="authenticated-owner",
                event_at=revoke_at,
                recorded_at=revoke_at,
            )
        )
    return FinancialNumericCatalogEntry(
        entry_id=applied.entry_id,
        qualification=qualification,
        recorded_at=recorded_at,
        capture_recorded_at=qualification.document_capture.captured_at,
        owner_events=tuple(events),
    )


def _event(
    qualification: FinancialNumericSourceQualification,
    entry_id: UUID,
    *,
    action: str,
    event_at: datetime,
    recorded_at: datetime,
    **overrides: object,
) -> object:
    """Build a candidate owner event with optional deliberately invalid fields."""

    values: dict[str, object] = {
        "event_id": uuid4(),
        "entry_id": entry_id,
        "action": action,
        "qualification_identity": qualification.identity,
        "qualification_sha256": qualification.content_hash,
        "actor_id": 7,
        "actor_username": "authenticated-owner",
        "event_at": event_at,
        "recorded_at": recorded_at,
    }
    values.update(overrides)
    return FinancialNumericCatalogOwnerEvent(**values)


def _resolve(
    entries: tuple[object, ...],
    *,
    contract_identity: str | None = None,
    endpoint: str = _ENDPOINT,
    response_at: datetime | None = None,
    known_at: datetime = _NOW,
    context: object = None,
) -> FinancialNumericSourceQualification | None:
    """Call the typed candidate resolver while keeping all clocks explicit."""

    return cast(
        FinancialNumericSourceQualification | None,
        resolve_financial_numeric_source_qualification(
            cast(tuple[FinancialNumericCatalogEntry, ...], entries),
            contract_identity=contract_identity or _qualification().contract.identity,
            endpoint=endpoint,
            source_response_completed_at=response_at or _NOW - timedelta(hours=1),
            source_context=({"statement_scope": "synthetic-scope"} if context is None else context),
            known_at=known_at,
        ),
    )


def test_resolves_only_exact_contract_endpoint_and_source_context() -> None:
    """Resolve one currently applied qualification with exact source-row context."""

    entry = cast(FinancialNumericCatalogEntry, _entry())
    result = _resolve((entry,))

    assert result == entry.qualification


@pytest.mark.parametrize(
    ("endpoint", "context"),
    [
        ("https://different.example/endpoint", {"statement_scope": "synthetic-scope"}),
        (_ENDPOINT, {"statement_scope": "other-scope"}),
        (_ENDPOINT, {}),
    ],
)
def test_missing_or_mismatched_endpoint_and_context_fail_closed(
    endpoint: str, context: object
) -> None:
    """Do not infer endpoint or source context when either is absent or different."""

    assert (
        _resolve(
            (cast(FinancialNumericCatalogEntry, _entry()),), endpoint=endpoint, context=context
        )
        is None
    )


def test_missing_authenticated_apply_event_blocks_resolution() -> None:
    """An entry payload without a real Owner event is not eligible."""

    qualification = _qualification()
    entry = FinancialNumericCatalogEntry(
        entry_id=uuid4(),
        qualification=qualification,
        recorded_at=_NOW - timedelta(days=1),
        capture_recorded_at=qualification.document_capture.captured_at,
        owner_events=(),
    )

    assert _resolve((entry,)) is None


def test_source_response_and_known_at_are_independent_clocks() -> None:
    """A newer document cannot retrospectively qualify an old response."""

    qualification = _qualification()
    later_document = FinancialNumericSourceDocumentCaptureReference(
        capture_id=uuid4(),
        document_id="later-document",
        issuer="synthetic-issuer",
        canonical_url="https://docs.example.test/finance-v2",
        body_sha256="b" * 64,
        body_size_bytes=12,
        captured_at=_NOW - timedelta(hours=2),
        content_type="text/html",
    )
    later_qualification = FinancialNumericSourceQualification(
        contract=qualification.contract,
        endpoint=qualification.endpoint,
        source_applicability=qualification.source_applicability,
        document_capture=later_document,
        context_requirements=qualification.context_requirements,
        effective_from=later_document.captured_at,
        effective_until=None,
    )
    entry = cast(FinancialNumericCatalogEntry, _entry(later_qualification))

    assert (
        _resolve(
            (entry,),
            response_at=_NOW - timedelta(days=1),
            known_at=_NOW,
        )
        is None
    )
    assert _resolve((entry,), response_at=_NOW - timedelta(hours=1), known_at=_NOW) == (
        later_qualification
    )
    assert (
        _resolve(
            (entry,),
            response_at=_NOW + timedelta(seconds=1),
            known_at=_NOW,
        )
        is None
    )


def test_effective_interval_is_half_open_and_can_expire_before_known_at() -> None:
    """Source applicability uses response time even when knowledge arrives later."""

    qualification = _qualification()
    source_from = qualification.effective_from
    source_until = _NOW - timedelta(hours=2)
    windowed = FinancialNumericSourceQualification(
        contract=qualification.contract,
        endpoint=qualification.endpoint,
        source_applicability=qualification.source_applicability,
        document_capture=qualification.document_capture,
        context_requirements=qualification.context_requirements,
        effective_from=source_from,
        effective_until=source_until,
    )
    entry = cast(FinancialNumericCatalogEntry, _entry(windowed))

    assert _resolve((entry,), response_at=source_from, known_at=_NOW) == windowed
    assert _resolve((entry,), response_at=source_until, known_at=_NOW) is None


def test_revocation_applies_only_when_known_at_or_after_event() -> None:
    """A later revoke does not rewrite earlier knowledge, but blocks afterwards."""

    revoke_at = _NOW - timedelta(minutes=30)
    entry = cast(FinancialNumericCatalogEntry, _entry(revoke_at=revoke_at))

    assert _resolve((entry,), known_at=revoke_at - timedelta(seconds=1)) == entry.qualification
    assert _resolve((entry,), known_at=_NOW) is None


def test_revocation_without_apply_is_rejected() -> None:
    """A revoke event cannot create the applied state it is supposed to withdraw."""

    qualification = _qualification()
    entry_id = uuid4()
    recorded_at = _NOW - timedelta(days=1)
    revoke = FinancialNumericCatalogOwnerEvent(
        event_id=uuid4(),
        entry_id=entry_id,
        action="revoke",
        qualification_identity=qualification.identity,
        qualification_sha256=qualification.content_hash,
        actor_id=7,
        actor_username="authenticated-owner",
        event_at=recorded_at,
        recorded_at=recorded_at,
    )

    with pytest.raises(ValueError, match="revoked before it is applied"):
        FinancialNumericCatalogEntry(
            entry_id=entry_id,
            qualification=qualification,
            recorded_at=recorded_at,
            capture_recorded_at=qualification.document_capture.captured_at,
            owner_events=(revoke,),
        )


def test_revoke_cannot_precede_apply_or_entry_clock() -> None:
    """Contradictory append-only event order is rejected at Domain construction."""

    qualification = _qualification()
    entry_id = uuid4()
    recorded_at = _NOW - timedelta(days=1)
    apply_at = recorded_at + timedelta(minutes=2)
    applied = FinancialNumericCatalogOwnerEvent(
        event_id=uuid4(),
        entry_id=entry_id,
        action="apply",
        qualification_identity=qualification.identity,
        qualification_sha256=qualification.content_hash,
        actor_id=7,
        actor_username="authenticated-owner",
        event_at=apply_at,
        recorded_at=apply_at,
    )
    revoked = FinancialNumericCatalogOwnerEvent(
        event_id=uuid4(),
        entry_id=entry_id,
        action="revoke",
        qualification_identity=qualification.identity,
        qualification_sha256=qualification.content_hash,
        actor_id=7,
        actor_username="authenticated-owner",
        event_at=recorded_at + timedelta(minutes=1),
        recorded_at=recorded_at + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="cannot predate"):
        FinancialNumericCatalogEntry(
            entry_id=entry_id,
            qualification=qualification,
            recorded_at=recorded_at,
            capture_recorded_at=qualification.document_capture.captured_at,
            owner_events=(applied, revoked),
        )


def test_ambiguous_qualifications_do_not_select_arbitrarily() -> None:
    """Overlapping applied qualifications with the same context block resolution."""

    first = cast(FinancialNumericCatalogEntry, _entry())
    second = cast(FinancialNumericCatalogEntry, _entry())

    assert _resolve((first, second)) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"event_id": "not-a-uuid"},
        {"action": "approve"},
        {"qualification_identity": " "},
        {"qualification_sha256": "not-a-hash"},
        {"actor_id": True},
        {"actor_username": " authenticated-owner "},
        {"event_at": _NOW + timedelta(seconds=1)},
        {"event_at": datetime(2026, 11, 15, 10, 0)},
        {"event_at": datetime(2026, 11, 15, 12, 0, tzinfo=timezone(timedelta(hours=2)))},
    ],
)
def test_owner_event_rejects_invalid_identity_actor_or_clock(overrides: dict[str, object]) -> None:
    """Reject altered event tags, owner identities, and non-UTC or contradictory clocks."""

    qualification = _qualification()
    recorded_at = _NOW - timedelta(days=1)

    values: dict[str, object] = {
        "event_id": uuid4(),
        "entry_id": uuid4(),
        "action": "apply",
        "qualification_identity": qualification.identity,
        "qualification_sha256": qualification.content_hash,
        "actor_id": 7,
        "actor_username": "authenticated-owner",
        "event_at": recorded_at,
        "recorded_at": recorded_at,
    }
    values.update(overrides)

    with pytest.raises((TypeError, ValueError)):
        FinancialNumericCatalogOwnerEvent(**values)


def test_owner_event_rejects_clock_that_cannot_be_normalized() -> None:
    """Reject aware-looking timestamps whose timezone conversion overflows."""

    qualification = _qualification()
    recorded_at = _NOW - timedelta(days=1)

    with pytest.raises(ValueError, match="representable in UTC"):
        _event(
            qualification,
            uuid4(),
            action="apply",
            event_at=datetime(2026, 11, 15, 10, 0, tzinfo=_ExplodingTimezone()),
            recorded_at=recorded_at,
        )


def test_catalog_entry_rejects_incomplete_and_contradictory_rows() -> None:
    """Reject missing capture chronology, untyped events, identity collisions, and duplicate actions."""

    entry = cast(FinancialNumericCatalogEntry, _entry())
    applied = entry.owner_events[0]
    future = applied.recorded_at + timedelta(minutes=1)

    invalid_values = (
        {"entry_id": "not-a-uuid"},
        {"qualification": object()},
        {
            "capture_recorded_at": entry.qualification.document_capture.captured_at
            - timedelta(seconds=1)
        },
        {"recorded_at": entry.capture_recorded_at - timedelta(seconds=1)},
        {"owner_events": []},
        {"owner_events": (applied, replace(applied))},
        {"owner_events": (replace(applied, entry_id=uuid4()),)},
        {
            "owner_events": (
                replace(
                    applied,
                    event_at=entry.recorded_at - timedelta(seconds=2),
                    recorded_at=entry.recorded_at - timedelta(seconds=1),
                ),
            )
        },
        {"owner_events": (replace(applied, event_at=entry.recorded_at - timedelta(seconds=1)),)},
        {"owner_events": (applied, replace(applied, event_id=uuid4()))},
    )

    for changes in invalid_values:
        with pytest.raises((TypeError, ValueError)):
            replace(entry, **changes)

    duplicate_revoke_events = (
        applied,
        _event(
            entry.qualification,
            entry.entry_id,
            action="revoke",
            event_at=future,
            recorded_at=future,
        ),
        _event(
            entry.qualification,
            entry.entry_id,
            action="revoke",
            event_at=future + timedelta(seconds=1),
            recorded_at=future + timedelta(seconds=1),
        ),
    )
    with pytest.raises(ValueError, match="more than one revoke"):
        replace(entry, owner_events=duplicate_revoke_events)

    duplicate_apply_events = (
        applied,
        replace(applied, event_id=uuid4()),
    )
    with pytest.raises(ValueError, match="more than one apply"):
        replace(entry, owner_events=duplicate_apply_events)


def test_unrecorded_future_revocation_preserves_historical_knowledge() -> None:
    """A future append-only revoke does not alter a cutoff before it was recorded."""

    revoked_at = _NOW + timedelta(days=1)
    entry = cast(FinancialNumericCatalogEntry, _entry(revoke_at=revoked_at))

    assert _resolve((entry,), known_at=_NOW) == entry.qualification
    assert _resolve((entry,), known_at=revoked_at + timedelta(seconds=1)) is None


def test_apply_and_revoke_hash_mismatches_block_resolution() -> None:
    """Do not treat an event with a changed qualification hash as authorization."""

    qualification = _qualification()
    entry_id = uuid4()
    recorded_at = _NOW - timedelta(days=1)
    changed_apply = _event(
        qualification,
        entry_id,
        action="apply",
        event_at=recorded_at,
        recorded_at=recorded_at,
        qualification_sha256="f" * 64,
    )
    bad_apply_entry = FinancialNumericCatalogEntry(
        entry_id=entry_id,
        qualification=qualification,
        recorded_at=recorded_at,
        capture_recorded_at=qualification.document_capture.captured_at,
        owner_events=(changed_apply,),
    )
    assert _resolve((bad_apply_entry,)) is None

    good_apply = _event(
        qualification,
        entry_id,
        action="apply",
        event_at=recorded_at,
        recorded_at=recorded_at,
    )
    changed_revoke = _event(
        qualification,
        entry_id,
        action="revoke",
        event_at=recorded_at + timedelta(minutes=1),
        recorded_at=recorded_at + timedelta(minutes=1),
        qualification_identity="changed-qualification",
    )
    bad_revoke_entry = FinancialNumericCatalogEntry(
        entry_id=entry_id,
        qualification=qualification,
        recorded_at=recorded_at,
        capture_recorded_at=qualification.document_capture.captured_at,
        owner_events=(good_apply, changed_revoke),
    )
    assert _resolve((bad_revoke_entry,)) is None


def test_resolver_rejects_invalid_query_shape_and_naive_clock() -> None:
    """Invalid typed query values cannot select a candidate from the catalog."""

    entry = cast(FinancialNumericCatalogEntry, _entry())
    base = {
        "contract_identity": entry.qualification.contract.identity,
        "endpoint": _ENDPOINT,
        "source_response_completed_at": _NOW - timedelta(hours=1),
        "source_context": {"statement_scope": "synthetic-scope"},
        "known_at": _NOW,
    }

    for changes in (
        {"contract_identity": " "},
        {"endpoint": " "},
        {"source_context": None},
        {"source_context": {1: "synthetic-scope"}},
        {"source_response_completed_at": datetime(2026, 11, 16, 9, 0)},
        {"known_at": datetime(2026, 11, 16, 10, 0)},
    ):
        query = {**base, **changes}
        assert (
            resolve_financial_numeric_source_qualification(
                (entry,),
                contract_identity=cast(str, query["contract_identity"]),
                endpoint=cast(str, query["endpoint"]),
                source_response_completed_at=cast(datetime, query["source_response_completed_at"]),
                source_context=cast(dict[str, object], query["source_context"]),
                known_at=cast(datetime, query["known_at"]),
            )
            is None
        )

    assert (
        resolve_financial_numeric_source_qualification(
            cast(object, []),
            contract_identity=base["contract_identity"],
            endpoint=_ENDPOINT,
            source_response_completed_at=base["source_response_completed_at"],
            source_context=cast(dict[str, object], base["source_context"]),
            known_at=_NOW,
        )
        is None
    )


class _NoNetworkFetch:
    """Count attempted transport calls and fail if invalid input reaches it."""

    def __init__(self) -> None:
        """Initialize the call counter."""

        self.calls = 0

    def __call__(
        self,
        context: EgressRequestContext,
        *,
        max_bytes: int,
        allowed_media_types: frozenset[str],
        max_attempts: int,
    ) -> ProviderDocumentResponseCapture:
        """Fail the test if the capture use case reaches its fetch port."""

        del context, max_bytes, allowed_media_types, max_attempts
        self.calls += 1
        raise AssertionError("invalid document input reached the fetch port")


@pytest.mark.parametrize(
    ("issuer", "document_id", "canonical_url"),
    [
        ("", "doc", "https://docs.example.test/finance"),
        ("issuer", "x" * 241, "https://docs.example.test/finance"),
        ("issuer\n", "doc", "https://docs.example.test/finance"),
        ("issuer", "doc", "http://docs.example.test/finance"),
        ("issuer", "doc", "https://docs.example.test:443/finance"),
        ("issuer", "doc", "https://user@docs.example.test/finance"),
        ("issuer", "doc", "https://docs.example.test/finance#fragment"),
    ],
)
def test_invalid_capture_identity_is_rejected_before_fetch(
    issuer: str, document_id: str, canonical_url: str
) -> None:
    """Reject incomplete, oversized, or noncanonical document identity with zero HTTP calls."""

    fetch = _NoNetworkFetch()
    use_case = CaptureFinancialNumericSourceDocumentUseCase(
        document_fetch=fetch,
        capture_repository=object(),
        provider_id=1,
        dataset_key="synthetic-document-dataset",
        deployment_region="test-region",
    )

    with pytest.raises(DataValidationError):
        use_case.execute(
            issuer=issuer,
            document_id=document_id,
            canonical_url=canonical_url,
            max_bytes=1024,
            allowed_media_types=frozenset({"text/html"}),
        )

    assert fetch.calls == 0


class _StaticDocumentFetch:
    """Return one fixture capture without opening a network connection."""

    def __init__(self, response: ProviderDocumentResponseCapture) -> None:
        """Store the exact response returned by the fake transport."""

        self.response = response
        self.calls = 0

    def __call__(
        self,
        context: EgressRequestContext,
        *,
        max_bytes: int,
        allowed_media_types: frozenset[str],
        max_attempts: int,
    ) -> ProviderDocumentResponseCapture:
        """Return the fixed response after checking explicit request bounds."""

        del max_attempts
        self.calls += 1
        assert context.target_url == "https://docs.example.test/finance"
        assert max_bytes == 1024
        assert allowed_media_types == frozenset({"text/html"})
        return self.response


class _CaptureRepository:
    """Record the candidate persistence call without touching a database."""

    def __init__(self) -> None:
        """Initialize the captured call slot."""

        self.call: tuple[int, str, str, object, object] | None = None

    def append_document_capture(
        self,
        *,
        provider_id: int,
        dataset_key: str,
        deployment_region: str,
        reference: object,
        response: object,
    ) -> object:
        """Retain the application handoff arguments in memory for assertion."""

        self.call = (provider_id, dataset_key, deployment_region, reference, response)
        return reference


def test_capture_use_case_hands_exact_response_to_repository_without_native_version() -> None:
    """Capture metadata uses a local UUID and exact bytes, without inventing a version."""

    body = b"<html>synthetic source</html>"
    capture_id = uuid4()
    captured_at = _NOW - timedelta(minutes=5)
    response = ProviderDocumentResponseCapture(
        request_id=capture_id,
        attempt=1,
        egress_id=6,
        target_url_sha256=hashlib.sha256(b"https://docs.example.test/finance").hexdigest(),
        target_host="docs.example.test",
        body=body,
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=captured_at,
        status_code=200,
        content_type="text/html; charset=utf-8",
        transport=ProviderResponseTransport.EGRESS,
    )
    fetch = _StaticDocumentFetch(response)
    repository = _CaptureRepository()
    use_case = CaptureFinancialNumericSourceDocumentUseCase(
        document_fetch=fetch,
        capture_repository=repository,
        provider_id=1,
        dataset_key="synthetic-document-dataset",
        deployment_region="test-region",
    )

    result = use_case.execute(
        issuer="synthetic-issuer",
        document_id="synthetic-document",
        canonical_url="https://docs.example.test/finance",
        max_bytes=1024,
        allowed_media_types=frozenset({"text/html"}),
    )

    assert fetch.calls == 1
    assert result.capture_id == capture_id
    assert result.captured_at == captured_at
    assert repository.call is not None
    assert repository.call[:3] == (
        1,
        "synthetic-document-dataset",
        "test-region",
    )
    assert repository.call[3] == result
    assert repository.call[4] is response
    assert "source_version" not in result.to_dict()
    assert result.content_type == "text/html; charset=utf-8"


def test_contract_identity_column_covers_maximum_contract_version() -> None:
    """Keep the DB contract identity bound wide enough for every legal v1 version."""

    model_file = (
        _SOURCE_ROOT
        / "apps"
        / "data_center"
        / "infrastructure"
        / "financial_numeric_catalog_models.py"
    )
    syntax = ast.parse(model_file.read_text(encoding="utf-8"))
    model_node = next(
        node
        for node in syntax.body
        if isinstance(node, ast.ClassDef) and node.name == "FinancialMetricSourceCatalogEntryModel"
    )
    field_assignment = next(
        node
        for node in model_node.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "contract_identity"
            for target in node.targets
        )
    )
    field_call = cast(ast.Call, field_assignment.value)
    max_length_node = next(
        keyword.value for keyword in field_call.keywords if keyword.arg == "max_length"
    )
    max_length = cast(ast.Constant, max_length_node).value
    longest_legal_identity = _contract("v" * 40).identity

    assert type(max_length) is int
    assert len(longest_legal_identity) <= max_length


def test_overlong_but_supported_capture_header_is_blocked_before_metadata_append() -> None:
    """Respect the numeric capture reference's tighter 200-character content-type bound."""

    body = b"<html>synthetic source</html>"
    content_type = "text/html; charset=" + ("x" * 190)
    response = ProviderDocumentResponseCapture(
        request_id=uuid4(),
        attempt=1,
        egress_id=6,
        target_url_sha256=hashlib.sha256(b"https://docs.example.test/finance").hexdigest(),
        target_host="docs.example.test",
        body=body,
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=_NOW - timedelta(minutes=5),
        status_code=200,
        content_type=content_type,
        transport=ProviderResponseTransport.EGRESS,
    )
    fetch = _StaticDocumentFetch(response)
    repository = _CaptureRepository()
    use_case = CaptureFinancialNumericSourceDocumentUseCase(
        document_fetch=fetch,
        capture_repository=repository,
        provider_id=1,
        dataset_key="synthetic-document-dataset",
        deployment_region="test-region",
    )

    with pytest.raises(DataValidationError):
        use_case.execute(
            issuer="synthetic-issuer",
            document_id="synthetic-document",
            canonical_url="https://docs.example.test/finance",
            max_bytes=1024,
            allowed_media_types=frozenset({"text/html"}),
        )

    assert fetch.calls == 1
    assert repository.call is None

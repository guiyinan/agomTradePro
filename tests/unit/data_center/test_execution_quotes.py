"""Typed execution quote evidence rejects unsafe adapter results."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from apps.data_center import execution_quote_composition, publication_read_composition
from apps.data_center.application import query_services
from apps.data_center.application.execution_quotes import (
    ExecutionQuoteBlockReason,
    ExecutionQuotePublicationGate,
    ExecutionQuoteUnavailable,
    GetExecutionQuoteUseCase,
)
from apps.data_center.domain.contracts import (
    DatasetContractAmbiguousError,
    DatasetKey,
    PublicationPolicy,
)
from apps.data_center.domain.execution_quotes import ExecutionQuoteSnapshot
from apps.data_center.infrastructure import execution_quote_repository
from core.exceptions import InvalidInputError

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
ASSET = "600000.SH"
PUBLICATION_ID = "publication-1"
PUBLICATION_HASH = "a" * 64
FACT_HASH = "b" * 64


def _gate(**changes: object) -> ExecutionQuotePublicationGate:
    """Build one valid active publication gate for the use-case tests."""

    value = ExecutionQuotePublicationGate(
        dataset_key="equity.quote.snapshot",
        publication_key="execution",
        publication_id=PUBLICATION_ID,
        publication_hash=PUBLICATION_HASH,
        publication_as_of=NOW - timedelta(seconds=1),
        published_at=NOW - timedelta(seconds=1),
        policy_identity="p2:policy:hash",
        contract_version="2.0",
        schema_version="1.0",
        contract_resolution="current_active_not_point_in_time",
        execution_freshness_seconds=60,
        must_not_use_for_decision=False,
        blocked_reason="",
        freshness_status="fresh",
    )
    return replace(value, **changes)


def _quote(**changes: object) -> ExecutionQuoteSnapshot:
    """Build one valid Decimal-preserving execution quote."""

    value = ExecutionQuoteSnapshot(
        asset_code=ASSET,
        last=Decimal("10.1234"),
        bid=None,
        ask=Decimal("10.1300"),
        previous_close=Decimal("9.9000"),
        snapshot_at=NOW - timedelta(seconds=10),
        fetched_at=NOW - timedelta(seconds=9),
        fact_pk="42",
        fact_content_hash=FACT_HASH,
        dataset_key="equity.quote.snapshot",
        publication_id=PUBLICATION_ID,
        publication_hash=PUBLICATION_HASH,
        publication_as_of=NOW - timedelta(seconds=1),
        published_at=NOW - timedelta(seconds=1),
        freshness_deadline=NOW + timedelta(seconds=50),
        queried_at=NOW,
        policy_identity="p2:policy:hash",
        contract_version="2.0",
        schema_version="1.0",
        contract_resolution="current_active_not_point_in_time",
        execution_freshness_seconds=60,
        source="tushare",
        quality_status="accepted",
    )
    for field_name, field_value in changes.items():
        object.__setattr__(value, field_name, field_value)
    return value


class _GateReader:
    def __init__(self, result: ExecutionQuotePublicationGate | None) -> None:
        self.result = result

    def get_current_gate(
        self, _asset_code: str, *, as_of: datetime
    ) -> ExecutionQuotePublicationGate | None:
        assert as_of == NOW
        return self.result


class _QuoteReader:
    def __init__(self, result: ExecutionQuoteSnapshot) -> None:
        self.result = result

    def get_exact_quote(
        self,
        _asset_code: str,
        *,
        publication_gate: ExecutionQuotePublicationGate,
        as_of: datetime,
    ) -> ExecutionQuoteSnapshot:
        assert publication_gate.publication_id == PUBLICATION_ID
        assert as_of == NOW
        return self.result


def _use_case(
    quote: object,
    gate: ExecutionQuotePublicationGate | None = None,
) -> GetExecutionQuoteUseCase:
    return GetExecutionQuoteUseCase(
        gate_reader=_GateReader(gate if gate is not None else _gate()),
        quote_reader=_QuoteReader(cast(ExecutionQuoteSnapshot, quote)),
    )


def test_execution_quote_keeps_decimal_precision_and_unknown_bbo() -> None:
    result = _use_case(_quote(last=Decimal("10.1234"))).execute(ASSET, as_of=NOW)

    assert result.last == Decimal("10.1234")
    assert result.bid is None
    assert result.ask == Decimal("10.1300")


def test_execution_gate_reads_exact_execution_key_and_preserves_its_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def _gate_payload(
        dataset_key: str,
        publication_key: str,
        *,
        as_of: datetime,
        asset_code: str,
    ) -> dict[str, object]:
        assert as_of == NOW
        assert asset_code == ASSET
        calls.append((dataset_key, publication_key))
        return {
            "dataset_key": dataset_key,
            "publication_key": publication_key,
            "publication_id": PUBLICATION_ID,
            "publication_hash": PUBLICATION_HASH,
            "as_of": NOW - timedelta(seconds=1),
            "published_at": NOW - timedelta(seconds=1),
            "policy_identity": "p2:policy:hash",
            "contract_version": "2.0",
            "schema_version": "1.0",
            "contract_resolution": "current_active_not_point_in_time",
            "execution_freshness_seconds": 5,
            "max_age_seconds": 14_400,
            "must_not_use_for_decision": False,
            "blocked_reason": "",
            "freshness_status": "fresh",
        }

    monkeypatch.setattr(
        execution_quote_composition,
        "get_current_publication_freshness_gate",
        _gate_payload,
    )
    gate = execution_quote_composition._ExecutionQuoteGateReader().get_current_gate(
        ASSET, as_of=NOW
    )

    assert gate is not None
    assert calls == [("equity.quote.snapshot", "execution")]
    assert gate.execution_freshness_seconds == 5
    assert gate.contract_version == "2.0"
    assert gate.schema_version == "1.0"


def test_execution_gate_does_not_fall_back_to_research_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "dataset_key": "equity.quote.snapshot",
        "publication_key": "execution",
        "publication_id": PUBLICATION_ID,
        "publication_hash": PUBLICATION_HASH,
        "as_of": NOW - timedelta(seconds=1),
        "published_at": NOW - timedelta(seconds=1),
        "policy_identity": "p2:policy:hash",
        "contract_version": "2.0",
        "schema_version": "1.0",
        "contract_resolution": "current_active_not_point_in_time",
        "execution_freshness_seconds": None,
        "max_age_seconds": 14_400,
        "must_not_use_for_decision": True,
        "blocked_reason": "publication_freshness_policy_missing",
        "freshness_status": "unverified",
    }
    monkeypatch.setattr(
        execution_quote_composition,
        "get_current_publication_freshness_gate",
        lambda *_args, **_kwargs: payload,
    )

    gate = execution_quote_composition._ExecutionQuoteGateReader().get_current_gate(
        ASSET, as_of=NOW
    )

    assert gate is not None
    assert gate.execution_freshness_seconds is None
    with pytest.raises(ExecutionQuoteUnavailable) as error:
        _use_case(_quote(), gate=gate).execute(ASSET, as_of=NOW)
    assert error.value.reason is ExecutionQuoteBlockReason.POLICY_MISSING


def test_execution_fact_repository_requests_exact_execution_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[tuple[str, str]] = []

    class _PublicationRepository:
        def get_current(self, dataset_key: str, publication_key: str) -> None:
            requested.append((dataset_key, publication_key))
            return None

    monkeypatch.setattr(
        execution_quote_repository,
        "CanonicalPublicationRepository",
        _PublicationRepository,
    )

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        execution_quote_repository.DjangoExecutionQuoteRepository().get_exact_quote(
            ASSET,
            publication_gate=_gate(),
            as_of=NOW,
        )

    assert requested == [("equity.quote.snapshot", "execution")]
    assert error.value.reason is ExecutionQuoteBlockReason.PUBLICATION_MISSING


def _patch_publication_gate_inputs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    publication_key: str,
    observed_at: datetime,
    freshness_seconds: int | None,
    execution_freshness_seconds: int | None,
) -> None:
    """Provide isolated catalog and publication ports to the query gate."""

    coverage = SimpleNamespace(
        requested_count=1,
        eligible_count=1,
        selected_count=1,
        missing_count=0,
    )
    publication = SimpleNamespace(
        publication_id=PUBLICATION_ID,
        dataset_key="equity.quote.snapshot",
        publication_key=publication_key,
        publication_hash=PUBLICATION_HASH,
        as_of=NOW - timedelta(seconds=1),
        published_at=NOW - timedelta(seconds=1),
        must_not_use_for_decision=False,
        blocked_reason="",
        policy_version="p2:policy:hash",
        selected_source="tushare",
        run_id="run-1",
        coverage=coverage,
        scope_blocks=(),
    )
    repository = SimpleNamespace(
        get_current=lambda *_args: publication,
        list_members=lambda _publication_id: (),
        get_fact_content_hashes=lambda _members: {},
        get_oldest_member_observed_at=lambda _publication_id: observed_at,
    )
    contract = SimpleNamespace(
        key=DatasetKey("equity.quote.snapshot", "2.0", "1.0"),
        freshness_seconds=freshness_seconds,
        execution_freshness_seconds=execution_freshness_seconds,
    )
    active_policy = PublicationPolicy(
        dataset=contract.key,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "observed_at", "payload_hash"),
        retention_days=3650,
        policy_version="execution-query-test-v1",
    )
    monkeypatch.setattr(
        publication_read_composition,
        "consistent_publication_read",
        lambda _dataset_key: nullcontext(),
    )
    monkeypatch.setattr(query_services, "get_canonical_publication_repository", lambda: repository)
    monkeypatch.setattr(
        query_services,
        "get_publication_policy_repository",
        lambda: SimpleNamespace(get_active=lambda _dataset_key: active_policy),
    )
    monkeypatch.setattr(
        query_services,
        "get_dataset_contract_repository",
        lambda: SimpleNamespace(
            get_active=lambda _dataset_key: contract,
            get_active_for_execution=lambda _dataset_key: contract,
        ),
    )
    monkeypatch.setattr(
        query_services, "current_publication_evidence_blocked_reason", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        query_services,
        "latest_completed_cn_market_session",
        lambda _reference: observed_at.astimezone(UTC).date(),
    )


def test_execution_query_uses_only_execution_ttl_and_skips_current_session_waiver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = NOW - timedelta(seconds=10)
    _patch_publication_gate_inputs(
        monkeypatch,
        publication_key="execution",
        observed_at=observation,
        freshness_seconds=14_400,
        execution_freshness_seconds=5,
    )

    gate = query_services._publication_gate("equity.quote.snapshot", "execution", now=NOW)

    assert gate is not None
    assert gate["max_age_seconds"] == 5
    assert gate["execution_freshness_seconds"] == 5
    assert gate["contract_version"] == "2.0"
    assert gate["schema_version"] == "1.0"
    assert gate["freshness_status"] == "stale"
    assert gate["must_not_use_for_decision"] is True


def test_execution_query_blocks_missing_execution_ttl_without_using_research_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_publication_gate_inputs(
        monkeypatch,
        publication_key="execution",
        observed_at=NOW - timedelta(seconds=1),
        freshness_seconds=14_400,
        execution_freshness_seconds=None,
    )

    gate = query_services._publication_gate("equity.quote.snapshot", "execution", now=NOW)

    assert gate is not None
    assert gate["execution_freshness_seconds"] is None
    assert gate["must_not_use_for_decision"] is True
    assert gate["blocked_reason"] == "publication_freshness_policy_missing"


def test_execution_query_blocks_ambiguous_active_contract_and_preserves_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execution reads do not choose one among multiple active catalog versions."""

    _patch_publication_gate_inputs(
        monkeypatch,
        publication_key="execution",
        observed_at=NOW - timedelta(seconds=1),
        freshness_seconds=14_400,
        execution_freshness_seconds=60,
    )

    def _ambiguous(_dataset_key: str) -> None:
        raise DatasetContractAmbiguousError("multiple active contracts")

    monkeypatch.setattr(
        query_services,
        "get_dataset_contract_repository",
        lambda: SimpleNamespace(
            get_active=lambda _dataset_key: pytest.fail("research resolution must not run"),
            get_active_for_execution=_ambiguous,
        ),
    )

    gate = query_services._publication_gate("equity.quote.snapshot", "execution", now=NOW)

    assert gate is not None
    assert gate["must_not_use_for_decision"] is True
    assert gate["blocked_reason"] == "execution_catalog_contract_ambiguous"
    assert gate["freshness_status"] == "invalid"


@pytest.mark.parametrize(
    ("quote_changes", "reason"),
    [
        ({"asset_code": "000001.SZ"}, ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT),
        ({"snapshot_at": NOW + timedelta(seconds=1)}, ExecutionQuoteBlockReason.FUTURE_EVIDENCE),
        ({"fetched_at": NOW + timedelta(seconds=1)}, ExecutionQuoteBlockReason.FUTURE_EVIDENCE),
        ({"published_at": NOW + timedelta(seconds=1)}, ExecutionQuoteBlockReason.FUTURE_EVIDENCE),
        ({"freshness_deadline": NOW}, ExecutionQuoteBlockReason.STALE),
        ({"source": "qmt-bridge:binding-1"}, ExecutionQuoteBlockReason.SOURCE_UNVERIFIED),
        ({"quality_status": "unverified"}, ExecutionQuoteBlockReason.SOURCE_UNVERIFIED),
        ({"publication_hash": "c" * 64}, ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT),
        ({"snapshot_at": "not-a-datetime"}, ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT),
    ],
)
def test_execution_quote_revalidates_provider_fields(
    quote_changes: dict[str, object], reason: ExecutionQuoteBlockReason
) -> None:
    with pytest.raises(ExecutionQuoteUnavailable) as error:
        _use_case(_quote(**quote_changes)).execute(ASSET, as_of=NOW)

    assert error.value.reason is reason


def test_execution_quote_blocks_missing_and_rejected_publication_gates() -> None:
    with pytest.raises(ExecutionQuoteUnavailable) as missing:
        GetExecutionQuoteUseCase(
            gate_reader=_GateReader(None), quote_reader=_QuoteReader(_quote())
        ).execute(ASSET, as_of=NOW)
    assert missing.value.reason is ExecutionQuoteBlockReason.PUBLICATION_MISSING

    blocked_gate = _gate(
        must_not_use_for_decision=True,
        blocked_reason="publication_policy_missing",
        freshness_status="unverified",
    )
    with pytest.raises(ExecutionQuoteUnavailable) as blocked:
        _use_case(_quote(), gate=blocked_gate).execute(ASSET, as_of=NOW)
    assert blocked.value.reason is ExecutionQuoteBlockReason.POLICY_MISSING


def test_execution_quote_requires_exact_dto_type_and_gate_binding() -> None:
    with pytest.raises(ExecutionQuoteUnavailable) as wrong_type:
        _use_case({"last": "10.1234"}).execute(ASSET, as_of=NOW)
    assert wrong_type.value.reason is ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT

    with pytest.raises(ExecutionQuoteUnavailable) as wrong_publication:
        _use_case(_quote(publication_id="other-publication")).execute(ASSET, as_of=NOW)
    assert wrong_publication.value.reason is ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT

    with pytest.raises(ExecutionQuoteUnavailable) as wrong_contract:
        _use_case(_quote(contract_version="1.0")).execute(ASSET, as_of=NOW)
    assert wrong_contract.value.reason is ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT


def test_execution_quote_rejects_current_key_and_missing_execution_ttl() -> None:
    with pytest.raises(ExecutionQuoteUnavailable) as wrong_key:
        _use_case(_quote(), gate=_gate(publication_key="current")).execute(ASSET, as_of=NOW)
    assert wrong_key.value.reason is ExecutionQuoteBlockReason.PUBLICATION_BLOCKED

    with pytest.raises(ExecutionQuoteUnavailable) as missing_ttl:
        _use_case(_quote(), gate=_gate(execution_freshness_seconds=None)).execute(ASSET, as_of=NOW)
    assert missing_ttl.value.reason is ExecutionQuoteBlockReason.POLICY_MISSING


def test_execution_quote_uses_the_execution_ttl_for_its_deadline() -> None:
    gate = _gate(execution_freshness_seconds=5)
    quote = _quote(
        snapshot_at=NOW - timedelta(seconds=4),
        fetched_at=NOW - timedelta(seconds=3),
        freshness_deadline=NOW + timedelta(seconds=1),
        execution_freshness_seconds=5,
    )

    result = _use_case(quote, gate=gate).execute(ASSET, as_of=NOW)

    assert result.freshness_deadline == NOW + timedelta(seconds=1)


def test_execution_quote_rejects_historical_query_after_publication_or_ttl() -> None:
    stale_gate = _gate(execution_freshness_seconds=5, freshness_status="stale")
    with pytest.raises(ExecutionQuoteUnavailable) as stale:
        _use_case(_quote(freshness_deadline=NOW - timedelta(seconds=5)), gate=stale_gate).execute(
            ASSET, as_of=NOW
        )
    assert stale.value.reason is ExecutionQuoteBlockReason.STALE

    with pytest.raises(ExecutionQuoteUnavailable) as invalid_time:
        _use_case(_quote(queried_at=NOW - timedelta(seconds=20))).execute(ASSET, as_of=NOW)
    assert invalid_time.value.reason is ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT


def test_execution_quote_rejects_an_unrepresentable_freshness_window() -> None:
    with pytest.raises(ExecutionQuoteUnavailable) as error:
        _use_case(_quote(), gate=_gate(execution_freshness_seconds=10**20)).execute(
            ASSET, as_of=NOW
        )

    assert error.value.reason is ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT


def test_execution_quote_rejects_unrecognized_freshness_status() -> None:
    with pytest.raises(ExecutionQuoteUnavailable) as error:
        _use_case(_quote(), gate=_gate(freshness_status="unverified")).execute(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT


def test_execution_quote_reports_invalid_requests_through_project_exception() -> None:
    with pytest.raises(InvalidInputError):
        _use_case(_quote()).execute("", as_of=NOW)

    with pytest.raises(InvalidInputError):
        _use_case(_quote()).execute(ASSET, as_of=cast(datetime, "not-a-datetime"))


@pytest.mark.parametrize(
    "changes",
    [
        {"asset_code": ""},
        {"fact_content_hash": "invalid"},
        {"last": None},
        {"bid": Decimal("0")},
        {"ask": Decimal("Infinity")},
        {"previous_close": "9.9000"},
        {
            "snapshot_at": NOW,
            "fetched_at": NOW - timedelta(seconds=1),
        },
        {
            "snapshot_at": NOW - timedelta(seconds=1),
            "fetched_at": NOW - timedelta(seconds=1),
            "publication_as_of": NOW - timedelta(seconds=2),
        },
        {
            "publication_as_of": NOW,
            "published_at": NOW - timedelta(seconds=1),
        },
        {
            "snapshot_at": NOW - timedelta(seconds=3),
            "fetched_at": NOW - timedelta(seconds=1),
            "publication_as_of": NOW - timedelta(seconds=2),
            "published_at": NOW - timedelta(seconds=2),
        },
        {
            "snapshot_at": NOW,
            "fetched_at": NOW + timedelta(seconds=1),
            "publication_as_of": NOW + timedelta(seconds=1),
            "published_at": NOW + timedelta(seconds=1),
            "queried_at": NOW - timedelta(seconds=1),
        },
        {"freshness_deadline": NOW - timedelta(seconds=10)},
        {"freshness_deadline": NOW},
    ],
)
def test_domain_rejects_malformed_or_inconsistent_execution_quotes(
    changes: dict[str, object],
) -> None:
    quote = _quote(**changes)

    with pytest.raises(ValueError):
        quote.validate()

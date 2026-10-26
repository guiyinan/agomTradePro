"""Exact quote response retention stays inside its issued sync unit of work."""

from __future__ import annotations

import dataclasses
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

import pytest

from apps.audit.application.data_fetch_audit import DataFetchAuditObservation
from apps.data_center.application.dtos import SyncQuoteRequest
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.application.quote_response_capture import (
    CapturedQuoteSnapshotResponse,
    ExactQuoteRequestScope,
)
from apps.data_center.application.sync_identity import (
    SyncExecutionIdentity,
    build_sync_execution_identity,
)
from apps.data_center.application.sync_use_cases import SyncQuoteUseCase
from apps.data_center.domain.entities import (
    ProviderConfig,
    QuoteChangePctCandidate,
    QuoteSnapshot,
    RawAudit,
    raw_audit_content_hash,
)
from apps.data_center.domain.provider_response import ProviderResponseCapture
from core.exceptions import DataFetchError

_NOW = datetime(2026, 10, 26, 8, 5, tzinfo=UTC)
_RUN_ID = "11111111-1111-4111-8111-111111111111"
_INGESTED_RUN_ID = "22222222-2222-4222-8222-222222222222"
_BATCH_ID = "33333333-3333-4333-8333-333333333333"


def _identity() -> SyncExecutionIdentity:
    """Build one canonical owner-issued identity for the test UOW."""

    return build_sync_execution_identity(
        run_id=_RUN_ID,
        ingested_run_id=_INGESTED_RUN_ID,
        batch_id=_BATCH_ID,
        dataset_key="equity.quote.snapshot",
        provider_name="provider-main",
    )


def _config() -> ProviderConfig:
    """Return one complete configured provider row."""

    return ProviderConfig(
        id=19,
        name="provider-main",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )


def _response() -> CapturedQuoteSnapshotResponse:
    """Build a quote whose exact body hashes are tied to its own request scope."""

    from apps.data_center.domain.provider_response import (
        ProviderResponseTransport,
        parse_provider_response_json,
    )

    body = (
        b'{"code":0,"data":{"fields":["ts_code","trade_date","close"],'
        b'"items":[["600000.SH","20261026",10.5]]}}'
    )
    capture = ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=_NOW,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.EGRESS,
    )
    scope = ExactQuoteRequestScope(
        provider_id=19,
        provider_name="provider-main",
        dataset_key="equity.quote.snapshot",
        api_name="daily",
        asset_code="600000.SH",
        trade_date=date(2026, 10, 26),
    )
    quote = QuoteSnapshot(
        asset_code="600000.SH",
        snapshot_at=_NOW,
        fetched_at=_NOW,
        current_price=10.5,
        source="wire-source-name",
        change_pct_candidate=QuoteChangePctCandidate(
            raw_value="5.25",
            source_field="pct_chg",
            origin="vendor_reported",
            provider_source="wire-source-name",
        ),
        extra={
            "raw_payload_hash": capture.body_sha256,
            "raw_payload_scope": "batch_response_body",
            "source_record_id": f"tushare:daily:20261026:600000.SH:{capture.body_sha256[:16]}",
            "actual_source": "provider-native",
        },
    )
    return CapturedQuoteSnapshotResponse(
        request_scope=scope,
        quote=quote,
        capture=capture,
        sensitive_values=("provider-secret",),
    )


class _Provider:
    """Expose only the exact-capture capability used by this request."""

    def __init__(
        self,
        events: list[str],
        uow: _Uow,
        response: CapturedQuoteSnapshotResponse,
    ) -> None:
        self.events = events
        self.uow = uow
        self.response = response

    def provider_name(self) -> str:
        """Return the configured source identity."""

        return "provider-main"

    def fetch_quote_snapshot_with_capture(
        self, asset_code: str, target_trade_date: date
    ) -> CapturedQuoteSnapshotResponse:
        """Fetch before the UOW and return this call's own capture object."""

        assert not self.uow.active
        self.events.append("provider_fetch")
        assert asset_code == "600000.SH"
        assert target_trade_date == date(2026, 10, 26)
        return self.response


class _ProviderRepository:
    def __init__(self) -> None:
        self.config = _config()

    def get_by_id(self, _provider_id: int) -> ProviderConfig:
        return self.config

    def save(self, config: ProviderConfig) -> ProviderConfig:
        self.config = config
        return config


class _Registry:
    def __init__(self, provider: _Provider) -> None:
        self.provider = provider

    def get_by_id(self, _provider_id: int) -> _Provider:
        return self.provider

    def record_success(self, *_args: object) -> None:
        return None

    def record_failure(self, *_args: object) -> None:
        return None


class _Uow:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.active = False

    def atomic(self) -> AbstractContextManager[None]:
        owner = self

        class _Atomic(AbstractContextManager[None]):
            def __enter__(self) -> None:
                owner.active = True
                owner.events.append("begin")
                return None

            def __exit__(self, exc_type: object, _error: object, _tb: object) -> bool:
                owner.events.append("rollback" if exc_type else "commit")
                owner.active = False
                return False

        return _Atomic()


class _Issuer:
    def __init__(
        self,
        events: list[str],
        uow: _Uow,
        *,
        mutate: ProviderResponseCapture | None = None,
    ) -> None:
        self.events = events
        self.uow = uow
        self.mutate = mutate

    def issue(self, *, dataset_key: str, provider_name: str) -> SyncExecutionIdentity:
        assert self.uow.active
        assert dataset_key == "equity.quote.snapshot"
        assert provider_name == "provider-main"
        self.events.append("identity")
        if self.mutate is not None:
            payload = self.mutate.payload
            assert isinstance(payload, dict)
            payload["code"] = 1
        return _identity()


class _Facts:
    def __init__(self, events: list[str], uow: _Uow) -> None:
        self.events = events
        self.uow = uow
        self.saved: list[QuoteSnapshot] = []

    def bulk_upsert(self, quotes: list[QuoteSnapshot]) -> int:
        assert self.uow.active
        self.events.append("facts")
        self.saved.extend(quotes)
        return len(quotes)


class _RawAudit:
    def __init__(self, events: list[str], uow: _Uow) -> None:
        self.events = events
        self.uow = uow
        self.persisted: list[RawAudit] = []

    def log(self, audit: RawAudit) -> RawAudit:
        assert self.uow.active
        self.events.append("raw_audit")
        persisted = dataclasses.replace(
            audit,
            raw_audit_id="raw-quote-1",
            content_hash=raw_audit_content_hash(audit),
        )
        self.persisted.append(persisted)
        return persisted


class _Writer:
    def __init__(self, events: list[str], uow: _Uow) -> None:
        self.events = events
        self.uow = uow

    def write(self, observation: object) -> None:
        assert self.uow.active
        assert isinstance(observation, (DataFetchAuditObservation,))
        self.events.append("fetch_audit")


class _Publisher:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls = 0

    def execute(self, *_args: object, **_kwargs: object) -> object:
        self.calls += 1
        self.events.append("publish_current")
        raise RuntimeError("current publication must not run after a failed retain")


class _QualityRecorder:
    def execute(self, **_kwargs: object) -> None:
        raise AssertionError("quality recording must not run after a failed retain")


class _Clock:
    def now(self) -> datetime:
        return _NOW


class _Retainer:
    def __init__(
        self,
        events: list[str],
        uow: _Uow,
        response: CapturedQuoteSnapshotResponse,
        *,
        failure: DataFetchError | None = None,
        wrong_reference: str | None = None,
    ) -> None:
        self.events = events
        self.uow = uow
        self.response = response
        self.failure = failure
        self.wrong_reference = wrong_reference
        self.references: list[ProviderResponsePayloadReference] = []

    def execute(
        self,
        capture: ProviderResponseCapture,
        *,
        provider_name: str,
        dataset_key: str,
        api_name: str,
        request_params: dict[str, object],
        sensitive_values: tuple[str, ...],
        run_id: str,
    ) -> ProviderResponsePayloadReference:
        assert self.uow.active
        assert capture is self.response.capture
        assert provider_name == "provider-main"
        assert dataset_key == "equity.quote.snapshot"
        assert api_name == "daily"
        assert request_params == self.response.request_scope.request_params()
        assert sensitive_values == ("provider-secret",)
        assert run_id == _RUN_ID
        self.events.append("retain")
        if self.failure is not None:
            raise self.failure
        payload_hash = "sha256:" + "a" * 64
        reference = ProviderResponsePayloadReference(
            payload_id=str(uuid5(NAMESPACE_URL, payload_hash)),
            payload_hash=payload_hash,
            record_digest="sha256:" + "b" * 64,
            body_sha256=capture.body_sha256,
            retained_content_sha256="c" * 64,
            original_body_retained=False,
            retained_content_encoding="redacted_canonical_json",
            body_size_bytes=capture.body_size_bytes,
            response_completed_at=capture.response_completed_at,
            provider_name=provider_name,
            dataset_key=dataset_key,
            transport=capture.transport,
            run_id=run_id,
        )
        if self.wrong_reference == "run_id":
            reference = dataclasses.replace(reference, run_id=_INGESTED_RUN_ID)
        elif self.wrong_reference == "provider_name":
            reference = dataclasses.replace(reference, provider_name="provider-other")
        elif self.wrong_reference == "body_sha256":
            reference = dataclasses.replace(reference, body_sha256="d" * 64)
        self.references.append(reference)
        return reference


def _build_use_case(
    *,
    mutate_after_identity: bool = False,
    retainer_failure: DataFetchError | None = None,
    wrong_reference: str | None = None,
    include_publication: bool = False,
) -> tuple[SyncQuoteUseCase, dict[str, object]]:
    response = _response()
    events: list[str] = []
    uow = _Uow(events)
    provider = _Provider(events, uow, response)
    facts = _Facts(events, uow)
    raw_audit = _RawAudit(events, uow)
    writer = _Writer(events, uow)
    issuer = _Issuer(
        events,
        uow,
        mutate=response.capture if mutate_after_identity else None,
    )
    retainer = _Retainer(
        events,
        uow,
        response,
        failure=retainer_failure,
        wrong_reference=wrong_reference,
    )
    publisher = _Publisher(events) if include_publication else None
    use_case = SyncQuoteUseCase(
        provider_repo=_ProviderRepository(),
        provider_registry=_Registry(provider),
        fact_repo=facts,
        raw_audit_repo=raw_audit,
        publication_publisher=publisher,
        sync_identity_issuer=issuer,
        sync_unit_of_work=uow,
        data_fetch_audit_writer=writer,
        data_publication_audit_writer=writer,
        publication_quality_recorder=(_QualityRecorder() if include_publication else None),
        clock=_Clock(),
        provider_response_payload_retainer=retainer,
    )
    return use_case, {
        "events": events,
        "uow": uow,
        "facts": facts,
        "raw_audit": raw_audit,
        "retainer": retainer,
        "response": response,
        "publisher": publisher,
    }


def test_exact_quote_retention_uses_issued_run_inside_short_uow() -> None:
    """Fetch is outside SQL; identity, retained bytes, facts and audit share one UOW."""

    use_case, state = _build_use_case()

    result = use_case.execute(
        SyncQuoteRequest(
            provider_id=19,
            asset_codes=["600000.SH"],
            require_exact_asset_codes=True,
            target_trade_date=date(2026, 10, 26),
        )
    )

    events = state["events"]
    assert isinstance(events, list)
    assert events.index("provider_fetch") < events.index("begin")
    assert events.index("identity") < events.index("retain") < events.index("facts")
    assert events[-1] == "commit"
    facts = state["facts"]
    assert isinstance(facts, _Facts)
    assert len(facts.saved) == 1
    assert state["response"].quote.source == "wire-source-name"
    assert state["response"].quote.change_pct_candidate is not None
    assert facts.saved[0].change_pct_candidate is None
    assert facts.saved[0].change_pct is None
    extra = facts.saved[0].extra
    assert facts.saved[0].source == "tushare"
    assert extra["source_type"] == "tushare"
    assert extra["provider_name"] == "provider-main"
    assert extra["actual_source"] == "provider-native"
    reference = extra["provider_response_payload_reference"]
    assert isinstance(reference, dict)
    assert reference["run_id"] == _RUN_ID
    assert reference["body_sha256"] == state["response"].capture.body_sha256
    assert "provider-secret" not in str(extra)
    assert state["retainer"].references[0].run_id == result.run_id
    raw_audit = state["raw_audit"]
    assert isinstance(raw_audit, _RawAudit)
    assert len(raw_audit.persisted) == 1
    raw_reference = raw_audit.persisted[0].exact_reference()
    assert raw_reference.run_id == result.run_id
    assert raw_audit.persisted[0].response_payload_hash == reference["payload_hash"]
    assert raw_audit.persisted[0].response_payload_hash.startswith("sha256:")
    assert raw_audit.persisted[0].response_payload_hash != reference["body_sha256"]
    assert raw_audit.persisted[0].content_hash == raw_audit_content_hash(raw_audit.persisted[0])
    assert raw_audit.persisted[0].payload_size_bytes == 0


def test_exact_quote_capture_payload_is_rechecked_after_identity_before_retention() -> None:
    """A mutable parsed payload cannot change after preflight and enter the UOW."""

    use_case, state = _build_use_case(mutate_after_identity=True)

    with pytest.raises(DataFetchError) as error:
        use_case.execute(
            SyncQuoteRequest(
                provider_id=19,
                asset_codes=["600000.SH"],
                require_exact_asset_codes=True,
                target_trade_date=date(2026, 10, 26),
            )
        )

    assert error.value.code == "CURRENT_QUOTE_RESPONSE_SCOPE_MISMATCH"
    assert state["events"][-1] == "rollback"
    facts = state["facts"]
    assert isinstance(facts, _Facts)
    assert facts.saved == []
    retainer = state["retainer"]
    assert isinstance(retainer, _Retainer)
    assert retainer.references == []


@pytest.mark.parametrize("wrong_reference", ["run_id", "provider_name", "body_sha256"])
def test_invalid_retained_quote_reference_rolls_back_without_current_publication(
    wrong_reference: str,
) -> None:
    """Mismatched RawPayload references cannot promote facts or current state."""

    use_case, state = _build_use_case(
        wrong_reference=wrong_reference,
        include_publication=True,
    )

    with pytest.raises(DataFetchError) as error:
        use_case.execute(
            SyncQuoteRequest(
                provider_id=19,
                asset_codes=["600000.SH"],
                require_exact_asset_codes=True,
                target_trade_date=date(2026, 10, 26),
            )
        )

    assert error.value.code == "CURRENT_QUOTE_RESPONSE_REFERENCE_MISMATCH"
    assert state["events"][-1] == "rollback"
    assert "facts" not in state["events"]
    assert "raw_audit" not in state["events"]
    assert "publish_current" not in state["events"]
    facts = state["facts"]
    assert isinstance(facts, _Facts)
    assert facts.saved == []
    publisher = state["publisher"]
    assert isinstance(publisher, _Publisher)
    assert publisher.calls == 0


def test_quote_retainer_failure_rolls_back_before_facts_or_current_publication() -> None:
    """A failed RawPayload write cannot leave a fact or publish a current pointer."""

    use_case, state = _build_use_case(
        retainer_failure=DataFetchError(
            "RawPayload write failed", code="PROVIDER_RESPONSE_PAYLOAD_SAVE_FAILED"
        ),
        include_publication=True,
    )

    with pytest.raises(DataFetchError) as error:
        use_case.execute(
            SyncQuoteRequest(
                provider_id=19,
                asset_codes=["600000.SH"],
                require_exact_asset_codes=True,
                target_trade_date=date(2026, 10, 26),
            )
        )

    assert error.value.code == "PROVIDER_RESPONSE_PAYLOAD_SAVE_FAILED"
    assert state["events"][-1] == "rollback"
    assert "retain" in state["events"]
    assert "facts" not in state["events"]
    assert "raw_audit" not in state["events"]
    assert "publish_current" not in state["events"]
    facts = state["facts"]
    assert isinstance(facts, _Facts)
    assert facts.saved == []
    publisher = state["publisher"]
    assert isinstance(publisher, _Publisher)
    assert publisher.calls == 0


class _SessionProvider:
    def __init__(self, events: list[str], uow: _Uow) -> None:
        self.events = events
        self.uow = uow

    def provider_name(self) -> str:
        return "provider-main"

    def fetch_quote_snapshots_for_session(
        self, asset_codes: list[str], target_trade_date: date
    ) -> list[QuoteSnapshot]:
        assert not self.uow.active
        assert asset_codes == ["600000.SH", "000001.SZ"]
        assert target_trade_date == date(2026, 10, 26)
        self.events.append("session_fetch")
        return [
            QuoteSnapshot(
                asset_code=asset_code,
                snapshot_at=_NOW,
                fetched_at=_NOW,
                current_price=10.5,
                source="session-native",
            )
            for asset_code in asset_codes
        ]


def test_session_quote_batch_keeps_legacy_path_without_response_retention() -> None:
    """Multi-asset session sync still uses its batch provider, not exact capture."""

    events: list[str] = []
    uow = _Uow(events)
    provider = _SessionProvider(events, uow)
    facts = _Facts(events, uow)
    raw_audit = _RawAudit(events, uow)
    writer = _Writer(events, uow)
    retainer = _Retainer(events, uow, _response())
    use_case = SyncQuoteUseCase(
        provider_repo=_ProviderRepository(),
        provider_registry=_Registry(provider),
        fact_repo=facts,
        raw_audit_repo=raw_audit,
        sync_identity_issuer=_Issuer(events, uow),
        sync_unit_of_work=uow,
        data_fetch_audit_writer=writer,
        data_publication_audit_writer=writer,
        clock=_Clock(),
        provider_response_payload_retainer=retainer,
    )

    result = use_case.execute(
        SyncQuoteRequest(
            provider_id=19,
            asset_codes=["600000.SH", "000001.SZ"],
            require_exact_asset_codes=True,
            target_trade_date=date(2026, 10, 26),
        )
    )

    assert events.index("session_fetch") < events.index("begin")
    assert events[-1] == "commit"
    assert result.stored_count == 2
    assert [quote.asset_code for quote in facts.saved] == ["600000.SH", "000001.SZ"]
    assert all(quote.source == "tushare" for quote in facts.saved)
    assert all("provider_response_payload_reference" not in quote.extra for quote in facts.saved)
    assert retainer.references == []
    assert raw_audit.persisted[0].response_payload_hash == ""

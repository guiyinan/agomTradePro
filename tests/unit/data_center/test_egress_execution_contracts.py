"""Real application orchestration for bounded provider reads and redacted audit."""

from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from apps.data_center.application import egress_service as service
from apps.data_center.application.egress_service import (
    FinancialResponseAttemptBudget,
    FinancialResponseRequestFailed,
)
from apps.data_center.domain.egress_routing import (
    EgressRequestContext,
    EgressRouteRule,
    EgressStrategy,
    target_hostname,
)
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseScope,
)
from apps.data_center.domain.provider_document_response import ProviderDocumentResponseCapture
from apps.data_center.domain.provider_response import ProviderResponseTransport
from core.exceptions import DataFetchError


@pytest.fixture
def routed(monkeypatch):
    rule = EgressRouteRule(
        rule_id=7,
        provider_id=3,
        dataset_key="equity.price.bar",
        domain_pattern="data.example.com",
        deployment_region="overseas",
        strategy=EgressStrategy.DIRECT_FALLBACK,
        fixed_egress_id=9,
        priority=10,
        enabled=True,
    )
    repository = Mock()
    repository.list.return_value = (rule,)
    transport = Mock()
    audit = Mock()
    monkeypatch.setattr(service, "_rule_repository", repository)
    monkeypatch.setattr(service, "_transport", transport)
    monkeypatch.setattr(service, "_audit_writer", audit)
    context = EgressRequestContext(
        provider_id=3,
        dataset_key="equity.price.bar",
        target_url="https://data.example.com/daily?token=private-token",
        deployment_region="overseas",
    )
    return context, transport, audit


def _document_capture_for(
    context: EgressRequestContext,
    *,
    request_id,
    attempt: int,
    egress_id: int | None,
    **overrides: object,
) -> ProviderDocumentResponseCapture:
    """Build a raw capture bound to the exact request attempt and URL."""

    body = overrides.pop("body", b"<html>raw law bytes\xff</html>")
    assert isinstance(body, bytes)
    values: dict[str, object] = {
        "request_id": request_id,
        "attempt": attempt,
        "egress_id": egress_id,
        "target_url_sha256": sha256(context.target_url.encode("utf-8")).hexdigest(),
        "target_host": target_hostname(context.target_url),
        "body": body,
        "body_sha256": sha256(body).hexdigest(),
        "body_size_bytes": len(body),
        "response_completed_at": service.datetime.now(service.UTC),
        "status_code": 200,
        "content_type": "text/html; charset=utf-8",
        "transport": ProviderResponseTransport.EGRESS,
    }
    values.update(overrides)
    return ProviderDocumentResponseCapture(**values)  # type: ignore[arg-type]


def test_network_failure_uses_one_backup_with_shared_request_id(routed):
    context, transport, audit = routed
    transport.request_payload.side_effect = [
        (
            service.EgressTransportResult(
                outcome="failed", error_code="EGRESS_TIMEOUT", retryable=True
            ),
            None,
        ),
        (service.EgressTransportResult(outcome="success", status_code=200), {"rows": [1]}),
    ]
    assert service.execute_provider_request(context) == {"rows": [1]}
    calls = transport.request_payload.call_args_list
    assert [call.kwargs["egress_id"] for call in calls] == [None, 9]
    assert [call.kwargs["attempt"] for call in calls] == [1, 2]
    assert calls[0].kwargs["request_id"] == calls[1].kwargs["request_id"]
    assert audit.record.call_count == 2
    assert "private-token" not in str(audit.record.call_args_list)


@pytest.mark.parametrize(
    "error", ["EGRESS_HTTP_401", "EGRESS_HTTP_403", "EGRESS_HTTP_429", "EGRESS_TLS_ERROR"]
)
def test_nonretryable_failure_never_rotates_exit(routed, error):
    context, transport, audit = routed
    transport.request_payload.return_value = (
        service.EgressTransportResult(outcome="failed", error_code=error),
        None,
    )
    with pytest.raises(DataFetchError):
        service.execute_provider_request(context)
    assert transport.request_payload.call_count == 1
    assert audit.record.call_count == 1


def test_total_budget_stops_before_backup(routed):
    context, transport, audit = routed
    transport.request_payload.return_value = (
        service.EgressTransportResult(
            outcome="failed", error_code="EGRESS_TIMEOUT", retryable=True
        ),
        None,
    )
    with pytest.raises(DataFetchError):
        service.execute_provider_request(context, max_attempts=1)
    assert transport.request_payload.call_count == 1
    assert audit.record.call_count == 1


def test_raw_document_executor_retries_and_audits_each_bound_request_attempt(
    routed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Raw documents use governed route candidates and one logical request ID."""

    context, transport, audit = routed
    request_id = uuid4()
    monkeypatch.setattr(service, "uuid4", lambda: request_id)
    first_capture = _document_capture_for(context, request_id=request_id, attempt=1, egress_id=None)
    second_capture = _document_capture_for(context, request_id=request_id, attempt=2, egress_id=9)
    transport.request_provider_document_response.side_effect = [
        (
            service.EgressTransportResult(
                outcome="failed", error_code="EGRESS_TIMEOUT", retryable=True
            ),
            None,
        ),
        (service.EgressTransportResult(outcome="success", status_code=200), second_capture),
    ]

    capture = service.execute_provider_document_request(
        context,
        max_bytes=128,
        allowed_media_types=frozenset({"text/html"}),
    )

    calls = transport.request_provider_document_response.call_args_list
    assert capture is second_capture
    assert [call.kwargs["egress_id"] for call in calls] == [None, 9]
    assert [call.kwargs["attempt"] for call in calls] == [1, 2]
    assert calls[0].kwargs["request_id"] == calls[1].kwargs["request_id"]
    assert [call.kwargs["outcome"] for call in audit.record.call_args_list] == [
        "failed",
        "success",
    ]
    assert "private-token" not in str(audit.record.call_args_list)
    assert first_capture.request_id == request_id


@pytest.mark.parametrize(
    ("overrides", "max_bytes"),
    [
        ({"request_id": uuid4()}, 128),
        ({"attempt": 2}, 128),
        ({"egress_id": 9}, 128),
        ({"target_url_sha256": "0" * 64}, 128),
        ({"target_host": "other.example.com"}, 128),
        ({"content_type": "application/pdf"}, 128),
        ({"transport": ProviderResponseTransport.DIRECT}, 128),
        ({"status_code": 201}, 128),
        ({"body": b"x" * 256}, 128),
    ],
    ids=[
        "request",
        "attempt",
        "egress",
        "url",
        "host",
        "mime",
        "transport",
        "status",
        "size",
    ],
)
def test_raw_document_executor_rejects_capture_not_bound_to_request(
    routed,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
    max_bytes: int,
) -> None:
    """A success result cannot return bytes from another route or request."""

    context, transport, audit = routed
    request_id = uuid4()
    monkeypatch.setattr(service, "uuid4", lambda: request_id)

    def response_for_request(
        request_context: EgressRequestContext, **kwargs: object
    ) -> tuple[service.EgressTransportResult, ProviderDocumentResponseCapture]:
        capture_fields: dict[str, object] = {
            "request_id": request_id,
            "attempt": kwargs["attempt"],
            "egress_id": kwargs["egress_id"],
        }
        capture_fields.update(overrides)
        return (
            service.EgressTransportResult(outcome="success", status_code=200),
            _document_capture_for(request_context, **capture_fields),
        )

    transport.request_provider_document_response.side_effect = response_for_request

    with pytest.raises(DataFetchError) as caught:
        service.execute_provider_document_request(
            context,
            max_bytes=max_bytes,
            allowed_media_types=frozenset({"text/html"}),
        )

    assert caught.value.code == "EGRESS_DOCUMENT_CAPTURE_BINDING_FAILED"
    assert audit.record.call_count == 1
    assert audit.record.call_args.kwargs["outcome"] == "failed"
    assert transport.request_provider_document_response.call_count == 1


def test_raw_document_executor_fails_closed_without_optional_transport_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transport without raw-byte support never falls back to decoded JSON."""

    audit = Mock()
    monkeypatch.setattr(service, "_transport", object())
    monkeypatch.setattr(service, "_audit_writer", audit)
    monkeypatch.setattr(service, "_rule_repository", Mock())
    context = EgressRequestContext(
        provider_id=3,
        dataset_key="equity.price.bar",
        target_url="https://data.example.com/daily",
        deployment_region="overseas",
    )

    with pytest.raises(DataFetchError) as caught:
        service.execute_provider_document_request(
            context,
            max_bytes=128,
            allowed_media_types=frozenset({"text/html"}),
        )

    assert caught.value.code == "EGRESS_DOCUMENT_TRANSPORT_UNAVAILABLE"
    audit.record.assert_not_called()


def test_capacity_financial_capture_does_not_retry_a_second_route_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The capacity capture budget of one route attempt survives a retryable failure."""

    rule = EgressRouteRule(
        rule_id=8,
        provider_id=17,
        dataset_key="equity.financial.fact",
        domain_pattern="data.example.com",
        deployment_region="test-region",
        strategy=EgressStrategy.DIRECT_FALLBACK,
        fixed_egress_id=9,
        priority=1,
        enabled=True,
    )
    repository = Mock()
    repository.list.return_value = (rule,)
    transport = Mock()
    transport.request_financial_response.return_value = (
        service.EgressTransportResult(
            outcome="failed",
            error_code="EGRESS_TIMEOUT",
            retryable=True,
        ),
        None,
    )
    audit = Mock()
    monkeypatch.setattr(service, "_rule_repository", repository)
    monkeypatch.setattr(service, "_transport", transport)
    monkeypatch.setattr(service, "_audit_writer", audit)
    context = EgressRequestContext(
        provider_id=17,
        dataset_key="equity.financial.fact",
        target_url="https://data.example.com/financial",
        deployment_region="test-region",
    )

    with pytest.raises(DataFetchError):
        service.execute_financial_response_request(
            context,
            request_id=uuid4(),
            method="GET",
            params={"filter": "bounded"},
            json_body=None,
            headers=None,
            request_scope=FinancialRequestScope(
                provider_name="akshare",
                dataset_key="equity.financial.fact",
                asset_code="000001.SZ",
                period_limit=200,
            ),
            response_scope=FinancialResponseScope(
                asset_codes=("000001.SZ",),
                period_ends=(),
                row_count=0,
            ),
            max_attempts=1,
        )

    calls = transport.request_financial_response.call_args_list
    assert len(calls) == 1
    assert calls[0].kwargs["egress_id"] is None
    assert calls[0].kwargs["attempt"] == 1
    assert audit.record.call_count == 1


def test_financial_response_retries_validation_on_same_persisted_direct_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A direct rule gets one bounded retry when captured provider content is transiently invalid."""

    rule = EgressRouteRule(
        rule_id=8,
        provider_id=17,
        dataset_key="equity.financial.fact",
        domain_pattern="data.example.com",
        deployment_region="test-region",
        strategy=EgressStrategy.DIRECT,
        fixed_egress_id=None,
        priority=1,
        enabled=True,
    )
    repository = Mock()
    repository.list.return_value = (rule,)
    transport = Mock()
    transport.request_financial_response.side_effect = [
        (
            service.EgressTransportResult(outcome="success", status_code=200),
            SimpleNamespace(payload={}, evidence=Mock(), raw_body=b"invalid"),
        ),
        (
            service.EgressTransportResult(outcome="success", status_code=200),
            SimpleNamespace(payload={}, evidence=Mock(), raw_body=b"valid"),
        ),
    ]
    audit = Mock()
    monkeypatch.setattr(service, "_rule_repository", repository)
    monkeypatch.setattr(service, "_transport", transport)
    monkeypatch.setattr(service, "_audit_writer", audit)
    context = EgressRequestContext(
        provider_id=17,
        dataset_key="equity.financial.fact",
        target_url="https://data.example.com/financial",
        deployment_region="test-region",
    )
    request_id = uuid4()

    result = service.execute_financial_response_request(
        context,
        request_id=request_id,
        method="GET",
        params={"filter": "bounded"},
        json_body=None,
        headers=None,
        request_scope=FinancialRequestScope(
            provider_name="akshare",
            dataset_key="equity.financial.fact",
            asset_code="000001.SZ",
            period_limit=200,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=("000001.SZ",),
            period_ends=(),
            row_count=0,
        ),
        max_attempts=2,
        validator=lambda body: service.FinancialResponseValidationResult(
            accepted=body == b"valid",
            retryable=True,
        ),
    )

    calls = transport.request_financial_response.call_args_list
    assert result.raw_body == b"valid"
    assert result.physical_request_attempts == 2
    assert [call.kwargs["egress_id"] for call in calls] == [None, None]
    assert [call.kwargs["attempt"] for call in calls] == [1, 2]
    assert [call.kwargs["request_id"] for call in calls] == [request_id, request_id]
    assert [call.kwargs["outcome"] for call in audit.record.call_args_list] == [
        "failed",
        "success",
    ]


def test_financial_response_reserves_before_send_and_enforces_shared_physical_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shared physical budget stops a later route attempt before transport."""

    rule = EgressRouteRule(
        rule_id=8,
        provider_id=17,
        dataset_key="equity.financial.fact",
        domain_pattern="data.example.com",
        deployment_region="test-region",
        strategy=EgressStrategy.DIRECT_FALLBACK,
        fixed_egress_id=9,
        priority=1,
        enabled=True,
    )
    repository = Mock()
    repository.list.return_value = (rule,)
    transport = Mock()
    transport.request_financial_response.return_value = (
        service.EgressTransportResult(
            outcome="failed",
            error_code="EGRESS_TIMEOUT",
            retryable=True,
        ),
        None,
    )
    audit = Mock()
    monkeypatch.setattr(service, "_rule_repository", repository)
    monkeypatch.setattr(service, "_transport", transport)
    monkeypatch.setattr(service, "_audit_writer", audit)
    context = EgressRequestContext(
        provider_id=17,
        dataset_key="equity.financial.fact",
        target_url="https://data.example.com/financial",
        deployment_region="test-region",
    )
    budget = FinancialResponseAttemptBudget(maximum_attempts=4)

    for _ in range(2):
        with pytest.raises(FinancialResponseRequestFailed) as caught:
            service.execute_financial_response_request(
                context,
                request_id=uuid4(),
                method="GET",
                params={"filter": "bounded"},
                json_body=None,
                headers=None,
                request_scope=FinancialRequestScope(
                    provider_name="akshare",
                    dataset_key="equity.financial.fact",
                    asset_code="000001.SZ",
                    period_limit=200,
                ),
                response_scope=FinancialResponseScope(
                    asset_codes=("000001.SZ",),
                    period_ends=(),
                    row_count=0,
                ),
                max_attempts=2,
                attempt_budget=budget,
            )
        assert caught.value.observed_attempts == 2

    with pytest.raises(FinancialResponseRequestFailed) as exhausted:
        service.execute_financial_response_request(
            context,
            request_id=uuid4(),
            method="GET",
            params={"filter": "bounded"},
            json_body=None,
            headers=None,
            request_scope=FinancialRequestScope(
                provider_name="akshare",
                dataset_key="equity.financial.fact",
                asset_code="000001.SZ",
                period_limit=200,
            ),
            response_scope=FinancialResponseScope(
                asset_codes=("000001.SZ",),
                period_ends=(),
                row_count=0,
            ),
            max_attempts=2,
            attempt_budget=budget,
        )

    assert exhausted.value.code == "FINANCIAL_PROVIDER_REQUEST_HARD_LIMIT_EXCEEDED"
    assert exhausted.value.observed_attempts == 0
    assert budget.reserved_attempts == 4
    assert transport.request_financial_response.call_count == 4
    assert audit.record.call_count == 4

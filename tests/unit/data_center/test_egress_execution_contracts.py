"""Real application orchestration for bounded provider reads and redacted audit."""

from unittest.mock import Mock

import pytest

from apps.data_center.application import egress_service as service
from apps.data_center.domain.egress_routing import (
    EgressRequestContext,
    EgressRouteRule,
    EgressStrategy,
)
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

"""Transport and response contracts for simulated fee-correction SDK calls."""

from __future__ import annotations

import re
from dataclasses import is_dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, cast
from unittest.mock import Mock

import pytest
import requests

import agomtradepro.exceptions as sdk_exceptions
from agomtradepro import AgomTradeProClient
from agomtradepro.exceptions import (
    AgomTradeProAPIError,
    AuthenticationError,
    ConflictError,
    ServerError,
    ValidationError,
)
from agomtradepro.transport import use_request_transport

_BASE_URL = "https://fixture.example.test"
_CSV_TEXT = "成交编号,佣金\r\nT-1,9.00\r\n"
_KEY = "fee-correction-operation-7"
_LOCATOR = "fc454ffb-b073-4c70-90ad-b52ccdf70a3e"
_HASH_A = "a" * 64
_HASH_B = "b" * 64


class _RecordingTransport:
    """Record each request and return one configured response or exception."""

    def __init__(self, outcome: Mock | BaseException) -> None:
        self.calls: list[dict[str, Any]] = []
        self.outcome = outcome

    def request(self, **kwargs: Any) -> Mock:
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _SequencedTransport:
    """Return one explicit response for each intentional SDK operation."""

    def __init__(self, outcomes: list[Mock | BaseException]) -> None:
        self.calls: list[dict[str, Any]] = []
        self.outcomes = outcomes

    def request(self, **kwargs: Any) -> Mock:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _response(status_code: int, payload: object) -> Mock:
    """Create the minimal requests response consumed by the SDK client."""

    return Mock(status_code=status_code, json=Mock(return_value=payload))


def _invalid_json_response(status_code: int = 200) -> Mock:
    """Create a response whose body cannot be decoded as JSON."""

    return Mock(status_code=status_code, json=Mock(side_effect=ValueError("invalid JSON")))


def _policy_response(
    *,
    account_id: int = 7,
    version: int = 3,
    valid_from: str | None = "2026-10-27T09:00:00+08:00",
    valid_until: str | None = None,
) -> dict[str, Any]:
    """Build one complete owner policy response with explicit assurance metadata."""

    return {
        "success": True,
        "policy": {
            "account_id": account_id,
            "version": version,
            "enabled": True,
            "allow_operator_attested_upload": True,
            "ledger_currency": "CNY",
            "valid_from": valid_from,
            "valid_until": valid_until,
            "updated_by_id": 21,
            "assurance_class": "operator_attested_upload",
            "assurance_notice": "操作者声明材料不代表券商认证。",
        },
    }


def _receipt(
    *,
    account_id: int = 7,
    trade_id: int = 19,
    event_id: int = 31,
    revision: int = 1,
    payload_hash: str = _HASH_A,
    replayed: bool = False,
) -> dict[str, Any]:
    """Build the public fee-correction receipt DTO payload."""

    return {
        "event_id": event_id,
        "account_id": account_id,
        "trade_id": trade_id,
        "revision": revision,
        "payload_hash": payload_hash,
        "replayed": replayed,
    }


def _head_response(
    *,
    account_id: int = 7,
    trade_id: int = 19,
    receipt: dict[str, Any] | None = None,
    as_of: str = "2026-10-27T01:02:03+00:00",
) -> dict[str, Any]:
    """Build a validated head envelope, optionally including exact-key readback."""

    return {
        "success": True,
        "head": {
            "account_id": account_id,
            "trade_id": trade_id,
            "revision": 1 if receipt is not None else 0,
            "expected_predecessor_id": receipt["event_id"] if receipt is not None else None,
            "as_of": as_of,
            "request_receipt": receipt,
        },
    }


def _upload_response(
    *,
    source_locator: str = _LOCATOR,
    content_sha256: str | None = None,
    payload_sha256: str = _HASH_B,
    stored_at: str = "2026-10-27T01:02:03+00:00",
) -> dict[str, Any]:
    """Build the exact API upload receipt; it deliberately contains no request identity."""

    return {
        "success": True,
        "evidence": {
            "source_locator": source_locator,
            "content_sha256": content_sha256 or sha256(_CSV_TEXT.encode("utf-8")).hexdigest(),
            "payload_sha256": payload_sha256,
            "assurance_class": "operator_attested_upload",
            "stored_at": stored_at,
        },
        "assurance_notice": "操作者声明材料不代表券商认证。",
    }


def _apply_response(**receipt_fields: object) -> dict[str, Any]:
    """Build a successful exact correction receipt envelope."""

    return {"success": True, "receipt": _receipt(**receipt_fields)}


def _new_client() -> AgomTradeProClient:
    """Create a deterministic client whose only transport is test-injected."""

    return AgomTradeProClient(base_url=_BASE_URL, api_token="sdk-fixture-token")


def _fee_corrections(client: AgomTradeProClient) -> Any:
    """Require the documented fee-correction facade without making a request."""

    module = getattr(client.simulated_trading, "fee_corrections", None)
    assert module is not None, "simulated_trading.fee_corrections must be exposed"
    return module


def _policy_input() -> dict[str, object]:
    """Return one complete consent command accepted by the owner policy endpoint."""

    return {
        "account_id": 7,
        "expected_version": 2,
        "enabled": True,
        "allow_operator_attested_upload": True,
        "ledger_currency": "CNY",
        "valid_from": "2026-10-27T09:00:00+08:00",
        "valid_until": None,
        "attestation_acknowledged": True,
    }


def _upload_input(**changes: object) -> dict[str, object]:
    """Return one exact UTF-8 evidence request, optionally with a malformed field."""

    value: dict[str, object] = {
        "account_id": 7,
        "trade_id": 19,
        "idempotency_key": _KEY,
        "expected_revision": 0,
        "expected_predecessor_id": None,
        "original_filename": "broker-fees.csv",
        "csv_text": _CSV_TEXT,
        "attestation_acknowledged": True,
    }
    value.update(changes)
    return value


def _apply_input(**changes: object) -> dict[str, object]:
    """Return one exact revision-bound apply request, optionally malformed."""

    value: dict[str, object] = {
        "account_id": 7,
        "trade_id": 19,
        "idempotency_key": _KEY,
        "source_locator": _LOCATOR,
        "expected_revision": 0,
    }
    value.update(changes)
    return value


def _invoke_write(module: Any, operation: str) -> object:
    """Run one explicitly requested SDK write using the shared test identity."""

    if operation == "set_policy":
        values = _policy_input()
        return module.set_policy(
            values.pop("account_id"),
            **values,
        )
    if operation == "upload_evidence":
        values = _upload_input()
        account_id = values.pop("account_id")
        trade_id = values.pop("trade_id")
        return module.upload_evidence(account_id, trade_id, **values)
    if operation == "apply":
        values = _apply_input()
        account_id = values.pop("account_id")
        trade_id = values.pop("trade_id")
        return module.apply(account_id, trade_id, **values)
    raise AssertionError(f"Unsupported write operation: {operation}")


def _assert_frozen_dto(value: object, expected_name: str | None = None) -> None:
    """Require a frozen dataclass result rather than a raw response dictionary."""

    assert is_dataclass(value)
    parameters = getattr(type(value), "__dataclass_params__", None)
    assert parameters is not None and parameters.frozen is True
    if expected_name is not None:
        assert type(value).__name__ == expected_name


def _assert_aware_datetime(value: object) -> None:
    """Require parsed SDK timestamps to retain an explicit UTC offset."""

    assert isinstance(value, datetime)
    assert value.tzinfo is not None
    assert value.utcoffset() is not None


def _assert_unknown_write(error: AgomTradeProAPIError) -> None:
    """Require the dedicated safe unknown-outcome type and recovery flags."""

    assert type(error).__name__ == "FeeCorrectionOutcomeUnknownError"
    assert isinstance(error, sdk_exceptions.AgomTradeProAPIError)
    assert getattr(error, "effects_indeterminate", False) is True
    assert getattr(error, "recovery_required", False) is True


def test_fee_corrections_facade_is_exposed_under_simulated_trading() -> None:
    client = _new_client()
    module = _fee_corrections(client)

    assert callable(module.get_policy)
    assert callable(module.set_policy)
    assert callable(module.get_head)
    assert callable(module.upload_evidence)
    assert callable(module.apply)


def test_get_policy_uses_owner_route_and_returns_frozen_aware_policy_dto() -> None:
    transport = _RecordingTransport(_response(200, _policy_response()))
    client = _new_client()

    with use_request_transport(transport):
        policy = _fee_corrections(client).get_policy(7)

    _assert_frozen_dto(policy, "FeeCorrectionPolicy")
    assert policy.account_id == 7
    assert policy.version == 3
    assert policy.enabled is True
    assert policy.allow_operator_attested_upload is True
    assert policy.ledger_currency == "CNY"
    _assert_aware_datetime(policy.valid_from)
    assert policy.valid_until is None
    assert policy.updated_by_id == 21
    assert policy.assurance_class == "operator_attested_upload"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == f"{_BASE_URL}/api/simulated-trading/accounts/7/fee-correction-policy/"


def test_set_policy_sends_only_explicit_versioned_owner_settings() -> None:
    transport = _RecordingTransport(_response(200, _policy_response(version=3)))
    client = _new_client()
    values = _policy_input()

    with use_request_transport(transport):
        policy = _fee_corrections(client).set_policy(
            values.pop("account_id"),
            **values,
        )

    _assert_frozen_dto(policy, "FeeCorrectionPolicy")
    call = transport.calls[0]
    assert len(transport.calls) == 1
    assert call["method"] == "PUT"
    assert call["url"] == f"{_BASE_URL}/api/simulated-trading/accounts/7/fee-correction-policy/"
    assert call["json"] == {
        "expected_version": 2,
        "enabled": True,
        "allow_operator_attested_upload": True,
        "ledger_currency": "CNY",
        "valid_from": "2026-10-27T09:00:00+08:00",
        "valid_until": None,
        "attestation_acknowledged": True,
    }
    assert "Idempotency-Key" not in call["headers"]


def test_get_head_forwards_optional_idempotency_key_and_parses_exact_receipt() -> None:
    payload = _head_response(receipt=_receipt(replayed=True))
    transport = _RecordingTransport(_response(200, payload))
    client = _new_client()

    with use_request_transport(transport):
        head = _fee_corrections(client).get_head(7, 19, idempotency_key=_KEY)

    _assert_frozen_dto(head, "FeeCorrectionHead")
    assert head.account_id == 7
    assert head.trade_id == 19
    assert head.revision == 1
    assert head.expected_predecessor_id == 31
    _assert_aware_datetime(head.as_of)
    _assert_frozen_dto(head.request_receipt, "FeeCorrectionReceipt")
    assert head.request_receipt.event_id == 31
    assert head.request_receipt.replayed is True
    call = transport.calls[0]
    assert len(transport.calls) == 1
    assert call["method"] == "GET"
    assert call["url"] == (
        f"{_BASE_URL}/api/simulated-trading/accounts/7/trades/19/fee-corrections/head/"
    )
    assert call["headers"]["Idempotency-Key"] == _KEY


def test_get_head_without_key_keeps_nullable_receipt_and_sends_no_key_header() -> None:
    transport = _RecordingTransport(_response(200, _head_response()))
    client = _new_client()

    with use_request_transport(transport):
        head = _fee_corrections(client).get_head(7, 19)

    _assert_frozen_dto(head, "FeeCorrectionHead")
    assert head.revision == 0
    assert head.expected_predecessor_id is None
    assert head.request_receipt is None
    assert "Idempotency-Key" not in transport.calls[0]["headers"]


def test_upload_preserves_original_utf8_csv_and_does_not_apply_or_enable_policy() -> None:
    transport = _RecordingTransport(_response(200, _upload_response()))
    client = _new_client()

    with use_request_transport(transport):
        result = _fee_corrections(client).upload_evidence(
            7,
            19,
            idempotency_key=_KEY,
            expected_revision=0,
            expected_predecessor_id=None,
            original_filename="broker-fees.csv",
            csv_text=_CSV_TEXT,
            attestation_acknowledged=True,
        )

    _assert_frozen_dto(result)
    _assert_frozen_dto(result.evidence, "FeeEvidenceReceipt")
    assert result.evidence.source_locator == _LOCATOR
    assert result.evidence.content_sha256 == sha256(_CSV_TEXT.encode("utf-8")).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", result.evidence.payload_sha256)
    _assert_aware_datetime(result.evidence.stored_at)
    assert result.evidence.assurance_class == "operator_attested_upload"
    assert result.assurance_notice
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == (
        f"{_BASE_URL}/api/simulated-trading/accounts/7/trades/19/fee-correction-evidence/"
    )
    assert call["headers"]["Idempotency-Key"] == _KEY
    assert call["json"] == {
        "expected_revision": 0,
        "expected_predecessor_id": None,
        "original_filename": "broker-fees.csv",
        "csv_text": _CSV_TEXT,
        "attestation_acknowledged": True,
    }


def test_apply_posts_only_locator_and_expected_revision_with_same_key() -> None:
    transport = _RecordingTransport(_response(200, _apply_response()))
    client = _new_client()

    with use_request_transport(transport):
        receipt = _fee_corrections(client).apply(
            7,
            19,
            idempotency_key=_KEY,
            source_locator=_LOCATOR,
            expected_revision=0,
        )

    _assert_frozen_dto(receipt, "FeeCorrectionReceipt")
    assert receipt.account_id == 7
    assert receipt.trade_id == 19
    assert receipt.event_id == 31
    assert receipt.revision == 1
    assert receipt.payload_hash == _HASH_A
    assert receipt.replayed is False
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == f"{_BASE_URL}/api/simulated-trading/accounts/7/trades/19/fee-corrections/"
    assert call["headers"]["Idempotency-Key"] == _KEY
    assert call["json"] == {"source_locator": _LOCATOR, "expected_revision": 0}


def test_explicit_upload_then_apply_share_key_and_are_two_separate_calls() -> None:
    transport = _SequencedTransport(
        [
            _response(200, _upload_response()),
            _response(200, _apply_response()),
        ]
    )
    client = _new_client()
    module = _fee_corrections(client)

    with use_request_transport(transport):
        upload = module.upload_evidence(
            7,
            19,
            idempotency_key=_KEY,
            expected_revision=0,
            expected_predecessor_id=None,
            original_filename="broker-fees.csv",
            csv_text=_CSV_TEXT,
            attestation_acknowledged=True,
        )
        receipt = module.apply(
            7,
            19,
            idempotency_key=_KEY,
            source_locator=upload.evidence.source_locator,
            expected_revision=0,
        )

    assert receipt.revision == 1
    assert len(transport.calls) == 2
    assert [call["headers"]["Idempotency-Key"] for call in transport.calls] == [_KEY, _KEY]
    assert transport.calls[0]["url"].endswith("/fee-correction-evidence/")
    assert transport.calls[1]["url"].endswith("/fee-corrections/")


@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        ("get_policy", {"account_id": True}),
        ("get_head", {"account_id": 7, "trade_id": True}),
        (
            "get_head",
            {"account_id": 7, "trade_id": 19, "idempotency_key": "bad key"},
        ),
        (
            "upload_evidence",
            _upload_input(expected_revision=True),
        ),
        (
            "upload_evidence",
            _upload_input(expected_predecessor_id=False),
        ),
        (
            "upload_evidence",
            _upload_input(attestation_acknowledged="true"),
        ),
        (
            "upload_evidence",
            _upload_input(csv_text=b"not text"),
        ),
        (
            "apply",
            _apply_input(expected_revision=True),
        ),
    ],
)
def test_noncanonical_ids_revisions_keys_and_json_types_fail_before_transport(
    method_name: str,
    kwargs: dict[str, object],
) -> None:
    transport = _RecordingTransport(_response(200, {}))
    module = _fee_corrections(_new_client())

    with use_request_transport(transport), pytest.raises(ValidationError):
        getattr(module, method_name)(**kwargs)

    assert transport.calls == []


@pytest.mark.parametrize("corruption", ["account_id", "boolean_version", "naive_valid_from"])
def test_get_policy_rejects_malformed_or_mismatched_policy_identity(corruption: str) -> None:
    payload = _policy_response()
    policy = cast(dict[str, Any], payload["policy"])
    if corruption == "account_id":
        policy["account_id"] = 8
    elif corruption == "boolean_version":
        policy["version"] = True
    else:
        policy["valid_from"] = "2026-10-27T09:00:00"
    transport = _RecordingTransport(_response(200, payload))
    client = _new_client()

    with use_request_transport(transport), pytest.raises(AgomTradeProAPIError):
        _fee_corrections(client).get_policy(7)

    assert len(transport.calls) == 1


@pytest.mark.parametrize("corruption", ["trade_id", "naive_as_of", "receipt_identity"])
def test_get_head_rejects_malformed_or_mismatched_readback(corruption: str) -> None:
    receipt = _receipt(replayed=True)
    payload = _head_response(receipt=receipt)
    head = cast(dict[str, Any], payload["head"])
    if corruption == "trade_id":
        head["trade_id"] = 20
    elif corruption == "naive_as_of":
        head["as_of"] = "2026-10-27T01:02:03"
    else:
        receipt["account_id"] = 8
    transport = _RecordingTransport(_response(200, payload))
    client = _new_client()

    with use_request_transport(transport), pytest.raises(AgomTradeProAPIError):
        _fee_corrections(client).get_head(7, 19, idempotency_key=_KEY)


@pytest.mark.parametrize("corruption", ["locator", "content_hash", "naive_stored_at"])
def test_malformed_upload_success_is_an_unknown_write_outcome(corruption: str) -> None:
    payload = _upload_response()
    evidence = cast(dict[str, Any], payload["evidence"])
    if corruption == "locator":
        evidence["source_locator"] = "not-a-canonical-uuid"
    elif corruption == "content_hash":
        evidence["content_sha256"] = _HASH_A
    else:
        evidence["stored_at"] = "2026-10-27T01:02:03"
    transport = _RecordingTransport(_response(200, payload))
    client = _new_client()

    with use_request_transport(transport), pytest.raises(AgomTradeProAPIError) as caught:
        _fee_corrections(client).upload_evidence(
            7,
            19,
            idempotency_key=_KEY,
            expected_revision=0,
            expected_predecessor_id=None,
            original_filename="broker-fees.csv",
            csv_text=_CSV_TEXT,
            attestation_acknowledged=True,
        )

    _assert_unknown_write(caught.value)
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "corruption", ["account_id", "boolean_event_id", "payload_hash", "replayed"]
)
def test_malformed_apply_receipt_is_an_unknown_write_outcome(corruption: str) -> None:
    receipt = _receipt()
    if corruption == "account_id":
        receipt["account_id"] = 8
    elif corruption == "boolean_event_id":
        receipt["event_id"] = True
    elif corruption == "payload_hash":
        receipt["payload_hash"] = "not-a-hash"
    else:
        receipt["replayed"] = "false"
    transport = _RecordingTransport(_response(200, {"success": True, "receipt": receipt}))
    client = _new_client()

    with use_request_transport(transport), pytest.raises(AgomTradeProAPIError) as caught:
        _fee_corrections(client).apply(
            7,
            19,
            idempotency_key=_KEY,
            source_locator=_LOCATOR,
            expected_revision=0,
        )

    _assert_unknown_write(caught.value)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("operation", ["set_policy", "upload_evidence", "apply"])
def test_timeout_on_any_write_is_unknown_and_never_retried_by_the_sdk(operation: str) -> None:
    sensitive = f"{_CSV_TEXT} key={_KEY} token=sensitive-sdk-token"
    transport = _RecordingTransport(requests.exceptions.ReadTimeout(sensitive))
    client = _new_client()

    with use_request_transport(transport), pytest.raises(AgomTradeProAPIError) as caught:
        _invoke_write(_fee_corrections(client), operation)

    _assert_unknown_write(caught.value)
    assert len(transport.calls) == 1
    assert sensitive not in str(caught.value)
    assert _KEY not in str(caught.value)
    assert "sensitive-sdk-token" not in str(caught.value)


@pytest.mark.parametrize("operation", ["set_policy", "upload_evidence", "apply"])
def test_server_error_on_write_is_unknown_and_keeps_sensitive_body_private(
    operation: str,
) -> None:
    secret_body = {"code": "database_unavailable", "detail": f"token secret {_KEY} {_CSV_TEXT}"}
    transport = _RecordingTransport(_response(503, secret_body))
    client = _new_client()

    with use_request_transport(transport), pytest.raises(AgomTradeProAPIError) as caught:
        _invoke_write(_fee_corrections(client), operation)

    _assert_unknown_write(caught.value)
    assert len(transport.calls) == 1
    assert _KEY not in str(caught.value)
    assert _CSV_TEXT not in str(caught.value)
    assert "token secret" not in str(caught.value)


@pytest.mark.parametrize("operation", ["upload_evidence", "apply"])
def test_owner_preflight_read_unavailable_503_remains_a_known_read_error(
    operation: str,
) -> None:
    """A preflight read failure must not claim that the requested write took effect."""

    transport = _RecordingTransport(
        _response(
            503,
            {
                "success": False,
                "code": "FEE_CORRECTION_READ_UNAVAILABLE",
                "error": "暂时无法读取已验证记录。",
            },
        )
    )
    client = _new_client()

    with use_request_transport(transport), pytest.raises(ServerError) as caught:
        _invoke_write(_fee_corrections(client), operation)

    assert caught.value.status_code == 503
    assert caught.value.code == "fee_correction_read_unavailable"
    assert type(caught.value).__name__ != "FeeCorrectionOutcomeUnknownError"
    assert getattr(caught.value, "effects_indeterminate", False) is not True
    assert getattr(caught.value, "recovery_required", False) is not True
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    ("status_code", "expected_type"),
    [
        (400, ValidationError),
        (401, AuthenticationError),
        (403, AuthenticationError),
        (404, AgomTradeProAPIError),
        (409, ConflictError),
        (422, AgomTradeProAPIError),
        (429, AgomTradeProAPIError),
    ],
)
def test_explicit_owner_or_revision_rejections_remain_known_api_errors(
    status_code: int,
    expected_type: type[AgomTradeProAPIError],
) -> None:
    transport = _RecordingTransport(
        _response(
            status_code, {"success": False, "code": "fee_correction_rejected", "error": "Blocked"}
        )
    )
    client = _new_client()

    with use_request_transport(transport), pytest.raises(expected_type) as caught:
        _fee_corrections(client).apply(
            7,
            19,
            idempotency_key=_KEY,
            source_locator=_LOCATOR,
            expected_revision=0,
        )

    assert caught.value.status_code == status_code
    assert type(caught.value).__name__ != "FeeCorrectionOutcomeUnknownError"
    assert getattr(caught.value, "effects_indeterminate", False) is not True
    assert getattr(caught.value, "recovery_required", False) is not True


def test_read_unavailable_503_remains_a_read_error_not_an_unknown_write() -> None:
    transport = _RecordingTransport(
        _response(
            503,
            {
                "success": False,
                "code": "FEE_CORRECTION_READ_UNAVAILABLE",
                "error": "暂时无法读取已验证记录。",
            },
        )
    )
    client = _new_client()

    with use_request_transport(transport), pytest.raises(ServerError) as caught:
        _fee_corrections(client).get_head(7, 19, idempotency_key=_KEY)

    assert caught.value.status_code == 503
    assert caught.value.code == "fee_correction_read_unavailable"
    assert type(caught.value).__name__ != "FeeCorrectionOutcomeUnknownError"
    assert getattr(caught.value, "effects_indeterminate", False) is not True
    assert getattr(caught.value, "recovery_required", False) is not True


@pytest.mark.parametrize("operation", ["upload_evidence", "apply"])
def test_invalid_json_after_write_is_an_unknown_outcome(operation: str) -> None:
    transport = _RecordingTransport(_invalid_json_response())
    client = _new_client()

    with use_request_transport(transport), pytest.raises(AgomTradeProAPIError) as caught:
        _invoke_write(_fee_corrections(client), operation)

    _assert_unknown_write(caught.value)
    assert len(transport.calls) == 1


def test_existing_policy_can_retain_a_nullable_historical_actor() -> None:
    """The public read contract permits a removed historical updater."""
    payload = _policy_response()
    payload["policy"]["updated_by_id"] = None
    transport = _RecordingTransport(_response(200, payload))
    with _new_client() as client, use_request_transport(transport):
        policy = _fee_corrections(client).get_policy(7)
    assert policy.version == 3
    assert policy.updated_by_id is None


def test_setting_identical_policy_can_confirm_the_existing_version() -> None:
    """An acknowledged no-op PUT keeps the version and is a verified result."""
    transport = _RecordingTransport(_response(200, _policy_response(version=2)))
    with _new_client() as client, use_request_transport(transport):
        result = _invoke_write(_fee_corrections(client), "set_policy")
    assert result.version == 2
    assert len(transport.calls) == 1


@pytest.mark.parametrize("corruption", ["current_event_mismatch", "unsolicited_receipt"])
def test_head_does_not_credit_an_inconsistent_or_unrequested_receipt(corruption: str) -> None:
    """An exact-key recovery result cannot claim an unrelated current event."""
    payload = _head_response(receipt=_receipt(replayed=True))
    key = _KEY
    if corruption == "current_event_mismatch":
        payload["head"]["expected_predecessor_id"] = 32
    else:
        key = None
    transport = _RecordingTransport(_response(200, payload))
    with _new_client() as client, use_request_transport(transport):
        with pytest.raises(AgomTradeProAPIError) as caught:
            _fee_corrections(client).get_head(7, 19, idempotency_key=key)
    assert not getattr(caught.value, "effects_indeterminate", False)


def test_original_key_receipt_remains_readable_after_a_later_revision() -> None:
    """Recovery can return an older receipt without replacing it with the latest one."""
    payload = _head_response(receipt=_receipt(replayed=True))
    payload["head"].update(revision=2, expected_predecessor_id=32)
    transport = _RecordingTransport(_response(200, payload))
    with _new_client() as client, use_request_transport(transport):
        head = _fee_corrections(client).get_head(7, 19, idempotency_key=_KEY)
    assert head.revision == 2
    assert head.request_receipt is not None
    assert head.request_receipt.revision == 1
    assert head.request_receipt.event_id == 31


def test_out_of_range_utc_input_is_rejected_before_sending_a_policy() -> None:
    """Valid ISO text whose UTC conversion overflows is still an invalid input."""
    values = _policy_input()
    values["valid_from"] = "0001-01-01T00:00:00+23:59"
    account_id = values.pop("account_id")
    transport = _RecordingTransport(_response(200, _policy_response()))
    with _new_client() as client, use_request_transport(transport):
        with pytest.raises(ValidationError):
            _fee_corrections(client).set_policy(account_id, **values)
    assert transport.calls == []


def test_out_of_range_utc_write_response_preserves_unknown_outcome() -> None:
    """An unrepresentable timestamp cannot escape post-write result recovery."""
    transport = _RecordingTransport(
        _response(200, _upload_response(stored_at="0001-01-01T00:00:00+23:59"))
    )
    with _new_client() as client, use_request_transport(transport):
        with pytest.raises(AgomTradeProAPIError) as caught:
            _invoke_write(_fee_corrections(client), "upload_evidence")
    _assert_unknown_write(caught.value)
    assert len(transport.calls) == 1

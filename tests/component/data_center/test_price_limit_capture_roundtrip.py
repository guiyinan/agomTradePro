"""Offline HTTP capture roundtrips through the real migrated raw-payload store."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import cast

import pytest
from django.db import connection

import apps.data_center.price_limit_capture_composition as composition
from apps.data_center.application.provider_response_payload import ProviderResponsePayloadReference
from apps.data_center.infrastructure.models import RawPayloadModel
from core.exceptions import DataFetchError
from tests.unit.data_center.test_price_limit_capture import (
    BODY,
    TRADE_DATE,
    ConfigReader,
    install_transport,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_capture_replays_original_body_from_fresh_raw_repository(
    monkeypatch: pytest.MonkeyPatch, record_testsuite_property: Callable[[str, object], None]
) -> None:
    """The real adapter and raw store preserve bytes across fresh compositions."""
    session = install_transport(monkeypatch)
    monkeypatch.setattr(composition, "ProviderConfigRepository", ConfigReader)
    result = composition.build_price_limit_capture_use_case().execute(
        provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE
    )
    stored = RawPayloadModel.objects.get(payload_hash=result.reference.payload_hash)
    assert stored.payload["retained_response_json"].encode("utf-8") == BODY
    assert stored.dataset_key == "equity.price.limit"
    assert result.reference.verifies(stored.to_domain())
    reference = ProviderResponsePayloadReference.from_payload(
        cast(dict[str, object], json.loads(json.dumps(result.reference.to_payload())))
    )
    fresh = composition.build_retained_price_limit_reader().execute(
        reference, scope=result.request_scope
    )
    assert fresh == result
    assert len(session.calls) == 1
    assert RawPayloadModel.objects.filter(dataset_key="equity.price.limit").count() == 1
    record_testsuite_property("price_limit_test_database", connection.settings_dict["NAME"])
    record_testsuite_property("price_limit_database_vendor", connection.vendor)


def test_corrupted_retained_request_cannot_be_replayed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypassing immutable storage to damage a row must invalidate its reference."""
    session = install_transport(monkeypatch)
    monkeypatch.setattr(composition, "ProviderConfigRepository", ConfigReader)
    result = composition.build_price_limit_capture_use_case().execute(
        provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE
    )
    RawPayloadModel.objects.filter(payload_hash=result.reference.payload_hash).update(
        request_params={"params": {"ts_code": "000001.SZ", "trade_date": "20261028"}}
    )
    with pytest.raises(DataFetchError):
        composition.build_retained_price_limit_reader().execute(
            result.reference, scope=result.request_scope
        )
    assert len(session.calls) == 1

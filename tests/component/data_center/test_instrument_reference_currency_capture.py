"""Keep optional stock currency bound to the real capture and retained raw evidence."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from playwright.sync_api import expect, sync_playwright

from apps.data_center import instrument_reference_snapshot_composition as composition
from apps.data_center.application.instrument_reference_capture import (
    CaptureExecutionStatus,
    CaptureInvocationMode,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.instrument_reference_capture import (
    InstrumentReferenceCaptureContractError,
)
from apps.data_center.domain.instrument_reference_snapshot import InstrumentReferenceMappingRecord
from apps.data_center.infrastructure import instrument_reference_capture_composition, tushare_client
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    InstrumentReferenceSnapshotPersistenceError,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_runtime import (
    create_instrument_reference_snapshot_repository,
)
from apps.data_center.infrastructure.models import (
    InstrumentReferenceMappingModel,
    InstrumentReferenceSnapshotModel,
    RawAuditModel,
    RawPayloadModel,
    SyncBatchModel,
    SyncCheckpointModel,
    SyncItemAttemptModel,
    SyncRunModel,
)
from tests.component.test_tui_task_first_browser import (
    _playwright_subprocess_policy as _playwright_subprocess_policy,
)
from tests.support.isolated_schema import isolated_schema
from tests.unit.data_center.test_instrument_reference_capture_provider import _ConfigRepository
from tests.unit.data_center.test_instrument_reference_capture_use_case import _mapping_record
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])


@pytest.fixture(autouse=True)
def _schema() -> Iterator[None]:
    with isolated_schema(
        (
            RawPayloadModel,
            RawAuditModel,
            InstrumentReferenceMappingModel,
            InstrumentReferenceSnapshotModel,
            SyncRunModel,
            SyncBatchModel,
            SyncCheckpointModel,
            SyncItemAttemptModel,
        )
    ):
        yield


class _CurrencySession(_Session):
    """Replace only HTTP; real request capture, claims and persistence remain active."""

    def __init__(self) -> None:
        super().__init__(_Response(b"{}"))
        self.currency: str | None = "CNY"

    def post(self, url: str, **kwargs: object) -> _Response:
        del url
        self.calls.append(kwargs)
        request = kwargs["json"]
        assert isinstance(request, dict)
        fields = request["fields"].split(",")
        params = request["params"]
        assert params == {"exchange": "SSE", "list_status": "L"}
        row = {
            "ts_code": "600000.SH",
            "name": "Fixture security",
            "exchange": "SSE",
            "market": "fixture-market",
            "list_status": "L",
            "list_date": "20200101",
            "delist_date": None,
            "curr_type": self.currency,
        }
        body = json.dumps(
            {
                "code": 0,
                "msg": None,
                "data": {"fields": fields, "items": [[row[k] for k in fields]]},
            }
        ).encode("utf-8")
        self.response = _Response(body)
        return cast(_Response, self.response)


@pytest.fixture
def capture_source(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_CurrencySession, InstrumentReferenceMappingRecord]:
    """Use the production public factory with fixture-owned transport and configuration."""

    session = _CurrencySession()
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    configuration = ProviderConfig(
        id=17,
        name="currency-capture-fixture",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="fixture-only-token",
        api_secret="",
        http_url="https://market.example.test/pro",
        api_endpoint="",
        extra_config={"tushare_request_mode": tushare_client.TUSHARE_REQUEST_MODE_UNIFIED_RELAY},
        description="Isolated test transport; never a real provider call",
    )
    repository = _ConfigRepository(configuration)
    monkeypatch.setattr(
        instrument_reference_capture_composition,
        "get_provider_config_repository",
        lambda: repository,
    )
    return session, composition.save_instrument_reference_mapping(_mapping_record().content)


def _capture_values(mapping: InstrumentReferenceMappingRecord) -> dict[str, object]:
    return {
        "capture_id": uuid4(),
        "provider_configuration_id": 17,
        "mapping_record_id": mapping.mapping_record_id,
        "exchange_scope": ("SSE",),
        "list_status_scope": ("L",),
        "actor_provenance": "component-fixture",
        "mode": CaptureInvocationMode.NORMAL,
    }


@pytest.mark.parametrize("currency", ["CNY", "USD", None, "", " cny "])
def test_public_capture_preserves_currency_through_raw_snapshot_readback_and_replay(
    capture_source: tuple[_CurrencySession, InstrumentReferenceMappingRecord],
    currency: str | None,
) -> None:
    session, mapping = capture_source
    session.currency = currency
    values = _capture_values(mapping)
    result = composition.capture_instrument_reference_snapshot(**values, include_currency=True)
    assert result.status is CaptureExecutionStatus.COMPLETED
    assert result.snapshot is not None
    saved = composition.read_instrument_reference_snapshot(snapshot_id=result.snapshot.snapshot_id)
    assert saved == result.snapshot
    assert saved is not None
    candidate = saved.content.fetch_rounds[0].candidate
    assert candidate.provider_contract.fields[-1] == "curr_type"
    assert candidate.provider_contract.contract_version == "v2"
    assert candidate.records[0].source_currency == currency
    classification = saved.content.classify_security("600000.SH")
    assert classification is not None
    assert classification.source_currency == currency
    assert saved.content.must_not_use_for_decision is True
    assert saved.content.must_not_execute is True
    assert candidate.records[0].source_observed_at is None
    assert candidate.records[0].source_available_at is None
    assert RawPayloadModel.objects.count() == RawAuditModel.objects.count() == 1
    assert InstrumentReferenceSnapshotModel.objects.count() == 1
    requests_before = len(session.calls)
    session.currency = "DIFFERENT-LATER-RESPONSE"
    replay = composition.capture_instrument_reference_snapshot(**values, include_currency=True)
    assert replay == result
    assert len(session.calls) == requests_before
    assert InstrumentReferenceSnapshotModel.objects.count() == 1


def test_public_capture_default_preserves_seven_fields_and_explicit_false_replay(
    capture_source: tuple[_CurrencySession, InstrumentReferenceMappingRecord],
) -> None:
    _session, mapping = capture_source
    values = _capture_values(mapping)
    result = composition.capture_instrument_reference_snapshot(**values)
    assert result.status is CaptureExecutionStatus.COMPLETED
    assert result.snapshot is not None
    candidate = result.snapshot.content.fetch_rounds[0].candidate
    assert candidate.provider_contract.contract_version == "v1"
    assert "curr_type" not in candidate.provider_contract.fields
    assert candidate.records[0].source_currency is None
    replay = composition.capture_instrument_reference_snapshot(**values, include_currency=False)
    assert replay == result


@pytest.mark.parametrize("original", [False, True])
@pytest.mark.parametrize("mode", [CaptureInvocationMode.NORMAL, CaptureInvocationMode.RESUME])
def test_existing_capture_cannot_change_currency_contract_on_retry(
    capture_source: tuple[_CurrencySession, InstrumentReferenceMappingRecord],
    original: bool,
    mode: CaptureInvocationMode,
) -> None:
    session, mapping = capture_source
    values = _capture_values(mapping)
    result = composition.capture_instrument_reference_snapshot(**values, include_currency=original)
    assert result.status is CaptureExecutionStatus.COMPLETED
    count = len(session.calls)
    values["mode"] = mode
    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        composition.capture_instrument_reference_snapshot(**values, include_currency=not original)
    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_DIGEST_MISMATCH"
    assert len(session.calls) == count
    assert InstrumentReferenceSnapshotModel.objects.count() == 1
    assert RawPayloadModel.objects.count() == RawAuditModel.objects.count() == 1


def test_snapshot_rejects_currency_forged_after_real_raw_capture(
    capture_source: tuple[_CurrencySession, InstrumentReferenceMappingRecord],
) -> None:
    _session, mapping = capture_source
    result = composition.capture_instrument_reference_snapshot(
        **_capture_values(mapping), include_currency=True
    )
    assert result.status is CaptureExecutionStatus.COMPLETED
    assert result.snapshot is not None
    content = result.snapshot.content
    first = content.fetch_rounds[0]
    forged = replace(first.candidate.records[0], source_currency="USD")
    changed = replace(first, candidate=replace(first.candidate, records=(forged,)))
    with pytest.raises(InstrumentReferenceSnapshotPersistenceError):
        create_instrument_reference_snapshot_repository().save_snapshot(
            replace(content, fetch_rounds=(changed,))
        )
    assert InstrumentReferenceSnapshotModel.objects.count() == 1
    assert (
        composition.read_instrument_reference_snapshot(snapshot_id=result.snapshot.snapshot_id)
        == result.snapshot
    )


@pytest.mark.django_db(transaction=True)
def test_currency_option_and_saved_value_are_visible_in_existing_tui(
    capture_source,
    live_server,
    _playwright_subprocess_policy,
    record_property,
) -> None:
    """Check the real local form and saved-source read, without submitting a capture in UI."""

    _session, mapping = capture_source
    result = composition.capture_instrument_reference_snapshot(
        **_capture_values(mapping), include_currency=True
    )
    assert result.snapshot is not None
    administrator = get_user_model().objects.create_user(
        username=f"currency-browser-{uuid4().hex}", is_staff=True
    )
    client = Client()
    client.force_login(administrator)
    screen = "api-library.data-center"
    metadata = client.get(f"/api/tui/screens/{screen}/")
    assert metadata.status_code == 200
    actions = {action["key"]: action for action in metadata.json()["actions"]}
    capture_key = "data-center.instrument-reference-capture"
    read_key = "data-center.instrument-reference-snapshot-read"
    capture_ui = actions[capture_key]["ui_key"]
    read_ui = actions[read_key]["ui_key"]
    output = (
        Path(settings.BASE_DIR)
        / "artifacts/a-share-usability/ash03-order-recovery-2026-10-29/durable-matcher"
        / f"currency-browser-{uuid4().hex}"
    )
    output.mkdir(parents=True)
    record_property("browser_artifacts", str(output))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1600, "height": 1000})
            context.add_cookies(
                [
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                        "url": live_server.url,
                    }
                ]
            )
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(
                    f"{live_server.url}/tui/?screen={screen}&action={capture_key}",
                    wait_until="networkidle",
                )
                form = page.locator(f'[data-action-ui-key="{capture_ui}"]')
                if not form.is_visible():
                    page.keyboard.press("F9")
                option = form.get_by_label("采集交易币种", exact=True)
                expect(option).to_be_visible()
                expect(option).not_to_be_checked()
                option.check()
                expect(option).to_be_checked()
                page.screenshot(path=str(output / "capture-option.png"), full_page=True)
                page.goto(
                    f"{live_server.url}/tui/?screen={screen}&action={read_key}",
                    wait_until="networkidle",
                )
                read_form = page.locator(f'[data-action-ui-key="{read_ui}"]')
                if not read_form.is_visible():
                    page.keyboard.press("F9")
                read_form.locator('[name="snapshot_id"]').fill(str(result.snapshot.snapshot_id))
                with page.expect_response(
                    lambda response: response.request.method == "POST"
                    and f"/api/tui/actions/{read_key}/run/" in response.url
                ) as response_info:
                    read_form.locator('button[type="submit"]').click()
                assert response_info.value.status == 200
                panel = page.locator("[data-main-panel]")
                header = panel.get_by_role("columnheader", name="来源交易币种", exact=True)
                header.scroll_into_view_if_needed()
                expect(header).to_be_visible()
                expect(panel.get_by_role("cell", name="CNY", exact=True)).to_be_visible()
                page.screenshot(path=str(output / "saved-currency.png"), full_page=True)
                assert errors == []
            finally:
                (output / "body.txt").write_text(
                    page.locator("body").inner_text(), encoding="utf-8"
                )
                page.screenshot(path=str(output / "final.png"), full_page=True)
        finally:
            browser.close()

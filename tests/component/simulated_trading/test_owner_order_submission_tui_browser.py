"""Exercise the real owner order flow through the authenticated TUI."""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime as datetime
from datetime import time as datetime_time
from datetime import timedelta as timedelta
from datetime import tzinfo as tzinfo
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from django.apps import apps
from django.conf import settings
from django.db import connection
from django.db.backends.utils import CursorWrapper
from django.utils import timezone as django_timezone
from playwright.sync_api import Route, expect, sync_playwright

from apps.data_center.application.sina_quote_capture import SinaQuoteCapture
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from shared.infrastructure.async_runtime import run_sync_compatible
from tests.component.equity.test_research_snapshot_tui_browser import (
    loopback_python_network_guard,
)
from tests.component.equity.test_research_snapshot_tui_browser import (
    subprocess_policy as subprocess_policy,
)
from tests.component.simulated_trading import (
    test_live_sina_close_snapshot_owner_acceptance as live_close_helpers,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import AS_OF as AS_OF
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    ASSET_CODE as ASSET_CODE,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    ASSET_NAME as ASSET_NAME,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    KNOWLEDGE_AT as KNOWLEDGE_AT,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _clear_runtime_profile_history as _clear_runtime_profile_history,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _owner_session_client as _owner_session_client,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _persist_sell_position as _persist_sell_position,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _QualifiedCallerContext as _QualifiedCallerContext,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    persisted_source_snapshot as persisted_source_snapshot,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    qualified_caller_context as qualified_caller_context,
)
from tests.component.simulated_trading.test_live_sina_close_snapshot_owner_acceptance import (  # noqa: F401
    live_owner_context as live_owner_context,
)
from tests.component.simulated_trading.test_owner_order_submission_api import (
    public_order_context as public_order_context,
)
from tests.support import ash03_auto_calendar_clock_v2 as auto_clock_fixture
from tests.support import ash03_auto_calendar_fixture as auto_calendar_fixture
from tests.support import ash03_auto_uow_fixture as auto_uow_fixture
from tests.support.ash03_auto_calendar_clock_v2 import freeze_auto_uow_fixture_clocks_native
from tests.support.native_postgres_database import assert_native_postgres_test_database

SCREEN = "simulated-trading.order-entry"
PREVIEW_ACTION_PATH = "/api/tui/actions/simulated-trading.order-preview/run/"
CONFIRM_ACTION_PATH = "/api/tui/actions/simulated-trading.order-confirm/run/"
READBACK_ACTION_PATH = "/api/tui/actions/simulated-trading.order-by-key/run/"

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def loopback_only_python_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Guard local and retained-replay flows against nonlocal Python network use."""
    yield from loopback_python_network_guard(monkeypatch)


@pytest.fixture
def _freeze_auto_fixture_knowledge_clocks(
    monkeypatch: pytest.MonkeyPatch,
    django_db_use_migrations: bool,
) -> None:
    """Freeze only the explicit historical fixture chain, never live close scenarios."""
    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.skip("qualified automatic caller proof requires migrated native PostgreSQL")
    assert_native_postgres_test_database()
    assert freeze_auto_uow_fixture_clocks_native(monkeypatch) == KNOWLEDGE_AT


def _business_state(
    account: SimulatedAccountModel,
    position: PositionModel,
) -> dict[str, str | int]:
    """Read database state on a synchronous thread, including inside Playwright."""

    account_id = account.pk
    position_id = position.pk

    def read_state() -> dict[str, str | int]:
        current_account = SimulatedAccountModel.objects.get(pk=account_id)
        current_position = PositionModel.objects.get(pk=position_id)
        active_sell_holds = list(
            SimulatedOrderReservationModel.objects.filter(
                account_id=account_id,
                side="sell",
                status=SimulatedOrderReservationModel.STATUS_ACTIVE,
            )
        )
        held_quantity = sum((hold.shares_reserved for hold in active_sell_holds), Decimal("0"))
        return {
            "cash": str(current_account.current_cash),
            "market_value": str(current_account.current_market_value),
            "total_value": str(current_account.total_value),
            "position_quantity": str(current_position.quantity),
            "available_quantity": str(current_position.available_quantity),
            "active_sell_hold_quantity": str(held_quantity),
            "free_sell_quantity": str(current_position.available_quantity - held_quantity),
            "reservation_count": SimulatedOrderReservationModel.objects.filter(
                account_id=account_id
            ).count(),
            "trade_count": SimulatedTradeModel.objects.filter(account_id=account_id).count(),
        }

    return run_sync_compatible(read_state)


def _aware_datetime(value: object) -> datetime:
    """Parse one TUI ISO timestamp and require its UTC offset."""

    assert type(value) is str and value
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None
    return parsed


@dataclass(frozen=True, slots=True)
class _AdvancingHistoricalClock:
    """Advance a local historical test clock with real monotonic elapsed time."""

    origin: datetime
    monotonic_origin: float

    def now(self) -> datetime:
        """Return the UTC origin plus real elapsed monotonic time."""

        elapsed = time.monotonic() - self.monotonic_origin
        return self.origin + timedelta(seconds=max(0.0, elapsed))

    def wait_until(self, target: datetime) -> None:
        """Let the real monotonic offset reach one exact historical cutoff."""

        while True:
            remaining = (target - self.now()).total_seconds()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.25))


@dataclass(frozen=True, slots=True)
class _RetainedCloseReplay:
    """Keep an exact source capture and the offset clock used by the test."""

    capture: SinaQuoteCapture
    index_path: Path
    clock: _AdvancingHistoricalClock


def _read_retained_sina_capture(index_path: Path) -> SinaQuoteCapture:
    """Reconstruct one retained public capture without changing bytes or clocks."""

    index_value = json.loads(index_path.read_text(encoding="utf-8"))
    if type(index_value) is not dict:
        raise AssertionError("retained Sina capture index must be an object")
    index = cast(dict[str, object], index_value)
    if (
        index.get("schema") != "ash03-live-sina-capture-index.v1"
        or index.get("purpose") != "test_only_public_source_capture"
    ):
        raise AssertionError("historical replay requires a retained live-source capture index")
    raw_body_name = index.get("raw_body_path")
    if type(raw_body_name) is not str or not raw_body_name:
        raise AssertionError("retained Sina index omits its exact raw-body path")
    body_path = (index_path.parent / raw_body_name).resolve()
    if body_path.parent != index_path.resolve().parent:
        raise AssertionError("retained Sina raw-body path escapes its evidence directory")
    body = body_path.read_bytes()
    payload: dict[str, object] = {
        "schema": "sina-quote-capture.v1",
        "asset_code": index["asset_code"],
        "requested_url": index["requested_url"],
        "final_url": index["final_url"],
        "request_started_at": index["request_started_at_utc"],
        "response_completed_at": index["response_completed_at_utc"],
        "http_status": index["http_status"],
        "http_date": index["http_date"],
        "content_type": index["content_type"],
        "charset": index["charset"],
        "content_encoding": index["content_encoding"],
        "body_base64": base64.b64encode(body).decode("ascii"),
        "body_size_bytes": index["body_bytes"],
        "body_sha256": index["body_sha256"],
        "parse_issue": index["parse_issue"],
    }
    capture = SinaQuoteCapture.from_payload(payload)
    live_close_helpers.live_helpers._verify_capture_artifact(capture, index_path)
    return capture


def _load_r9_r10_retained_close_capture() -> tuple[SinaQuoteCapture, Path]:
    """Select the earliest verified actual R9/R10 source artifact for this replay."""

    evidence_root = (
        Path(__file__).resolve().parents[3] / ".tmp" / "ash03-live-sina-close-snapshot-acceptance"
    )
    index_paths = tuple(
        index_path
        for directory_name in (
            "owner-reserve-20261102",
            "owner-stop-loss-20261102",
        )
        for index_path in sorted((evidence_root / directory_name).glob("*.json"))
    )
    if not index_paths:
        pytest.skip("controlled browser replay requires a retained R9/R10 Sina capture artifact")

    candidates: list[tuple[SinaQuoteCapture, Path]] = []
    for index_path in index_paths:
        capture = _read_retained_sina_capture(index_path)
        quote = capture.quote
        if (
            capture.usable_parse
            and quote is not None
            and quote.asset_code == ASSET_CODE
            and quote.last_price is not None
            and quote.source_observed_at is not None
            and quote.source_clock_status.value == "valid"
            and quote.reported_trading_state.name == "TRADING"
            and quote.source_observed_at.astimezone(live_close_helpers.SHANGHAI).date()
            == capture.response_completed_at.astimezone(live_close_helpers.SHANGHAI).date()
        ):
            candidates.append((capture, index_path))
    if not candidates:
        pytest.skip("retained R9/R10 source artifacts contain no exact usable close quote")
    return min(candidates, key=lambda candidate: candidate[0].response_completed_at)


def _advancing_datetime_type(clock: _AdvancingHistoricalClock) -> type[datetime]:
    """Build exact native datetime return values for the historical clock seams."""

    class _OffsetDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            """Return one advancing offset instant in the requested timezone."""

            value = clock.now()
            selected = value.replace(tzinfo=None) if tz is None else value.astimezone(tz)
            return datetime(
                selected.year,
                selected.month,
                selected.day,
                selected.hour,
                selected.minute,
                selected.second,
                selected.microsecond,
                tzinfo=selected.tzinfo,
                fold=selected.fold,
            )

    return _OffsetDateTime


@pytest.fixture(autouse=True)
def _retained_close_historical_clock(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> _RetainedCloseReplay | None:
    """Install the advancing historical clock only for the retained replay UI test."""

    if (
        request.node.originalname
        != "test_retained_historical_close_snapshot_owner_previews_confirms_and_reads_order"
        or os.environ.get("AGOM_RUN_RETAINED_SINA_CLOSE_UI_ACCEPTANCE") != "1"
    ):
        return None
    capture, index_path = _load_r9_r10_retained_close_capture()
    clock = _AdvancingHistoricalClock(
        origin=capture.response_completed_at - timedelta(seconds=60),
        monotonic_origin=time.monotonic(),
    )
    offset_datetime = _advancing_datetime_type(clock)
    monkeypatch.setattr(django_timezone, "now", clock.now)
    monkeypatch.setattr(auto_calendar_fixture.runtime_public_application, "datetime", datetime)

    def datetime_type_at(_value: datetime) -> type[datetime]:
        """Keep runtime-profile writes on the same advancing historical clock."""

        return offset_datetime

    monkeypatch.setattr(auto_calendar_fixture, "_datetime_class_at", datetime_type_at)
    for module in (
        auto_calendar_fixture.runtime_config_application,
        auto_calendar_fixture.runtime_config_domain,
        auto_clock_fixture.provider_response_capture,
        auto_clock_fixture.tushare_client,
        auto_clock_fixture.calendar_source_fixture,
    ):
        monkeypatch.setattr(module, "datetime", offset_datetime)

    def advancing_server_clock(_clock: object) -> datetime:
        """Return the same offset time through the settlement clock seam."""

        return clock.now()

    monkeypatch.setattr(
        auto_calendar_fixture.execution_current_reference_composition._ServerUTCClock,
        "now",
        advancing_server_clock,
    )

    def wrap_runtime_profile_activation(activation: Any) -> Any:
        """Confine the offset class to existing runtime-profile write contexts."""

        def activate(*args: Any, **kwargs: Any) -> Any:
            with auto_calendar_fixture._runtime_public_write_clock():
                return activation(*args, **kwargs)

        return activate

    monkeypatch.setattr(
        auto_calendar_fixture,
        "activate_runtime_profile_patch",
        wrap_runtime_profile_activation(auto_calendar_fixture.activate_runtime_profile_patch),
    )
    monkeypatch.setattr(
        auto_uow_fixture,
        "activate_runtime_profile_patch",
        wrap_runtime_profile_activation(auto_uow_fixture.activate_runtime_profile_patch),
    )
    monkeypatch.setattr(
        live_close_helpers.live_helpers,
        "activate_runtime_profile_patch",
        wrap_runtime_profile_activation(
            live_close_helpers.live_helpers.activate_runtime_profile_patch
        ),
    )
    return _RetainedCloseReplay(capture=capture, index_path=index_path, clock=clock)


def _configure_retained_historical_close_source(
    *,
    monkeypatch: pytest.MonkeyPatch,
    context: live_close_helpers.live_helpers._LiveOwnerContext,
    replay: _RetainedCloseReplay,
) -> live_close_helpers._CloseSnapshotEvidence:
    """Qualify an exact retained source response for a bounded historical UI replay."""

    capture = replay.capture
    quote = capture.quote
    if quote is None or quote.last_price is None or quote.source_observed_at is None:
        raise AssertionError("retained R9/R10 response no longer has its qualified quote row")
    trade_date = quote.source_observed_at.astimezone(live_close_helpers.SHANGHAI).date()
    if context.uow.market_session != trade_date:
        raise AssertionError(
            "historical local calendar differs from the original source trade date"
        )
    replay.clock.wait_until(capture.response_completed_at + timedelta(seconds=2))
    now = replay.clock.now()
    if (
        not capture.response_completed_at
        <= now
        < capture.response_completed_at + timedelta(seconds=300)
    ):
        raise AssertionError("historical decision clock is outside the original capture TTL")

    close_at = datetime.combine(
        trade_date,
        max(window.ends_at for window in context.policy.session_windows),
        live_close_helpers.SHANGHAI,
    )
    day_end = live_close_helpers._utc(
        datetime.combine(
            trade_date + timedelta(days=1), datetime_time.min, live_close_helpers.SHANGHAI
        )
        - timedelta(microseconds=1)
    )
    available_until = min(capture.response_completed_at + timedelta(seconds=300), day_end)
    policy = live_close_helpers.CloseSnapshotSimulationPolicy(
        policy_id=f"ash03-close-snapshot-retained-replay-{live_close_helpers.uuid4().hex}",
        policy_version="retained-replay-v1",
        account_id=int(context.account.pk),
        security_id=live_close_helpers.SECURITY_ID,
        asset_code=live_close_helpers.ASSET_CODE,
        market=context.policy.market,
        board=context.policy.board,
        trading_date=trade_date,
        source_id=context.policy.source_id,
        source_name=context.policy.source_name,
        usage_ttl_seconds=300,
        status_mapping_sha256=context.policy.status_mapping_sha256,
        trusted_vendor_status_codes=context.policy.trusted_vendor_status_codes,
        available_from=max(capture.response_completed_at, live_close_helpers._utc(close_at)),
        available_until=available_until,
        price_rule="exact_vendor_last_after_close.v1",
        price_rule_source_hash=live_close_helpers.sha256(
            b"test policy: exact retained vendor last price after published close"
        ).hexdigest(),
        price_boundary_mode=context.policy.price_boundary_mode,
        lower_boundary_factor=context.policy.lower_boundary_factor,
        upper_boundary_factor=context.policy.upper_boundary_factor,
        boundary_rule_source_id=cast(str, context.policy.boundary_rule_source_id),
        boundary_rule_version=cast(str, context.policy.boundary_rule_version),
        boundary_rule_source_hash=cast(str, context.policy.boundary_rule_source_hash),
        unrestricted_reason_code=context.policy.unrestricted_reason_code,
    )
    open_calendar = live_close_helpers.live_helpers._local_calendar_context(
        context=context,
        as_of=now,
    )
    if open_calendar.calendar_available_at > capture.response_completed_at:
        raise AssertionError("historical calendar fixture was recorded after the original capture")
    evaluation = live_close_helpers.evaluate_close_snapshot_simulation(
        capture=capture,
        policy=policy,
        calendar=live_close_helpers.replace(
            open_calendar,
            session_state=live_close_helpers.SessionState.CLOSED,
        ),
        rule=context.uow.rule_bundle.execution_submission_v2,
        account_id=int(context.account.pk),
        security_id=live_close_helpers.SECURITY_ID,
        asset_code=live_close_helpers.ASSET_CODE,
        trading_date=trade_date,
        requested_price=quote.last_price,
        as_of=now,
    )
    if not live_close_helpers._is_qualified(evaluation.decision.status):
        raise AssertionError(
            "retained close capture did not qualify under the bounded local replay policy: "
            f"{evaluation.decision.reason_codes}"
        )
    if evaluation.bundle is None:
        raise AssertionError("qualified retained capture omitted its close-snapshot bundle")

    with live_close_helpers._runtime_public_write_clock():
        live_close_helpers.activate_runtime_profile_patch(
            environment="development",
            patch={
                live_close_helpers.CLOSE_SNAPSHOT_POLICIES_KEY: {"policies": [policy.to_payload()]}
            },
            actor="ash03-retained-historical-close-ui-test",
            reason="bounded replay of an existing actual Sina capture for local UI acceptance",
        )

    routed_captures: list[SinaQuoteCapture] = []
    routed_indexes: list[Path] = []

    def replay_original_capture(asset_code: str) -> SinaQuoteCapture:
        """Return the retained object and original bytes without issuing another request."""

        if asset_code != capture.asset_code:
            raise AssertionError("replay port requested a different security than the capture")
        live_close_helpers.live_helpers._verify_capture_artifact(capture, replay.index_path)
        routed_captures.append(capture)
        routed_indexes.append(replay.index_path)
        return capture

    monkeypatch.setattr(
        live_close_helpers.owner_market_composition,
        "capture_sina_quote",
        replay_original_capture,
    )
    monkeypatch.setattr(
        live_close_helpers.close_market_composition,
        "capture_sina_quote",
        replay_original_capture,
    )
    return live_close_helpers._CloseSnapshotEvidence(
        policy=policy,
        preflight_capture=capture,
        preflight_index=replay.index_path,
        routed_captures=routed_captures,
        routed_indexes=routed_indexes,
    )


def _is_simulated_table_write(sql: object, table_names: frozenset[str]) -> bool:
    """Identify DML against simulated-trading or the held-position table."""

    statement = str(sql).lstrip().casefold()
    verb = statement.split(None, 1)[0] if statement else ""
    if verb not in {"insert", "update", "delete", "replace"}:
        return False
    return any(table in statement for table in table_names)


def _write_response_artifact(
    evidence_dir: Path,
    filename: str,
    status_code: int,
    body: object,
) -> None:
    """Retain one complete local TUI HTTP response for failed-journey diagnosis."""

    artifact = {"status_code": status_code, "body": body}
    (evidence_dir / filename).write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "viewport",
    [(1440, 1000), (390, 844)],
    ids=["desktop", "narrow"],
)
def test_ordinary_owner_previews_confirms_and_reads_original_order_in_tui(
    public_order_context: tuple[_QualifiedCallerContext, list[str]],
    live_server: Any,
    subprocess_policy: None,
    loopback_only_python_network: list[str],
    viewport: tuple[int, int],
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview without business writes, confirm once, then recover by-key in TUI."""

    fixture_context, capture_calls = public_order_context
    # The qualified fixture pins this shared module used by terminal execution;
    # repatching it here would also alter the fixture's source-knowledge clocks.
    assert django_timezone.now() == AS_OF
    account = fixture_context.account
    position = _persist_sell_position(account)
    account.current_market_value = position.market_value
    account.total_value = account.current_cash + position.market_value
    account.save(
        update_fields=[
            "current_market_value",
            "total_value",
            "cash_known",
            "cash_reconciliation_status",
        ]
    )
    initial_state = _business_state(account, position)
    assert initial_state["reservation_count"] == 0
    assert initial_state["trade_count"] == 0

    client, csrf_token = _owner_session_client(fixture_context.owner_id)
    session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    csrf_cookie = client.cookies[settings.CSRF_COOKIE_NAME].value
    assert csrf_cookie == csrf_token
    evidence_dir = tmp_path / "browser" / request.node.name
    evidence_dir.mkdir(parents=True, exist_ok=True)

    simulated_tables = {
        model._meta.db_table.casefold()
        for model in apps.get_app_config("simulated_trading").get_models()
    }
    simulated_tables.add(PositionModel._meta.db_table.casefold())
    simulated_table_names = frozenset(simulated_tables)
    capture_simulated_dml = threading.Event()
    preview_simulated_dml: list[str] = []
    readback_simulated_dml: list[str] = []
    active_dml_log = preview_simulated_dml
    original_execute = CursorWrapper.execute
    original_executemany = CursorWrapper.executemany

    def observe_execute(
        cursor: CursorWrapper,
        sql: Any,
        params: Any = None,
    ) -> Any:
        if capture_simulated_dml.is_set() and _is_simulated_table_write(sql, simulated_table_names):
            active_dml_log.append(str(sql).lstrip().split(None, 1)[0].upper())
        return original_execute(cursor, sql, params)

    def observe_executemany(
        cursor: CursorWrapper,
        sql: Any,
        param_list: Any,
    ) -> Any:
        if capture_simulated_dml.is_set() and _is_simulated_table_write(sql, simulated_table_names):
            active_dml_log.append(str(sql).lstrip().split(None, 1)[0].upper())
        return original_executemany(cursor, sql, param_list)

    monkeypatch.setattr(CursorWrapper, "execute", observe_execute)
    monkeypatch.setattr(CursorWrapper, "executemany", observe_executemany)

    browser_requests: list[dict[str, str]] = []
    preview_request_parameters: list[dict[str, object]] = []
    nonlocal_browser_attempts: list[str] = []
    page_errors: list[str] = []
    request_failures: list[str] = []
    confirmation_upstream: list[dict[str, object]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        browser_context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}
        )
        browser_context.clock.install(time=AS_OF)
        browser_context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": session_cookie,
                    "url": live_server.url,
                },
                {
                    "name": settings.CSRF_COOKIE_NAME,
                    "value": csrf_cookie,
                    "url": live_server.url,
                },
            ]
        )

        def local_only(route: Route) -> None:
            """Keep the browser on the local server origin."""

            target = urlsplit(route.request.url)
            expected = urlsplit(live_server.url)
            if target.scheme not in {"http", "https"} or target.netloc != expected.netloc:
                nonlocal_browser_attempts.append(route.request.url)
                route.abort("blockedbyclient")
                return
            route.continue_()

        def simulate_lost_confirm_response(route: Route) -> None:
            """Commit the real confirmation, then lose only its browser response."""

            target = urlsplit(route.request.url)
            expected = urlsplit(live_server.url)
            if target.netloc != expected.netloc:
                nonlocal_browser_attempts.append(route.request.url)
                route.abort("blockedbyclient")
                return

            request_body = route.request.post_data_json
            confirmed = isinstance(request_body, dict) and request_body.get("confirmed") is True
            if not confirmed:
                route.continue_()
                return

            upstream = route.fetch()
            upstream_payload = upstream.json()
            upstream_response = (
                upstream_payload.get("response") if isinstance(upstream_payload, dict) else None
            )
            _write_response_artifact(
                evidence_dir,
                "confirm-upstream-response.json",
                upstream.status,
                upstream_payload,
            )
            confirmation_upstream.append(
                {
                    "http_status": upstream.status,
                    "business_status": (
                        upstream_response.get("status_code")
                        if isinstance(upstream_response, dict)
                        else None
                    ),
                    "outcome": (
                        upstream_payload.get("outcome")
                        if isinstance(upstream_payload, dict)
                        else None
                    ),
                }
            )
            route.fulfill(
                status=502,
                content_type="application/json",
                body=json.dumps({"detail": "test-only browser response loss after local commit"}),
            )

        browser_context.route("**/*", local_only)
        browser_context.route(
            f"{live_server.url}{CONFIRM_ACTION_PATH}",
            simulate_lost_confirm_response,
        )
        page = browser_context.new_page()

        def record_action_request(browser_request: Any) -> None:
            path = urlsplit(browser_request.url).path
            if path in {
                PREVIEW_ACTION_PATH,
                CONFIRM_ACTION_PATH,
                READBACK_ACTION_PATH,
            }:
                browser_requests.append(
                    {
                        "path": path,
                        "method": browser_request.method,
                        "idempotency_key": browser_request.headers.get("idempotency-key", ""),
                    }
                )
                if path == PREVIEW_ACTION_PATH:
                    request_body = browser_request.post_data_json
                    request_params = (
                        request_body.get("params") if isinstance(request_body, dict) else None
                    )
                    if isinstance(request_params, dict):
                        preview_request_parameters.append(
                            {
                                field: request_params.get(field)
                                for field in (
                                    "quantity",
                                    "limit_price",
                                    "fee_budget",
                                    "market_purpose",
                                )
                            }
                        )

        page.on("request", record_action_request)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda browser_request: request_failures.append(
                f"{browser_request.method} {browser_request.url}: {browser_request.failure}"
            ),
        )
        try:
            page.goto(
                f"{live_server.url}/tui/?screen={SCREEN}",
                wait_until="networkidle",
            )
            panel = page.locator('[data-main-panel] [data-dashboard-panel="order-entry-intent"]')
            form = panel.locator("form.tui-action-form")
            expect(form).to_be_visible()
            assert form.count() == 1
            account_select = form.locator('[name="account_id"]')
            owned_account_option = account_select.locator(f'option[value="{account.pk}"]')
            expect(owned_account_option).to_have_count(1)
            account_select.select_option(value=str(account.pk))
            expect(account_select).to_have_value(str(account.pk))
            form.locator('[name="asset_code"]').fill(ASSET_CODE)
            form.locator('[name="asset_name"]').fill(ASSET_NAME)
            form.locator('[name="side"]').select_option("sell")
            form.locator('[name="quantity"]').fill("100")
            form.locator('[name="limit_price"]').fill("10.00")

            capture_simulated_dml.set()
            try:
                with page.expect_response(
                    lambda response: urlsplit(response.url).path == PREVIEW_ACTION_PATH
                ) as preview_response:
                    form.locator(".tui-action-submit").click()
            finally:
                capture_simulated_dml.clear()

            preview_http = preview_response.value
            preview = preview_http.json()
            actual_continuation = preview.get("continuation")
            actual_continuation_input = (
                actual_continuation.get("input") if isinstance(actual_continuation, dict) else None
            )
            actual_preview_token = (
                actual_continuation_input.get("preview_token")
                if isinstance(actual_continuation_input, dict)
                else None
            )
            sanitized_preview_request = (
                preview_request_parameters[0] if len(preview_request_parameters) == 1 else None
            )
            (evidence_dir / "preview-request-body.json").write_text(
                json.dumps(
                    {"params": sanitized_preview_request},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            preview_artifact = dict(preview)
            artifact_continuation = preview_artifact.get("continuation")
            if isinstance(artifact_continuation, dict):
                safe_continuation = {
                    key: artifact_continuation[key]
                    for key in ("action_key", "expires_at")
                    if key in artifact_continuation
                }
                continuation_input = artifact_continuation.get("input")
                if isinstance(continuation_input, dict):
                    safe_continuation["input"] = {
                        key: continuation_input[key]
                        for key in ("account_id", "order_key")
                        if key in continuation_input
                    }
                preview_artifact["continuation"] = safe_continuation
            serialized_preview_artifact = json.dumps(preview_artifact, ensure_ascii=False)
            assert type(actual_preview_token) is str and actual_preview_token
            assert actual_preview_token not in serialized_preview_artifact
            _write_response_artifact(
                evidence_dir,
                "preview-response.json",
                preview_http.status,
                preview_artifact,
            )
            assert sanitized_preview_request == {
                "quantity": "100",
                "limit_price": "10.00",
                "fee_budget": None,
                "market_purpose": "local_simulation_only",
            }
            assert preview_http.status == 200
            assert preview.get("outcome") == "success"
            assert preview.get("response", {}).get("status_code") == 200
            assert preview.get("view_model", {}).get("outcome") == "success"
            assert preview_simulated_dml == []
            assert _business_state(account, position) == initial_state
            assert capture_calls == [ASSET_CODE]

            continuation = preview.get("continuation")
            assert isinstance(continuation, dict)
            assert continuation.get("action_key") == "simulated-trading.order-confirm"
            continuation_input = continuation.get("input")
            assert isinstance(continuation_input, dict)
            order_key = continuation_input.get("order_key")
            assert type(order_key) is str and order_key
            assert continuation_input.get("preview_token") == actual_preview_token
            view_model = preview.get("view_model")
            assert isinstance(view_model, dict)
            summary = view_model.get("business_summary")
            assert type(summary) is str and summary
            field_values = {
                field["key"]: field.get("value")
                for field in view_model.get("fields", [])
                if isinstance(field, dict) and type(field.get("key")) is str
            }
            assert field_values.get("asset_code") == ASSET_CODE
            assert field_values.get("side") == "卖出"
            assert Decimal(str(field_values.get("quantity"))) == Decimal("100")
            assert Decimal(str(field_values.get("limit_price"))) == Decimal("10.00")
            assert field_values.get("fee_estimate") is not None
            observed_at = _aware_datetime(field_values.get("market_observed_at"))
            available_at = _aware_datetime(field_values.get("market_available_at"))
            confirmation_expires_at = _aware_datetime(field_values.get("continuation_expires_at"))
            assert observed_at.date().isoformat() == AS_OF.date().isoformat()
            assert observed_at < available_at < AS_OF
            assert confirmation_expires_at > AS_OF
            for visible_fact in (
                ASSET_CODE,
                "卖出",
                "100",
                "10.00",
                "预估费用",
                str(field_values["market_observed_at"]),
                str(field_values["continuation_expires_at"]),
                "不会提交券商",
            ):
                assert visible_fact in summary
            main_panel = page.locator("[data-main-panel]")
            expect(main_panel).to_contain_text("不会提交券商")
            expect(main_panel).to_contain_text(ASSET_CODE)
            assert main_panel.evaluate("element => element.scrollWidth") <= viewport[0] + 1

            preview_key_headers = [
                item["idempotency_key"]
                for item in browser_requests
                if item["path"] == PREVIEW_ACTION_PATH
            ]
            assert len(preview_key_headers) == 1 and preview_key_headers[0]

            continue_button = page.get_by_role(
                "button",
                name="继续：确认模拟订单预留",
                exact=True,
            )
            expect(continue_button).to_be_visible()
            with page.expect_response(
                lambda response: urlsplit(response.url).path == CONFIRM_ACTION_PATH
            ) as preflight_response:
                continue_button.click()
            preflight_http = preflight_response.value
            preflight = preflight_http.json()
            _write_response_artifact(
                evidence_dir, "confirm-preflight-response.json", preflight_http.status, preflight
            )
            assert preflight_http.status == 200
            assert preflight.get("confirmation_required") is True
            assert preflight.get("response", {}).get("status_code") == 409
            expect(page.locator("[data-tui-modal]")).to_be_visible()
            confirm_button = page.locator("[data-tui-modal] [data-confirm-action]")
            expect(confirm_button).to_be_visible()
            assert _business_state(account, position) == initial_state
            assert capture_calls == [ASSET_CODE]

            with page.expect_response(
                lambda response: urlsplit(response.url).path == CONFIRM_ACTION_PATH
            ) as lost_confirm_response:
                confirm_button.click()
            lost_confirm_http = lost_confirm_response.value
            lost_confirm_body = lost_confirm_http.json()
            _write_response_artifact(
                evidence_dir,
                "confirm-browser-response.json",
                lost_confirm_http.status,
                lost_confirm_body,
            )
            assert lost_confirm_http.status == 502
            assert confirmation_upstream == [
                {"http_status": 200, "business_status": 200, "outcome": "success"}
            ]
            confirmation_keys = [
                item["idempotency_key"]
                for item in browser_requests
                if item["path"] == CONFIRM_ACTION_PATH
            ]
            assert len(confirmation_keys) == 2
            assert confirmation_keys == [preview_key_headers[0], preview_key_headers[0]]

            reservations = run_sync_compatible(
                lambda: list(SimulatedOrderReservationModel.objects.filter(account_id=account.pk))
            )
            assert len(reservations) == 1
            reservation = reservations[0]
            assert reservation.idempotency_key == order_key
            assert reservation.owner_user_id == fixture_context.owner_id
            assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
            assert reservation.side == "sell"
            assert reservation.quantity == Decimal("100")
            assert reservation.limit_price == Decimal("10.00")
            assert reservation.shares_reserved == Decimal("100")
            assert reservation.filled_quantity == Decimal("0")
            assert "submission_market" in reservation.plan_snapshot
            after_confirm = _business_state(account, position)
            assert after_confirm["cash"] == initial_state["cash"]
            assert after_confirm["position_quantity"] == initial_state["position_quantity"]
            assert after_confirm["available_quantity"] == initial_state["available_quantity"]
            assert Decimal(str(after_confirm["active_sell_hold_quantity"])) == Decimal("100")
            assert Decimal(str(initial_state["free_sell_quantity"])) - Decimal(
                str(after_confirm["free_sell_quantity"])
            ) == Decimal("100")
            assert after_confirm["reservation_count"] == 1
            assert after_confirm["trade_count"] == 0
            expect(page.locator("[data-main-panel]")).to_contain_text("原请求结果待确认")
            page.screenshot(path=str(evidence_dir / "unknown-confirm.png"))

            readback_button = page.locator("[data-main-panel] [data-continuation-readback]")
            expect(readback_button).to_be_visible()
            active_dml_log = readback_simulated_dml
            capture_simulated_dml.set()
            try:
                with page.expect_response(
                    lambda response: urlsplit(response.url).path == READBACK_ACTION_PATH
                ) as readback_response:
                    readback_button.click()
            finally:
                capture_simulated_dml.clear()

            readback_http = readback_response.value
            readback = readback_http.json()
            _write_response_artifact(
                evidence_dir, "readback-response.json", readback_http.status, readback
            )
            assert readback_http.status == 200
            assert readback.get("outcome") == "success"
            assert readback.get("response", {}).get("status_code") == 200
            readback_action = readback.get("action")
            assert isinstance(readback_action, dict)
            assert readback_action.get("key") == "simulated-trading.order-by-key"
            assert readback_action.get("method") == "GET"
            readback_keys = [
                item["idempotency_key"]
                for item in browser_requests
                if item["path"] == READBACK_ACTION_PATH
            ]
            assert readback_keys == [preview_key_headers[0]]
            assert readback_simulated_dml == []
            assert capture_calls == [ASSET_CODE]
            assert _business_state(account, position) == after_confirm

            readback_view = readback.get("view_model")
            assert isinstance(readback_view, dict)
            assert readback_view.get("outcome") == "success"
            readback_summary = readback_view.get("business_summary")
            assert type(readback_summary) is str
            assert "已找到同一原订单" in readback_summary
            assert "未重新读取行情或创建新单" in readback_summary
            readback_fields = {
                field["key"]: field.get("value")
                for field in readback_view.get("fields", [])
                if isinstance(field, dict) and type(field.get("key")) is str
            }
            assert int(readback_fields["order_id"]) == reservation.pk
            assert readback_fields["side"] == "卖出"
            assert Decimal(str(readback_fields["quantity"])) == Decimal("100")
            assert Decimal(str(readback_fields["filled_quantity"])) == Decimal("0")
            expect(page.locator("[data-main-panel]")).to_contain_text("已找到同一原订单")
            expect(page.locator("[data-main-panel]")).to_contain_text("累计成交数量 0")
            assert (
                page.locator("[data-main-panel]").evaluate("element => element.scrollWidth")
                <= viewport[0] + 1
            )
            page.screenshot(path=str(evidence_dir / "readback.png"))

            assert page_errors == []
            assert request_failures == []
            assert nonlocal_browser_attempts == []
            assert loopback_only_python_network == []
            safe_evidence = {
                "case": request.node.name,
                "screen": SCREEN,
                "viewport": {"width": viewport[0], "height": viewport[1]},
                "as_of": AS_OF.isoformat(),
                "simulation_scope": "explicit local fixture; no brokerage submission",
                "preview_summary": summary,
                "preview_request_params": sanitized_preview_request,
                "preview_simulated_table_dml": preview_simulated_dml,
                "confirm_upstream": confirmation_upstream,
                "readback": {
                    "action_key": readback_action["key"],
                    "method": readback_action["method"],
                    "order_id": reservation.pk,
                    "status": readback_view.get("status"),
                },
                "final_business_state": after_confirm,
                "capture_calls": capture_calls,
                "page_errors": page_errors,
                "request_failures": request_failures,
                "nonlocal_browser_attempts": nonlocal_browser_attempts,
                "nonlocal_python_socket_attempts": loopback_only_python_network,
            }
            (evidence_dir / "journey.json").write_text(
                json.dumps(safe_evidence, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        finally:
            try:
                if not page.is_closed():
                    page.screenshot(
                        path=str(evidence_dir / "final-diagnostic.png"),
                        full_page=True,
                    )
            finally:
                browser_context.close()
                browser.close()


@pytest.mark.parametrize(
    "viewport",
    [(1440, 1000), (390, 844)],
    ids=["desktop", "narrow"],
)
@pytest.mark.skipif(
    os.environ.get("AGOM_RUN_LIVE_SINA_CLOSE_SNAPSHOT_ACCEPTANCE") != "1",
    reason=(
        "set AGOM_RUN_LIVE_SINA_CLOSE_SNAPSHOT_ACCEPTANCE=1 for actual-time close browser acceptance"
    ),
)
def test_close_snapshot_owner_previews_confirms_and_reads_original_order_in_tui(
    live_owner_context: live_close_helpers.live_helpers._LiveOwnerContext,
    live_server: Any,
    subprocess_policy: None,
    _native_close_snapshot_browser_database: None,
    viewport: tuple[int, int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preserve_account_authority_generation: None,
) -> None:
    """Prove the current-clock close flow against an actual public Sina capture."""

    owner_context = live_owner_context
    desktop = viewport[0] > 500
    evidence = live_close_helpers._configure_close_snapshot_source(
        monkeypatch=monkeypatch,
        context=owner_context,
        account_id=int(owner_context.account.pk),
        scenario="tui-desktop" if desktop else "tui-narrow",
    )
    _run_close_snapshot_owner_browser_journey(
        owner_context=owner_context,
        evidence=evidence,
        live_server=live_server,
        viewport=viewport,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        journey_label="live-close-desktop" if desktop else "live-close-narrow",
        simulation_scope=(
            "current-clock public Sina HTTP capture; close-snapshot local simulation only"
        ),
        browser_clock_origin=None,
        simulation_clock_metadata={"mode": "actual_wall_clock"},
    )


@pytest.mark.parametrize(
    "viewport",
    [(1440, 1000), (390, 844)],
    ids=["desktop", "narrow"],
)
@pytest.mark.skipif(
    os.environ.get("AGOM_RUN_RETAINED_SINA_CLOSE_UI_ACCEPTANCE") != "1",
    reason=(
        "set AGOM_RUN_RETAINED_SINA_CLOSE_UI_ACCEPTANCE=1 for the controlled historical replay UI journey"
    ),
)
def test_retained_historical_close_snapshot_owner_previews_confirms_and_reads_order(
    _retained_close_historical_clock: _RetainedCloseReplay | None,
    live_owner_context: live_close_helpers.live_helpers._LiveOwnerContext,
    live_server: Any,
    subprocess_policy: None,
    _native_close_snapshot_browser_database: None,
    viewport: tuple[int, int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preserve_account_authority_generation: None,
    loopback_only_python_network: list[str],
) -> None:
    """Prove the close UI with an unchanged R9/R10 capture under a local history clock."""

    replay = _retained_close_historical_clock
    if replay is None:
        raise AssertionError("the opt-in retained replay clock fixture did not initialize")
    owner_context = live_owner_context
    evidence = _configure_retained_historical_close_source(
        monkeypatch=monkeypatch,
        context=owner_context,
        replay=replay,
    )
    desktop = viewport[0] > 500
    browser_clock_origin = replay.clock.now()
    if browser_clock_origin <= replay.capture.response_completed_at:
        raise AssertionError("controlled browser decision clock must follow original availability")
    _run_close_snapshot_owner_browser_journey(
        owner_context=owner_context,
        evidence=evidence,
        live_server=live_server,
        viewport=viewport,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        journey_label=(
            "retained-historical-close-desktop" if desktop else "retained-historical-close-narrow"
        ),
        simulation_scope=(
            "controlled historical replay of the original retained Sina HTTP response; "
            "no new source request; this does not qualify a current/live quote"
        ),
        browser_clock_origin=browser_clock_origin,
        simulation_clock_metadata={
            "mode": "monotonic_historical_offset",
            "clock_origin_utc": replay.clock.origin.isoformat(),
            "decision_started_at_utc": browser_clock_origin.isoformat(),
            "advances_with": "real_monotonic_elapsed_time",
        },
    )
    assert evidence.preflight_capture is replay.capture
    assert evidence.routed_captures == [replay.capture]
    assert evidence.routed_indexes == [replay.index_path]
    assert loopback_only_python_network == []


@pytest.fixture
def _native_close_snapshot_browser_database(django_db_use_migrations: bool) -> None:
    """Limit live close-source browser acceptance to an isolated Native PG database."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.fail("close-snapshot browser acceptance requires migrated Native PostgreSQL")
    if str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip().endswith(".production"):
        pytest.fail("close-snapshot browser acceptance is forbidden under production settings")
    assert_native_postgres_test_database()


def _run_close_snapshot_owner_browser_journey(
    *,
    owner_context: live_close_helpers.live_helpers._LiveOwnerContext,
    evidence: live_close_helpers._CloseSnapshotEvidence,
    live_server: Any,
    viewport: tuple[int, int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    journey_label: str,
    simulation_scope: str,
    browser_clock_origin: datetime | None,
    simulation_clock_metadata: dict[str, object],
) -> None:
    """Run one authenticated TUI preview, explicit confirm, and original readback."""

    preflight_quote = evidence.preflight_capture.quote
    assert preflight_quote is not None and preflight_quote.last_price is not None
    price = preflight_quote.last_price.quantize(Decimal("0.0001"))
    account = owner_context.account
    position = _persist_sell_position(account)
    position.current_price = price
    position.market_value = (price * position.quantity).quantize(Decimal("0.01"))
    position.unrealized_pnl = position.market_value - position.total_cost
    position.unrealized_pnl_pct = float(
        (position.unrealized_pnl / position.total_cost) * Decimal("100")
    )
    position.save(
        update_fields=("current_price", "market_value", "unrealized_pnl", "unrealized_pnl_pct")
    )
    account.current_market_value = position.market_value
    account.total_value = account.current_cash + position.market_value
    account.save(update_fields=("current_market_value", "total_value"))

    initial_state = _business_state(account, position)
    assert initial_state["reservation_count"] == 0
    assert initial_state["trade_count"] == 0
    client, csrf_token = _owner_session_client(owner_context.owner_id)
    session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    csrf_cookie = client.cookies[settings.CSRF_COOKIE_NAME].value
    assert csrf_cookie == csrf_token
    evidence_dir = tmp_path / "browser" / journey_label
    evidence_dir.mkdir(parents=True, exist_ok=True)

    simulated_tables = {
        model._meta.db_table.casefold()
        for model in apps.get_app_config("simulated_trading").get_models()
    }
    simulated_tables.add(PositionModel._meta.db_table.casefold())
    simulated_table_names = frozenset(simulated_tables)
    capture_simulated_dml = threading.Event()
    preview_simulated_dml: list[str] = []
    readback_simulated_dml: list[str] = []
    active_dml_log = preview_simulated_dml
    original_execute = CursorWrapper.execute
    original_executemany = CursorWrapper.executemany

    def observe_execute(
        cursor: CursorWrapper,
        sql: Any,
        params: Any = None,
    ) -> Any:
        """Detect SQL mutation during browser read-only stages."""

        if capture_simulated_dml.is_set() and _is_simulated_table_write(sql, simulated_table_names):
            active_dml_log.append(str(sql).lstrip().split(None, 1)[0].upper())
        return original_execute(cursor, sql, params)

    def observe_executemany(
        cursor: CursorWrapper,
        sql: Any,
        param_list: Any,
    ) -> Any:
        """Detect bulk SQL mutation during browser read-only stages."""

        if capture_simulated_dml.is_set() and _is_simulated_table_write(sql, simulated_table_names):
            active_dml_log.append(str(sql).lstrip().split(None, 1)[0].upper())
        return original_executemany(cursor, sql, param_list)

    monkeypatch.setattr(CursorWrapper, "execute", observe_execute)
    monkeypatch.setattr(CursorWrapper, "executemany", observe_executemany)

    browser_requests: list[dict[str, str]] = []
    preview_request_parameters: list[dict[str, object]] = []
    nonlocal_browser_attempts: list[str] = []
    page_errors: list[str] = []
    request_failures: list[str] = []
    confirmation_upstream: list[dict[str, object]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        browser_context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}
        )
        # Live acceptance keeps the real browser clock. Controlled replay installs
        # the same advancing historical offset used by the local server fixture.
        browser_context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": session_cookie,
                    "url": live_server.url,
                },
                {
                    "name": settings.CSRF_COOKIE_NAME,
                    "value": csrf_cookie,
                    "url": live_server.url,
                },
            ]
        )

        def local_only(route: Route) -> None:
            """Keep browser navigation and actions on the local test server."""

            target = urlsplit(route.request.url)
            expected = urlsplit(live_server.url)
            if target.scheme not in {"http", "https"} or target.netloc != expected.netloc:
                nonlocal_browser_attempts.append(route.request.url)
                route.abort("blockedbyclient")
                return
            route.continue_()

        def simulate_lost_confirm_response(route: Route) -> None:
            """Commit one local confirmation, then exercise TUI original-order recovery."""

            target = urlsplit(route.request.url)
            expected = urlsplit(live_server.url)
            if target.netloc != expected.netloc:
                nonlocal_browser_attempts.append(route.request.url)
                route.abort("blockedbyclient")
                return
            body = route.request.post_data_json
            if not isinstance(body, dict) or body.get("confirmed") is not True:
                route.continue_()
                return
            upstream = route.fetch()
            upstream_payload = upstream.json()
            upstream_response = (
                upstream_payload.get("response") if isinstance(upstream_payload, dict) else None
            )
            confirmation_upstream.append(
                {
                    "http_status": upstream.status,
                    "business_status": (
                        upstream_response.get("status_code")
                        if isinstance(upstream_response, dict)
                        else None
                    ),
                    "outcome": (
                        upstream_payload.get("outcome")
                        if isinstance(upstream_payload, dict)
                        else None
                    ),
                }
            )
            route.fulfill(
                status=502,
                content_type="application/json",
                body=json.dumps({"detail": "test-only browser response loss after local commit"}),
            )

        browser_context.route("**/*", local_only)
        browser_context.route(
            f"{live_server.url}{CONFIRM_ACTION_PATH}",
            simulate_lost_confirm_response,
        )
        page = browser_context.new_page()
        if browser_clock_origin is not None:
            page.clock.install(time=browser_clock_origin)
        browser_clock_sync_at = [time.monotonic()]

        def synchronize_browser_clock() -> None:
            """Advance only the controlled browser clock by real elapsed time."""

            if browser_clock_origin is None:
                return
            elapsed_ms = max(
                0,
                round((time.monotonic() - browser_clock_sync_at[0]) * 1000),
            )
            if elapsed_ms:
                page.clock.run_for(elapsed_ms)
                browser_clock_sync_at[0] = time.monotonic()

        def record_action_request(browser_request: Any) -> None:
            target = urlsplit(browser_request.url)
            if target.path not in {
                PREVIEW_ACTION_PATH,
                CONFIRM_ACTION_PATH,
                READBACK_ACTION_PATH,
            }:
                return
            browser_requests.append(
                {
                    "path": target.path,
                    "method": browser_request.method,
                    "idempotency_key": browser_request.headers.get("idempotency-key", ""),
                    "query": target.query,
                }
            )
            if target.path == PREVIEW_ACTION_PATH:
                body = browser_request.post_data_json
                params = body.get("params") if isinstance(body, dict) else None
                if isinstance(params, dict):
                    preview_request_parameters.append(
                        {
                            field: params.get(field)
                            for field in (
                                "quantity",
                                "limit_price",
                                "fee_budget",
                                "market_purpose",
                            )
                        }
                    )

        page.on("request", record_action_request)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda browser_request: request_failures.append(
                f"{browser_request.method} {browser_request.url}: {browser_request.failure}"
            ),
        )
        try:
            synchronize_browser_clock()
            page.goto(f"{live_server.url}/tui/?screen={SCREEN}", wait_until="networkidle")
            synchronize_browser_clock()
            panel = page.locator('[data-main-panel] [data-dashboard-panel="order-entry-intent"]')
            form = panel.locator("form.tui-action-form")
            expect(form).to_be_visible()
            account_select = form.locator('[name="account_id"]')
            expect(account_select.locator(f'option[value="{account.pk}"]')).to_have_count(1)
            account_select.select_option(value=str(account.pk))
            form.locator('[name="asset_code"]').fill(ASSET_CODE)
            form.locator('[name="asset_name"]').fill(ASSET_NAME)
            form.locator('[name="side"]').select_option("sell")
            form.locator('[name="quantity"]').fill("100")
            form.locator('[name="limit_price"]').fill(format(price, ".4f"))
            purpose_select = form.locator('[name="market_purpose"]')
            purpose_select.select_option("close_snapshot_simulation")
            expect(purpose_select).to_have_value("close_snapshot_simulation")

            capture_simulated_dml.set()
            try:
                synchronize_browser_clock()
                with page.expect_response(
                    lambda response: urlsplit(response.url).path == PREVIEW_ACTION_PATH
                ) as preview_response:
                    form.locator(".tui-action-submit").click()
            finally:
                capture_simulated_dml.clear()

            synchronize_browser_clock()
            preview_http = preview_response.value
            preview = preview_http.json()
            continuation = preview.get("continuation")
            continuation_input = (
                continuation.get("input") if isinstance(continuation, dict) else None
            )
            preview_token = (
                continuation_input.get("preview_token")
                if isinstance(continuation_input, dict)
                else None
            )
            params = preview_request_parameters[0] if len(preview_request_parameters) == 1 else None
            (evidence_dir / "preview-request-body.json").write_text(
                json.dumps({"params": params}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            safe_preview = dict(preview)
            if isinstance(continuation, dict):
                safe_continuation: dict[str, object] = {
                    key: continuation[key]
                    for key in ("action_key", "expires_at")
                    if key in continuation
                }
                if isinstance(continuation_input, dict):
                    safe_continuation["input"] = {
                        key: continuation_input[key]
                        for key in ("account_id", "order_key")
                        if key in continuation_input
                    }
                safe_preview["continuation"] = safe_continuation
            serialized_preview = json.dumps(safe_preview, ensure_ascii=False)
            assert type(preview_token) is str and preview_token
            assert preview_token not in serialized_preview
            _write_response_artifact(
                evidence_dir, "preview-response.json", preview_http.status, safe_preview
            )

            assert params == {
                "quantity": "100",
                "limit_price": format(price, ".4f"),
                "fee_budget": None,
                "market_purpose": "close_snapshot_simulation",
            }
            assert preview_http.status == 200
            assert preview.get("outcome") == "success"
            assert preview.get("response", {}).get("status_code") == 200
            assert preview.get("view_model", {}).get("outcome") == "success"
            assert preview_simulated_dml == []
            assert _business_state(account, position) == initial_state
            assert len(evidence.routed_captures) == 1

            preview_view = preview.get("view_model")
            assert isinstance(preview_view, dict)
            summary = preview_view.get("business_summary")
            assert type(summary) is str and summary
            preview_fields = {
                field["key"]: field.get("value")
                for field in preview_view.get("fields", [])
                if isinstance(field, dict) and type(field.get("key")) is str
            }
            routed_capture = evidence.routed_captures[0]
            routed_index = evidence.routed_indexes[0]
            routed_quote = routed_capture.quote
            assert routed_quote is not None and routed_quote.last_price is not None
            assert routed_quote.last_price == price
            close_at = datetime.combine(
                owner_context.uow.market_session,
                max(window.ends_at for window in owner_context.policy.session_windows),
                live_close_helpers.SHANGHAI,
            )
            live_close_helpers._assert_capture_clocks(
                capture=routed_capture,
                index_path=routed_index,
                expected_price=price,
                trade_date=owner_context.uow.market_session,
                close_at=close_at,
            )
            assert preview_fields.get("market_purpose") == "收盘快照模拟（非官方收盘价）"
            assert preview_fields.get("security_state") == "TRADING"
            assert preview_fields.get("session_state") == "已收市"
            assert preview_fields.get("trade_date") == owner_context.uow.market_session.isoformat()
            assert preview_fields.get("snapshot_kind") == "供应商收盘后末笔报价；不是官方收盘价"
            assert preview_fields.get("price_rule") == "仅限供应商末笔快照价"
            assert preview_fields.get("freshness") == "收盘快照（非实时、非新鲜报价）"
            assert preview_fields.get("must_not_use_for_decision") == "不得用于投资决策"
            assert preview_fields.get("must_not_execute") == "不得提交外部执行"
            assert Decimal(str(preview_fields["limit_price"])) == Decimal(
                str(preview_fields["reference_price"])
            )
            assert Decimal(str(preview_fields.get("reference_price"))) == routed_quote.last_price
            observed_at = _aware_datetime(preview_fields.get("market_observed_at"))
            available_at = _aware_datetime(preview_fields.get("market_available_at"))
            valid_until = _aware_datetime(preview_fields.get("market_valid_until"))
            assert observed_at == routed_quote.source_observed_at
            assert available_at == routed_capture.response_completed_at
            assert observed_at <= available_at < django_timezone.now()
            assert valid_until > django_timezone.now()
            for required_notice in (
                "非官方收盘价",
                "限价仅按该快照价用于本地模拟",
                "当前不是实时新鲜行情",
                "不会提交券商",
            ):
                assert required_notice in summary
            main_panel = page.locator("[data-main-panel]")
            expect(main_panel).to_contain_text("收盘快照模拟（非官方收盘价）")
            expect(main_panel).to_contain_text("不是官方收盘价")
            expect(main_panel).to_contain_text("不会提交券商")
            assert main_panel.evaluate("element => element.scrollWidth") <= viewport[0] + 1

            preview_keys = [
                item["idempotency_key"]
                for item in browser_requests
                if item["path"] == PREVIEW_ACTION_PATH
            ]
            assert len(preview_keys) == 1 and preview_keys[0]
            assert continuation.get("action_key") == "simulated-trading.order-confirm"
            assert isinstance(continuation_input, dict)
            assert set(continuation_input) == {"account_id", "order_key", "preview_token"}
            assert "market_purpose" not in continuation_input
            order_key = continuation_input.get("order_key")
            assert type(order_key) is str and order_key

            continue_button = page.get_by_role("button", name="继续：确认模拟订单预留", exact=True)
            expect(continue_button).to_be_visible()
            synchronize_browser_clock()
            with page.expect_response(
                lambda response: urlsplit(response.url).path == CONFIRM_ACTION_PATH
            ) as confirm_preflight_response:
                continue_button.click()
            confirm_preflight_http = confirm_preflight_response.value
            synchronize_browser_clock()
            confirm_preflight = confirm_preflight_http.json()
            _write_response_artifact(
                evidence_dir,
                "confirm-preflight-response.json",
                confirm_preflight_http.status,
                confirm_preflight,
            )
            assert confirm_preflight_http.status == 200
            assert confirm_preflight.get("confirmation_required") is True
            assert confirm_preflight.get("response", {}).get("status_code") == 409
            expect(page.locator("[data-tui-modal]")).to_be_visible()
            confirm_button = page.locator("[data-tui-modal] [data-confirm-action]")
            expect(confirm_button).to_be_visible()
            assert _business_state(account, position) == initial_state
            assert len(evidence.routed_captures) == 1

            synchronize_browser_clock()
            with page.expect_response(
                lambda response: urlsplit(response.url).path == CONFIRM_ACTION_PATH
            ) as lost_confirm_response:
                confirm_button.click()
            lost_confirm_http = lost_confirm_response.value
            synchronize_browser_clock()
            lost_confirm_body = lost_confirm_http.json()
            _write_response_artifact(
                evidence_dir,
                "confirm-browser-response.json",
                lost_confirm_http.status,
                lost_confirm_body,
            )
            assert lost_confirm_http.status == 502
            assert confirmation_upstream == [
                {"http_status": 200, "business_status": 200, "outcome": "success"}
            ]
            confirm_keys = [
                item["idempotency_key"]
                for item in browser_requests
                if item["path"] == CONFIRM_ACTION_PATH
            ]
            assert len(confirm_keys) == 2
            assert confirm_keys == [preview_keys[0], preview_keys[0]]

            reservations = run_sync_compatible(
                lambda: list(SimulatedOrderReservationModel.objects.filter(account_id=account.pk))
            )
            assert len(reservations) == 1
            reservation = reservations[0]
            assert reservation.idempotency_key == order_key
            assert reservation.owner_user_id == owner_context.owner_id
            assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
            assert reservation.side == "sell"
            assert reservation.quantity == Decimal("100")
            assert reservation.limit_price == price
            assert reservation.shares_reserved == Decimal("100")
            assert reservation.filled_quantity == Decimal("0")
            assert "submission_market" in reservation.plan_snapshot
            assert "close_snapshot_simulation" in json.dumps(
                reservation.plan_snapshot, ensure_ascii=False, sort_keys=True
            )
            after_confirm = _business_state(account, position)
            assert after_confirm["cash"] == initial_state["cash"]
            assert after_confirm["position_quantity"] == initial_state["position_quantity"]
            assert after_confirm["available_quantity"] == initial_state["available_quantity"]
            assert Decimal(str(after_confirm["active_sell_hold_quantity"])) == Decimal("100")
            assert Decimal(str(initial_state["free_sell_quantity"])) - Decimal(
                str(after_confirm["free_sell_quantity"])
            ) == Decimal("100")
            assert after_confirm["reservation_count"] == 1
            assert after_confirm["trade_count"] == 0
            expect(page.locator("[data-main-panel]")).to_contain_text("原请求结果待确认")
            page.screenshot(path=str(evidence_dir / "unknown-confirm.png"))

            readback_button = page.locator("[data-main-panel] [data-continuation-readback]")
            expect(readback_button).to_be_visible()
            active_dml_log = readback_simulated_dml
            capture_simulated_dml.set()
            try:
                synchronize_browser_clock()
                with page.expect_response(
                    lambda response: urlsplit(response.url).path == READBACK_ACTION_PATH
                ) as readback_response:
                    readback_button.click()
            finally:
                capture_simulated_dml.clear()

            synchronize_browser_clock()
            readback_http = readback_response.value
            readback = readback_http.json()
            _write_response_artifact(
                evidence_dir, "readback-response.json", readback_http.status, readback
            )
            assert readback_http.status == 200
            assert readback.get("outcome") == "success"
            assert readback.get("response", {}).get("status_code") == 200
            readback_action = readback.get("action")
            assert isinstance(readback_action, dict)
            assert readback_action.get("key") == "simulated-trading.order-by-key"
            assert readback_action.get("method") == "GET"
            readback_requests = [
                item for item in browser_requests if item["path"] == READBACK_ACTION_PATH
            ]
            assert len(readback_requests) == 1
            assert parse_qs(readback_requests[0]["query"], keep_blank_values=True) == {}
            assert [item["idempotency_key"] for item in readback_requests] == [preview_keys[0]]
            assert readback_simulated_dml == []
            assert len(evidence.routed_captures) == 1
            assert _business_state(account, position) == after_confirm

            readback_view = readback.get("view_model")
            assert isinstance(readback_view, dict)
            assert readback_view.get("outcome") == "success"
            readback_summary = readback_view.get("business_summary")
            assert type(readback_summary) is str
            assert "已找到同一原订单" in readback_summary
            assert "未重新读取行情或创建新单" in readback_summary
            readback_fields = {
                field["key"]: field.get("value")
                for field in readback_view.get("fields", [])
                if isinstance(field, dict) and type(field.get("key")) is str
            }
            assert int(readback_fields["order_id"]) == reservation.pk
            assert readback_fields["market_purpose"] == "收盘快照模拟（非官方收盘价）"
            assert Decimal(str(readback_fields["quantity"])) == Decimal("100")
            assert Decimal(str(readback_fields["filled_quantity"])) == Decimal("0")
            expect(page.locator("[data-main-panel]")).to_contain_text("已找到同一原订单")
            expect(page.locator("[data-main-panel]")).to_contain_text("收盘快照模拟")
            assert (
                page.locator("[data-main-panel]").evaluate("element => element.scrollWidth")
                <= viewport[0] + 1
            )
            page.screenshot(path=str(evidence_dir / "readback.png"))

            assert page_errors == []
            assert request_failures == []
            assert nonlocal_browser_attempts == []
            safe_evidence = {
                "case": journey_label,
                "screen": SCREEN,
                "viewport": {"width": viewport[0], "height": viewport[1]},
                "simulation_scope": simulation_scope,
                "simulation_clock": simulation_clock_metadata,
                "market_purpose": "close_snapshot_simulation",
                "source_access": (
                    "current public Sina HTTP capture"
                    if browser_clock_origin is None
                    else "same retained capture object replayed through a local test port; no HTTP"
                ),
                "trade_date": owner_context.uow.market_session.isoformat(),
                "source_observed_at": str(routed_quote.source_observed_at),
                "source_available_at": routed_capture.response_completed_at.isoformat(),
                "original_source_body_sha256": routed_capture.body_sha256,
                "original_source_capture_index": str(evidence.preflight_index),
                "exact_snapshot_price": str(price),
                "preview_summary": summary,
                "preview_request_params": params,
                "preview_simulated_table_dml": preview_simulated_dml,
                "confirm_upstream": confirmation_upstream,
                "readback": {
                    "action_key": readback_action["key"],
                    "method": readback_action["method"],
                    "market_purpose_source": "verified durable readback response",
                    "order_id": reservation.pk,
                    "status": readback_view.get("status"),
                },
                "final_business_state": after_confirm,
                "routed_capture_count": len(evidence.routed_captures),
                "page_errors": page_errors,
                "request_failures": request_failures,
                "nonlocal_browser_attempts": nonlocal_browser_attempts,
            }
            (evidence_dir / "journey.json").write_text(
                json.dumps(safe_evidence, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        finally:
            try:
                if not page.is_closed():
                    page.screenshot(
                        path=str(evidence_dir / "final-diagnostic.png"),
                        full_page=True,
                    )
            finally:
                browser_context.close()
                browser.close()

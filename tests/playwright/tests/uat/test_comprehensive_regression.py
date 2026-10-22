"""
Comprehensive Playwright UAT regression coverage for key user-facing surfaces.

This suite replaces the old root-level smoke script with collected pytest tests
that reuse the shared Playwright fixtures, markers, and failure screenshot flow.
"""

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from playwright.sync_api import (
    Page,
    Response,
)
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tests.playwright.config.test_config import config
from tests.playwright.tests.smoke.test_critical_paths import (
    _assert_asset_analysis_contract,
    _assert_audit_contract,
    _assert_backtest_contract,
    _assert_box_size,
    _assert_card_style,
    _assert_dashboard_contract,
    _assert_equity_contract,
    _assert_filter_contract,
    _assert_fund_contract,
    _assert_macro_contract,
    _assert_min_count,
    _assert_page_shell,
    _assert_policy_contract,
    _assert_regime_contract,
    _assert_rotation_contract,
    _assert_signal_contract,
    _assert_simulated_trading_contract,
    _wait_for_non_placeholder_text,
)

REMOTE_UAT_RUN_ID = os.environ.get("AGOM_REMOTE_UAT_RUN_ID", "").strip()
REMOTE_UAT_ACCOUNT_IDS = os.environ.get("AGOM_REMOTE_UAT_ACCOUNT_IDS", "").strip()


def _expected_rc_playwright_settings_module() -> str:
    """Use the M5 overlay only when the calendar fixture is explicitly enabled."""

    if os.environ.get("AGOM_M5_SYNTHETIC_CALENDAR", "").strip() == "1":
        return "tests.settings.m5_playwright"
    return "core.settings.playwright"


def _remote_uat_active() -> bool:
    """Return whether this run targets explicitly provisioned remote fixtures."""

    hostname = (urlparse(config.base_url).hostname or "").lower()
    return bool(REMOTE_UAT_RUN_ID) and hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
        "testserver",
    }


def _uat_suffix() -> str:
    """Return a stable per-run suffix remotely and a random suffix locally."""

    if REMOTE_UAT_RUN_ID:
        return re.sub(r"[^A-Za-z0-9]", "", REMOTE_UAT_RUN_ID)[:8]
    return uuid4().hex[:8]


def _remote_account_ids() -> dict[str, int]:
    """Return explicit remote account fixtures keyed by their generated names."""

    if not REMOTE_UAT_ACCOUNT_IDS:
        return {}
    payload = json.loads(REMOTE_UAT_ACCOUNT_IDS)
    return {str(key): int(value) for key, value in payload.items()}


PUBLIC_SURFACES = [
    pytest.param("/", None, id="home"),
    pytest.param(config.login_url, config.login_url, id="login"),
    pytest.param("/api/docs/", "/api/docs/", id="swagger"),
    pytest.param("/api/redoc/", "/api/redoc/", id="redoc"),
]

PROTECTED_ENTRYPOINTS = [
    pytest.param(config.dashboard_url, id="dashboard"),
    pytest.param(config.policy_manage_url, id="policy-workbench"),
    pytest.param("/decision/workspace/", id="decision-workspace"),
    pytest.param("/settings/", id="settings-center"),
]

AUTHENTICATED_SURFACES = [
    pytest.param(config.dashboard_url, "/tui/", id="dashboard"),
    pytest.param(config.macro_data_url, "/macro/", id="macro-data"),
    pytest.param(config.regime_dashboard_url, "/regime/", id="regime-dashboard"),
    pytest.param(config.signal_manage_url, "/signal/", id="signal-manage"),
    pytest.param(config.policy_manage_url, "/policy/workbench/", id="policy-workbench"),
    pytest.param(config.equity_screen_url, "/equity/", id="equity-screen"),
    pytest.param(config.fund_dashboard_url, "/fund/", id="fund-dashboard"),
    pytest.param(config.asset_analysis_screen_url, "/asset-analysis/", id="asset-analysis"),
    pytest.param(config.backtest_create_url, "/backtest/", id="backtest"),
    pytest.param(
        config.simulated_trading_dashboard_url, "/simulated-trading/", id="simulated-trading"
    ),
    pytest.param(config.audit_reports_url, "/audit/", id="audit"),
    pytest.param(config.filter_manage_url, "/filter/", id="filter"),
    pytest.param(config.sector_analysis_url, "/rotation/assets/", id="sector"),
    pytest.param("/decision/workspace/", "/decision/workspace/", id="decision-workspace"),
    pytest.param("/settings/", "/settings/", id="settings-center"),
    pytest.param(config.admin_index, "/admin/", id="admin-index"),
]

NON_PAGE_LINK_PREFIXES = (
    "/api/",
    "/static/",
    "/media/",
    "/admin/logout/",
    "/account/logout/",
)

SURFACE_CONTRACTS = {
    config.dashboard_url: _assert_dashboard_contract,
    config.macro_data_url: _assert_macro_contract,
    config.regime_dashboard_url: _assert_regime_contract,
    config.signal_manage_url: _assert_signal_contract,
    config.policy_manage_url: _assert_policy_contract,
    config.equity_screen_url: _assert_equity_contract,
    config.fund_dashboard_url: _assert_fund_contract,
    config.asset_analysis_screen_url: _assert_asset_analysis_contract,
    config.backtest_create_url: _assert_backtest_contract,
    config.simulated_trading_dashboard_url: _assert_simulated_trading_contract,
    config.audit_reports_url: _assert_audit_contract,
    config.filter_manage_url: _assert_filter_contract,
    config.sector_analysis_url: _assert_rotation_contract,
}


def _goto(page: Page, path: str) -> Response | None:
    """Navigate with route-aware readiness and retry transient connection refusal."""
    requested_path = urlparse(urljoin(config.base_url, path)).path
    signal_manage_path = urlparse(urljoin(config.base_url, config.signal_manage_url)).path
    wait_until = "domcontentloaded" if requested_path == signal_manage_path else "networkidle"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return page.goto(
                f"{config.base_url}{path}",
                wait_until=wait_until,
                timeout=config.navigation_timeout,
            )
        except Exception as exc:
            last_error = exc
            if "ERR_CONNECTION_REFUSED" not in str(exc) or attempt == 2:
                raise
            page.wait_for_timeout(1000)
    if last_error:
        raise last_error
    return None


def _assert_http_success(response: Response | None, path: str) -> None:
    """Assert the final browser navigation resolves to a non-error HTTP response."""
    assert response is None or response.status < 400, f"{path} returned HTTP {response.status}"


def _assert_non_error_shell(page: Page, expected_path_fragment: str | None = None) -> None:
    """Assert the rendered page is not a 404/500 shell and has visible content."""
    page.wait_for_load_state("networkidle")
    body_text = page.locator("body").inner_text(timeout=5000)

    assert body_text.strip(), "Page body should not be empty"
    assert "/404/" not in page.url, f"Unexpected 404 page: {page.url}"
    assert "Page not found" not in body_text
    assert "Server Error (500)" not in body_text
    assert "Traceback" not in body_text

    if expected_path_fragment:
        assert (
            expected_path_fragment in page.url
        ), f"Expected path fragment {expected_path_fragment!r}, got {page.url!r}"


def _assert_login_redirect(page: Page, path: str) -> None:
    """Assert a protected route redirects unauthenticated users to a login page."""
    _goto(page, path)
    current_url = page.url.lower()
    assert (
        "login" in current_url or "/account/" in current_url
    ), f"Expected auth redirect for {path}, got {page.url}"
    _assert_non_error_shell(page, "/login/")


def _assert_surface_contract(
    page: Page, path: str, expected_path_fragment: str | None = None
) -> None:
    """Assert a known page-specific contract when available, else fall back to shell checks."""
    contract = SURFACE_CONTRACTS.get(path)
    if contract is not None:
        contract(page)
        return

    _assert_non_error_shell(page, expected_path_fragment)


def _assert_decision_workspace_contract(page: Page) -> None:
    """Assert the decision workspace renders account context and the funnel shell."""
    _assert_page_shell(page, "/decision/workspace/")
    assert "/decision/workspace/" in page.url
    _wait_for_non_placeholder_text(page, ".funnel-title")
    _assert_min_count(page, ".workspace-kpi", 6)
    _assert_min_count(page, ".step-button", 6)
    _assert_min_count(page, ".workspace-sidebar-card", 3)
    _assert_card_style(page, ".workspace-sidebar-card")
    _assert_card_style(page, ".funnel-stepper")
    _assert_box_size(page, ".funnel-content-area", min_width=400, min_height=220)


def _assert_ops_center_contract(page: Page) -> None:
    """Assert settings center exposes filter controls and configuration cards."""
    _assert_page_shell(page, "/settings/")
    _wait_for_non_placeholder_text(page, "h1")
    _assert_min_count(page, ".config-card", 3)
    _assert_box_size(page, "#config-search", min_width=180, min_height=36)
    _assert_box_size(page, "#config-section-filter", min_width=180, min_height=36)
    _assert_box_size(page, "#config-status-filter", min_width=180, min_height=36)
    _assert_card_style(page, ".config-card")


def _assert_terminal_contract(page: Page) -> None:
    """Assert terminal page exposes interactive shell controls and sidebar tools."""
    _assert_page_shell(page, "/terminal/")
    _wait_for_non_placeholder_text(page, ".terminal-title")
    _assert_box_size(page, "#terminal-input", min_width=300, min_height=20)
    _assert_min_count(page, ".quick-cmd-btn", 5)
    _assert_box_size(page, "#provider-select", min_width=120, min_height=32)
    _assert_box_size(page, "#model-select", min_width=120, min_height=32)
    _assert_box_size(page, "#terminal-mode-select", min_width=120, min_height=32)
    _assert_card_style(page, ".terminal-window")


def _assert_simulated_accounts_contract(page: Page) -> None:
    """Assert my-accounts page exposes account cards or a clear empty state plus modal shell."""
    _assert_page_shell(page, "/simulated-trading/")
    _wait_for_non_placeholder_text(page, "h1")
    _assert_box_size(page, 'button:has-text("创建新账户")', min_width=100, min_height=32)
    _wait_for_non_placeholder_text(page, "#selectedAccountCount", disallowed=("",))
    assert page.locator("#createModal").count() == 1
    assert (
        page.locator(".account-card").count() > 0
        or page.locator("text=您还没有创建任何账户").count() == 1
    ), "Account page should show cards or a clear empty state"
    if page.locator(".account-card").count() > 0:
        _assert_card_style(page, ".account-card")


SURFACE_CONTRACTS.update(
    {
        "/decision/workspace/": _assert_decision_workspace_contract,
        "/settings/": _assert_ops_center_contract,
        "/terminal/": _assert_terminal_contract,
        config.simulated_trading_positions_url: _assert_simulated_accounts_contract,
    }
)


def _collect_internal_paths(page: Page, limit: int = 5) -> list[str]:
    """Collect a small, stable set of internal HTML page links from the current page."""
    hrefs = page.eval_on_selector_all(
        "a[href]",
        "elements => elements.map(element => element.getAttribute('href') || '')",
    )
    base_netloc = urlparse(config.base_url).netloc
    paths: list[str] = []

    for href in hrefs:
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        parsed = urlparse(urljoin(config.base_url, href))
        if parsed.netloc and parsed.netloc != base_netloc:
            continue

        path = parsed.path or "/"
        if any(path.startswith(prefix) for prefix in NON_PAGE_LINK_PREFIXES):
            continue
        if path in paths:
            continue

        paths.append(path)
        if len(paths) >= limit:
            break

    return paths


def _assert_paths_are_navigable(
    page: Page, paths: list[str], allow_login_redirect: bool = False
) -> None:
    """Assert each discovered path can be opened without landing on an error shell."""
    assert paths, "Expected at least one internal link to validate"

    for path in paths:
        response = _goto(page, path)
        _assert_http_success(response, path)
        if allow_login_redirect and "login" in page.url.lower():
            _assert_non_error_shell(page, "/login/")
            continue
        _assert_non_error_shell(page)


def _run_db_operation(django_db_blocker, operation):
    """Run ORM setup/cleanup in a worker thread and close SQLite connections deterministically."""

    def _wrapped():
        with django_db_blocker.unblock():
            from django.db import close_old_connections, connections

            close_old_connections()
            try:
                return operation()
            finally:
                connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_wrapped)
        return future.result()


def _prepare_signal_indicator_fixture(base_url: str, django_db_blocker: object) -> str | None:
    """Create a preconfigured synthetic macro.fact UI fixture in opted-in RC SQLite only.

    The real catalog normalizer, macro publisher, query and freshness gate run.
    The test-only current pointer does not model activation, Account fencing,
    RawAudit evidence, or production UAT approval.
    """

    if os.environ.get("AGOM_SIGNAL_RC_FIXTURE_SEED", "").strip() != "1":
        return None

    parsed_url = urlparse(base_url)
    try:
        is_loopback_ip = ip_address((parsed_url.hostname or "").strip()).is_loopback
    except ValueError:
        is_loopback_ip = False
    if parsed_url.scheme != "http" or not is_loopback_ip:
        raise RuntimeError("Signal RC fixture requires an HTTP URL on a loopback IP")
    expected_settings_module = _expected_rc_playwright_settings_module()
    if os.environ.get("DJANGO_SETTINGS_MODULE", "").strip() != expected_settings_module:
        raise RuntimeError("Signal RC fixture requires the selected isolated settings module")
    if any(
        os.environ.get(name, "").strip()
        for name in ("AGOM_REMOTE_UAT_RUN_ID", "AGOM_REMOTE_UAT_ACCOUNT_IDS")
    ):
        raise RuntimeError("Signal RC fixture refuses remote UAT credentials or scope")

    runner_temp = os.environ.get("RUNNER_TEMP", "").strip()
    configured_path = os.environ.get("AGOM_PLAYWRIGHT_DB_PATH", "").strip()
    if (
        os.environ.get("GITHUB_ACTIONS", "").strip().lower() != "true"
        or os.environ.get("CI", "").strip().lower() != "true"
        or not runner_temp
        or not configured_path
    ):
        raise RuntimeError("Signal RC fixture requires a disposable GitHub Actions runner database")
    runner_temp_path = Path(runner_temp).expanduser().resolve()
    expected_database_path = (runner_temp_path / "agomtradepro-rc-playwright.sqlite3").resolve()
    if Path(configured_path).expanduser().resolve() != expected_database_path:
        raise RuntimeError("Signal RC fixture database must be the fixed file under RUNNER_TEMP")

    def _seed() -> str:
        from django.conf import settings
        from django.core.management import call_command
        from django.db import connection
        from django.utils import timezone

        database = settings.DATABASES["default"]
        test_database = database.get("TEST", {})
        default_name = str(database.get("NAME", "")).strip()
        test_name = str(test_database.get("NAME", "")).strip()
        default_path = Path(default_name).expanduser().resolve() if default_name else None
        test_path = Path(test_name).expanduser().resolve() if test_name else None
        if (
            database.get("ENGINE") != "django.db.backends.sqlite3"
            or connection.vendor != "sqlite"
            or default_path != expected_database_path
            or test_path != expected_database_path
        ):
            raise RuntimeError("Signal RC fixture refused a non-disposable Playwright database")

        call_command("initialize_data_center_catalog", verbosity=0)

        from apps.data_center.application.macro_fact_governance import (
            MacroFactGovernanceNormalizer,
        )
        from apps.data_center.application.macro_publication import PublishMacroBatchUseCase
        from apps.data_center.application.public import list_published_macro_indicator_summaries
        from apps.data_center.application.public_published_queries import save_macro_facts
        from apps.data_center.application.publication_utils import (
            publication_hash,
            publication_member_from_reference,
        )
        from apps.data_center.application.query_services import query_published_macro_fact_series
        from apps.data_center.composition import (
            get_canonical_publication_repository,
            get_indicator_catalog_repository,
            get_indicator_unit_rule_repository,
            get_macro_fact_repository,
            get_publication_policy_repository,
        )
        from apps.data_center.domain.control_plane import (
            PublicationFactReference,
            PublicationMember,
        )
        from apps.data_center.domain.entities import MacroFact
        from apps.data_center.domain.enums import DataQualityStatus
        from apps.data_center.domain.publication_snapshot_policy import (
            publication_selected_source_summary,
        )
        from apps.data_center.infrastructure.macro_fact_selection import (
            configured_macro_source,
        )
        from apps.data_center.infrastructure.models import MacroFactModel
        from apps.data_center.infrastructure.publication_rollback_models import (
            CanonicalPublicationModel,
            CanonicalPublicationPointerModel,
            CoverageSnapshotModel,
            PublicationMemberModel,
        )

        indicator_code = "CN_CPI_FOOD"
        source_name = "signal-rc-fixture"
        source_date = timezone.localdate()
        reporting_period = date(source_date.year, source_date.month, 1)
        source_record_id = (
            f"synthetic:{source_name}:{indicator_code}:"
            f"{reporting_period.isoformat()}:{source_date.isoformat()}"
        )
        raw_payload_hash = hashlib.sha256(
            json.dumps(
                {
                    "synthetic_fixture": True,
                    "fixture_name": "signal-rc-preconfigured-local-only",
                    "indicator_code": indicator_code,
                    "reporting_period": reporting_period.isoformat(),
                    "source": source_name,
                    "source_published_date": source_date.isoformat(),
                    "source_record_id": source_record_id,
                    "value": 2.0,
                    "unit_kind": "catalog_default_unit",
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        run_id = str(
            uuid5(
                NAMESPACE_URL,
                f"signal-rc-preconfigured-fixture:{source_record_id}:{raw_payload_hash}",
            )
        )
        fixture_extra = {
            "synthetic_fixture": True,
            "fixture_name": "signal-rc-preconfigured-local-only",
        }

        catalog_repository = get_indicator_catalog_repository()
        catalog = catalog_repository.get_by_code(indicator_code)
        if catalog is None or not catalog.is_active or not catalog.default_unit:
            raise AssertionError("CN_CPI_FOOD must be active with its migrated default unit")
        if not isinstance(catalog.extra, dict):
            raise AssertionError("CN_CPI_FOOD catalog metadata must be a JSON object")
        if catalog.extra.get("alias_of_indicator_code") or configured_macro_source(catalog.extra):
            raise AssertionError(
                "CN_CPI_FOOD must be a non-alias without a real-source requirement"
            )
        visible_codes = [
            item.code
            for item in sorted(catalog_repository.list_active(), key=lambda item: item.code)[:50]
        ]
        if indicator_code not in visible_codes:
            raise AssertionError("CN_CPI_FOOD is outside the published-indicator frontend limit")

        unit_rule_repository = get_indicator_unit_rule_repository()
        unit_rule = unit_rule_repository.resolve_active_rule(
            indicator_code,
            source_type=source_name,
            original_unit=catalog.default_unit,
        )
        if unit_rule is None or unit_rule.storage_unit != catalog.default_unit:
            raise AssertionError("CN_CPI_FOOD needs its existing migrated default-unit rule")
        publication_repository = get_canonical_publication_repository()
        policy_repository = get_publication_policy_repository()
        policy = policy_repository.get_active("macro.fact")
        if policy is None or policy.dataset.value != "macro.fact":
            raise AssertionError("The official bootstrap did not install the macro.fact policy")
        normalizer = MacroFactGovernanceNormalizer(catalog_repository, unit_rule_repository)

        def _normalized_fact(fetched_at: datetime) -> MacroFact:
            """Normalize one deterministic test fact while retaining its acquisition time."""

            fact = MacroFact(
                indicator_code=indicator_code,
                reporting_period=reporting_period,
                value=2.0,
                unit=catalog.default_unit,
                source=source_name,
                revision_number=0,
                published_at=source_date,
                quality=DataQualityStatus.VALID,
                fetched_at=fetched_at,
                extra=dict(fixture_extra),
                ingested_run_id=run_id,
            )
            return normalizer.normalize(
                fact,
                source_type=source_name,
                provider_name="synthetic local Playwright UI fixture",
            )

        def _identity(
            fact: MacroFact,
        ) -> tuple[PublicationFactReference, str, str, str]:
            """Compute the same publication digest and UUID as the canonical publisher."""

            references = get_macro_fact_repository().list_publication_candidates([fact])
            if len(references) != 1:
                raise AssertionError("The exact synthetic fact lacks one publication reference")
            reference = references[0]
            digest = publication_hash(
                references,
                policy_identity=policy.identity if policy.uses_versioned_evidence else None,
            )
            publication_id = str(
                uuid5(NAMESPACE_URL, f"agomtradepro:macro.fact:{indicator_code}:{digest}")
            )
            selected_source = (
                publication_selected_source_summary(references)
                if policy.uses_versioned_evidence
                else source_name
            )
            return reference, digest, publication_id, selected_source

        def _member(
            reference: PublicationFactReference,
            publication_id: str,
        ) -> PublicationMember:
            """Build the deterministic canonical member used by the publisher."""

            member_id = str(uuid5(uuid5(NAMESPACE_URL, publication_id), reference.natural_key))
            return publication_member_from_reference(
                reference,
                member_id=member_id,
                publication_id=publication_id,
                dataset_key="macro.fact",
            )

        def _validate_publication(
            fact: MacroFact,
        ) -> tuple[CanonicalPublicationModel | None, str, str, PublicationFactReference]:
            """Reject every non-fixture publication or member in this indicator scope."""

            reference, digest, publication_id, selected_source = _identity(fact)
            rows = list(
                CanonicalPublicationModel._default_manager.filter(
                    dataset_key="macro.fact",
                    publication_key=indicator_code,
                ).order_by("publication_id")
            )
            all_members = list(
                PublicationMemberModel._default_manager.filter(
                    dataset_key="macro.fact",
                    natural_key__startswith=f"{indicator_code}:",
                ).order_by("publication_id", "natural_key")
            )
            if not rows:
                if all_members:
                    raise RuntimeError("Refusing orphan or differently-scoped macro.fact members")
                return None, digest, publication_id, reference
            if len(rows) != 1:
                raise RuntimeError("Refusing multiple CN_CPI_FOOD publication snapshots")

            row = rows[0]
            if (
                str(row.publication_id) != publication_id
                or row.dataset_key != "macro.fact"
                or row.publication_key != indicator_code
                or row.policy_version != policy.identity
                or row.state != "published"
                or row.selected_source != selected_source
                or row.publication_hash != digest
                or row.member_count != 1
                or row.conflict_count != 0
                or row.coverage_requested_count != 1
                or row.coverage_eligible_count != 1
                or row.coverage_selected_count != 1
                or row.coverage_missing_count != 0
                or row.coverage_conflict_count != 0
                or row.as_of != reference.observed_at
                or row.must_not_use_for_decision
                or row.blocked_reason
                or row.created_by != "sync.macro_fact"
                or str(row.run_id or "") != run_id
                or row.scope_blocks != []
                or row.superseded_at is not None
                or row.reinstated_at is not None
                or row.published_at is None
                or row.published_at < reference.observed_at
                or row.published_at > timezone.now()
            ):
                raise RuntimeError("Refusing a non-fixture or invalid macro.fact publication")
            expected_member = _member(reference, publication_id)
            members = list(
                PublicationMemberModel._default_manager.filter(
                    publication_id=row.publication_id
                ).order_by("natural_key")
            )
            if (
                len(members) != 1
                or members[0].to_domain() != expected_member
                or len(all_members) != 1
                or all_members[0].to_domain() != expected_member
            ):
                raise RuntimeError("Refusing non-fixture or mismatched publication members")
            expected_coverage_id = str(uuid5(NAMESPACE_URL, f"coverage:{publication_id}"))
            coverage = list(
                CoverageSnapshotModel._default_manager.filter(publication_id=row.publication_id)
            )
            if (
                len(coverage) != 1
                or str(coverage[0].coverage_id) != expected_coverage_id
                or coverage[0].requested_count != 1
                or coverage[0].eligible_count != 1
                or coverage[0].selected_count != 1
                or coverage[0].missing_count != 0
                or coverage[0].conflict_count != 0
                or coverage[0].generated_at != row.published_at
            ):
                raise RuntimeError("Refusing incomplete synthetic publication coverage")
            return row, digest, publication_id, reference

        def _validate_pointer(publication_id: str, digest: str, publication_exists: bool) -> None:
            """Accept only an empty pointer or the exact preconfigured test pointer."""

            pointers = list(
                CanonicalPublicationPointerModel._default_manager.filter(
                    dataset_key="macro.fact",
                    publication_key=indicator_code,
                ).order_by("pointer_id")
            )
            if len(pointers) > 1:
                raise RuntimeError("Refusing ambiguous CN_CPI_FOOD publication pointers")
            if not pointers:
                return
            pointer = pointers[0]
            empty = (
                pointer.publication_id is None
                and pointer.publication_hash == ""
                and pointer.activation_id == ""
            )
            exact = (
                publication_exists
                and str(pointer.publication_id or "") == publication_id
                and pointer.publication_hash == digest
                and pointer.activation_id == ""
            )
            if not empty and not exact:
                raise RuntimeError("Refusing a non-fixture, activated, or partial current pointer")

        fact_rows = list(
            MacroFactModel._default_manager.filter(indicator_code=indicator_code).order_by("pk")
        )
        if len(fact_rows) > 1:
            raise RuntimeError(
                "Refusing to seed when CN_CPI_FOOD has non-fixture or duplicate facts"
            )
        stored_fact = fact_rows[0] if fact_rows else None

        if stored_fact is None:
            normalized_fact = _normalized_fact(timezone.now())
            pubs = list(
                CanonicalPublicationModel._default_manager.filter(
                    dataset_key="macro.fact",
                    publication_key=indicator_code,
                )
            )
            member_exists = PublicationMemberModel._default_manager.filter(
                dataset_key="macro.fact",
                natural_key__startswith=f"{indicator_code}:",
            ).exists()
            _validate_pointer("", "", False)
            if pubs or member_exists:
                raise RuntimeError("Refusing publication history without its exact synthetic fact")
        else:
            if (
                stored_fact.indicator_code != indicator_code
                or stored_fact.reporting_period != reporting_period
                or stored_fact.source != source_name
                or stored_fact.revision_number != 0
                or stored_fact.published_at != source_date
                or stored_fact.source_record_id != source_record_id
                or stored_fact.raw_payload_hash != raw_payload_hash
                or str(stored_fact.ingested_run_id or "") != run_id
                or stored_fact.quality != DataQualityStatus.VALID.value
                or stored_fact.quality_status != "accepted"
                or stored_fact.available_at is None
                or stored_fact.available_at != stored_fact.fetched_at
            ):
                raise RuntimeError("Refusing to overwrite non-fixture or stale CN_CPI_FOOD data")
            for timestamp in (stored_fact.available_at, stored_fact.fetched_at):
                if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    raise RuntimeError(
                        "Synthetic acquisition timestamps must remain timezone-aware"
                    )
            if stored_fact.fetched_at > timezone.now():
                raise RuntimeError("Synthetic acquisition time cannot be in the future")
            normalized_fact = _normalized_fact(stored_fact.fetched_at)
            if (
                stored_fact.value != Decimal(str(normalized_fact.value))
                or stored_fact.unit != normalized_fact.unit
                or stored_fact.extra != normalized_fact.extra
            ):
                raise RuntimeError("Existing synthetic fact content no longer matches its identity")
            publication_row, digest, publication_id, _ = _validate_publication(normalized_fact)
            _validate_pointer(
                digest=digest,
                publication_id=publication_id,
                publication_exists=publication_row is not None,
            )

        if stored_fact is None:
            if save_macro_facts([normalized_fact]) != 1:
                raise AssertionError("The synthetic macro fact was not persisted")
            stored_fact = MacroFactModel._default_manager.get(
                indicator_code=indicator_code,
                reporting_period=reporting_period,
                source=source_name,
                revision_number=0,
            )
            updated = MacroFactModel._default_manager.filter(
                pk=stored_fact.pk,
                source_record_id="",
                raw_payload_hash="",
                available_at__isnull=True,
            ).update(
                source_record_id=source_record_id,
                raw_payload_hash=raw_payload_hash,
                available_at=stored_fact.fetched_at,
            )
            if updated != 1:
                raise AssertionError(
                    "The new synthetic source evidence was not initialized exactly"
                )
            stored_fact.refresh_from_db()
            if (
                stored_fact.available_at is None
                or stored_fact.available_at != stored_fact.fetched_at
                or stored_fact.indicator_code != indicator_code
                or stored_fact.reporting_period != reporting_period
                or stored_fact.source != source_name
                or stored_fact.revision_number != 0
                or stored_fact.published_at != source_date
                or stored_fact.source_record_id != source_record_id
                or stored_fact.raw_payload_hash != raw_payload_hash
                or str(stored_fact.ingested_run_id or "") != run_id
                or stored_fact.quality != DataQualityStatus.VALID.value
                or stored_fact.quality_status != "accepted"
                or stored_fact.value != Decimal(str(normalized_fact.value))
                or stored_fact.unit != normalized_fact.unit
                or stored_fact.extra != normalized_fact.extra
            ):
                raise AssertionError("The persisted synthetic fact does not match its identity")
            for timestamp in (stored_fact.available_at, stored_fact.fetched_at):
                if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    raise AssertionError("The synthetic fact needs aware acquisition timestamps")
            normalized_fact = _normalized_fact(stored_fact.fetched_at)

        publication_row, digest, publication_id, reference = _validate_publication(normalized_fact)
        _validate_pointer(
            digest=digest,
            publication_id=publication_id,
            publication_exists=publication_row is not None,
        )
        if publication_row is None:
            published = PublishMacroBatchUseCase(
                fact_repository=get_macro_fact_repository(),
                publication_repository=publication_repository,
                policy_repository=policy_repository,
            ).execute(
                [normalized_fact],
                provider_name=source_name,
                publication_key=indicator_code,
                run_id=run_id,
                published_at=timezone.now(),
            )
            if (
                published is None
                or published.publication_id != publication_id
                or published.publication_hash != digest
            ):
                raise AssertionError("The canonical publisher returned an unexpected fixture")
        publication_row, digest, publication_id, reference = _validate_publication(normalized_fact)
        if publication_row is None:
            raise AssertionError("The canonical synthetic publication was not persisted")

        pointer, _ = CanonicalPublicationPointerModel._default_manager.get_or_create(
            dataset_key="macro.fact",
            publication_key=indicator_code,
            defaults={"publication_id": None, "publication_hash": "", "activation_id": ""},
        )
        if (
            str(pointer.publication_id or "") != publication_id
            or pointer.publication_hash != digest
            or pointer.activation_id
        ):
            updated = CanonicalPublicationPointerModel._default_manager.filter(
                pointer_id=pointer.pointer_id,
                publication_id__isnull=True,
                publication_hash="",
                activation_id="",
            ).update(
                publication_id=publication_row.publication_id,
                publication_hash=digest,
                updated_at=timezone.now(),
            )
            if updated != 1:
                pointer.refresh_from_db()
                if (
                    str(pointer.publication_id or "") != publication_id
                    or pointer.publication_hash != digest
                    or pointer.activation_id
                ):
                    raise RuntimeError("The synthetic current pointer changed during setup")
        pointer = CanonicalPublicationPointerModel._default_manager.get(
            dataset_key="macro.fact",
            publication_key=indicator_code,
        )
        if (
            str(pointer.publication_id or "") != publication_id
            or pointer.publication_hash != digest
            or pointer.activation_id
        ):
            raise AssertionError("The preconfigured synthetic pointer did not persist")
        current = publication_repository.get_current("macro.fact", indicator_code)
        if (
            current is None
            or current.publication_id != publication_id
            or current.publication_hash != digest
        ):
            raise AssertionError("The synthetic pointer did not resolve to its publication")

        query = query_published_macro_fact_series(indicator_code, publication_key=indicator_code)
        if query.get("must_not_use_for_decision") is not False:
            raise AssertionError("The synthetic publication did not pass its freshness gate")
        rows = query.get("rows")
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise AssertionError("The freshness-gated macro query did not return one synthetic row")
        row = rows[0]
        if (
            row.get("indicator_code") != indicator_code
            or row.get("source") != source_name
            or row.get("reporting_period") != reporting_period.isoformat()
            or float(row.get("value", -1)) != 2.0
        ):
            raise AssertionError("The freshness-gated query returned unexpected synthetic data")
        summaries = list_published_macro_indicator_summaries()
        if not any(
            isinstance(summary, dict) and summary.get("code") == indicator_code
            for summary in summaries
        ):
            raise AssertionError("The published macro summary omitted CN_CPI_FOOD")
        return indicator_code

    return _run_db_operation(django_db_blocker, _seed)


def _cleanup_signal(asset_code: str, django_db_blocker) -> None:
    """Delete a created signal by unique asset code."""

    if _remote_uat_active():
        return

    def _delete() -> None:
        from apps.signal.infrastructure.models import InvestmentSignalModel

        InvestmentSignalModel.objects.filter(asset_code=asset_code).delete()

    _run_db_operation(django_db_blocker, _delete)


def _seed_signal(asset_code: str, django_db_blocker, *, status: str = "pending") -> None:
    """Create a deterministic signal owned by the Playwright admin user."""

    if _remote_uat_active():
        return

    def _create() -> None:
        from django.contrib.auth import get_user_model

        from apps.signal.infrastructure.models import InvestmentSignalModel

        user = get_user_model().objects.get(username=config.admin_username)
        InvestmentSignalModel.objects.create(
            user=user,
            asset_code=asset_code,
            asset_class="EQUITY",
            direction="LONG",
            logic_desc=f"Seeded Playwright signal {asset_code}",
            invalidation_logic="CN_PMI < 49",
            invalidation_description="CN_PMI < 49",
            invalidation_rules={
                "conditions": [{"indicator": "CN_PMI", "condition": "lt", "threshold": 49}],
                "logic": "AND",
            },
            target_regime="Recovery",
            status=status,
            rejection_reason="",
        )

    _run_db_operation(django_db_blocker, _create)


def _cleanup_account(account_name: str, django_db_blocker) -> None:
    """Delete a created investment account by its unique test name."""

    if _remote_uat_active():
        return

    def _delete() -> None:
        from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

        SimulatedAccountModel.objects.filter(account_name=account_name).delete()

    _run_db_operation(django_db_blocker, _delete)


def _seed_account(account_name: str, django_db_blocker, *, account_type: str = "simulated") -> int:
    """Create a deterministic investment account for the Playwright admin user."""

    if _remote_uat_active():
        account_id = _remote_account_ids().get(account_name)
        if account_id is None:
            raise AssertionError(f"Remote UAT account fixture is missing: {account_name}")
        return account_id

    def _create() -> int:
        from django.contrib.auth import get_user_model

        from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

        user = get_user_model().objects.get(username=config.admin_username)
        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name=account_name,
            account_type=account_type,
            initial_capital=Decimal("100000.00"),
            current_cash=Decimal("82000.00"),
            current_market_value=Decimal("18000.00"),
            total_value=Decimal("100000.00"),
            total_return=0.0,
            annual_return=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            win_rate=0.0,
            total_trades=0,
            winning_trades=0,
            is_active=True,
            auto_trading_enabled=True,
            max_position_pct=20.0,
            max_total_position_pct=95.0,
            commission_rate=0.0003,
            slippage_rate=0.001,
        )
        return int(account.id)

    return _run_db_operation(django_db_blocker, _create)


@pytest.mark.e2e
@pytest.mark.uat
@pytest.mark.global_experience
class TestComprehensiveSurfaceAvailability:
    """High-level user-visible surfaces remain reachable in the browser."""

    @pytest.mark.parametrize(("path", "expected_path_fragment"), PUBLIC_SURFACES)
    def test_public_surfaces_load(
        self, page: Page, path: str, expected_path_fragment: str | None
    ) -> None:
        """Public entry surfaces should load without rendering an error shell."""
        response = _goto(page, path)
        _assert_http_success(response, path)
        _assert_non_error_shell(page, expected_path_fragment)

    @pytest.mark.parametrize("path", PROTECTED_ENTRYPOINTS)
    def test_protected_surfaces_redirect_to_login(self, page: Page, path: str) -> None:
        """Protected entry surfaces should send unauthenticated users to login."""
        _assert_login_redirect(page, path)

    @pytest.mark.parametrize(("path", "expected_path_fragment"), AUTHENTICATED_SURFACES)
    def test_authenticated_surfaces_load(
        self,
        authenticated_page: Page,
        path: str,
        expected_path_fragment: str,
    ) -> None:
        """Authenticated users should reach key work surfaces without 404/500 shells."""
        response = _goto(authenticated_page, path)
        _assert_http_success(response, path)
        _assert_surface_contract(authenticated_page, path, expected_path_fragment)


@pytest.mark.e2e
@pytest.mark.uat
@pytest.mark.navigation
@pytest.mark.slow
class TestComprehensiveNavigationRegression:
    """Link-level regression checks derived from the old comprehensive smoke script."""

    def test_homepage_links_remain_navigable(self, page: Page) -> None:
        """A sample of homepage links should stay reachable for anonymous users."""
        response = _goto(page, "/")
        _assert_http_success(response, "/")
        _assert_non_error_shell(page)

        sampled_paths = _collect_internal_paths(page, limit=4)
        _assert_paths_are_navigable(page, sampled_paths, allow_login_redirect=True)

    def test_dashboard_links_remain_navigable(self, authenticated_page: Page) -> None:
        """The dashboard should expose internal links that navigate to usable pages."""
        response = _goto(authenticated_page, config.dashboard_url)
        _assert_http_success(response, config.dashboard_url)
        _assert_dashboard_contract(authenticated_page)

        sampled_paths = _collect_internal_paths(authenticated_page, limit=5)
        _assert_paths_are_navigable(authenticated_page, sampled_paths)


@pytest.mark.e2e
@pytest.mark.uat
@pytest.mark.navigation
@pytest.mark.slow
class TestAdminNavigationRegression:
    """Admin navigation regression checks for the superuser Playwright session."""

    def test_admin_index_links_remain_navigable(self, authenticated_page: Page) -> None:
        """Admin index should expose reachable module links for the superuser test account."""
        response = _goto(authenticated_page, config.admin_index)
        _assert_http_success(response, config.admin_index)
        _assert_non_error_shell(authenticated_page, "/admin/")

        sampled_paths = _collect_internal_paths(authenticated_page, limit=5)
        _assert_paths_are_navigable(authenticated_page, sampled_paths)


@pytest.mark.e2e
@pytest.mark.uat
@pytest.mark.priority
class TestComprehensiveBusinessWorkflowShells:
    """Second-phase UAT checks for actionable workflows on core business pages."""

    def test_signal_page_exposes_creation_and_review_controls(
        self, authenticated_page: Page
    ) -> None:
        """Signal management should expose AI assistance, creation fields, and review context."""
        response = _goto(authenticated_page, config.signal_manage_url)
        _assert_http_success(response, config.signal_manage_url)
        _assert_signal_contract(authenticated_page)

        assert authenticated_page.locator("#aiInput").count() == 1
        assert authenticated_page.locator("button:has-text('AI 生成规则')").count() == 1
        assert authenticated_page.locator("#createForm").count() == 1
        assert authenticated_page.locator('input[name="asset_code"]').count() == 1
        assert authenticated_page.locator('select[name="asset_class"]').count() == 1
        assert authenticated_page.locator('input[name="logic_desc"]').count() == 1
        assert authenticated_page.locator('button[type="submit"]:has-text("创建信号")').count() == 1
        assert authenticated_page.locator(".stats-row .stat-card").count() >= 4
        assert (
            authenticated_page.locator(".signal-card").count() > 0
            or authenticated_page.locator(".empty-state").count() == 1
        ), "Signal page should show either existing signals or an empty state"

    def test_policy_workbench_exposes_filters_tabs_and_batch_actions(
        self, authenticated_page: Page
    ) -> None:
        """Policy workbench should expose the core operator controls for triage."""
        response = _goto(authenticated_page, config.policy_manage_url)
        _assert_http_success(response, config.policy_manage_url)
        _assert_policy_contract(authenticated_page)

        assert authenticated_page.locator(".overview-cards .overview-card").count() == 4
        assert authenticated_page.locator(".tab-nav .tab-btn").count() == 3
        assert authenticated_page.locator("#filter-event-type").count() == 1
        assert authenticated_page.locator("#filter-level").count() == 1
        assert authenticated_page.locator("#filter-gate-level").count() == 1
        assert authenticated_page.locator("#filter-start-date").count() == 1
        assert authenticated_page.locator("#filter-end-date").count() == 1
        assert authenticated_page.locator("#filter-search").count() == 1
        assert authenticated_page.locator("#events-tbody").count() == 1
        assert authenticated_page.locator('button:has-text("批量通过")').count() == 1
        assert authenticated_page.locator('button:has-text("批量拒绝")').count() == 1
        assert authenticated_page.locator(".quick-actions button").count() >= 2

    def test_backtest_page_supports_form_preparation_before_submission(
        self, authenticated_page: Page
    ) -> None:
        """Backtest page should prefill dates and expose the core run configuration form."""
        response = _goto(authenticated_page, config.backtest_create_url)
        _assert_http_success(response, config.backtest_create_url)
        _assert_backtest_contract(authenticated_page)

        authenticated_page.fill("#name", "Phase2 UAT Backtest")
        assert authenticated_page.input_value("#name") == "Phase2 UAT Backtest"

        start_date_before = authenticated_page.input_value("#start_date")
        end_date_before = authenticated_page.input_value("#end_date")
        assert start_date_before, "Backtest page should initialize a start date"
        assert end_date_before, "Backtest page should initialize an end date"

        authenticated_page.click('button:has-text("最近1年")')
        start_date_after = authenticated_page.input_value("#start_date")
        end_date_after = authenticated_page.input_value("#end_date")
        assert start_date_after, "Preset selection should keep a start date"
        assert end_date_after, "Preset selection should keep an end date"

        assert authenticated_page.input_value("#initial_capital") == "100000"
        assert authenticated_page.input_value("#transaction_cost_bps") == "10"
        assert authenticated_page.locator("#rebalance_frequency").count() == 1
        assert authenticated_page.locator("#use_pit_data").count() == 1
        assert authenticated_page.locator("#submit-btn").is_enabled()

    def test_simulated_accounts_page_supports_account_creation_shell(
        self, authenticated_page: Page
    ) -> None:
        """Account management should expose creation modal controls and portfolio operations."""
        response = _goto(authenticated_page, config.simulated_trading_positions_url)
        _assert_http_success(response, config.simulated_trading_positions_url)
        _assert_simulated_accounts_contract(authenticated_page)

        assert authenticated_page.locator('button:has-text("创建新账户")').count() == 1
        authenticated_page.click('button:has-text("创建新账户")')
        assert authenticated_page.locator("#createModal").count() == 1
        assert authenticated_page.locator("#createModal").is_visible()

        assert authenticated_page.locator("#account_name").count() == 1
        assert authenticated_page.locator("#account_type").count() == 1
        assert authenticated_page.locator("#initial_capital").count() == 1

        authenticated_page.click("#createModal .quick-option-btn:nth-child(3)")
        assert authenticated_page.input_value("#initial_capital") == "500000"

        assert (
            authenticated_page.locator(".account-card").count() > 0
            or authenticated_page.locator("text=您还没有创建任何账户").count() == 1
        ), "Account page should show cards or a clear empty state"

    def test_decision_workspace_exposes_stepper_and_account_context(
        self, authenticated_page: Page
    ) -> None:
        """Decision workspace should expose account context and the six-step funnel structure."""
        response = _goto(authenticated_page, "/decision/workspace/")
        _assert_http_success(response, "/decision/workspace/")
        _assert_decision_workspace_contract(authenticated_page)

        assert authenticated_page.locator("#workspace-account-selector").count() == 1
        assert authenticated_page.locator(".workspace-kpi").count() == 6
        assert authenticated_page.locator("#workspace-position-list").count() == 1
        assert authenticated_page.locator(".step-button").count() == 6
        assert authenticated_page.locator("#step-1-container").count() == 1
        assert authenticated_page.locator("#step-6-container").count() == 1
        assert authenticated_page.locator("#funnel-loading-indicator").count() == 1

    def test_ops_center_search_filters_configuration_cards(self, authenticated_page: Page) -> None:
        """Settings center should allow narrowing and resetting configuration cards in the browser."""
        response = _goto(authenticated_page, "/settings/")
        _assert_http_success(response, "/settings/")
        _assert_ops_center_contract(authenticated_page)

        search = authenticated_page.locator("#config-search")
        section_filter = authenticated_page.locator("#config-section-filter")
        status_filter = authenticated_page.locator("#config-status-filter")
        cards = authenticated_page.locator(".config-card")

        assert search.count() == 1
        assert section_filter.count() == 1
        assert status_filter.count() == 1
        assert cards.count() > 0, "Settings center should render configuration cards"

        search.fill("zzzz-no-match")
        authenticated_page.wait_for_timeout(150)
        assert authenticated_page.locator(".config-card:visible").count() == 0

        search.fill("")
        authenticated_page.wait_for_timeout(150)
        assert authenticated_page.locator(".config-card:visible").count() > 0

    def test_terminal_shell_updates_input_counter_and_mode_selector(
        self, authenticated_page: Page
    ) -> None:
        """Terminal UI should expose input, mode selection, and reactive character counting."""
        response = _goto(authenticated_page, "/terminal/")
        _assert_http_success(response, "/terminal/")
        _assert_terminal_contract(authenticated_page)

        terminal_input = authenticated_page.locator("#terminal-input")
        input_count = authenticated_page.locator("#terminal-input-count")
        mode_select = authenticated_page.locator("#terminal-mode-select")

        assert terminal_input.count() == 1
        assert authenticated_page.locator("#provider-select").count() == 1
        assert authenticated_page.locator("#model-select").count() == 1
        assert authenticated_page.locator(".quick-cmd-btn").count() >= 5

        terminal_input.fill("/help")
        authenticated_page.wait_for_timeout(100)
        assert input_count.inner_text().startswith("5/"), "Character counter should react to input"

        mode_select.select_option("readonly")
        assert mode_select.input_value() == "readonly"


@pytest.mark.e2e
@pytest.mark.uat
@pytest.mark.priority
@pytest.mark.slow
class TestComprehensiveInteractiveFlows:
    """Third-phase UAT coverage with visible state changes from real interactions."""

    def test_signal_creation_round_trip_adds_a_card(
        self, authenticated_page: Page, django_db_blocker, base_url: str
    ) -> None:
        """Create a signal using the opted-in preconfigured synthetic UI indicator fixture."""
        signal_indicator_fixture = _prepare_signal_indicator_fixture(base_url, django_db_blocker)
        # ``UATSIG*`` is deliberately hidden from production-facing lists.
        # Use a unique visible code so this round trip exercises the rendered card,
        # then remove it in ``finally`` below.
        asset_code = f"UATCRT{_uat_suffix().upper()}"

        try:
            response = _goto(authenticated_page, config.signal_manage_url)
            _assert_http_success(response, config.signal_manage_url)
            _assert_signal_contract(authenticated_page)

            asset_class_value = authenticated_page.locator(
                'select[name="asset_class"] option[value]'
            ).evaluate_all(
                """options => {
                    const valid = options
                        .map(option => option.value)
                        .filter(value => value && value.trim().length > 0);
                    return valid[0] || null;
                }"""
            )
            indicator_value = authenticated_page.locator(
                "#indicatorSelect option[value]"
            ).evaluate_all(
                """options => {
                    const valid = options
                        .map(option => option.value)
                        .filter(value => value && value.trim().length > 0);
                    return valid[0] || null;
                }"""
            )

            assert asset_class_value, "Signal form has no selectable asset classes"
            if signal_indicator_fixture is not None:
                fixture_option = authenticated_page.locator(
                    f'#indicatorSelect option[value="{signal_indicator_fixture}"]'
                )
                assert (
                    fixture_option.count() == 1
                ), "The synthetic fixture did not appear through the published-indicator query"
                indicator_value = signal_indicator_fixture
            assert indicator_value, (
                "Signal form has no selectable published indicators; provision governed "
                "macro.fact publication data instead of skipping this journey"
            )

            authenticated_page.fill('input[name="asset_code"]', asset_code)
            authenticated_page.select_option('select[name="asset_class"]', asset_class_value)
            authenticated_page.fill(
                'input[name="logic_desc"]', f"Phase 3 UAT signal for {asset_code}"
            )
            authenticated_page.select_option("#indicatorSelect", indicator_value)
            authenticated_page.fill("#thresholdInput", "1")
            authenticated_page.click('button:has-text("添加条件")')

            assert authenticated_page.locator("#conditionsList .condition-item").count() >= 1

            create_url = urljoin(config.base_url, config.signal_create_url)
            create_path = urlparse(create_url).path
            try:
                with authenticated_page.expect_response(
                    lambda response: (
                        response.request.method == "POST"
                        and urlparse(response.url).path == create_path
                    ),
                    timeout=config.navigation_timeout,
                ) as create_response_info:
                    authenticated_page.click('button[type="submit"]:has-text("创建信号")')
            except PlaywrightTimeoutError as exc:
                raise AssertionError(
                    f"Submitting signal {asset_code} produced no POST response for "
                    f"{create_path!r}; the form may have been blocked before "
                    "submission."
                ) from exc

            create_response = create_response_info.value
            response_body = create_response.text()
            try:
                create_payload = json.loads(response_body)
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"Signal create POST for {asset_code} returned non-JSON HTTP "
                    f"{create_response.status}; body={response_body[:500]!r}"
                ) from exc
            assert isinstance(create_payload, dict), (
                f"Signal create POST for {asset_code} returned HTTP "
                f"{create_response.status} with a non-object JSON response: "
                f"{create_payload!r}"
            )
            assert create_response.status < 400, (
                f"Signal create POST for {asset_code} returned HTTP "
                f"{create_response.status}: {create_payload!r}"
            )
            assert create_payload.get("success") is True, (
                f"Signal create POST for {asset_code} failed with HTTP "
                f"{create_response.status}: {create_payload!r}"
            )

            created_card = authenticated_page.locator(f'.signal-card:has-text("{asset_code}")')
            created_card.first.wait_for(
                state="visible",
                timeout=config.navigation_timeout,
            )
            _assert_signal_contract(authenticated_page)
            assert authenticated_page.locator(f"text={asset_code}").count() >= 1
        finally:
            _cleanup_signal(asset_code, django_db_blocker)

    def test_simulated_account_creation_round_trip_adds_a_card(
        self,
        authenticated_page: Page,
        django_db_blocker,
    ) -> None:
        """Creating an investment account from the modal should surface a new account card."""
        account_name = f"Phase3-UAT-{_uat_suffix()}"

        try:
            response = _goto(authenticated_page, config.simulated_trading_positions_url)
            _assert_http_success(response, config.simulated_trading_positions_url)
            _assert_simulated_accounts_contract(authenticated_page)

            authenticated_page.click('button:has-text("创建新账户")')
            assert authenticated_page.locator("#createModal").is_visible()

            authenticated_page.fill("#account_name", account_name)
            authenticated_page.select_option("#account_type", "simulated")
            authenticated_page.click("#createModal .quick-option-btn:nth-child(2)")

            with authenticated_page.expect_navigation(wait_until="networkidle"):
                authenticated_page.click('#createModal button[type="submit"]:has-text("创建")')

            _assert_simulated_accounts_contract(authenticated_page)
            assert authenticated_page.locator(f"text={account_name}").count() >= 1
        finally:
            _cleanup_account(account_name, django_db_blocker)

    def test_backtest_form_blocks_invalid_date_range(self, authenticated_page: Page) -> None:
        """Submitting a reversed date range should raise the client-side validation alert."""
        response = _goto(authenticated_page, config.backtest_create_url)
        _assert_http_success(response, config.backtest_create_url)
        _assert_backtest_contract(authenticated_page)

        authenticated_page.evaluate("""() => {
                window.__uatLastAlert = null;
                window.alert = (message) => {
                    window.__uatLastAlert = message;
                };
            }""")
        authenticated_page.fill("#name", "Phase 3 Invalid Date Backtest")
        authenticated_page.fill("#start_date", "2025-01-10")
        authenticated_page.fill("#end_date", "2025-01-01")
        authenticated_page.click("#submit-btn")
        authenticated_page.wait_for_timeout(150)

        alert_message = authenticated_page.evaluate("window.__uatLastAlert")
        assert alert_message is not None
        assert "起始日期必须早于结束日期" in alert_message

    def test_terminal_status_command_renders_readiness_output(
        self, authenticated_page: Page
    ) -> None:
        """Quick status command should append readiness output into the terminal transcript."""
        response = _goto(authenticated_page, "/terminal/")
        _assert_http_success(response, "/terminal/")
        _assert_terminal_contract(authenticated_page)

        output = authenticated_page.locator("#terminal-output")
        initial_text = output.inner_text(timeout=5000)

        authenticated_page.click('.quick-cmd-btn[data-cmd="status"]')
        authenticated_page.locator("#terminal-output").locator("text=System Readiness").wait_for(
            timeout=15000
        )

        updated_text = output.inner_text(timeout=5000)
        assert "System Readiness" in updated_text
        assert updated_text != initial_text


@pytest.mark.e2e
@pytest.mark.uat
@pytest.mark.priority
@pytest.mark.slow
class TestComprehensiveActionRegression:
    """Fourth-phase UAT checks for list actions and cross-page transitions."""

    def test_pending_signal_can_be_approved_from_the_card(
        self, authenticated_page: Page, django_db_blocker
    ) -> None:
        """Approving a seeded pending signal should reload the page and update its status badge."""
        asset_code = f"UATAPP{_uat_suffix().upper()}"
        _seed_signal(asset_code, django_db_blocker, status="pending")

        try:
            response = _goto(authenticated_page, config.signal_manage_url)
            _assert_http_success(response, config.signal_manage_url)
            _assert_signal_contract(authenticated_page)

            card = authenticated_page.locator(f'.signal-card:has-text("{asset_code}")').first
            assert card.count() == 1

            with authenticated_page.expect_navigation(wait_until="domcontentloaded"):
                card.locator(".action-btn.approve").click()

            updated_card = authenticated_page.locator(
                f'.signal-card:has-text("{asset_code}")'
            ).first
            assert updated_card.locator("text=已通过").count() >= 1
        finally:
            _cleanup_signal(asset_code, django_db_blocker)

    def test_pending_signal_can_be_rejected_from_the_card(
        self, authenticated_page: Page, django_db_blocker
    ) -> None:
        """Rejecting a seeded pending signal should prompt for a reason and show rejected state."""
        asset_code = f"UATREJ{_uat_suffix().upper()}"
        _seed_signal(asset_code, django_db_blocker, status="pending")

        try:
            response = _goto(authenticated_page, config.signal_manage_url)
            _assert_http_success(response, config.signal_manage_url)
            _assert_signal_contract(authenticated_page)

            authenticated_page.evaluate("""() => {
                    window.uiPrompt = async () => 'Phase4 rejection reason';
                }""")

            card = authenticated_page.locator(f'.signal-card:has-text("{asset_code}")').first
            assert card.count() == 1

            with authenticated_page.expect_navigation(wait_until="domcontentloaded"):
                card.locator(".action-btn.reject").click()

            updated_card = authenticated_page.locator(
                f'.signal-card:has-text("{asset_code}")'
            ).first
            assert updated_card.locator("text=已拒绝").count() >= 1
        finally:
            _cleanup_signal(asset_code, django_db_blocker)

    def test_seeded_accounts_support_batch_delete_flow(
        self, authenticated_page: Page, django_db_blocker
    ) -> None:
        """Selecting two seeded accounts should enable batch delete and remove both cards."""
        suffix = _uat_suffix()
        account_names = [f"UAT-Batch-{suffix}-A", f"UAT-Batch-{suffix}-B"]
        for name in account_names:
            _seed_account(name, django_db_blocker)

        try:
            response = _goto(authenticated_page, config.simulated_trading_positions_url)
            _assert_http_success(response, config.simulated_trading_positions_url)
            _assert_simulated_accounts_contract(authenticated_page)

            authenticated_page.evaluate("""() => {
                    window.uiConfirm = async () => true;
                }""")

            for name in account_names:
                authenticated_page.locator(
                    f'.account-select-input[data-account-name="{name}"]'
                ).check()

            assert "已选择 2 个" in authenticated_page.locator("#selectedAccountCount").inner_text()
            assert authenticated_page.locator("#bulkDeleteBtn").is_enabled()

            authenticated_page.click("#bulkDeleteBtn")
            authenticated_page.wait_for_timeout(1400)

            for name in account_names:
                assert authenticated_page.locator(f"text={name}").count() == 0
        finally:
            for name in account_names:
                _cleanup_account(name, django_db_blocker)

    def test_ops_center_frontend_card_link_opens_a_usable_page(
        self, authenticated_page: Page
    ) -> None:
        """The ops center should expose at least one frontend entry link that opens cleanly."""
        response = _goto(authenticated_page, "/settings/")
        _assert_http_success(response, "/settings/")
        _assert_ops_center_contract(authenticated_page)

        frontend_href = authenticated_page.evaluate("""() => {
                const link = document.querySelector('.config-card a.btn.btn-primary[href]');
                return link ? link.getAttribute('href') : null;
            }""")
        if not frontend_href:
            pytest.skip(
                "Settings center has no visible frontend entry card in current fixture data"
            )

        target_path = urlparse(urljoin(config.base_url, frontend_href)).path
        response = _goto(authenticated_page, target_path)
        _assert_http_success(response, target_path)
        _assert_surface_contract(authenticated_page, target_path)

    def test_decision_workspace_account_switch_refreshes_snapshot(
        self, authenticated_page: Page, django_db_blocker
    ) -> None:
        """Switching to a seeded account should refresh account summary and status text."""
        account_name = f"UAT-Workspace-{_uat_suffix()}"
        account_id = _seed_account(account_name, django_db_blocker)

        try:
            response = _goto(authenticated_page, "/decision/workspace/")
            _assert_http_success(response, "/decision/workspace/")
            _assert_decision_workspace_contract(authenticated_page)

            selector = authenticated_page.locator("#workspace-account-selector")
            authenticated_page.wait_for_function(
                """accountId => {
                    const selector = document.querySelector('#workspace-account-selector');
                    return !!selector?.querySelector(`option[value="${accountId}"]`);
                }""",
                arg=str(account_id),
                timeout=15000,
            )
            selector.select_option(str(account_id))

            authenticated_page.wait_for_function(
                """expectedName => {
                    return Array.from(document.querySelectorAll('[data-workspace-account-name]'))
                        .some(node => (node.textContent || '').includes(expectedName));
                }""",
                arg=account_name,
                timeout=15000,
            )
            authenticated_page.wait_for_function(
                """() => {
                    const meta = document.querySelector('#workspace-account-meta');
                    const status = document.querySelector('#workspace-account-status');
                    return !!meta && !!status
                        && meta.textContent.includes('模拟账户')
                        && ['运行中', '已停用'].includes((status.textContent || '').trim());
                }""",
                timeout=15000,
            )
            assert "模拟账户" in authenticated_page.locator("#workspace-account-meta").inner_text()
            assert authenticated_page.locator("#workspace-account-status").inner_text() in {
                "运行中",
                "已停用",
            }
            assert "100,000" in authenticated_page.locator(
                "#workspace-total-value"
            ).inner_text().replace(".00", "")
        finally:
            _cleanup_account(account_name, django_db_blocker)

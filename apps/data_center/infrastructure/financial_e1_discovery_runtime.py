"""Persisted selection preflight and request composition for one E1 run.

This module loads only the caller's explicit qualification identities. It
rechecks provider configuration, actual Owner events, retained document bytes,
and the two persisted egress routes before capture. A successful preflight is
only readiness for this finite capture; each response is resolved again from
its own body, row context, and response-completion clock before the v3 writer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections

from apps.data_center.akshare_financial_capture_composition import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL,
)
from apps.data_center.application.egress_service import preview_route
from apps.data_center.application.financial_e1_discovery_runner import (
    FinancialE1PreflightSnapshot,
)
from apps.data_center.application.financial_numeric_catalog import (
    FinancialNumericSourceCatalogRepositoryPort,
)
from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericCatalogEntrySnapshotReadPort,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.financial_e1_capture_contract import (
    FinancialE1EndpointRequest,
)
from apps.data_center.domain.financial_e1_discovery_plan import FinancialE1DiscoveryPlanV2
from apps.data_center.domain.financial_numeric_catalog import FinancialNumericCatalogEntry
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceQualification,
)
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseScope,
)
from apps.data_center.infrastructure.financial_e1_capture_gateway import (
    FinancialE1RequestProjection,
)
from apps.data_center.infrastructure.financial_e1_discovery_replay import (
    FinancialE1BalanceCaptureConfigV2,
)
from apps.data_center.infrastructure.financial_numeric_catalog_capture_repository import (
    DjangoFinancialNumericSourceCaptureRepository,
    FinancialNumericCatalogEvidenceError,
)
from apps.data_center.infrastructure.financial_numeric_catalog_models import (
    FinancialMetricSourceCatalogEntryModel,
)
from apps.data_center.infrastructure.financial_numeric_catalog_repository import (
    DjangoFinancialMetricSourceCatalogRepository,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_raw_boundary import (
    BalanceCandidateContract,
    BalanceCandidateRequest,
    build_balance_candidate_query,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_verifier import (
    AKSHARE_BALANCE_API_URL,
)
from apps.data_center.infrastructure.financial_numeric_qualification.django_snapshot_reader import (
    DjangoFinancialNumericCatalogEntrySnapshotReader,
)
from apps.data_center.infrastructure.financial_source_body_runtime import (
    build_statutory_source_body_store,
)
from apps.data_center.infrastructure.models import ProviderConfigModel
from core.exceptions import DataValidationError

_MAIN_REPORT_TYPE = "RPT_F10_FINANCE_MAINFINADATA"
_MAIN_QUERY_STYLE = "APP_F10_MAINFINADATA"
_MAIN_MAX_PAGE_SIZE = 200
_MAX_SELECTION_SIZE = 64


class FinancialE1PreflightError(DataValidationError):
    """Stable block for missing persisted selection, route, or retained evidence."""

    default_message = "E1 财报采集预检未通过。"
    default_code = "FINANCIAL_E1_PREFLIGHT_BLOCKED"


@dataclass(frozen=True, slots=True)
class FinancialE1PreparedSelection:
    """One readiness snapshot used only to build the exact response parsers."""

    plan_identity_sha256: str
    known_at: datetime
    entries: tuple[FinancialNumericCatalogEntry, ...]
    qualifications: tuple[FinancialNumericSourceQualification, ...]
    balance_config: FinancialE1BalanceCaptureConfigV2
    balance_parser_contract: BalanceCandidateContract
    provider_config_sha256: str

    def __post_init__(self) -> None:
        """Reject incomplete or untyped preflight snapshots."""

        _require_utc(self.known_at, "preflight known_at")
        if (
            type(self.plan_identity_sha256) is not str
            or len(self.plan_identity_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.plan_identity_sha256)
            or type(self.provider_config_sha256) is not str
            or len(self.provider_config_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.provider_config_sha256)
        ):
            raise ValueError("E1 prepared selection hashes are invalid")
        if (
            type(self.entries) is not tuple
            or not self.entries
            or any(type(entry) is not FinancialNumericCatalogEntry for entry in self.entries)
            or type(self.qualifications) is not tuple
            or len(self.qualifications) != len(self.entries)
            or any(
                type(item) is not FinancialNumericSourceQualification
                for item in self.qualifications
            )
        ):
            raise TypeError("E1 prepared selection requires exact typed catalog entries")
        if type(self.balance_parser_contract) is not BalanceCandidateContract:
            raise TypeError("E1 prepared selection requires an exact Balance parser contract")


class DjangoFinancialE1DatabaseClock:
    """Supply current UTC instants from PostgreSQL rather than request clocks."""

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        """Bind the single supported default database alias."""

        if type(using) is not str or using != DEFAULT_DB_ALIAS:
            raise ValueError("E1 capture currently requires the default database alias")
        self._using = using

    def now_utc(self) -> datetime:
        """Read PostgreSQL server time and normalize to exact UTC."""

        database = connections[self._using]
        if database.vendor != "postgresql":
            raise FinancialE1PreflightError(
                "E1 fact capture requires the isolated PostgreSQL runtime",
                code="FINANCIAL_E1_POSTGRES_REQUIRED",
            )
        try:
            with database.cursor() as cursor:
                cursor.execute("SELECT CURRENT_TIMESTAMP")
                row = cursor.fetchone()
        except DatabaseError as error:
            raise FinancialE1PreflightError(
                "E1 server clock is unavailable", code="FINANCIAL_E1_DATABASE_CLOCK_UNAVAILABLE"
            ) from error
        if row is None or len(row) != 1:
            raise FinancialE1PreflightError(
                "E1 server clock did not return one timestamp",
                code="FINANCIAL_E1_DATABASE_CLOCK_INVALID",
            )
        return _require_utc(row[0], "database current timestamp")


class DjangoFinancialE1SelectionLoader:
    """Load the exact explicit set and its real capture/Owner state before egress."""

    def __init__(
        self,
        *,
        capture_repository: DjangoFinancialNumericSourceCaptureRepository,
        entry_reader: FinancialNumericCatalogEntrySnapshotReadPort,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        """Require the catalog, source-document reader, and default PostgreSQL alias."""

        if type(capture_repository) is not DjangoFinancialNumericSourceCaptureRepository:
            raise TypeError("E1 needs the real numeric retained-document repository")
        if type(using) is not str or using != DEFAULT_DB_ALIAS:
            raise ValueError("E1 qualification reads require the default database alias")
        if getattr(capture_repository, "database_alias", None) != using:
            raise ValueError("E1 catalog and retained-document readers must share one alias")
        if getattr(entry_reader, "database_alias", None) != using:
            raise ValueError("E1 entry snapshot reader must share the capture database alias")
        self._capture_repository = capture_repository
        self._entry_reader = entry_reader
        self._using = using

    def load(
        self,
        plan: FinancialE1DiscoveryPlanV2,
        *,
        known_at: datetime,
    ) -> FinancialE1PreparedSelection:
        """Verify every explicit identity, current event, source doc, config, and route."""

        from apps.data_center.application.financial_e1_discovery_runner import (
            FinancialE1PreflightSnapshot,
        )
        from apps.data_center.domain.financial_e1_discovery_plan import (
            FinancialE1DiscoveryPlanV2,
        )

        if type(plan) is not FinancialE1DiscoveryPlanV2:
            raise FinancialE1PreflightError("E1 requires an explicit discovery plan")
        cutoff = _require_utc(known_at, "preflight known_at")
        if not 1 <= len(plan.qualification_identities) <= _MAX_SELECTION_SIZE:
            raise FinancialE1PreflightError("E1 finite qualification set is outside its bound")
        self._require_postgres()
        provider = _active_provider(plan.provider_id, expected_source_type=plan.provider_name)
        try:
            balance_config = FinancialE1BalanceCaptureConfigV2.from_provider_extra_config(
                provider.extra_config
            )
        except (TypeError, ValueError) as error:
            raise FinancialE1PreflightError(
                "E1 Balance request/parser config is missing or unsupported",
                code="FINANCIAL_E1_PROVIDER_CONFIG_BLOCKED",
            ) from error
        provider_digest = _provider_config_sha256(provider)
        qualifications, entries = self._load_entries(plan, known_at=cutoff)
        try:
            parser_contract = balance_config.build_parser_contract(qualifications)
        except (TypeError, ValueError) as error:
            raise FinancialE1PreflightError(
                "E1 selected Balance qualifications do not form the exact parser contract",
                code="FINANCIAL_E1_BALANCE_SELECTION_BLOCKED",
            ) from error
        snapshot = FinancialE1PreflightSnapshot(known_at=cutoff, entries=entries)
        _validate_current_entries(snapshot)
        _validate_plan_egress_routes(
            plan,
            provider_id=plan.provider_id,
        )
        return FinancialE1PreparedSelection(
            plan_identity_sha256=plan.selection_sha256,
            known_at=cutoff,
            entries=entries,
            qualifications=qualifications,
            balance_config=balance_config,
            balance_parser_contract=parser_contract,
            provider_config_sha256=provider_digest,
        )

    def _load_entries(
        self,
        plan: object,
        *,
        known_at: datetime,
    ) -> tuple[
        tuple[FinancialNumericSourceQualification, ...],
        tuple[FinancialNumericCatalogEntry, ...],
    ]:
        """Match exact DB entry rows, event snapshots, and body readbacks."""

        from apps.data_center.domain.financial_e1_discovery_plan import (
            FinancialE1DiscoveryPlanV2,
        )

        if type(plan) is not FinancialE1DiscoveryPlanV2:
            raise TypeError("plan must be a FinancialE1DiscoveryPlanV2")
        try:
            models = tuple(
                FinancialMetricSourceCatalogEntryModel._default_manager.using(self._using)
                .filter(qualification_identity__in=plan.qualification_identities)
                .order_by("qualification_identity")[: len(plan.qualification_identities) + 1]
            )
        except DatabaseError as error:
            raise FinancialE1PreflightError(
                "E1 selected catalog rows are unavailable",
                code="FINANCIAL_E1_CATALOG_UNAVAILABLE",
            ) from error
        if len(models) != len(plan.qualification_identities):
            raise FinancialE1PreflightError(
                "E1 qualification selection does not match the persisted row set",
                code="FINANCIAL_E1_SELECTION_MISMATCH",
            )
        model_identities = tuple(row.qualification_identity for row in models)
        if set(model_identities) != set(plan.qualification_identities) or len(
            set(model_identities)
        ) != len(model_identities):
            raise FinancialE1PreflightError(
                "E1 qualification selection contains missing or duplicate rows",
                code="FINANCIAL_E1_SELECTION_MISMATCH",
            )
        qualifications: list[FinancialNumericSourceQualification] = []
        entries: list[FinancialNumericCatalogEntry] = []
        verified_capture_ids: set[object] = set()
        for row in models:
            try:
                qualification = FinancialNumericSourceQualification.from_payload(row.qualification)
                _validate_catalog_row_columns(row, qualification)
                entry = self._entry_reader.read_exact_entry(qualification, known_at=known_at)
                if type(entry) is not FinancialNumericCatalogEntry:
                    raise ValueError("exact catalog entry snapshot is unavailable")
                if entry.qualification != qualification:
                    raise ValueError("catalog entry snapshot differs from the selected payload")
                verified = self._capture_repository.read_verified_capture(
                    qualification.document_capture,
                    known_at=known_at,
                )
                if (
                    verified.reference != qualification.document_capture
                    or not verified.body
                    or verified.capture_recorded_at > known_at
                    or verified.response_completed_at > known_at
                ):
                    raise ValueError("exact source document capture is not known and readable")
                verified_capture_ids.add(qualification.document_capture.capture_id)
                _validate_current_entry(entry, known_at=known_at)
            except (
                DatabaseError,
                FinancialNumericCatalogEvidenceError,
                OSError,
                TypeError,
                ValueError,
            ) as error:
                raise FinancialE1PreflightError(
                    "E1 source qualification, Owner event, or retained document is blocked",
                    code="FINANCIAL_E1_SELECTION_EVIDENCE_BLOCKED",
                ) from error
            qualifications.append(qualification)
            entries.append(entry)
        if len(verified_capture_ids) == 0:
            raise FinancialE1PreflightError("E1 selection has no retained document bodies")
        return tuple(qualifications), tuple(entries)

    def _require_postgres(self) -> None:
        """Refuse a SQLite/default-fixture path for financial E1 readiness."""

        database = connections[self._using]
        if database.vendor != "postgresql":
            raise FinancialE1PreflightError(
                "E1 financial capture requires PostgreSQL",
                code="FINANCIAL_E1_POSTGRES_REQUIRED",
            )


class DjangoFinancialE1PinnedPreflight:
    """Re-read all selected evidence immediately before the first response send."""

    def __init__(
        self,
        *,
        loader: DjangoFinancialE1SelectionLoader,
        expected: FinancialE1PreparedSelection,
    ) -> None:
        """Pin the prepared parser/config to the same finite selection."""

        self._loader = loader
        self._expected = expected

    def load_exact_current_selection(
        self,
        plan: FinancialE1DiscoveryPlanV2,
        *,
        known_at: datetime,
    ) -> FinancialE1PreflightSnapshot:
        """Return a snapshot only if the fresh DB/config state matches preparation."""

        from apps.data_center.application.financial_e1_discovery_runner import (
            FinancialE1PreflightSnapshot,
        )

        prepared = self._loader.load(plan, known_at=known_at)
        if (
            prepared.plan_identity_sha256 != self._expected.plan_identity_sha256
            or prepared.qualifications != self._expected.qualifications
            or prepared.entries != self._expected.entries
            or prepared.balance_config != self._expected.balance_config
            or prepared.balance_parser_contract != self._expected.balance_parser_contract
            or prepared.provider_config_sha256 != self._expected.provider_config_sha256
        ):
            raise FinancialE1PreflightError(
                "E1 provider/catalog state changed after preparation",
                code="FINANCIAL_E1_PREFLIGHT_STATE_CHANGED",
            )
        return FinancialE1PreflightSnapshot(known_at=prepared.known_at, entries=prepared.entries)


class DjangoFinancialE1RequestProjector:
    """Construct one exact Main or Balance request over existing routed egress."""

    def __init__(
        self,
        *,
        plan: object,
        prepared: FinancialE1PreparedSelection,
        deployment_region: str,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        """Bind one plan and its provider-authored Balance parser settings."""

        from apps.data_center.domain.financial_e1_discovery_plan import (
            FinancialE1DiscoveryPlanV2,
        )

        if type(plan) is not FinancialE1DiscoveryPlanV2:
            raise TypeError("request projector requires the exact E1 plan")
        if type(prepared) is not FinancialE1PreparedSelection:
            raise TypeError("request projector requires prepared persisted qualifications")
        if type(using) is not str or using != DEFAULT_DB_ALIAS:
            raise ValueError("E1 request projection requires the default alias")
        if (
            type(deployment_region) is not str
            or not deployment_region
            or deployment_region == "unknown"
        ):
            raise ValueError("E1 deployment region must be explicitly configured")
        self._plan = plan
        self._prepared = prepared
        self._deployment_region = deployment_region
        self._using = using

    def project(self, request: FinancialE1EndpointRequest) -> FinancialE1RequestProjection:
        """Return a no-page query and persisted route context for one exact request."""

        from apps.data_center.domain.financial_e1_discovery_plan import (
            FinancialE1DiscoveryPlanV2,
        )

        if (
            type(request) is not FinancialE1EndpointRequest
            or type(self._plan) is not FinancialE1DiscoveryPlanV2
        ):
            raise FinancialE1PreflightError("E1 endpoint request is not typed")
        if request == self._plan.main_request:
            target_url = AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL
            params = self._main_query_params()
        elif request == self._plan.balance_request:
            target_url = AKSHARE_BALANCE_API_URL
            balance_request = BalanceCandidateRequest(
                symbol=self._plan.asset_code,
                security_code=_security_code(self._plan.asset_code),
                report_date=self._plan.period_end,
            )
            params = dict(
                build_balance_candidate_query(
                    balance_request,
                    self._prepared.balance_parser_contract,
                ).parameters
            )
        else:
            raise FinancialE1PreflightError("E1 request is outside the exact two plan slots")
        self._check_provider_snapshot()
        context = EgressRequestContext(
            provider_id=self._plan.provider_id,
            dataset_key=request.dataset_key,
            target_url=target_url,
            deployment_region=self._deployment_region,
        )
        route = preview_route(context)
        if route.rule_id is None:
            raise FinancialE1PreflightError(
                "E1 endpoint has no persisted controlled-egress route",
                code="FINANCIAL_E1_EGRESS_ROUTE_BLOCKED",
            )
        return FinancialE1RequestProjection(
            request=request,
            context=context,
            method="GET",
            params=MappingProxyType(params),
            json_body=None,
            headers=None,
            request_scope=FinancialRequestScope(
                provider_name=request.provider_name,
                dataset_key=request.dataset_key,
                asset_code=request.request_asset_code,
                period_limit=1,
            ),
            declared_response_scope=FinancialResponseScope(
                asset_codes=(request.request_asset_code,),
                period_ends=(),
                row_count=0,
            ),
            provider_id=self._plan.provider_id,
        )

    def _main_query_params(self) -> dict[str, object]:
        """Build the existing Main endpoint query using report period, never NOTICE."""

        contract = self._plan.main_notice_contract
        asset_filter = f'({contract.asset_field}="{self._plan.asset_code}")'
        period_filter = f"({contract.period_end_field}='{self._plan.period_end.isoformat()}')"
        return {
            "type": _MAIN_REPORT_TYPE,
            "sty": _MAIN_QUERY_STYLE,
            "quoteColumns": "",
            "filter": asset_filter + period_filter,
            "p": "1",
            "ps": str(_MAIN_MAX_PAGE_SIZE),
            "sr": "-1",
            "st": contract.period_end_field,
            "source": "HSF10",
            "client": "PC",
        }

    def _check_provider_snapshot(self) -> None:
        """Recheck source type, active state, and exact v2 parser config before each send."""

        try:
            provider = _active_provider(
                self._plan.provider_id,
                expected_source_type=self._plan.provider_name,
            )
            current_config = FinancialE1BalanceCaptureConfigV2.from_provider_extra_config(
                provider.extra_config
            )
        except (DatabaseError, TypeError, ValueError) as error:
            raise FinancialE1PreflightError(
                "E1 provider or parser config changed before send",
                code="FINANCIAL_E1_PROVIDER_CONFIG_BLOCKED",
            ) from error
        if (
            _provider_config_sha256(provider) != self._prepared.provider_config_sha256
            or current_config != self._prepared.balance_config
        ):
            raise FinancialE1PreflightError(
                "E1 provider config changed after preflight",
                code="FINANCIAL_E1_PROVIDER_CONFIG_CHANGED",
            )


class DjangoFinancialE1ExactQualificationResolver:
    """Resolve each raw metric under its exact endpoint, context, and two clocks."""

    def __init__(self, repository: FinancialNumericSourceCatalogRepositoryPort) -> None:
        """Require the real persisted numeric catalog repository."""

        if repository is None:
            raise TypeError("financial numeric source catalog repository is required")
        self._repository = repository

    def resolve_exact(
        self,
        qualification_identity: str,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        known_at: datetime,
    ) -> FinancialNumericSourceQualification | None:
        """Return only the same exact qualification after an actual-row resolution."""

        qualification = self._repository.resolve_exact(
            contract_identity,
            endpoint=endpoint,
            source_response_completed_at=source_response_completed_at,
            source_context=source_context,
            known_at=known_at,
        )
        if (
            type(qualification) is not FinancialNumericSourceQualification
            or qualification.identity != qualification_identity
            or qualification.contract.identity != contract_identity
            or qualification.endpoint != endpoint
        ):
            return None
        return qualification


def build_financial_e1_preflight_loader(
    *,
    using: str = DEFAULT_DB_ALIAS,
    capture_repository: DjangoFinancialNumericSourceCaptureRepository | None = None,
) -> DjangoFinancialE1SelectionLoader:
    """Build the exact catalog/body selection reader with one configured store."""

    if type(using) is not str or using != DEFAULT_DB_ALIAS:
        raise FinancialE1PreflightError("E1 currently supports only the default database alias")
    source_capture_repository = capture_repository
    if source_capture_repository is None:
        source_capture_repository = DjangoFinancialNumericSourceCaptureRepository(
            body_store=build_statutory_source_body_store(),
            using=using,
        )
    if (
        type(source_capture_repository) is not DjangoFinancialNumericSourceCaptureRepository
        or source_capture_repository.database_alias != using
    ):
        raise FinancialE1PreflightError(
            "E1 catalog and retained-document readers must share the default alias",
            code="FINANCIAL_E1_ALIAS_MISMATCH",
        )
    return DjangoFinancialE1SelectionLoader(
        capture_repository=source_capture_repository,
        entry_reader=DjangoFinancialNumericCatalogEntrySnapshotReader(using=using),
        using=using,
    )


def build_financial_e1_resolver(
    *,
    capture_repository: DjangoFinancialNumericSourceCaptureRepository,
    using: str = DEFAULT_DB_ALIAS,
) -> DjangoFinancialE1ExactQualificationResolver:
    """Build the same-alias exact qualification resolver used after capture."""

    repository = DjangoFinancialMetricSourceCatalogRepository(
        capture_repository=capture_repository,
        using=using,
    )
    return DjangoFinancialE1ExactQualificationResolver(repository)


def _active_provider(provider_id: int, *, expected_source_type: str) -> ProviderConfigModel:
    """Read one active persisted provider with exact numeric-source identity."""

    if type(provider_id) is not int or provider_id <= 0:
        raise FinancialE1PreflightError("E1 provider id is invalid")
    try:
        provider = (
            ProviderConfigModel._default_manager.using(DEFAULT_DB_ALIAS)
            .filter(pk=provider_id)
            .first()
        )
    except DatabaseError as error:
        raise FinancialE1PreflightError(
            "E1 persisted provider config is unavailable",
            code="FINANCIAL_E1_PROVIDER_UNAVAILABLE",
        ) from error
    if (
        provider is None
        or provider.pk != provider_id
        or provider.source_type != expected_source_type
        or provider.is_active is not True
    ):
        raise FinancialE1PreflightError(
            "E1 provider is missing, inactive, or has changed source identity",
            code="FINANCIAL_E1_PROVIDER_IDENTITY_BLOCKED",
        )
    return provider


def _provider_config_sha256(provider: ProviderConfigModel) -> str:
    """Hash the actual persisted provider identity and complete extra-config JSON."""

    encoded = json.dumps(
        {
            "extra_config": provider.extra_config,
            "id": provider.pk,
            "is_active": provider.is_active,
            "name": provider.name,
            "source_type": provider.source_type,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_catalog_row_columns(
    row: FinancialMetricSourceCatalogEntryModel,
    qualification: FinancialNumericSourceQualification,
) -> None:
    """Check every denormalized catalog column against the exact JSON payload."""

    contract = qualification.contract
    if (
        qualification.identity != row.qualification_identity
        or qualification.content_hash != row.qualification_sha256
        or contract.identity != row.contract_identity
        or contract.content_hash != row.contract_sha256
        or contract.provider != row.contract_provider
        or contract.dataset_key != row.dataset_key
        or contract.metric_code != row.metric_code
        or qualification.document_capture.capture_id != row.document_capture_id
        or qualification.effective_from != row.effective_from
        or qualification.effective_until != row.effective_until
    ):
        raise ValueError("catalog row identity columns differ from the exact qualification payload")


def _validate_current_entry(entry: FinancialNumericCatalogEntry, *, known_at: datetime) -> None:
    """Require one real apply and no recorded revoke at the current cutoff."""

    qualification = entry.qualification
    apply_events = tuple(event for event in entry.owner_events if event.action == "apply")
    revoke_events = tuple(event for event in entry.owner_events if event.action == "revoke")
    if (
        entry.recorded_at > known_at
        or entry.capture_recorded_at > known_at
        or len(apply_events) != 1
        or revoke_events
        or apply_events[0].event_at > known_at
        or apply_events[0].recorded_at > known_at
        or apply_events[0].qualification_identity != qualification.identity
        or apply_events[0].qualification_sha256 != qualification.content_hash
        or qualification.effective_from > known_at
        or (qualification.effective_until is not None and known_at >= qualification.effective_until)
    ):
        raise ValueError("catalog entry is not currently applied, effective, and known")


def _validate_current_entries(snapshot: object) -> None:
    """Cross-check the typed app snapshot at its exact current preflight clock."""

    from apps.data_center.application.financial_e1_discovery_runner import (
        FinancialE1PreflightSnapshot,
    )

    if type(snapshot) is not FinancialE1PreflightSnapshot:
        raise TypeError("E1 preflight snapshot has an unsupported type")
    for entry in snapshot.entries:
        _validate_current_entry(entry, known_at=snapshot.known_at)


def _validate_plan_egress_routes(
    plan: object,
    *,
    provider_id: int,
) -> None:
    """Preview both exact persisted routes before any response request can begin."""

    from apps.data_center.domain.financial_e1_discovery_plan import (
        FinancialE1DiscoveryPlanV2,
    )
    from apps.data_center.infrastructure.akshare_financial_slice_sync import (
        akshare_financial_deployment_region,
    )

    if type(plan) is not FinancialE1DiscoveryPlanV2:
        raise TypeError("plan must be a FinancialE1DiscoveryPlanV2")
    deployment_region = akshare_financial_deployment_region()
    if not deployment_region or deployment_region == "unknown":
        raise FinancialE1PreflightError(
            "E1 deployment region is not explicitly configured",
            code="FINANCIAL_E1_EGRESS_ROUTE_BLOCKED",
        )
    for request in (plan.main_request, plan.balance_request):
        if request.endpoint == plan.main_request.endpoint:
            target_url = AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL
        elif request.endpoint == plan.balance_request.endpoint:
            target_url = AKSHARE_BALANCE_API_URL
        else:
            raise FinancialE1PreflightError("E1 plan has an unknown endpoint")
        context = EgressRequestContext(
            provider_id=provider_id,
            dataset_key=request.dataset_key,
            target_url=target_url,
            deployment_region=deployment_region,
        )
        route = preview_route(context)
        if route.rule_id is None:
            raise FinancialE1PreflightError(
                "E1 endpoint lacks an exact persisted egress route",
                code="FINANCIAL_E1_EGRESS_ROUTE_BLOCKED",
            )


def _security_code(asset_code: str) -> str:
    """Return the six digits in an explicitly exchange-qualified symbol."""

    if (
        type(asset_code) is not str
        or len(asset_code) != 9
        or asset_code[6] != "."
        or asset_code[7:] not in {"SH", "SZ"}
        or not asset_code[:6].isascii()
        or not asset_code[:6].isdigit()
    ):
        raise FinancialE1PreflightError(
            "Balance request requires an explicit six-digit SH/SZ asset identity",
            code="FINANCIAL_E1_ASSET_IDENTITY_INVALID",
        )
    return asset_code[:6]


def _require_utc(value: object, field_name: str) -> datetime:
    """Require an explicit aware UTC clock without converting local time."""

    if type(value) is not datetime or value.tzinfo is None:
        raise FinancialE1PreflightError(
            f"{field_name} is not timezone-aware", code="FINANCIAL_E1_CLOCK_INVALID"
        )
    try:
        offset = value.utcoffset()
        if offset != timedelta(0):
            raise ValueError("timestamp is not UTC")
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise FinancialE1PreflightError(
            f"{field_name} is not a representable UTC clock",
            code="FINANCIAL_E1_CLOCK_INVALID",
        ) from error


__all__ = [
    "DjangoFinancialE1DatabaseClock",
    "DjangoFinancialE1ExactQualificationResolver",
    "DjangoFinancialE1PinnedPreflight",
    "DjangoFinancialE1RequestProjector",
    "DjangoFinancialE1SelectionLoader",
    "FinancialE1PreparedSelection",
    "FinancialE1PreflightError",
    "build_financial_e1_preflight_loader",
    "build_financial_e1_resolver",
]

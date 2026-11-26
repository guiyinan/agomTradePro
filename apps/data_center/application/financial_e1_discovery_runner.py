"""Finite E1 discovery capture, qualification, v3 write, and readback flow.

This application flow is separate from the frozen date-predeclared E1 v1 use
case. Main NOTICE is independently discovered and replayed from the exact Main
body; Balance keeps its own body and NOTICE. A stored result is reported only
after the injected v3 writer commits and independently reads back every
selected fact through its same-UOW verification path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Protocol
from uuid import UUID, uuid4

from apps.data_center.application.egress_service import FinancialResponseAttemptBudget
from apps.data_center.application.financial_e1_capture_use_case import (
    FinancialE1CaptureGatewayPort,
    FinancialE1NativeRowIdentity,
    FinancialE1RetainedResponse,
)
from apps.data_center.domain.control_plane import SyncRun
from apps.data_center.domain.entities import FinancialFact, RawAudit
from apps.data_center.domain.financial_e1_capture_contract import (
    FinancialE1EndpointRequest,
    FinancialE1ResponseRole,
    FinancialSharedResponseNoticeBindingV2,
)
from apps.data_center.domain.financial_e1_discovery_plan import FinancialE1DiscoveryPlanV2
from apps.data_center.domain.financial_numeric_catalog import FinancialNumericCatalogEntry
from apps.data_center.domain.financial_numeric_evidence import NativeFinancialMetricObservation
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceQualification,
)
from core.exceptions import DataFetchError, DataValidationError


class FinancialE1DiscoveryError(DataValidationError):
    """Stable failure raised when one finite E1 run cannot be completed."""

    default_message = "E1 财报原件或精确事实写入未能完成。"
    default_code = "FINANCIAL_E1_DISCOVERY_BLOCKED"


@dataclass(frozen=True, slots=True)
class FinancialE1PreflightSnapshot:
    """Actual selected catalog rows verified before the first provider request.

    Infrastructure constructs this only after reading the exact persisted
    qualification rows, Owner events, source-document captures, retained
    document bytes, provider identity, and current clocks. This metadata is a
    capture-readiness snapshot, not a qualification for a later raw response.
    """

    known_at: datetime
    entries: tuple[FinancialNumericCatalogEntry, ...]

    def __post_init__(self) -> None:
        """Require aware time and typed unique catalog entry rows."""

        _require_aware(self.known_at, "preflight known_at")
        if type(self.entries) is not tuple or not self.entries:
            raise ValueError("preflight must return a non-empty exact entry tuple")
        if any(type(entry) is not FinancialNumericCatalogEntry for entry in self.entries):
            raise TypeError("preflight entries must be typed catalog entry snapshots")
        if len({entry.entry_id for entry in self.entries}) != len(self.entries):
            raise ValueError("preflight returned a duplicate catalog entry")


class FinancialE1DiscoveryPreflightPort(Protocol):
    """Reload exact DB-owned catalog and retained documentation evidence."""

    def load_exact_current_selection(
        self,
        plan: FinancialE1DiscoveryPlanV2,
        *,
        known_at: datetime,
    ) -> FinancialE1PreflightSnapshot:
        """Raise before egress unless exactly the requested entries are current."""
        ...


@dataclass(frozen=True, slots=True)
class FinancialE1EndpointReplay:
    """One independently replayed raw row and its native observations/context."""

    role: FinancialE1ResponseRole
    row: FinancialE1NativeRowIdentity
    observations: tuple[NativeFinancialMetricObservation, ...]
    source_context: Mapping[str, object]
    notice_binding: FinancialSharedResponseNoticeBindingV2 | None = None

    def __post_init__(self) -> None:
        """Keep body, role, typed metrics, and immutable context aligned."""

        if type(self.role) is not FinancialE1ResponseRole:
            raise TypeError("endpoint replay role must be typed")
        if type(self.row) is not FinancialE1NativeRowIdentity:
            raise TypeError("endpoint replay row must be typed")
        if type(self.observations) is not tuple or not self.observations:
            raise ValueError("endpoint replay requires an immutable native observation tuple")
        if any(type(item) is not NativeFinancialMetricObservation for item in self.observations):
            raise TypeError("endpoint replay observations must be exact typed evidence")
        if not isinstance(self.source_context, Mapping) or any(
            type(key) is not str for key in self.source_context
        ):
            raise TypeError("raw source context must be a string-keyed mapping")
        object.__setattr__(self, "source_context", MappingProxyType(dict(self.source_context)))
        if self.role is FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC:
            if type(self.notice_binding) is not FinancialSharedResponseNoticeBindingV2:
                raise ValueError("Main replay must include its independently parsed NOTICE binding")
            if (
                self.notice_binding.artifact_reference.response_reference
                != self.row.artifact_reference
                or self.notice_binding.native_row_id != self.row.native_row_id
                or self.notice_binding.notice_date != self.row.notice_date
                or self.notice_binding.row_projection_sha256 != self.row.row_projection_sha256
            ):
                raise ValueError("Main numeric row and NOTICE projection do not match")
        elif self.notice_binding is not None:
            raise ValueError("Balance replay cannot borrow Main NOTICE evidence")
        metric_codes = tuple(item.contract.metric_code for item in self.observations)
        if len(set(metric_codes)) != len(metric_codes):
            raise ValueError("endpoint replay contains a duplicate metric")
        for observation in self.observations:
            if (
                observation.body_sha256 != self.row.artifact_reference.body_sha256
                or observation.native_row_id != self.row.native_row_id
                or observation.contract.provider != self.row.provider_name
                or observation.contract.dataset_key != self.row.dataset_key
            ):
                raise ValueError("observation does not bind its exact endpoint row")


class FinancialE1DiscoveryRoleReplayerPort(Protocol):
    """Strictly replay both roles from Main and native values from Balance."""

    def replay_main(
        self,
        plan: FinancialE1DiscoveryPlanV2,
        response: FinancialE1RetainedResponse,
        *,
        qualifications: tuple[FinancialNumericSourceQualification, ...],
    ) -> FinancialE1EndpointReplay:
        """Discover NOTICE from this exact Main body and replay selected fields."""
        ...

    def replay_balance(
        self,
        plan: FinancialE1DiscoveryPlanV2,
        response: FinancialE1RetainedResponse,
        *,
        qualifications: tuple[FinancialNumericSourceQualification, ...],
    ) -> FinancialE1EndpointReplay:
        """Replay Balance native values and its own raw NOTICE field."""
        ...


class FinancialE1ExactQualificationResolverPort(Protocol):
    """Resolve each selected contract against the actual response row and clocks."""

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
        """Return the exact persisted qualification or ``None`` when blocked."""
        ...


@dataclass(frozen=True, slots=True)
class FinancialE1FactWriteCandidate:
    """One selected native observation awaiting the same-UOW v3 builder/writer."""

    qualification: FinancialNumericSourceQualification
    row: FinancialE1NativeRowIdentity
    observation: NativeFinancialMetricObservation

    def __post_init__(self) -> None:
        """Reject any observation that differs from its selected contract or row."""

        if type(self.qualification) is not FinancialNumericSourceQualification:
            raise TypeError("write candidate requires the exact persisted qualification")
        if type(self.row) is not FinancialE1NativeRowIdentity:
            raise TypeError("write candidate requires a typed native row")
        if type(self.observation) is not NativeFinancialMetricObservation:
            raise TypeError("write candidate requires exact native numeric evidence")
        if (
            self.qualification.contract != self.observation.contract
            or self.qualification.endpoint != self.row.endpoint
            or self.observation.body_sha256 != self.row.artifact_reference.body_sha256
            or self.observation.native_row_id != self.row.native_row_id
        ):
            raise ValueError("write candidate differs from its qualification or source row")


class FinancialE1FactWriteReadbackPort(Protocol):
    """Build date-only v3 witnesses, write, and verify exact rows in one UOW."""

    def preview_recovery(
        self,
        candidates: tuple[FinancialE1FactWriteCandidate, ...],
        *,
        exchange: str,
        calendar_dataset_key: str,
    ) -> tuple[FinancialFact, ...]:
        """Return verified forecast rows without changing facts or run state."""
        ...

    def write_and_read_back(
        self,
        candidates: tuple[FinancialE1FactWriteCandidate, ...],
        *,
        exchange: str,
        calendar_dataset_key: str,
        run: SyncRun,
        main_raw_audit: RawAudit,
        balance_raw_audit: RawAudit,
    ) -> tuple[FinancialFact, ...]:
        """Return exact rows after readback and append the aggregate fetch audit."""
        ...


class FinancialE1DiscoveryClockPort(Protocol):
    """Supply trusted aware UTC time from the production composition."""

    def now_utc(self) -> datetime:
        """Return current server UTC time, never a request or report timestamp."""


class FinancialE1ExecutionAuthorityPort(Protocol):
    """Revalidate the current task actor and selected simulated-account owner."""

    def assert_current(self) -> None:
        """Raise before the next provider request or persistence boundary."""
        ...


class FinancialE1DiscoveryCaptureIdFactory(Protocol):
    """Create unique IDs for the two exact body and RawAudit records."""

    def __call__(self) -> UUID:
        """Return one new UUID without contacting a provider."""
        ...


@dataclass(frozen=True, slots=True)
class FinancialE1DiscoveryRunResult:
    """Finite per-run reconciliation; never a full-universe acceptance result."""

    outcome: str
    requested: int
    succeeded: int
    failed: int
    stored: int
    selection_sha256: str
    qualification_identities: tuple[str, ...]
    retained_capture_ids: tuple[str, ...]
    failure_code: str | None
    physical_attempts: int

    def __post_init__(self) -> None:
        """Keep counts, identities, and non-success outcomes internally exact."""

        if self.outcome not in {"stored", "partial", "blocked", "failed"}:
            raise ValueError("unsupported E1 discovery outcome")
        for name, value in (
            ("requested", self.requested),
            ("succeeded", self.succeeded),
            ("failed", self.failed),
            ("stored", self.stored),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.requested != self.succeeded + self.failed or self.stored != self.succeeded:
            raise ValueError("E1 discovery counts do not reconcile")
        if type(self.selection_sha256) is not str or len(self.selection_sha256) != 64:
            raise ValueError("selection_sha256 is invalid")
        if (
            type(self.qualification_identities) is not tuple
            or len(self.qualification_identities) != self.requested
        ):
            raise ValueError("result identities must exactly match requested count")
        if type(self.retained_capture_ids) is not tuple or len(self.retained_capture_ids) > 2:
            raise ValueError("result capture IDs exceed the two-response plan")
        if type(self.physical_attempts) is not int or not 0 <= self.physical_attempts <= 2:
            raise ValueError("physical attempts exceed the two-send ceiling")
        if self.outcome == "stored":
            if self.failure_code is not None or self.stored != self.requested:
                raise ValueError("stored result requires complete readback and no failure code")
        elif self.failure_code is None or self.stored != 0:
            raise ValueError("non-success result cannot claim stored facts")


class CaptureFinancialE1DiscoveryUseCase:
    """Capture two exact bodies and store only after every selected fact passes."""

    def __init__(
        self,
        *,
        preflight: FinancialE1DiscoveryPreflightPort,
        capture_gateway: FinancialE1CaptureGatewayPort,
        role_replayer: FinancialE1DiscoveryRoleReplayerPort,
        qualification_resolver: FinancialE1ExactQualificationResolverPort,
        fact_writer: FinancialE1FactWriteReadbackPort,
        clock: FinancialE1DiscoveryClockPort,
        authority_guard: FinancialE1ExecutionAuthorityPort,
        capture_id_factory: FinancialE1DiscoveryCaptureIdFactory = uuid4,
        retained_captures: tuple[UUID, UUID] | None = None,
    ) -> None:
        """Require real preflight, egress, replay, qualification, and writer ports."""

        if any(
            dependency is None
            for dependency in (
                preflight,
                capture_gateway,
                role_replayer,
                qualification_resolver,
                fact_writer,
                clock,
                authority_guard,
            )
        ):
            raise TypeError("E1 discovery requires every preflight and write boundary")
        if not callable(capture_id_factory):
            raise TypeError("capture_id_factory must be callable")
        self._preflight = preflight
        self._capture_gateway = capture_gateway
        self._role_replayer = role_replayer
        self._qualification_resolver = qualification_resolver
        self._fact_writer = fact_writer
        self._clock = clock
        self._authority_guard = authority_guard
        self._capture_id_factory = capture_id_factory
        self._retained_captures = retained_captures

    def prepare_retained_candidates(
        self,
        plan: FinancialE1DiscoveryPlanV2,
        main: FinancialE1RetainedResponse,
        balance: FinancialE1RetainedResponse,
    ) -> tuple[FinancialE1FactWriteCandidate, ...]:
        """Requalify both captured responses without constructing or sending a request."""

        self._authority_guard.assert_current()
        cutoff = self._clock.now_utc()
        if self._retained_captures is not None:
            refs = (main.retention.reference, balance.retention.reference)
            if tuple(ref.capture_id for ref in refs) != self._retained_captures:
                raise ValueError("This review is bound to a different pair of captures.")
            cutoff = min(ref.evidence.response_completed_at for ref in refs)
        snapshot = self._preflight.load_exact_current_selection(plan, known_at=cutoff)
        qualifications = _validate_preflight(plan, snapshot)
        if (
            main.request != plan.main_request
            or balance.request != plan.balance_request
            or main.retention.reference.capture_id == balance.retention.reference.capture_id
        ):
            raise ValueError("Recovery requires two distinct captures matching the pinned plan")
        main_replay = self._replay_retained_role(
            plan, main, qualifications, FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC
        )
        balance_replay = self._replay_retained_role(
            plan, balance, qualifications, FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC
        )
        return _resolve_candidates(
            qualifications=qualifications,
            main=main_replay,
            balance=balance_replay,
            resolver=self._qualification_resolver,
            known_at=self._clock.now_utc(),
        )

    def _replay_retained_role(
        self,
        plan: FinancialE1DiscoveryPlanV2,
        response: FinancialE1RetainedResponse,
        qualifications: tuple[FinancialNumericSourceQualification, ...],
        role: FinancialE1ResponseRole,
    ) -> FinancialE1EndpointReplay:
        selected = tuple(
            item for item in qualifications if item.endpoint == response.request.endpoint
        )
        replay = (
            self._role_replayer.replay_main
            if role is FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC
            else self._role_replayer.replay_balance
        )
        result = replay(plan, response, qualifications=selected)
        _validate_replay(
            result,
            response=response,
            expected_role=role,
            expected_qualifications=selected,
            plan=plan,
        )
        return result

    def preview_retained_recovery(
        self,
        plan: FinancialE1DiscoveryPlanV2,
        main: FinancialE1RetainedResponse,
        balance: FinancialE1RetainedResponse,
    ) -> tuple[FinancialFact, ...]:
        """Fully verify source, calendar, scope and numeric evidence with no new capture or write."""
        candidates = self.prepare_retained_candidates(plan, main, balance)
        return self._fact_writer.preview_recovery(
            candidates, exchange=plan.exchange, calendar_dataset_key=plan.calendar_dataset_key
        )

    def store_retained_recovery(
        self,
        plan: FinancialE1DiscoveryPlanV2,
        run: SyncRun,
        main: FinancialE1RetainedResponse,
        balance: FinancialE1RetainedResponse,
    ) -> tuple[FinancialFact, ...]:
        """Write one claimed recovery with current evidence and both original audit rows."""

        candidates = self.prepare_retained_candidates(plan, main, balance)
        return self._fact_writer.write_and_read_back(
            candidates,
            exchange=plan.exchange,
            calendar_dataset_key=plan.calendar_dataset_key,
            run=run,
            main_raw_audit=main.retention.audit,
            balance_raw_audit=balance.retention.audit,
        )

    def execute(
        self,
        plan: FinancialE1DiscoveryPlanV2,
        *,
        run: SyncRun,
    ) -> FinancialE1DiscoveryRunResult:
        """Run one finite plan; any incomplete stage returns no stored success."""

        if type(plan) is not FinancialE1DiscoveryPlanV2:
            raise TypeError("plan must be FinancialE1DiscoveryPlanV2")
        if self._retained_captures is not None:
            raise ValueError("This retained write review cannot perform a capture.")
        requested = len(plan.qualification_identities)
        if type(run) is not SyncRun:
            raise TypeError("run must be a persisted SyncRun returned by the owner repository")
        try:
            run_uuid = UUID(run.run_id)
        except (TypeError, ValueError) as error:
            raise ValueError("run must carry a canonical persisted UUID") from error
        if (
            str(run_uuid) != run.run_id.lower()
            or run.dataset_key != plan.main_request.dataset_key
            or run.provider_name != plan.provider_name
            or run.requested != requested
            or run.finished_at is not None
        ):
            raise ValueError("persisted run does not match the exact E1 execution plan")
        budget = FinancialResponseAttemptBudget(plan.maximum_physical_attempts)
        retained: list[FinancialE1RetainedResponse] = []
        try:
            preflight_at = self._clock.now_utc()
            _require_aware(preflight_at, "preflight known_at")
            snapshot = self._preflight.load_exact_current_selection(
                plan,
                known_at=preflight_at,
            )
            qualifications = _validate_preflight(plan, snapshot)
        except (
            DataFetchError,
            DataValidationError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            return _result(
                plan=plan,
                outcome="blocked",
                retained=retained,
                budget=budget,
                failure_code=_error_code(error, "FINANCIAL_E1_PREFLIGHT_BLOCKED"),
            )

        main_id = self._capture_id_factory()
        balance_id = self._capture_id_factory()
        if type(main_id) is not UUID or type(balance_id) is not UUID or main_id == balance_id:
            return _result(
                plan=plan,
                outcome="blocked",
                retained=retained,
                budget=budget,
                failure_code="FINANCIAL_E1_CAPTURE_IDENTITY_INVALID",
            )

        try:
            self._authority_guard.assert_current()
        except (DataFetchError, DataValidationError, RuntimeError, TypeError, ValueError) as error:
            return _result(
                plan=plan,
                outcome="blocked",
                retained=retained,
                budget=budget,
                failure_code=_error_code(error, "FINANCIAL_E1_AUTHORITY_REVOKED"),
            )
        main_response = self._capture_one(
            plan.main_request,
            request_id=main_id,
            budget=budget,
            run_id=run_uuid,
            retained=retained,
        )
        if main_response is None:
            return _result(
                plan=plan,
                outcome="failed",
                retained=retained,
                budget=budget,
                failure_code="FINANCIAL_E1_MAIN_CAPTURE_FAILED",
            )

        try:
            main_replay = self._replay_retained_role(
                plan, main_response, qualifications, FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC
            )
        except (
            DataFetchError,
            DataValidationError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            return _result(
                plan=plan,
                outcome="blocked",
                retained=retained,
                budget=budget,
                failure_code=_error_code(error, "FINANCIAL_E1_MAIN_REPLAY_BLOCKED"),
            )

        try:
            self._authority_guard.assert_current()
        except (DataFetchError, DataValidationError, RuntimeError, TypeError, ValueError) as error:
            return _result(
                plan=plan,
                outcome="partial",
                retained=retained,
                budget=budget,
                failure_code=_error_code(error, "FINANCIAL_E1_AUTHORITY_REVOKED"),
            )
        balance_response = self._capture_one(
            plan.balance_request,
            request_id=balance_id,
            budget=budget,
            run_id=run_uuid,
            retained=retained,
        )
        if balance_response is None:
            return _result(
                plan=plan,
                outcome="partial",
                retained=retained,
                budget=budget,
                failure_code="FINANCIAL_E1_BALANCE_CAPTURE_FAILED",
            )
        if (
            main_response.retention.reference.capture_id
            == balance_response.retention.reference.capture_id
            or main_response.retention.audit.raw_audit_id
            == balance_response.retention.audit.raw_audit_id
        ):
            return _result(
                plan=plan,
                outcome="blocked",
                retained=retained,
                budget=budget,
                failure_code="FINANCIAL_E1_RESPONSE_IDENTITY_REUSED",
            )

        try:
            balance_replay = self._replay_retained_role(
                plan,
                balance_response,
                qualifications,
                FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC,
            )
        except (
            DataFetchError,
            DataValidationError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            return _result(
                plan=plan,
                outcome="blocked",
                retained=retained,
                budget=budget,
                failure_code=_error_code(error, "FINANCIAL_E1_BALANCE_REPLAY_BLOCKED"),
            )

        try:
            known_at = self._clock.now_utc()
            _require_aware(known_at, "post-capture known_at")
            candidates = _resolve_candidates(
                qualifications=qualifications,
                main=main_replay,
                balance=balance_replay,
                resolver=self._qualification_resolver,
                known_at=known_at,
            )
            if budget.reserved_attempts != 2 or len(candidates) != requested:
                raise ValueError("finite E1 requests and native candidates do not reconcile")
            self._authority_guard.assert_current()
            written = self._fact_writer.write_and_read_back(
                candidates,
                exchange=plan.exchange,
                calendar_dataset_key=plan.calendar_dataset_key,
                run=run,
                main_raw_audit=main_response.retention.audit,
                balance_raw_audit=balance_response.retention.audit,
            )
            _validate_readback(candidates, written)
        except (
            DataFetchError,
            DataValidationError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            return _result(
                plan=plan,
                outcome="failed",
                retained=retained,
                budget=budget,
                failure_code=_error_code(error, "FINANCIAL_E1_WRITE_READBACK_FAILED"),
            )

        if budget.reserved_attempts != 2 or len(candidates) != requested:
            return _result(
                plan=plan,
                outcome="blocked",
                retained=retained,
                budget=budget,
                failure_code="FINANCIAL_E1_RECONCILIATION_MISMATCH",
            )
        return FinancialE1DiscoveryRunResult(
            outcome="stored",
            requested=requested,
            succeeded=len(written),
            failed=requested - len(written),
            stored=len(written),
            selection_sha256=plan.selection_sha256,
            qualification_identities=plan.qualification_identities,
            retained_capture_ids=(
                str(main_response.retention.reference.capture_id),
                str(balance_response.retention.reference.capture_id),
            ),
            failure_code=None,
            physical_attempts=budget.reserved_attempts,
        )

    def _capture_one(
        self,
        request: FinancialE1EndpointRequest,
        *,
        request_id: UUID,
        budget: FinancialResponseAttemptBudget,
        run_id: UUID | None,
        retained: list[FinancialE1RetainedResponse],
    ) -> FinancialE1RetainedResponse | None:
        """Reserve exactly one attempt and retain only its typed audited result."""

        before = budget.reserved_attempts
        try:
            response = self._capture_gateway.capture_one(
                request,
                request_id=request_id,
                attempt_budget=budget,
                run_id=run_id,
            )
        except (
            DataFetchError,
            DataValidationError,
            OSError,
            RuntimeError,
            TimeoutError,
            TypeError,
            ValueError,
        ):
            return None
        if (
            type(response) is not FinancialE1RetainedResponse
            or response.request != request
            or response.retention.reference.capture_id != request_id
            or response.observed_attempts != 1
            or budget.reserved_attempts - before != 1
        ):
            return None
        retained.append(response)
        return response


def _validate_preflight(
    plan: FinancialE1DiscoveryPlanV2,
    snapshot: FinancialE1PreflightSnapshot,
) -> tuple[FinancialNumericSourceQualification, ...]:
    """Require exact selected identities and current Owner/effective metadata."""

    if type(snapshot) is not FinancialE1PreflightSnapshot:
        raise ValueError("preflight did not return the typed catalog snapshot")
    _require_utc(snapshot.known_at, "preflight known_at")
    identities = tuple(entry.qualification.identity for entry in snapshot.entries)
    if set(identities) != set(plan.qualification_identities) or len(identities) != len(
        plan.qualification_identities
    ):
        raise ValueError("preflight rows do not exactly equal the finite requested set")
    if len({entry.qualification.contract.metric_code for entry in snapshot.entries}) != len(
        snapshot.entries
    ):
        raise ValueError("selected metric natural keys collide across endpoint groups")
    main_count = 0
    balance_count = 0
    qualifications: list[FinancialNumericSourceQualification] = []
    for entry in snapshot.entries:
        qualification = entry.qualification
        contract = qualification.contract
        if (
            type(qualification) is not FinancialNumericSourceQualification
            or contract.origin != "native"
            or contract.provider != plan.provider_name
            or contract.dataset_key != plan.main_request.dataset_key
            or entry.recorded_at > snapshot.known_at
            or entry.capture_recorded_at > snapshot.known_at
        ):
            raise ValueError("selected catalog entry is not fully known at preflight")
        apply_events = tuple(event for event in entry.owner_events if event.action == "apply")
        revoke_events = tuple(event for event in entry.owner_events if event.action == "revoke")
        if (
            len(apply_events) != 1
            or apply_events[0].event_at > snapshot.known_at
            or apply_events[0].recorded_at > snapshot.known_at
            or any(
                event.event_at <= snapshot.known_at and event.recorded_at <= snapshot.known_at
                for event in revoke_events
            )
            or qualification.effective_from > snapshot.known_at
            or (
                qualification.effective_until is not None
                and snapshot.known_at >= qualification.effective_until
            )
        ):
            raise ValueError("selected qualification is not currently applied and effective")
        if qualification.endpoint == plan.main_request.endpoint:
            main_count += 1
        elif qualification.endpoint == plan.balance_request.endpoint:
            balance_count += 1
        else:
            raise ValueError("selected qualification endpoint is outside the two E1 slots")
        qualifications.append(qualification)
    if main_count == 0 or balance_count == 0:
        raise ValueError("finite E1 selection must contain both exact endpoint groups")
    return tuple(qualifications)


def _validate_replay(
    replay: FinancialE1EndpointReplay,
    *,
    response: FinancialE1RetainedResponse,
    expected_role: FinancialE1ResponseRole,
    expected_qualifications: tuple[FinancialNumericSourceQualification, ...],
    plan: FinancialE1DiscoveryPlanV2,
) -> None:
    """Bind role replay, selected contracts, response body, and target period."""

    if type(replay) is not FinancialE1EndpointReplay or replay.role is not expected_role:
        raise ValueError("role replayer returned the wrong endpoint type")
    if (
        replay.row.artifact_reference != response.retention.reference
        or replay.row.provider_name != plan.provider_name
        or replay.row.dataset_key != plan.main_request.dataset_key
        or replay.row.endpoint != response.request.endpoint
        or replay.row.asset_code != plan.asset_code
        or replay.row.period_end != plan.period_end
        or replay.row.matched_row_count != 1
    ):
        raise ValueError("role replay row differs from the exact captured request")
    expected_contracts = {item.contract.identity: item.contract for item in expected_qualifications}
    observations = {item.contract.identity: item for item in replay.observations}
    if set(observations) != set(expected_contracts) or len(observations) != len(expected_contracts):
        raise ValueError("raw replay does not exactly cover the selected endpoint metrics")
    for identity, contract in expected_contracts.items():
        observation = observations[identity]
        if (
            observation.contract != contract
            or observation.contract_identity != identity
            or observation.contract_hash != contract.content_hash
            or observation.source_field != contract.source_field
        ):
            raise ValueError("raw observation differs from its selected catalog contract")


def _resolve_candidates(
    *,
    qualifications: tuple[FinancialNumericSourceQualification, ...],
    main: FinancialE1EndpointReplay,
    balance: FinancialE1EndpointReplay,
    resolver: FinancialE1ExactQualificationResolverPort,
    known_at: datetime,
) -> tuple[FinancialE1FactWriteCandidate, ...]:
    """Re-resolve every metric against actual raw context and response clocks."""

    _require_utc(known_at, "post-capture known_at")
    by_endpoint = {
        main.row.endpoint: main,
        balance.row.endpoint: balance,
    }
    candidates: list[FinancialE1FactWriteCandidate] = []
    for qualification in qualifications:
        replay = by_endpoint.get(qualification.endpoint)
        if replay is None:
            raise ValueError("selected qualification endpoint has no independently replayed body")
        observation = next(
            (
                item
                for item in replay.observations
                if item.contract.metric_code == qualification.contract.metric_code
            ),
            None,
        )
        if observation is None:
            raise ValueError("selected metric is absent from its unique raw row")
        response_completed_at = replay.row.artifact_reference.evidence.response_completed_at
        if response_completed_at > known_at:
            raise ValueError("raw response was not complete at the resolution knowledge cutoff")
        resolved = resolver.resolve_exact(
            qualification.identity,
            qualification.contract.identity,
            endpoint=qualification.endpoint,
            source_response_completed_at=response_completed_at,
            source_context=replay.source_context,
            known_at=known_at,
        )
        if type(resolved) is not FinancialNumericSourceQualification or resolved != qualification:
            raise ValueError("actual response context has no exact current catalog qualification")
        candidates.append(
            FinancialE1FactWriteCandidate(
                qualification=resolved,
                row=replay.row,
                observation=observation,
            )
        )
    return tuple(candidates)


def _validate_readback(
    candidates: tuple[FinancialE1FactWriteCandidate, ...],
    facts: tuple[FinancialFact, ...],
) -> None:
    """Require every selected exact Decimal revision to return from v3 reads."""

    if type(facts) is not tuple or len(facts) != len(candidates):
        raise ValueError("writer readback did not return every selected financial fact")
    expected = {
        (
            candidate.row.asset_code,
            candidate.row.period_end,
            candidate.observation.contract.metric_code,
        ): candidate
        for candidate in candidates
    }
    observed: set[tuple[str, object, str]] = set()
    for fact in facts:
        if type(fact) is not FinancialFact or fact.numeric_schema != "native-decimal-v2":
            raise ValueError("readback contains an unsupported financial schema")
        key = (fact.asset_code, fact.period_end, fact.metric_code)
        candidate = expected.get(key)
        if (
            candidate is None
            or type(fact.value) is not Decimal
            or fact.numeric_evidence != candidate.observation
            or fact.unit != candidate.observation.contract.canonical_unit
            or fact.source != candidate.observation.contract.provider
            or fact.decision_evidence is None
            or fact.decision_evidence.native_row_id != candidate.row.native_row_id
            or fact.decision_evidence.artifact_reference != candidate.row.artifact_reference
            or fact.available_at is None
            or fact.decision_evidence.source_time_witness_v3 is None
            or fact.decision_evidence.source_time_witness_v3.financial_row.notice_date
            != candidate.row.notice_date
        ):
            raise ValueError("v3 readback differs from the exact raw numeric candidate")
        observed.add(key)
    if observed != set(expected):
        raise ValueError("v3 readback duplicated or omitted selected metric rows")


def _capture_error_code(error: BaseException, fallback: str) -> str:
    """Return only a stable bounded domain error code."""

    raw: object = getattr(error, "code", None)
    if type(raw) is str and raw and raw.replace("_", "").isalnum():
        return raw[:96]
    return fallback


def _result(
    *,
    plan: FinancialE1DiscoveryPlanV2,
    outcome: str,
    retained: list[FinancialE1RetainedResponse],
    budget: FinancialResponseAttemptBudget,
    failure_code: str,
) -> FinancialE1DiscoveryRunResult:
    """Build an explicitly non-successful, count-reconciled result."""

    return FinancialE1DiscoveryRunResult(
        outcome=outcome,
        requested=len(plan.qualification_identities),
        succeeded=0,
        failed=len(plan.qualification_identities),
        stored=0,
        selection_sha256=plan.selection_sha256,
        qualification_identities=plan.qualification_identities,
        retained_capture_ids=tuple(str(item.retention.reference.capture_id) for item in retained),
        failure_code=failure_code,
        physical_attempts=budget.reserved_attempts,
    )


def _error_code(error: BaseException, fallback: str) -> str:
    """Return a stable domain error code without echoing source data."""

    return _capture_error_code(error, fallback)


def _require_aware(value: object, field_name: str) -> datetime:
    """Require a representable aware timestamp and reject naive clock inputs."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_utc(value: object, field_name: str) -> datetime:
    """Require exact zero-offset UTC at current capture/knowledge boundaries."""

    timestamp = _require_aware(value, field_name)
    if timestamp.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must use UTC")
    return timestamp


__all__ = [
    "CaptureFinancialE1DiscoveryUseCase",
    "FinancialE1DiscoveryError",
    "FinancialE1DiscoveryPreflightPort",
    "FinancialE1DiscoveryRunResult",
    "FinancialE1DiscoveryRoleReplayerPort",
    "FinancialE1EndpointReplay",
    "FinancialE1ExactQualificationResolverPort",
    "FinancialE1FactWriteCandidate",
    "FinancialE1FactWriteReadbackPort",
    "FinancialE1PreflightSnapshot",
]

"""Typed application orchestration for one bounded E1 financial capture.

This candidate preserves separate Main and Balance artifacts, audits, payloads,
and native row identities. It is not a production qualification or decision
path: a real composition must inject a qualification gate that verifies the
exact shared-Main NOTICE contract and every endpoint metric contract before
the first request and again after both captures.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

from apps.data_center.application.egress_service import FinancialResponseAttemptBudget
from apps.data_center.application.financial_response_artifact import (
    FinancialResponseArtifactRetention,
)
from apps.data_center.domain.entities import raw_audit_content_hash
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_e1_capture_contract import (
    FinancialE1CaptureContractV1,
    FinancialE1EndpointRequest,
    FinancialE1ResponseRole,
    FinancialSharedResponseNoticeBindingV2,
)
from apps.data_center.domain.financial_next_session_witness import FinancialNativeRowBinding
from apps.data_center.domain.financial_numeric_evidence import NativeFinancialMetricObservation
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import FinancialResponseScopeBasis
from core.exceptions import DataFetchError, DataValidationError

FinancialE1Outcome = Literal["captured", "partial", "blocked", "failed"]
FinancialE1FailureKind = Literal["blocked", "failed"]
_SHA256_CHARS = frozenset("0123456789abcdef")


class FinancialE1CaptureError(DataValidationError):
    """Stable, bounded failure raised when one E1 capture cannot be verified."""

    default_message = "E1 财报响应无法完成原件与来源验证。"
    default_code = "FINANCIAL_E1_CAPTURE_BLOCKED"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str,
        kind: FinancialE1FailureKind = "blocked",
        observed_attempts: int | None = None,
        orphan_reference: FinancialResponseArtifactRef | None = None,
    ) -> None:
        """Retain only a stable failure code and bounded retry evidence."""

        if kind not in {"blocked", "failed"}:
            raise ValueError("E1 capture failure kind is unsupported")
        if observed_attempts is not None and (
            type(observed_attempts) is not int or observed_attempts < 0
        ):
            raise ValueError("observed_attempts must be a non-negative integer or None")
        self.kind = kind
        self.observed_attempts = observed_attempts
        self.orphan_reference = orphan_reference
        super().__init__(message or self.default_message, code=code)


class FinancialE1ClockPort(Protocol):
    """Provide a trusted aware UTC knowledge clock to the application flow."""

    def now_utc(self) -> datetime:
        """Return the current server UTC instant without using a request clock."""
        ...


class FinancialE1CaptureIdFactory(Protocol):
    """Generate one unique UUID for each physical response capture."""

    def __call__(self) -> UUID:
        """Return a new UUID without contacting a provider."""
        ...


class FinancialE1CaptureQualificationPort(Protocol):
    """Check the real catalog and Owner evidence required before/after capture.

    Production implementations must fail closed unless the exact shared-Main
    NOTICE v2 contract, Main numeric contracts, and Balance numeric contracts
    are resolved from their real authoritative sources at ``known_at``. This
    port intentionally returns no caller-constructed boolean or approval DTO.
    """

    def assert_capture_ready(
        self,
        plan: FinancialE1CaptureContractV1,
        *,
        known_at: datetime,
    ) -> None:
        """Raise a stable business error unless this exact plan may be captured."""
        ...

    def assert_captured_pair_qualified(
        self,
        plan: FinancialE1CaptureContractV1,
        *,
        main_response: FinancialE1RetainedResponse,
        balance_response: FinancialE1RetainedResponse,
        main_notice: FinancialE1RoleReplay,
        main_numeric: FinancialE1RoleReplay,
        balance_numeric: FinancialE1RoleReplay,
        known_at: datetime,
    ) -> None:
        """Recheck exact catalog, source response clocks, contexts, and current Owner state."""
        ...


class FinancialE1CaptureGatewayPort(Protocol):
    """Capture and retain exactly one endpoint response through the egress path."""

    def capture_one(
        self,
        request: FinancialE1EndpointRequest,
        *,
        request_id: UUID,
        attempt_budget: FinancialResponseAttemptBudget,
        run_id: UUID | None,
    ) -> FinancialE1RetainedResponse:
        """Return one exact body after retention, RawAudit, and readback checks."""
        ...


class FinancialE1RoleReplayerPort(Protocol):
    """Replay each row role from the corresponding retained endpoint body."""

    def replay_main_notice(
        self,
        request: FinancialE1EndpointRequest,
        response: FinancialE1RetainedResponse,
        *,
        plan: FinancialE1CaptureContractV1,
    ) -> FinancialE1RoleReplay:
        """Independently replay Main NOTICE_DATE from the same retained body."""
        ...

    def replay_main_numeric(
        self,
        request: FinancialE1EndpointRequest,
        response: FinancialE1RetainedResponse,
        *,
        plan: FinancialE1CaptureContractV1,
    ) -> FinancialE1RoleReplay:
        """Independently replay Main native values from the same retained body."""
        ...

    def replay_balance_numeric(
        self,
        request: FinancialE1EndpointRequest,
        response: FinancialE1RetainedResponse,
        *,
        plan: FinancialE1CaptureContractV1,
    ) -> FinancialE1RoleReplay:
        """Replay Balance values and its own native NOTICE_DATE from Balance bytes."""
        ...


@dataclass(frozen=True, slots=True)
class FinancialE1NativeRowIdentity:
    """One endpoint-specific native row identity bound to one response artifact."""

    artifact_reference: FinancialResponseArtifactRef
    provider_name: str
    dataset_key: str
    endpoint: str
    asset_code: str
    period_end: date
    period_type: FinancialPeriodType
    notice_date: date
    native_row_id: str
    row_projection_sha256: str
    matched_row_count: int

    def __post_init__(self) -> None:
        """Require a body-verified single native row with its own source dates."""

        if type(self.artifact_reference) is not FinancialResponseArtifactRef:
            raise ValueError("native row requires an exact financial response reference")
        for field_name, value, maximum in (
            ("provider_name", self.provider_name, 128),
            ("dataset_key", self.dataset_key, 160),
            ("endpoint", self.endpoint, 512),
            ("asset_code", self.asset_code, 64),
            ("native_row_id", self.native_row_id, 256),
        ):
            _bounded_text(value, field_name, maximum)
        _require_date(self.period_end, "period_end")
        _require_date(self.notice_date, "notice_date")
        if type(self.period_type) is not FinancialPeriodType:
            raise ValueError("period_type must be an explicit FinancialPeriodType")
        if type(self.matched_row_count) is not int or self.matched_row_count != 1:
            raise ValueError("native row replay must match exactly one row")
        if not _is_sha256(self.row_projection_sha256):
            raise ValueError("row_projection_sha256 must be lowercase SHA-256")
        evidence = self.artifact_reference.evidence
        request_scope = evidence.request_scope
        response_scope = evidence.response_scope
        if (
            request_scope.provider_name != self.provider_name
            or request_scope.dataset_key != self.dataset_key
            or request_scope.asset_code != self.asset_code
            or evidence.response_scope_basis
            is not FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED
            or response_scope.row_count <= 0
            or self.period_end not in response_scope.period_ends
            or self.asset_code not in response_scope.asset_codes
        ):
            raise ValueError("native row identity does not match its verified response scope")

    def financial_row(self, metric_code: str) -> FinancialNativeRowBinding:
        """Build the C2 v3 financial_row for one metric without changing source identity."""

        _bounded_text(metric_code, "metric_code", 128)
        return FinancialNativeRowBinding(
            artifact_reference=self.artifact_reference,
            asset_code=self.asset_code,
            period_end=self.period_end,
            period_type=self.period_type,
            metric_code=metric_code,
            native_row_id=self.native_row_id,
            notice_date=self.notice_date,
            row_projection_sha256=self.row_projection_sha256,
            matched_row_count=self.matched_row_count,
        )


@dataclass(frozen=True, slots=True)
class FinancialE1RetainedResponse:
    """One separately retained endpoint payload, RawAudit, provider, and body."""

    request: FinancialE1EndpointRequest
    retention: FinancialResponseArtifactRetention
    raw_body: bytes
    provider_id: int
    provider_payload: object
    observed_attempts: int

    def __post_init__(self) -> None:
        """Bind the exact capture to its own request, provider, audit, and response bytes."""

        if type(self.request) is not FinancialE1EndpointRequest:
            raise ValueError("retained E1 request must be typed")
        if type(self.retention) is not FinancialResponseArtifactRetention:
            raise ValueError("retained E1 response must carry its artifact and RawAudit")
        if type(self.raw_body) is not bytes or not self.raw_body:
            raise ValueError("retained E1 body must be non-empty exact bytes")
        if type(self.provider_id) is not int or self.provider_id <= 0:
            raise ValueError("retained E1 provider id must be positive")
        if type(self.observed_attempts) is not int or self.observed_attempts != 1:
            raise ValueError("each E1 endpoint must use exactly one observed transport attempt")

        reference = self.retention.reference
        audit = self.retention.audit
        evidence = reference.evidence
        scope = evidence.request_scope
        response_scope = evidence.response_scope
        if (
            len(self.raw_body) != reference.body_size_bytes
            or hashlib.sha256(self.raw_body).hexdigest() != reference.body_sha256
            or scope.provider_name != self.request.provider_name
            or scope.dataset_key != self.request.dataset_key
            or scope.asset_code != self.request.request_asset_code
            or evidence.response_scope_basis
            is not FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED
            or response_scope.row_count <= 0
            or self.request.request_period_end not in response_scope.period_ends
            or self.request.request_asset_code not in response_scope.asset_codes
        ):
            raise ValueError("retained E1 artifact does not match its exact request and body")
        request_params = audit.request_params
        link = audit.extra.get("financial_response_artifact")
        if (
            audit.capability != "financial"
            or audit.status != "ok"
            or audit.provider_name != self.request.provider_name
            or audit.fetched_at != evidence.response_completed_at
            or audit.row_count != response_scope.row_count
            or audit.payload_size_bytes != reference.body_size_bytes
            or not audit.redacted
            or not audit.raw_audit_id
            or not audit.content_hash
            or audit.content_hash != raw_audit_content_hash(audit)
            or type(request_params) is not dict
            or request_params.get("endpoint") != self.request.endpoint
            or not isinstance(link, dict)
            or link.get("capture_id") != str(reference.capture_id)
            or link.get("body_sha256") != reference.body_sha256
            or link.get("provider_id") != self.provider_id
        ):
            raise ValueError("retained E1 RawAudit does not bind the endpoint artifact")


@dataclass(frozen=True, slots=True)
class FinancialE1RoleReplay:
    """One independently parsed role tied to one response and native row."""

    role: FinancialE1ResponseRole
    row: FinancialE1NativeRowIdentity
    native_observations: tuple[NativeFinancialMetricObservation, ...]
    notice_binding: FinancialSharedResponseNoticeBindingV2 | None
    provider_payload: object

    def __post_init__(self) -> None:
        """Keep Main date and numeric roles explicit and endpoint-specific."""

        if type(self.role) is not FinancialE1ResponseRole:
            raise ValueError("replayed E1 role must be typed")
        if type(self.row) is not FinancialE1NativeRowIdentity:
            raise ValueError("replayed E1 row must be typed")
        if type(self.native_observations) is not tuple:
            raise ValueError("native observations must be an immutable tuple")
        if not all(
            type(item) is NativeFinancialMetricObservation for item in self.native_observations
        ):
            raise ValueError("native observations must contain exact typed evidence")
        if self.role is FinancialE1ResponseRole.MAIN_NOTICE_DATE:
            if self.native_observations:
                raise ValueError("Main NOTICE replay cannot carry numeric observations")
            if type(self.notice_binding) is not FinancialSharedResponseNoticeBindingV2:
                raise ValueError("Main NOTICE replay requires the shared-response v2 binding")
            if (
                self.notice_binding.capture_id != self.row.artifact_reference.capture_id
                or self.notice_binding.artifact_reference.response_reference
                != self.row.artifact_reference
                or self.notice_binding.native_row_id != self.row.native_row_id
                or self.notice_binding.notice_date != self.row.notice_date
            ):
                raise ValueError("Main NOTICE binding does not match its exact row artifact")
        else:
            if self.notice_binding is not None:
                raise ValueError("numeric replay cannot carry a borrowed Main NOTICE binding")
            if not self.native_observations:
                raise ValueError("native numeric replay must contain at least one observation")
        metric_codes: set[str] = set()
        for observation in self.native_observations:
            if (
                observation.body_sha256 != self.row.artifact_reference.body_sha256
                or observation.native_row_id != self.row.native_row_id
                or observation.contract.provider != self.row.provider_name
                or observation.contract.dataset_key != self.row.dataset_key
                or observation.contract.metric_code in metric_codes
            ):
                raise ValueError("numeric observation does not match the endpoint row")
            metric_codes.add(observation.contract.metric_code)


@dataclass(frozen=True, slots=True)
class FinancialE1MainCapture:
    """Main response retained once and independently replayed for both roles."""

    response: FinancialE1RetainedResponse
    notice: FinancialE1RoleReplay
    numeric: FinancialE1RoleReplay
    financial_rows: tuple[FinancialNativeRowBinding, ...]

    def __post_init__(self) -> None:
        """Prove both Main roles reuse the same capture and exact native row."""

        if self.notice.role is not FinancialE1ResponseRole.MAIN_NOTICE_DATE:
            raise ValueError("Main capture must carry its NOTICE-date replay")
        if self.numeric.role is not FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC:
            raise ValueError("Main capture must carry its native numeric replay")
        if self.notice.row.artifact_reference != self.response.retention.reference:
            raise ValueError("Main NOTICE replay does not use the retained Main artifact")
        if self.numeric.row.artifact_reference != self.response.retention.reference:
            raise ValueError("Main numeric replay does not use the retained Main artifact")
        if not _same_native_row(self.notice.row, self.numeric.row):
            raise ValueError("Main numeric and NOTICE roles selected different native rows")
        _validate_financial_rows(self.numeric, self.financial_rows)


@dataclass(frozen=True, slots=True)
class FinancialE1BalanceCapture:
    """Balance response, RawAudit, row, own NOTICE date, and v3 rows."""

    response: FinancialE1RetainedResponse
    numeric: FinancialE1RoleReplay
    financial_rows: tuple[FinancialNativeRowBinding, ...]

    def __post_init__(self) -> None:
        """Require Balance values and v3 rows to use the separate Balance capture."""

        if self.numeric.role is not FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC:
            raise ValueError("Balance capture must carry its own native numeric replay")
        if self.numeric.row.artifact_reference != self.response.retention.reference:
            raise ValueError("Balance replay does not use the retained Balance artifact")
        _validate_financial_rows(self.numeric, self.financial_rows)


@dataclass(frozen=True, slots=True)
class FinancialE1CapturedPair:
    """Two retained endpoint responses with independent raw and row identities."""

    contract: FinancialE1CaptureContractV1
    main: FinancialE1MainCapture
    balance: FinancialE1BalanceCapture

    def __post_init__(self) -> None:
        """Reject capture or audit identity reuse across the two endpoint roles."""

        if type(self.contract) is not FinancialE1CaptureContractV1:
            raise ValueError("E1 captured pair requires the exact typed plan")
        if self.main.response.request != self.contract.main_request:
            raise ValueError("Main retained request differs from the E1 plan")
        if self.balance.response.request != self.contract.balance_request:
            raise ValueError("Balance retained request differs from the E1 plan")
        if (
            self.main.response.retention.reference.capture_id
            == self.balance.response.retention.reference.capture_id
            or self.main.response.retention.audit.raw_audit_id
            == self.balance.response.retention.audit.raw_audit_id
        ):
            raise ValueError("Main and Balance must have distinct capture and RawAudit identities")
        if self.main.response.provider_id != self.balance.response.provider_id:
            raise ValueError("Main and Balance artifacts must bind the same provider row")


@dataclass(frozen=True, slots=True)
class FinancialE1CaptureOutput:
    """Result of raw capture, explicitly separate from D1 or decision readiness."""

    outcome: FinancialE1Outcome
    captured_pair: FinancialE1CapturedPair | None
    retained_responses: tuple[FinancialE1RetainedResponse, ...]
    failure_code: str | None
    reserved_attempts: int

    def __post_init__(self) -> None:
        """Keep successful capture complete and partial/error states non-successful."""

        if self.outcome not in {"captured", "partial", "blocked", "failed"}:
            raise ValueError("unsupported E1 capture outcome")
        if type(self.retained_responses) is not tuple:
            raise ValueError("retained_responses must be an immutable tuple")
        if type(self.reserved_attempts) is not int or not 0 <= self.reserved_attempts <= 2:
            raise ValueError("reserved_attempts must stay within the two-send ceiling")
        if len(self.retained_responses) > self.reserved_attempts:
            raise ValueError("retained response count cannot exceed reserved physical attempts")
        if not all(type(item) is FinancialE1RetainedResponse for item in self.retained_responses):
            raise ValueError("retained_responses must contain typed audited artifacts")
        capture_ids = tuple(item.retention.reference.capture_id for item in self.retained_responses)
        audit_ids = tuple(item.retention.audit.raw_audit_id for item in self.retained_responses)
        if len(set(capture_ids)) != len(capture_ids) or len(set(audit_ids)) != len(audit_ids):
            raise ValueError("retained responses must have unique capture and RawAudit identities")
        if self.outcome == "captured":
            if (
                type(self.captured_pair) is not FinancialE1CapturedPair
                or self.failure_code is not None
            ):
                raise ValueError("captured output requires one complete pair and no failure code")
            if len(self.retained_responses) != 2 or self.reserved_attempts != 2:
                raise ValueError("captured output requires both independently retained responses")
            if self.retained_responses != (
                self.captured_pair.main.response,
                self.captured_pair.balance.response,
            ):
                raise ValueError("captured output responses must exactly match its complete pair")
        elif self.captured_pair is not None or self.failure_code is None:
            raise ValueError("partial, blocked, and failed outputs must not expose a pair")

    @property
    def evidence_only(self) -> bool:
        """Raw capture remains evidence-only even when both bodies were retained."""

        return True

    @property
    def production_ready(self) -> bool:
        """This isolated candidate never claims production or D1 eligibility."""

        return False

    @property
    def must_not_use_for_decision(self) -> bool:
        """Downstream decision code must use separately qualified canonical facts."""

        return True


class CaptureFinancialE1UseCase:
    """Capture Main once, replay its two roles, then capture and replay Balance once."""

    def __init__(
        self,
        capture_gateway: FinancialE1CaptureGatewayPort,
        role_replayer: FinancialE1RoleReplayerPort,
        qualification: FinancialE1CaptureQualificationPort,
        clock: FinancialE1ClockPort,
        *,
        capture_id_factory: FinancialE1CaptureIdFactory = uuid4,
    ) -> None:
        """Require real egress, role replay, qualification, and knowledge-clock ports."""

        if (
            capture_gateway is None
            or role_replayer is None
            or qualification is None
            or clock is None
        ):
            raise TypeError("E1 capture, replay, qualification, and clock ports are required")
        if not callable(capture_id_factory):
            raise TypeError("capture_id_factory must be callable")
        self._capture_gateway = capture_gateway
        self._role_replayer = role_replayer
        self._qualification = qualification
        self._clock = clock
        self._capture_id_factory = capture_id_factory

    def execute(
        self,
        plan: FinancialE1CaptureContractV1,
        *,
        run_id: UUID | None = None,
    ) -> FinancialE1CaptureOutput:
        """Return a complete two-response capture or an explicit non-success outcome."""

        if type(plan) is not FinancialE1CaptureContractV1:
            raise TypeError("plan must be FinancialE1CaptureContractV1")
        if run_id is not None and type(run_id) is not UUID:
            raise ValueError("run_id must be a UUID or None")
        budget = FinancialResponseAttemptBudget(plan.maximum_physical_attempts)
        retained: list[FinancialE1RetainedResponse] = []
        try:
            known_at = self._clock.now_utc()
            _require_utc(known_at, "known_at")
            self._qualification.assert_capture_ready(plan, known_at=known_at)
        except (DataFetchError, OSError, RuntimeError, TypeError, ValueError) as error:
            return _output(
                outcome="blocked",
                retained=retained,
                code=_error_code(error, "FINANCIAL_E1_CAPTURE_NOT_QUALIFIED"),
                budget=budget,
            )

        main_id = self._capture_id_factory()
        balance_id = self._capture_id_factory()
        if type(main_id) is not UUID or type(balance_id) is not UUID or main_id == balance_id:
            return _output(
                outcome="blocked",
                retained=retained,
                code="FINANCIAL_E1_CAPTURE_IDENTITY_INVALID",
                budget=budget,
            )

        main_response = self._capture_endpoint(
            plan.main_request,
            request_id=main_id,
            budget=budget,
            run_id=run_id,
            retained=retained,
        )
        if main_response is None:
            return _output(
                outcome="failed",
                retained=retained,
                code="FINANCIAL_E1_MAIN_CAPTURE_FAILED",
                budget=budget,
            )

        try:
            main_notice = self._role_replayer.replay_main_notice(
                plan.main_request,
                main_response,
                plan=plan,
            )
            main_numeric = self._role_replayer.replay_main_numeric(
                plan.main_request,
                main_response,
                plan=plan,
            )
            _require_role(main_notice, FinancialE1ResponseRole.MAIN_NOTICE_DATE)
            _require_role(main_numeric, FinancialE1ResponseRole.MAIN_NATIVE_NUMERIC)
            if not _same_native_row(main_notice.row, main_numeric.row):
                raise ValueError("Main numeric and NOTICE roles selected different native rows")
            main_financial_rows = _financial_rows(main_numeric)
            main = FinancialE1MainCapture(
                response=main_response,
                notice=main_notice,
                numeric=main_numeric,
                financial_rows=main_financial_rows,
            )
        except (DataFetchError, OSError, RuntimeError, TypeError, ValueError) as error:
            return _output(
                outcome="blocked",
                retained=retained,
                code=_error_code(error, "FINANCIAL_E1_MAIN_ROLE_REPLAY_BLOCKED"),
                budget=budget,
            )

        balance_response = self._capture_endpoint(
            plan.balance_request,
            request_id=balance_id,
            budget=budget,
            run_id=run_id,
            retained=retained,
        )
        if balance_response is None:
            return _output(
                outcome="partial",
                retained=retained,
                code="FINANCIAL_E1_BALANCE_CAPTURE_FAILED",
                budget=budget,
            )

        try:
            balance_numeric = self._role_replayer.replay_balance_numeric(
                plan.balance_request,
                balance_response,
                plan=plan,
            )
            _require_role(balance_numeric, FinancialE1ResponseRole.BALANCE_NATIVE_NUMERIC)
            if balance_numeric.row.notice_date == main.notice.row.notice_date:
                # Equal dates are valid source facts; this branch intentionally
                # does not substitute or require a different Balance date.
                pass
            balance = FinancialE1BalanceCapture(
                response=balance_response,
                numeric=balance_numeric,
                financial_rows=_financial_rows(balance_numeric),
            )
            pair = FinancialE1CapturedPair(contract=plan, main=main, balance=balance)
            final_known_at = self._clock.now_utc()
            _require_utc(final_known_at, "known_at")
            self._qualification.assert_captured_pair_qualified(
                plan,
                main_response=main_response,
                balance_response=balance_response,
                main_notice=main_notice,
                main_numeric=main_numeric,
                balance_numeric=balance_numeric,
                known_at=final_known_at,
            )
        except (DataFetchError, OSError, RuntimeError, TypeError, ValueError) as error:
            return _output(
                outcome="blocked",
                retained=retained,
                code=_error_code(error, "FINANCIAL_E1_PAIR_QUALIFICATION_BLOCKED"),
                budget=budget,
            )

        if budget.reserved_attempts != 2:
            return _output(
                outcome="blocked",
                retained=retained,
                code="FINANCIAL_E1_PHYSICAL_ATTEMPT_COUNT_MISMATCH",
                budget=budget,
            )
        return FinancialE1CaptureOutput(
            outcome="captured",
            captured_pair=pair,
            retained_responses=(main_response, balance_response),
            failure_code=None,
            reserved_attempts=budget.reserved_attempts,
        )

    def _capture_endpoint(
        self,
        request: FinancialE1EndpointRequest,
        *,
        request_id: UUID,
        budget: FinancialResponseAttemptBudget,
        run_id: UUID | None,
        retained: list[FinancialE1RetainedResponse],
    ) -> FinancialE1RetainedResponse | None:
        """Enforce one reserved physical attempt and preserve the exact response."""

        before = budget.reserved_attempts
        try:
            response = self._capture_gateway.capture_one(
                request,
                request_id=request_id,
                attempt_budget=budget,
                run_id=run_id,
            )
        except (DataFetchError, OSError, RuntimeError, TypeError, ValueError):
            return None
        delta = budget.reserved_attempts - before
        try:
            if (
                type(response) is not FinancialE1RetainedResponse
                or response.request != request
                or response.retention.reference.capture_id != request_id
                or response.observed_attempts != 1
                or delta != 1
            ):
                raise ValueError("endpoint response did not use one exact retained attempt")
        except (AttributeError, TypeError, ValueError):
            return None
        retained.append(response)
        return response


def _financial_rows(replay: FinancialE1RoleReplay) -> tuple[FinancialNativeRowBinding, ...]:
    """Build one v3 financial_row binding for each exact native observation."""

    if not replay.native_observations:
        raise ValueError("numeric replay did not return native observations")
    return tuple(
        replay.row.financial_row(observation.contract.metric_code)
        for observation in replay.native_observations
    )


def _validate_financial_rows(
    replay: FinancialE1RoleReplay,
    rows: tuple[FinancialNativeRowBinding, ...],
) -> None:
    """Keep every C2 row binding aligned with its own endpoint observation."""

    if type(rows) is not tuple or len(rows) != len(replay.native_observations):
        raise ValueError("v3 financial rows must match the role observation count")
    for binding, observation in zip(rows, replay.native_observations, strict=True):
        if (
            type(binding) is not FinancialNativeRowBinding
            or binding.artifact_reference != replay.row.artifact_reference
            or binding.asset_code != replay.row.asset_code
            or binding.period_end != replay.row.period_end
            or binding.notice_date != replay.row.notice_date
            or binding.native_row_id != replay.row.native_row_id
            or binding.row_projection_sha256 != replay.row.row_projection_sha256
            or binding.metric_code != observation.contract.metric_code
        ):
            raise ValueError("v3 financial_row does not preserve its endpoint-native row")


def _same_native_row(
    left: FinancialE1NativeRowIdentity, right: FinancialE1NativeRowIdentity
) -> bool:
    """Compare Main row identity dimensions while allowing role-specific projections."""

    return (
        left.artifact_reference == right.artifact_reference
        and left.provider_name == right.provider_name
        and left.dataset_key == right.dataset_key
        and left.endpoint == right.endpoint
        and left.asset_code == right.asset_code
        and left.period_end == right.period_end
        and left.period_type is right.period_type
        and left.notice_date == right.notice_date
        and left.native_row_id == right.native_row_id
        and left.matched_row_count == right.matched_row_count == 1
    )


def _require_role(result: FinancialE1RoleReplay, expected: FinancialE1ResponseRole) -> None:
    """Reject a parser output that was returned for the wrong endpoint role."""

    if type(result) is not FinancialE1RoleReplay or result.role is not expected:
        raise ValueError("E1 role replay returned the wrong endpoint role")


def _output(
    *,
    outcome: FinancialE1Outcome,
    retained: list[FinancialE1RetainedResponse],
    code: str,
    budget: FinancialResponseAttemptBudget,
) -> FinancialE1CaptureOutput:
    """Build a bounded no-pair result for any incomplete or blocked capture."""

    return FinancialE1CaptureOutput(
        outcome=outcome,
        captured_pair=None,
        retained_responses=tuple(retained),
        failure_code=code,
        reserved_attempts=budget.reserved_attempts,
    )


def _error_code(error: BaseException, fallback: str) -> str:
    """Return a stable business code without echoing provider payload text."""

    raw_code: object = getattr(error, "code", None)
    if type(raw_code) is str and raw_code and raw_code.replace("_", "").isalnum():
        return raw_code[:96]
    return fallback


def _bounded_text(value: object, field_name: str, maximum: int) -> None:
    """Require exact, bounded, unpadded identity text."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"{field_name} must be bounded canonical text")


def _is_sha256(value: object) -> bool:
    """Return whether one value is a lowercase SHA-256 digest."""

    return (
        type(value) is str
        and len(value) == 64
        and all(character in _SHA256_CHARS for character in value)
    )


def _require_date(value: object, field_name: str) -> None:
    """Require date precision and reject datetime subclasses."""

    if type(value) is not date:
        raise ValueError(f"{field_name} must be a date without a time component")


def _require_utc(value: object, field_name: str) -> None:
    """Require a real aware zero-offset server instant."""

    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != timedelta(0)
    ):
        raise ValueError(f"{field_name} must be an aware UTC datetime")


__all__ = [
    "CaptureFinancialE1UseCase",
    "FinancialE1BalanceCapture",
    "FinancialE1CaptureError",
    "FinancialE1CaptureIdFactory",
    "FinancialE1CaptureGatewayPort",
    "FinancialE1CaptureOutput",
    "FinancialE1CaptureQualificationPort",
    "FinancialE1CapturedPair",
    "FinancialE1ClockPort",
    "FinancialE1MainCapture",
    "FinancialE1NativeRowIdentity",
    "FinancialE1RetainedResponse",
    "FinancialE1RoleReplay",
    "FinancialE1RoleReplayerPort",
]

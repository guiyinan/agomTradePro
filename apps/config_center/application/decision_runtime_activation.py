"""Fail-closed activation workflow for decision-facing runtime surfaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils import timezone

from apps.config_center.application.repository_provider import (
    get_config_center_settings_repository,
)
from apps.config_center.domain.entities import DecisionRuntimeState, DecisionRuntimeStatus
from core.integration.data_center_readiness import (
    get_active_stock_fact_coverage_payload,
    get_decision_data_readiness_payload,
    get_decision_provider_capability_health_payload,
)

ReadinessPayload = dict[str, Any]
ReadinessProbe = Callable[[], ReadinessPayload]
RuntimeStateReader = Callable[[], DecisionRuntimeState]
RuntimeStateCompareAndSetter = Callable[
    [DecisionRuntimeState, DecisionRuntimeState], DecisionRuntimeState | None
]
RuntimeStateBlocker = Callable[[DecisionRuntimeState], DecisionRuntimeState]

ACTIVATION_ALLOWED_STATUSES = frozenset(
    {
        DecisionRuntimeStatus.BLOCKED,
        DecisionRuntimeStatus.VALIDATING,
    }
)


class DecisionRuntimeActivationError(ValueError):
    """Raised when activation cannot prove and preserve a safe transition."""


@dataclass(frozen=True)
class DecisionRuntimeActivationDependencies:
    """Injected reads and mutations used by the activation workflow."""

    read_runtime_state: RuntimeStateReader
    compare_and_set_runtime_state: RuntimeStateCompareAndSetter
    block_runtime_state: RuntimeStateBlocker
    probes: tuple[tuple[str, ReadinessProbe], ...]
    clock: Callable[[], datetime]


@dataclass(frozen=True)
class DecisionRuntimeActivationPreview:
    """Candidate-bound preflight that never mutates the runtime gate."""

    release_ref: str
    runtime_state: DecisionRuntimeState
    checks: dict[str, ReadinessPayload]
    failed_checks: tuple[str, ...]

    @property
    def ready(self) -> bool:
        """Return whether an exact compare-and-set activation may be attempted."""

        return self.runtime_state.status in ACTIVATION_ALLOWED_STATUSES and not self.failed_checks

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe preflight evidence."""

        return {
            "ready": self.ready,
            "release_ref": self.release_ref,
            "runtime_state": self.runtime_state.to_dict(),
            "failed_checks": list(self.failed_checks),
            "checks": self.checks,
        }


@dataclass(frozen=True)
class DecisionRuntimeActivationResult:
    """Final activated or automatically re-blocked runtime evidence."""

    activated: bool
    reblocked: bool
    release_ref: str
    runtime_state: DecisionRuntimeState
    checks: dict[str, ReadinessPayload]
    failed_checks: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe activation evidence."""

        return {
            "activated": self.activated,
            "reblocked": self.reblocked,
            "release_ref": self.release_ref,
            "runtime_state": self.runtime_state.to_dict(),
            "failed_checks": list(self.failed_checks),
            "checks": self.checks,
        }


class ActivateDecisionRuntimeUseCase:
    """Preflight, compare-and-set, revalidate, and fail closed on drift."""

    def __init__(self, dependencies: DecisionRuntimeActivationDependencies) -> None:
        probe_names = [name for name, _probe in dependencies.probes]
        if probe_names != ["core_coverage", "provider_capabilities", "decision_data"]:
            raise ValueError("activation probes must use the canonical three-check order")
        self._dependencies = dependencies

    def preview(self, *, release_ref: str) -> DecisionRuntimeActivationPreview:
        """Run the non-runtime strict checks without changing persisted state."""

        normalized_release_ref = _require_identity(release_ref, "release_ref", 200)
        runtime_state = self._dependencies.read_runtime_state()
        checks, failed_checks = self._run_probes()
        if runtime_state.status not in ACTIVATION_ALLOWED_STATUSES:
            failed_checks = ("runtime_state", *failed_checks)
        return DecisionRuntimeActivationPreview(
            release_ref=normalized_release_ref,
            runtime_state=runtime_state,
            checks=checks,
            failed_checks=failed_checks,
        )

    def execute(
        self,
        *,
        release_ref: str,
        changed_by: str,
    ) -> DecisionRuntimeActivationResult:
        """Activate only after strict preflight and automatically re-block on drift."""

        normalized_release_ref = _require_identity(release_ref, "release_ref", 200)
        normalized_changed_by = _require_identity(changed_by, "changed_by", 100)
        preview = self.preview(release_ref=normalized_release_ref)
        if not preview.ready:
            raise DecisionRuntimeActivationError(
                "decision runtime activation preflight is not ready: "
                + ", ".join(preview.failed_checks)
            )
        changed_at = self._dependencies.clock()
        _require_aware(changed_at, "activation clock")
        requested_state = DecisionRuntimeState(
            status=DecisionRuntimeStatus.ACTIVE,
            reason="",
            changed_at=changed_at,
            changed_by=normalized_changed_by,
            release_ref=normalized_release_ref,
        )
        activated_state = self._dependencies.compare_and_set_runtime_state(
            preview.runtime_state,
            requested_state,
        )
        if activated_state is None:
            raise DecisionRuntimeActivationError(
                "decision runtime state drifted before compare-and-set"
            )

        final_runtime_state = self._dependencies.read_runtime_state()
        checks, failed_checks = self._run_probes()
        runtime_matches = (
            final_runtime_state.status is DecisionRuntimeStatus.ACTIVE
            and final_runtime_state.release_ref == normalized_release_ref
            and final_runtime_state.changed_by == normalized_changed_by
        )
        if not runtime_matches:
            failed_checks = ("runtime_state", *failed_checks)
        if not failed_checks:
            return DecisionRuntimeActivationResult(
                activated=True,
                reblocked=False,
                release_ref=normalized_release_ref,
                runtime_state=final_runtime_state,
                checks=checks,
                failed_checks=(),
            )

        blocked_at = self._dependencies.clock()
        _require_aware(blocked_at, "reblock clock")
        blocked_state = self._dependencies.block_runtime_state(
            DecisionRuntimeState(
                status=DecisionRuntimeStatus.BLOCKED,
                reason=("Fail-closed activation verification failed: " + ", ".join(failed_checks)),
                changed_at=blocked_at,
                changed_by="system:decision-runtime-activation",
                release_ref=normalized_release_ref,
            )
        )
        if blocked_state.status is not DecisionRuntimeStatus.BLOCKED:
            raise DecisionRuntimeActivationError(
                "activation verification failed and runtime could not be re-blocked"
            )
        return DecisionRuntimeActivationResult(
            activated=False,
            reblocked=True,
            release_ref=normalized_release_ref,
            runtime_state=blocked_state,
            checks=checks,
            failed_checks=failed_checks,
        )

    def _run_probes(self) -> tuple[dict[str, ReadinessPayload], tuple[str, ...]]:
        """Run all canonical probes and normalize technical failures as blocked."""

        checks: dict[str, ReadinessPayload] = {}
        failed: list[str] = []
        for name, probe in self._dependencies.probes:
            try:
                payload = probe()
            except Exception:
                payload = {
                    "status": "error",
                    "must_not_use_for_decision": True,
                    "block_reason_code": f"{name}_probe_failed",
                }
            checks[name] = payload
            if not _is_ready(payload):
                failed.append(name)
        return checks, tuple(failed)


def make_decision_runtime_activation_use_case() -> ActivateDecisionRuntimeUseCase:
    """Compose the activation workflow from public application ports."""

    repository = get_config_center_settings_repository()

    def compare_and_set(
        expected: DecisionRuntimeState,
        state: DecisionRuntimeState,
    ) -> DecisionRuntimeState | None:
        return repository.compare_and_set_decision_runtime_state(
            expected=expected,
            state=state,
        )

    return ActivateDecisionRuntimeUseCase(
        DecisionRuntimeActivationDependencies(
            read_runtime_state=repository.get_decision_runtime_state,
            compare_and_set_runtime_state=compare_and_set,
            block_runtime_state=repository.set_decision_runtime_state,
            probes=(
                ("core_coverage", get_active_stock_fact_coverage_payload),
                (
                    "provider_capabilities",
                    get_decision_provider_capability_health_payload,
                ),
                ("decision_data", get_decision_data_readiness_payload),
            ),
            clock=timezone.now,
        )
    )


def _is_ready(payload: ReadinessPayload) -> bool:
    """Return whether one strict probe explicitly proves readiness."""

    return bool(
        payload.get("status") == "ok" and payload.get("must_not_use_for_decision") is not True
    )


def _require_identity(value: str, field_name: str, max_length: int) -> str:
    """Return a bounded single-line operator or candidate identity."""

    normalized = str(value or "").strip()
    if (
        not normalized
        or len(normalized) > max_length
        or any(marker in value for marker in ("\r", "\n"))
    ):
        raise DecisionRuntimeActivationError(
            f"{field_name} must be a non-empty single-line value of at most "
            f"{max_length} characters"
        )
    return normalized


def _require_aware(value: datetime, field_name: str) -> None:
    """Reject naive activation and rollback clocks."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise DecisionRuntimeActivationError(f"{field_name} must be timezone-aware")


__all__ = [
    "ActivateDecisionRuntimeUseCase",
    "DecisionRuntimeActivationDependencies",
    "DecisionRuntimeActivationError",
    "DecisionRuntimeActivationPreview",
    "DecisionRuntimeActivationResult",
    "make_decision_runtime_activation_use_case",
]

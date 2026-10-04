"""Read-only preflight for the production full-market publication chain.

The production full-market task can run for well over an hour before the
publication stage fails closed on a configuration or wiring problem. This use
case moves those failure modes to a minutes-level, strictly read-only gate:
it never writes database rows, never dispatches provider fetches, and never
moves any current publication pointer. Every check runs to completion and
reports stable blocked codes so operators see the full failure set at once.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from django.db import DatabaseError

from apps.data_center.domain.protocols import PublicationPolicyRepositoryProtocol
from apps.data_center.domain.raw_audit_manifest import CURRENT_MARKET_PUBLICATION_DATASETS
from core.exceptions import AgomTradeProException
from core.integration import data_center_audit as audit_integration

from .current_market_publication_activation import CurrentMarketPublicationBundle
from .model_market_data import ModelMarketDataService
from .model_market_data_preparation import evaluate_model_market_bulk_preparation
from .publication_activation import (
    CurrentPublicationPointerSnapshot,
    PublicationActivationError,
)

PREFLIGHT_REPORT_SCHEMA = "data_center.full_market_publication_preflight.v1"

CHECK_PROVIDER_POLICY_AND_ROUTES = "provider_policy_and_routes"
CHECK_CURRENT_PUBLICATION_GATES = "current_publication_gates"
CHECK_ACCOUNT_AUTHORITY_CAPTURE = "account_authority_capture"
CHECK_TASK_ATTEMPT_IDENTITY = "task_attempt_identity"

CANONICAL_CHECK_NAMES: tuple[str, ...] = (
    CHECK_PROVIDER_POLICY_AND_ROUTES,
    CHECK_CURRENT_PUBLICATION_GATES,
    CHECK_ACCOUNT_AUTHORITY_CAPTURE,
    CHECK_TASK_ATTEMPT_IDENTITY,
)

PREFLIGHT_PROVIDER_SETTINGS_BLOCKED = "PREFLIGHT_PROVIDER_SETTINGS_BLOCKED"
PREFLIGHT_MODEL_MARKET_ROUTES_UNAVAILABLE = "PREFLIGHT_MODEL_MARKET_ROUTES_UNAVAILABLE"
PREFLIGHT_PUBLICATION_BUNDLE_UNAVAILABLE = "PREFLIGHT_PUBLICATION_BUNDLE_UNAVAILABLE"
PREFLIGHT_PUBLICATION_REBUILDERS_INCOMPLETE = "PREFLIGHT_PUBLICATION_REBUILDERS_INCOMPLETE"
PREFLIGHT_PUBLICATION_POLICY_MISSING = "PREFLIGHT_PUBLICATION_POLICY_MISSING"
PREFLIGHT_PUBLICATION_POLICY_NOT_VERSIONED = "PREFLIGHT_PUBLICATION_POLICY_NOT_VERSIONED"
PREFLIGHT_PUBLICATION_POLICY_UNAVAILABLE = "PREFLIGHT_PUBLICATION_POLICY_UNAVAILABLE"
PREFLIGHT_PUBLICATION_UNIVERSE_UNAVAILABLE = "PREFLIGHT_PUBLICATION_UNIVERSE_UNAVAILABLE"
PREFLIGHT_AUTHORITY_CAPTURE_UNAVAILABLE = "PREFLIGHT_AUTHORITY_CAPTURE_UNAVAILABLE"
PREFLIGHT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE = "PREFLIGHT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE"

# Codes reused verbatim from the production publication path so a preflight
# block predicts the exact production failure identity.
CURRENT_PUBLICATION_COMPOSITION_UNAVAILABLE = "CURRENT_PUBLICATION_COMPOSITION_UNAVAILABLE"
CURRENT_PUBLICATION_CURRENT_POINTER_UNAVAILABLE = "CURRENT_PUBLICATION_CURRENT_POINTER_UNAVAILABLE"
CURRENT_PUBLICATION_PREVIEW_FAILED = "CURRENT_PUBLICATION_PREVIEW_FAILED"

ATTEMPT_RESOLUTION_BOUND = "bound_to_active_attempt"
ATTEMPT_RESOLUTION_OUTSIDE_TASK = "expected_unavailable_outside_task"


@dataclass(frozen=True, slots=True)
class AuthorityCaptureProbeEvidence:
    """Read-only proof that the production Account authority capture is wired."""

    environment: str
    mode: str
    scope_schema: str
    snapshot_id: str


@dataclass(frozen=True, slots=True)
class TaskAttemptIdentityProbeEvidence:
    """Read-only proof that the Task Monitor attempt identity path assembles."""

    repository: str
    resolution: str

    def __post_init__(self) -> None:
        """Keep the resolution vocabulary closed and explicit."""

        if self.resolution not in {ATTEMPT_RESOLUTION_BOUND, ATTEMPT_RESOLUTION_OUTSIDE_TASK}:
            raise ValueError("task attempt identity probe resolution is not supported")


@dataclass(frozen=True, slots=True)
class FullMarketPublicationPreflightPorts:
    """Application-owned collaborators; every port is strictly read-only."""

    load_provider_settings: Callable[[], Mapping[str, object]]
    build_model_market_service: Callable[[Mapping[str, object]], ModelMarketDataService]
    build_publication_bundle: Callable[[], CurrentMarketPublicationBundle]
    publication_policies: PublicationPolicyRepositoryProtocol
    load_active_universe: Callable[[], tuple[str, ...]]
    probe_authority_capture: Callable[[], AuthorityCaptureProbeEvidence]
    probe_task_attempt_identity: Callable[[], TaskAttemptIdentityProbeEvidence]
    clock: Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class PreflightCheckOutcome:
    """Stable result of one preflight check."""

    name: str
    status: Literal["pass", "blocked"]
    blocked_codes: tuple[str, ...]
    detail: str
    evidence: Mapping[str, object]

    def __post_init__(self) -> None:
        """Keep one closed vocabulary: pass carries no codes, blocked requires one."""

        if not self.name.strip():
            raise ValueError("preflight check name cannot be empty")
        if self.status == "pass" and self.blocked_codes:
            raise ValueError("a passing preflight check cannot carry blocked codes")
        if self.status == "blocked" and not self.blocked_codes:
            raise ValueError("a blocked preflight check requires at least one stable code")

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON-safe check payload."""

        return {
            "name": self.name,
            "status": self.status,
            "blocked_codes": list(self.blocked_codes),
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class FullMarketPublicationPreflightReport:
    """Aggregated read-only preflight evidence across all checks."""

    evaluated_at: datetime
    checks: tuple[PreflightCheckOutcome, ...]

    def __post_init__(self) -> None:
        """Require a non-empty selection of known checks in canonical order."""

        names = tuple(check.name for check in self.checks)
        if not names:
            raise ValueError("preflight report must contain at least one check")
        expected = tuple(name for name in CANONICAL_CHECK_NAMES if name in names)
        if names != expected:
            raise ValueError("preflight report checks must be known and in canonical order")

    @property
    def outcome(self) -> Literal["pass", "blocked"]:
        """Return pass only when every check passed."""

        if any(check.status == "blocked" for check in self.checks):
            return "blocked"
        return "pass"

    @property
    def blocked_codes(self) -> tuple[str, ...]:
        """Return the sorted set of every stable blocked code."""

        return tuple(sorted({code for check in self.checks for code in check.blocked_codes}))

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON-safe report written to stdout."""

        return {
            "schema": PREFLIGHT_REPORT_SCHEMA,
            "outcome": self.outcome,
            "evaluated_at": self.evaluated_at.isoformat(),
            "blocked_codes": list(self.blocked_codes),
            "checks": [check.to_dict() for check in self.checks],
        }


def _passed(name: str, evidence: Mapping[str, object]) -> PreflightCheckOutcome:
    """Build one passing check outcome."""

    return PreflightCheckOutcome(
        name=name,
        status="pass",
        blocked_codes=(),
        detail="",
        evidence=evidence,
    )


def _blocked(name: str, codes: tuple[str, ...], detail: str) -> PreflightCheckOutcome:
    """Build one blocked check outcome with at least one stable code."""

    return PreflightCheckOutcome(
        name=name,
        status="blocked",
        blocked_codes=tuple(dict.fromkeys(codes)),
        detail=detail,
        evidence={},
    )


def _code_of(error: BaseException, fallback: str) -> str:
    """Reuse the exact application error code when one is available."""

    if isinstance(error, AgomTradeProException) and error.code:
        return error.code
    return fallback


def _payload_sha256(payload: Mapping[str, object]) -> str:
    """Hash the canonical JSON form of one settings payload deterministically."""

    canonical = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RunFullMarketPublicationPreflightUseCase:
    """Run every read-only full-market publication gate and aggregate codes."""

    def __init__(self, ports: FullMarketPublicationPreflightPorts) -> None:
        self._ports = ports

    def execute(
        self,
        checks: tuple[str, ...] | None = None,
    ) -> FullMarketPublicationPreflightReport:
        """Run the selected checks to completion; never short-circuit on a block."""

        selected = CANONICAL_CHECK_NAMES if checks is None else tuple(dict.fromkeys(checks))
        unknown = [name for name in selected if name not in CANONICAL_CHECK_NAMES]
        if unknown:
            raise ValueError(f"unknown preflight checks: {','.join(unknown)}")
        if not selected:
            raise ValueError("at least one preflight check must be selected")
        runners = {
            CHECK_PROVIDER_POLICY_AND_ROUTES: self._check_provider_policy_and_routes,
            CHECK_CURRENT_PUBLICATION_GATES: self._check_current_publication_gates,
            CHECK_ACCOUNT_AUTHORITY_CAPTURE: self._check_account_authority_capture,
            CHECK_TASK_ATTEMPT_IDENTITY: self._check_task_attempt_identity,
        }
        return FullMarketPublicationPreflightReport(
            evaluated_at=self._ports.clock(),
            checks=tuple(runners[name]() for name in CANONICAL_CHECK_NAMES if name in selected),
        )

    def _check_provider_policy_and_routes(self) -> PreflightCheckOutcome:
        """Verify provider runtime settings and audited bulk route capability."""

        name = CHECK_PROVIDER_POLICY_AND_ROUTES
        try:
            settings_payload = dict(self._ports.load_provider_settings())
        except AgomTradeProException as exc:
            return _blocked(name, (exc.code,), type(exc).__name__)
        except Exception as exc:
            return _blocked(name, (PREFLIGHT_PROVIDER_SETTINGS_BLOCKED,), type(exc).__name__)
        if settings_payload.get("status") != "active":
            reason = str(settings_payload.get("blocked_reason") or "provider_settings_not_active")
            return _blocked(name, (PREFLIGHT_PROVIDER_SETTINGS_BLOCKED,), reason)
        try:
            service = self._ports.build_model_market_service(settings_payload)
        except AgomTradeProException as exc:
            return _blocked(name, (exc.code,), type(exc).__name__)
        except Exception as exc:
            return _blocked(name, (PREFLIGHT_MODEL_MARKET_ROUTES_UNAVAILABLE,), type(exc).__name__)
        # A full-market scope always exceeds any bounded per-asset preparation
        # limit, so probe one asset above the configured limit.
        probe_asset_count = (service.max_per_asset_preparation_assets or 0) + 1
        try:
            gate = evaluate_model_market_bulk_preparation(
                routes=service.configured_routes,
                requested_count=probe_asset_count,
                max_per_asset_preparation_assets=service.max_per_asset_preparation_assets,
            )
        except AgomTradeProException as exc:
            return _blocked(name, (exc.code,), type(exc).__name__)
        return _passed(
            name,
            {
                "default_source": settings_payload.get("default_source"),
                "enable_failover": settings_payload.get("enable_failover"),
                "failover_tolerance": settings_payload.get("failover_tolerance"),
                "provider_settings_sha256": _payload_sha256(settings_payload),
                "preferred_route": gate.preferred_route,
                "probe_asset_count": gate.requested_count,
                "route_capabilities": [item.to_dict() for item in gate.route_capabilities],
            },
        )

    def _check_current_publication_gates(self) -> PreflightCheckOutcome:
        """Verify bundle composition, dataset policies, and a dry-run preview."""

        name = CHECK_CURRENT_PUBLICATION_GATES
        bundle_outcome = self._build_bundle(name)
        if isinstance(bundle_outcome, PreflightCheckOutcome):
            return bundle_outcome
        bundle = bundle_outcome
        expected_datasets = tuple(sorted(CURRENT_MARKET_PUBLICATION_DATASETS))
        rebuilder_datasets = tuple(
            sorted(rebuilder.dataset.dataset_key for rebuilder in bundle.previewer.rebuilders)
        )
        if rebuilder_datasets != expected_datasets:
            return _blocked(
                name,
                (PREFLIGHT_PUBLICATION_REBUILDERS_INCOMPLETE,),
                ",".join(rebuilder_datasets),
            )
        pointer_outcome = self._read_current_pointers(
            name=name,
            bundle=bundle,
            dataset_keys=expected_datasets,
        )
        if isinstance(pointer_outcome, PreflightCheckOutcome):
            return pointer_outcome
        pointer_evidence = pointer_outcome
        policy_codes: list[str] = []
        policy_evidence: dict[str, object] = {}
        for dataset_key in expected_datasets:
            try:
                policy = self._ports.publication_policies.get_active(dataset_key)
            except Exception as exc:
                policy_codes.append(PREFLIGHT_PUBLICATION_POLICY_UNAVAILABLE)
                policy_evidence[dataset_key] = {"error_type": type(exc).__name__}
                continue
            if policy is None:
                policy_codes.append(PREFLIGHT_PUBLICATION_POLICY_MISSING)
                policy_evidence[dataset_key] = {"active_policy": None}
                continue
            if not policy.uses_versioned_evidence:
                policy_codes.append(PREFLIGHT_PUBLICATION_POLICY_NOT_VERSIONED)
            policy_evidence[dataset_key] = {
                "active_policy": policy.identity,
                "policy_version": policy.policy_version,
                "uses_versioned_evidence": policy.uses_versioned_evidence,
                "minimum_coverage_ratio": policy.minimum_coverage_ratio,
                "allow_partial": policy.allow_partial,
            }
        if policy_codes:
            outcome = _blocked(name, tuple(policy_codes), "publication policy gate unavailable")
            return PreflightCheckOutcome(
                name=outcome.name,
                status=outcome.status,
                blocked_codes=outcome.blocked_codes,
                detail=outcome.detail,
                evidence={"policies": policy_evidence},
            )
        try:
            universe = tuple(
                sorted(
                    {
                        str(code or "").strip().upper()
                        for code in self._ports.load_active_universe()
                        if str(code or "").strip()
                    }
                )
            )
        except Exception as exc:
            return _blocked(name, (PREFLIGHT_PUBLICATION_UNIVERSE_UNAVAILABLE,), type(exc).__name__)
        if not universe:
            return _blocked(
                name, (PREFLIGHT_PUBLICATION_UNIVERSE_UNAVAILABLE,), "active_universe_empty"
            )
        published_at = self._ports.clock()
        try:
            preview = bundle.previewer.preview(
                asset_codes=universe,
                published_at=published_at,
            )
        except Exception as exc:
            return _blocked(
                name,
                (_code_of(exc, CURRENT_PUBLICATION_PREVIEW_FAILED),),
                type(exc).__name__,
            )
        preview_by_dataset = {item.dataset_key: item for item in preview.datasets}
        if set(preview_by_dataset) != set(expected_datasets):
            return _blocked(
                name,
                (CURRENT_PUBLICATION_PREVIEW_FAILED,),
                "preview dataset set is incomplete",
            )
        return _passed(
            name,
            {
                "universe_asset_count": len(universe),
                "current_pointers": pointer_evidence,
                "policies": policy_evidence,
                "preview": {
                    dataset_key: preview_by_dataset[dataset_key].to_dict()
                    for dataset_key in expected_datasets
                },
            },
        )

    @staticmethod
    def _read_current_pointers(
        *,
        name: str,
        bundle: CurrentMarketPublicationBundle,
        dataset_keys: tuple[str, ...],
    ) -> dict[str, object] | PreflightCheckOutcome:
        """Read and validate every current-pointer CAS pair without mutation."""

        evidence: dict[str, object] = {}
        try:
            for dataset_key in dataset_keys:
                snapshot = bundle.current_pointer_reader(dataset_key, "current")
                if type(snapshot) is not CurrentPublicationPointerSnapshot:
                    raise PublicationActivationError(
                        "current pointer reader returned an invalid pair"
                    )
                snapshot.__post_init__()
                evidence[dataset_key] = {
                    "state": "empty" if snapshot.publication_id is None else "bound",
                    "publication_id": snapshot.publication_id,
                    "publication_hash": snapshot.publication_hash,
                }
        except (
            PublicationActivationError,
            audit_integration.SystemAuditCompositionUnavailable,
            DatabaseError,
            TypeError,
            ValueError,
        ) as exc:
            return _blocked(
                name,
                (CURRENT_PUBLICATION_CURRENT_POINTER_UNAVAILABLE,),
                type(exc).__name__,
            )
        return evidence

    def _check_account_authority_capture(self) -> PreflightCheckOutcome:
        """Verify complete Account authority capture wiring without fencing."""

        name = CHECK_ACCOUNT_AUTHORITY_CAPTURE
        try:
            evidence = self._ports.probe_authority_capture()
        except audit_integration.SystemAuditCompositionUnavailable as exc:
            return _blocked(name, (PREFLIGHT_AUTHORITY_CAPTURE_UNAVAILABLE,), exc.reason_code)
        except Exception as exc:
            return _blocked(name, (PREFLIGHT_AUTHORITY_CAPTURE_UNAVAILABLE,), type(exc).__name__)
        bundle_outcome = self._build_bundle(name)
        if isinstance(bundle_outcome, PreflightCheckOutcome):
            return PreflightCheckOutcome(
                name=name,
                status="blocked",
                blocked_codes=(PREFLIGHT_AUTHORITY_CAPTURE_UNAVAILABLE,),
                detail=bundle_outcome.detail,
                evidence={},
            )
        if not callable(getattr(bundle_outcome, "authority_capture", None)):
            return _blocked(
                name,
                (PREFLIGHT_AUTHORITY_CAPTURE_UNAVAILABLE,),
                "authority_capture_factory_missing",
            )
        return _passed(
            name,
            {
                "environment": evidence.environment,
                "mode": evidence.mode,
                "scope_schema": evidence.scope_schema,
                "snapshot_id": evidence.snapshot_id,
                "authority_capture_factory": "wired",
            },
        )

    def _check_task_attempt_identity(self) -> PreflightCheckOutcome:
        """Verify the Task Monitor attempt identity path assembles fail-closed."""

        name = CHECK_TASK_ATTEMPT_IDENTITY
        try:
            evidence = self._ports.probe_task_attempt_identity()
        except AgomTradeProException as exc:
            return _blocked(name, (exc.code,), type(exc).__name__)
        except Exception as exc:
            return _blocked(
                name, (PREFLIGHT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE,), type(exc).__name__
            )
        return _passed(
            name,
            {
                "repository": evidence.repository,
                "resolution": evidence.resolution,
            },
        )

    def _build_bundle(self, name: str) -> CurrentMarketPublicationBundle | PreflightCheckOutcome:
        """Compose the production bundle read-only or return a blocked outcome."""

        try:
            bundle = self._ports.build_publication_bundle()
        except audit_integration.SystemAuditCompositionUnavailable as exc:
            return _blocked(name, (PREFLIGHT_PUBLICATION_BUNDLE_UNAVAILABLE,), exc.reason_code)
        except DatabaseError as exc:
            return _blocked(
                name, (CURRENT_PUBLICATION_COMPOSITION_UNAVAILABLE,), type(exc).__name__
            )
        except AgomTradeProException as exc:
            return _blocked(name, (exc.code,), type(exc).__name__)
        except Exception as exc:
            return _blocked(name, (PREFLIGHT_PUBLICATION_BUNDLE_UNAVAILABLE,), type(exc).__name__)
        if bundle.database_alias != "default":
            return _blocked(
                name, (PREFLIGHT_PUBLICATION_BUNDLE_UNAVAILABLE,), "composition_alias_mismatch"
            )
        return bundle


__all__ = [
    "ATTEMPT_RESOLUTION_BOUND",
    "ATTEMPT_RESOLUTION_OUTSIDE_TASK",
    "AuthorityCaptureProbeEvidence",
    "CANONICAL_CHECK_NAMES",
    "CHECK_ACCOUNT_AUTHORITY_CAPTURE",
    "CHECK_CURRENT_PUBLICATION_GATES",
    "CHECK_PROVIDER_POLICY_AND_ROUTES",
    "CHECK_TASK_ATTEMPT_IDENTITY",
    "CURRENT_PUBLICATION_COMPOSITION_UNAVAILABLE",
    "CURRENT_PUBLICATION_CURRENT_POINTER_UNAVAILABLE",
    "CURRENT_PUBLICATION_PREVIEW_FAILED",
    "FullMarketPublicationPreflightPorts",
    "FullMarketPublicationPreflightReport",
    "PREFLIGHT_AUTHORITY_CAPTURE_UNAVAILABLE",
    "PREFLIGHT_MODEL_MARKET_ROUTES_UNAVAILABLE",
    "PREFLIGHT_PROVIDER_SETTINGS_BLOCKED",
    "PREFLIGHT_PUBLICATION_BUNDLE_UNAVAILABLE",
    "PREFLIGHT_PUBLICATION_POLICY_MISSING",
    "PREFLIGHT_PUBLICATION_POLICY_NOT_VERSIONED",
    "PREFLIGHT_PUBLICATION_POLICY_UNAVAILABLE",
    "PREFLIGHT_PUBLICATION_REBUILDERS_INCOMPLETE",
    "PREFLIGHT_PUBLICATION_UNIVERSE_UNAVAILABLE",
    "PREFLIGHT_REPORT_SCHEMA",
    "PREFLIGHT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE",
    "PreflightCheckOutcome",
    "RunFullMarketPublicationPreflightUseCase",
    "TaskAttemptIdentityProbeEvidence",
]

"""Build a full dynamic financial scope candidate from provider-native reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from apps.data_center.application.egress_service import FinancialResponseAttemptBudget
from apps.data_center.domain.financial_scope_discovery import (
    FINANCIAL_SCOPE_DISCOVERY_ERROR_CODES,
    FinancialScopeDiscoveryAsset,
    FinancialScopeDiscoveryAuthorization,
    FinancialScopeDiscoveryBinding,
    FinancialScopeDiscoveryCandidate,
    FinancialScopeDiscoveryCapture,
    FinancialScopeDiscoveryCounts,
    FinancialScopeDiscoveryError,
    FinancialScopeManifestReview,
    FinancialScopeReviewedManifest,
    build_asset_item,
    make_candidate,
)


class FinancialScopeDiscoveryReader(Protocol):
    """Capture two independent provider-native pages for one active security."""

    def preflight(self, *, binding: FinancialScopeDiscoveryBinding) -> None:
        """Validate frozen provider, contract, parser, and both persisted routes."""
        ...

    def capture_pair(
        self,
        *,
        binding: FinancialScopeDiscoveryBinding,
        asset_code: str,
        maximum_rows: int,
        attempt_budget: FinancialResponseAttemptBudget,
    ) -> tuple[FinancialScopeDiscoveryCapture, FinancialScopeDiscoveryCapture]:
        """Return exact raw, RawAudit-bound captures or a sanitized stable failure."""
        ...


class FinancialScopeDiscoveryAuthorizationSource(Protocol):
    """Read one persisted owner-authenticated authorization for the exact universe."""

    def get(
        self,
        *,
        binding: FinancialScopeDiscoveryBinding,
        asset_codes: tuple[str, ...],
        now: datetime,
    ) -> FinancialScopeDiscoveryAuthorization | None:
        """Return a verified, unrevoked owner event or ``None`` when not approved."""
        ...


class FinancialScopeManifestReviewSource(Protocol):
    """Read authenticated owner and independent-reviewer events for one candidate."""

    def get(
        self,
        *,
        candidate: FinancialScopeDiscoveryCandidate,
        now: datetime,
    ) -> tuple[FinancialScopeManifestReview, FinancialScopeManifestReview] | None:
        """Return the exact pair of distinct persisted review events, if complete."""
        ...


class FinancialScopeDiscoveryUniverseSource(Protocol):
    """Read the complete current active securities universe without side effects."""

    def get_active_asset_codes(self) -> tuple[str, ...]:
        """Return all active supported securities in canonical order."""
        ...


@dataclass(frozen=True, slots=True)
class ScopeDiscoveryRequest:
    """One isolated dynamic universe and its pre-egress owner authorization."""

    environment: Literal["isolated", "production"]
    asset_codes: tuple[str, ...]
    binding: FinancialScopeDiscoveryBinding
    now: datetime


@dataclass(frozen=True, slots=True)
class FinancialScopeDiscoveryResult:
    """Aggregate outcome containing a candidate only for complete verified coverage."""

    outcome: Literal["success", "blocked"]
    candidate: FinancialScopeDiscoveryCandidate | None
    counts: FinancialScopeDiscoveryCounts
    error_codes: tuple[str, ...]

    @property
    def requested_count(self) -> int:
        """Return the number of active securities in the supplied dynamic universe."""

        return self.counts.requested_assets

    @property
    def captured_count(self) -> int:
        """Return the number of assets with a complete consistent dual capture."""

        return self.counts.captured_assets

    @property
    def missing_count(self) -> int:
        """Return active assets absent from the complete candidate evidence."""

        return self.counts.missing_assets

    @property
    def failed_capture_count(self) -> int:
        """Return the number of active assets for which provider capture failed."""

        return self.counts.failed_capture_assets

    @property
    def observed_count(self) -> int:
        """Return the number of assets with a verified dual capture."""

        return self.counts.captured_assets

    @property
    def fact_write_count(self) -> int:
        """Return business fact writes, always zero for scope discovery."""

        return self.counts.fact_write_count

    @property
    def publication_write_count(self) -> int:
        """Return publication writes, always zero for scope discovery."""

        return self.counts.publication_write_count

    @property
    def duplicate_count(self) -> int:
        """Return duplicate universe codes or duplicate native response rows."""

        return self.counts.duplicate_assets

    @property
    def conflict_count(self) -> int:
        """Return assets whose two raw reads disagree on normalized provider rows."""

        return self.counts.conflicting_assets

    def to_dict(self) -> dict[str, object]:
        """Return safe counts and the exact pending manifest for independent review."""

        candidate_manifest: dict[str, object] | None = None
        if self.candidate is not None:
            candidate_manifest = self.candidate.payload()
            candidate_manifest["manifest_sha256"] = self.candidate.manifest_sha256

        return {
            "schema": "data-center.financial-scope-discovery-result.v1",
            "outcome": self.outcome,
            "error_codes": list(self.error_codes),
            "counts": {
                "requested": self.counts.requested_assets,
                "captured": self.counts.captured_assets,
                "failed_capture": self.counts.failed_capture_assets,
                "missing": self.counts.missing_assets,
                "duplicates": self.counts.duplicate_assets,
                "conflicts": self.counts.conflicting_assets,
                "logical_requests": self.counts.logical_request_count,
                "physical_attempts": self.counts.physical_request_attempts,
                "artifact_writes": self.counts.artifact_writes,
                "raw_audit_writes": self.counts.raw_audit_writes,
                "fact_writes": self.counts.fact_write_count,
                "publication_writes": self.counts.publication_write_count,
            },
            "candidate": (
                {
                    "manifest_sha256": self.candidate.manifest_sha256,
                    "universe_sha256": self.candidate.universe_sha256,
                    "coverage_count": self.candidate.coverage_count,
                    "review_status": "pending_independent_review",
                }
                if self.candidate is not None
                else None
            ),
            "candidate_manifest": candidate_manifest,
        }


class FinancialScopeDiscoveryUseCase:
    """Perform authorized isolated scope reads and freeze a review-required manifest."""

    def __init__(
        self,
        *,
        reader: FinancialScopeDiscoveryReader,
        authorization_source: FinancialScopeDiscoveryAuthorizationSource,
        universe_source: FinancialScopeDiscoveryUniverseSource,
    ) -> None:
        """Bind provider reads and persisted owner authorization through application ports."""

        self._reader = reader
        self._authorization_source = authorization_source
        self._universe_source = universe_source

    def execute(self, request: ScopeDiscoveryRequest) -> FinancialScopeDiscoveryResult:
        """Read every active asset once, aggregate all defects, and fail closed as a set."""

        assets = request.asset_codes if isinstance(request.asset_codes, tuple) else ()
        duplicate_assets = _duplicate_count(assets)
        unique_assets = tuple(sorted(set(assets))) if assets and duplicate_assets == 0 else ()
        if request.environment != "isolated":
            return self._blocked(
                requested=len(assets),
                duplicate_assets=duplicate_assets,
                error_codes=("FINANCIAL_SCOPE_DISCOVERY_ENVIRONMENT_FORBIDDEN",),
            )
        if not unique_assets or unique_assets != assets or not _valid_universe(assets):
            return self._blocked(
                requested=len(assets),
                duplicate_assets=duplicate_assets,
                error_codes=("FINANCIAL_SCOPE_DISCOVERY_UNIVERSE_INVALID",),
            )
        try:
            active_assets = self._universe_source.get_active_asset_codes()
        except Exception:
            return self._blocked(
                requested=len(assets),
                error_codes=("FINANCIAL_SCOPE_DISCOVERY_AUTHORITY_INVALID",),
            )
        if active_assets != assets:
            return self._blocked(
                requested=len(assets),
                error_codes=("FINANCIAL_SCOPE_DISCOVERY_UNIVERSE_DRIFT",),
            )
        try:
            authorization = self._authorization_source.get(
                binding=request.binding,
                asset_codes=assets,
                now=request.now,
            )
        except Exception:
            return self._blocked(
                requested=len(assets),
                error_codes=("FINANCIAL_SCOPE_DISCOVERY_AUTHORITY_INVALID",),
            )
        if authorization is None:
            return self._blocked(
                requested=len(assets),
                error_codes=("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_REQUIRED",),
            )
        try:
            authorization.validate(
                binding=request.binding,
                asset_codes=assets,
                now=request.now,
            )
        except FinancialScopeDiscoveryError as exc:
            return self._blocked(requested=len(assets), error_codes=(exc.code,))

        try:
            self._reader.preflight(binding=request.binding)
        except Exception as exc:
            return self._blocked(
                requested=len(assets),
                error_codes=(_safe_error_code(exc),),
            )

        attempt_budget = FinancialResponseAttemptBudget(authorization.maximum_physical_attempts)
        items: list[FinancialScopeDiscoveryAsset] = []
        error_codes: set[str] = set()
        failed_assets = 0
        duplicate_rows = 0
        conflicting_assets = 0
        duplicate_response_assets: set[str] = set()
        physical_attempts = 0
        artifact_writes = 0
        audit_writes = 0
        attempted_assets = 0
        for asset_code in assets:
            attempted_assets += 1
            try:
                pair = self._reader.capture_pair(
                    binding=request.binding,
                    asset_code=asset_code,
                    maximum_rows=authorization.maximum_rows_per_asset,
                    attempt_budget=attempt_budget,
                )
                if not isinstance(pair, tuple) or len(pair) != 2:
                    raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
                financial, source_time = pair
                if (
                    type(financial) is not FinancialScopeDiscoveryCapture
                    or type(source_time) is not FinancialScopeDiscoveryCapture
                ):
                    raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
                artifact_writes += 2
                audit_writes += 2
                if _capture_duplicate_rows(financial) or _capture_duplicate_rows(source_time):
                    duplicate_response_assets.add(asset_code)
                items.append(
                    build_asset_item(
                        binding=request.binding,
                        asset_code=asset_code,
                        financial=financial,
                        source_time=source_time,
                    )
                )
            except Exception as exc:
                failed_assets += 1
                code = _safe_error_code(exc)
                error_codes.add(code)
                if code == "FINANCIAL_SCOPE_DISCOVERY_CAPTURE_CONFLICT":
                    conflicting_assets += 1
                if code == "FINANCIAL_SCOPE_DISCOVERY_DUPLICATE_NATIVE_ROW":
                    duplicate_response_assets.add(asset_code)
                reported_attempts = getattr(exc, "physical_request_attempts", 0)
                if type(reported_attempts) is int and reported_attempts >= 0:
                    physical_attempts = max(physical_attempts, reported_attempts)
                reported_artifact_writes = getattr(exc, "artifact_writes", 0)
                if type(reported_artifact_writes) is int and reported_artifact_writes >= 0:
                    artifact_writes += reported_artifact_writes
                reported_audit_writes = getattr(exc, "audit_writes", 0)
                if type(reported_audit_writes) is int and reported_audit_writes >= 0:
                    audit_writes += reported_audit_writes

        physical_attempts = attempt_budget.reserved_attempts
        try:
            final_assets = self._universe_source.get_active_asset_codes()
        except Exception:
            final_assets = ()
            error_codes.add("FINANCIAL_SCOPE_DISCOVERY_AUTHORITY_INVALID")
        if final_assets != assets:
            error_codes.add("FINANCIAL_SCOPE_DISCOVERY_UNIVERSE_DRIFT")

        missing_assets = len(assets) - len(items)
        logical_requests = attempted_assets * 2
        if logical_requests > authorization.maximum_logical_requests:
            error_codes.add("FINANCIAL_SCOPE_DISCOVERY_BUDGET_EXCEEDED")
        if physical_attempts > authorization.maximum_physical_attempts:
            error_codes.add("FINANCIAL_SCOPE_DISCOVERY_BUDGET_EXCEEDED")
        duplicate_rows = len(duplicate_response_assets)
        if duplicate_rows:
            error_codes.add("FINANCIAL_SCOPE_DISCOVERY_DUPLICATE_NATIVE_ROW")
        if missing_assets:
            error_codes.add("FINANCIAL_SCOPE_DISCOVERY_COVERAGE_INCOMPLETE")

        counts = FinancialScopeDiscoveryCounts(
            requested_assets=len(assets),
            captured_assets=len(items),
            failed_capture_assets=failed_assets,
            missing_assets=missing_assets,
            duplicate_assets=duplicate_assets + duplicate_rows,
            conflicting_assets=conflicting_assets,
            logical_request_count=logical_requests,
            physical_request_attempts=physical_attempts,
            artifact_writes=artifact_writes,
            raw_audit_writes=audit_writes,
        )
        if error_codes or len(items) != len(assets):
            return FinancialScopeDiscoveryResult(
                outcome="blocked",
                candidate=None,
                counts=counts,
                error_codes=tuple(
                    sorted(error_codes or {"FINANCIAL_SCOPE_DISCOVERY_COVERAGE_INCOMPLETE"})
                ),
            )
        candidate = make_candidate(
            binding=request.binding,
            authorization=authorization,
            asset_codes=assets,
            items=tuple(items),
            generated_at=request.now,
        )
        return FinancialScopeDiscoveryResult(
            outcome="success",
            candidate=candidate,
            counts=counts,
            error_codes=(),
        )

    @staticmethod
    def _blocked(
        *,
        requested: int,
        error_codes: tuple[str, ...],
        duplicate_assets: int = 0,
    ) -> FinancialScopeDiscoveryResult:
        """Create one sanitized blocked result for pre-egress validation failures."""

        return FinancialScopeDiscoveryResult(
            outcome="blocked",
            candidate=None,
            counts=FinancialScopeDiscoveryCounts(
                requested_assets=requested,
                captured_assets=0,
                failed_capture_assets=0,
                missing_assets=requested,
                duplicate_assets=duplicate_assets,
                conflicting_assets=0,
                logical_request_count=0,
                physical_request_attempts=0,
                artifact_writes=0,
                raw_audit_writes=0,
            ),
            error_codes=tuple(sorted(set(error_codes))),
        )


def _duplicate_count(values: tuple[str, ...]) -> int:
    """Count repeated universe entries without losing the original requested size."""

    return len(values) - len(set(values))


def _valid_universe(values: tuple[str, ...]) -> bool:
    """Require exact canonical dynamic codes in sorted order."""

    return (
        bool(values)
        and all(
            type(value) is str
            and len(value) == 9
            and value[6:] in {".SH", ".SZ", ".BJ"}
            and value[:6].isascii()
            and value[:6].isdecimal()
            for value in values
        )
        and tuple(sorted(set(values))) == values
    )


def _capture_duplicate_rows(capture: FinancialScopeDiscoveryCapture) -> int:
    """Count duplicate composite provider row identities for aggregate rejection."""

    return len(capture.rows) - len({row.native_row_id for row in capture.rows})


def _safe_error_code(exc: BaseException) -> str:
    """Keep one stable allowlisted code and discard exception/provider messages."""

    code = getattr(exc, "code", "")
    if isinstance(code, str) and code in FINANCIAL_SCOPE_DISCOVERY_ERROR_CODES:
        return code
    return "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_CAPTURE_FAILED"


def independently_review_financial_scope_candidate(
    *,
    candidate: FinancialScopeDiscoveryCandidate,
    source: FinancialScopeManifestReviewSource,
    now: datetime,
) -> FinancialScopeReviewedManifest:
    """Return an approved manifest only from two exact authenticated review events."""

    try:
        reviews = source.get(candidate=candidate, now=now)
        if reviews is None or len(reviews) != 2:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_REVIEW_REQUIRED")
        owner, reviewer = reviews
        return candidate.approve(owner=owner, reviewer=reviewer, now=now)
    except FinancialScopeDiscoveryError:
        raise
    except Exception:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_REVIEW_REQUIRED") from None


__all__ = [
    "FinancialScopeDiscoveryAuthorizationSource",
    "FinancialScopeDiscoveryReader",
    "FinancialScopeDiscoveryResult",
    "FinancialScopeDiscoveryUseCase",
    "FinancialScopeManifestReviewSource",
    "FinancialScopeDiscoveryUniverseSource",
    "ScopeDiscoveryRequest",
    "independently_review_financial_scope_candidate",
]

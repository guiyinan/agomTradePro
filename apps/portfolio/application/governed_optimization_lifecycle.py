"""Contracts for the ID-only, server-clocked R8 result lifecycle boundary."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.domain._optimization_canonical import (
    require_aware,
    require_ordered_unique,
    require_token,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.optimization_lifecycle import (
    OptimizationLifecycleEventType,
    OptimizationLifecycleOwnerAttestation,
    OptimizationResearchLifecycleEvent,
    create_optimization_lifecycle_event,
)
from apps.portfolio.domain.optimization_research_result import (
    GovernedOptimizationResearchResult,
)


class GovernedOptimizationUnavailable(ValueError):
    """Authoritative R8 input or authorization evidence is unavailable."""


class GovernedOptimizationLifecycleConflict(ValueError):
    """Persisted R8 lifecycle identity or stream changed during an append."""


class ExactPromotionProvider(Protocol):
    """Research-owned Application port for exact active Promotion evidence."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction/lock identity used by this provider."""

    def get_exact(
        self,
        *,
        capability_key: str,
        decision_id: str,
        evaluated_at: datetime,
    ) -> ExactPromotionAttestation | None:
        """Return the exact Research decision, including retirement state."""


class GovernedOptimizationLifecycleRepository(Protocol):
    """Composition-private exact lifecycle transaction and persistence port."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the transaction identity shared with every owner provider."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared owner-read/result-read/lifecycle-write transaction."""

    def server_now(self) -> datetime:
        """Return the repository-owned timezone-aware server clock."""

    def get_result(
        self,
        result_id: str,
    ) -> GovernedOptimizationResearchResult | None:
        """Reconstruct one exact non-legacy result inside the active UoW."""

    def list_lifecycle_events(
        self,
        result_id: str,
    ) -> tuple[OptimizationResearchLifecycleEvent, ...]:
        """Reconstruct and verify the complete canonical stream."""

    def append_lifecycle_event(
        self,
        event: OptimizationResearchLifecycleEvent,
    ) -> OptimizationResearchLifecycleEvent:
        """Append an already-authorized exact lifecycle event."""


class ExactPortfolioLifecycleAuthorizationProvider(Protocol):
    """Portfolio-owned exact authorization lookup for terminal events."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction/lock identity used by this provider."""

    def get_exact(
        self,
        *,
        attestation_id: str,
        result_id: str,
        result_hash: str,
        event_type: OptimizationLifecycleEventType,
        evaluated_at: datetime,
    ) -> OptimizationLifecycleOwnerAttestation | None:
        """Return and lock one exact active authorization in the shared UoW."""


@dataclass(frozen=True)
class AppendGovernedOptimizationLifecycleEventCommand:
    """ID-only lifecycle request without caller-supplied evidence or clocks."""

    result_id: str
    event_type: OptimizationLifecycleEventType
    authorization_id: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require one governed transition and canonical lookup identities."""

        require_token(self.result_id, "lifecycle command result_id")
        if self.event_type not in {
            OptimizationLifecycleEventType.PROMOTION_ATTESTED,
            OptimizationLifecycleEventType.RETIRED,
            OptimizationLifecycleEventType.ROLLED_BACK,
        }:
            raise ValueError("lifecycle command only accepts governed transitions")
        require_token(self.authorization_id, "lifecycle command authorization_id")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("lifecycle command reason_codes must be a non-empty tuple")
        require_ordered_unique(self.reason_codes, "lifecycle command reason_codes")


class AppendGovernedOptimizationLifecycleEventUseCase:
    """Reread every owner and append one server-clocked lifecycle transition."""

    def __init__(
        self,
        *,
        promotion_provider: ExactPromotionProvider,
        owner_authorization_provider: ExactPortfolioLifecycleAuthorizationProvider,
        repository: GovernedOptimizationLifecycleRepository,
    ) -> None:
        try:
            expected_key = repository.unit_of_work_key
            promotion_key = promotion_provider.unit_of_work_key
            owner_key = owner_authorization_provider.unit_of_work_key
        except Exception as exc:
            raise GovernedOptimizationUnavailable(
                "R8 lifecycle owner unit of work is unavailable"
            ) from exc
        if (
            type(expected_key) is not str
            or not expected_key
            or promotion_key != expected_key
            or owner_key != expected_key
        ):
            raise GovernedOptimizationUnavailable("R8 lifecycle owners must share one unit of work")
        self._promotion_provider = promotion_provider
        self._owner_authorization_provider = owner_authorization_provider
        self._repository = repository

    def execute(
        self,
        command: AppendGovernedOptimizationLifecycleEventCommand,
    ) -> OptimizationResearchLifecycleEvent:
        """Resolve IDs under one UoW and never trust caller evidence or time."""

        self._validate_command(command)
        self._require_shared_unit_of_work()
        try:
            with self._repository.atomic():
                return self._execute_inside_unit_of_work(command)
        except (GovernedOptimizationUnavailable, GovernedOptimizationLifecycleConflict):
            raise
        except Exception as exc:
            raise GovernedOptimizationLifecycleConflict(
                "governed optimization lifecycle repository is unavailable"
            ) from exc

    def _execute_inside_unit_of_work(
        self,
        command: AppendGovernedOptimizationLifecycleEventCommand,
    ) -> OptimizationResearchLifecycleEvent:
        recorded_at = self._server_now()
        result = self._repository.get_result(command.result_id)
        if result is None:
            raise GovernedOptimizationUnavailable(
                "exact governed optimization result is unavailable"
            )
        if result.evaluated_at > recorded_at:
            raise GovernedOptimizationUnavailable(
                "future governed optimization result is unavailable"
            )
        try:
            previous_events = self._repository.list_lifecycle_events(command.result_id)
        except ValueError as exc:
            raise GovernedOptimizationLifecycleConflict(
                "governed optimization lifecycle stream is invalid"
            ) from exc
        if not previous_events:
            raise GovernedOptimizationUnavailable(
                "canonical governed optimization lifecycle stream is unavailable"
            )
        promotion_attestation: ExactPromotionAttestation | None = None
        owner_attestation: OptimizationLifecycleOwnerAttestation | None = None
        if command.event_type is OptimizationLifecycleEventType.PROMOTION_ATTESTED:
            if recorded_at >= result.valid_until:
                raise GovernedOptimizationUnavailable(
                    "expired governed optimization result cannot be promoted"
                )
            promotion_attestation = self._get_exact_promotion(command, recorded_at)
        else:
            owner_attestation = self._get_exact_owner(command, result, recorded_at)
        try:
            event = create_optimization_lifecycle_event(
                result=result,
                previous_events=previous_events,
                event_type=command.event_type,
                occurred_at=recorded_at,
                recorded_at=recorded_at,
                reason_codes=command.reason_codes,
                promotion_attestation=promotion_attestation,
                owner_attestation=owner_attestation,
            )
        except ValueError as exc:
            raise GovernedOptimizationLifecycleConflict(
                "governed optimization lifecycle transition is invalid"
            ) from exc
        self._require_shared_unit_of_work()
        self._revalidate_authorization(
            command=command,
            result=result,
            recorded_at=recorded_at,
            promotion_attestation=promotion_attestation,
            owner_attestation=owner_attestation,
        )
        self._require_shared_unit_of_work()
        try:
            latest_result = self._repository.get_result(command.result_id)
            latest_events = self._repository.list_lifecycle_events(command.result_id)
            if latest_result != result or latest_events != previous_events:
                raise GovernedOptimizationLifecycleConflict(
                    "governed optimization lifecycle changed before append"
                )
            OptimizationResearchLifecycleEvent.__post_init__(event)
            self._require_shared_unit_of_work()
            return self._repository.append_lifecycle_event(event)
        except GovernedOptimizationLifecycleConflict:
            raise
        except ValueError as exc:
            raise GovernedOptimizationLifecycleConflict(
                "governed optimization lifecycle append conflicted"
            ) from exc

    def _server_now(self) -> datetime:
        try:
            recorded_at = self._repository.server_now()
            require_aware(recorded_at, "R8 lifecycle server clock")
        except Exception as exc:
            raise GovernedOptimizationUnavailable(
                "R8 lifecycle server clock is unavailable"
            ) from exc
        return recorded_at

    @staticmethod
    def _validate_command(command: AppendGovernedOptimizationLifecycleEventCommand) -> None:
        if type(command) is not AppendGovernedOptimizationLifecycleEventCommand:
            raise GovernedOptimizationUnavailable("R8 lifecycle command is invalid")
        try:
            AppendGovernedOptimizationLifecycleEventCommand.__post_init__(command)
        except (TypeError, ValueError) as exc:
            raise GovernedOptimizationUnavailable("R8 lifecycle command is invalid") from exc

    def _require_shared_unit_of_work(self) -> None:
        try:
            expected_key = self._repository.unit_of_work_key
            promotion_key = self._promotion_provider.unit_of_work_key
            owner_key = self._owner_authorization_provider.unit_of_work_key
        except Exception as exc:
            raise GovernedOptimizationUnavailable(
                "R8 lifecycle owner unit of work is unavailable"
            ) from exc
        if promotion_key != expected_key or owner_key != expected_key:
            raise GovernedOptimizationUnavailable(
                "R8 lifecycle owners no longer share one unit of work"
            )

    def _get_exact_promotion(
        self,
        command: AppendGovernedOptimizationLifecycleEventCommand,
        recorded_at: datetime,
    ) -> ExactPromotionAttestation:
        try:
            trusted = self._promotion_provider.get_exact(
                capability_key="r8",
                decision_id=command.authorization_id,
                evaluated_at=recorded_at,
            )
        except Exception as exc:
            raise GovernedOptimizationUnavailable(
                "Research Promotion authorization is unavailable"
            ) from exc
        if trusted is None:
            raise GovernedOptimizationUnavailable("Research Promotion authorization is unavailable")
        if type(trusted) is not ExactPromotionAttestation:
            raise GovernedOptimizationUnavailable("Research Promotion authorization is invalid")
        try:
            ExactPromotionAttestation.__post_init__(trusted)
        except (AttributeError, TypeError, ValueError) as exc:
            raise GovernedOptimizationUnavailable(
                "Research Promotion authorization is invalid"
            ) from exc
        if trusted.decision_id != command.authorization_id:
            raise GovernedOptimizationUnavailable(
                "Research Promotion authorization does not match selector"
            )
        return trusted

    def _get_exact_owner(
        self,
        command: AppendGovernedOptimizationLifecycleEventCommand,
        result: GovernedOptimizationResearchResult,
        recorded_at: datetime,
    ) -> OptimizationLifecycleOwnerAttestation:
        try:
            trusted = self._owner_authorization_provider.get_exact(
                attestation_id=command.authorization_id,
                result_id=result.result_id,
                result_hash=result.content_hash,
                event_type=command.event_type,
                evaluated_at=recorded_at,
            )
        except Exception as exc:
            raise GovernedOptimizationUnavailable(
                "Portfolio lifecycle authorization is unavailable"
            ) from exc
        if trusted is None:
            raise GovernedOptimizationUnavailable(
                "Portfolio lifecycle authorization is unavailable"
            )
        if type(trusted) is not OptimizationLifecycleOwnerAttestation:
            raise GovernedOptimizationUnavailable("Portfolio lifecycle authorization is invalid")
        try:
            OptimizationLifecycleOwnerAttestation.__post_init__(trusted)
        except (AttributeError, TypeError, ValueError) as exc:
            raise GovernedOptimizationUnavailable(
                "Portfolio lifecycle authorization is invalid"
            ) from exc
        if trusted.attestation_id != command.authorization_id:
            raise GovernedOptimizationUnavailable(
                "Portfolio lifecycle authorization does not match selector"
            )
        if trusted.issued_at > recorded_at:
            raise GovernedOptimizationUnavailable(
                "future Portfolio lifecycle authorization is unavailable"
            )
        return trusted

    def _revalidate_authorization(
        self,
        *,
        command: AppendGovernedOptimizationLifecycleEventCommand,
        result: GovernedOptimizationResearchResult,
        recorded_at: datetime,
        promotion_attestation: ExactPromotionAttestation | None,
        owner_attestation: OptimizationLifecycleOwnerAttestation | None,
    ) -> None:
        if promotion_attestation is not None:
            latest: ExactPromotionAttestation | OptimizationLifecycleOwnerAttestation = (
                self._get_exact_promotion(command, recorded_at)
            )
            expected: ExactPromotionAttestation | OptimizationLifecycleOwnerAttestation = (
                promotion_attestation
            )
        else:
            latest = self._get_exact_owner(command, result, recorded_at)
            if owner_attestation is None:
                raise GovernedOptimizationLifecycleConflict(
                    "terminal lifecycle authorization was not reconstructed"
                )
            expected = owner_attestation
        if latest != expected:
            raise GovernedOptimizationUnavailable(
                "R8 lifecycle authorization changed before append"
            )


__all__ = [
    "AppendGovernedOptimizationLifecycleEventCommand",
    "AppendGovernedOptimizationLifecycleEventUseCase",
    "ExactPortfolioLifecycleAuthorizationProvider",
    "ExactPromotionProvider",
    "GovernedOptimizationLifecycleConflict",
    "GovernedOptimizationLifecycleRepository",
    "GovernedOptimizationUnavailable",
]

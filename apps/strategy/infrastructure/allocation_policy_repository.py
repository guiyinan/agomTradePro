"""Django persistence adapter for versioned Strategy allocation policies."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Max, Prefetch, QuerySet
from django.utils import timezone

from apps.strategy.domain.allocation_matrix import (
    AllocationPolicyConfigurationError,
    AllocationPolicyDraft,
    AllocationPolicyEntry,
    AllocationPolicySourceType,
    AllocationPolicyStatus,
    AllocationPolicyVersion,
    AllocationStatisticsStatus,
    AllocationTarget,
    AssetAllocation,
    PolicyAllocationAdjustment,
    PolicyLevel,
    RegimeType,
    RiskProfile,
    calculate_allocation_policy_content_hash,
)
from apps.strategy.infrastructure.models import (
    AllocationPolicyAdjustmentModel,
    AllocationPolicyEntryModel,
    AllocationPolicyVersionModel,
)


class DjangoAllocationPolicyRepository:
    """Persist append-only allocation-policy versions with atomic activation."""

    def get_active(self, policy_key: str) -> AllocationPolicyVersion | None:
        """Return the sole active policy version, validating its content hash."""

        model = (
            self._version_queryset()
            .filter(
                policy_key=policy_key,
                status=AllocationPolicyVersionModel.Status.ACTIVE,
            )
            .first()
        )
        return None if model is None else self._to_domain(model)

    def get_version(
        self,
        policy_key: str,
        version: int,
    ) -> AllocationPolicyVersion | None:
        """Return one immutable policy version by identity."""

        model = (
            self._version_queryset()
            .filter(
                policy_key=policy_key,
                version=version,
            )
            .first()
        )
        return None if model is None else self._to_domain(model)

    def list_versions(self, policy_key: str) -> list[AllocationPolicyVersion]:
        """List all versions from newest to oldest."""

        return [
            self._to_domain(model)
            for model in self._version_queryset().filter(policy_key=policy_key).order_by("-version")
        ]

    def create_version(self, draft: AllocationPolicyDraft) -> AllocationPolicyVersion:
        """Create the next draft version without changing the active pointer."""

        content_hash = calculate_allocation_policy_content_hash(
            draft.entries,
            draft.adjustments,
        )
        try:
            with transaction.atomic():
                locked_versions = (
                    AllocationPolicyVersionModel._default_manager.select_for_update().filter(
                        policy_key=draft.policy_key
                    )
                )
                max_version = locked_versions.aggregate(value=Max("version"))["value"] or 0
                model = AllocationPolicyVersionModel._default_manager.create(
                    policy_key=draft.policy_key,
                    version=int(max_version) + 1,
                    status=AllocationPolicyVersionModel.Status.DRAFT,
                    content_hash=content_hash,
                    source_type=draft.source_type.value,
                    change_reason=draft.change_reason,
                    based_on_version=draft.based_on_version,
                    created_by_id=draft.created_by_id,
                )
                AllocationPolicyEntryModel._default_manager.bulk_create(
                    [self._entry_model(model, entry) for entry in draft.entries]
                )
                AllocationPolicyAdjustmentModel._default_manager.bulk_create(
                    [self._adjustment_model(model, item) for item in draft.adjustments]
                )
        except IntegrityError as exc:
            raise AllocationPolicyConfigurationError(
                "allocation policy version could not be created because its identity conflicts"
            ) from exc

        created = self.get_version(draft.policy_key, model.version)
        if created is None:
            raise AllocationPolicyConfigurationError(
                "created allocation policy version is unreadable"
            )
        return created

    def activate_version(
        self,
        policy_key: str,
        version: int,
        *,
        activated_by_id: int | None,
        effective_at: datetime | None = None,
    ) -> AllocationPolicyVersion:
        """Atomically make a complete draft the only active version."""

        activation_time = effective_at or timezone.now()
        if not timezone.is_aware(activation_time):
            raise ValueError("effective_at must be timezone-aware")

        with transaction.atomic():
            locked = list(
                AllocationPolicyVersionModel._default_manager.select_for_update()
                .filter(policy_key=policy_key)
                .order_by("version")
            )
            target_model = next((item for item in locked if item.version == version), None)
            if target_model is None:
                raise AllocationPolicyConfigurationError(
                    f"allocation policy {policy_key} v{version} does not exist"
                )
            if target_model.status == AllocationPolicyVersionModel.Status.ACTIVE:
                active = self.get_active(policy_key)
                if active is None:
                    raise AllocationPolicyConfigurationError(
                        "active allocation policy could not be read"
                    )
                return active
            if target_model.status != AllocationPolicyVersionModel.Status.DRAFT:
                raise AllocationPolicyConfigurationError(
                    "superseded policy content must be copied into a new rollback version"
                )

            target = self.get_version(policy_key, version)
            if target is None:
                raise AllocationPolicyConfigurationError("allocation policy draft is unreadable")
            target.validate_for_activation()

            AllocationPolicyVersionModel._default_manager.filter(
                policy_key=policy_key,
                status=AllocationPolicyVersionModel.Status.ACTIVE,
            ).exclude(pk=target_model.pk).update(
                status=AllocationPolicyVersionModel.Status.SUPERSEDED
            )
            updated = AllocationPolicyVersionModel._default_manager.filter(
                pk=target_model.pk,
                status=AllocationPolicyVersionModel.Status.DRAFT,
            ).update(
                status=AllocationPolicyVersionModel.Status.ACTIVE,
                effective_at=activation_time,
                activated_at=timezone.now(),
                activated_by_id=activated_by_id,
            )
            if updated != 1:
                raise AllocationPolicyConfigurationError(
                    "allocation policy activation lost an optimistic state race"
                )

        active = self.get_active(policy_key)
        if active is None or active.version != version:
            raise AllocationPolicyConfigurationError("allocation policy activation did not persist")
        return active

    def rollback_to_version(
        self,
        policy_key: str,
        version: int,
        *,
        change_reason: str,
        actor_id: int | None,
        effective_at: datetime | None = None,
    ) -> AllocationPolicyVersion:
        """Copy an old revision into a new version and activate the copy."""

        if not change_reason.strip():
            raise ValueError("change_reason is required")
        with transaction.atomic():
            target_model = (
                AllocationPolicyVersionModel._default_manager.select_for_update()
                .filter(policy_key=policy_key, version=version)
                .first()
            )
            if target_model is None:
                raise AllocationPolicyConfigurationError(
                    f"allocation policy {policy_key} v{version} does not exist"
                )
            target = self.get_version(policy_key, version)
            if target is None:
                raise AllocationPolicyConfigurationError("rollback source is unreadable")
            target.validate_for_activation()
            copy = self.create_version(
                target.as_draft(
                    source_type=AllocationPolicySourceType.ROLLBACK,
                    change_reason=change_reason,
                    created_by_id=actor_id,
                )
            )
            return self.activate_version(
                policy_key,
                copy.version,
                activated_by_id=actor_id,
                effective_at=effective_at,
            )

    @staticmethod
    def _version_queryset() -> QuerySet[AllocationPolicyVersionModel]:
        """Return the fully prefetched policy queryset."""

        return AllocationPolicyVersionModel._default_manager.prefetch_related(
            Prefetch(
                "entries",
                queryset=AllocationPolicyEntryModel._default_manager.order_by(
                    "regime", "risk_profile"
                ),
            ),
            Prefetch(
                "adjustments",
                queryset=AllocationPolicyAdjustmentModel._default_manager.order_by("policy_level"),
            ),
        )

    @staticmethod
    def _to_domain(model: AllocationPolicyVersionModel) -> AllocationPolicyVersion:
        """Narrow ORM rows into immutable domain values."""

        entries = tuple(
            AllocationPolicyEntry(
                regime=RegimeType(entry.regime),
                risk_profile=RiskProfile(entry.risk_profile),
                target=AllocationTarget(
                    allocation=AssetAllocation(
                        equity=float(entry.equity),
                        fixed_income=float(entry.fixed_income),
                        commodity=float(entry.commodity),
                        cash=float(entry.cash),
                    ),
                    reasoning=entry.reasoning,
                    expected_return=_optional_float(entry.expected_return),
                    expected_volatility=_optional_float(entry.expected_volatility),
                    sharpe_ratio=_optional_float(entry.sharpe_ratio),
                    statistics_status=AllocationStatisticsStatus(entry.statistics_status),
                    research_evidence_id=entry.research_evidence_id,
                ),
            )
            for entry in model.entries.all()
        )
        adjustments = tuple(
            PolicyAllocationAdjustment(
                policy_level=PolicyLevel(adjustment.policy_level),
                equity_multiplier=float(adjustment.equity_multiplier),
                expected_return_multiplier=float(adjustment.expected_return_multiplier),
                expected_volatility_multiplier=float(adjustment.expected_volatility_multiplier),
                sharpe_multiplier=float(adjustment.sharpe_multiplier),
            )
            for adjustment in model.adjustments.all()
        )
        return AllocationPolicyVersion(
            policy_key=model.policy_key,
            version=model.version,
            status=AllocationPolicyStatus(model.status),
            entries=entries,
            adjustments=adjustments,
            content_hash=model.content_hash,
            source_type=AllocationPolicySourceType(model.source_type),
            change_reason=model.change_reason,
            created_at=model.created_at,
            effective_at=model.effective_at,
            based_on_version=model.based_on_version,
            created_by_id=model.created_by_id,
        )

    @staticmethod
    def _entry_model(
        version: AllocationPolicyVersionModel,
        entry: AllocationPolicyEntry,
    ) -> AllocationPolicyEntryModel:
        """Build an unsaved ORM entry from a domain matrix cell."""

        target = entry.target
        return AllocationPolicyEntryModel(
            policy_version=version,
            regime=entry.regime.value,
            risk_profile=entry.risk_profile.value,
            equity=Decimal(str(target.allocation.equity)),
            fixed_income=Decimal(str(target.allocation.fixed_income)),
            commodity=Decimal(str(target.allocation.commodity)),
            cash=Decimal(str(target.allocation.cash)),
            reasoning=target.reasoning,
            expected_return=_optional_decimal(target.expected_return),
            expected_volatility=_optional_decimal(target.expected_volatility),
            sharpe_ratio=_optional_decimal(target.sharpe_ratio),
            statistics_status=target.statistics_status.value,
            research_evidence_id=target.research_evidence_id,
        )

    @staticmethod
    def _adjustment_model(
        version: AllocationPolicyVersionModel,
        adjustment: PolicyAllocationAdjustment,
    ) -> AllocationPolicyAdjustmentModel:
        """Build an unsaved ORM adjustment from a domain value."""

        return AllocationPolicyAdjustmentModel(
            policy_version=version,
            policy_level=adjustment.policy_level.value,
            equity_multiplier=Decimal(str(adjustment.equity_multiplier)),
            expected_return_multiplier=Decimal(str(adjustment.expected_return_multiplier)),
            expected_volatility_multiplier=Decimal(str(adjustment.expected_volatility_multiplier)),
            sharpe_multiplier=Decimal(str(adjustment.sharpe_multiplier)),
        )


def _optional_float(value: Decimal | None) -> float | None:
    """Convert an optional Decimal from the ORM boundary."""

    return None if value is None else float(value)


def _optional_decimal(value: float | None) -> Decimal | None:
    """Convert an optional float into an exact decimal representation."""

    return None if value is None else Decimal(str(value))

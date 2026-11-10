"""Compose canonical plan readers and constraints with existing account grants."""

from __future__ import annotations

from datetime import datetime

from django.db import DEFAULT_DB_ALIAS, DatabaseError
from django.utils import timezone

from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar_reference,
)
from apps.data_center.calendar_workbench_scope_composition import (
    read_calendar_capture_configuration_reference_at,
)
from apps.portfolio.application.transition_plan_event_review import (
    TransitionPlanEventReviewValidator,
)
from apps.portfolio.application.transition_plan_lifecycle import (
    GetExactTransitionPlanRevisionUseCase,
    TransitionPlanCurrentPolicyPinsValidator,
)
from apps.portfolio.domain.transition_plan_event_review import TransitionPlanEventReviewAssessment
from apps.portfolio.domain.transition_plan_revision import TransitionPlanRevision
from apps.portfolio.infrastructure.transition_plan_revision_repository import (
    DjangoTransitionPlanLockedActionGuard,
    DjangoTransitionPlanRevisionRepository,
)
from apps.risk_center.application.portfolio_risk_runtime import get_portfolio_risk_runtime
from apps.risk_center.execution_settlement_composition import (
    build_execution_settlement_v3_rule_reader,
)
from apps.simulated_trading.application.portfolio_risk_calendar import (
    build_portfolio_risk_calendar_reader,
)
from apps.simulated_trading.application.rebalance_journey_authorization import (
    RebalanceJourneyAccountAuthorizer,
)
from apps.simulated_trading.application.rebalance_journey_current_pins import (
    JourneyCurrentPolicyPinsValidator,
)
from apps.simulated_trading.application.rebalance_journey_order_adapters import (
    JourneyPlanOrderPreviewer as JourneyPlanOrderPreviewAdapter,
)
from apps.simulated_trading.application.rebalance_journey_order_adapters import (
    JourneyPlanProgressReader as JourneyPlanProgressAdapter,
)
from apps.simulated_trading.application.rebalance_journey_preparation import (
    PortfolioJourneyPreparationProvider,
)
from apps.simulated_trading.application.rebalance_journey_public import (
    RebalanceJourneyCommand,
    RebalanceJourneyUnavailable,
)
from apps.simulated_trading.application.rebalance_journey_readers import ServerRebalanceJourneyReads
from apps.simulated_trading.application.rebalance_journey_service import (
    RebalanceJourneyApplication,
    ReferenceBasis,
    retained_plan_reference_price_basis,
)
from apps.simulated_trading.application.transition_plan_execution import (
    PreviewTransitionPlanOrderUseCase,
)
from apps.simulated_trading.application.transition_plan_execution_progress import (
    GetTransitionPlanExecutionProgressUseCase,
)
from apps.simulated_trading.composition import build_observer_grant_repository
from apps.simulated_trading.execution_current_reference_composition import (
    build_configured_execution_calendar_reader,
    build_current_reference_classification_reader,
    build_current_reference_identity_reader,
    get_simulated_execution_runtime_environment,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.portfolio_risk_resource_repository import (
    DjangoPortfolioRiskResourceRepository,
)
from apps.simulated_trading.infrastructure.rebalance_resource_snapshot_repository import (
    DjangoRebalanceResourceSnapshotRepository,
)
from apps.simulated_trading.infrastructure.transition_plan_execution_history_repository import (
    DjangoTransitionPlanExecutionHistoryRepository,
)
from apps.simulated_trading.rebalance_plan_preview_composition import (
    build_readonly_rebalance_plan_preview_builder,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    DISCLOSURE_COVERAGE_POLICY_KEY,
)
from apps.simulated_trading.transition_plan_event_coverage_composition import (
    build_configured_rebalance_journey_event_coverage_pinner,
)
from apps.simulated_trading.transition_plan_event_review_composition import (
    build_configured_transition_plan_event_review_validator,
)
from apps.simulated_trading.transition_plan_official_disclosure_source import (
    build_official_szse_distribution_refresher,
)
from core.exceptions import AgomTradeProException
from core.integration.config_center_runtime import get_active_runtime_value


def build_transition_plan_exact_reader(
    *, using: str = DEFAULT_DB_ALIAS
) -> GetExactTransitionPlanRevisionUseCase:
    """Reuse actual owner/delegated-read grants without querying rows at construction."""

    repository = DjangoTransitionPlanRevisionRepository(using=using)
    resources = DjangoPortfolioRiskResourceRepository(
        using=using, observer_grant_repository=build_observer_grant_repository(using=using)
    )
    return GetExactTransitionPlanRevisionUseCase(
        repository=repository,
        authorizer=RebalanceJourneyAccountAuthorizer(resources),
        clock=repository,
    )


def build_transition_plan_locked_guard(
    *,
    current_policy_pins_validator: TransitionPlanCurrentPolicyPinsValidator,
    event_review_validator: TransitionPlanEventReviewValidator | None = None,
    using: str = DEFAULT_DB_ALIAS,
) -> DjangoTransitionPlanLockedActionGuard:
    """Require an explicit current-policy reader in addition to ordinary order guards."""

    return DjangoTransitionPlanLockedActionGuard(
        using=using,
        current_policy_pins_validator=current_policy_pins_validator,
        event_review_validator=event_review_validator,
    )


class _LazyCurrentPolicyPinsValidator:
    """Build current read ports only when a bound order actually needs validation."""

    def __init__(self, *, using: str) -> None:
        self._using = using

    def validate_current_policy_pins(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> None:
        """Keep unbound legacy submissions independent of the new plan service."""

        validator = build_journey_current_policy_pins_validator(using=self._using)
        validator.validate_current_policy_pins(revision, as_of=as_of)


class _LazyConfiguredEventReviewValidator:
    """Build read-only event ports only when an event-bound plan needs assessment."""

    def __init__(self, *, using: str) -> None:
        self._using = using

    def assess(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> TransitionPlanEventReviewAssessment:
        """Use the same current Config Center and Data Center gate for review and holds."""

        environment = get_simulated_execution_runtime_environment()
        validator = build_configured_transition_plan_event_review_validator(
            runtime_environment=environment,
            using=self._using,
        )
        return validator.assess(revision, as_of=as_of)


def build_configured_transition_plan_guard(
    *, using: str = DEFAULT_DB_ALIAS
) -> DjangoTransitionPlanLockedActionGuard:
    """Supply the same lazy plan constraints to preview and ordinary confirmation."""

    return build_transition_plan_locked_guard(
        using=using,
        current_policy_pins_validator=_LazyCurrentPolicyPinsValidator(using=using),
        event_review_validator=_LazyConfiguredEventReviewValidator(using=using),
    )


def build_journey_current_policy_pins_validator(
    *, using: str = DEFAULT_DB_ALIAS
) -> JourneyCurrentPolicyPinsValidator:
    """Compose only existing database and retained-reference readers for the lock."""

    if using != DEFAULT_DB_ALIAS:
        raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_DATABASE_ALIAS_UNSUPPORTED")
    environment = get_simulated_execution_runtime_environment()
    runtime = get_portfolio_risk_runtime(using=using, environment=environment)
    identities = build_current_reference_identity_reader(runtime_environment=environment)
    calendars = build_configured_execution_calendar_reader(
        runtime_environment=environment,
        read_publication=read_current_exchange_calendar_reference,
        read_configuration=read_calendar_capture_configuration_reference_at,
    )
    return JourneyCurrentPolicyPinsValidator(
        risk_policy_reader=runtime.policy_reader,
        baseline_reader=runtime.baseline_reader,
        resource_reader=DjangoPortfolioRiskResourceRepository(
            using=using, observer_grant_repository=build_observer_grant_repository(using=using)
        ),
        classification_reader=build_current_reference_classification_reader(
            runtime_environment=environment
        ),
        calendar_reader=build_portfolio_risk_calendar_reader(
            identity_reader=identities, calendar_reader=calendars
        ),
        fee_reader=DjangoFeePolicyV2Repository(using=using),
        rule_reader=build_execution_settlement_v3_rule_reader(),
        business_timezone=timezone.get_default_timezone(),
    )


class _PurposeBoundPlanOrderPreviewer:
    """Retain the actual plan lane when constructing the ordinary signed preview."""

    def __init__(self, *, using: str) -> None:
        self._using = using

    def preview(
        self, *, command: RebalanceJourneyCommand, revision: TransitionPlanRevision
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Select the producer from immutable context, never from a client purpose hint."""

        from apps.simulated_trading.owner_order_submission_composition import (
            build_owner_order_submission_use_case,
        )

        lane = retained_plan_reference_price_basis(revision)
        purpose = (
            "close_snapshot_simulation" if lane == "published_close" else "local_simulation_only"
        )
        repository = DjangoTransitionPlanRevisionRepository(using=self._using)
        use_case = PreviewTransitionPlanOrderUseCase(
            revision_reader=build_transition_plan_exact_reader(using=self._using),
            order_submission=build_owner_order_submission_use_case(
                market_purpose=purpose,
                transition_plan_guard=build_configured_transition_plan_guard(using=self._using),
            ),
            clock=repository,
        )
        return JourneyPlanOrderPreviewAdapter(use_case).preview(command=command, revision=revision)


def build_rebalance_journey_service(using: str = DEFAULT_DB_ALIAS) -> RebalanceJourneyApplication:
    """Register a lazy owned simulation journey without querying at application startup."""

    if using != DEFAULT_DB_ALIAS:
        raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_DATABASE_ALIAS_UNSUPPORTED")
    event_review_validator = _LazyConfiguredEventReviewValidator(using=using)
    repository = DjangoTransitionPlanRevisionRepository(
        using=using, event_review_validator=event_review_validator
    )
    resources = DjangoPortfolioRiskResourceRepository(
        using=using, observer_grant_repository=build_observer_grant_repository(using=using)
    )
    reads = ServerRebalanceJourneyReads(
        preview_builder_factory=build_readonly_rebalance_plan_preview_builder,
        fee_reader=DjangoFeePolicyV2Repository(using=using),
        quantity_rule_reader=build_execution_settlement_v3_rule_reader(),
        using=using,
    )

    def prepare(
        *, target_weights: str, reference_price_basis: ReferenceBasis
    ) -> PortfolioJourneyPreparationProvider:
        """Capture one true preview/risk pair for each explicit create or successor."""

        environment = get_simulated_execution_runtime_environment()
        event_required = _official_event_gate_enabled(
            runtime_environment=environment,
            as_of=repository.now(),
        )
        return PortfolioJourneyPreparationProvider(
            reads,
            target_weights=target_weights,
            reference_price_basis=reference_price_basis,
            business_timezone=timezone.get_default_timezone(),
            clock=repository,
            event_coverage_pinner=(
                build_configured_rebalance_journey_event_coverage_pinner(
                    runtime_environment=environment, using=using
                )
                if event_required
                else None
            ),
            event_refresher=(
                build_official_szse_distribution_refresher(
                    runtime_environment=environment, using=using
                )
                if event_required
                else None
            ),
            event_coverage_required=event_required,
        )

    progress = GetTransitionPlanExecutionProgressUseCase(
        revision_reader=build_transition_plan_exact_reader(using=using),
        family_head_reader=repository,
        history_reader=DjangoTransitionPlanExecutionHistoryRepository(using=using),
        resource_reader=DjangoRebalanceResourceSnapshotRepository(using=using),
        clock=repository,
    )
    return RebalanceJourneyApplication(
        repository=repository,
        authorizer=RebalanceJourneyAccountAuthorizer(resources),
        clock=repository,
        preparation_factory=prepare,
        progress_reader=JourneyPlanProgressAdapter(progress),
        order_previewer=_PurposeBoundPlanOrderPreviewer(using=using),
        event_review_validator=event_review_validator,
    )


def _official_event_gate_enabled(*, runtime_environment: str, as_of: datetime) -> bool:
    """Enable exact official capture only for an explicit active Config Center value."""

    try:
        value = get_active_runtime_value(
            environment=runtime_environment,
            definition_key=DISCLOSURE_COVERAGE_POLICY_KEY,
            as_of=as_of,
        )
    except (
        AgomTradeProException,
        ArithmeticError,
        AttributeError,
        DatabaseError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_POLICY_UNAVAILABLE") from error
    if value is None:
        return False
    if type(value) is not dict or type(value.get("enabled")) is not bool:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_POLICY_INVALID")
    return value["enabled"] is True

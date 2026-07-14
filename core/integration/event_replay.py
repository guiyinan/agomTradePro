"""Cross-application target composition for controlled event replay."""

from apps.events.application.replay_registry import ReplayTarget, ReplayTargetRegistry
from apps.events.domain.entities import EventHandler, EventType


def _decision_approved() -> EventHandler:
    from apps.events.application.decision_execution_handlers import DecisionApprovedHandler

    return DecisionApprovedHandler()


def _decision_rejected() -> EventHandler:
    from apps.events.application.decision_execution_handlers import DecisionRejectedHandler

    return DecisionRejectedHandler()


def _decision_executed() -> EventHandler:
    from apps.events.application.decision_execution_handlers import DecisionExecutedHandler

    return DecisionExecutedHandler()


def _decision_execution_failed() -> EventHandler:
    from apps.events.application.decision_execution_handlers import (
        DecisionExecutionFailedHandler,
    )

    return DecisionExecutionFailedHandler()


def _decision_rhythm_main() -> EventHandler:
    from apps.decision_rhythm.application.handlers import DecisionRhythmEventHandler

    return DecisionRhythmEventHandler()


def _decision_rhythm_quota() -> EventHandler:
    from apps.decision_rhythm.application.handlers import QuotaMonitorHandler
    from apps.decision_rhythm.domain.services import QuotaManager
    from apps.events.domain.services import get_event_bus

    return QuotaMonitorHandler(QuotaManager(), get_event_bus())


def _decision_rhythm_cooldown() -> EventHandler:
    from apps.decision_rhythm.application.handlers import CooldownEventHandler
    from apps.decision_rhythm.domain.services import CooldownManager
    from apps.events.domain.services import get_event_bus

    return CooldownEventHandler(CooldownManager(), get_event_bus())


def _alpha_trigger_main() -> EventHandler:
    from apps.alpha_trigger.application.handlers import AlphaTriggerEventHandler
    from apps.events.domain.services import get_event_bus

    return AlphaTriggerEventHandler(event_bus=get_event_bus())


def _alpha_trigger_invalidation() -> EventHandler:
    from apps.alpha_trigger.application.handlers import TriggerInvalidationHandler
    from apps.events.domain.services import get_event_bus

    return TriggerInvalidationHandler(None, get_event_bus())


def _alpha_trigger_promotion() -> EventHandler:
    from apps.alpha_trigger.application.handlers import CandidatePromotionHandler
    from apps.alpha_trigger.application.repository_provider import (
        get_alpha_candidate_repository,
    )
    from apps.events.domain.services import get_event_bus

    return CandidatePromotionHandler(get_alpha_candidate_repository(), get_event_bus())


def build_replay_target_registry() -> ReplayTargetRegistry:
    """Build the fixed initial registry of ten approved real handlers."""

    return ReplayTargetRegistry(
        [
            ReplayTarget(
                "events.decision.approved",
                (EventType.DECISION_APPROVED,),
                "Synchronize approved decision references to alpha candidates.",
                _decision_approved,
            ),
            ReplayTarget(
                "events.decision.rejected",
                (EventType.DECISION_REJECTED,),
                "Synchronize rejected decision state to alpha candidates.",
                _decision_rejected,
            ),
            ReplayTarget(
                "events.decision.executed",
                (EventType.DECISION_EXECUTED,),
                "Synchronize successful execution state to requests and candidates.",
                _decision_executed,
            ),
            ReplayTarget(
                "events.decision.execution_failed",
                (EventType.DECISION_EXECUTION_FAILED,),
                "Synchronize failed execution state to requests and candidates.",
                _decision_execution_failed,
            ),
            ReplayTarget(
                "decision_rhythm.main",
                (
                    EventType.DECISION_APPROVED,
                    EventType.DECISION_REJECTED,
                    EventType.ALPHA_TRIGGER_FIRED,
                ),
                "Reapply decision rhythm bookkeeping for decisions and alpha triggers.",
                _decision_rhythm_main,
            ),
            ReplayTarget(
                "decision_rhythm.quota",
                (EventType.DECISION_APPROVED,),
                "Re-evaluate decision quota warning side effects.",
                _decision_rhythm_quota,
            ),
            ReplayTarget(
                "decision_rhythm.cooldown",
                (EventType.DECISION_APPROVED, EventType.SIGNAL_TRIGGERED),
                "Re-evaluate cooldown side effects for decisions and signals.",
                _decision_rhythm_cooldown,
            ),
            ReplayTarget(
                "alpha_trigger.main",
                (
                    EventType.SIGNAL_CREATED,
                    EventType.SIGNAL_APPROVED,
                    EventType.REGIME_CHANGED,
                    EventType.POLICY_LEVEL_CHANGED,
                ),
                "Reapply alpha-trigger creation and environment reactions.",
                _alpha_trigger_main,
            ),
            ReplayTarget(
                "alpha_trigger.invalidation",
                (EventType.REGIME_CHANGED, EventType.POLICY_LEVEL_CHANGED),
                "Re-evaluate active trigger invalidation against environment changes.",
                _alpha_trigger_invalidation,
            ),
            ReplayTarget(
                "alpha_trigger.promotion",
                (EventType.ALPHA_TRIGGER_FIRED,),
                "Reapply candidate promotion from fired alpha triggers.",
                _alpha_trigger_promotion,
            ),
        ]
    )

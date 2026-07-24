"""Event, query, and template-filter contracts for Alpha Trigger."""

from __future__ import annotations

from types import SimpleNamespace

from apps.alpha_trigger.application import handlers, query_services
from apps.alpha_trigger.domain.entities import CandidateStatus
from apps.alpha_trigger.interface.templatetags.alpha_trigger_filters import pprint_json
from apps.events.domain.entities import EventType, create_event


class _Bus:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def test_alpha_trigger_event_handler_routes_all_supported_events() -> None:
    """Signal, regime, and policy events retain their distinct side effects."""
    requests: list[object] = []

    class _Creator:
        def execute(self, request: object):
            requests.append(request)
            return SimpleNamespace(
                success=True,
                trigger=SimpleNamespace(trigger_id="trigger-1"),
                error=None,
            )

    bus = _Bus()
    handler = handlers.AlphaTriggerEventHandler(_Creator(), bus)
    assert handler.can_handle(EventType.SIGNAL_CREATED)
    assert handler.can_handle(EventType.REGIME_CHANGED)
    assert handler.can_handle(EventType.POLICY_LEVEL_CHANGED)
    assert handler.can_handle(EventType.SIGNAL_APPROVED)
    assert not handler.can_handle(EventType.UNKNOWN)
    handler.handle(
        create_event(
            EventType.SIGNAL_CREATED,
            {
                "signal_id": 1,
                "asset_code": "000001.SZ",
                "asset_class": "equity",
                "direction": "LONG",
                "confidence": 0.9,
                "logic_desc": "momentum",
            },
        )
    )
    assert requests[0].asset_code == "000001.SZ"
    handler.handle(create_event(EventType.SIGNAL_CREATED, {}))
    handler.handle(create_event(EventType.SIGNAL_APPROVED, {"signal_id": 1}))
    handler.handle(
        create_event(
            EventType.REGIME_CHANGED,
            {"old_regime": "Stagflation", "new_regime": "Recovery"},
        )
    )
    handler.handle(
        create_event(
            EventType.POLICY_LEVEL_CHANGED,
            {"old_level": 1, "new_level": 2},
        )
    )
    assert [event.payload["reason"] for event in bus.events] == [
        "regime_changed",
        "policy_changed",
    ]
    assert handler.get_handler_id().endswith("AlphaTriggerEventHandler")

    no_creator = handlers.AlphaTriggerEventHandler()
    no_creator.handle(create_event(EventType.SIGNAL_CREATED, {"asset_code": "000001.SZ"}))


def test_invalidation_and_candidate_promotion_handlers_cover_strengths() -> None:
    """Candidate promotion maps every strength band and publishes only persisted updates."""
    bus = _Bus()
    invalidation = handlers.TriggerInvalidationHandler(object(), bus)
    assert invalidation.can_handle(EventType.REGIME_CHANGED)
    assert not invalidation.can_handle(EventType.SIGNAL_CREATED)
    invalidation.handle(create_event(EventType.REGIME_CHANGED, {"new_regime": "Recovery"}))
    assert invalidation.get_handler_id().endswith("TriggerInvalidationHandler")

    class _Repo:
        def __init__(self) -> None:
            self.statuses: list[CandidateStatus] = []

        def get_by_trigger_id(self, trigger_id: str):
            if trigger_id == "missing":
                return None
            return SimpleNamespace(
                candidate_id=f"candidate-{trigger_id}",
                asset_code="000001.SZ",
                status=CandidateStatus.WATCH,
            )

        def update_status(self, candidate_id: str, status: CandidateStatus):
            self.statuses.append(status)
            return SimpleNamespace(candidate_id=candidate_id, asset_code="000001.SZ")

    repo = _Repo()
    promotion = handlers.CandidatePromotionHandler(repo, bus)
    assert promotion.can_handle(EventType.ALPHA_TRIGGER_FIRED)
    for trigger_id, strength in [
        ("strong", "strong"),
        ("moderate", "moderate"),
        ("weak", "weak"),
        ("missing", "strong"),
    ]:
        promotion.handle(
            create_event(
                EventType.ALPHA_TRIGGER_FIRED,
                {
                    "trigger_id": trigger_id,
                    "asset_code": "000001.SZ",
                    "strength": strength,
                },
            )
        )
    assert repo.statuses == [
        CandidateStatus.ACTIONABLE,
        CandidateStatus.CANDIDATE,
        CandidateStatus.WATCH,
    ]
    assert promotion.get_handler_id().endswith("CandidatePromotionHandler")


def test_alpha_trigger_queries_and_json_filter(monkeypatch) -> None:
    """Cross-app query context deduplicates existing triggers and exposes availability."""
    triggers = [
        SimpleNamespace(trigger_id="t1"),
        SimpleNamespace(trigger_id="t2"),
    ]
    trigger_repo = SimpleNamespace(
        list_models_by_statuses=lambda statuses, limit: triggers,
        get_active=lambda: triggers,
    )
    candidate_repo = SimpleNamespace(
        list_models_by_statuses=lambda statuses, limit: [
            SimpleNamespace(trigger_id="t1"),
            SimpleNamespace(trigger_id="other"),
        ],
        count_by_status=lambda status: 3,
    )
    monkeypatch.setattr(query_services, "get_alpha_trigger_repository", lambda: trigger_repo)
    monkeypatch.setattr(
        query_services,
        "get_alpha_candidate_repository",
        lambda: candidate_repo,
    )
    context = query_services.get_candidate_generation_context(limit=2)
    assert context["existing_trigger_ids"] == {"t1"}
    assert context["actionable_count"] == 3
    assert query_services.has_alpha_triggers() is True
    assert query_services.has_alpha_candidates() is True
    assert '"a": 1' in pprint_json('{"a": 1}')
    assert pprint_json("not-json") == "not-json"
    assert '"b": 2' in pprint_json({"b": 2})

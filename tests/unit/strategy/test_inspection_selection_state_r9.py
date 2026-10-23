"""Selection-state tests for strategy lookup provenance."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.strategy.application.execution_gateway import (
    InspectionSelection,
    StrategyExecutionGateway,
)
from apps.strategy.infrastructure import repositories as strategy_repositories


class _QuerySet:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def select_related(self, *_fields: str) -> _QuerySet:
        return self

    def order_by(self, *_fields: str) -> _QuerySet:
        return self

    def __getitem__(self, value: slice) -> list[object]:
        return self._rows[value]

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None


class _Manager:
    def __init__(self, result: list[object] | None = None) -> None:
        self._result = result or []
        self.calls: list[dict[str, object]] = []

    def filter(self, **criteria: object) -> _QuerySet:
        self.calls.append(criteria)
        rows = self._result
        for key, expected in criteria.items():
            if key == "metadata__has_key":
                rows = [
                    row
                    for row in rows
                    if isinstance(getattr(row, "metadata", None), dict) and expected in row.metadata
                ]
            elif key == "metadata__account_id":
                rows = [
                    row
                    for row in rows
                    if isinstance(getattr(row, "metadata", None), dict)
                    and row.metadata.get("account_id") == expected
                ]
            elif key in {"strategy_id", "portfolio_id"}:
                rows = [row for row in rows if getattr(row, key, expected) == expected]
            elif key == "is_active":
                rows = [row for row in rows if getattr(row, key, True) is expected]
        return _QuerySet(rows)


def _model(manager: _Manager) -> type[object]:
    return type("FakeModel", (), {"_default_manager": manager})


def test_unverified_empty_selection_does_not_mean_confirmed_absence() -> None:
    selection = InspectionSelection(
        strategy_id=None,
        position_rule_id=None,
        rule_metadata={},
    )

    assert selection.validated_selection_state == "unavailable"


def test_absence_marker_with_contradictory_rule_metadata_is_unavailable() -> None:
    selection = InspectionSelection(
        strategy_id=None,
        position_rule_id=None,
        rule_metadata={"risk": "present"},
        selection_state="confirmed_unconfigured",
    )

    assert selection.validated_selection_state == "unavailable"


def test_configured_assignment_with_missing_policy_stays_restrictive() -> None:
    selection = InspectionSelection(
        strategy_id=13,
        position_rule_id=None,
        rule_metadata={},
        max_position_pct=None,
        max_total_position_pct=None,
        selection_state="configured",
    )

    assert selection.validated_selection_state == "configured"


def test_successful_empty_repository_lookup_confirms_unconfigured_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assignment_manager = _Manager()
    rule_manager = _Manager()
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(assignment_manager),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(rule_manager),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613
    )

    assert selection.validated_selection_state == "confirmed_unconfigured"
    assert assignment_manager.calls == [{"portfolio_id": 613, "is_active": True}]
    assert rule_manager.calls == [{"is_active": True, "metadata__has_key": "account_id"}]


def test_active_assignment_without_rule_remains_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = SimpleNamespace(
        id=27,
        is_active=True,
        name="configured",
        strategy_type="rule_based",
        version=3,
        max_position_pct=18.0,
        max_total_position_pct=90.0,
        stop_loss_pct=None,
    )
    assignment_manager = _Manager(
        [
            SimpleNamespace(
                strategy=strategy,
                is_active=True,
                portfolio_id=613,
                override_max_position_pct=None,
                override_stop_loss_pct=None,
            )
        ]
    )
    rule_manager = _Manager()
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(assignment_manager),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(rule_manager),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613
    )

    assert selection.selection_state == "configured"
    assert selection.strategy_id == 27
    assert selection.position_rule_id is None
    assert selection.validated_selection_state == "configured"
    assert rule_manager.calls[-1] == {"strategy_id": 27, "is_active": True}


@pytest.mark.parametrize("bound_account_id", [613, "613"])
def test_account_bound_rule_without_assignment_is_not_treated_as_absence(
    monkeypatch: pytest.MonkeyPatch,
    bound_account_id: int | str,
) -> None:
    strategy = SimpleNamespace(
        id=31,
        is_active=True,
        name="bound rule",
        strategy_type="rule_based",
        version=1,
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        stop_loss_pct=None,
    )
    rule = SimpleNamespace(
        id=42,
        strategy_id=31,
        strategy=strategy,
        is_active=True,
        metadata={"account_id": bound_account_id},
        name="account rule",
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(_Manager()),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(_Manager([rule])),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613
    )

    assert selection.validated_selection_state == "configured"
    assert selection.strategy_id == 31
    assert selection.position_rule_id == 42


def test_assignment_does_not_borrow_rule_bound_to_another_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = SimpleNamespace(
        id=27,
        is_active=True,
        name="assigned strategy",
        strategy_type="rule_based",
        version=3,
        max_position_pct=18.0,
        max_total_position_pct=90.0,
        stop_loss_pct=None,
    )
    assignment = SimpleNamespace(
        strategy=strategy,
        is_active=True,
        portfolio_id=613,
        override_max_position_pct=None,
        override_stop_loss_pct=None,
    )
    other_account_rule = SimpleNamespace(
        id=42,
        strategy_id=27,
        strategy=strategy,
        is_active=True,
        metadata={"account_id": 614},
        name="other account rule",
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(_Manager([assignment])),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(_Manager([other_account_rule])),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613
    )

    assert selection.selection_state == "unavailable"
    assert selection.validated_selection_state == "unavailable"


def test_malformed_rule_for_unrelated_strategy_does_not_block_valid_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assigned_strategy = SimpleNamespace(
        id=27,
        is_active=True,
        name="assigned strategy",
        strategy_type="rule_based",
        version=3,
        max_position_pct=18.0,
        max_total_position_pct=90.0,
        stop_loss_pct=None,
    )
    unrelated_strategy = SimpleNamespace(id=31, is_active=True)
    assignment = SimpleNamespace(
        strategy=assigned_strategy,
        is_active=True,
        portfolio_id=613,
        override_max_position_pct=None,
        override_stop_loss_pct=None,
    )
    unrelated_malformed_rule = SimpleNamespace(
        id=42,
        strategy_id=31,
        strategy=unrelated_strategy,
        is_active=True,
        metadata={"account_id": True},
        name="unrelated malformed rule",
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(_Manager([assignment])),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(_Manager([unrelated_malformed_rule])),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613
    )

    assert selection.validated_selection_state == "configured"
    assert selection.strategy_id == 27
    assert selection.position_rule_id is None


def test_explicit_strategy_does_not_borrow_other_accounts_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = SimpleNamespace(
        id=27,
        is_active=True,
        name="requested strategy",
        strategy_type="rule_based",
        version=3,
        max_position_pct=18.0,
        max_total_position_pct=90.0,
        stop_loss_pct=None,
    )
    other_account_rule = SimpleNamespace(
        id=42,
        strategy_id=27,
        strategy=strategy,
        is_active=True,
        metadata={"account_id": 614},
        name="other account rule",
    )
    monkeypatch.setattr(
        strategy_repositories,
        "StrategyModel",
        _model(_Manager([strategy])),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(_Manager()),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(_Manager([other_account_rule])),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613,
        strategy_id=27,
    )

    assert selection.selection_state == "unavailable"
    assert selection.validated_selection_state == "unavailable"


def test_explicit_strategy_with_no_account_override_remains_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = SimpleNamespace(
        id=27,
        is_active=True,
        name="requested strategy",
        strategy_type="rule_based",
        version=3,
        max_position_pct=18.0,
        max_total_position_pct=90.0,
        stop_loss_pct=None,
    )
    assignment = SimpleNamespace(
        strategy_id=27,
        portfolio_id=613,
        is_active=True,
        override_max_position_pct=None,
        override_stop_loss_pct=None,
    )
    assignment_manager = _Manager([assignment])
    rule_manager = _Manager()
    monkeypatch.setattr(strategy_repositories, "StrategyModel", _model(_Manager([strategy])))
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(assignment_manager),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(rule_manager),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613,
        strategy_id=27,
    )

    assert selection.validated_selection_state == "configured"
    assert selection.strategy_id == 27
    assert assignment_manager.calls == [{"portfolio_id": 613, "strategy_id": 27, "is_active": True}]


def test_explicit_strategy_ignores_another_accounts_assignment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = SimpleNamespace(
        id=27,
        is_active=True,
        name="requested strategy",
        strategy_type="rule_based",
        version=3,
        max_position_pct=18.0,
        max_total_position_pct=90.0,
        stop_loss_pct=None,
    )
    other_account_assignment = SimpleNamespace(
        strategy_id=27,
        portfolio_id=614,
        is_active=True,
        override_max_position_pct=10.0,
        override_stop_loss_pct=None,
    )
    assignment_manager = _Manager([other_account_assignment])
    monkeypatch.setattr(strategy_repositories, "StrategyModel", _model(_Manager([strategy])))
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(assignment_manager),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(_Manager()),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613,
        strategy_id=27,
    )

    assert selection.validated_selection_state == "configured"
    assert assignment_manager.calls == [{"portfolio_id": 613, "strategy_id": 27, "is_active": True}]


@pytest.mark.parametrize(
    ("override_max_position_pct", "override_stop_loss_pct"),
    [(0.0, None), (None, 0.0), (5.0, None), (None, 3.0)],
)
def test_explicit_strategy_assignment_override_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    override_max_position_pct: float | None,
    override_stop_loss_pct: float | None,
) -> None:
    strategy = SimpleNamespace(
        id=27,
        is_active=True,
        name="requested strategy",
        strategy_type="rule_based",
        version=3,
        max_position_pct=18.0,
        max_total_position_pct=90.0,
        stop_loss_pct=8.0,
    )
    assignment = SimpleNamespace(
        strategy_id=27,
        portfolio_id=613,
        is_active=True,
        override_max_position_pct=override_max_position_pct,
        override_stop_loss_pct=override_stop_loss_pct,
    )
    monkeypatch.setattr(strategy_repositories, "StrategyModel", _model(_Manager([strategy])))
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(_Manager([assignment])),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(_Manager()),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613,
        strategy_id=27,
    )

    assert selection.selection_state == "unavailable"
    assert selection.validated_selection_state == "unavailable"
    assert "STRATEGY_ASSIGNMENT_OVERRIDE_UNSUPPORTED" in caplog.text


@pytest.mark.parametrize(
    ("override_max_position_pct", "override_stop_loss_pct"),
    [(0.0, None), (None, 0.0), (5.0, None), (None, 3.0)],
)
def test_selected_account_assignment_override_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    override_max_position_pct: float | None,
    override_stop_loss_pct: float | None,
) -> None:
    strategy = SimpleNamespace(
        id=27,
        is_active=True,
        name="assigned strategy",
        strategy_type="rule_based",
        version=3,
        max_position_pct=18.0,
        max_total_position_pct=90.0,
        stop_loss_pct=8.0,
    )
    assignment = SimpleNamespace(
        strategy=strategy,
        strategy_id=27,
        is_active=True,
        portfolio_id=613,
        override_max_position_pct=override_max_position_pct,
        override_stop_loss_pct=override_stop_loss_pct,
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(_Manager([assignment])),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(_Manager()),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613,
    )

    assert selection.selection_state == "unavailable"
    assert selection.validated_selection_state == "unavailable"
    assert "STRATEGY_ASSIGNMENT_OVERRIDE_UNSUPPORTED" in caplog.text


def test_malformed_account_binding_is_not_treated_as_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed_rule = SimpleNamespace(
        id=42,
        strategy_id=31,
        strategy=SimpleNamespace(id=31, is_active=True),
        is_active=True,
        metadata={"account_id": True},
        name="malformed account rule",
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(_Manager()),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(_Manager([malformed_rule])),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613
    )

    assert selection.selection_state == "unavailable"
    assert selection.validated_selection_state == "unavailable"


def test_assignment_and_account_rule_for_different_strategies_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assigned = SimpleNamespace(id=27, is_active=True)
    bound = SimpleNamespace(id=31, is_active=True)
    rule = SimpleNamespace(
        id=42,
        strategy_id=31,
        strategy=bound,
        is_active=True,
        metadata={"account_id": 613},
        name="account rule",
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(
            _Manager(
                [
                    SimpleNamespace(
                        strategy=assigned,
                        is_active=True,
                        portfolio_id=613,
                        override_max_position_pct=None,
                        override_stop_loss_pct=None,
                    )
                ]
            )
        ),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(_Manager([rule])),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613
    )

    assert selection.selection_state == "unavailable"
    assert selection.validated_selection_state == "unavailable"


def test_ambiguous_active_assignments_are_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    first = SimpleNamespace(
        strategy=SimpleNamespace(id=27, is_active=True),
        is_active=True,
        portfolio_id=613,
        override_max_position_pct=None,
        override_stop_loss_pct=None,
    )
    second = SimpleNamespace(
        strategy=SimpleNamespace(id=28, is_active=True),
        is_active=True,
        portfolio_id=613,
        override_max_position_pct=None,
        override_stop_loss_pct=None,
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PortfolioStrategyAssignmentModel",
        _model(_Manager([first, second])),
    )
    monkeypatch.setattr(
        strategy_repositories,
        "PositionManagementRuleModel",
        _model(_Manager()),
    )

    selection = strategy_repositories.DjangoStrategyGatewayRepository().get_inspection_selection(
        account_id=613
    )

    assert selection.selection_state == "unavailable"
    assert selection.validated_selection_state == "unavailable"


def test_gateway_lookup_exception_is_unavailable() -> None:
    class _BrokenRepository:
        def get_inspection_selection(
            self,
            account_id: int,
            strategy_id: int | None = None,
        ) -> InspectionSelection:
            raise RuntimeError(f"lookup failed for {account_id}:{strategy_id}")

    selection = StrategyExecutionGateway(
        query_repository=_BrokenRepository()
    ).get_inspection_selection(account_id=613)

    assert selection.selection_state == "unavailable"
    assert selection.validated_selection_state == "unavailable"


def test_gateway_malformed_repository_result_is_unavailable() -> None:
    class _MalformedRepository:
        def get_inspection_selection(
            self,
            account_id: int,
            strategy_id: int | None = None,
        ) -> object:
            return object()

    selection = StrategyExecutionGateway(
        query_repository=_MalformedRepository()
    ).get_inspection_selection(account_id=613)

    assert selection.selection_state == "unavailable"
    assert selection.validated_selection_state == "unavailable"
    assert selection.rule_metadata == {}


def test_gateway_malformed_absence_dto_is_sanitized_to_unavailable() -> None:
    class _MalformedRepository:
        def get_inspection_selection(
            self,
            account_id: int,
            strategy_id: int | None = None,
        ) -> InspectionSelection:
            return InspectionSelection(
                strategy_id=None,
                position_rule_id=None,
                rule_metadata={"unvalidated": True},
                selection_state="confirmed_unconfigured",
            )

    selection = StrategyExecutionGateway(
        query_repository=_MalformedRepository()
    ).get_inspection_selection(account_id=613)

    assert selection.selection_state == "unavailable"
    assert selection.validated_selection_state == "unavailable"
    assert selection.rule_metadata == {}

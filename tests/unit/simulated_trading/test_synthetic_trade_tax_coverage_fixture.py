"""Legacy test scaffolding must never override a real or deliberately missing reader."""

import pytest

from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from tests.support.synthetic_trade_tax_coverage import (
    SyntheticTradeTaxCoverage,
    install_synthetic_trade_tax_compositions,
    install_synthetic_trade_tax_coverage,
)


def test_composition_fixture_installs_at_the_actual_lazy_import_roots(monkeypatch):
    import apps.simulated_trading.corporate_action_tax_cash_coverage_composition as coverage
    import apps.simulated_trading.execution_settlement_composition as execution

    install_synthetic_trade_tax_compositions(monkeypatch)
    reader = execution.build_configured_tax_cash_coverage_reader(using="default")
    assert isinstance(reader, SyntheticTradeTaxCoverage)
    assert (
        coverage.DjangoCorporateActionTaxCashCoverageReader(
            runtime_environment="synthetic-isolated-trade", using="default"
        )
        is reader
    )


@pytest.mark.parametrize(
    "repository",
    (
        DjangoSimulatedTradeExecutionRepository,
        DjangoSimulatedOrderReservationRepository,
        DjangoSimulatedOrderFillRepository,
    ),
)
def test_fixture_injects_only_when_the_test_did_not_select_a_reader(monkeypatch, repository):
    install_synthetic_trade_tax_coverage(monkeypatch)
    assert isinstance(
        repository(using="default")._tax_cash_coverage_reader, SyntheticTradeTaxCoverage
    )
    assert (
        repository(using="default", tax_cash_coverage_reader=None)._tax_cash_coverage_reader is None
    )
    explicit = SyntheticTradeTaxCoverage()
    assert (
        repository(using="default", tax_cash_coverage_reader=explicit)._tax_cash_coverage_reader
        is explicit
    )

"""
Django ORM Model Factories

For integration and API tests that need database records.
Uses factory_boy for model creation with sensible defaults.

Usage:
    from tests.factories.model_factories import MacroIndicatorFactory, RegimeLogFactory
"""

from datetime import date

try:
    import factory
    from factory.django import DjangoModelFactory
except ImportError:
    raise ImportError(
        "factory_boy is required for model factories. "
        "Install with: pip install factory-boy"
    ) from None


class MacroIndicatorFactory(DjangoModelFactory):
    """Factory for MacroIndicator (unified config+data model)."""

    class Meta:
        model = "macro.MacroIndicator"
        django_get_or_create = ("code", "reporting_period")

    code = factory.Sequence(lambda n: f"TEST_INDICATOR_{n}")
    value = 50.0
    unit = "指数"
    reporting_period = factory.LazyFunction(date.today)
    period_type = "M"
    source = "fixture"


class RegimeLogFactory(DjangoModelFactory):
    """Factory for RegimeLog."""

    class Meta:
        model = "regime.RegimeLog"

    observed_at = factory.LazyFunction(date.today)
    growth_momentum_z = 0.5
    inflation_momentum_z = -0.3
    distribution = factory.LazyFunction(lambda: {
        "growth_inflation": 0.1,
        "growth_deflation": 0.6,
        "recession_inflation": 0.1,
        "recession_deflation": 0.2,
    })
    dominant_regime = "growth_deflation"
    confidence = 0.75


class SignalFactory(DjangoModelFactory):
    """Factory for InvestmentSignalModel."""

    class Meta:
        model = "signal.InvestmentSignalModel"

    asset_code = factory.Sequence(lambda n: f"{n + 1:06d}.SH")
    asset_class = "a_share"
    direction = "LONG"
    logic_desc = factory.Faker("sentence")
    invalidation_description = factory.Faker("sentence")
    invalidation_threshold = 50.0
    status = "pending"

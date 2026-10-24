"""Tests for the versioned Data Center catalog manifests."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load_checker() -> ModuleType:
    script = _ROOT / "scripts" / "check_data_center_catalog_contracts.py"
    spec = importlib.util.spec_from_file_location("check_data_center_catalog_contracts", script)
    if spec is None or spec.loader is None:
        raise AssertionError("catalog checker cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_canonical_datasets_have_versioned_manifests() -> None:
    """D0-D9 must each have a schema, provider binding, and publish policy."""

    _load_checker().validate()


def test_quote_change_pct_source_contracts_parse_as_typed_catalog_values() -> None:
    """Nested quote source semantics must not remain an untyped JSON mapping."""

    from apps.data_center.infrastructure.catalog_models import _field_contracts

    fields = _field_contracts(
        [
            {
                "name": "change_pct",
                "type": "decimal",
                "unit": "percent",
                "nullable": True,
                "zero_allowed": True,
                "source_contracts": [
                    {
                        "provider_source": "vendor-main",
                        "source_field": "pct",
                        "origin": "vendor_reported",
                        "source_unit": "hundredth_percent",
                        "canonical_unit": "percent",
                        "scale_numerator": 1,
                        "scale_denominator": 100,
                        "reference_session": "source_quote_observation",
                        "action_basis": "vendor_basis_unverified",
                    }
                ],
            }
        ]
    )

    assert len(fields) == 1
    assert len(fields[0].source_contracts) == 1
    assert fields[0].source_contracts[0].provider_source == "vendor-main"
    assert fields[0].source_contracts[0].scale_denominator == 100


def test_quote_change_pct_contract_is_unseeded_until_source_semantics_are_verified() -> None:
    """The schema is nullable while no provider receives implicit rank eligibility."""

    manifest = json.loads((_ROOT / "governance" / "dataset_contracts.json").read_text())
    quote_contract = next(
        row for row in manifest["contracts"] if row["dataset_key"] == "equity.quote.snapshot"
    )

    assert quote_contract["contract_version"] == "2.0"
    assert quote_contract["schema_version"] == "2.0"
    metric_field = next(
        field for field in quote_contract["fields"] if field["name"] == "change_pct"
    )
    assert metric_field["nullable"] is True
    assert metric_field["zero_allowed"] is True
    assert metric_field.get("source_contracts", []) == []


def test_quote_metric_source_contracts_are_limited_to_nullable_percent_quote_field() -> None:
    """Metric interpretation rules cannot be attached to another field or dataset."""

    from apps.data_center.domain.contracts import (
        DatasetContract,
        DatasetFieldContract,
        DatasetKey,
        QuoteMetricSourceContract,
    )

    source_contract = QuoteMetricSourceContract(
        provider_source="vendor-main",
        source_field="pct",
        origin="vendor_reported",
        source_unit="percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
        reference_session="source_quote_observation",
        action_basis="basis-unverified",
    )
    with pytest.raises(ValueError, match="nullable decimal percent"):
        DatasetFieldContract(
            name="change_pct",
            value_type="decimal",
            unit="CNY",
            nullable=False,
            zero_allowed=True,
            source_contracts=(source_contract,),
        )

    field = DatasetFieldContract(
        name="change_pct",
        value_type="decimal",
        unit="percent",
        nullable=True,
        zero_allowed=True,
        source_contracts=(source_contract,),
    )
    with pytest.raises(ValueError, match="quote snapshot dataset"):
        DatasetContract(
            key=DatasetKey("equity.price.bar", "2.0", "2.0"),
            owner="data-platform",
            frequency="daily",
            decision_critical=True,
            fields=(field,),
        )


@pytest.mark.django_db
def test_quote_change_pct_contract_requires_new_dataset_version_for_semantic_change() -> None:
    """Persisted quote semantics stay fixed until the next contract version."""

    from apps.data_center.domain.contracts import (
        DatasetContract,
        DatasetFieldContract,
        DatasetKey,
        QuoteMetricSourceContract,
    )
    from apps.data_center.infrastructure.catalog_models import DatasetContractModel
    from apps.data_center.infrastructure.catalog_runtime_repositories import (
        DatasetContractRepository,
    )

    source_contract = QuoteMetricSourceContract(
        provider_source="vendor-main",
        source_field="pct",
        origin="vendor_reported",
        source_unit="percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
        reference_session="source_quote_observation",
        action_basis="basis-a",
    )
    price_field = DatasetFieldContract(
        name="price",
        value_type="decimal",
        unit="CNY",
        nullable=False,
        zero_allowed=False,
        minimum=0.01,
        maximum=9999.99,
    )
    metric_field = DatasetFieldContract(
        name="change_pct",
        value_type="decimal",
        unit="percent",
        nullable=True,
        zero_allowed=True,
        source_contracts=(source_contract,),
    )
    existing_contract = DatasetContract(
        key=DatasetKey("equity.quote.snapshot", "2.0", "2.0"),
        owner="data-platform",
        frequency="intraday",
        decision_critical=True,
        fields=(price_field, metric_field),
        freshness_seconds=120,
        comparable_group="equity-quotes",
        execution_freshness_seconds=30,
        calendar_response_max_age_seconds=20,
    )
    changed_source_contract = replace(source_contract, action_basis="basis-b")
    same_version_rewrites = (
        replace(existing_contract, owner="different-owner"),
        replace(existing_contract, frequency="daily"),
        replace(existing_contract, decision_critical=False),
        replace(existing_contract, freshness_seconds=240),
        replace(existing_contract, comparable_group="other-quotes"),
        replace(existing_contract, execution_freshness_seconds=60),
        replace(existing_contract, calendar_response_max_age_seconds=40),
        replace(
            existing_contract,
            fields=(replace(price_field, name="open_price"), metric_field),
        ),
        replace(
            existing_contract,
            fields=(replace(price_field, value_type="integer"), metric_field),
        ),
        replace(existing_contract, fields=(replace(price_field, unit="USD"), metric_field)),
        replace(
            existing_contract,
            fields=(replace(price_field, nullable=True), metric_field),
        ),
        replace(
            existing_contract,
            fields=(replace(price_field, zero_allowed=True), metric_field),
        ),
        replace(
            existing_contract,
            fields=(replace(price_field, minimum=0.02), metric_field),
        ),
        replace(
            existing_contract,
            fields=(replace(price_field, maximum=999.99), metric_field),
        ),
        replace(existing_contract, fields=(metric_field, price_field)),
        replace(
            existing_contract,
            fields=(
                price_field,
                replace(
                    metric_field,
                    source_contracts=(changed_source_contract,),
                ),
            ),
        ),
    )

    repository = DatasetContractRepository()
    repository.save(existing_contract)
    stored_row = DatasetContractModel._default_manager.get(
        dataset_key=existing_contract.key.value,
        contract_version=existing_contract.key.contract_version,
        schema_version=existing_contract.key.schema_version,
    )

    for rewritten in same_version_rewrites:
        with pytest.raises(ValueError, match="new contract version"):
            repository.save(rewritten)

        stored_row.refresh_from_db()
        assert stored_row.to_domain() == existing_contract
        assert stored_row.active is True

    new_version = replace(
        existing_contract,
        key=DatasetKey("equity.quote.snapshot", "3.0", "3.0"),
        fields=(
            price_field,
            replace(metric_field, source_contracts=(changed_source_contract,)),
        ),
    )
    assert repository.save(new_version) == new_version

    stored_row.refresh_from_db()
    assert stored_row.active is False
    new_row = DatasetContractModel._default_manager.get(
        dataset_key=new_version.key.value,
        contract_version=new_version.key.contract_version,
        schema_version=new_version.key.schema_version,
    )
    assert new_row.to_domain() == new_version
    assert new_row.active is True


def test_quote_contract_creation_race_rechecks_locked_winner_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model proxy exercises the concurrent-winner immutability branch."""

    from apps.data_center.domain.contracts import (
        DatasetContract,
        DatasetFieldContract,
        DatasetKey,
    )
    from apps.data_center.infrastructure import catalog_runtime_repositories

    requested_contract = DatasetContract(
        key=DatasetKey("equity.quote.snapshot", "2.0", "2.0"),
        owner="data-platform",
        frequency="intraday",
        decision_critical=True,
        fields=(
            DatasetFieldContract(
                name="price",
                value_type="decimal",
                unit="CNY",
                nullable=False,
                zero_allowed=False,
            ),
        ),
    )
    concurrent_contract = replace(requested_contract, owner="different-owner")

    class _Rows:
        def first(self) -> None:
            return None

        def exclude(self, **_kwargs: object) -> _Rows:
            return self

        def update(self, **_kwargs: object) -> int:
            return 0

    class _Winner:
        pk: int = 17
        execution_freshness_seconds: int | None = None
        calendar_response_max_age_seconds: int | None = None
        active: bool = True

        def to_domain(self) -> DatasetContract:
            return concurrent_contract

        def save(self, **_kwargs: object) -> None:
            raise AssertionError("a changed contract must not be updated")

    winner = _Winner()

    class _Manager:
        def __init__(self) -> None:
            self.race_recovered = False
            self.locked_winner_read = False

        def select_for_update(self) -> _Manager:
            return self

        def filter(self, **_kwargs: object) -> _Rows:
            return _Rows()

        def get_or_create(self, **_kwargs: object) -> tuple[_Winner, bool]:
            self.race_recovered = True
            return winner, False

        def get(self, **kwargs: object) -> _Winner:
            assert kwargs == {"pk": winner.pk}
            self.locked_winner_read = True
            return winner

    manager = _Manager()

    class _DatasetContractModelProxy:
        _default_manager = manager

    monkeypatch.setattr(
        catalog_runtime_repositories,
        "DatasetContractModel",
        _DatasetContractModelProxy,
    )
    monkeypatch.setattr(
        catalog_runtime_repositories.transaction,
        "atomic",
        lambda: __import__("contextlib").nullcontext(),
    )

    with pytest.raises(ValueError, match="quote dataset contract semantics.*new contract version"):
        catalog_runtime_repositories.DatasetContractRepository().save(requested_contract)

    assert manager.race_recovered is True
    assert manager.locked_winner_read is True

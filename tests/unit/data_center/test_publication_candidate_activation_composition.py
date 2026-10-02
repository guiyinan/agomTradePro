"""Contracts for the isolated production current-market bundle composition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from apps.data_center.infrastructure.candidate_raw_audit_metadata_resolver import (
    DjangoCandidateRawAuditMetadataResolver,
)
from apps.data_center.infrastructure.current_publication_staging_repository import (
    DjangoCurrentPublicationStagingRepository,
)
from apps.data_center.infrastructure.publication_group_activation_repository import (
    DjangoPublicationActivationGroupRepository,
)
from apps.data_center.publication_candidate_activation_composition import (
    ProductionCurrentMarketPublicationBundle,
    build_production_current_market_publication_bundle,
)
from core.integration import data_center_audit


def test_production_bundle_reuses_fixed_rebuilders_and_binds_all_components_to_default() -> None:
    bundle = build_production_current_market_publication_bundle()

    assert bundle.database_alias == "default"
    expected = {
        "quote_staging": ("equity.quote.snapshot", "data_center_quote_snapshot"),
        "price_staging": ("equity.price.bar", "data_center_price_bar"),
        "valuation_staging": ("equity.valuation.fact", "data_center_valuation_fact"),
    }
    for field_name, (dataset_key, fact_table) in expected.items():
        staging = getattr(bundle, field_name)
        assert staging._rebuilder.dataset.dataset_key == dataset_key
        assert staging._rebuilder.dataset.fact_table == fact_table
        assert isinstance(staging._raw_audit_resolver, DjangoCandidateRawAuditMetadataResolver)
        assert staging._raw_audit_resolver.database_alias == "default"
        assert isinstance(staging._repository, DjangoCurrentPublicationStagingRepository)
        assert staging._repository.database_alias == "default"

    activation_repository = bundle.activate_group._repository
    assert isinstance(activation_repository, DjangoPublicationActivationGroupRepository)
    assert activation_repository.database_alias == "default"


def test_dedicated_composition_exposes_a_typed_production_bundle() -> None:
    bundle = build_production_current_market_publication_bundle(using="default")

    assert isinstance(bundle, ProductionCurrentMarketPublicationBundle)
    assert bundle.database_alias == "default"


@pytest.mark.parametrize("using", ["replica", "", " default", None])
def test_production_bundle_rejects_noncanonical_or_nondefault_aliases(using: object) -> None:
    with pytest.raises(data_center_audit.SystemAuditCompositionUnavailable) as error:
        build_production_current_market_publication_bundle(using=using)  # type: ignore[arg-type]

    assert error.value.reason_code == "composition_alias_mismatch"


def test_stage_and_group_infrastructure_reject_nondefault_aliases() -> None:
    with pytest.raises(ValueError, match="default database"):
        DjangoCandidateRawAuditMetadataResolver(using="replica")
    with pytest.raises(ValueError, match="default database"):
        DjangoCurrentPublicationStagingRepository(using="replica")
    with pytest.raises(ValueError, match="default database alias"):
        DjangoPublicationActivationGroupRepository(using="replica")


def test_bundle_rejects_staging_repository_alias_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    class _WrongAliasRepository:
        database_alias = "analytics"

    monkeypatch.setattr(
        "apps.data_center.publication_candidate_activation_composition.DjangoCurrentPublicationStagingRepository",
        lambda *, using: _WrongAliasRepository(),
    )

    with pytest.raises(data_center_audit.SystemAuditCompositionUnavailable) as error:
        build_production_current_market_publication_bundle()
    assert error.value.reason_code == "composition_alias_mismatch"


def test_audit_writer_factory_uses_canonical_production_runtime_and_checks_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Writer:
        database_alias = "default"

        def append_manifest_required(self, **_kwargs: object) -> object:
            return object()

        def append_manifest_group_required(self, **_kwargs: object) -> tuple[object, ...]:
            return (object(),)

    calls: list[tuple[str, str]] = []

    def build_writer(*, environment: str, using: str) -> _Writer:
        calls.append((environment, using))
        return _Writer()

    monkeypatch.setattr(
        "apps.data_center.publication_candidate_activation_composition.get_data_publication_activation_audit_writer",
        build_writer,
    )
    bundle = build_production_current_market_publication_bundle()

    writer = bundle.audit_writer_factory()
    assert writer.database_alias == "default"
    assert callable(writer.append_manifest_required)
    assert calls == [("production", "default")]

    class _WrongAliasWriter(_Writer):
        database_alias = "analytics"

    monkeypatch.setattr(
        "apps.data_center.publication_candidate_activation_composition.get_data_publication_activation_audit_writer",
        lambda **_kwargs: _WrongAliasWriter(),
    )
    with pytest.raises(data_center_audit.SystemAuditCompositionUnavailable) as error:
        bundle.audit_writer_factory()
    assert error.value.reason_code == "composition_alias_mismatch"


def test_audit_outbox_configuration_failure_is_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_error = data_center_audit.SystemAuditCompositionUnavailable(
        "outbox runtime is unavailable",
        reason_code="composition_not_wired",
    )
    monkeypatch.setattr(
        "apps.data_center.publication_candidate_activation_composition.get_data_publication_activation_audit_writer",
        lambda **_kwargs: (_ for _ in ()).throw(expected_error),
    )
    bundle = build_production_current_market_publication_bundle()

    with pytest.raises(data_center_audit.SystemAuditCompositionUnavailable) as error:
        bundle.audit_writer_factory()
    assert error.value is expected_error


def test_authority_capture_callable_is_alias_bound_and_preserves_preflight_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass(frozen=True)
    class _Capture:
        database_alias: str

    class _ReaderContext:
        pass

    expected_context = _ReaderContext()
    expected_cutoff = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
    calls: list[tuple[str, datetime, object]] = []

    def capture(*, using: str, as_of: datetime, preflight_context: object) -> _Capture:
        calls.append((using, as_of, preflight_context))
        return _Capture(database_alias=using)

    monkeypatch.setattr(
        "apps.data_center.publication_candidate_activation_composition.ProductionAccountAuthorityCapture",
        _Capture,
    )
    monkeypatch.setattr(
        "apps.data_center.publication_candidate_activation_composition.capture_production_account_authority",
        capture,
    )
    bundle = build_production_current_market_publication_bundle()

    result = bundle.authority_capture(
        as_of=expected_cutoff,
        preflight_context=expected_context,  # type: ignore[arg-type]
    )
    assert isinstance(result, _Capture)
    assert calls == [("default", expected_cutoff, expected_context)]

    monkeypatch.setattr(
        "apps.data_center.publication_candidate_activation_composition.capture_production_account_authority",
        lambda **_kwargs: _Capture(database_alias="analytics"),
    )
    with pytest.raises(data_center_audit.SystemAuditCompositionUnavailable) as error:
        bundle.authority_capture(
            as_of=expected_cutoff,
            preflight_context=expected_context,  # type: ignore[arg-type]
        )
    assert error.value.reason_code == "composition_alias_mismatch"

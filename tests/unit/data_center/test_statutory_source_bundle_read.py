"""Exact retained bundle reads preserve evidence without conferring legal authority."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from apps.data_center import statutory_source_capture_composition as composition
from apps.data_center.application.statutory_source_bundle import (
    ConfiguredStatutorySourceBundleRead,
)
from apps.data_center.domain.statutory_source_catalog import (
    StatutorySourceCatalogProfile,
    StatutorySourceDocumentCaptureRule,
)
from core.exceptions import DataValidationError
from tests.unit.data_center.test_statutory_source_documents import (
    _CAPTURED_AT,
    BODY,
    _bundle,
)


def _reader(monkeypatch: pytest.MonkeyPatch) -> tuple[object, Mock, Mock, Mock]:
    bundle = _bundle()
    profile = StatutorySourceCatalogProfile(
        profile_id="fixture",
        version="v1",
        publisher_code="QA",
        enabled=True,
        allowed_hosts=frozenset({"example.invalid"}),
        max_capture_age_seconds=60,
        documents=(
            StatutorySourceDocumentCaptureRule(
                revision=bundle.captures[0].revision,
                max_bytes=1024,
                allowed_media_types=frozenset({"text/html"}),
            ),
        ),
    )
    configuration = composition._Configuration(profile, "a" * 64)
    service = composition.ConfiguredStatutorySourceCaptureService(
        provider_id=123, body_store_root=Path("synthetic"), deployment_region="qa"
    )
    monkeypatch.setattr(service, "_configuration", Mock(return_value=configuration))
    repo = Mock()
    repo.get_exact.return_value = bundle
    store = Mock()
    store.read.return_value = BODY
    audit = Mock()
    audit.filter.return_value.count.return_value = 1
    monkeypatch.setattr(composition, "DjangoStatutorySourceRepository", Mock(return_value=repo))
    monkeypatch.setattr(composition, "StatutorySourceBodyStore", Mock(return_value=store))
    monkeypatch.setattr(composition, "_retained_capture_audit_count", audit)
    monkeypatch.setattr(composition.timezone, "now", lambda: _CAPTURED_AT + timedelta(seconds=30))
    return service, repo, store, audit


def test_exact_bundle_read_keeps_original_clocks_and_blocks_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, repo, store, audit = _reader(monkeypatch)
    audit.return_value = 1
    result = reader.read_retained_bundle(
        bundle_id="synthetic-source-set", version="catalog-revision-1"
    )
    assert type(result) is ConfiguredStatutorySourceBundleRead
    assert result.bundle == _bundle()
    assert result.bodies == (BODY,)
    assert result.source_observed_at == _CAPTURED_AT
    assert result.checked_at == _CAPTURED_AT + timedelta(seconds=30)
    assert result.freshness_status == "fresh"
    assert result.reliability == "unqualified"
    assert result.must_not_use_for_decision is True
    assert result.blocked_reason == "statutory_legal_qualification_required"
    repo.get_exact.assert_called_once_with(
        bundle_id="synthetic-source-set", version="catalog-revision-1"
    )
    store.read.assert_called_once()


@pytest.mark.parametrize("age", [-1, 61])
def test_future_or_old_capture_does_not_receive_new_observation_time(
    monkeypatch: pytest.MonkeyPatch,
    age: int,
) -> None:
    reader, _, _, audit = _reader(monkeypatch)
    audit.return_value = 1
    monkeypatch.setattr(composition.timezone, "now", lambda: _CAPTURED_AT + timedelta(seconds=age))
    with pytest.raises(DataValidationError, match="window"):
        reader.read_retained_bundle(bundle_id="synthetic-source-set", version="catalog-revision-1")


@pytest.mark.parametrize("count", [0, 2])
def test_missing_or_ambiguous_successful_capture_audit_blocks(
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    reader, _, _, audit = _reader(monkeypatch)
    audit.return_value = count
    with pytest.raises(DataValidationError) as error:
        reader.read_retained_bundle(bundle_id="synthetic-source-set", version="catalog-revision-1")
    assert error.value.code == "STATUTORY_SOURCE_CAPTURE_PROVENANCE_UNAVAILABLE"


def test_missing_exact_bundle_has_no_latest_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    reader, repo, _, _ = _reader(monkeypatch)
    repo.get_exact.return_value = None
    with pytest.raises(DataValidationError) as error:
        reader.read_retained_bundle(bundle_id="synthetic-source-set", version="catalog-revision-1")
    assert error.value.code == "STATUTORY_SOURCE_BUNDLE_UNAVAILABLE"


def test_body_readback_mismatch_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    reader, _, store, audit = _reader(monkeypatch)
    audit.return_value = 1
    store.read.return_value = b"different bytes"
    with pytest.raises(DataValidationError) as error:
        reader.read_retained_bundle(bundle_id="synthetic-source-set", version="catalog-revision-1")
    assert error.value.code == "STATUTORY_SOURCE_BODY_INTEGRITY_FAILED"


def test_configuration_drift_after_readback_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    reader, _, _, audit = _reader(monkeypatch)
    audit.return_value = 1
    first = reader._configuration()
    monkeypatch.setattr(
        reader,
        "_configuration",
        Mock(side_effect=[first, composition._Configuration(first.profile, "b" * 64)]),
    )
    with pytest.raises(DataValidationError) as error:
        reader.read_retained_bundle(bundle_id="synthetic-source-set", version="catalog-revision-1")
    assert error.value.code == "STATUTORY_SOURCE_CAPTURE_CONFIGURATION_CHANGED"


def test_expiry_while_final_configuration_is_checked_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, _, _, audit = _reader(monkeypatch)
    audit.return_value = 1
    clocks = iter((_CAPTURED_AT + timedelta(seconds=59), _CAPTURED_AT + timedelta(seconds=61)))
    monkeypatch.setattr(composition.timezone, "now", lambda: next(clocks))
    with pytest.raises(DataValidationError) as error:
        reader.read_retained_bundle(bundle_id="synthetic-source-set", version="catalog-revision-1")
    assert error.value.code == "STATUTORY_SOURCE_CAPTURE_OUTSIDE_WINDOW"


def test_catalog_revision_mismatch_cannot_be_read_as_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, repo, _, audit = _reader(monkeypatch)
    audit.return_value = 1
    original = _bundle()
    capture = original.captures[0]
    repo.get_exact.return_value = replace(
        original,
        captures=(
            replace(capture, revision=replace(capture.revision, title="Different retained title")),
        ),
    )
    with pytest.raises(DataValidationError) as error:
        reader.read_retained_bundle(bundle_id="synthetic-source-set", version="catalog-revision-1")
    assert error.value.code == "STATUTORY_SOURCE_BUNDLE_CATALOG_MISMATCH"


def test_wrong_bundle_identity_is_never_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    reader, repo, _, _ = _reader(monkeypatch)
    repo.get_exact.return_value = replace(_bundle(), version="other-version")
    with pytest.raises(DataValidationError) as error:
        reader.read_retained_bundle(bundle_id="synthetic-source-set", version="catalog-revision-1")
    assert error.value.code == "STATUTORY_SOURCE_BUNDLE_READ_IDENTITY_MISMATCH"


def test_success_audit_query_binds_capture_provider_host_dataset_and_real_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = Mock()
    selected.filter.return_value.count.return_value = 1
    using = Mock(return_value=selected)
    monkeypatch.setattr(composition.EgressRequestAuditModel._default_manager, "using", using)
    capture = _bundle().captures[0]
    cutoff = _CAPTURED_AT + timedelta(seconds=30)
    assert (
        composition._retained_capture_audit_count(
            capture, provider_id=123, checked_at=cutoff, using="isolated"
        )
        == 1
    )
    using.assert_called_once_with("isolated")
    selected.filter.assert_called_once_with(
        request_id=capture.capture_id,
        provider_id=123,
        dataset_key="statutory_source_documents",
        target_host="example.invalid",
        outcome="success",
        created_at__gte=_CAPTURED_AT,
        created_at__lte=cutoff,
    )

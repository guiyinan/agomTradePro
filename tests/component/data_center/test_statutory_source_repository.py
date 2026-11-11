"""Persist synthetic, unqualified statutory evidence on an isolated database."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, models, transaction

from apps.data_center.application.statutory_source_documents import (
    RetainStatutorySourceDocumentUseCase,
    StatutorySourceRevisionConflictError,
)
from apps.data_center.domain.statutory_source_documents import (
    RetainedStatutorySourceDocumentCapture,
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentBundle,
    StatutorySourceDocumentRevision,
)
from apps.data_center.infrastructure import statutory_source_repository as repository_module
from apps.data_center.infrastructure.statutory_source_body_store import StatutorySourceBodyStore
from apps.data_center.infrastructure.statutory_source_models import (
    StatutorySourceDocumentBundleMemberModel,
    StatutorySourceDocumentBundleModel,
    StatutorySourceDocumentCaptureModel,
    StatutorySourceDocumentRevisionModel,
)
from apps.data_center.infrastructure.statutory_source_repository import (
    DjangoStatutorySourceRepository,
)
from core.exceptions import DataValidationError
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

pytestmark = pytest.mark.django_db(available_apps=["apps.data_center"])
BODY = b"<html>Entirely synthetic statutory source fixture</html>"
OBSERVED = datetime(2026, 11, 1, tzinfo=UTC)
RECORDED = OBSERVED + timedelta(days=1)
SOURCE_MODELS = (
    StatutorySourceDocumentRevisionModel,
    StatutorySourceDocumentCaptureModel,
    StatutorySourceDocumentBundleModel,
    StatutorySourceDocumentBundleMemberModel,
)


@pytest.fixture(scope="module", autouse=True)
def require_real_native_source_schema(django_db_setup: None, django_db_blocker: object) -> None:
    """Require actual migration/trigger evidence rather than a synthetic syncdb schema."""
    del django_db_setup
    with django_db_blocker.unblock():
        if connection.vendor != "postgresql":
            pytest.skip("Native PostgreSQL source schema required")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM django_migrations WHERE app=%s AND name=%s",
                ["data_center", "0111_statutory_source_evidence"],
            )
            assert cursor.fetchone() == (1,)
            cursor.execute(
                "SELECT tgname FROM pg_trigger WHERE tgenabled='A' AND NOT tgisinternal "
                "AND tgname IN (%s,%s,%s,%s)",
                [
                    "dc_stat_rev_immutable",
                    "dc_stat_cap_immutable",
                    "dc_stat_bundle_immutable",
                    "dc_stat_member_immutable",
                ],
            )
            assert len(cursor.fetchall()) == 4


def _revision(body: bytes = BODY) -> StatutorySourceDocumentRevision:
    return StatutorySourceDocumentRevision(
        issuer="Synthetic publisher fixture",
        document_id="SYNTHETIC-DOCUMENT",
        source_version="publisher-version-1",
        canonical_url="https://example.invalid/source",
        title="Synthetic source title",
        legal_number="SYNTHETIC-001",
        publication_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.DATE,
            date_value=date(2001, 1, 1),
        ),
        effective_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.UNKNOWN,
        ),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
    )


def _repository(tmp_path: Path) -> DjangoStatutorySourceRepository:
    return DjangoStatutorySourceRepository(
        body_store=StatutorySourceBodyStore(tmp_path, max_body_bytes=4096),
        clock=lambda: RECORDED,
    )


def _capture(
    repository: DjangoStatutorySourceRepository,
    tmp_path: Path,
    *,
    capture_id: UUID | None = None,
    body: bytes = BODY,
) -> RetainedStatutorySourceDocumentCapture:
    return (
        RetainStatutorySourceDocumentUseCase(
            body_store=StatutorySourceBodyStore(tmp_path, max_body_bytes=4096),
            document_repository=repository,
        )
        .execute(
            revision=_revision(body),
            capture_id=capture_id or uuid4(),
            captured_at=OBSERVED,
            content_type="text/html",
            body=body,
        )
        .capture
    )


def test_real_body_and_metadata_roundtrip_replays_exact_capture(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    capture_id = uuid4()
    first = _capture(repository, tmp_path, capture_id=capture_id)
    assert _capture(repository, tmp_path, capture_id=capture_id) == first
    second = _capture(repository, tmp_path)
    assert first.capture_id != second.capture_id
    assert StatutorySourceDocumentRevisionModel.objects.count() == 1
    assert StatutorySourceDocumentCaptureModel.objects.count() == 2
    assert repository.get_capture(capture_id) == first
    assert (
        repository.get_revision_exact(
            issuer=first.revision.issuer,
            document_id=first.revision.document_id,
            source_version=first.revision.source_version,
        )
        == first.revision
    )
    assert repository.get_capture(uuid4()) is None


def test_same_revision_changed_bytes_and_capture_facts_are_rejected(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    original = _capture(repository, tmp_path)
    with pytest.raises(StatutorySourceRevisionConflictError):
        _capture(repository, tmp_path, body=BODY + b" changed")
    with pytest.raises(DataValidationError):
        repository.append_capture(
            original.revision,
            replace(original, captured_at=OBSERVED + timedelta(seconds=1)),
        )
    assert repository.get_capture(original.capture_id) == original
    assert StatutorySourceDocumentCaptureModel.objects.count() == 1


def test_metadata_append_requires_retained_matching_body_and_valid_clock(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    capture = _capture(repository, tmp_path)
    path = tmp_path / f"{capture.capture_id}.body"
    path.write_bytes(BODY + b" tampered")
    with pytest.raises(DataValidationError):
        repository.append_capture(capture.revision, capture)
    path.write_bytes(BODY)
    with pytest.raises(DataValidationError):
        repository.append_capture(
            capture.revision,
            replace(capture, captured_at=RECORDED + timedelta(seconds=1)),
        )
    assert repository.get_capture(capture.capture_id) == capture


def test_bundle_preserves_both_hashes_and_requires_exact_retained_members(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    capture = _capture(repository, tmp_path)
    bundle = StatutorySourceDocumentBundle(
        bundle_id="synthetic-source-bundle",
        version="1",
        captures=(capture,),
    )
    assert repository.append(bundle).record == bundle
    assert repository.append(bundle).record == bundle
    restored = repository.get_exact(bundle_id=bundle.bundle_id, version=bundle.version)
    assert restored == bundle
    assert restored.source_bundle_sha256 == bundle.source_bundle_sha256
    assert restored.capture_manifest_sha256 == bundle.capture_manifest_sha256
    assert StatutorySourceDocumentBundleModel.objects.count() == 1
    assert StatutorySourceDocumentBundleMemberModel.objects.count() == 1
    unretained = replace(capture, content_type="application/octet-stream")
    with pytest.raises(DataValidationError):
        repository.append(replace(bundle, version="2", captures=(unretained,)))
    assert StatutorySourceDocumentBundleModel.objects.count() == 1


def test_bundle_member_failure_rolls_back_entire_metadata_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    first = _capture(repository, tmp_path)
    second_revision = replace(first.revision, document_id="SECOND-SYNTHETIC-DOCUMENT")
    second_id = uuid4()
    reference = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096).store(second_id, BODY)
    second = replace(
        first, capture_id=second_id, revision=second_revision, body_reference=reference
    )
    repository.append_capture(second_revision, second)
    original_insert = repository_module._insert_claimed
    inserted_members = 0

    def fail_second_member(
        model_type: type[models.Model], values: dict[str, object], *, using: str
    ) -> models.Model:
        nonlocal inserted_members
        if model_type is StatutorySourceDocumentBundleMemberModel:
            inserted_members += 1
            if inserted_members == 2:
                raise IntegrityError("Synthetic second member failure")
        return original_insert(model_type, values, using=using)

    monkeypatch.setattr(repository_module, "_insert_claimed", fail_second_member)
    with pytest.raises(DataValidationError):
        repository.append(
            StatutorySourceDocumentBundle(
                bundle_id="synthetic", version="1", captures=(first, second)
            )
        )
    assert StatutorySourceDocumentBundleModel.objects.count() == 0
    assert StatutorySourceDocumentBundleMemberModel.objects.count() == 0
    assert StatutorySourceDocumentCaptureModel.objects.count() == 2


def test_orm_write_shortcuts_cannot_modify_source_facts(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    capture = _capture(repository, tmp_path)
    repository.append(
        StatutorySourceDocumentBundle(bundle_id="synthetic", version="1", captures=(capture,))
    )
    for model_type in SOURCE_MODELS:
        row = model_type.objects.get()
        with pytest.raises(ValidationError):
            row.save()
        with pytest.raises(ValidationError):
            row.save_base(raw=True)
        with pytest.raises(ValidationError):
            row.delete()
        with pytest.raises(ValidationError):
            model_type.objects.all().update(recorded_at=RECORDED)
        with pytest.raises(ValidationError):
            model_type.objects.all().delete()
        with pytest.raises(ValidationError):
            model_type.objects.all()._raw_delete("default")
        with pytest.raises(ValidationError):
            model_type.objects.bulk_create([model_type()])
        with pytest.raises(ValidationError):
            model_type().save()


def test_postgres_native_mutation_guards_reject_even_raw_sql(tmp_path: Path) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Native PostgreSQL trigger contract")
    repository = _repository(tmp_path)
    capture = _capture(repository, tmp_path)
    repository.append(
        StatutorySourceDocumentBundle(bundle_id="synthetic", version="1", captures=(capture,))
    )
    for model_type in SOURCE_MODELS:
        table = connection.ops.quote_name(model_type._meta.db_table)
        for statement in (f"UPDATE {table} SET recorded_at=recorded_at", f"DELETE FROM {table}"):
            with (
                pytest.raises(IntegrityError) as error,
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(statement)
            cause = error.value.__cause__
            assert getattr(cause, "sqlstate", getattr(cause, "pgcode", None)) == "23514"
        assert model_type.objects.count() == 1


@pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])
def test_postgres_concurrent_revision_conflict_has_one_immutable_winner(tmp_path: Path) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Native PostgreSQL concurrent insert contract")

    def append(index: int) -> str:
        try:
            body = BODY if index == 0 else BODY + b" changed"
            _capture(_repository(tmp_path), tmp_path, body=body)
            return "stored"
        except StatutorySourceRevisionConflictError:
            return "conflict"
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, range(2)))
    assert sorted(results) == ["conflict", "stored"]
    assert StatutorySourceDocumentRevisionModel.objects.count() == 1
    assert StatutorySourceDocumentCaptureModel.objects.count() == 1


@pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])
def test_postgres_concurrent_capture_uuid_is_one_exact_replay(tmp_path: Path) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Native PostgreSQL capture-UUID insert contract")
    capture_id = uuid4()

    def append(_: int) -> str:
        try:
            store = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096)
            return (
                RetainStatutorySourceDocumentUseCase(
                    body_store=store, document_repository=_repository(tmp_path)
                )
                .execute(
                    revision=_revision(),
                    capture_id=capture_id,
                    captured_at=OBSERVED,
                    content_type="text/html",
                    body=BODY,
                )
                .disposition.value
            )
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, range(2)))
    assert sorted(results) == ["duplicate", "stored"]
    assert StatutorySourceDocumentRevisionModel.objects.count() == 1
    assert StatutorySourceDocumentCaptureModel.objects.count() == 1


@pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])
def test_postgres_unsupported_isolation_blocks_before_metadata_write(tmp_path: Path) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Native PostgreSQL isolation contract")
    repository = _repository(tmp_path)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with pytest.raises(DataValidationError) as error:
            _capture(repository, tmp_path)
        assert error.value.code == "STATUTORY_SOURCE_ISOLATION_UNSUPPORTED"
    assert StatutorySourceDocumentRevisionModel.objects.count() == 0
    assert StatutorySourceDocumentCaptureModel.objects.count() == 0

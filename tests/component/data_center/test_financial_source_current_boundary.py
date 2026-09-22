"""Actual current financial reads must preserve source proof and historical rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.data_center.application.publication_utils import publication_member_from_reference
from apps.data_center.domain.publication_evidence import validate_publication_evidence
from apps.data_center.infrastructure.financial_fact_repository import (
    FinancialFactProvenanceConflictError,
    FinancialFactRepository,
)
from apps.data_center.infrastructure.models import FinancialFactModel
from apps.data_center.infrastructure.publication_member_store import (
    add_immutable_publication_member,
    publication_fact_content_hashes,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from tests.component.data_center.test_financial_source_provenance import (
    _activate_policy3,
    _decision_projection,
    _decision_transport_extra,
)

pytestmark = pytest.mark.django_db

ANNOUNCED = datetime(2026, 9, 10, 8, tzinfo=UTC)
BODY = b'{"record_id":"source-1","announced_at":"2026-09-10T08:00:00Z","value":"123.45"}'


def _stored_row(**changes: object) -> FinancialFactModel:
    """Seed one source record with an independently hashed original test body."""

    available_at = ANNOUNCED + timedelta(minutes=5)
    decision_evidence = _decision_projection(
        source_record_id="source-1",
        announced_at=ANNOUNCED,
        available_at=available_at,
        raw_payload_hash=sha256(BODY).hexdigest(),
    )
    values: dict[str, object] = {
        "asset_code": "000001.SZ",
        "period_end": "2026-06-30",
        "period_type": "quarterly",
        "metric_code": "revenue",
        "value": "123.45",
        "unit": "CNY",
        "source": "provider-main",
        "report_date": ANNOUNCED.date(),
        "announced_at": ANNOUNCED,
        "available_at": available_at,
        "source_record_id": "source-1",
        "raw_payload_hash": sha256(BODY).hexdigest(),
        "extra": _decision_transport_extra(decision_evidence),
        "decision_evidence": decision_evidence,
    }
    values.update(changes)
    return FinancialFactModel.objects.create(**values)


def test_current_financial_source_survives_persisted_member_replay() -> None:
    """The current candidate and persisted member agree on the actual source row."""

    _activate_policy3()
    row = _stored_row()
    before = list(FinancialFactModel.objects.values())
    references = FinancialFactRepository(
        source_time_evidence_verifier=lambda _decision: True
    ).list_current_publication_candidates((row.asset_code,))
    policy = PublicationPolicyRepository().get_active("equity.financial.fact")
    assert policy is not None
    validate_publication_evidence(policy, references, published_at=row.fetched_at)
    assert references[0].source_published_at == ANNOUNCED
    member = publication_member_from_reference(
        references[0],
        member_id=str(uuid4()),
        publication_id=str(uuid4()),
        dataset_key="equity.financial.fact",
    )
    assert add_immutable_publication_member(member) == member
    assert add_immutable_publication_member(member) == member
    assert publication_fact_content_hashes((member,)) == {
        (row._meta.db_table, str(row.pk)): member.fact_content_hash
    }
    assert list(FinancialFactModel.objects.values()) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"announced_at": None},
        {"source_record_id": ""},
        {"raw_payload_hash": ""},
        {"extra": {"raw_payload_scope": "normalized_row"}},
        {"available_at": datetime(2026, 9, 10, tzinfo=UTC)},
    ],
    ids=("source-time", "source-id", "original-hash", "original-scope", "old-midnight"),
)
def test_current_financial_missing_source_proof_never_mutates_history(
    changes: dict[str, object],
) -> None:
    """Each independent source gap blocks the real current API without history DML."""

    _activate_policy3()
    row = _stored_row(**changes)
    before = list(FinancialFactModel.objects.values())
    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(
            (ValueError, FinancialFactProvenanceConflictError),
            match="financial (publication )?",
        ):
            FinancialFactRepository(
                source_time_evidence_verifier=lambda _decision: True
            ).list_current_publication_candidates((row.asset_code,))
    assert list(FinancialFactModel.objects.values()) == before
    assert all(item["sql"].lstrip().upper().startswith("SELECT") for item in queries)

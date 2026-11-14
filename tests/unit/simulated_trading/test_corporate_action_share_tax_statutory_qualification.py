"""Synthetic retained source controls do not claim real-holder legal eligibility."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from apps.data_center.application.statutory_source_bundle import ConfiguredStatutorySourceBundleRead
from apps.data_center.domain.statutory_source_catalog import (
    StatutorySourceCatalogProfile,
    StatutorySourceDocumentCaptureRule,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
)
from apps.simulated_trading import corporate_action_share_tax_policy_composition as policy
from apps.simulated_trading import corporate_action_share_tax_statutory_qualification as statutory
from apps.simulated_trading.domain.corporate_action_capital_tax_terms import (
    CapitalTaxSourceDocumentId,
)
from core.exceptions import BusinessLogicError
from tests.unit.data_center.test_statutory_source_documents import _bundle, _capture, _revision
from tests.unit.simulated_trading.test_corporate_action_share_tax_model import _NOW, _query
from tests.unit.simulated_trading.test_corporate_action_share_tax_policy_composition import (
    _install,
    _payload,
)
from tests.unit.simulated_trading.test_statutory_capital_tax_parser import (
    _NUMBER_1997,
    _NUMBER_1998,
    _TITLE_1997,
    _TITLE_1998,
    _html,
)


def _inputs(monkeypatch):
    captures = []
    bodies = {}
    pairs = (
        (CapitalTaxSourceDocumentId.SAT_1997_198, _TITLE_1997, _NUMBER_1997, "c5193235"),
        (CapitalTaxSourceDocumentId.SAT_1998_289, _TITLE_1998, _NUMBER_1998, "c5193247"),
    )
    for index, (doc, title, number, page) in enumerate(pairs, 1):
        body = _html(doc)
        native = f"synthetic-{doc.value}"
        revision = replace(
            _revision(document_id=native, body=body),
            issuer="国家税务总局",
            title=title,
            legal_number=number,
            canonical_url=f"https://fgk.chinatax.gov.cn/zcfgk/c100012/{page}/content.html",
            publication_date=StatutorySourceDateEvidence(StatutorySourceDatePrecision.UNKNOWN),
            effective_date=StatutorySourceDateEvidence(StatutorySourceDatePrecision.UNKNOWN),
        )
        captures.append(
            _capture(
                revision=revision,
                capture_id=UUID(int=index),
                captured_at=_NOW - timedelta(seconds=30),
                body=body,
            )
        )
        bodies[native] = body
    bundle = _bundle(tuple(captures))
    catalog = StatutorySourceCatalogProfile(
        profile_id="synthetic-capital-catalog",
        version="1",
        publisher_code="QA_SYNTHETIC",
        enabled=True,
        allowed_hosts=frozenset({"fgk.chinatax.gov.cn"}),
        max_capture_age_seconds=60,
        documents=tuple(
            StatutorySourceDocumentCaptureRule(c.revision, 16384, frozenset({"text/html"}))
            for c in bundle.captures
        ),
    )
    retained = ConfiguredStatutorySourceBundleRead(
        bundle,
        tuple(bodies[c.revision.document_id] for c in bundle.captures),
        7,
        catalog,
        "d" * 64,
        _NOW,
    )
    payload = _payload()
    row = payload["models"][0]
    row.update(
        statutory_bundle_id=bundle.bundle_id,
        statutory_bundle_version=bundle.version,
        statutory_source_bundle_sha256=bundle.source_bundle_sha256,
    )
    _install(monkeypatch, payload)
    configured = policy.read_current_share_capital_tax_policy(
        query=_query(), environment="test", as_of=_NOW
    )
    return configured, retained


def test_actual_retained_grammar_and_catalog_bind_to_an_explicit_simulation_only(monkeypatch):
    configured, retained = _inputs(monkeypatch)
    proof = statutory.qualify_share_capital_tax_statutory_evidence(
        query=_query(), configured=configured, retained=retained, as_of=_NOW
    )
    assert proof.source_1997_198.body_sha256 == proof.terms.source_1997_198.body_sha256
    assert proof.source_1998_289.body_sha256 == proof.terms.source_1998_289.body_sha256
    assert proof.valid_until == _NOW + timedelta(seconds=30)
    assert proof.source_observed_at == _NOW - timedelta(seconds=30)
    assert retained.must_not_use_for_decision is True
    assert proof.must_not_use_for_real_tax_decision is True
    assert (
        retained.bundle.captures[0].revision.effective_date.precision
        is StatutorySourceDatePrecision.UNKNOWN
    )


@pytest.mark.parametrize(
    "defect",
    ["bundle", "pin", "body", "expired", "future", "missing_document", "wrong_document_map"],
)
def test_unverified_or_stale_primary_pair_never_becomes_share_model_authority(monkeypatch, defect):
    configured, retained = _inputs(monkeypatch)
    cutoff = _NOW
    if defect == "bundle":
        configured = replace(configured, statutory_bundle_version="another")
    elif defect == "pin":
        configured = replace(configured, statutory_source_bundle_sha256="f" * 64)
    elif defect == "body":
        object.__setattr__(retained, "bodies", (b"changed", *retained.bodies[1:]))
    elif defect == "expired":
        cutoff += timedelta(seconds=30)
    elif defect == "future":
        cutoff -= timedelta(seconds=1)
    elif defect == "missing_document":
        object.__setattr__(retained, "bodies", retained.bodies[:1])
    else:
        configured = replace(configured, document_1997_id=configured.document_1998_id)
    with pytest.raises(BusinessLogicError):
        statutory.qualify_share_capital_tax_statutory_evidence(
            query=_query(), configured=configured, retained=retained, as_of=cutoff
        )

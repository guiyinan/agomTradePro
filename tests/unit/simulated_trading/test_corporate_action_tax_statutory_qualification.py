"""Controlled source clauses prove model binding, not current legal suitability."""

import json
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from uuid import UUID

import pytest

from apps.data_center.application.statutory_source_bundle import ConfiguredStatutorySourceBundleRead
from apps.data_center.domain.statutory_source_catalog import (
    StatutorySourceCatalogProfile,
    StatutorySourceDocumentCaptureRule,
)
from apps.data_center.domain.statutory_source_documents import _revision_payload
from apps.simulated_trading.corporate_action_tax_policy_composition import (
    ConfiguredSimulatedDividendTaxPolicy,
)
from apps.simulated_trading.corporate_action_tax_statutory_qualification import (
    qualify_simulated_dividend_tax_statutory_evidence,
)
from core.exceptions import BusinessLogicError
from tests.unit.data_center.test_statutory_source_documents import (
    _bundle,
    _capture,
    _revision,
)
from tests.unit.simulated_trading.test_corporate_action_tax_policy_composition import (
    _NOW,
    _evidence,
    _policy_row,
    _read,
    _runtime_value,
    _tax_policy_json,
)
from tests.unit.simulated_trading.test_statutory_dividend_tax_parser import (
    MECHANICS_PARAGRAPHS,
    RATE_PARAGRAPHS,
    _html,
)


def _inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ConfiguredSimulatedDividendTaxPolicy, ConfiguredStatutorySourceBundleRead]:
    """Build two retained synthetic documents and an explicit current model candidate."""

    captures = []
    bodies_by_id = {}
    for index, (number, paragraphs) in enumerate(
        (("SYNTHETIC-RATE", RATE_PARAGRAPHS), ("SYNTHETIC-MECHANICS", MECHANICS_PARAGRAPHS)),
        start=1,
    ):
        body = _html(number, paragraphs)
        revision = replace(
            _revision(document_id=number, body=body),
            legal_number=number,
            canonical_url=f"https://example.invalid/synthetic/{number}",
        )
        captures.append(
            _capture(
                revision=revision,
                capture_id=UUID(int=index),
                captured_at=_NOW - timedelta(seconds=30),
                body=body,
            )
        )
        bodies_by_id[number] = body
    bundle = _bundle(tuple(captures))
    catalog = StatutorySourceCatalogProfile(
        profile_id="synthetic-model-source",
        version="1",
        publisher_code="QA",
        enabled=True,
        allowed_hosts=frozenset({"example.invalid"}),
        max_capture_age_seconds=60,
        documents=tuple(
            StatutorySourceDocumentCaptureRule(
                revision=capture.revision,
                max_bytes=16384,
                allowed_media_types=frozenset({"text/html"}),
            )
            for capture in bundle.captures
        ),
    )
    retained = ConfiguredStatutorySourceBundleRead(
        bundle=bundle,
        bodies=tuple(bodies_by_id[c.revision.document_id] for c in bundle.captures),
        provider_id=7,
        catalog=catalog,
        configuration_sha256="d" * 64,
        checked_at=_NOW,
    )
    # Use Data Center's native codec independently of the conversion under test.
    revision_set = sha256(
        json.dumps(
            {
                "schema": "statutory-revision-set.v1",
                "revisions": [_revision_payload(c.revision) for c in bundle.captures],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    policy = _tax_policy_json(
        source_identity=f"statutory-revision-set.v1:{revision_set}",
        source_sha256=revision_set,
    )
    policy["bands"] = [
        {
            "band_id": name,
            "maximum_holding_months": months,
            "taxable_dividend_ratio": ratio,
            "withholding_rate": "0.2",
        }
        for name, months, ratio in (("short", 1, "1"), ("middle", 12, "0.5"), ("long", None, "0"))
    ]
    row = _policy_row(
        statutory_bundle_id=bundle.bundle_id,
        statutory_bundle_version=bundle.version,
        statutory_revision_set_sha256=revision_set,
        tax_policy=policy,
    )
    configured = _read(monkeypatch, _evidence(_runtime_value(rows=[row])))
    return configured, retained


def test_explicit_simulated_policy_binds_complete_retained_clauses_without_upgrading_source_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured, source = _inputs(monkeypatch)
    qualified = qualify_simulated_dividend_tax_statutory_evidence(
        configured=configured, retained=source, as_of=_NOW
    )
    assert (
        qualified.source_bundle.source_revision_set_sha256
        == configured.candidate.statutory_revision_set_sha256
    )
    assert qualified.source_bundle.source_bundle_sha256 == source.bundle.source_bundle_sha256
    assert (
        qualified.terms.withholding_rate
        == configured.candidate.tax_policy.bands[0].withholding_rate
    )
    assert qualified.source_observed_at == _NOW - timedelta(seconds=30)
    assert qualified.valid_until == _NOW + timedelta(seconds=30)
    assert qualified.must_not_use_as_real_tax_proof is True
    assert source.must_not_use_for_decision is True and source.reliability == "unqualified"


@pytest.mark.parametrize("offset", [-1, 30, 60])
def test_future_read_or_expired_original_capture_is_blocked(
    monkeypatch: pytest.MonkeyPatch, offset: int
) -> None:
    configured, source = _inputs(monkeypatch)
    with pytest.raises(BusinessLogicError):
        qualify_simulated_dividend_tax_statutory_evidence(
            configured=configured, retained=source, as_of=_NOW + timedelta(seconds=offset)
        )


def test_changed_configured_capture_set_is_not_repaired_or_selected_by_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured, source = _inputs(monkeypatch)
    wrong = replace(
        configured, candidate=replace(configured.candidate, statutory_bundle_version="other")
    )
    with pytest.raises(BusinessLogicError):
        qualify_simulated_dividend_tax_statutory_evidence(
            configured=wrong, retained=source, as_of=_NOW
        )


def test_policy_numbers_cannot_differ_from_the_retained_clauses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured, source = _inputs(monkeypatch)
    from decimal import Decimal

    policy = configured.candidate.tax_policy
    changed = replace(
        policy,
        bands=tuple(replace(band, withholding_rate=Decimal("0.18")) for band in policy.bands),
    )
    wrong = replace(configured, candidate=replace(configured.candidate, tax_policy=changed))
    with pytest.raises(BusinessLogicError):
        qualify_simulated_dividend_tax_statutory_evidence(
            configured=wrong, retained=source, as_of=_NOW
        )


def test_source_bytes_are_rechecked_after_the_original_dto_was_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured, source = _inputs(monkeypatch)
    object.__setattr__(source, "bodies", (b"changed", *source.bodies[1:]))
    with pytest.raises(BusinessLogicError):
        qualify_simulated_dividend_tax_statutory_evidence(
            configured=configured, retained=source, as_of=_NOW
        )
    assert sha256(b"changed").hexdigest() != source.bundle.captures[0].revision.body_sha256

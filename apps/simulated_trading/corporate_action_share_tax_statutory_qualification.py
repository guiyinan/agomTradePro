"""Bind exact retained capital-transfer clauses to an explicit simulation declaration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from apps.data_center.application.statutory_source_bundle import ConfiguredStatutorySourceBundleRead
from apps.data_center.domain.statutory_source_documents import (
    RetainedStatutorySourceDocumentCapture,
)
from apps.simulated_trading.application.corporate_action_share_tax_model import (
    ShareCapitalTaxModelQuery,
    ShareCapitalTaxSourceReference,
)
from apps.simulated_trading.corporate_action_share_tax_policy_composition import (
    ConfiguredShareCapitalTaxModelPolicy,
)
from apps.simulated_trading.domain.corporate_action_capital_tax_terms import (
    CapitalTaxSourceDocumentId,
    ParsedCapitalTaxSourceDocument,
    ParsedShareCapitalTaxSourceTerms,
    combine_share_capital_tax_source_terms,
)
from apps.simulated_trading.infrastructure.statutory_capital_tax_parser import (
    parse_sat_capital_tax_source_document,
)
from core.exceptions import AgomTradeProException, BusinessLogicError

_URLS = {
    CapitalTaxSourceDocumentId.SAT_1997_198: "https://fgk.chinatax.gov.cn/zcfgk/c100012/c5193235/content.html",
    CapitalTaxSourceDocumentId.SAT_1998_289: "https://fgk.chinatax.gov.cn/zcfgk/c100012/c5193247/content.html",
}


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "送转模拟模型所需的两份官方税务原文、完整条款或原始时限无法核对。",
        code="SHARE_CAPITAL_TAX_STATUTORY_EVIDENCE_UNVERIFIED",
    )


@dataclass(frozen=True, slots=True)
class ShareCapitalTaxStatutoryEvidence:
    """Parsed original clauses and capture references, with real-tax use prohibited."""

    terms: ParsedShareCapitalTaxSourceTerms
    source_1997_198: ShareCapitalTaxSourceReference
    source_1998_289: ShareCapitalTaxSourceReference
    source_configuration_sha256: str
    source_bundle_sha256: str
    capture_manifest_sha256: str
    source_observed_at: datetime
    known_at: datetime
    checked_at: datetime
    valid_until: datetime

    @property
    def must_not_use_for_real_tax_decision(self) -> Literal[True]:
        """Retain actual holder and real-tax qualification outside this model."""
        return True


def _reference(
    doc: CapitalTaxSourceDocumentId,
    capture: RetainedStatutorySourceDocumentCapture,
    parsed: ParsedCapitalTaxSourceDocument,
) -> ShareCapitalTaxSourceReference:
    native = capture.revision
    if (
        native.canonical_url != _URLS[doc]
        or native.issuer != parsed.issuer
        or native.title != parsed.title
        or native.legal_number != parsed.legal_number
        or native.body_sha256 != parsed.body_sha256
    ):
        raise _blocked()
    return ShareCapitalTaxSourceReference(
        doc,
        native.issuer,
        native.source_version,
        native.source_revision_sha256,
        native.body_sha256,
        str(capture.capture_id),
        capture.captured_at,
    )


def qualify_share_capital_tax_statutory_evidence(
    *,
    query: ShareCapitalTaxModelQuery,
    configured: ConfiguredShareCapitalTaxModelPolicy,
    retained: ConfiguredStatutorySourceBundleRead,
    as_of: datetime,
) -> ShareCapitalTaxStatutoryEvidence:
    """Recheck pinned catalog/body bytes and full clauses without inventing legal dates."""
    try:
        if (
            type(configured) is not ConfiguredShareCapitalTaxModelPolicy
            or type(retained) is not ConfiguredStatutorySourceBundleRead
        ):
            raise _blocked()
        configured.verify_for(query, as_of=as_of)
        retained.__post_init__()
        bundle = retained.bundle
        if (
            retained.checked_at > as_of
            or len(bundle.captures) != 2
            or bundle.bundle_id != configured.statutory_bundle_id
            or bundle.version != configured.statutory_bundle_version
            or bundle.source_bundle_sha256 != configured.statutory_source_bundle_sha256
        ):
            raise _blocked()
        deadline = min(
            configured.valid_until,
            *(
                capture.captured_at + timedelta(seconds=retained.catalog.max_capture_age_seconds)
                for capture in bundle.captures
            ),
        )
        if as_of >= deadline:
            raise _blocked()
        expected = (
            (CapitalTaxSourceDocumentId.SAT_1997_198, configured.document_1997_id),
            (CapitalTaxSourceDocumentId.SAT_1998_289, configured.document_1998_id),
        )
        documents: dict[CapitalTaxSourceDocumentId, ParsedCapitalTaxSourceDocument] = {}
        references: dict[CapitalTaxSourceDocumentId, ShareCapitalTaxSourceReference] = {}
        rules = {rule.revision.identity_key: rule for rule in retained.catalog.documents}
        for doc, native_id in expected:
            matches = tuple(
                (capture, body)
                for capture, body in zip(bundle.captures, retained.bodies, strict=True)
                if capture.revision.document_id == native_id
            )
            if len(matches) != 1:
                raise _blocked()
            capture, body = matches[0]
            capture.__post_init__()
            capture.revision.__post_init__()
            rule = rules.get(capture.revision.identity_key)
            if rule is None:
                raise _blocked()
            parsed = parse_sat_capital_tax_source_document(
                body, expected_document_id=doc, max_body_bytes=rule.max_bytes
            )
            references[doc] = _reference(doc, capture, parsed)
            documents[doc] = parsed
        first, second = (
            CapitalTaxSourceDocumentId.SAT_1997_198,
            CapitalTaxSourceDocumentId.SAT_1998_289,
        )
        if references[first].capture_id == references[second].capture_id:
            raise _blocked()
        terms = combine_share_capital_tax_source_terms(
            source_1997_198=documents[first], source_1998_289=documents[second]
        )
        return ShareCapitalTaxStatutoryEvidence(
            terms,
            references[first],
            references[second],
            retained.configuration_sha256,
            bundle.source_bundle_sha256,
            bundle.capture_manifest_sha256,
            retained.source_observed_at,
            max(capture.captured_at for capture in bundle.captures),
            as_of,
            deadline,
        )
    except BusinessLogicError:
        raise
    except (AgomTradeProException, ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise _blocked() from error

"""Read exact local risk-input manifests from Data Center's retained raw store."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime
from decimal import InvalidOperation
from typing import Literal, cast

from django.db import DatabaseError

from apps.data_center.application import raw_landing_public
from apps.risk_center.application.portfolio_risk_assets import (
    CloseSnapshotSessionEvidence,
    PortfolioRiskAssetIdentity,
    PortfolioRiskAssetInputs,
    PortfolioRiskAssetsReadRequest,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_close_snapshot_state_clock import (
    qualify_policy_bounded_close_snapshot_state,
)
from apps.risk_center.application.portfolio_risk_date_snapshot_clock import (
    PortfolioRiskClockEvidenceMode,
    qualify_policy_bounded_industry_date_snapshot,
)
from apps.risk_center.application.portfolio_risk_policy import (
    PortfolioRiskSourceReference,
)
from apps.risk_center.application.portfolio_risk_source_codec import (
    decode_portfolio_risk_source_evidence,
)
from apps.risk_center.application.portfolio_risk_timestamp_snapshot_clock import (
    PortfolioRiskTimestampSnapshotFacts,
    qualify_policy_bounded_timestamp_snapshot,
)
from apps.risk_center.domain.portfolio_capacity import CapacityWindowObservation
from apps.risk_center.domain.portfolio_exposure_types import (
    ETFConstituentKind,
    ETFConstituentReport,
    IndustryMembership,
    PortfolioAssetKind,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import (
    PortfolioRiskCaptureReceipt,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)
from apps.risk_center.infrastructure.portfolio_risk_assets_manifest import (
    _CAPTURE_RECEIPT_KEYS,
    _CAPTURE_RECEIPT_MANIFEST_KEYS,
    _CAPTURE_RECEIPT_MANIFEST_SCHEMA,
    _CAPTURE_RECEIPT_PARSER_VERSION,
    _DATASET_KEY,
    _MANIFEST_KEYS,
    _MANIFEST_SCHEMA,
    _PARSER_VERSION,
    _SOURCE_KIND_VALUES,
    _AssetKey,
    _capacity_observation_from_sources,
    _CapacityWindowFacts,
    _decode_original_body,
    _etf_report_from_source,
    _ETFReportFacts,
    _ExecutionSessionStateFacts,
    _LoadedSource,
    _manifest_payload_hash,
    _membership_from_source,
    _optional_string,
    _parse_facts,
    _policy_source_rules,
    _ReferenceKey,
    _require_exact_keys,
    _require_mapping,
    _required_string,
    _required_token,
    _source_age_reason,
    _SourceKind,
    _SourceRead,
    _validate_json_source_clock_types,
    _ValuationFacts,
)
from apps.risk_center.infrastructure.portfolio_risk_sina_capture_manifest import (
    rebuild_sina_quote_capture_from_manifest,
)
from core.exceptions import AgomTradeProException


class RetainedPortfolioRiskAssetsReader:
    """Read only exact retained manifest hashes named by the active policy."""

    def read_assets(
        self,
        request: PortfolioRiskAssetsReadRequest,
    ) -> PortfolioRiskAssetsReadResult:
        """Read and qualify every pinned input without fetching or substituting sources."""

        if type(request) is not PortfolioRiskAssetsReadRequest:
            return _result(
                status="blocked",
                reason_codes=("RISK_INPUT_REQUEST_INVALID",),
            )
        policy = request.policy
        if request.as_of != policy.as_of or request.business_date != policy.business_date:
            return _result(
                status="blocked",
                reason_codes=("RISK_INPUT_POLICY_CUTOFF_MISMATCH",),
                policy_snapshot_id=policy.snapshot_id,
                policy_snapshot_hash=policy.snapshot_hash,
            )

        policy_references = tuple(
            sorted(
                policy.source_references,
                key=lambda item: (item.kind, item.asset_code, item.security_id),
            )
        )
        keys = tuple((ref.kind, ref.asset_code, ref.security_id) for ref in policy_references)
        if len(set(keys)) != len(keys):
            return _result(
                status="blocked",
                reason_codes=("RISK_INPUT_POLICY_SOURCE_REFERENCES_INVALID",),
                policy_snapshot_id=policy.snapshot_id,
                policy_snapshot_hash=policy.snapshot_hash,
            )

        resolved_asset_keys, unresolved_assets, identity_reasons = _resolve_requested_assets(
            request.requested_assets,
            policy_references,
        )
        reasons: list[str] = list(identity_reasons)
        has_blocker = bool(identity_reasons)
        has_partial = False
        requested_keys = set(resolved_asset_keys)
        candidate_references = tuple(
            ref for ref in policy_references if (ref.asset_code, ref.security_id) in requested_keys
        )
        reads: dict[_ReferenceKey, _LoadedSource] = {}
        all_evidence: list[PortfolioRiskSourceEvidence] = []
        valuation_references = tuple(
            reference for reference in candidate_references if reference.kind == "valuation"
        )
        for reference in valuation_references:
            source_read = self._read_reference(reference, request)
            reasons.extend(source_read.reason_codes)
            has_blocker = has_blocker or source_read.blocked
            has_partial = has_partial or source_read.partial
            if source_read.source is not None:
                key = (reference.kind, reference.asset_code, reference.security_id)
                reads[key] = source_read.source
                all_evidence.append(source_read.source.evidence)

        requested_kinds: dict[_AssetKey, PortfolioAssetKind | None] = {}
        for asset_code, security_id in requested_keys:
            valuation = reads.get(("valuation", asset_code, security_id))
            facts = valuation.facts if valuation is not None else None
            requested_kinds[(asset_code, security_id)] = (
                facts.asset_kind if isinstance(facts, _ValuationFacts) else None
            )
        references_list: list[PortfolioRiskSourceReference] = list(valuation_references)
        for reference in candidate_references:
            if reference.kind == "valuation":
                continue
            if (
                reference.kind == "industry_membership"
                and requested_kinds.get((reference.asset_code, reference.security_id))
                is not PortfolioAssetKind.EQUITY
            ):
                continue
            references_list.append(reference)
        references = tuple(references_list)
        loaded_keys = {
            (reference.kind, reference.asset_code, reference.security_id)
            for reference in valuation_references
        }
        for reference in references:
            key = (reference.kind, reference.asset_code, reference.security_id)
            if key in loaded_keys:
                continue
            source_read = self._read_reference(reference, request)
            reasons.extend(source_read.reason_codes)
            has_blocker = has_blocker or source_read.blocked
            has_partial = has_partial or source_read.partial
            if source_read.source is not None:
                reads[key] = source_read.source
                all_evidence.append(source_read.source.evidence)
            loaded_keys.add(key)

        closure_references: list[PortfolioRiskSourceReference] = []
        for reference in references:
            if reference.kind != "etf_report":
                continue
            source = reads.get((reference.kind, reference.asset_code, reference.security_id))
            if source is None or not isinstance(source.facts, _ETFReportFacts):
                continue
            for constituent in source.facts.constituents:
                if constituent.kind is not ETFConstituentKind.EQUITY:
                    continue
                matches = tuple(
                    candidate
                    for candidate in policy_references
                    if candidate.kind == "industry_membership"
                    and candidate.asset_code == constituent.asset_code
                )
                if not matches:
                    reasons.append("RISK_INPUT_ETF_CONSTITUENT_INDUSTRY_REFERENCE_MISSING")
                    has_partial = True
                    continue
                if len(matches) != 1:
                    reasons.append("RISK_INPUT_ETF_CONSTITUENT_INDUSTRY_REFERENCE_AMBIGUOUS")
                    has_blocker = True
                    continue
                closure_references.append(matches[0])

        selected_reference_keys = {
            (ref.kind, ref.asset_code, ref.security_id) for ref in references
        }
        for reference in closure_references:
            key = (reference.kind, reference.asset_code, reference.security_id)
            if key in selected_reference_keys:
                continue
            selected_reference_keys.add(key)
            source_read = self._read_reference(reference, request)
            reasons.extend(source_read.reason_codes)
            has_blocker = has_blocker or source_read.blocked
            has_partial = has_partial or source_read.partial
            if source_read.source is not None:
                reads[key] = source_read.source
                all_evidence.append(source_read.source.evidence)
        selected_by_key = {
            (ref.kind, ref.asset_code, ref.security_id): ref
            for ref in (*references, *closure_references)
        }
        selected_references = tuple(
            sorted(
                selected_by_key.values(),
                key=lambda item: (item.kind, item.asset_code, item.security_id),
            )
        )

        memberships: dict[_AssetKey, IndustryMembership | None] = {}
        for reference in selected_references:
            if reference.kind != "industry_membership":
                continue
            key = (reference.kind, reference.asset_code, reference.security_id)
            source = reads.get(key)
            membership = _membership_from_source(source, reasons)
            memberships[(reference.asset_code, reference.security_id)] = membership

        assets: list[PortfolioRiskAssetInputs] = []
        reference_keys = {
            (ref.kind, ref.asset_code, ref.security_id) for ref in selected_references
        }
        for unresolved in unresolved_assets:
            assets.append(
                PortfolioRiskAssetInputs(
                    asset_code=unresolved.asset_code,
                    security_id=None,
                    kind=None,
                    price=None,
                    quantity_unit=None,
                    price_unit=None,
                    valuation_evidence=None,
                    industry_membership=None,
                    etf_report=None,
                    capacity_observation=None,
                )
            )
        for asset_code, security_id in sorted(requested_keys):
            asset_key = (asset_code, security_id)
            valuation_key = ("valuation", asset_code, security_id)
            membership_key = ("industry_membership", asset_code, security_id)
            etf_key = ("etf_report", asset_code, security_id)
            capacity_key = ("capacity_window", asset_code, security_id)
            state_key = ("execution_session_state", asset_code, security_id)

            valuation_source = reads.get(valuation_key)
            valuation_facts = (
                valuation_source.facts
                if valuation_source is not None
                and isinstance(valuation_source.facts, _ValuationFacts)
                else None
            )
            if valuation_key not in reference_keys:
                reasons.append("RISK_INPUT_VALUATION_REFERENCE_MISSING")
                has_partial = True
            if valuation_facts is None and valuation_source is not None:
                reasons.append("RISK_INPUT_VALUATION_FACTS_UNKNOWN")
                has_partial = True
            if valuation_facts is not None:
                if valuation_facts.price is None:
                    reasons.append("RISK_INPUT_VALUATION_PRICE_UNKNOWN")
                    has_partial = True
                if valuation_facts.asset_kind is None:
                    reasons.append("RISK_INPUT_ASSET_KIND_UNKNOWN")
                    has_partial = True
                if valuation_facts.quantity_unit is None or valuation_facts.price_unit is None:
                    reasons.append("RISK_INPUT_VALUATION_UNIT_UNKNOWN")
                    has_partial = True
                if (
                    valuation_facts.price_unit is not None
                    and valuation_facts.price_unit != policy.ledger_money_unit
                ):
                    reasons.append("RISK_INPUT_VALUATION_PRICE_UNIT_MISMATCH")
                    has_blocker = True

            kind = valuation_facts.asset_kind if valuation_facts is not None else None
            if kind is None:
                reasons.append("RISK_INPUT_ASSET_KIND_UNKNOWN")
                has_partial = True
            membership = memberships.get(asset_key)
            membership_reference_exists = membership_key in reference_keys
            if kind is PortfolioAssetKind.EQUITY and not membership_reference_exists:
                reasons.append("RISK_INPUT_INDUSTRY_MEMBERSHIP_REFERENCE_MISSING")
                has_partial = True
            if kind is PortfolioAssetKind.ETF and membership_reference_exists:
                reasons.append("RISK_INPUT_ETF_ISSUER_MEMBERSHIP_NOT_USED")
                has_partial = True
                membership = None

            report_source = reads.get(etf_key)
            report_facts = (
                report_source.facts
                if report_source is not None and isinstance(report_source.facts, _ETFReportFacts)
                else None
            )
            report: ETFConstituentReport | None = None
            if kind is PortfolioAssetKind.ETF and etf_key not in reference_keys:
                reasons.append("RISK_INPUT_ETF_REPORT_REFERENCE_MISSING")
                has_partial = True
            if report_source is not None and report_facts is not None:
                report, report_reasons, report_blocked = _etf_report_from_source(
                    source=report_source,
                    facts=report_facts,
                    references=selected_references,
                    memberships=memberships,
                )
                reasons.extend(report_reasons)
                has_blocker = has_blocker or report_blocked
                has_partial = has_partial or bool(report_reasons) and not report_blocked

            capacity_source = reads.get(capacity_key)
            capacity_facts = (
                capacity_source.facts
                if capacity_source is not None
                and isinstance(capacity_source.facts, _CapacityWindowFacts)
                else None
            )
            state_source = reads.get(state_key)
            state_facts = (
                state_source.facts
                if state_source is not None
                and isinstance(state_source.facts, _ExecutionSessionStateFacts)
                else None
            )
            capacity_observation: CapacityWindowObservation | None = None
            if capacity_source is not None and capacity_facts is not None and security_id:
                capacity_observation, capacity_reasons, capacity_blocked = (
                    _capacity_observation_from_sources(
                        asset_code=asset_code,
                        security_id=security_id,
                        facts=capacity_facts,
                        window_source=capacity_source,
                        state_source=state_source,
                        state_facts=state_facts,
                        request=request,
                        quantity_unit=(
                            valuation_facts.quantity_unit if valuation_facts is not None else None
                        ),
                        ledger_money_unit=policy.ledger_money_unit,
                        capacity_measure=policy.capacity_policy.measure,
                        capacity_unit=policy.capacity_policy.unit,
                    )
                )
                reasons.extend(capacity_reasons)
                has_blocker = has_blocker or capacity_blocked
                has_partial = has_partial or bool(capacity_reasons) and not capacity_blocked

            if kind is PortfolioAssetKind.EQUITY and report is not None:
                reasons.append("RISK_INPUT_EQUITY_HAS_ETF_REPORT")
                report = None
                has_partial = True

            assets.append(
                PortfolioRiskAssetInputs(
                    asset_code=asset_code,
                    security_id=security_id,
                    kind=kind,
                    price=valuation_facts.price if valuation_facts is not None else None,
                    quantity_unit=(
                        valuation_facts.quantity_unit if valuation_facts is not None else None
                    ),
                    price_unit=valuation_facts.price_unit if valuation_facts is not None else None,
                    valuation_evidence=(
                        valuation_source.evidence if valuation_source is not None else None
                    ),
                    industry_membership=membership,
                    etf_report=report,
                    capacity_observation=capacity_observation,
                )
            )

        unique_reasons = tuple(sorted(set(reasons)))
        status: Literal["complete", "partial", "blocked"] = (
            "blocked" if has_blocker else "partial" if has_partial or unique_reasons else "complete"
        )
        return _result(
            status=status,
            assets=tuple(assets),
            all_source_evidence=tuple(
                sorted(
                    all_evidence,
                    key=lambda item: (
                        item.source_id,
                        item.source_record_id,
                        item.original_payload_sha256 or "",
                    ),
                )
            ),
            reason_codes=unique_reasons,
            policy_snapshot_id=policy.snapshot_id,
            policy_snapshot_hash=policy.snapshot_hash,
            source_reference_bindings=tuple(
                sorted(
                    (source.reference for source in reads.values()),
                    key=lambda item: (item.kind, item.asset_code, item.security_id),
                )
            ),
        )

    def _read_reference(
        self,
        reference: PortfolioRiskSourceReference,
        request: PortfolioRiskAssetsReadRequest,
    ) -> _SourceRead:
        try:
            retained = raw_landing_public.get_retained_raw_payload(
                payload_hash=reference.raw_payload_hash,
            )
        except (
            AgomTradeProException,
            AttributeError,
            DatabaseError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return _SourceRead(
                source=None,
                reason_codes=("RISK_INPUT_RETAINED_PAYLOAD_READ_FAILED",),
                blocked=True,
                partial=False,
            )
        if retained is None:
            return _SourceRead(
                source=None,
                reason_codes=("RISK_INPUT_RETAINED_PAYLOAD_MISSING",),
                blocked=False,
                partial=True,
            )
        if (
            retained.dataset_key != _DATASET_KEY
            or retained.parser_version
            not in (
                _PARSER_VERSION,
                _CAPTURE_RECEIPT_PARSER_VERSION,
            )
            or retained.content_type != "application/json"
            or retained.redacted is not True
        ):
            return _SourceRead(
                source=None,
                reason_codes=("RISK_INPUT_MANIFEST_CONTRACT_INVALID",),
                blocked=True,
                partial=False,
            )
        capture_schema = retained.parser_version == _CAPTURE_RECEIPT_PARSER_VERSION
        if (
            reference.clock_evidence_mode
            in (
                PortfolioRiskClockEvidenceMode.POLICY_BOUNDED_DATE_SNAPSHOT.value,
                PortfolioRiskClockEvidenceMode.POLICY_BOUNDED_TIMESTAMP_SNAPSHOT.value,
                PortfolioRiskClockEvidenceMode.POLICY_BOUNDED_CLOSE_SNAPSHOT_STATE.value,
            )
            and not capture_schema
        ):
            return _SourceRead(
                source=None,
                reason_codes=("RISK_INPUT_CAPTURE_RECEIPT_REQUIRED",),
                blocked=True,
                partial=False,
            )
        try:
            payload = _require_mapping(retained.payload, "retained payload")
            manifest_hash = _manifest_payload_hash(payload)
        except (TypeError, ValueError, OverflowError):
            return _SourceRead(
                source=None,
                reason_codes=("RISK_INPUT_MANIFEST_CONTRACT_INVALID",),
                blocked=True,
                partial=False,
            )
        if (
            retained.payload_hash != reference.raw_payload_hash
            or manifest_hash != retained.payload_hash
        ):
            return _SourceRead(
                source=None,
                reason_codes=("RISK_INPUT_MANIFEST_HASH_MISMATCH",),
                blocked=True,
                partial=False,
            )
        try:
            expected_keys = _CAPTURE_RECEIPT_MANIFEST_KEYS if capture_schema else _MANIFEST_KEYS
            _require_exact_keys(payload, expected_keys, "manifest")
            schema_version = _required_token(payload["schema_version"], "schema_version")
            expected_schema = (
                _CAPTURE_RECEIPT_MANIFEST_SCHEMA if capture_schema else _MANIFEST_SCHEMA
            )
            if schema_version != expected_schema:
                raise ValueError("manifest schema_version is unsupported")
            kind = _required_token(payload["kind"], "kind")
            if kind != reference.kind or kind not in _SOURCE_KIND_VALUES:
                raise ValueError("manifest kind does not match its policy reference")
            if _required_token(payload["asset_code"], "asset_code") != reference.asset_code:
                raise ValueError("manifest asset_code does not match its policy reference")
            if _required_token(payload["security_id"], "security_id") != reference.security_id:
                raise ValueError("manifest security_id does not match its policy reference")
            if _required_token(payload["source_record_id"], "source_record_id") != (
                reference.source_record_id
            ):
                raise ValueError("manifest source_record_id does not match its policy reference")
            original_url = _optional_string(payload["original_url"], "original_url")
            body_text = _required_string(payload["original_body_base64"], "original_body_base64")
            original_body = _decode_original_body(body_text)
            evidence_mapping = _require_mapping(payload["source_evidence"], "source_evidence")
            precision_text = _required_token(
                evidence_mapping.get("observation_precision"),
                "source_evidence.observation_precision",
            )
            date_cutoff = request.business_date if precision_text == "date" else None
            _validate_json_source_clock_types(evidence_mapping)
            evidence = decode_portfolio_risk_source_evidence(
                evidence_mapping,
                decision_cutoff=request.as_of,
                decision_date_cutoff=date_cutoff,
            )
            if evidence.source_record_id != reference.source_record_id:
                raise ValueError("source evidence record id does not match its policy reference")
            receipt = (
                _capture_receipt_from_manifest(payload["capture_receipt"])
                if capture_schema
                else None
            )
            sina_capture = (
                rebuild_sina_quote_capture_from_manifest(
                    payload["sina_capture_metadata"],
                    asset_code=reference.asset_code,
                    original_url=original_url,
                    original_body=original_body,
                    receipt=receipt,
                )
                if capture_schema and payload["sina_capture_metadata"] is not None
                else None
            )
        except (TypeError, ValueError, InvalidOperation, OverflowError):
            return _SourceRead(
                source=None,
                reason_codes=("RISK_INPUT_MANIFEST_CONTRACT_INVALID",),
                blocked=True,
                partial=False,
            )

        expected_original_hash = evidence.original_payload_sha256
        computed_original_hash = hashlib.sha256(original_body).hexdigest()
        integrity_reasons: list[str] = []
        if expected_original_hash is None:
            integrity_reasons.append("RISK_INPUT_ORIGINAL_BODY_HASH_UNKNOWN")
        elif expected_original_hash != computed_original_hash:
            return _SourceRead(
                source=None,
                reason_codes=("RISK_INPUT_ORIGINAL_BODY_HASH_MISMATCH",),
                blocked=True,
                partial=False,
            )

        try:
            facts = _parse_facts(cast(_SourceKind, kind), payload["facts"])
        except (TypeError, ValueError, InvalidOperation, OverflowError):
            return _SourceRead(
                source=None,
                reason_codes=("RISK_INPUT_FACTS_INVALID",),
                blocked=True,
                partial=False,
            )

        source = _LoadedSource(
            reference=reference,
            evidence=evidence,
            original_url=original_url,
            facts=facts,
            sina_capture=sina_capture,
        )
        requested_purpose, precisions, date_purposes, restrictions = _policy_source_rules(
            request.policy,
            cast(_SourceKind, kind),
            request.capacity_requested_purpose,
        )
        clock_reason_codes: tuple[str, ...] = ()
        if (
            reference.clock_evidence_mode
            == PortfolioRiskClockEvidenceMode.POLICY_BOUNDED_DATE_SNAPSHOT.value
        ):
            membership_reasons: list[str] = []
            membership = _membership_from_source(source, membership_reasons)
            if membership is None:
                clock_reason_codes = tuple(
                    dict.fromkeys(
                        (
                            "PORTFOLIO_RISK_DATE_SNAPSHOT_MEMBERSHIP_INVALID",
                            *membership_reasons,
                        )
                    )
                )
            elif (
                request.account_id is None
                or request.business_timezone is None
                or request.business_timezone_name is None
            ):
                clock_reason_codes = ("PORTFOLIO_RISK_DATE_SNAPSHOT_CONTEXT_UNKNOWN",)
            elif receipt is None or receipt.response_completed_at != retained.fetched_at:
                clock_reason_codes = ("PORTFOLIO_RISK_DATE_SNAPSHOT_CAPTURE_TIME_MISMATCH",)
            else:
                date_clock_result = qualify_policy_bounded_industry_date_snapshot(
                    clock_evidence_mode=PortfolioRiskClockEvidenceMode(
                        reference.clock_evidence_mode
                    ),
                    policy=request.policy,
                    source_reference=reference,
                    retained_payload_hash=retained.payload_hash,
                    account_id=request.account_id,
                    asset_code=reference.asset_code,
                    security_id=reference.security_id,
                    membership=membership,
                    receipt=receipt,
                    original_body=original_body,
                    as_of=request.as_of,
                    business_date=request.business_date,
                    business_timezone=request.business_timezone,
                    business_timezone_name=request.business_timezone_name,
                )
                clock_reason_codes = date_clock_result.reason_codes
                if date_clock_result.proof is not None:
                    evidence = replace(
                        evidence,
                        policy_clock_proof=date_clock_result.proof.to_domain(),
                    )
                    source = replace(source, evidence=evidence)
        elif (
            reference.clock_evidence_mode
            == PortfolioRiskClockEvidenceMode.POLICY_BOUNDED_TIMESTAMP_SNAPSHOT.value
        ):
            if (
                request.account_id is None
                or request.business_timezone is None
                or request.business_timezone_name is None
            ):
                clock_reason_codes = ("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_CONTEXT_UNKNOWN",)
            elif receipt is None or receipt.response_completed_at != retained.fetched_at:
                clock_reason_codes = ("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_CAPTURE_TIME_MISMATCH",)
            else:
                timestamp_facts: PortfolioRiskTimestampSnapshotFacts | None = None
                if kind == "valuation" and isinstance(facts, _ValuationFacts):
                    timestamp_facts = PortfolioRiskTimestampSnapshotFacts(
                        source_kind="valuation",
                        valuation_price=facts.price,
                        valuation_quantity_unit=facts.quantity_unit,
                        valuation_price_unit=facts.price_unit,
                    )
                elif kind == "capacity_window" and isinstance(facts, _CapacityWindowFacts):
                    measure = request.policy.capacity_policy.measure
                    timestamp_facts = PortfolioRiskTimestampSnapshotFacts(
                        source_kind="capacity_window",
                        capacity_window_kind=facts.window_kind,
                        capacity_window_start=facts.start,
                        capacity_window_end=facts.end,
                        capacity_window_sessions=facts.sessions,
                        capacity_volume_value=facts.volume.value,
                        capacity_volume_unit=facts.volume.unit,
                        capacity_amount_value=facts.amount.value,
                        capacity_amount_unit=facts.amount.unit,
                        capacity_measure=measure,
                        capacity_policy_unit=request.policy.capacity_policy.unit,
                    )
                if timestamp_facts is None:
                    clock_reason_codes = ("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_FACTS_UNKNOWN",)
                else:
                    timestamp_clock_result = qualify_policy_bounded_timestamp_snapshot(
                        policy=request.policy,
                        source_reference=reference,
                        retained_payload_hash=retained.payload_hash,
                        account_id=request.account_id,
                        source_evidence=evidence,
                        facts=timestamp_facts,
                        receipt=receipt,
                        original_body=original_body,
                        as_of=request.as_of,
                        business_date=request.business_date,
                        execution_session=request.execution_session,
                        requested_purpose=requested_purpose,
                        asset_code=reference.asset_code,
                        security_id=reference.security_id,
                        business_timezone=request.business_timezone,
                        business_timezone_name=request.business_timezone_name,
                    )
                    clock_reason_codes = timestamp_clock_result.reason_codes
                    if timestamp_clock_result.proof is not None:
                        evidence = replace(
                            evidence, policy_clock_proof=timestamp_clock_result.proof
                        )
                        source = replace(source, evidence=evidence)
        elif (
            reference.clock_evidence_mode
            == PortfolioRiskClockEvidenceMode.POLICY_BOUNDED_CLOSE_SNAPSHOT_STATE.value
        ):
            if request.account_id is None:
                clock_reason_codes = ("PORTFOLIO_RISK_CLOSE_STATE_ACCOUNT_UNKNOWN",)
            elif receipt is None or receipt.response_completed_at != retained.fetched_at:
                clock_reason_codes = ("PORTFOLIO_RISK_CLOSE_STATE_CAPTURE_TIME_MISMATCH",)
            elif (
                not isinstance(facts, _ExecutionSessionStateFacts)
                or facts.session_date != request.execution_session
                or facts.suspended is not None
            ):
                clock_reason_codes = ("PORTFOLIO_RISK_CLOSE_STATE_FACTS_INVALID",)
            elif source.sina_capture is None:
                clock_reason_codes = ("PORTFOLIO_RISK_CLOSE_STATE_SINA_CAPTURE_METADATA_REQUIRED",)
            elif request.close_snapshot_session_provider is None:
                clock_reason_codes = ("PORTFOLIO_RISK_CLOSE_STATE_PROVIDER_UNAVAILABLE",)
            else:
                try:
                    session_evidence = request.close_snapshot_session_provider.read_evidence(
                        capture=source.sina_capture,
                        source_reference=reference,
                        receipt=receipt,
                        retained_payload_hash=retained.payload_hash,
                        account_id=request.account_id,
                        asset_code=reference.asset_code,
                        security_id=reference.security_id,
                        trading_date=request.execution_session,
                        as_of=request.as_of,
                    )
                except (AgomTradeProException, DatabaseError, TypeError, ValueError):
                    session_evidence = None
                    clock_reason_codes = ("PORTFOLIO_RISK_CLOSE_STATE_PROVIDER_READ_FAILED",)
                if session_evidence is None:
                    if not clock_reason_codes:
                        clock_reason_codes = ("PORTFOLIO_RISK_CLOSE_STATE_EVALUATION_MISSING",)
                elif type(session_evidence) is not CloseSnapshotSessionEvidence:
                    clock_reason_codes = ("PORTFOLIO_RISK_CLOSE_STATE_EVALUATION_INVALID",)
                else:
                    close_result = qualify_policy_bounded_close_snapshot_state(
                        policy=request.policy,
                        source_reference=reference,
                        retained_payload_hash=retained.payload_hash,
                        account_id=request.account_id,
                        source_evidence=evidence,
                        receipt=receipt,
                        original_body=original_body,
                        source_capture=source.sina_capture,
                        session_evidence=session_evidence,
                        as_of=request.as_of,
                        business_date=request.business_date,
                        execution_session=request.execution_session,
                        requested_purpose=requested_purpose,
                    )
                    clock_reason_codes = close_result.reason_codes
                    if close_result.proof is not None:
                        evidence = replace(evidence, policy_clock_proof=close_result.proof)
                        source = replace(source, evidence=evidence)

        qualification = qualify_portfolio_risk_source(
            evidence=evidence,
            requested_purpose=requested_purpose,
            allowed_observation_precisions=precisions,
            as_of=request.as_of,
            allowed_restrictions=restrictions,
            expected_source_kind=(
                reference.kind
                if reference.clock_evidence_mode
                in (
                    PortfolioRiskClockEvidenceMode.POLICY_BOUNDED_DATE_SNAPSHOT.value,
                    PortfolioRiskClockEvidenceMode.POLICY_BOUNDED_TIMESTAMP_SNAPSHOT.value,
                    PortfolioRiskClockEvidenceMode.POLICY_BOUNDED_CLOSE_SNAPSHOT_STATE.value,
                )
                else None
            ),
        )
        qualification_reasons = [*qualification.reason_codes, *clock_reason_codes]
        if (
            evidence.observation_precision is SourceObservationPrecision.DATE
            and requested_purpose not in date_purposes
        ):
            qualification_reasons.append("RISK_INPUT_DATE_PRECISION_PURPOSE_NOT_ALLOWED")
        age_reason = _source_age_reason(evidence, request)
        if age_reason is not None:
            qualification_reasons.append(age_reason)
        coverage_reasons: list[str] = []
        if evidence.coverage.status is CoverageStatus.PARTIAL:
            coverage_reasons.append("RISK_INPUT_SOURCE_COVERAGE_PARTIAL")
        elif evidence.coverage.status is CoverageStatus.UNKNOWN:
            coverage_reasons.append("RISK_INPUT_SOURCE_COVERAGE_UNKNOWN")
        all_reasons = tuple(
            dict.fromkeys((*integrity_reasons, *qualification_reasons, *coverage_reasons))
        )
        is_blocked = bool(integrity_reasons or qualification_reasons)
        return _SourceRead(
            source=source,
            reason_codes=all_reasons,
            blocked=is_blocked,
            partial=bool(coverage_reasons),
        )


def _capture_receipt_from_manifest(value: object) -> PortfolioRiskCaptureReceipt:
    """Decode the exact transport receipt without converting it into a source clock."""

    mapping = _require_mapping(value, "capture_receipt")
    _require_exact_keys(mapping, _CAPTURE_RECEIPT_KEYS, "capture_receipt")
    timestamp_text = _required_string(
        mapping["response_completed_at"], "capture_receipt.response_completed_at"
    )
    try:
        response_completed_at = datetime.fromisoformat(timestamp_text)
    except ValueError as exc:
        raise ValueError("capture receipt completion time must be an ISO timestamp") from exc
    if response_completed_at.tzinfo is None or response_completed_at.utcoffset() is None:
        raise ValueError("capture receipt completion time must retain its timezone")
    http_status = mapping["http_status"]
    body_size_bytes = mapping["body_size_bytes"]
    body_complete = mapping["body_complete"]
    if type(http_status) is not int:
        raise TypeError("capture receipt http_status must be an exact integer")
    if type(body_size_bytes) is not int:
        raise TypeError("capture receipt body_size_bytes must be an exact integer")
    if type(body_complete) is not bool:
        raise TypeError("capture receipt body_complete must be an exact boolean")
    return PortfolioRiskCaptureReceipt(
        capture_id=_required_token(mapping["capture_id"], "capture_receipt.capture_id"),
        source_id=_required_token(mapping["source_id"], "capture_receipt.source_id"),
        source_record_id=_required_token(
            mapping["source_record_id"], "capture_receipt.source_record_id"
        ),
        original_body_sha256=_required_token(
            mapping["original_body_sha256"], "capture_receipt.original_body_sha256"
        ),
        response_completed_at=response_completed_at,
        http_status=http_status,
        body_size_bytes=body_size_bytes,
        body_complete=body_complete,
    )


def _resolve_requested_assets(
    requested_assets: tuple[PortfolioRiskAssetIdentity, ...],
    references: tuple[PortfolioRiskSourceReference, ...],
) -> tuple[
    tuple[_AssetKey, ...],
    tuple[PortfolioRiskAssetIdentity, ...],
    tuple[str, ...],
]:
    """Resolve only missing ledger IDs through one explicit valuation pin."""

    resolved: list[_AssetKey] = []
    unresolved: list[PortfolioRiskAssetIdentity] = []
    reasons: list[str] = []
    for requested in requested_assets:
        asset_references = tuple(
            reference for reference in references if reference.asset_code == requested.asset_code
        )
        valuation_references = tuple(
            reference for reference in asset_references if reference.kind == "valuation"
        )
        if requested.security_id is None:
            if not valuation_references:
                reasons.append("RISK_INPUT_LEDGER_SECURITY_ID_UNMAPPED")
                unresolved.append(requested)
                continue
            if len(valuation_references) != 1:
                reasons.append("RISK_INPUT_LEDGER_SECURITY_ID_AMBIGUOUS")
                unresolved.append(requested)
                continue
            selected_security_id = valuation_references[0].security_id
            if any(reference.security_id != selected_security_id for reference in asset_references):
                reasons.append("RISK_INPUT_ASSET_SECURITY_REFERENCE_CONFLICT")
                unresolved.append(requested)
                continue
        else:
            selected_security_id = requested.security_id
            if any(reference.security_id != selected_security_id for reference in asset_references):
                reasons.append("RISK_INPUT_ASSET_SECURITY_REFERENCE_CONFLICT")
                unresolved.append(requested)
                continue
            if len(valuation_references) > 1:
                reasons.append("RISK_INPUT_VALUATION_REFERENCE_AMBIGUOUS")
                unresolved.append(requested)
                continue
            if valuation_references and (
                valuation_references[0].security_id != selected_security_id
            ):
                reasons.append("RISK_INPUT_VALUATION_REFERENCE_CONFLICT")
                unresolved.append(requested)
                continue
        resolved.append((requested.asset_code, selected_security_id))

    unique_resolved = set(resolved)
    return (
        tuple(sorted(unique_resolved)),
        tuple(unresolved),
        tuple(sorted(set(reasons))),
    )


def _result(
    *,
    status: Literal["complete", "partial", "blocked"],
    assets: tuple[PortfolioRiskAssetInputs, ...] = (),
    all_source_evidence: tuple[PortfolioRiskSourceEvidence, ...] = (),
    reason_codes: tuple[str, ...],
    policy_snapshot_id: str | None = None,
    policy_snapshot_hash: str | None = None,
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...] = (),
) -> PortfolioRiskAssetsReadResult:
    return PortfolioRiskAssetsReadResult(
        status=status,
        assets=assets,
        all_source_evidence=all_source_evidence,
        reason_codes=reason_codes,
        policy_snapshot_id=policy_snapshot_id,
        policy_snapshot_hash=policy_snapshot_hash,
        source_reference_bindings=source_reference_bindings,
    )


__all__ = ("RetainedPortfolioRiskAssetsReader",)

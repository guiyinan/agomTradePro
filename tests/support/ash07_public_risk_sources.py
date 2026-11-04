"""Build dry-run RawPayload manifests from the retained public-source facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo


def _repository_root() -> Path:
    """Find the checkout from this test-support module's formal location."""

    for parent in Path(__file__).resolve().parents:
        if (parent / "manage.py").is_file() and (parent / "apps").is_dir():
            return parent
    raise RuntimeError("AgomTradePro repository root could not be resolved")


REPOSITORY_ROOT = _repository_root()

if TYPE_CHECKING:
    from apps.risk_center.application.portfolio_risk_source_admission import (
        PortfolioRiskSourceAdmissionRequest,
    )


def _read_json(path: Path) -> dict[str, Any]:
    """Load one retained operator facts document without parsing source bytes."""

    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if type(value) is not dict:
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _trusted_capture_metadata(document: dict[str, Any], body: bytes) -> tuple[Any, Any | None]:
    """Validate retained transport metadata and rebuild the exact typed capture."""

    from apps.risk_center.domain.portfolio_risk_clock_evidence import (
        PortfolioRiskCaptureReceipt,
    )

    meta_path = _resolve_evidence_path(document["capture_metadata_path"])
    meta_bytes = meta_path.read_bytes()
    if hashlib.sha256(meta_bytes).hexdigest() != document["capture_metadata_sha256"]:
        raise ValueError(f"capture metadata hash differs: {meta_path}")
    metadata = json.loads(meta_bytes.decode("utf-8-sig"))
    source_id = document["source_evidence"]["source_id"]
    if document["kind"] == "industry_membership":
        response_hash = metadata["sha256"]
        response_time = metadata["captured_at"]
        status = metadata["status"]
        request_matches = (
            metadata["url"] == document["original_url"]
            and metadata["request_form"] == document["source_request"]
        )
        source_rows = json.loads(body)
        rows = source_rows["data"]["rows"]
        total = source_rows["data"]["total"]
        complete = (
            request_matches
            and type(total) is int
            and total == len(rows)
            and total == document["expected_source_row_count"]
            and total <= int(metadata["request_form"]["pageSize"])
            and len(
                [
                    row
                    for row in rows
                    if row["stockCode"] == document["provider_asset_code"]
                    and row["tradeDate"] == document["facts"]["effective_from"]
                    and row["industryCode3"] == document["facts"]["industry_code"]
                ]
            )
            == 1
        )
        clock_match = (
            document["source_evidence"]["observation_precision"] == "date"
            and document["source_evidence"]["observed_on"] == document["facts"]["effective_from"]
            and document["source_evidence"]["observed_at"] is None
            and datetime.fromisoformat(document["source_evidence"]["known_at"])
            == datetime.fromisoformat(response_time)
            and document["source_evidence"]["available_at"] is None
            and document["source_evidence"]["valid_until"] is None
        )
        sina_capture = None
    else:
        response_hash = metadata["body_sha256"]
        response_time = metadata["response_completed_at"]
        status = metadata["http_status"]
        request_matches = metadata["requested_url"] == document["original_url"] and (
            metadata["final_url"] == document["original_url"]
        )
        if metadata["body_size_bytes"] != len(body):
            raise ValueError("Sina capture metadata body size differs from original bytes")
        from apps.data_center.domain.sina_quote_capture import parse_sina_quote_capture

        capture = parse_sina_quote_capture(
            asset_code=document["provider_asset_code"],
            requested_url=metadata["requested_url"],
            final_url=metadata["final_url"],
            request_started_at=datetime.fromisoformat(metadata["request_started_at"]),
            response_completed_at=datetime.fromisoformat(response_time),
            http_status=status,
            http_date=metadata["http_date"],
            content_type=metadata["content_type"],
            charset=metadata["charset"],
            content_encoding=metadata["content_encoding"],
            body=body,
        )
        quote = capture.quote
        evidence_observed_at = document["source_evidence"]["observed_at"]
        clock_match = (
            document["source_evidence"]["observation_precision"] == "timestamp"
            and document["source_evidence"]["observed_on"] is None
            and evidence_observed_at is not None
            and quote is not None
            and quote.source_observed_at == datetime.fromisoformat(evidence_observed_at)
            and datetime.fromisoformat(document["source_evidence"]["known_at"])
            == datetime.fromisoformat(response_time)
            and document["source_evidence"]["available_at"] is None
            and document["source_evidence"]["valid_until"] is None
        )
        if document["kind"] == "valuation":
            facts_match = quote is not None and str(quote.last_price) == document["facts"]["price"]
        elif document["kind"] == "execution_session_state":
            observed_at = quote.source_observed_at if quote is not None else None
            facts_match = (
                quote is not None
                and observed_at is not None
                and document["facts"]["session_date"]
                == observed_at.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
                and document["facts"]["suspended"] is None
            )
        else:
            facts_match = (
                quote is not None
                and str(quote.volume) == document["facts"]["volume"]["value"]
                and str(quote.amount) == document["facts"]["amount"]["value"]
            )
        complete = request_matches and clock_match and capture.usable_parse and facts_match
        # The trusted Sina object is needed only by the close-state proof
        # provider. Valuation/capacity use the same typed receipt but their
        # source clocks remain the timestamp facts carried by this manifest.
        sina_capture = capture if document["kind"] == "execution_session_state" else None

    body_hash = hashlib.sha256(body).hexdigest()
    if (
        not complete
        or not clock_match
        or body_hash != response_hash
        or len(body) != document["body_size_bytes"]
        or datetime.fromisoformat(response_time) != datetime.fromisoformat(document["captured_at"])
        or not 200 <= status < 300
    ):
        raise ValueError("retained capture metadata/body contract did not qualify")
    receipt = PortfolioRiskCaptureReceipt(
        capture_id=f"retained-capture-{hashlib.sha256(meta_bytes).hexdigest()[:24]}",
        source_id=source_id,
        source_record_id=document["source_record_id"],
        original_body_sha256=body_hash,
        response_completed_at=datetime.fromisoformat(response_time),
        http_status=status,
        body_size_bytes=len(body),
        body_complete=complete,
    )
    return receipt, sina_capture


def _admission_documents(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand the explicitly mapped source facts into per-kind admission requests."""

    documents: list[dict[str, Any]] = []
    identity_by_code = {
        item["sse_company_code"]: item for item in candidate["identity_resolution"]["records"]
    }
    industry = candidate["industry_capture"]
    industry_source = industry["source_clock_fields"]
    for member in industry["same_day_policy_bounded_memberships"]:
        identity = identity_by_code[member["stock_code"]]
        local_record_id = f"{industry['source_record_id']}:{member['stock_code']}"
        documents.append(
            {
                "schema_version": "ash07.source_admission_request.v1",
                "kind": "industry_membership",
                "asset_code": identity["asset_code"],
                "security_id": identity["security_id"],
                "source_record_id": local_record_id,
                "original_url": industry["url"],
                "captured_at": industry["response_completed_at"],
                "source_evidence": {
                    "source_id": industry["source_id"],
                    "source_record_id": local_record_id,
                    "original_payload_sha256": industry["raw_body_sha256"],
                    **industry_source,
                    "effective_on": industry_source["observed_on"],
                    "effective_until": industry_source["observed_on"],
                    "source_purpose": industry["purpose"],
                    "allowed_purposes": [industry["purpose"]],
                    "restrictions": industry["restrictions"],
                    "must_not_use_for_decision": False,
                    "coverage": industry["coverage"],
                },
                "facts": {
                    "taxonomy_id": industry["taxonomy_id"],
                    "taxonomy_kind": industry["taxonomy_kind"],
                    "provider_id": industry["provider_id"],
                    "provider_version": industry["provider_version"],
                    "industry_code": member["industry_code_3"],
                    "effective_from": industry["source_clock_fields"]["observed_on"],
                    "effective_end_state": "bounded",
                    "effective_until": industry["source_clock_fields"]["observed_on"],
                },
                "body_path": industry["raw_body_path"],
                "body_size_bytes": industry["body_size_bytes"],
                "capture_metadata_path": industry["capture_metadata_path"],
                "capture_metadata_sha256": industry["capture_metadata_sha256"],
                "source_request": industry["request"],
                "provider_asset_code": member["stock_code"],
                "expected_source_row_count": industry["coverage"]["expected_item_count"],
            }
        )

    for quote in candidate["sina_quotes"]:
        for kind in ("valuation", "capacity_window", "execution_session_state"):
            template_key = (
                "capacity_source_evidence_template"
                if kind == "capacity_window"
                else f"{kind}_source_evidence_template"
            )
            source_clocks = {
                key: value
                for key, value in quote["source_clock_fields"].items()
                if key != "http_date"
            }
            template = quote.get(template_key)
            if kind == "execution_session_state":
                close_state = quote["close_state_candidate"]
                template = {
                    "source_purpose": close_state["purpose"],
                    "allowed_purposes": [close_state["purpose"]],
                    "restrictions": close_state["restrictions"],
                    "must_not_use_for_decision": False,
                    "coverage": {
                        "status": "complete",
                        "precision_basis": "one_security_quote_response",
                        "expected_item_count": 1,
                        "observed_item_count": 1,
                    },
                }
            if not isinstance(template, dict):
                raise ValueError(f"missing explicit evidence template for {kind}")
            local_record_id = f"{quote['source_record_id']}:{kind}"
            evidence = {
                "source_id": quote["source_id"],
                "source_record_id": local_record_id,
                "original_payload_sha256": quote["raw_body_sha256"],
                **source_clocks,
                **template,
                "effective_on": (
                    candidate["business_date"] if kind == "execution_session_state" else None
                ),
                "effective_until": None,
                "observed_at": quote["quote"]["observed_at"],
            }
            facts: dict[str, Any]
            if kind == "valuation":
                facts = {
                    "price": quote["quote"]["last_price"],
                    **quote["valuation_facts"],
                }
            elif kind == "capacity_window":
                facts = {
                    **quote["capacity_facts"],
                    "volume": {
                        "value": quote["quote"]["volume_raw"],
                        "unit": quote["capacity_facts"]["volume_unit"],
                    },
                    "amount": {
                        "value": quote["quote"]["amount_raw"],
                        "unit": quote["capacity_facts"]["amount_unit"],
                    },
                }
                facts.pop("volume_unit")
                facts.pop("amount_unit")
                facts.pop("selected_measure")
            else:
                facts = {
                    "session_date": candidate["business_date"],
                    "suspended": None,
                }
            documents.append(
                {
                    "schema_version": "ash07.source_admission_request.v1",
                    "kind": kind,
                    "asset_code": quote["risk_asset_code"],
                    "security_id": quote["security_id"],
                    "source_record_id": local_record_id,
                    "original_url": quote["url"],
                    "captured_at": quote["response_completed_at"],
                    "source_evidence": evidence,
                    "facts": facts,
                    "body_path": quote["raw_body_path"],
                    "body_size_bytes": quote["body_size_bytes"],
                    "capture_metadata_path": quote["capture_metadata_path"],
                    "capture_metadata_sha256": quote["capture_metadata_sha256"],
                    "provider_asset_code": quote["provider_asset_code"],
                }
            )
    return documents


def _admission_request(document: dict[str, Any]) -> PortfolioRiskSourceAdmissionRequest:
    """Validate retained bytes/receipt and create one typed admission request."""

    from apps.risk_center.application.portfolio_risk_source_admission import (
        PortfolioRiskSourceAdmissionRequest,
        parse_portfolio_risk_source_admission_request,
    )

    body_path = _resolve_evidence_path(document["body_path"])
    body = body_path.read_bytes()
    actual_hash = sha256(body).hexdigest()
    if len(body) != document["body_size_bytes"]:
        raise ValueError(f"retained body hash/size differs: {body_path}")
    if actual_hash != document["source_evidence"]["original_payload_sha256"]:
        raise ValueError(f"retained source body differs from explicit facts: {body_path}")
    receipt, sina_capture = _trusted_capture_metadata(document, body)
    admission_document = {
        key: value
        for key, value in document.items()
        if key
        not in {
            "body_path",
            "body_size_bytes",
            "capture_metadata_path",
            "capture_metadata_sha256",
            "source_request",
            "provider_asset_code",
            "expected_source_row_count",
        }
    }
    request = parse_portfolio_risk_source_admission_request(
        admission_document,
        original_body=body,
        capture_receipt=receipt,
        sina_capture=sina_capture,
    )
    if type(request) is not PortfolioRiskSourceAdmissionRequest:
        raise TypeError("admission parser returned an unexpected request type")
    return request


def verify_source_unit_mapping(candidate: dict[str, Any]) -> dict[str, object]:
    """Verify the retained Sina field-mapping artifact used for canonical units."""

    mapping = candidate["unit_mapping"]
    path = _resolve_evidence_path(mapping["source_mapping_path"])
    source_bytes = path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if source_hash != mapping["source_mapping_sha256"]:
        raise ValueError(f"Sina unit-mapping artifact hash differs: {path}")
    if mapping["numeric_scale"] != "1":
        raise ValueError("this candidate only retains exact scale-1 Sina values")
    return {
        "source_mapping_url": mapping["source_mapping_url"],
        "source_mapping_sha256": source_hash,
        "canonical_quantity_unit": mapping["canonical_quantity_unit"],
        "canonical_money_unit": mapping["canonical_money_unit"],
        "numeric_scale": mapping["numeric_scale"],
    }


def verify_source_request_units(
    requests: Sequence[PortfolioRiskSourceAdmissionRequest],
    *,
    unit_mapping: Mapping[str, object],
    policy: Mapping[str, object] | None = None,
) -> None:
    """Cross-check declared units without filling missing source units.

    The hash-bound vendor artifact supports the explicitly reviewed mapping;
    this helper does not infer a currency or quantity unit from JavaScript.
    """

    quantity_unit = unit_mapping.get("canonical_quantity_unit")
    money_unit = unit_mapping.get("canonical_money_unit")
    if any(type(unit) is not str or not unit for unit in (quantity_unit, money_unit)):
        raise ValueError("declared unit mapping must name both canonical units")
    for request in requests:
        facts = request.facts
        if request.kind == "valuation":
            pairs = (
                (facts.get("quantity_unit"), quantity_unit),
                (facts.get("price_unit"), money_unit),
            )
        elif request.kind == "capacity_window":
            volume = facts.get("volume")
            amount = facts.get("amount")
            if not isinstance(volume, Mapping) or not isinstance(amount, Mapping):
                raise ValueError("capacity facts must preserve their value/unit pairs")
            pairs = ((volume.get("unit"), quantity_unit), (amount.get("unit"), money_unit))
        else:
            continue
        if any(actual is not None and actual != expected for actual, expected in pairs):
            raise ValueError("source facts differ from the declared unit mapping")
    if policy is not None:
        capacity = policy.get("capacity")
        if not isinstance(capacity, Mapping) or capacity.get("measure") not in {"volume", "amount"}:
            raise ValueError("policy capacity measure is not bound to the declared unit mapping")
        expected_capacity_unit = quantity_unit if capacity["measure"] == "volume" else money_unit
        if (
            policy.get("ledger_money_unit") != money_unit
            or capacity.get("unit") != expected_capacity_unit
        ):
            raise ValueError("policy differs from the declared unit mapping")


def build_real_source_admission_requests(
    candidate_path: Path,
) -> tuple[PortfolioRiskSourceAdmissionRequest, ...]:
    """Build exact local source requests from verified retained evidence only."""

    selected_candidate_path = candidate_path
    if not selected_candidate_path.is_absolute():
        selected_candidate_path = (REPOSITORY_ROOT / selected_candidate_path).resolve()
    candidate = _read_json(selected_candidate_path)
    unit_mapping = verify_source_unit_mapping(candidate)
    requests = tuple(_admission_request(document) for document in _admission_documents(candidate))
    verify_source_request_units(requests, unit_mapping=unit_mapping)
    return requests


def _resolve_evidence_path(value: object) -> Path:
    """Resolve one explicit retained-data path against the repository root."""

    if type(value) is not str or not value.strip():
        raise ValueError("retained source evidence path must be a nonempty string")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPOSITORY_ROOT / path).resolve()


def _dry_run_manifest(document: dict[str, Any]) -> dict[str, Any]:
    """Build one hash-addressed manifest without writing it to RawPayload."""

    from apps.risk_center.source_admission_composition import (
        build_portfolio_risk_source_admission_use_case,
    )

    body_path = _resolve_evidence_path(document["body_path"])
    original_body = body_path.read_bytes()
    actual_hash = sha256(original_body).hexdigest()
    request = _admission_request(document)
    result = build_portfolio_risk_source_admission_use_case().execute(request, persist=False)
    payload = result.payload
    receipt = request.capture_receipt
    if receipt is None:
        raise ValueError("candidate is missing its typed transport receipt")
    if result.stored or payload.fetched_at != receipt.response_completed_at:
        raise ValueError("dry-run admission unexpectedly stored or changed its capture clock")
    return {
        "kind": document["kind"],
        "asset_code": document["asset_code"],
        "security_id": document["security_id"],
        "source_record_id": document["source_record_id"],
        "source_id": document["source_evidence"]["source_id"],
        "original_body_sha256": actual_hash,
        "raw_payload_manifest_hash": payload.payload_hash,
        "schema_fingerprint": payload.schema_fingerprint,
        "dataset_key": payload.dataset_key,
        "parser_version": payload.parser_version,
        "fetched_at": payload.fetched_at.isoformat(),
        "payload_size_bytes": payload.payload_size_bytes,
    }


def main() -> int:
    """Write dry-run hashes for current-reference-bound candidate records."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        type=Path,
        default=None,
        help="ignored-directory retained source-facts candidate to verify",
    )
    parser.add_argument(
        "--as-of",
        required=True,
        help="aware ISO cutoff for exact CurrentReference identity checks",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="explicit external output path for non-persistent manifest hashes",
    )
    args = parser.parse_args()
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        raise SystemExit("DJANGO_SETTINGS_MODULE must point to the isolated test settings")
    candidate_argument = args.candidate or os.environ.get("ASH07_REAL_SOURCE_CANDIDATE_PATH")
    if candidate_argument is None:
        raise SystemExit(
            "pass --candidate or set ASH07_REAL_SOURCE_CANDIDATE_PATH to the retained facts file"
        )

    import django

    django.setup()
    candidate_path = Path(candidate_argument)
    if not candidate_path.is_absolute():
        candidate_path = (REPOSITORY_ROOT / candidate_path).resolve()
    candidate = _read_json(candidate_path)
    unit_mapping = verify_source_unit_mapping(candidate)
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise SystemExit("--as-of must include a timezone offset")
    from apps.simulated_trading.execution_current_reference_composition import (
        build_current_reference_identity_reader,
    )

    identity_reader = build_current_reference_identity_reader(runtime_environment="development")
    verified_identities: list[dict[str, str]] = []
    for expected in candidate["identity_resolution"]["records"]:
        actual = identity_reader.resolve_current_reference_identity(
            asset_code=expected["asset_code"],
            as_of=as_of,
        )
        if (
            actual is None
            or actual.asset_code != expected["asset_code"]
            or actual.security_id != expected["security_id"]
            or actual.source_exchange != "SSE"
        ):
            raise SystemExit(
                "CurrentReference did not resolve the exact approved SSE identity for "
                f"{expected['asset_code']}"
            )
        verified_identities.append(
            {
                "asset_code": actual.asset_code,
                "security_id": actual.security_id,
                "source_exchange": actual.source_exchange,
                "identity_valid_until": actual.identity_valid_until.isoformat(),
            }
        )
    documents = _admission_documents(candidate)
    manifests = [_dry_run_manifest(document) for document in documents]
    output_path = args.output
    if not output_path.is_absolute():
        output_path = (REPOSITORY_ROOT / output_path).resolve()
    output_path.write_text(
        json.dumps(
            {
                "schema": "ash07.raw_payload_admission_candidates.v1",
                "persisted": False,
                "identity_status": "exact_current_reference_resolution_verified",
                "as_of": as_of.isoformat(),
                "unit_mapping": unit_mapping,
                "identities": verified_identities,
                "manifests": manifests,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

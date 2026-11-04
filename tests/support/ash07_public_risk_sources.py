"""Build dry-run RawPayload manifests from the retained public-source facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
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
    from apps.data_center.domain.sina_quote_capture import SinaQuoteCapture
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


def _capture_time_text(value: datetime) -> str:
    """Serialize one aware capture clock without changing its instant."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Sina capture clocks must remain timezone-aware")
    return value.isoformat()


def _decimal_text(value: Decimal | None) -> str | None:
    """Preserve a parsed decimal without converting it through binary float."""

    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise TypeError("Sina numeric fields must remain Decimal values")
    return str(value)


def _capture_file_stem(asset_code: str) -> str:
    """Build a bounded filename stem from an existing provider asset ID."""

    stem = "".join(character.lower() if character.isalnum() else "-" for character in asset_code)
    if not stem or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in stem
    ):
        raise ValueError("Sina provider asset ID cannot be used as a local filename")
    return stem


def _capture_metadata_document(
    *,
    capture: SinaQuoteCapture,
    template: Mapping[str, Any],
    raw_file: str,
) -> dict[str, Any]:
    """Build the existing sidecar shape from one exact typed Sina response."""

    quote = capture.quote
    if not capture.usable_parse or quote is None:
        raise ValueError(f"Sina capture for {capture.asset_code} is not parseable")
    if template.get("schema") != "sina-quote-capture.v1":
        raise ValueError("Sina sidecar template uses an unsupported schema")
    if (
        template.get("source_availability_at") is not None
        or template.get("source_valid_until") is not None
    ):
        raise ValueError("Sina source availability and expiry must remain unknown")
    quote_template = template.get("quote")
    if not isinstance(quote_template, dict):
        raise ValueError("Sina sidecar template is missing its source-fact fields")
    metadata = dict(template)
    quote_document = dict(quote_template)
    quote_document.update(
        {
            "source_symbol": quote.source_symbol,
            "source_date_text": quote.source_date_text,
            "source_time_text": quote.source_time_text,
            "source_observed_at": (
                quote.source_observed_at.isoformat()
                if quote.source_observed_at is not None
                else None
            ),
            "source_clock_status": quote.source_clock_status.value,
            "vendor_status_code": quote.vendor_status_code,
            "vendor_status_label": quote.vendor_status_label,
            "reported_trading_state": quote.reported_trading_state.value,
            "open_price": _decimal_text(quote.open_price),
            "previous_close": _decimal_text(quote.previous_close),
            "last_price": _decimal_text(quote.last_price),
            "high_price": _decimal_text(quote.high_price),
            "low_price": _decimal_text(quote.low_price),
            "bid_price": _decimal_text(quote.bid_price),
            "ask_price": _decimal_text(quote.ask_price),
            "volume": _decimal_text(quote.volume),
            "amount": _decimal_text(quote.amount),
        }
    )
    metadata.update(
        {
            "schema": "sina-quote-capture.v1",
            "asset_code": capture.asset_code,
            "requested_url": capture.requested_url,
            "final_url": capture.final_url,
            "request_started_at": _capture_time_text(capture.request_started_at),
            "response_completed_at": _capture_time_text(capture.response_completed_at),
            "http_status": capture.http_status,
            "http_date": capture.http_date,
            "content_type": capture.content_type,
            "charset": capture.charset,
            "content_encoding": capture.content_encoding,
            "body_size_bytes": capture.body_size_bytes,
            "body_sha256": capture.body_sha256,
            "parse_issue": capture.parse_issue.value if capture.parse_issue is not None else None,
            "raw_file": raw_file,
            "raw_file_sha256": capture.body_sha256,
            "source_availability_at": None,
            "source_valid_until": None,
            "local_known_at_utc": capture.response_completed_at.astimezone(UTC).isoformat(),
            "quote": quote_document,
        }
    )
    return metadata


def _capture_candidate_quote(
    *,
    quote_entry: dict[str, Any],
    capture: SinaQuoteCapture,
    business_date: date,
    output_dir: Path,
    require_capacity_values: bool,
) -> tuple[Path, Path, bytes, bytes]:
    """Replace only one candidate quote's bytes and receipt with a real capture."""

    provider_asset_code = quote_entry.get("provider_asset_code")
    if type(provider_asset_code) is not str or capture.asset_code != provider_asset_code:
        raise ValueError("refreshed Sina capture differs from the candidate provider asset ID")
    observation = capture.quote
    if not capture.usable_parse or observation is None:
        raise ValueError(f"refreshed Sina capture for {provider_asset_code} is not parseable")
    if observation.source_clock_status.value != "valid" or observation.source_observed_at is None:
        raise ValueError(f"refreshed Sina source clock for {provider_asset_code} is unknown")
    shanghai = ZoneInfo("Asia/Shanghai")
    observed_local = observation.source_observed_at.astimezone(shanghai)
    received_local = capture.response_completed_at.astimezone(shanghai)
    if (
        observed_local.date() != business_date
        or observed_local.time() < time(15)
        or received_local.date() != business_date
        or capture.response_completed_at < observation.source_observed_at
    ):
        raise ValueError("refreshed Sina capture is not a same-day completed close observation")
    if observation.last_price is None:
        raise ValueError(f"refreshed Sina capture for {provider_asset_code} lacks a price")
    if require_capacity_values and (observation.volume is None or observation.amount is None):
        raise ValueError(f"refreshed Sina capture for {provider_asset_code} lacks capacity values")

    metadata_path_value = quote_entry.get("capture_metadata_path")
    if type(metadata_path_value) is not str:
        raise ValueError("candidate Sina capture metadata path is missing")
    old_metadata_path = _resolve_evidence_path(metadata_path_value)
    old_metadata_bytes = old_metadata_path.read_bytes()
    expected_metadata_hash = quote_entry.get("capture_metadata_sha256")
    if hashlib.sha256(old_metadata_bytes).hexdigest() != expected_metadata_hash:
        raise ValueError("candidate Sina capture metadata hash differs from its sidecar")
    old_metadata = json.loads(old_metadata_bytes.decode("utf-8-sig"))
    if type(old_metadata) is not dict or old_metadata.get("asset_code") != provider_asset_code:
        raise ValueError("candidate Sina capture sidecar is not bound to its provider asset ID")
    metadata_document = _capture_metadata_document(
        capture=capture,
        template=old_metadata,
        raw_file=f"{_capture_file_stem(provider_asset_code)}.response.bin",
    )
    metadata_bytes = (json.dumps(metadata_document, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    raw_path = output_dir / f"{_capture_file_stem(provider_asset_code)}.response.bin"
    metadata_path = output_dir / f"{_capture_file_stem(provider_asset_code)}.capture.json"
    quote_entry.update(
        {
            "url": capture.requested_url,
            "raw_body_path": str(raw_path.resolve()),
            "capture_metadata_path": str(metadata_path.resolve()),
            "capture_metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
            "raw_body_sha256": capture.body_sha256,
            "body_size_bytes": capture.body_size_bytes,
            "http_status": capture.http_status,
            "response_completed_at": capture.response_completed_at.isoformat(),
            "quote": {
                **quote_entry["quote"],
                "observed_at": observation.source_observed_at.isoformat(),
                "last_price": _decimal_text(observation.last_price),
                "volume_raw": _decimal_text(observation.volume),
                "amount_raw": _decimal_text(observation.amount),
                "vendor_status_code": observation.vendor_status_code,
                "vendor_reported_state": observation.reported_trading_state.value,
            },
            "source_clock_fields": {
                **quote_entry["source_clock_fields"],
                "observation_precision": "timestamp",
                "observed_on": None,
                "available_at": None,
                "known_at": capture.response_completed_at.isoformat(),
                "valid_until": None,
                "http_date": capture.http_date,
            },
        }
    )
    return raw_path, metadata_path, capture.body, metadata_bytes


def _refresh_supplemental_etf_quote(
    *,
    candidate_path: Path,
    output_dir: Path,
    business_date: date,
    capture_sina_quote: Callable[[str], SinaQuoteCapture],
) -> tuple[Path, Path, bytes, bytes, dict[str, Any]]:
    """Refresh the one existing supplemental provider-ID mapping without adding identity data."""

    supplemental_path = candidate_path.parent / "supplemental-quotes.json"
    if not supplemental_path.is_file():
        raise ValueError("ETF refresh requires the candidate's retained supplemental quote archive")
    supplemental_value = json.loads(supplemental_path.read_text(encoding="utf-8-sig"))
    if type(supplemental_value) is not list or len(supplemental_value) != 1:
        raise ValueError("ETF refresh requires exactly one existing supplemental mapping")
    entry = supplemental_value[0]
    if type(entry) is not dict:
        raise ValueError("supplemental quote mapping must be a JSON object")
    asset_code = entry.get("asset_code")
    metadata_path_value = entry.get("metadata_path")
    if type(asset_code) is not str or type(metadata_path_value) is not str:
        raise ValueError("supplemental quote mapping lacks its existing provider asset ID")
    old_metadata_path = _resolve_evidence_path(metadata_path_value)
    old_metadata_bytes = old_metadata_path.read_bytes()
    if hashlib.sha256(old_metadata_bytes).hexdigest() != entry.get("metadata_sha256"):
        raise ValueError("supplemental quote sidecar hash differs from its archive entry")
    old_metadata = json.loads(old_metadata_bytes.decode("utf-8-sig"))
    if type(old_metadata) is not dict or old_metadata.get("asset_code") != asset_code:
        raise ValueError("supplemental quote sidecar differs from its existing provider mapping")
    capture = capture_sina_quote(asset_code)
    if capture.asset_code != asset_code:
        raise ValueError("refreshed ETF capture differs from its existing provider asset ID")
    observation = capture.quote
    if observation is None or observation.source_observed_at is None:
        raise ValueError("refreshed ETF quote lacks a valid source timestamp")
    observed_local = observation.source_observed_at.astimezone(ZoneInfo("Asia/Shanghai"))
    received_local = capture.response_completed_at.astimezone(ZoneInfo("Asia/Shanghai"))
    if (
        not capture.usable_parse
        or observation.source_clock_status.value != "valid"
        or observation.last_price is None
        or observed_local.date() != business_date
        or observed_local.time() < time(15)
        or received_local.date() != business_date
    ):
        raise ValueError("refreshed ETF quote is not a same-day completed close observation")
    stem = _capture_file_stem(asset_code)
    raw_path = output_dir / f"{stem}.response.bin"
    metadata_path = output_dir / f"{stem}.capture.json"
    metadata_document = _capture_metadata_document(
        capture=capture,
        template=old_metadata,
        raw_file=raw_path.name,
    )
    metadata_bytes = (json.dumps(metadata_document, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    refreshed_entry = {
        **entry,
        "http_status": capture.http_status,
        "parsed": True,
        "source_observed_at": observation.source_observed_at.isoformat(),
        "vendor_status_code": observation.vendor_status_code,
        "last_price": _decimal_text(observation.last_price),
        "volume": _decimal_text(observation.volume),
        "amount": _decimal_text(observation.amount),
        "body_sha256": capture.body_sha256,
        "meta_file": metadata_path.name,
        "metadata_path": str(metadata_path.resolve()),
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
    }
    return raw_path, metadata_path, capture.body, metadata_bytes, refreshed_entry


def refresh_current_quote_candidate(
    candidate_path: Path,
    output_dir: Path,
    include_etf: bool = False,
) -> Path:
    """Copy a retained candidate and refresh only Sina quotes after calendar/rule setup.

    Call this after the test has completed its real calendar publication and
    execution-rule setup. Captures are obtained from Data Center's production
    Sina capture API; the helper never changes the candidate date, provider
    identities, industry bytes, source purposes, or unknown source availability
    and expiry. With ``include_etf=True``, it refreshes the single provider ID
    already recorded in the adjacent ``supplemental-quotes.json`` archive.
    """

    if type(include_etf) is not bool:
        raise TypeError("include_etf must be a boolean")
    selected_candidate_path = _resolve_evidence_path(str(candidate_path))
    candidate = _read_json(selected_candidate_path)
    if (
        candidate.get("schema") != "ash07.real_source_owner_risk_candidate.v1"
        or candidate.get("candidate_status")
        != "raw_capture_facts_only_not_admitted_or_policy_pinned"
    ):
        raise ValueError("candidate is not the expected retained real-source facts document")
    business_date_text = candidate.get("business_date")
    if type(business_date_text) is not str:
        raise ValueError("candidate business date is missing")
    business_date = date.fromisoformat(business_date_text)
    quote_entries = candidate.get("sina_quotes")
    if type(quote_entries) is not list or not quote_entries:
        raise ValueError("candidate does not contain explicit Sina quote entries")
    output_path = (
        output_dir.resolve()
        if output_dir.is_absolute()
        else (REPOSITORY_ROOT / output_dir).resolve()
    )
    allowed_roots = (
        (REPOSITORY_ROOT / ".tmp").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    )
    if not any(_is_path_below(output_path, root) for root in allowed_roots):
        raise ValueError("refreshed captures must be written below .tmp or the test temp root")
    if output_path == selected_candidate_path.parent:
        raise ValueError("refreshed captures must use a new output directory")
    candidate_output_path = output_path / selected_candidate_path.name
    if candidate_output_path.exists():
        raise FileExistsError(f"refreshed candidate already exists: {candidate_output_path}")

    from apps.data_center.composition import capture_sina_quote

    def capture_retaining_original(asset_code: str) -> SinaQuoteCapture:
        """Retain every actual response before any financial/source qualification."""

        archive = output_path / "capture-attempt-originals" / _capture_file_stem(asset_code)
        archive.mkdir(parents=True, exist_ok=False)
        capture = capture_sina_quote(asset_code)
        (archive / "response.bin").write_bytes(capture.body)
        transport = dict(capture.to_payload())
        transport.pop("body_base64")
        transport["raw_file"] = "response.bin"
        transport["source_availability_at"] = None
        transport["source_valid_until"] = None
        (archive / "transport-receipt.json").write_text(
            json.dumps(transport, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return capture

    artifacts: list[tuple[Path, Path, bytes, bytes]] = []
    target_paths: set[Path] = {candidate_output_path}
    for quote_entry in quote_entries:
        if type(quote_entry) is not dict:
            raise ValueError("candidate Sina quote entries must be JSON objects")
        provider_asset_code = quote_entry.get("provider_asset_code")
        if type(provider_asset_code) is not str:
            raise ValueError("candidate Sina quote is missing its provider asset ID")
        stem = _capture_file_stem(provider_asset_code)
        raw_path = output_path / f"{stem}.response.bin"
        metadata_path = output_path / f"{stem}.capture.json"
        if raw_path in target_paths or metadata_path in target_paths:
            raise ValueError("candidate provider IDs do not produce unique capture filenames")
        target_paths.update((raw_path, metadata_path))
        artifacts.append(
            _capture_candidate_quote(
                quote_entry=quote_entry,
                capture=capture_retaining_original(provider_asset_code),
                business_date=business_date,
                output_dir=output_path,
                require_capacity_values=True,
            )
        )

    refreshed_supplemental: dict[str, Any] | None = None
    if include_etf:
        (
            supplemental_raw_path,
            supplemental_metadata_path,
            supplemental_body,
            supplemental_metadata,
            supplemental_entry,
        ) = _refresh_supplemental_etf_quote(
            candidate_path=selected_candidate_path,
            output_dir=output_path,
            business_date=business_date,
            capture_sina_quote=capture_retaining_original,
        )
        if supplemental_raw_path in target_paths or supplemental_metadata_path in target_paths:
            raise ValueError("supplemental provider ID collides with a candidate capture")
        target_paths.update((supplemental_raw_path, supplemental_metadata_path))
        supplemental_manifest_path = output_path / "supplemental-quotes.json"
        if supplemental_manifest_path in target_paths:
            raise ValueError("supplemental quote archive collides with another output")
        target_paths.add(supplemental_manifest_path)
        artifacts.append(
            (
                supplemental_raw_path,
                supplemental_metadata_path,
                supplemental_body,
                supplemental_metadata,
            )
        )
        refreshed_supplemental = supplemental_entry

    existing_targets = [path for path in target_paths if path.exists()]
    if existing_targets:
        raise FileExistsError(f"refreshed capture output already exists: {existing_targets[0]}")
    output_path.mkdir(parents=True, exist_ok=True)
    for raw_path, metadata_path, body, metadata_bytes in artifacts:
        raw_path.write_bytes(body)
        metadata_path.write_bytes(metadata_bytes)
    candidate_bytes = (json.dumps(candidate, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    candidate_output_path.write_bytes(candidate_bytes)
    if refreshed_supplemental is not None:
        supplemental_bytes = (
            json.dumps([refreshed_supplemental], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        (output_path / "supplemental-quotes.json").write_bytes(supplemental_bytes)
    return candidate_output_path


def _is_path_below(path: Path, parent: Path) -> bool:
    """Return whether a resolved output path is contained by its allowed root."""

    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


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

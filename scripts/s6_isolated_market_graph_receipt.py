"""Build and verify opt-in S6 isolated current-market graph receipts."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SHA1_RE = re.compile(r"[0-9a-f]{40}\Z")
_CORE_DATASETS = (
    "equity.price.bar",
    "equity.quote.snapshot",
    "equity.valuation.fact",
)
_TASK_NAME = "data_center.refresh_full_market_publications"
_RECEIPT_NAME = "current-market-graph-refresh.json"


class MarketGraphReceiptError(ValueError):
    """A market-graph refresh receipt failure with a stable diagnostic code."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _canonical_json(payload: object) -> bytes:
    """Encode JSON with one deterministic byte representation."""

    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(payload: object) -> str:
    """Hash one canonical JSON value."""

    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _parse_task_result(raw_result: object) -> dict[str, object] | None:
    """Parse Task Monitor's bounded JSON/literal result without evaluating code."""

    if not isinstance(raw_result, str) or not raw_result or len(raw_result) > 1_000_000:
        return None
    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(raw_result)
        except (SyntaxError, ValueError):
            return None
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        return None
    return cast(dict[str, object], parsed)


def _valid_business_result(result: Mapping[str, object], *, task_id: str, attempt_id: str) -> bool:
    """Require a successful normalized full-market result and exact Task Monitor identity."""

    requested = result.get("requested")
    succeeded = result.get("succeeded")
    failed = result.get("failed")
    stored = result.get("stored")
    return (
        result.get("_task_id") == task_id
        and result.get("_task_attempt_id") == attempt_id
        and result.get("_task_status") == "success"
        and result.get("outcome") == "success"
        and result.get("success") is True
        and result.get("publication_updated") is True
        and isinstance(result.get("publication_run_id"), str)
        and bool(result.get("publication_run_id"))
        and isinstance(result.get("target_trade_date"), str)
        and _is_canonical_date(cast(str, result.get("target_trade_date")))
        and isinstance(requested, int)
        and not isinstance(requested, bool)
        and requested > 0
        and isinstance(succeeded, int)
        and not isinstance(succeeded, bool)
        and succeeded == requested
        and isinstance(failed, int)
        and not isinstance(failed, bool)
        and failed == 0
        and isinstance(stored, int)
        and not isinstance(stored, bool)
        and stored > 0
    )


def _is_canonical_date(value: str) -> bool:
    """Return whether a date string uses the canonical ISO representation."""

    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _validate_task_target_date(result: Mapping[str, object], target_date: date) -> str:
    """Require the Task Monitor result to name the live current-publication date."""

    target_text = target_date.isoformat()
    if result.get("target_trade_date") != target_text:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
    return target_text


def _iso(value: object) -> object:
    """Project ORM and JSONField values into JSON-safe stable values."""

    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
            raise MarketGraphReceiptError("S6_GRAPH_REFRESH_EVIDENCE_INVALID")
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise MarketGraphReceiptError("S6_GRAPH_REFRESH_EVIDENCE_INVALID")
            projected[key] = _iso(item)
        return projected
    if isinstance(value, (list, tuple)):
        return [_iso(item) for item in value]
    if type(value) is float and math.isfinite(value):
        return value
    if value is None or type(value) in {str, int, bool}:
        return value
    raise MarketGraphReceiptError("S6_GRAPH_REFRESH_EVIDENCE_INVALID")


def _member_projection(member: object) -> dict[str, object]:
    """Project the immutable publication member identity and fact hash."""

    fields = (
        "dataset_key",
        "natural_key",
        "source",
        "source_record_id",
        "fact_table",
        "fact_pk",
        "observed_at",
        "raw_payload_hash",
        "quality_status",
        "revision_number",
        "fact_content_hash",
    )
    return {name: _iso(getattr(member, name, None)) for name in fields}


def _validate_publication_hash_bindings(
    *,
    pointers: Sequence[Mapping[str, object]],
    publications: Sequence[Mapping[str, object]],
    member_hashes: Mapping[str, str],
    publication_hashes: Mapping[str, str],
    run_id: str,
) -> None:
    """Require recomputed member/publication seals to match all current headers."""

    pointer_by_dataset = {item.get("dataset_key"): item for item in pointers}
    publication_by_dataset = {item.get("dataset_key"): item for item in publications}
    if (
        set(pointer_by_dataset) != set(_CORE_DATASETS)
        or set(publication_by_dataset) != set(_CORE_DATASETS)
        or set(member_hashes) != set(_CORE_DATASETS)
        or set(publication_hashes) != set(_CORE_DATASETS)
    ):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
    activation_ids: set[object] = set()
    for dataset_key in _CORE_DATASETS:
        pointer = pointer_by_dataset[dataset_key]
        publication = publication_by_dataset[dataset_key]
        member_hash = member_hashes[dataset_key]
        publication_hash = publication_hashes[dataset_key]
        member_count = publication.get("member_count")
        coverage_selected_count = publication.get("coverage_selected_count")
        coverage_eligible_count = publication.get("coverage_eligible_count")
        members_sealed_at = publication.get("members_sealed_at")
        published_at = publication.get("published_at")
        if (
            publication.get("dataset_key") != dataset_key
            or pointer.get("dataset_key") != dataset_key
            or pointer.get("publication_id") != publication.get("publication_id")
            or pointer.get("publication_hash") != publication.get("publication_hash")
            or publication.get("member_manifest_hash") != member_hash
            or publication.get("publication_hash") != publication_hash
            or publication.get("publication_key") != "current"
            or publication.get("run_id") is None
            or str(publication.get("run_id")) != run_id
            or publication.get("state") != "published"
            or publication.get("must_not_use_for_decision") is not False
            or not isinstance(member_count, int)
            or isinstance(member_count, bool)
            or member_count <= 0
            or coverage_selected_count != member_count
            or coverage_selected_count != coverage_eligible_count
            or not isinstance(members_sealed_at, datetime)
            or members_sealed_at.tzinfo is None
            or members_sealed_at.utcoffset() is None
            or not isinstance(published_at, datetime)
            or published_at.tzinfo is None
            or published_at.utcoffset() is None
            or members_sealed_at > published_at
        ):
            raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
        activation_ids.add(pointer.get("activation_id"))
    expected_activation_id = str(
        uuid5(NAMESPACE_URL, f"agomtradepro:current-market-activation:{run_id}")
    )
    if activation_ids != {expected_activation_id}:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")


def _context_fields(context: Mapping[str, str]) -> dict[str, str]:
    """Validate and return attempt-bound, non-secret runtime identities."""

    required = {
        "candidate_sha",
        "attempt_id",
        "attempt_plan_sha256",
        "database",
        "postgres_container",
        "redis_container",
        "postgres_container_id",
        "redis_container_id",
        "network",
        "network_id",
        "execution_image_id",
    }
    if set(context) != required:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_IDENTITY_INVALID")
    if (
        not isinstance(context.get("candidate_sha"), str)
        or _SHA1_RE.fullmatch(context["candidate_sha"]) is None
    ):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_IDENTITY_INVALID")
    for field in (
        "attempt_plan_sha256",
        "postgres_container_id",
        "redis_container_id",
        "network_id",
    ):
        if not isinstance(context.get(field), str) or _SHA256_RE.fullmatch(context[field]) is None:
            raise MarketGraphReceiptError("S6_GRAPH_REFRESH_IDENTITY_INVALID")
    if (
        not isinstance(context.get("attempt_id"), str)
        or re.fullmatch(r"[0-9a-f]{32}\Z", context["attempt_id"]) is None
    ):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_IDENTITY_INVALID")
    if (
        not isinstance(context.get("execution_image_id"), str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}\Z", context["execution_image_id"]) is None
    ):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_IDENTITY_INVALID")
    if (
        not isinstance(context.get("database"), str)
        or re.fullmatch(r"agom_release_rehearsal_[a-f0-9]{32}\Z", context["database"]) is None
    ):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_IDENTITY_INVALID")
    for field, prefix in (
        ("postgres_container", "agom-s6-postgres-"),
        ("redis_container", "agom-s6-redis-"),
    ):
        if (
            not isinstance(context.get(field), str)
            or re.fullmatch(rf"{prefix}[a-f0-9]{{32}}\Z", context[field]) is None
        ):
            raise MarketGraphReceiptError("S6_GRAPH_REFRESH_IDENTITY_INVALID")
    if (
        not isinstance(context.get("network"), str)
        or re.fullmatch(r"agom-s6-network-[a-z0-9-]+\Z", context["network"]) is None
    ):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_IDENTITY_INVALID")
    return cast(dict[str, str], dict(context))


def capture_current_market_graph(*, context: Mapping[str, str], task_id: str) -> dict[str, object]:
    """Read one fully validated current graph and produce its deterministic evidence."""

    from django.db import connection

    from apps.data_center.infrastructure.publication_models import (
        CanonicalPublicationModel,
        CanonicalPublicationPointerModel,
        PublicationMemberModel,
    )
    from apps.task_monitor.infrastructure.models import TaskExecutionModel
    from scripts import export_s6_rehearsal_inputs as exporter

    identity = _context_fields(context)
    if task_id != f"s6-market-refresh-{identity['attempt_id']}":
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_TASK_ID_INVALID")
    if connection.settings_dict.get("NAME") != identity["database"]:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_DATABASE_IDENTITY_INVALID")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        row = cursor.fetchone()
    if not row or row[0] != identity["database"]:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_DATABASE_IDENTITY_INVALID")

    task_row = (
        TaskExecutionModel._default_manager.filter(task_id=task_id)
        .values("task_id", "attempt_id", "task_name", "status", "result")
        .first()
    )
    if (
        not isinstance(task_row, dict)
        or task_row.get("task_name") != _TASK_NAME
        or task_row.get("status") != "success"
        or not isinstance(task_row.get("attempt_id"), str)
    ):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_TASK_MONITOR_INVALID")
    task_attempt_id = cast(str, task_row["attempt_id"])
    parsed_result = _parse_task_result(task_row.get("result"))
    if parsed_result is None:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_TASK_RESULT_INVALID")
    parsed_result.update(
        {
            "_task_id": task_id,
            "_task_attempt_id": task_attempt_id,
            "_task_status": "success",
        }
    )
    if not _valid_business_result(parsed_result, task_id=task_id, attempt_id=task_attempt_id):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_TASK_RESULT_INVALID")

    try:
        target_date = exporter._current_market_publication_target_date()
    except exporter.ExportBlocked as exc:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID") from exc
    target_text = _validate_task_target_date(parsed_result, target_date)

    pointers = list(
        CanonicalPublicationPointerModel._default_manager.filter(
            dataset_key__in=_CORE_DATASETS, publication_key="current"
        ).values("dataset_key", "publication_id", "publication_hash", "activation_id")
    )
    pointers.sort(key=lambda item: str(item.get("dataset_key")))
    if {item.get("dataset_key") for item in pointers} != set(_CORE_DATASETS):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
    activation_ids = {item.get("activation_id") for item in pointers}
    if len(activation_ids) != 1 or not next(iter(activation_ids)):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
    publication_id_values = [item.get("publication_id") for item in pointers]
    if any(not isinstance(item, UUID) for item in publication_id_values):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
    publication_ids = cast(list[UUID], publication_id_values)
    publication_objects = {
        str(item.publication_id): item
        for item in CanonicalPublicationModel._default_manager.filter(
            publication_id__in=publication_ids
        )
    }
    publications = list(
        CanonicalPublicationModel._default_manager.filter(
            publication_id__in=publication_ids
        ).values(
            "dataset_key",
            "publication_id",
            "publication_key",
            "policy_version",
            "publication_hash",
            "member_manifest_hash",
            "member_count",
            "as_of",
            "published_at",
            "run_id",
            "state",
            "must_not_use_for_decision",
            "coverage_requested_count",
            "coverage_eligible_count",
            "coverage_selected_count",
            "coverage_missing_count",
            "members_sealed_at",
            "scope_blocks",
        )
    )
    publications.sort(key=lambda item: str(item.get("dataset_key")))
    if {item.get("dataset_key") for item in publications} != set(_CORE_DATASETS):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
    member_hashes: dict[str, str] = {}
    fact_hashes: dict[str, str] = {}
    computed_publication_hashes: dict[str, str] = {}
    source_times: list[datetime] = []
    from apps.data_center.application.publication_utils import (
        member_reference,
        publication_hash,
        publication_member_manifest_hash,
    )
    from apps.data_center.infrastructure.publication_member_store import (
        publication_fact_content_hashes,
    )

    for publication in publications:
        dataset_key = cast(str, publication.get("dataset_key"))
        publication_id_value = publication.get("publication_id")
        if not isinstance(publication_id_value, UUID):
            raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
        publication_id = publication_id_value
        members = list(
            PublicationMemberModel._default_manager.filter(
                publication_id=publication_id, dataset_key=dataset_key
            ).order_by("natural_key", "source")
        )
        projected_members = [_member_projection(member) for member in members]
        publication_object = publication_objects.get(str(publication_id))
        if publication_object is None or len(members) != publication.get("member_count"):
            raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
        domain_publication = publication_object.to_domain()
        domain_members = tuple(member.to_domain() for member in members)
        try:
            computed_fact_contents = publication_fact_content_hashes(domain_members)
        except (AttributeError, TypeError, ValueError) as exc:
            raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID") from exc
        if len(computed_fact_contents) != len(domain_members):
            raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
        fact_rows: list[dict[str, object]] = []
        for domain_member, projected_member in zip(domain_members, projected_members, strict=True):
            computed_fact_content = computed_fact_contents.get(
                (domain_member.fact_table, domain_member.fact_pk)
            )
            if (
                not isinstance(computed_fact_content, str)
                or computed_fact_content != domain_member.fact_content_hash
                or computed_fact_content != projected_member["fact_content_hash"]
            ):
                raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
            fact_rows.append(
                {
                    "fact_table": projected_member["fact_table"],
                    "fact_pk": projected_member["fact_pk"],
                    "fact_content_hash": computed_fact_content,
                }
            )
        computed_member_hash = publication_member_manifest_hash(
            domain_members,
            policy_identity=publication_object.policy_version,
        )
        computed_publication_hash = publication_hash(
            tuple(member_reference(item) for item in domain_members),
            policy_identity=publication_object.policy_version,
            scope_blocks=domain_publication.scope_blocks,
        )
        member_hashes[dataset_key] = computed_member_hash
        computed_publication_hashes[dataset_key] = computed_publication_hash
        fact_hashes[dataset_key] = _sha256(fact_rows)
        if not members:
            raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
        for member in members:
            observed_at = getattr(member, "observed_at", None)
            if (
                not isinstance(observed_at, datetime)
                or observed_at.tzinfo is None
                or observed_at.utcoffset() is None
            ):
                raise MarketGraphReceiptError("S6_GRAPH_REFRESH_SOURCE_TIME_INVALID")
            source_times.append(observed_at)

    if len(source_times) == 0:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_SOURCE_TIME_INVALID")
    run_ids = {str(item.get("run_id")) for item in publications}
    result_run_id = parsed_result.get("publication_run_id")
    if len(run_ids) != 1 or not isinstance(result_run_id, str) or run_ids != {result_run_id}:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
    _validate_publication_hash_bindings(
        pointers=cast(Sequence[Mapping[str, object]], pointers),
        publications=cast(Sequence[Mapping[str, object]], publications),
        member_hashes=member_hashes,
        publication_hashes=computed_publication_hashes,
        run_id=result_run_id,
    )

    source_time_min = min(source_times).isoformat()
    source_time_max = max(source_times).isoformat()
    normalized_pointers = [
        {
            "dataset_key": _iso(item.get("dataset_key")),
            "publication_id": _iso(item.get("publication_id")),
            "publication_hash": _iso(item.get("publication_hash")),
            "activation_id": _iso(item.get("activation_id")),
        }
        for item in pointers
    ]
    normalized_publications = [
        {
            name: _iso(item.get(name))
            for name in (
                "dataset_key",
                "publication_id",
                "publication_key",
                "policy_version",
                "publication_hash",
                "member_manifest_hash",
                "member_count",
                "as_of",
                "published_at",
                "run_id",
                "state",
                "must_not_use_for_decision",
                "coverage_requested_count",
                "coverage_eligible_count",
                "coverage_selected_count",
                "coverage_missing_count",
                "members_sealed_at",
                "scope_blocks",
            )
        }
        for item in publications
    ]
    payload: dict[str, object] = {
        "schema": "release.s6-isolated-market-graph-refresh.v1",
        "outcome": "success",
        **identity,
        "task_name": _TASK_NAME,
        "task_id": task_id,
        "task_attempt_id": task_attempt_id,
        "task_result_sha256": hashlib.sha256(
            cast(str, task_row["result"]).encode("utf-8")
        ).hexdigest(),
        "task_result": {
            "outcome": parsed_result["outcome"],
            "requested": parsed_result["requested"],
            "succeeded": parsed_result["succeeded"],
            "failed": parsed_result["failed"],
            "stored": parsed_result["stored"],
            "publication_run_id": parsed_result["publication_run_id"],
        },
        "run_id": parsed_result["publication_run_id"],
        "activation_id": normalized_pointers[0]["activation_id"] if normalized_pointers else None,
        "target_trade_date": target_text,
        "source_time_min": source_time_min,
        "source_time_max": source_time_max,
        "pointers": normalized_pointers,
        "publications": normalized_publications,
        "member_hashes": member_hashes,
        "fact_hashes": fact_hashes,
    }
    if (
        len(normalized_pointers) != len(_CORE_DATASETS)
        or len(publications) != len(_CORE_DATASETS)
        or set(member_hashes) != set(_CORE_DATASETS)
        or set(fact_hashes) != set(_CORE_DATASETS)
    ):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_GRAPH_INVALID")
    payload["receipt_sha256"] = _sha256(payload)
    return payload


def read_and_validate_refresh_receipt(
    path: Path, *, context: Mapping[str, str]
) -> dict[str, object]:
    """Rebuild and compare a success receipt against the exact live isolated graph."""

    if path.is_symlink() or not path.is_file():
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_RECEIPT_MISSING")
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o222:
            raise MarketGraphReceiptError("S6_GRAPH_REFRESH_RECEIPT_INVALID")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except MarketGraphReceiptError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_RECEIPT_INVALID") from exc
    if not isinstance(value, dict) or _canonical_json(value) != raw:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_RECEIPT_INVALID")
    receipt = cast(dict[str, object], value)
    task_id = receipt.get("task_id")
    if not isinstance(task_id, str):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_RECEIPT_INVALID")
    expected = capture_current_market_graph(context=context, task_id=task_id)
    if receipt != expected:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_RECEIPT_MISMATCH")
    return receipt


def write_success_receipt(path: Path, payload: Mapping[str, object]) -> None:
    """Atomically publish a new private receipt and refuse pre-existing output."""

    if path.name != _RECEIPT_NAME or path.parent.is_symlink() or not path.parent.is_dir():
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_OUTPUT_INVALID")
    output = dict(payload)
    receipt_hash = output.pop("receipt_sha256", None)
    if (
        output.get("schema") != "release.s6-isolated-market-graph-refresh.v1"
        or output.get("outcome") != "success"
        or not isinstance(receipt_hash, str)
        or _SHA256_RE.fullmatch(receipt_hash) is None
        or receipt_hash != _sha256(output)
    ):
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_RECEIPT_INVALID")
    output["receipt_sha256"] = receipt_hash
    raw = _canonical_json(output)
    if path.is_symlink() or path.exists():
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_OUTPUT_COLLISION")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise MarketGraphReceiptError("S6_GRAPH_REFRESH_OUTPUT_INVALID") from exc


__all__ = [
    "MarketGraphReceiptError",
    "capture_current_market_graph",
    "read_and_validate_refresh_receipt",
    "write_success_receipt",
]

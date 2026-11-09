#!/usr/bin/env python3
"""Replay the versioned REF-05 PUBLIC case from an explicit raw-evidence directory.

This offline command never reads a database, fetches a URL, or grants production
qualification. The tracked recipe binds the external evidence and existing code.
"""

from __future__ import annotations

import argparse
import base64
import calendar
import hashlib
import json
import re
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from apps.data_center.domain.pit import (  # noqa: E402
    KnowledgeScope,
    PITDatasetManifest,
    PITFactVersion,
    PITQuality,
    calculate_pit_manifest_hash,
)
from apps.regime.domain.services_v2 import (  # noqa: E402
    RegimeCalculatorV2,
    ThresholdConfig,
)
from shared.numeric import safe_float  # noqa: E402

SHANGHAI = timezone(timedelta(hours=8))


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError("Expected a JSON object with string keys")
    return cast(dict[str, Any], value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list) or not value:
        raise ValueError("Expected a nonempty JSON array")
    return cast(list[object], value)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Expected nonempty exact text")
    return value


def _clock(value: object) -> datetime:
    result = datetime.fromisoformat(_text(value))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Evidence clock must include a timezone")
    return result


def _number(value: object) -> float:
    result = None if isinstance(value, bool) else safe_float(value)
    if result is None:
        raise ValueError("Evidence number must be finite")
    return result


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_hash(value: object) -> str:
    return _hash(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode())


def _verified_file(
    root: Path, relative: object, expected_hash: object, *, normalize_newlines: bool = False
) -> bytes:
    path = (root / _text(relative)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Evidence path escapes its declared root")
    raw = path.read_bytes()
    hash_input = raw.replace(b"\r\n", b"\n") if normalize_newlines else raw
    if _hash(hash_input) != _text(expected_hash):
        raise ValueError(f"Evidence hash mismatch: {relative}")
    return raw


class ReleaseDocument(HTMLParser):
    """Extract source metadata and the first table without optional HTML packages."""

    def __init__(self, raw: bytes) -> None:
        """Parse one captured UTF-8 document into detached source fields."""
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.publication = ""
        self.release_header: list[str] = []
        self._header_depth = 0
        self.text_parts: list[str] = []
        self.rows: list[list[str]] = []
        self._in_title = False
        self._depth = 0
        self._finished = False
        self._row: list[str] = []
        self._cell: list[str] | None = None
        self.feed(raw.decode("utf-8"))
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Capture only the first table and named publication metadata."""
        attributes = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "meta" and attributes.get("name") == "PubDate":
            self.publication = attributes.get("content") or ""
        if tag == "div":
            if self._header_depth:
                self._header_depth += 1
            elif "detail-title-des" in (attributes.get("class") or "").split():
                self._header_depth = 1
        if tag == "table" and not self._finished:
            self._depth += 1
        if self._depth == 1:
            if tag == "tr":
                self._row = []
            elif tag in {"td", "th"}:
                self._cell = []

    def handle_endtag(self, tag: str) -> None:
        """Finish complete cells and rows without joining separate tables."""
        if tag == "title":
            self._in_title = False
        if tag == "div" and self._header_depth:
            self._header_depth -= 1
        if self._depth == 1:
            if tag in {"td", "th"} and self._cell is not None:
                self._row.append(re.sub(r"\s+", "", "".join(self._cell)))
                self._cell = None
            elif tag == "tr" and self._row:
                self.rows.append(self._row)
                self._row = []
        if tag == "table" and self._depth:
            self._depth -= 1
            self._finished = self._depth == 0

    def handle_data(self, data: str) -> None:
        """Keep source text, title and current table cell independently."""
        self.text_parts.append(data)
        if self._header_depth:
            self.release_header.append(data)
        if self._in_title:
            self.title += data
        if self._cell is not None:
            self._cell.append(data)


def _source_facts(spec: dict[str, Any], evidence: Path, first_id: int) -> list[PITFactVersion]:
    raw = _verified_file(evidence, spec["raw_path"], spec["sha256"])
    document = ReleaseDocument(raw)
    published = _clock(spec["published_at"]).astimezone(SHANGHAI)
    retrieved = _clock(spec["retrieved_at"])
    url = _text(spec["url"])
    address = urlparse(url)
    visible_clock = published.strftime("%Y/%m/%d %H:%M")
    publication_basis = spec.get("publication_basis", "metadata_and_visible_text")
    if publication_basis == "visible_release_header":
        header_clocks = re.findall(
            r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}", "".join(document.release_header)
        )
        publication_valid = header_clocks == [visible_clock] and (
            not document.publication or document.publication == visible_clock
        )
    elif publication_basis == "metadata_and_visible_text":
        publication_valid = document.publication == visible_clock
    else:
        raise ValueError("Unsupported publication evidence basis")
    if (
        address.scheme != "https"
        or address.hostname != "www.stats.gov.cn"
        or re.fullmatch(r"/sj/zxfb/\d{6}/t\d{8}_[A-Za-z0-9]+\.html", address.path) is None
        or document.title.strip() != _text(spec["title"])
        or not document.title.strip().endswith(" - 国家统计局")
        or not publication_valid
        or visible_clock not in "".join(document.text_parts)
        or retrieved < published
    ):
        raise ValueError("Official document identity or publication evidence differs")
    available = published.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    rows = document.rows
    parsed: dict[str, float] = {}
    if spec["parser"] == "nbs_pmi_table":
        if len(rows) < 2 or "单位：%" not in rows[0] or rows[1][1:2] != ["PMI"]:
            raise ValueError("PMI table identity or unit differs")
        for row in rows:
            match = re.fullmatch(r"(\d{4})年(\d{1,2})月", row[0])
            if match and len(row) >= 2:
                period = f"{int(match[1]):04d}-{int(match[2]):02d}"
                if period in parsed:
                    raise ValueError("Duplicate PMI observation")
                parsed[period] = _number(row[1])
    elif spec["parser"] == "nbs_cpi_yoy":
        match = re.search(r"(\d{4})年(\d{1,2})月份居民消费价格", document.title)
        if (
            match is None
            or len(rows) < 2
            or rows[0][2:3] != ["同比涨跌幅（%）"]
            or rows[1][:1] != ["居民消费价格"]
            or len(rows[1]) < 3
        ):
            raise ValueError("National CPI year-on-year column differs")
        period = f"{int(match[1]):04d}-{int(match[2]):02d}"
        value = _number(rows[1][2])
        narrative = re.search(
            rf"(?:{int(match[1])}年|(?<![\d年])){int(match[2])}月份，"
            r"[^。；]*?全国居民消费价格同比"
            r"(?:(上涨|下降)(\d+(?:\.\d+)?)%|持平)(?=[。，；])",
            re.sub(r"\s+", "", "".join(document.text_parts)),
        )
        narrative_value = (
            None
            if narrative is None
            else (
                0.0
                if narrative[1] is None
                else _number(narrative[2]) * (-1 if narrative[1] == "下降" else 1)
            )
        )
        if narrative_value != value:
            raise ValueError("CPI narrative and table disagree")
        parsed[period] = value
    else:
        raise ValueError("Unsupported frozen document parser")
    result: list[PITFactVersion] = []
    for item in _array(spec["observations"]):
        observation = _object(item)
        period, value = _text(observation["period"]), _number(observation["value"])
        if parsed.get(period) != value:
            raise ValueError("Declared observation differs from original document")
        year, month = map(int, period.split("-"))
        effective = datetime(year, month, calendar.monthrange(year, month)[1], tzinfo=SHANGHAI)
        if effective > available:
            raise ValueError("Observation period follows its availability")
        indicator = _text(spec["indicator"])
        result.append(
            PITFactVersion(
                version_id=first_id + len(result),
                dataset="macro",
                business_key=indicator + ":" + period,
                effective_at=effective,
                effective_to=None,
                available_at=available,
                ingested_at=retrieved,
                superseded_at=None,
                revision_number=0,
                source_record_id=url + "#" + period,
                content_hash=_text(spec["sha256"]),
                pit_quality=PITQuality.VERIFIED,
                payload={
                    "indicator": indicator,
                    "period": period,
                    "value": value,
                    "unit": _text(spec["unit"]),
                    "availability_basis": "official_dated_release_next_calendar_day",
                    "source_first_publication_at": None,
                    "source_revision_number": None,
                    "historical_system_known_at": None,
                    "independent_historical_capture_at": None,
                    "research_only": True,
                },
            )
        )
    return result


def _archive_sample(spec: dict[str, Any], evidence: Path) -> dict[str, object]:
    raw = _verified_file(evidence, spec["raw_path"], spec["sha256"])
    cdx_raw = _verified_file(evidence, spec["cdx_path"], spec["cdx_sha256"])
    rows = _array(json.loads(cdx_raw))
    if len(rows) != 2:
        raise ValueError("Archive sample requires one exact CDX row")
    record = dict(
        zip((_text(x) for x in _array(rows[0])), (_text(x) for x in _array(rows[1])), strict=True)
    )
    if (
        record.get("statuscode") != "200"
        or record.get("original") != spec["original_url"]
        or record.get("digest") != base64.b32encode(hashlib.sha1(raw).digest()).decode()
        or _text(spec["required_text"]) not in raw.decode("utf-8")
    ):
        raise ValueError("Archive body, original identity or CDX digest differs")
    captured = datetime.strptime(record["timestamp"], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    return {
        "public_usable_from": captured.astimezone(SHANGHAI).isoformat(),
        "source_first_publication_at": None,
        "historical_system_known_at": None,
        "required_for_regime": False,
        "payload_sha256": _hash(raw),
    }


def _history_choice(
    facts: list[PITFactVersion], cutoff: datetime, scope: KnowledgeScope
) -> PITFactVersion | None:
    def order(fact: PITFactVersion) -> tuple[datetime, int, int]:
        clock = fact.available_at if scope is KnowledgeScope.PUBLIC else fact.ingested_at
        assert clock is not None
        return clock, fact.revision_number, fact.version_id

    eligible = [
        fact
        for fact in facts
        if fact.pit_quality is PITQuality.VERIFIED
        and fact.effective_at <= cutoff
        and (fact.effective_to is None or cutoff < fact.effective_to)
        and (
            (fact.available_at is not None and fact.available_at <= cutoff)
            if scope is KnowledgeScope.PUBLIC
            else fact.ingested_at <= cutoff
        )
    ]
    return max(eligible, key=order) if eligible else None


def _history_identity(fact: PITFactVersion | None) -> dict[str, object] | None:
    if fact is None:
        return None
    return {
        "content_hash": fact.content_hash,
        "source_record_id": fact.source_record_id,
        "value": _number(fact.payload["value"]),
        "available_at": fact.available_at.isoformat() if fact.available_at else None,
        "ingested_at": fact.ingested_at.isoformat(),
    }


def _run_history_audit(
    recipe: dict[str, Any], recipe_raw: bytes, evidence_dir: Path, *, code_root: Path = REPO
) -> dict[str, Any]:
    binding = _object(recipe["base_recipe"])
    base = _object(json.loads(_verified_file(evidence_dir, binding["raw_path"], binding["sha256"])))
    binding = _object(recipe["query_freeze"])
    freeze = _object(
        json.loads(_verified_file(evidence_dir, binding["raw_path"], binding["sha256"]))
    )
    base_dir = (evidence_dir / _text(recipe["base_evidence_dir"])).resolve()
    if not base_dir.is_relative_to(evidence_dir.resolve()):
        raise ValueError("Base evidence escapes its declared root")
    for item in _array(recipe["code_inputs"]):
        code = _object(item)
        if code.get("hash_basis") != "lf_normalized_bytes":
            raise ValueError("Code input must declare portable LF hash semantics")
        _verified_file(code_root, code["path"], code["sha256"], normalize_newlines=True)
    targets = [_object(item) for item in _array(freeze["targets"])]
    labels = [_text(target["label"]) for target in targets]
    if len(set(labels)) != len(labels):
        raise ValueError("Duplicate historical target")
    raw_captures = recipe["captures"]
    if not isinstance(raw_captures, list):
        raise ValueError("Captures must be an explicit list, possibly empty")
    captures = [_object(item) for item in raw_captures]
    if any(capture["label"] not in labels for capture in captures):
        raise ValueError("Capture is outside frozen targets")
    outputs: list[dict[str, Any]] = []
    count = 0
    for target in targets:
        source = _object(target["source"])
        if source not in _array(base["sources"]) or source["label"] != target["label"]:
            raise ValueError("Target differs from frozen source recipe")
        cutoff = _clock(target["cutoff"])
        indicator, period = _text(target["business_key"]).split(":", 1)
        if not any(
            _clock(_object(case)["at"]) == cutoff
            and period in _object(_object(case)["expected_periods"]).get(indicator, [])
            for case in _array(base["cutoffs"])
        ):
            raise ValueError("Historical cutoff/key is outside the frozen grid")
        current = [
            fact
            for fact in _source_facts(source, base_dir, 1)
            if fact.business_key == target["business_key"]
        ]
        if len(current) != 1:
            raise ValueError("Historical target must identify exactly one source fact")
        asserted = current[0]
        facts = [
            replace(
                asserted,
                available_at=None,
                pit_quality=PITQuality.UNKNOWN,
                payload=dict(
                    asserted.payload,
                    source_published_at=source["published_at"],
                    source_title=source["title"],
                ),
            )
        ]
        seen: set[tuple[str, str]] = set()
        for capture in captures:
            if capture["label"] != target["label"]:
                continue
            document = _object(capture["source"])
            original = _text(capture["original_url"])
            if (
                original not in _array(target["addresses"])
                or original.replace("http:", "https:", 1) != source["url"]
                or any(
                    document[key] != source[key] for key in ("url", "indicator", "unit", "parser")
                )
                or any(capture[key] != document[key] for key in ("raw_path", "sha256"))
                or capture["required_text"] != document["title"]
            ):
                raise ValueError("Capture document identity differs from admitted source")
            archive = _archive_sample(capture, evidence_dir)
            captured = _clock(archive["public_usable_from"])
            if not _clock(document["published_at"]) <= captured <= _clock(document["retrieved_at"]):
                raise ValueError("Capture clock contradicts publication or actual retrieval")
            identity = (original, captured.isoformat())
            if identity in seen:
                raise ValueError("Duplicate historical capture")
            seen.add(identity)
            versions = _source_facts(document, evidence_dir, len(facts) + 1)
            if len(versions) != 1 or versions[0].business_key != asserted.business_key:
                raise ValueError("Capture must contain the exact frozen target key")
            version = versions[0]
            if version.available_at is None:
                raise ValueError("Capture lacks source publication availability")
            facts.append(
                replace(
                    version,
                    available_at=max(version.available_at, captured),
                    source_record_id=original + "#" + period + "@" + captured.isoformat(),
                    payload=dict(
                        version.payload,
                        independent_historical_capture_at=captured.isoformat(),
                        source_published_at=document["published_at"],
                        source_title=document["title"],
                        availability_basis="verified_archive_capture_and_source_date",
                    ),
                )
            )
        public = _history_choice(facts, cutoff, KnowledgeScope.PUBLIC)
        system = _history_choice(facts, cutoff, KnowledgeScope.SYSTEM)
        versions_out: list[dict[str, object]] = []
        for fact in facts:
            identity_out = _history_identity(fact)
            assert identity_out is not None
            reason = (
                "independent_capture_unproved"
                if fact.pit_quality is PITQuality.UNKNOWN
                else (
                    "after_cutoff"
                    if fact.available_at is None or fact.available_at > cutoff
                    else (
                        "not_effective"
                        if fact.effective_at > cutoff
                        else "selected" if fact == public else "superseded_by_later_eligible"
                    )
                )
            )
            versions_out.append(
                dict(
                    identity_out,
                    public_result=reason,
                    published_at=_text(fact.payload["source_published_at"]),
                    title=_text(fact.payload["source_title"]),
                    independent_capture_at=fact.payload["independent_historical_capture_at"],
                    same_date_as_current=fact.payload["source_published_at"]
                    == source["published_at"],
                    same_title_as_current=fact.payload["source_title"] == source["title"],
                    same_bytes_as_current=fact.content_hash == asserted.content_hash,
                    same_value_as_current=fact.payload["value"] == asserted.payload["value"],
                )
            )
        count += len(facts)
        outputs.append(
            {
                "label": target["label"],
                "business_key": asserted.business_key,
                "at": cutoff.isoformat(),
                "source_asserted_public": _history_identity(
                    _history_choice([asserted], cutoff, KnowledgeScope.PUBLIC)
                ),
                "independent_public": _history_identity(public),
                "system": _history_identity(system),
                "versions": versions_out,
            }
        )
    return {
        "recipe_sha256": _hash(recipe_raw),
        "fact_count": count,
        "cutoffs": outputs,
        "database_writes": 0,
        "canonical_registration": False,
        "production_eligibility": False,
        "first_publication": None,
        "revision_history_complete": None,
        "historical_system_clock": None,
        "evidence_basis": "Bounded named archive versions; separate from source-asserted PUBLIC and historical SYSTEM qualification.",
    }


def _bound_root(evidence: Path, relative: object) -> Path:
    root = (evidence / _text(relative)).resolve()
    if not root.is_relative_to(evidence.resolve()):
        raise ValueError("Code evidence escapes its declared root")
    return root


def _verify_code(recipe: dict[str, Any], root: Path) -> None:
    for item in _array(recipe["code_inputs"]):
        code = _object(item)
        if code.get("hash_basis") != "lf_normalized_bytes":
            raise ValueError("Code input must declare portable LF hash semantics")
        _verified_file(root, code["path"], code["sha256"], normalize_newlines=True)


def _qualification_manifest(
    cutoff: datetime,
    scope: KnowledgeScope,
    expected: dict[str, list[str]],
    selected: list[PITFactVersion],
    missing: list[dict[str, str]],
    recipe_hash: str,
) -> PITDatasetManifest:
    manifest = PITDatasetManifest(
        manifest_id="local-ref05-history-" + scope.value + "-" + cutoff.isoformat(),
        as_of_time=cutoff,
        knowledge_scope=scope,
        calendar_version="recipe-observation-grid-not-execution-calendar",
        query_spec={"macro": {"recipe_sha256": recipe_hash, "expected_periods": expected}},
        selected_versions=tuple(
            dict(
                _history_identity(fact) or {},
                id=fact.version_id,
                dataset=fact.dataset,
                business_key=fact.business_key,
                pit_quality=fact.pit_quality.value,
                payload_hash=_json_hash(fact.payload),
            )
            for fact in selected
        ),
        coverage={
            indicator: sum(f.business_key.startswith(indicator + ":") for f in selected)
            / len(periods)
            for indicator, periods in expected.items()
        },
        missing=tuple(dict(item) for item in missing),
        estimated=(),
        unknown=tuple(dict(item) for item in missing),
        manifest_hash="",
    )
    return replace(manifest, manifest_hash=calculate_pit_manifest_hash(manifest))


def _run_history_projection(
    recipe: dict[str, Any], recipe_raw: bytes, evidence_dir: Path
) -> dict[str, Any]:
    _verify_code(recipe, REPO)
    binding = _object(recipe["history_recipe"])
    history_raw = _verified_file(evidence_dir, binding["raw_path"], binding["sha256"])
    history = _object(json.loads(history_raw))
    if history.get("schema") != "ref05.history-audit.v1":
        raise ValueError("Projection requires the frozen history audit recipe")
    audit = _run_history_audit(
        history,
        history_raw,
        evidence_dir,
        code_root=_bound_root(evidence_dir, recipe["history_code_root"]),
    )
    binding = _object(history["base_recipe"])
    base = _object(json.loads(_verified_file(evidence_dir, binding["raw_path"], binding["sha256"])))
    if base.get("schema") != "ref05.public-replay.v1":
        raise ValueError("Projection requires the frozen PUBLIC source recipe")
    _verify_code(base, _bound_root(evidence_dir, recipe["base_code_root"]))
    base_dir = _bound_root(evidence_dir, history["base_evidence_dir"])
    if "grid_freeze" in base:
        binding = _object(base["grid_freeze"])
        frozen = _object(
            json.loads(_verified_file(base_dir, binding["raw_path"], binding["sha256"]))
        )
        if any(base[key] != frozen[key] for key in ("cutoffs", "roles", "parameters")):
            raise ValueError("Projection differs from frozen grid or configuration")
    current: dict[str, PITFactVersion] = {}
    for source in _array(base["sources"]):
        for fact in _source_facts(_object(source), base_dir, len(current) + 1):
            if fact.business_key in current:
                raise ValueError("Duplicate business keys in frozen document case")
            current[fact.business_key] = fact
    audited = {
        _text(_object(row)["business_key"]): _object(row) for row in _array(audit["cutoffs"])
    }
    if len(audited) != len(_array(audit["cutoffs"])):
        raise ValueError("Duplicate audited business key")
    versions: dict[str, list[PITFactVersion]] = {}
    for key, asserted in current.items():
        versions[key] = [replace(asserted, available_at=None, pit_quality=PITQuality.UNKNOWN)]
        if key not in audited:
            continue
        for raw_version in _array(audited[key]["versions"]):
            version = _object(raw_version)
            if version["independent_capture_at"] is None:
                continue
            versions[key].append(
                replace(
                    asserted,
                    version_id=len(current) + sum(len(v) - 1 for v in versions.values()) + 1,
                    available_at=_clock(version["available_at"]),
                    ingested_at=_clock(version["ingested_at"]),
                    source_record_id=_text(version["source_record_id"]),
                    content_hash=_text(version["content_hash"]),
                    payload=dict(
                        asserted.payload,
                        value=_number(version["value"]),
                        independent_historical_capture_at=version["independent_capture_at"],
                        source_published_at=version["published_at"],
                        source_title=version["title"],
                        availability_basis="verified_archive_capture_and_source_date",
                    ),
                )
            )
    roles = [_text(value) for value in _object(base["roles"]).values()]
    if len(roles) != 2 or len(set(roles)) != 2:
        raise ValueError("Expected two distinct frozen input roles")
    outputs: list[dict[str, Any]] = []
    seen: set[datetime] = set()
    for raw_case in _array(base["cutoffs"]):
        case = _object(raw_case)
        cutoff = _clock(case["at"])
        if cutoff in seen:
            raise ValueError("Duplicate observation cutoff")
        seen.add(cutoff)
        expected = {
            indicator: [_text(p) for p in _array(periods)]
            for indicator, periods in _object(case["expected_periods"]).items()
        }
        if set(expected) != set(roles) or any(
            periods != sorted(set(periods)) for periods in expected.values()
        ):
            raise ValueError(
                "Required grid keys must include ordered unique periods for both roles"
            )
        rows: list[dict[str, Any]] = []
        selected: list[PITFactVersion] = []
        missing: list[dict[str, str]] = []
        system_missing: list[dict[str, str]] = []
        for indicator, periods in expected.items():
            for period in periods:
                key = indicator + ":" + period
                facts = versions.get(key, [])
                chosen = _history_choice(facts, cutoff, KnowledgeScope.PUBLIC)
                reason = (
                    "no_independent_version_by_cutoff"
                    if key in audited
                    else "not_independently_audited"
                )
                if chosen is None:
                    missing.append({"business_key": key, "reason": reason})
                else:
                    selected.append(chosen)
                system_missing.append(
                    {"business_key": key, "reason": "historical_system_clock_unknown"}
                )
                candidates = []
                for fact in facts:
                    public_result = (
                        "independent_capture_unproved"
                        if fact.pit_quality is PITQuality.UNKNOWN
                        else (
                            "after_cutoff"
                            if fact.available_at is None or fact.available_at > cutoff
                            else (
                                "not_effective"
                                if fact.effective_at > cutoff
                                else (
                                    "selected" if fact == chosen else "superseded_by_later_eligible"
                                )
                            )
                        )
                    )
                    candidates.append(
                        dict(_history_identity(fact) or {}, public_result=public_result)
                    )
                source_asserted = (
                    _history_choice([current[key]], cutoff, KnowledgeScope.PUBLIC)
                    if key in current
                    else None
                )
                rows.append(
                    {
                        "business_key": key,
                        "audit_status": "audited" if key in audited else "unknown_not_audited",
                        "source_asserted_public": _history_identity(source_asserted),
                        "independent_public": _history_identity(chosen),
                        "blocking_reason": reason if chosen is None else None,
                        "versions": candidates,
                        "system": None,
                        "historical_system_known_at": None,
                    }
                )
        manifest = _qualification_manifest(
            cutoff, KnowledgeScope.PUBLIC, expected, selected, missing, _hash(recipe_raw)
        )
        system_manifest = _qualification_manifest(
            cutoff, KnowledgeScope.SYSTEM, expected, [], system_missing, _hash(recipe_raw)
        )
        outputs.append(
            {
                "at": cutoff.isoformat(),
                "keys": rows,
                "manifest_verified": manifest.is_verified,
                "manifest": asdict(manifest),
                "system_manifest_verified": system_manifest.is_verified,
                "system_manifest": asdict(system_manifest),
                "outcome": "qualified" if manifest.is_verified else "blocked",
            }
        )
    keys = [row for output in outputs for row in output["keys"]]
    return {
        "recipe_sha256": _hash(recipe_raw),
        "history_recipe_sha256": _hash(history_raw),
        "fact_count": sum(len(facts) for facts in versions.values()),
        "required_key_count": len(keys),
        "source_asserted_public_count": sum(
            row["source_asserted_public"] is not None for row in keys
        ),
        "independent_public_count": sum(row["independent_public"] is not None for row in keys),
        "verified_observation_count": sum(output["manifest_verified"] for output in outputs),
        "cutoffs": outputs,
        "missing_unknown_semantics": "Missing means no eligible version; unknown records the unresolved evidence for that same required key. Counts overlap.",
        "first_publication": None,
        "revision_history_complete": None,
        "historical_system_clock": None,
        "downstream_calculation_count": 0,
        "database_writes": 0,
        "canonical_registration": False,
        "production_eligibility": False,
        "evidence_basis": "Frozen named independent captures only; source assertions and SYSTEM clocks remain separate. Legacy recipes and their archived code are verified, never executed as current code.",
    }


def run_replay(recipe_path: Path, evidence_dir: Path) -> dict[str, Any]:
    """Verify exact external inputs and replay the tracked case without side effects."""
    recipe_raw = recipe_path.read_bytes()
    recipe = _object(json.loads(recipe_raw))
    if recipe.get("schema") == "ref05.history-projection.v1":
        return _run_history_projection(recipe, recipe_raw, evidence_dir)
    if recipe.get("schema") == "ref05.history-audit.v1":
        return _run_history_audit(recipe, recipe_raw, evidence_dir)
    if recipe.get("schema") != "ref05.public-replay.v1":
        raise ValueError("Unsupported replay recipe")
    if "grid_freeze" in recipe:
        binding = _object(recipe["grid_freeze"])
        frozen = _object(
            json.loads(_verified_file(evidence_dir, binding["raw_path"], binding["sha256"]))
        )
        if any(recipe[key] != frozen[key] for key in ("cutoffs", "roles", "parameters")):
            raise ValueError("Replay differs from the frozen observation grid or configuration")
    for item in _array(recipe["code_inputs"]):
        code = _object(item)
        if code.get("hash_basis") != "lf_normalized_bytes":
            raise ValueError("Code input must declare portable LF hash semantics")
        _verified_file(REPO, code["path"], code["sha256"], normalize_newlines=True)
    params = {key: _number(value) for key, value in _object(recipe["parameters"]).items()}
    calculator = RegimeCalculatorV2(ThresholdConfig(**params))
    roles = _object(recipe["roles"])
    growth, inflation = _text(roles["growth"]), _text(roles["inflation"])
    if growth == inflation:
        raise ValueError("Growth and inflation inputs must differ")
    facts: list[PITFactVersion] = []
    for source in _array(recipe["sources"]):
        facts.extend(_source_facts(_object(source), evidence_dir, len(facts) + 1))
    if len({fact.business_key for fact in facts}) != len(facts):
        raise ValueError("Duplicate business keys in frozen document case")
    outputs: list[dict[str, Any]] = []
    seen_cutoffs: set[datetime] = set()
    for item in _array(recipe["cutoffs"]):
        case = _object(item)
        cutoff = _clock(case["at"])
        if cutoff in seen_cutoffs:
            raise ValueError("Duplicate observation cutoff")
        seen_cutoffs.add(cutoff)
        expected = _object(case["expected_periods"])
        if set(expected) != {growth, inflation}:
            raise ValueError("Expected keys must include both exact input roles")
        selected: dict[str, list[PITFactVersion]] = {}
        for indicator in (growth, inflation):
            periods = [_text(p) for p in _array(expected[indicator])]
            if len(set(periods)) != len(periods) or periods != sorted(periods):
                raise ValueError("Expected periods must be unique and ordered")
            eligible = sorted(
                (
                    fact
                    for fact in facts
                    if fact.payload["indicator"] == indicator
                    and fact.available_at is not None
                    and fact.available_at <= cutoff
                    and fact.effective_at <= cutoff
                ),
                key=lambda fact: fact.effective_at,
            )[-len(periods) :]
            if [fact.payload["period"] for fact in eligible] != periods:
                raise ValueError("Missing or future input in required observation grid")
            selected[indicator] = eligible
        members = sorted(
            (fact for values in selected.values() for fact in values),
            key=lambda fact: fact.version_id,
        )
        manifest = PITDatasetManifest(
            manifest_id="local-ref05-" + cutoff.isoformat(),
            as_of_time=cutoff,
            knowledge_scope=KnowledgeScope.PUBLIC,
            calendar_version="recipe-observation-grid-not-execution-calendar",
            query_spec={
                "macro": {"recipe_sha256": _hash(recipe_raw), "expected_periods": expected}
            },
            selected_versions=tuple(
                {
                    "id": fact.version_id,
                    "dataset": fact.dataset,
                    "business_key": fact.business_key,
                    "content_hash": fact.content_hash,
                    "payload_hash": _json_hash(fact.payload),
                    "pit_quality": fact.pit_quality.value,
                }
                for fact in members
            ),
            coverage={key: len(selected[key]) / len(_array(expected[key])) for key in selected},
            missing=(),
            estimated=(),
            unknown=(),
            manifest_hash="",
        )
        manifest = replace(manifest, manifest_hash=calculate_pit_manifest_hash(manifest))
        if not manifest.is_verified:
            raise ValueError("Local diagnostic manifest failed verification")
        result = calculator.calculate(
            [_number(f.payload["value"]) for f in selected[growth]],
            [_number(f.payload["value"]) for f in selected[inflation]],
            cutoff.date(),
        )
        result_payload = asdict(result)
        result_payload["regime"] = result.regime.value
        outputs.append(
            {
                "at": cutoff.isoformat(),
                "selected_count": len(members),
                "manifest_verified": True,
                "manifest_hash": manifest.manifest_hash,
                "manifest": asdict(manifest),
                "selected": {
                    k: [
                        dict(
                            f.payload,
                            available_at=f.available_at.isoformat() if f.available_at else None,
                        )
                        for f in v
                    ]
                    for k, v in selected.items()
                },
                "system_visible_fact_count": sum(
                    f.ingested_at <= cutoff and f.effective_at <= cutoff for f in facts
                ),
                "result": result_payload,
            }
        )
    return {
        "recipe_sha256": _hash(recipe_raw),
        "fact_count": len(facts),
        "cutoffs": outputs,
        "archive_sample": (
            _archive_sample(_object(recipe["archive_sample"]), evidence_dir)
            if "archive_sample" in recipe
            else None
        ),
        "database_writes": 0,
        "canonical_registration": False,
        "production_eligibility": False,
        "evidence_basis": "Official source dates and independent archive capture are distinct; see tracked recipe scope.",
    }


def main(argv: list[str] | None = None) -> int:
    """Write one new replay report or fail without overwriting existing evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recipe", type=Path, default=REPO / "docs/reviews/ref05-public-replay-20261108.json"
    )
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError("Output already exists")
        result = run_replay(args.recipe, args.evidence_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, default=str)
            stream.write("\n")
    except (ValueError, TypeError, KeyError, IndexError, OSError) as error:
        print(f"Replay error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "fact_count": result["fact_count"],
                "cutoff_count": len(result["cutoffs"]),
                "output": str(args.output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

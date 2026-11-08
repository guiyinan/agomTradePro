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


def _verified_file(root: Path, relative: object, expected_hash: object) -> bytes:
    path = (root / _text(relative)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Evidence path escapes its declared root")
    raw = path.read_bytes()
    if _hash(raw) != _text(expected_hash):
        raise ValueError(f"Evidence hash mismatch: {relative}")
    return raw


class ReleaseDocument(HTMLParser):
    """Extract source metadata and the first table without optional HTML packages."""

    def __init__(self, raw: bytes) -> None:
        """Parse one captured UTF-8 document into detached source fields."""
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.publication = ""
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
    if (
        address.scheme != "https"
        or address.hostname != "www.stats.gov.cn"
        or not address.path.startswith("/sj/zxfb/")
        or f"t{published:%Y%m%d}_" not in address.path
        or document.title.strip() != _text(spec["title"])
        or not document.title.strip().endswith(" - 国家统计局")
        or document.publication != published.strftime("%Y/%m/%d %H:%M")
        or document.publication not in "".join(document.text_parts)
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
        value_text = rows[1][2]
        narrative = f"{int(match[1])}年{int(match[2])}月份，全国居民消费价格同比上涨{value_text}%"
        if narrative not in re.sub(r"\s+", "", "".join(document.text_parts)):
            raise ValueError("CPI narrative and table disagree")
        parsed[period] = _number(value_text)
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


def run_replay(recipe_path: Path, evidence_dir: Path) -> dict[str, Any]:
    """Verify exact external inputs and replay the tracked case without side effects."""
    recipe_raw = recipe_path.read_bytes()
    recipe = _object(json.loads(recipe_raw))
    if recipe.get("schema") != "ref05.public-replay.v1":
        raise ValueError("Unsupported replay recipe")
    for item in _array(recipe["code_inputs"]):
        code = _object(item)
        _verified_file(REPO, code["path"], code["sha256"])
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
        "archive_sample": _archive_sample(_object(recipe["archive_sample"]), evidence_dir),
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

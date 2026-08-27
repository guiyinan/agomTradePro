"""Check TUX-05 field translation and internal screen-locator boundaries."""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLISHED_PATH = ROOT / "config/tui/published/tui_operation_graph.published.json"
DEFAULT_GENERATED_PATH = ROOT / "config/tui/generated/tui_operation_graph.generated.json"
DEFAULT_TEMPLATE_PATH = ROOT / "core/templates/terminal/tui_workbench.html"
DEFAULT_RUNTIME_CONSTANTS_PATH = ROOT / "apps/terminal/application/tui_workbench_constants.py"
DEFAULT_COMPILER_PATH = ROOT / "tui-metadata-compiler/scripts/generate_tui_metadata.py"

AUDITED_FIELD_LABELS: dict[str, str] = {
    "active_today_count": "今日生效数量",
    "effective_today_count": "今日生效数量",
    "global_gate_level": "全球闸门等级",
    "global_heat_score": "全球热度评分",
    "global_sentiment_score": "全球情绪评分",
    "last_fetch_at": "最近抓取时间",
    "last_fetch_status": "最近抓取状态",
    "model": "模型",
    "must_not_use_for_decision": "禁止用于决策",
    "owner_user_id": "所有者用户ID",
    "pending_review_count": "待审核数量",
    "provider_name": "服务商名称",
    "provider_scope": "服务商范围",
    "quota_charged": "已计入配额",
    "request_type": "请求类型",
    "sla_exceeded_count": "SLA 超时数量",
    "strict_freshness": "严格时效校验",
    "user_id": "用户ID",
    "username": "用户名",
}
FORBIDDEN_FIELD_FRAGMENTS = (
    "Active Today",
    "ActiveToday",
    "Effective Today",
    "EffectiveToday",
    "Global Gate",
    "Global Heat",
    "Global Sentiment",
    "GlobalGate",
    "GlobalHeat",
    "GlobalSentiment",
    "Last Fetch",
    "LastFetch",
    "Must Not Use For Decision",
    "MustNotUseFor",
    "Pending Review",
    "PendingReview",
    "Quota Charged",
    "QuotaCharged",
    "Sla Exceeded",
    "SlaExceeded",
    "Strict Freshness",
    "User Id",
)
INTERNAL_LOCATOR_MARKERS = (
    "data-current-location",
    'id="tui-location-input"',
    "screen:boot",
)


@dataclass(frozen=True)
class TuiPresentationViolation:
    """One deterministic TUX-05 presentation violation."""

    rule_id: str
    source: str
    message: str
    action_key: str = ""
    field_key: str = ""


@dataclass(frozen=True)
class TuiPresentationReport:
    """Stable machine-readable TUX-05 field and internal-key report."""

    outcome: str
    audited_field_count: int
    graph_field_occurrence_count: int
    raw_field_name_count: int
    internal_screen_locator_count: int
    violations: tuple[TuiPresentationViolation, ...]

    @property
    def passed(self) -> bool:
        """Return whether every TUX-05 machine presentation rule passed."""

        return not self.violations

    def as_json(self) -> dict[str, Any]:
        """Return a stable JSON-compatible report."""

        return {
            "outcome": self.outcome,
            "passed": self.passed,
            "audited_field_count": self.audited_field_count,
            "graph_field_occurrence_count": self.graph_field_occurrence_count,
            "raw_field_name_count": self.raw_field_name_count,
            "internal_screen_locator_count": self.internal_screen_locator_count,
            "violations": [asdict(item) for item in self.violations],
        }


def _load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _literal_mapping(path: Path, variable_name: str) -> dict[str, str]:
    """Read one literal string mapping without importing production modules."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == variable_name for target in node.targets
        ):
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, dict):
            break
        return {
            str(key): str(item)
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, str)
        }
    raise ValueError(f"Literal mapping {variable_name} not found in {path}")


def _mapping_violations(
    *,
    source: str,
    labels: Mapping[str, str],
) -> list[TuiPresentationViolation]:
    """Return missing or divergent audited source-label violations."""

    violations: list[TuiPresentationViolation] = []
    for field_key, expected_label in sorted(AUDITED_FIELD_LABELS.items()):
        actual_label = labels.get(field_key)
        if actual_label == expected_label:
            continue
        violations.append(
            TuiPresentationViolation(
                rule_id="field_translation:source_mapping",
                source=source,
                field_key=field_key,
                message=f"expected {expected_label!r}, found {actual_label!r}",
            )
        )
    return violations


def _graph_violations(
    *,
    source: str,
    payload: Mapping[str, Any],
) -> tuple[int, int, list[TuiPresentationViolation]]:
    """Check reviewed graph fields and return occurrences, raw count, violations."""

    occurrences = 0
    raw_count = 0
    violations: list[TuiPresentationViolation] = []
    actions = payload.get("actions", [])
    if not isinstance(actions, Sequence) or isinstance(actions, str | bytes):
        return occurrences, raw_count, violations
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        action_key = str(action.get("key") or "")
        fields = action.get("fields", [])
        if not isinstance(fields, Sequence) or isinstance(fields, str | bytes):
            continue
        for field in fields:
            if not isinstance(field, Mapping):
                continue
            field_key = str(field.get("key") or "")
            label = str(field.get("label") or "")
            placeholder = str(field.get("placeholder") or "")
            visible_copy = f"{label}\n{placeholder}"
            if field_key in AUDITED_FIELD_LABELS:
                occurrences += 1
                expected_label = AUDITED_FIELD_LABELS[field_key]
                if label != expected_label:
                    violations.append(
                        TuiPresentationViolation(
                            rule_id="field_translation:graph_label",
                            source=source,
                            action_key=action_key,
                            field_key=field_key,
                            message=f"expected {expected_label!r}, found {label!r}",
                        )
                    )
            exposed = sorted(
                fragment for fragment in FORBIDDEN_FIELD_FRAGMENTS if fragment in visible_copy
            )
            if not exposed:
                continue
            raw_count += 1
            violations.append(
                TuiPresentationViolation(
                    rule_id="field_translation:raw_fragment",
                    source=source,
                    action_key=action_key,
                    field_key=field_key,
                    message=f"visible field copy exposes: {', '.join(exposed)}",
                )
            )
    return occurrences, raw_count, violations


def check_tui_presentation_details(
    *,
    published_payload: Mapping[str, Any],
    generated_payload: Mapping[str, Any],
    runtime_labels: Mapping[str, str],
    compiler_labels: Mapping[str, str],
    template_text: str,
) -> TuiPresentationReport:
    """Evaluate the deterministic TUX-05 machine presentation contract."""

    violations = [
        *_mapping_violations(source="runtime", labels=runtime_labels),
        *_mapping_violations(source="compiler", labels=compiler_labels),
    ]
    graph_field_occurrence_count = 0
    raw_field_name_count = 0
    for source, payload in (
        ("published", published_payload),
        ("generated", generated_payload),
    ):
        occurrences, raw_count, graph_issues = _graph_violations(
            source=source,
            payload=payload,
        )
        graph_field_occurrence_count += occurrences
        raw_field_name_count += raw_count
        violations.extend(graph_issues)

    internal_screen_locator_count = 0
    for marker in INTERNAL_LOCATOR_MARKERS:
        count = template_text.count(marker)
        internal_screen_locator_count += count
        if count:
            violations.append(
                TuiPresentationViolation(
                    rule_id="internal_key:visible_locator",
                    source="template",
                    message=f"visible shell contains {marker!r} {count} time(s)",
                )
            )

    ordered = tuple(
        sorted(
            violations,
            key=lambda item: (
                item.rule_id,
                item.source,
                item.action_key,
                item.field_key,
                item.message,
            ),
        )
    )
    return TuiPresentationReport(
        outcome="ok" if not ordered else "blocked",
        audited_field_count=len(AUDITED_FIELD_LABELS),
        graph_field_occurrence_count=graph_field_occurrence_count,
        raw_field_name_count=raw_field_name_count,
        internal_screen_locator_count=internal_screen_locator_count,
        violations=ordered,
    )


def build_report(
    *,
    published_path: Path = DEFAULT_PUBLISHED_PATH,
    generated_path: Path = DEFAULT_GENERATED_PATH,
    template_path: Path = DEFAULT_TEMPLATE_PATH,
    runtime_constants_path: Path = DEFAULT_RUNTIME_CONSTANTS_PATH,
    compiler_path: Path = DEFAULT_COMPILER_PATH,
) -> TuiPresentationReport:
    """Load repository sources and build the read-only TUX-05 report."""

    return check_tui_presentation_details(
        published_payload=_load_json(published_path),
        generated_payload=_load_json(generated_path),
        runtime_labels=_literal_mapping(runtime_constants_path, "FIELD_LABELS"),
        compiler_labels=_literal_mapping(compiler_path, "FIELD_LABELS"),
        template_text=template_path.read_text(encoding="utf-8"),
    )


def main() -> int:
    """Run the TUX-05 presentation guard and emit stable JSON."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--published", type=Path, default=DEFAULT_PUBLISHED_PATH)
    parser.add_argument("--generated", type=Path, default=DEFAULT_GENERATED_PATH)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE_PATH)
    args = parser.parse_args()
    report = build_report(
        published_path=args.published,
        generated_path=args.generated,
        template_path=args.template,
    )
    print(json.dumps(report.as_json(), ensure_ascii=False, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

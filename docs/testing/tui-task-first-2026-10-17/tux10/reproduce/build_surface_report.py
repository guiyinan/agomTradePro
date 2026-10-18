"""Project an actual TUX10 safe metadata inventory into a reviewable CSV and note."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def main() -> int:
    """Write full key coverage without turning declarations into action acceptance."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    data: dict[str, Any] = json.loads(raw)
    assert data["schema"] == "tux10-surface-inventory.v3"
    screens = data["screens"]
    actions = data["actions"]
    assert len({row["key"] for row in screens}) == len(screens)
    assert len({row["key"] for row in actions}) == len(actions)
    args.output.mkdir(parents=True, exist_ok=True)
    csv_path = args.output / "capability-placement.csv"
    note_path = args.output / "capability-placement.md"
    assert not csv_path.exists() and not note_path.exists(), "Do not overwrite evidence"
    labels = {
        "task_reuse": "任务复用",
        "professional_retained": "专业保留",
        "admin_governance": "管理员治理",
        "diagnostics": "诊断",
        "review_dedupe": "待审查去重",
    }
    fields = [
        "kind",
        "key",
        "label",
        "surface",
        "surface_label",
        "surface_basis",
        "owner_refs",
        "roles",
        "task_entry_action_references",
        "record_sha256",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for kind, rows in (("screen", screens), ("action", actions)):
            for row in rows:
                writer.writerow(
                    {
                        "kind": kind,
                        "key": row["key"],
                        "label": row.get("label", ""),
                        "surface": row["surface"],
                        "surface_label": labels[row["surface"]],
                        "surface_basis": row.get("surface_basis", ""),
                        "owner_refs": json.dumps(
                            row.get("owner_refs", {}), ensure_ascii=False, sort_keys=True
                        ),
                        "roles": json.dumps(
                            row.get("roles", {}), ensure_ascii=False, sort_keys=True
                        ),
                        "task_entry_action_references": json.dumps(
                            row.get("task_entry_action_references", []),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "record_sha256": row["record_sha256"],
                    }
                )
    lines = [
        "# TUX10 能力去向清单",
        "",
        "本表来自实际发布与 runtime 组合 metadata，以及新建普通用户和超级管理员的已认证目录/详情读取。管理员快照表示本地最大权限表面，不代表所有 staff 账号。",
        "",
        "动作标为任务复用，要求 metadata 明确引用，且同一角色可见相应任务入口和引用屏幕内的动作。它证明声明与可见性，不证明浏览器执行、业务动作授权或生产成功读取。",
        "",
        "专业保留表示仍在授权目录/详情中；诊断权限另记于角色快照和动作的 diagnostic_policy_only；分类统计不根据 raw_debug 将业务对象推定为独立诊断入口。待审查去重及下列引用问题保持显式待审状态。",
        "",
        f"原始 JSON SHA-256：`{hashlib.sha256(raw).hexdigest()}`。",
        "",
        "| 分类 | screen | action |",
        "| --- | ---: | ---: |",
    ]
    screen_counts = Counter(row["surface"] for row in screens)
    action_counts = Counter(row["surface"] for row in actions)
    for key, label in labels.items():
        lines.append(f"| {label} | {screen_counts[key]} | {action_counts[key]} |")
    lines += [
        f"| 合计 | {len(screens)} | {len(actions)} |",
        "",
        "完整逐项归属、角色投影、task 引用及记录哈希见 `capability-placement.csv`；group/module/alias 与覆盖断言保留在原始 JSON。",
        "",
        "## 待审 workflow 引用",
        "",
    ]
    findings = data.get("workflow_review_findings", [])
    if findings:
        lines += [
            f"- `{item['screen_key']}` / `{item['relation']}` → `{item['declared_key']}`：{item['resolution_status']}。"
            for item in findings
        ]
    else:
        lines.append(
            "本次实际导出没有未解析的 workflow screen 引用。旧别名的原始 key、canonical key 和解析依据保留在 JSON 中。"
        )
    lines += [
        "",
        "本清单不替代五人上手试用、真实正常市场源、PostgreSQL、大组合性能或生产发布验收。",
        "",
    ]
    note_path.write_text("\n".join(lines), encoding="utf8")
    print(
        json.dumps(
            {
                "screens": len(screens),
                "actions": len(actions),
                "workflow_findings": len(findings),
                "csv": str(csv_path),
                "note": str(note_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

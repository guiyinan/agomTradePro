#!/usr/bin/env python
"""
本地 Qlib 推理结果上传工具

不依赖 Django，仅需 SDK。可以：
1. 运行 Qlib 推理并上传结果
2. 上传已有的 CSV/JSON 评分文件

用法示例：

  # 上传 JSON 文件（用户模式，只有自己可见）
  python tools/qlib_uploader.py \\
      --input scores.json \\
      --universe csi300 \\
      --date 2026-03-08 \\
      --base-url http://141.11.211.21:8000 \\
      --token YOUR_TOKEN

  # admin 上传全局评分
  python tools/qlib_uploader.py \\
      --input scores.json \\
      --universe csi300 \\
      --date 2026-03-08 \\
      --base-url http://141.11.211.21:8000 \\
      --token ADMIN_TOKEN \\
      --scope system

  # 运行 Qlib 推理并直接上传（需要 qlib 环境）
  python tools/qlib_uploader.py \\
      --model-path ./models/alpha_v1 \\
      --universe csi300 \\
      --date 2026-03-08 \\
      --base-url http://141.11.211.21:8000 \\
      --token YOUR_TOKEN

JSON 评分文件格式（scores.json）：
  [
    {"code": "000001.SZ", "score": 0.85, "rank": 1, "confidence": 0.9, "factors": {}},
    {"code": "000002.SZ", "score": 0.80, "rank": 2, "confidence": 0.88, "factors": {}},
    ...
  ]

CSV 评分文件格式（scores.csv）：
  code,score,rank,confidence
  000001.SZ,0.85,1,0.9
  000002.SZ,0.80,2,0.88
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "sdk"
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

try:
    from agomtradepro.client import AgomTradeProClient
except ImportError:
    print("Error: agomtradepro SDK not importable from ./sdk", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_from_json(filepath: str) -> list[dict[str, Any]]:
    """从 JSON 文件加载评分"""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON 文件必须是列表格式")
    return data


def load_from_csv(filepath: str) -> list[dict[str, Any]]:
    """从 CSV 文件加载评分（自动添加 rank 如果没有）"""
    scores = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            item: dict[str, Any] = {
                "code": row["code"],
                "score": float(row["score"]),
                "rank": int(row.get("rank", i)),
                "confidence": float(row.get("confidence", 1.0)),
                "source": row.get("source", "local_qlib"),
                "factors": json.loads(row["factors"]) if "factors" in row and row["factors"] else {},
            }
            scores.append(item)
    return scores


def load_from_file(filepath: str) -> list[dict[str, Any]]:
    """根据文件扩展名自动选择加载方式"""
    path = Path(filepath)
    if path.suffix.lower() == ".csv":
        return load_from_csv(filepath)
    elif path.suffix.lower() in (".json", ".jsonl"):
        return load_from_json(filepath)
    else:
        raise ValueError(f"不支持的文件格式: {path.suffix}，请使用 .json 或 .csv")


# ---------------------------------------------------------------------------
# Qlib inference (optional)
# ---------------------------------------------------------------------------

def run_qlib_inference(model_path: str, universe: str, infer_date: str) -> list[dict[str, Any]]:
    """
    运行 Qlib 推理，返回标准格式评分列表。

    Args:
        model_path: 模型目录或文件路径
        universe: 股票池（如 "csi300"）
        infer_date: 推理日期（ISO 格式）

    Returns:
        评分列表 [{code, score, rank, factors, confidence, source}, ...]
    """
    try:
        import qlib
        from qlib.config import REG_CN
    except ImportError:
        raise ImportError(
            "未安装 qlib。请先安装：pip install pyqlib\n"
            "或者使用 --input 参数上传已计算好的评分文件"
        )

    print(f"初始化 Qlib（universe={universe}, date={infer_date}）...")
    qlib.init(provider_uri="~/.qlib/qlib_data/cn_data", region=REG_CN)

    # 根据模型文件类型选择推理方式
    model_path_obj = Path(model_path)
    if not model_path_obj.exists():
        raise FileNotFoundError(f"模型路径不存在: {model_path}")

    print(f"加载模型: {model_path}")

    # 这里是 Qlib 推理的占位符逻辑
    # 实际使用时请根据你的模型类型替换：
    #
    # from qlib.contrib.model.gbdt import LGBModel
    # model = LGBModel()
    # model.load(model_path)
    # pred = model.predict(dataset)
    #
    # 以下为示例返回格式
    raise NotImplementedError(
        "Qlib 推理逻辑需要根据你的模型类型自定义实现。\n"
        "请修改 tools/qlib_uploader.py 中的 run_qlib_inference 函数，\n"
        "或使用 --input scores.json 上传预先计算好的评分。"
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def upload(
    scores: list[dict[str, Any]],
    universe_id: str,
    asof_date: str,
    intended_trade_date: str,
    model_id: str,
    model_artifact_hash: str,
    scope: str,
    base_url: str,
    token: str,
    timeout: int = 60,
) -> dict[str, Any]:
    """通过 SDK 上传评分到 VPS"""
    client = AgomTradeProClient(
        base_url=base_url,
        api_token=token,
        timeout=timeout,
    )
    print(f"通过 SDK 上传 {len(scores)} 条评分到 {base_url.rstrip('/')} (scope={scope})...")
    return client.alpha.upload_scores(
        scores=scores,
        universe_id=universe_id,
        asof_date=asof_date,
        intended_trade_date=intended_trade_date,
        model_id=model_id,
        model_artifact_hash=model_artifact_hash,
        scope=scope,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="本地 Qlib 推理结果上传工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # 数据来源（二选一）
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--input", "-i",
        metavar="FILE",
        help="上传已有评分文件（.json 或 .csv）",
    )
    source_group.add_argument(
        "--model-path", "-m",
        metavar="PATH",
        help="运行 Qlib 推理的模型路径",
    )

    # 必需参数
    parser.add_argument(
        "--universe", "-u",
        required=True,
        help="股票池标识，如 csi300、csi500",
    )
    parser.add_argument(
        "--date", "-d",
        required=True,
        metavar="YYYY-MM-DD",
        help="信号生成日期（asof_date），也作为计划交易日期",
    )

    # 可选参数
    parser.add_argument(
        "--trade-date",
        metavar="YYYY-MM-DD",
        help="计划交易日期（默认与 --date 相同）",
    )
    parser.add_argument(
        "--model-id",
        default="local_qlib",
        help="模型标识（默认 local_qlib）",
    )
    parser.add_argument(
        "--model-hash",
        default="",
        help="模型文件哈希（可选）",
    )
    parser.add_argument(
        "--scope",
        choices=["user", "system"],
        default="user",
        help="写入范围：user=个人（默认），system=全局（仅 admin）",
    )

    # 连接参数
    parser.add_argument(
        "--base-url",
        default="http://141.11.211.21:8000",
        help="VPS 地址（默认 http://141.11.211.21:8000）",
    )
    parser.add_argument(
        "--token",
        required=True,
        help="API Token（DRF Token Auth）",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="HTTP 超时秒数（默认 60）",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # 1. 获取评分数据
    if args.input:
        print(f"从文件加载评分: {args.input}")
        scores = load_from_file(args.input)
        print(f"加载完成: {len(scores)} 条")
    else:
        print(f"运行 Qlib 推理: model={args.model_path}, universe={args.universe}, date={args.date}")
        scores = run_qlib_inference(args.model_path, args.universe, args.date)
        print(f"推理完成: {len(scores)} 条")

    if not scores:
        print("错误: 评分列表为空", file=sys.stderr)
        sys.exit(1)

    # 2. 上传
    intended_trade_date = args.trade_date or args.date
    result = upload(
        scores=scores,
        universe_id=args.universe,
        asof_date=args.date,
        intended_trade_date=intended_trade_date,
        model_id=args.model_id,
        model_artifact_hash=args.model_hash,
        scope=args.scope,
        base_url=args.base_url,
        token=args.token,
        timeout=args.timeout,
    )

    # 3. 输出结果
    print("\n上传结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("success"):
        action = "新建" if result.get("created") else "更新"
        print(
            f"\n✓ 成功{action} {result['count']} 条评分"
            f"（scope={result['scope']}, id={result['id']}）"
        )
    else:
        print(f"\n✗ 上传失败: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

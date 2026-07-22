"""Command-line entry point for the standalone Windows QMT Agent."""

from __future__ import annotations

import argparse
import json
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .api_client import AgentApiClient
from .config import AgentConfig, load_agent_token
from .executor import QmtAgentExecutor
from .fake_adapter import FakeQmtAdapter
from .health import run_preflight, run_qmt_read_probe
from .qmt_adapter import XtQuantAdapter
from .state_store import AgentStateStore


def main() -> int:
    parser = argparse.ArgumentParser(description="AgomTradePro QMT Agent")
    parser.add_argument("--config", required=True)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument(
        "--qmt-read-probe",
        action="store_true",
        help="Connect to QMT and query account facts without submitting or canceling orders.",
    )
    parser.add_argument(
        "--evidence-file",
        help="Optional JSON output path for --preflight or --qmt-read-probe evidence.",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--fake",
        choices=["success", "reject", "unknown", "disconnect", "partial", "filled"],
    )
    args = parser.parse_args()
    config = AgentConfig.from_file(args.config)
    if args.preflight:
        report = run_preflight(config)
        _emit_report(report, args.evidence_file)
        return 0 if report["ready"] else 2
    if args.evidence_file and not args.qmt_read_probe:
        parser.error("--evidence-file requires --preflight or --qmt-read-probe")
    if args.qmt_read_probe:
        broker = (
            FakeQmtAdapter(args.fake)
            if args.fake
            else XtQuantAdapter(
                userdata_path=config.qmt_userdata_path,
                broker_account_id=config.broker_account_id,
                account_type=config.broker_account_type,
                qmt_client_version=config.qmt_client_version,
                xtquant_version=config.xtquant_version,
            )
        )
        report = run_qmt_read_probe(
            config,
            broker,
            adapter_name="fake" if args.fake else "xtquant",
        )
        _emit_report(report, args.evidence_file)
        return 0 if report["ready"] else 2
    config.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            RotatingFileHandler(
                config.log_dir / "qmt-agent.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=10,
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
    )
    broker = (
        FakeQmtAdapter(args.fake)
        if args.fake
        else XtQuantAdapter(
            userdata_path=config.qmt_userdata_path,
            broker_account_id=config.broker_account_id,
            account_type=config.broker_account_type,
            qmt_client_version=config.qmt_client_version,
            xtquant_version=config.xtquant_version,
        )
    )
    api = AgentApiClient(config, load_agent_token())
    state = AgentStateStore(config.state_dir / "agent-state.sqlite3")
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)
    try:
        executor.initialize()
        while True:
            try:
                executor.run_once()
            except Exception:
                logging.getLogger(__name__).exception(
                    "QMT Agent polling cycle failed; retrying conservatively"
                )
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(config.poll_interval_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        state.close()


def _emit_report(report: dict[str, Any], evidence_file: str | None) -> None:
    """Print and optionally persist one secret-free compatibility report."""

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if evidence_file:
        target = Path(evidence_file).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

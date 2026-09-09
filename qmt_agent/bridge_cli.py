"""User-facing pairing and collection commands within the unified Agent package."""

import argparse
import getpass
import json
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .api_client import AgentApiError
from .bridge_client import BridgeClient
from .bridge_worker import BridgeWorker, XtDataSource


def main(argv: list[str]) -> int:
    """Pair once, then run the market worker independently of the trading process."""
    parser = argparse.ArgumentParser(
        description="QMT bridge: user/server pairing and market collection"
    )
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--pair", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--server")
    parser.add_argument("--agent-id")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--backfill-start", default="")
    parser.add_argument("--backfill-end", default="")
    args = parser.parse_args(argv)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            RotatingFileHandler(
                args.state_dir / "market-bridge.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.pair or args.repair:
        if not args.server or not args.agent_id:
            parser.error("Pairing requires --server and --agent-id")
        client = BridgeClient(args.server)
        client.pair(
            getpass.getpass("One-time pairing code: "),
            args.agent_id,
            args.state_dir,
            repair=args.repair,
        )
        print("User and server bound. Approve market collection on the server before starting.")
        return 0
    if bool(args.backfill_start) != bool(args.backfill_end):
        parser.error("Backfill requires both start and end dates")
    client = BridgeClient.load(args.state_dir)
    worker = BridgeWorker(args.state_dir, client, XtDataSource())
    collected_history = False
    try:
        while True:
            try:
                result = worker.run_once(start=args.backfill_start, end=args.backfill_end)
                print(json.dumps(result))
                collected_history = collected_history or result.get("collected") is True
                if args.once:
                    return 2 if result["outcome"] == "blocked" else 0
                if (
                    args.backfill_start
                    and collected_history
                    and not result.get("pending_batches")
                    and result["outcome"] != "blocked"
                ):
                    return 0
                time.sleep(int(str(result.get("poll_seconds", 10))))
            except (AgentApiError, OSError, ValueError) as exc:
                logging.getLogger(__name__).warning("Market bridge cycle failed: %s", exc)
                if args.once:
                    return 1
                time.sleep(10)
    except KeyboardInterrupt:
        return 0
    finally:
        worker.close()

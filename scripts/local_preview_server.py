"""Run a lightweight local Django preview server for development."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from wsgiref.simple_server import make_server

from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.wsgi import get_wsgi_application

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the local preview server."""
    parser = argparse.ArgumentParser(description="Run AgomTradePro local preview server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="Bind port. Default: 8000")
    parser.add_argument(
        "--settings",
        default="core.settings.development",
        help="Django settings module. Default: core.settings.development",
    )
    return parser.parse_args()


def main() -> None:
    """Start the preview server and serve forever."""
    args = parse_args()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", args.settings)

    application = StaticFilesHandler(get_wsgi_application())
    server = make_server(args.host, args.port, application)
    print(f"Serving AgomTradePro preview on http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

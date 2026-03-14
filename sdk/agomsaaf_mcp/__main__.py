"""
AgomSAAF MCP Server - Standard Entry Point

This module provides the standard entry point for running the AgomSAAF MCP server.
It can be invoked via: python -m agomsaaf_mcp

Usage:
    # Run with default settings
    python -m agomsaaf_mcp

    # Or from the sdk directory
    cd sdk && python -m agomsaaf_mcp

Environment Variables:
    AGOMSAAF_BASE_URL / AGOMSAAF_API_BASE_URL: Base URL for AgomSAAF API
        (default: http://127.0.0.1:8000)
    AGOMSAAF_API_TOKEN: API token for authentication
    AGOMSAAF_MCP_ROLE: RBAC role (default: viewer)
    AGOMSAAF_DEFAULT_PORTFOLIO_ID: Default portfolio ID for account resources
    AGOMSAAF_RHIZOME_PATH: Path to rhizome knowledge base (optional)
"""

import sys
import os

# Ensure the parent directory is in the path for imports
# This allows running: python -m agomsaaf_mcp
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)


def main() -> None:
    """Main entry point for the MCP server."""
    from agomsaaf_mcp.server import main as server_main

    # Validate required environment variables
    api_base = os.getenv("AGOMSAAF_BASE_URL") or os.getenv("AGOMSAAF_API_BASE_URL")
    if not api_base:
        print(
            "Warning: AGOMSAAF_BASE_URL not set, using default: http://127.0.0.1:8000",
            file=sys.stderr,
        )

    api_token = os.getenv("AGOMSAAF_API_TOKEN")
    if not api_token:
        print("Warning: AGOMSAAF_API_TOKEN not set. API calls may fail.", file=sys.stderr)

    mcp_role = os.getenv("AGOMSAAF_MCP_ROLE", "viewer")
    print(f"Starting AgomSAAF MCP Server with role: {mcp_role}", file=sys.stderr)

    # Run the server
    server_main()


if __name__ == "__main__":
    main()

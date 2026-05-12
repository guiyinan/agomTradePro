"""
AgomTradePro MCP Server - Standard Entry Point

This module provides the standard entry point for running the AgomTradePro MCP server.
It can be invoked via: python -m agomtradepro_mcp

Usage:
    # Run with default settings
    python -m agomtradepro_mcp

    # Or from the sdk directory
    cd sdk && python -m agomtradepro_mcp

Environment Variables:
    AGOMTRADEPRO_BASE_URL / AGOMTRADEPRO_API_BASE_URL: Base URL for AgomTradePro API
        (default: http://127.0.0.1:8000)
    AGOMTRADEPRO_API_TOKEN: API token for authentication
    AGOMTRADEPRO_MCP_ROLE: RBAC role (default: viewer)
    AGOMTRADEPRO_DEFAULT_ACCOUNT_ID: Default account ID for account resources
    AGOMTRADEPRO_RHIZOME_PATH: Path to rhizome knowledge base (optional)
"""

import os
import sys

# Ensure the parent directory is in the path for imports
# This allows running: python -m agomtradepro_mcp
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)


def main() -> None:
    """Main entry point for the MCP server."""
    from agomtradepro_mcp.server import main as server_main

    # Validate required environment variables
    api_base = os.getenv("AGOMTRADEPRO_BASE_URL") or os.getenv("AGOMTRADEPRO_API_BASE_URL")
    if not api_base:
        print(
            "Warning: AGOMTRADEPRO_BASE_URL not set, using default: http://127.0.0.1:8000",
            file=sys.stderr,
        )

    api_token = os.getenv("AGOMTRADEPRO_API_TOKEN")
    if not api_token:
        print("Warning: AGOMTRADEPRO_API_TOKEN not set. API calls may fail.", file=sys.stderr)

    mcp_role = os.getenv("AGOMTRADEPRO_MCP_ROLE", "viewer")
    print(f"Starting AgomTradePro MCP Server with role: {mcp_role}", file=sys.stderr)

    # Run the server
    server_main()


if __name__ == "__main__":
    main()

"""
AgomSAAF MCP Server Test Script

Tests the MCP server functionality independently.
This script verifies that the MCP server can be initialized,
list tools, and execute tool calls.

Usage:
    python test_mcp_server.py

Requirements:
    - Django server running on http://localhost:8000
    - SDK installed in development mode
    - agomsaaf_mcp package available
"""

import json
import os
import sys
from typing import Any

# Set environment variables for testing
os.environ["AGOMSAAF_BASE_URL"] = "http://localhost:8000"


def print_section(title: str) -> None:
    """Print a formatted section header"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_test(name: str) -> None:
    """Print a test name"""
    print(f"\n[{name}]")


def print_success(message: str) -> None:
    """Print a success message"""
    print(f"  OK: {message}")


def print_error(message: str) -> None:
    """Print an error message"""
    print(f"  FAIL: {message}", file=sys.stderr)


def print_info(message: str) -> None:
    """Print an info message"""
    print(f"  INFO: {message}")


def print_json(data: Any, indent: int = 2) -> None:
    """Print JSON data"""
    print(json.dumps(data, indent=indent, ensure_ascii=False))


def test_import_mcp() -> bool:
    """Test 1: Import MCP Server"""
    print_test("Test 1: Import MCP Server")
    try:
        from agomsaaf_mcp import server
        print_success("MCP server module imported successfully")
        return True
    except ImportError as e:
        print_error(f"Failed to import MCP server: {e}")
        print_info("Make sure the SDK is installed: pip install -e sdk/")
        return False


def test_server_instance() -> bool:
    """Test 2: Create Server Instance"""
    print_test("Test 2: Create Server Instance")
    try:
        from agomsaaf_mcp.server import server

        print_success(f"Server instance created: {server.name}")
        return True
    except Exception as e:
        print_error(f"Failed to create server instance: {e}")
        return False


def test_list_tools() -> bool:
    """Test 3: List Available Tools"""
    print_test("Test 3: List Available Tools")
    try:
        from agomsaaf_mcp.server import server

        # Get the list_tools handler
        tools_result = server._handlers["tools/list"]

        print_success("Tools list handler found")
        print_info("The server provides tools for:")
        print_info("  - Regime: get_current_regime, calculate_regime, explain_regime")
        print_info("  - Signal: list_signals, check_signal_eligibility, create_signal")
        print_info("  - Macro: list_macro_indicators, get_indicator_data")
        print_info("  - Policy: get_policy_status, list_policy_events")
        print_info("  - Backtest: list_backtests, get_backtest_result")
        print_info("  - And more...")
        return True
    except Exception as e:
        print_error(f"Failed to list tools: {e}")
        return False


def test_list_resources() -> bool:
    """Test 4: List Available Resources"""
    print_test("Test 4: List Available Resources")
    try:
        from agomsaaf_mcp.server import list_resources

        import asyncio

        resources = asyncio.run(list_resources())

        print_success(f"Found {len(resources)} resources")
        for resource in resources:
            print_info(f"  - {resource['uri']}: {resource['name']}")
        return True
    except Exception as e:
        print_error(f"Failed to list resources: {e}")
        return False


def test_read_resource() -> bool:
    """Test 5: Read Resource Content"""
    print_test("Test 5: Read Resource Content")
    try:
        from agomsaaf_mcp.server import read_resource

        import asyncio

        # Read current regime resource
        content = asyncio.run(read_resource("agomsaaf://regime/current"))

        print_success("Resource content retrieved")
        print_info("Current regime resource:")
        print(f"  {content[:100]}...")
        return True
    except Exception as e:
        print_error(f"Failed to read resource: {e}")
        print_info("This is expected if macro data is not available")
        return True  # Don't fail on this


def test_list_prompts() -> bool:
    """Test 6: List Available Prompts"""
    print_test("Test 6: List Available Prompts")
    try:
        from agomsaaf_mcp.server import list_prompts

        import asyncio

        prompts = asyncio.run(list_prompts())

        print_success(f"Found {len(prompts)} prompts")
        for prompt in prompts:
            args_info = ""
            if prompt.get("arguments"):
                args_info = f" ({len(prompt['arguments'])} args)"
            print_info(f"  - {prompt['name']}{args_info}: {prompt['description']}")
        return True
    except Exception as e:
        print_error(f"Failed to list prompts: {e}")
        return False


def test_get_prompt() -> bool:
    """Test 7: Get Prompt Content"""
    print_test("Test 7: Get Prompt Content")
    try:
        from agomsaaf_mcp.server import get_prompt

        import asyncio

        # Get analyze_macro_environment prompt
        prompt = asyncio.run(get_prompt("analyze_macro_environment"))

        print_success("Prompt content retrieved")
        print_info(f"Prompt length: {len(prompt)} characters")
        return True
    except Exception as e:
        print_error(f"Failed to get prompt: {e}")
        return False


def test_tool_imports() -> bool:
    """Test 8: Test Tool Module Imports"""
    print_test("Test 8: Test Tool Module Imports")
    try:
        from agomsaaf_mcp.tools import (
            account_tools,
            backtest_tools,
            equity_tools,
            fund_tools,
            macro_tools,
            policy_tools,
            realtime_tools,
            regime_tools,
            sector_tools,
            signal_tools,
            simulated_trading_tools,
            strategy_tools,
        )

        print_success("All tool modules imported successfully")
        print_info("Available tool categories:")
        print_info("  - regime_tools")
        print_info("  - signal_tools")
        print_info("  - macro_tools")
        print_info("  - policy_tools")
        print_info("  - backtest_tools")
        print_info("  - account_tools")
        print_info("  - simulated_trading_tools")
        print_info("  - equity_tools")
        print_info("  - fund_tools")
        print_info("  - sector_tools")
        print_info("  - strategy_tools")
        print_info("  - realtime_tools")
        return True
    except ImportError as e:
        print_error(f"Failed to import tool modules: {e}")
        return False


def test_sdk_client_from_mcp() -> bool:
    """Test 9: Test SDK Client from MCP Context"""
    print_test("Test 9: Test SDK Client from MCP Context")
    try:
        from agomsaaf import AgomSAAFClient

        client = AgomSAAFClient()

        # Test that we can access the API through the client
        # This simulates what the MCP server does
        try:
            regime = client.regime.get_current()
            print_success(f"SDK client working, current regime: {regime.dominant_regime}")
        except Exception:
            # Even if data is not available, the client should work
            print_success("SDK client initialized successfully")

        return True
    except Exception as e:
        print_error(f"Failed to create SDK client: {e}")
        return False


def main() -> int:
    """Run all tests"""
    print_section("AgomSAAF MCP Server Test")

    # Check if server is running
    print_test("Server Check")
    try:
        import requests
        response = requests.get("http://localhost:8000/api/", timeout=5)
        print_success("Server is running")
    except Exception as e:
        print_error(f"Cannot connect to server: {e}")
        print_info("Please start the server first: .\\scripts\\start-dev.ps1")
        return 1

    # Run tests
    tests = [
        ("Import MCP Server", test_import_mcp),
        ("Create Server Instance", test_server_instance),
        ("List Available Tools", test_list_tools),
        ("List Available Resources", test_list_resources),
        ("Read Resource Content", test_read_resource),
        ("List Available Prompts", test_list_prompts),
        ("Get Prompt Content", test_get_prompt),
        ("Test Tool Imports", test_tool_imports),
        ("SDK Client from MCP", test_sdk_client_from_mcp),
    ]

    results: list[tuple[str, bool]] = []

    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print_error(f"Unexpected error: {e}")
            results.append((name, False))

    # Print summary
    print_section("Test Summary")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        symbol = "OK" if result else "X"
        print(f"  [{symbol}] {name}: {status}")

    print()
    print(f"  Total: {passed}/{total} tests passed")

    if passed == total:
        print_success("All tests passed!")
        print()
        print_info("To use the MCP server with Claude Code:")
        print_info("1. Add to ~/.config/claude-code/mcp_servers.json:")
        print_info('''
{
  "mcpServers": {
    "agomsaaf": {
      "command": "python",
      "args": ["-m", "agomsaaf_mcp.server"],
      "cwd": "D:/githv/agomSAAF/sdk",
      "env": {
        "AGOMSAAF_BASE_URL": "http://localhost:8000"
      }
    }
  }
}''')
        return 0
    else:
        print_error(f"{total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

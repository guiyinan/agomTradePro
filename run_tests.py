"""Run SDK/MCP tests with proper path setup."""
import sys

# Add SDK to path
sys.path.insert(0, r"D:\githv\agomTradePro\sdk")

# Now run pytest
import pytest

# Run SDK extended modules tests
print("=" * 60)
print("Running SDK Extended Modules Tests...")
print("=" * 60)
result1 = pytest.main([
    "sdk/tests/test_sdk/test_extended_modules.py",
    "sdk/tests/test_sdk/test_extended_module_endpoints.py",
    "-v",
    "--tb=short",
    "-q"
])

print("\n" + "=" * 60)
print("Running MCP Tool Tests...")
print("=" * 60)
result2 = pytest.main([
    "sdk/tests/test_mcp/test_tool_registration.py",
    "sdk/tests/test_mcp/test_tool_execution.py",
    "sdk/tests/test_mcp/test_rbac.py",
    "-v",
    "--tb=short",
    "-q"
])

print(f"\nSDK Tests result: {result1}")
print(f"MCP Tests result: {result2}")

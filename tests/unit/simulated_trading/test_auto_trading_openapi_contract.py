"""Check generated automatic-run transport contracts without database access."""

import re
from pathlib import Path

import yaml

SCHEMA = Path("docs/testing/api/openapi.yaml")
ENDPOINT = "/api/simulated-trading/auto-trading/run/"


def _operation() -> dict[str, object]:
    """Read the generated operation from the canonical OpenAPI artifact."""
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    return schema["paths"][ENDPOINT]["post"]


def test_auto_run_header_describes_exact_key_constraints() -> None:
    operation = _operation()
    parameter = next(item for item in operation["parameters"] if item["name"] == "Idempotency-Key")
    schema = parameter["schema"]
    assert parameter["required"] is True
    assert schema["type"] == "string"
    assert schema.get("minLength") == 1
    assert schema.get("maxLength") == 128
    pattern = schema["pattern"]
    for key in ("a", "a" * 128, "paper:one-01"):
        assert re.search(pattern, key) is not None
    for key in ("", " ", "a b", "\ta", "a\n", "a\r", "a\u3000b"):
        assert re.search(pattern, key) is None


def test_auto_run_describes_setup_failure_envelope() -> None:
    operation = _operation()
    response = operation["responses"].get("500")
    assert response is not None
    schema = response["content"]["application/json"]["schema"]
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"success", "error", "stable_error_code"}
    assert schema["properties"]["success"] == {"type": "boolean", "enum": [False]}
    assert schema["properties"]["error"]["type"] == "string"
    assert schema["properties"]["stable_error_code"] == {
        "type": "string",
        "enum": ["AUTO_TRADING_SETUP_FAILED"],
    }

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "remote_build_deploy_vps.py"
    spec = importlib.util.spec_from_file_location("remote_build_deploy_vps", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


remote_build_deploy_vps = _load_module()


@pytest.mark.parametrize(
    "value",
    [
        "62.171.144.39",
        "2001:db8::1",
        "https://demo.agomtrade.pro",
        "demo.agomtrade.pro/path",
        "demo.agomtrade.pro:443",
    ],
)
def test_normalize_domain_rejects_values_that_caddy_cannot_certify_safely(value: str):
    with pytest.raises(ValueError):
        remote_build_deploy_vps._normalize_domain(value)


def test_normalize_domain_accepts_and_canonicalizes_dns_hostname():
    assert (
        remote_build_deploy_vps._normalize_domain(" Demo.AgomTrade.Pro. ")
        == "demo.agomtrade.pro"
    )


def test_normalize_domain_keeps_blank_http_only_mode():
    assert remote_build_deploy_vps._normalize_domain("  ") == ""

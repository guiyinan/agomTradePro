# Nightly Test Stability Notes (2026-04-28)

## Root Cause

`tests/integration/test_alpha_stress.py` still allowed some Alpha fallback paths to reach the ETF remote holdings adapter. In GitHub Actions, that occasionally triggered a real `akshare` network request and stalled in SSL handshake, causing the nightly integration stage to fail.

## Fix

The stress test module now applies an autouse patch for ETF constituents so every test in the file stays offline by default, even when execution falls through to the ETF fallback provider.

## Validation

- `pytest tests/integration/test_alpha_stress.py -q`
- `pytest tests/integration/ -q --maxfail=1`

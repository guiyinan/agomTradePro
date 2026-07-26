import logging

from core.logging_utils import normalize_log_level


def test_normalize_log_level_trims_and_uppercases_batch_values():
    assert normalize_log_level("INFO ") == "INFO"
    assert normalize_log_level(" debug ") == "DEBUG"


def test_normalize_log_level_falls_back_for_blank_values():
    assert normalize_log_level("   ") == "INFO"
    assert normalize_log_level(None, default="WARNING") == "WARNING"


def test_normalize_log_level_returns_logging_compatible_level_name():
    level_name = normalize_log_level(" warning ")

    assert logging.getLevelName(level_name) == logging.WARNING


def test_normalize_log_level_rejects_unknown_environment_value():
    assert normalize_log_level("verbose") == "INFO"
    assert normalize_log_level("verbose", default=" warning ") == "WARNING"


def test_normalize_log_level_falls_back_when_default_is_invalid():
    assert normalize_log_level(None, default="verbose") == "INFO"

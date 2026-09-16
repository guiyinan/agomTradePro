"""Production target-image diagnostic must stay isolated and fail closed."""

from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "evid09_target_current_db_readonly_runtime.py"
)


def test_target_current_read_requires_readonly_before_public_ports() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert source.index("default_transaction_read_only=on") < source.index("django.setup()")
    assert source.index("SHOW default_transaction_read_only") < source.index(
        "get_current_publication("
    )
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in source
    assert "transaction.set_rollback(True)" in source
    assert "get_published_market_news(limit=50)" in source
    assert '"business_dml_performed": False' in source


def test_target_runtime_binds_new_real_news_and_sanitizes_errors() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "5713bdc5-0810-54ea-a043-119e724d773d" in source
    assert "aed230f1d3c4e6b322e9533f594421badabe1f52fa513580ef217d2089725375" in source
    assert "EXPECTED_MEMBER_COUNT = 12" in source
    assert "sys.excepthook = _safe_excepthook" in source
    assert "print(json.dumps(report" in source
    assert "print(str(exc)" not in source
    for forbidden in (".save(", ".create(", "requests.", "OPENAI_API_KEY"):
        assert forbidden not in source

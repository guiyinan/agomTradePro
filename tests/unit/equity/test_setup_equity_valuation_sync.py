from apps.equity.management.commands.setup_equity_valuation_sync import Command


def test_equity_valuation_sync_defaults_to_late_evening() -> None:
    command = Command()
    parser = command.create_parser("manage.py", "setup_equity_valuation_sync")

    options = vars(parser.parse_args([]))

    assert options["hour"] == 21
    assert options["minute"] == 30

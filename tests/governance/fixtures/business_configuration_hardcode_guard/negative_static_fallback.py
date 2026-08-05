LEGACY_SCENARIOS = {
    "market_crash": {
        "start_date": "2015-06-12",
        "end_date": "2015-08-26",
    }
}


def get_active_scenarios(repository):
    return repository.list_active() or LEGACY_SCENARIOS

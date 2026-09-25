from types import SimpleNamespace

from apps.data_center.infrastructure import published_fact_versions


def test_postgres_latest_rows_reduce_history_before_asset_ranking(monkeypatch):
    """The production query must bound history before ranking one row per asset."""

    captured: dict[str, object] = {}
    result_row = SimpleNamespace(id=11)

    class FakeManager:
        def raw(self, sql: str, parameters: list[object]) -> list[object]:
            captured["sql"] = sql
            captured["parameters"] = parameters
            return [result_row]

    field_names = (
        "id",
        "asset_code",
        "val_date",
        "source",
        "observed_at",
        "available_at",
        "fetched_at",
        "revision_number",
    )

    class FakeModel:
        _meta = SimpleNamespace(
            db_table="data_center_valuation_fact",
            concrete_fields=[SimpleNamespace(name=name) for name in field_names],
        )
        _default_manager = FakeManager()

    monkeypatch.setattr(
        published_fact_versions,
        "connection",
        SimpleNamespace(
            vendor="postgresql",
            ops=SimpleNamespace(quote_name=lambda name: f'"{name}"'),
        ),
    )

    rows = published_fact_versions.latest_versioned_rows_for_assets(
        FakeModel,
        natural_key=("asset_code", "val_date", "source"),
        asset_codes=("600000.sh", "000001.SZ", "600000.SH"),
        observation_field="val_date",
        asset_order=(
            "-val_date",
            "-observed_at",
            "-available_at",
            "-fetched_at",
            "-revision_number",
            "-id",
        ),
    )

    assert rows == [result_row]
    sql = str(captured["sql"])
    assert "latest_observations AS MATERIALIZED" in sql
    assert 'MAX(base."val_date")' in sql
    assert "latest_revisions AS MATERIALIZED" in sql
    assert 'DISTINCT ON (base."asset_code", base."val_date", base."source")' in sql
    assert "ROW_NUMBER() OVER" in sql
    assert captured["parameters"] == [
        ["000001.SZ", "600000.SH"],
        ["000001.SZ", "600000.SH"],
    ]


def test_latest_rows_reject_unknown_fields_before_query(monkeypatch):
    """Repository field names are validated before any SQL is constructed."""

    class FakeModel:
        _meta = SimpleNamespace(
            db_table="facts",
            concrete_fields=[
                SimpleNamespace(name=name)
                for name in ("id", "asset_code", "observed_at", "revision_number")
            ],
        )
        _default_manager = SimpleNamespace()

    monkeypatch.setattr(
        published_fact_versions,
        "connection",
        SimpleNamespace(vendor="postgresql"),
    )

    try:
        published_fact_versions.latest_versioned_rows_for_assets(
            FakeModel,
            natural_key=("asset_code", "missing_source"),
            asset_codes=("000001.SZ",),
            observation_field="observed_at",
            asset_order=("-observed_at", "-id"),
        )
    except ValueError as exc:
        assert "missing_source" in str(exc)
    else:
        raise AssertionError("unknown fact field was accepted")

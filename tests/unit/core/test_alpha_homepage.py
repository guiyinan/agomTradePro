from core.integration.alpha_homepage import load_alpha_homepage_data


class _FakeAlphaHomepageQuery:
    def execute(self, *, user, top_n, portfolio_id, pool_mode):
        return {
            "user": user,
            "top_n": top_n,
            "portfolio_id": portfolio_id,
            "pool_mode": pool_mode,
        }


def test_load_alpha_homepage_data_uses_dashboard_query(monkeypatch):
    monkeypatch.setattr(
        "apps.dashboard.application.alpha_homepage.AlphaHomepageQuery",
        _FakeAlphaHomepageQuery,
    )

    assert load_alpha_homepage_data(
        user="user-1",
        top_n=10,
        portfolio_id=7,
        pool_mode="price_covered",
    ) == {
        "user": "user-1",
        "top_n": 10,
        "portfolio_id": 7,
        "pool_mode": "price_covered",
    }

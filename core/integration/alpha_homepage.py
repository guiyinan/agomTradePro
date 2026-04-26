"""Dashboard alpha homepage bridge."""


def load_alpha_homepage_data(*, user, top_n: int, portfolio_id: int, pool_mode: str):
    """Load dashboard alpha homepage data through the owning dashboard module."""
    from apps.dashboard.application.alpha_homepage import AlphaHomepageQuery

    return AlphaHomepageQuery().execute(
        user=user,
        top_n=top_n,
        portfolio_id=portfolio_id,
        pool_mode=pool_mode,
    )

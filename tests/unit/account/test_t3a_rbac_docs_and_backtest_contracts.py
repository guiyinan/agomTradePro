"""T3A account ownership, RBAC, documentation, and backtest import contracts."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from apps.account.application import documentation_use_cases, rbac
from apps.account.application.documentation_use_cases import (
    DocumentationDTO,
    DocumentationFormData,
    DocumentationService,
    DocumentationStats,
)
from apps.account.application.use_cases import (
    CreatePositionFromBacktestInput,
    CreatePositionFromBacktestUseCase,
)
from apps.account.domain.entities import AssetClassType, Region


@pytest.mark.parametrize(
    ("role", "level", "domain", "allowed"),
    [
        ("admin", "admin", "system", True),
        ("owner", "write", "general", True),
        ("owner", "admin", "system", False),
        ("analyst", "read", "strategy", True),
        ("analyst", "write", "strategy", False),
        ("investment_manager", "read", "system", False),
        ("investment_manager", "write", "strategy", True),
        ("investment_manager", "write", "account", False),
        ("trader", "read", "general", True),
        ("trader", "write", "trading", True),
        ("trader", "write", "risk", False),
        ("risk", "read", "general", True),
        ("risk", "write", "risk", True),
        ("risk", "write", "trading", False),
        ("read_only", "read", "general", True),
        ("read_only", "write", "general", False),
        ("future_role", "read", "general", False),
    ],
)
def test_rbac_matrix_is_fail_closed(
    role: str,
    level: str,
    domain: str,
    allowed: bool,
) -> None:
    assert rbac.role_allows_by_matrix(role, level, domain) is allowed


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        (None, "read_only"),
        ("", "read_only"),
        (" 管理员 ", "admin"),
        ("VIEWER", "read_only"),
        ("custom", "custom"),
    ],
)
def test_role_normalization_handles_aliases_and_unknown_values(
    raw: str | None,
    normalized: str,
) -> None:
    assert rbac.normalize_role(raw) == normalized


def test_user_role_requires_authentication_and_profile() -> None:
    anonymous = SimpleNamespace(is_authenticated=False, is_superuser=False)
    superuser = SimpleNamespace(is_authenticated=True, is_superuser=True)
    owner = SimpleNamespace(
        is_authenticated=True,
        is_superuser=False,
        account_profile=SimpleNamespace(rbac_role="所有者"),
    )
    no_profile = SimpleNamespace(
        is_authenticated=True,
        is_superuser=False,
        account_profile=None,
    )

    assert rbac.get_user_role(anonymous) == "read_only"
    assert rbac.get_user_role(superuser) == "admin"
    assert rbac.get_user_role(owner) == "owner"
    assert rbac.get_user_role(no_profile) == "read_only"
    assert rbac.user_allows(owner, "write", "general") is True
    assert rbac.is_system_admin(superuser) is True
    assert rbac.is_system_admin(owner) is False


def _doc(*, doc_id: int = 1, slug: str = "guide") -> DocumentationDTO:
    now = datetime.now(UTC)
    return DocumentationDTO(
        id=doc_id,
        title="Guide",
        slug=slug,
        category="user_guide",
        category_display="User Guide",
        content="content",
        summary="summary",
        order=1,
        is_published=True,
        created_at=now,
        updated_at=now,
    )


class _DocumentationRepository:
    def __init__(self) -> None:
        self.docs = [_doc()]
        self.upserts: list[DocumentationFormData] = []

    def list_docs(self, **_filters: str) -> list[DocumentationDTO]:
        return self.docs

    def list_all_docs(self) -> list[DocumentationDTO]:
        return self.docs

    def list_published_docs(self) -> list[DocumentationDTO]:
        return self.docs

    def get_doc(self, _doc_id: int) -> DocumentationDTO:
        return self.docs[0]

    def get_published_doc_by_slug(self, _slug: str) -> DocumentationDTO:
        return self.docs[0]

    def save_doc(
        self,
        data: DocumentationFormData,
        doc_id: int | None = None,
    ) -> DocumentationDTO:
        return _doc(doc_id=doc_id or 2, slug=data.slug)

    def delete_doc(self, _doc_id: int) -> str:
        return "Guide"

    def upsert_doc(self, data: DocumentationFormData) -> bool:
        self.upserts.append(data)
        return len(self.upserts) % 2 == 1

    def get_category_choices(self) -> list[tuple[str, str]]:
        return [("user_guide", "User Guide")]

    def get_stats(self) -> DocumentationStats:
        return DocumentationStats(total=1, published=1, draft=0, by_category={"user_guide": 1})


def test_documentation_service_delegates_crud_and_display_contract() -> None:
    repository = _DocumentationRepository()
    service = DocumentationService(repository)
    form = DocumentationFormData(
        title="New",
        slug="new",
        category="api",
        content="body",
        summary="short",
        order=2,
        is_published=False,
    )

    assert service.list_admin_docs(category="api") == repository.docs
    assert service.list_all_docs() == repository.docs
    assert service.list_published_docs() == repository.docs
    assert service.get_doc(1).get_category_display() == "User Guide"
    assert service.get_published_doc_by_slug("guide").slug == "guide"
    assert service.save_doc(form, doc_id=7).id == 7
    assert service.delete_doc(1) == "Guide"
    assert service.get_category_choices() == [("user_guide", "User Guide")]
    assert service.get_stats().published == 1


def test_documentation_json_import_skips_missing_slug_and_counts_upserts() -> None:
    repository = _DocumentationRepository()
    result = DocumentationService(repository).import_json_text("""
        [
          {"title": "skip"},
          {"title": "One", "slug": "one", "order": "2"},
          {"title": "Two", "slug": "two", "is_published": false}
        ]
        """)

    assert result.created == 1
    assert result.updated == 1
    assert repository.upserts[0].order == 2
    assert repository.upserts[1].is_published is False


def test_documentation_csv_import_maps_category_newlines_and_publish_flag() -> None:
    repository = _DocumentationRepository()
    result = DocumentationService(repository).import_csv_text(
        "\n".join(
            [
                "标题,Slug,分类,内容,摘要,排序,是否发布",
                "Skip,,其他,none,,0,True",
                "API,api,API 文档,line1\\nline2,summary,3,True",
                "Custom,custom,自定义,body,,4,False",
            ]
        )
    )

    assert result.created == 1
    assert result.updated == 1
    assert repository.upserts[0].category == "api"
    assert repository.upserts[0].content == "line1\nline2"
    assert repository.upserts[1].category == "自定义"
    assert repository.upserts[1].is_published is False


def test_documentation_repository_configuration_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(documentation_use_cases, "_documentation_repository", None)
    with pytest.raises(RuntimeError, match="not configured"):
        documentation_use_cases.get_documentation_service()

    repository = _DocumentationRepository()
    documentation_use_cases.configure_documentation_repository(repository)

    assert documentation_use_cases.get_documentation_service().repository is repository


class _PositionRepository:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def create_position_legacy(self, **kwargs: Any) -> SimpleNamespace:
        self.created.append(kwargs)
        return SimpleNamespace(market_value=Decimal(str(kwargs["shares"])) * kwargs["price"])


class _AccountRepository:
    def get_or_create_default_portfolio(self, user_id: int) -> int:
        assert user_id == 7
        return 70


class _AssetRepository:
    def __init__(self) -> None:
        self.assets: list[dict[str, Any]] = []

    def get_or_create_asset(self, **kwargs: Any) -> None:
        self.assets.append(kwargs)


class _SettingsRepository:
    def get_runtime_asset_proxy_code(self, asset_class: str, _default: str) -> str:
        return {"china_growth": "510300.SH"}.get(asset_class, "")


class _PriceService:
    def get_price_with_metadata(self, asset_code: str) -> dict[str, Any] | None:
        if asset_code == "510300.SH":
            return {"price": Decimal("12"), "source": "cache"}
        return None


def _backtest(**overrides: Any) -> SimpleNamespace:
    payload = {
        "user_id": 7,
        "status": "completed",
        "name": "allocation backtest",
        "trades": [
            {"asset_class": "china_growth", "action": "buy", "shares": 10, "price": 9},
            {"asset_class": "china_growth", "action": "buy", "shares": 10, "price": 11},
            {"asset_class": "us_bond", "action": "buy", "shares": 5, "price": 100},
            {"asset_class": "us_bond", "action": "sell", "shares": 2, "price": 105},
            {"asset_class": "", "action": "buy", "shares": 99, "price": 1},
        ],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _backtest_use_case(backtest: object | None) -> tuple[
    CreatePositionFromBacktestUseCase,
    _PositionRepository,
    _AssetRepository,
]:
    positions = _PositionRepository()
    assets = _AssetRepository()
    use_case = CreatePositionFromBacktestUseCase(
        position_repo=positions,  # type: ignore[arg-type]
        account_repo=_AccountRepository(),  # type: ignore[arg-type]
        asset_meta_repo=assets,  # type: ignore[arg-type]
        market_price_service=_PriceService(),
        backtest_repo=SimpleNamespace(get_backtest_by_id=lambda _backtest_id: backtest),
        settings_repo=_SettingsRepository(),  # type: ignore[arg-type]
    )
    return use_case, positions, assets


@pytest.mark.parametrize(
    ("backtest", "message"),
    [
        (None, "不存在"),
        (_backtest(user_id=8), "无权限"),
        (_backtest(status="running"), "无法应用"),
        (_backtest(trades=[]), "无持仓数据"),
    ],
)
def test_backtest_import_rejects_missing_cross_user_incomplete_and_empty(
    backtest: object | None,
    message: str,
) -> None:
    use_case, _, _ = _backtest_use_case(backtest)

    with pytest.raises(ValueError, match=message):
        use_case.execute(CreatePositionFromBacktestInput(user_id=7, backtest_id=9))


def test_backtest_import_uses_live_price_then_falls_back_to_trade_price() -> None:
    use_case, positions, assets = _backtest_use_case(_backtest())

    result = use_case.execute(
        CreatePositionFromBacktestInput(user_id=7, backtest_id=9, scale_factor=2.0)
    )

    assert result.total_positions == 2
    assert result.total_value == pytest.approx(480 + 600)
    assert positions.created[0]["asset_code"] == "510300.SH"
    assert positions.created[0]["shares"] == 40
    assert positions.created[0]["price"] == Decimal("12")
    assert positions.created[1]["asset_code"] == "us_bond"
    assert positions.created[1]["shares"] == 6
    assert positions.created[1]["price"] == Decimal("100")
    assert assets.assets[0]["asset_class"] == AssetClassType.EQUITY.value
    assert assets.assets[1]["region"] == Region.US.value


def test_backtest_trade_reduction_resets_non_positive_holdings() -> None:
    use_case, _, _ = _backtest_use_case(_backtest())
    holdings = use_case._extract_final_holdings_from_trades(
        [
            {"asset_class": "gold", "action": "buy", "shares": 3, "price": 100},
            {"asset_class": "gold", "action": "sell", "shares": 4, "price": 110},
            {"asset_class": "cash", "action": "hold", "shares": 2, "price": 1},
        ]
    )

    assert holdings == []


@pytest.mark.parametrize(
    ("name", "asset_type", "region"),
    [
        ("a_share_growth", AssetClassType.EQUITY, Region.CN),
        ("fixed_bond", AssetClassType.FIXED_INCOME, Region.CN),
        ("gold_commodity", AssetClassType.COMMODITY, Region.CN),
        ("cash_money", AssetClassType.CASH, Region.CN),
        ("other", AssetClassType.OTHER, Region.CN),
        ("us_equity", AssetClassType.EQUITY, Region.US),
        ("global_equity", AssetClassType.EQUITY, Region.GLOBAL),
    ],
)
def test_backtest_asset_class_and_region_inference(
    name: str,
    asset_type: AssetClassType,
    region: Region,
) -> None:
    use_case, _, _ = _backtest_use_case(_backtest())

    assert use_case._infer_asset_class_type(name) is asset_type
    assert use_case._infer_region(name) is region

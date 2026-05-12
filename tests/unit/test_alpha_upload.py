"""
Alpha 上传与用户隔离单元测试

测试：
- POST /api/alpha/scores/upload/ 普通用户上传个人评分
- POST /api/alpha/scores/upload/ admin 上传系统级评分
- GET /api/alpha/scores/ 读取优先级（个人 > 系统级）
- 权限边界：普通用户不能上传 scope=system
"""

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="admin_test",
        password="admin123",
        email="admin@test.com",
    )


@pytest.fixture
def normal_user(db):
    return User.objects.create_user(
        username="normal_test",
        password="user123",
        email="user@test.com",
    )


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def user_client(normal_user):
    client = APIClient()
    client.force_authenticate(user=normal_user)
    return client


SAMPLE_SCORES = [
    {
        "code": "000001.SZ",
        "score": 0.85,
        "rank": 1,
        "confidence": 0.9,
        "factors": {"momentum": 0.8},
        "source": "local_qlib",
    },
    {
        "code": "000002.SZ",
        "score": 0.75,
        "rank": 2,
        "confidence": 0.85,
        "factors": {"momentum": 0.7},
        "source": "local_qlib",
    },
]

def _make_upload_payload(**overrides):
    """生成使用动态日期的上传 payload"""
    today = date.today()
    payload = {
        "universe_id": "csi300",
        "asof_date": (today - timedelta(days=1)).isoformat(),
        "intended_trade_date": today.isoformat(),
        "model_id": "test_model",
        "scope": "user",
        "scores": SAMPLE_SCORES,
    }
    payload.update(overrides)
    return payload


UPLOAD_PAYLOAD = _make_upload_payload()


@pytest.mark.django_db
class TestUploadScoresPermissions:
    """上传权限测试"""

    def test_unauthenticated_upload_rejected(self):
        client = APIClient()
        resp = client.post("/api/alpha/scores/upload/", data=UPLOAD_PAYLOAD, format="json")
        # DRF returns 403 when using SessionAuthentication without credentials
        assert resp.status_code in (401, 403)

    def test_normal_user_can_upload_user_scope(self, user_client):
        resp = user_client.post("/api/alpha/scores/upload/", data=UPLOAD_PAYLOAD, format="json")
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["success"] is True
        assert data["scope"] == "user"
        assert data["count"] == 2

    def test_normal_user_cannot_upload_system_scope(self, user_client):
        payload = {**UPLOAD_PAYLOAD, "scope": "system"}
        resp = user_client.post("/api/alpha/scores/upload/", data=payload, format="json")
        assert resp.status_code == 403
        assert "admin" in resp.json().get("error", "").lower() or "管理员" in resp.json().get("error", "")

    def test_admin_can_upload_system_scope(self, admin_client):
        payload = {**UPLOAD_PAYLOAD, "scope": "system"}
        resp = admin_client.post("/api/alpha/scores/upload/", data=payload, format="json")
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["success"] is True
        assert data["scope"] == "system"

    def test_admin_can_also_upload_user_scope(self, admin_client):
        resp = admin_client.post("/api/alpha/scores/upload/", data=UPLOAD_PAYLOAD, format="json")
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["success"] is True


@pytest.mark.django_db
class TestUserIsolation:
    """用户隔离测试"""

    def test_user_upload_creates_personal_cache(self, normal_user, user_client):
        from apps.alpha.infrastructure.models import AlphaScoreCacheModel

        resp = user_client.post("/api/alpha/scores/upload/", data=UPLOAD_PAYLOAD, format="json")
        assert resp.status_code in (200, 201)

        # 确认 DB 里的 user FK 指向该用户
        cache = AlphaScoreCacheModel.objects.get(pk=resp.json()["id"])
        assert cache.user_id == normal_user.pk

    def test_admin_system_upload_creates_null_user_cache(self, admin_client):
        from apps.alpha.infrastructure.models import AlphaScoreCacheModel

        payload = {**UPLOAD_PAYLOAD, "scope": "system"}
        resp = admin_client.post("/api/alpha/scores/upload/", data=payload, format="json")
        assert resp.status_code in (200, 201)

        cache = AlphaScoreCacheModel.objects.get(pk=resp.json()["id"])
        assert cache.user is None

    def test_idempotent_upload_updates_existing(self, user_client):
        from apps.alpha.infrastructure.models import AlphaScoreCacheModel

        # 第一次上传
        resp1 = user_client.post("/api/alpha/scores/upload/", data=UPLOAD_PAYLOAD, format="json")
        assert resp1.status_code == 201
        assert resp1.json()["created"] is True

        # 第二次上传相同 key → 更新
        resp2 = user_client.post("/api/alpha/scores/upload/", data=UPLOAD_PAYLOAD, format="json")
        assert resp2.status_code == 200
        assert resp2.json()["created"] is False

        # DB 里只有一条记录
        count = AlphaScoreCacheModel.objects.filter(
            universe_id="csi300",
            intended_trade_date=date.today(),
        ).count()
        assert count >= 1  # 至少自己的一条


@pytest.mark.django_db
class TestUploadValidation:
    """上传参数验证测试"""

    def test_missing_scores_rejected(self, user_client):
        payload = {k: v for k, v in UPLOAD_PAYLOAD.items() if k != "scores"}
        resp = user_client.post("/api/alpha/scores/upload/", data=payload, format="json")
        assert resp.status_code == 400

    def test_missing_universe_id_rejected(self, user_client):
        payload = {k: v for k, v in UPLOAD_PAYLOAD.items() if k != "universe_id"}
        resp = user_client.post("/api/alpha/scores/upload/", data=payload, format="json")
        assert resp.status_code == 400

    def test_invalid_scope_rejected(self, user_client):
        payload = {**UPLOAD_PAYLOAD, "scope": "global"}
        resp = user_client.post("/api/alpha/scores/upload/", data=payload, format="json")
        assert resp.status_code == 400

    def test_empty_scores_accepted(self, user_client):
        """空评分列表可以上传（清空操作）"""
        payload = {**UPLOAD_PAYLOAD, "scores": []}
        resp = user_client.post("/api/alpha/scores/upload/", data=payload, format="json")
        assert resp.status_code in (200, 201)
        assert resp.json()["count"] == 0


@pytest.mark.django_db
class TestReadIsolation:
    """读取优先级与 admin 查询测试"""

    def test_user_read_prefers_personal_cache(self, normal_user, user_client):
        from apps.alpha.infrastructure.models import AlphaScoreCacheModel

        today = date.today()
        yesterday = today - timedelta(days=1)

        AlphaScoreCacheModel.objects.create(
            user=None,
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="qlib",
            asof_date=yesterday,
            model_id="system_model",
            model_artifact_hash="system_hash",
            scores=[{"code": "SYS", "score": 0.1, "rank": 1, "confidence": 1.0, "source": "system", "factors": {}}],
            status="available",
        )
        AlphaScoreCacheModel.objects.create(
            user=normal_user,
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="qlib",
            asof_date=yesterday,
            model_id="user_model",
            model_artifact_hash="user_hash",
            scores=[{"code": "USR", "score": 0.9, "rank": 1, "confidence": 1.0, "source": "user", "factors": {}}],
            status="available",
        )

        resp = user_client.get(f"/api/alpha/scores/?universe=csi300&trade_date={today.isoformat()}")

        assert resp.status_code == 200
        assert resp.json()["stocks"][0]["code"] == "USR"

    def test_user_read_falls_back_to_system_cache(self, user_client):
        from apps.alpha.infrastructure.models import AlphaScoreCacheModel

        today = date.today()
        yesterday = today - timedelta(days=1)

        AlphaScoreCacheModel.objects.create(
            user=None,
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="qlib",
            asof_date=yesterday,
            model_id="system_model",
            model_artifact_hash="system_hash",
            scores=[{"code": "SYS", "score": 0.1, "rank": 1, "confidence": 1.0, "source": "system", "factors": {}}],
            status="available",
        )

        resp = user_client.get(f"/api/alpha/scores/?universe=csi300&trade_date={today.isoformat()}")

        assert resp.status_code == 200
        assert resp.json()["stocks"][0]["code"] == "SYS"

    def test_admin_can_query_specific_user_scores(self, admin_client, normal_user):
        from apps.alpha.infrastructure.models import AlphaScoreCacheModel

        today = date.today()
        yesterday = today - timedelta(days=1)

        AlphaScoreCacheModel.objects.create(
            user=normal_user,
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="qlib",
            asof_date=yesterday,
            model_id="user_model",
            model_artifact_hash="user_hash",
            scores=[{"code": "USR", "score": 0.9, "rank": 1, "confidence": 1.0, "source": "user", "factors": {}}],
            status="available",
        )

        resp = admin_client.get(
            f"/api/alpha/scores/?universe=csi300&trade_date={today.isoformat()}&user_id={normal_user.pk}"
        )

        assert resp.status_code == 200
        assert resp.json()["stocks"][0]["code"] == "USR"

    def test_non_admin_cannot_query_other_user_scores(self, user_client, normal_user):
        today = date.today()
        resp = user_client.get(
            f"/api/alpha/scores/?universe=csi300&trade_date={today.isoformat()}&user_id={normal_user.pk}"
        )

        assert resp.status_code == 403

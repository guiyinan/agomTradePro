# UAT Route Baseline

**Generated:** 2026-02-21
**System Version:** AgomTradePro V3.4

---

## Summary

本文档基于 `tests/uat/route_baseline.json`（单一事实源）生成，并使用 `scripts/validate_uat_route_baseline.py` 校验可解析性。

### Statistics

| Category | Mounted Prefixes | Root Accessible | Root 404 |
|----------|-----------------|-----------------|----------|
| Page Routes | 20 | 15 | 5 |
| API Routes | 23 | 16 | 7 |

---

## 1. Page Routes (HTML Views)

### 1.1 Routes with Root Access

以下模块的根路径 `/module/` 可直接访问：

| Module | Root Path | Default Redirect/View | Status |
|--------|-----------|----------------------|--------|
| Account | `/account/` | Login page | OK |
| Admin | `/admin/` | Django Admin | OK |
| Audit | `/audit/` | Reports page | OK |
| Backtest | `/backtest/` | List page | OK |
| Dashboard | `/dashboard/` | Index page | OK |
| Factor | `/factor/` | Management page | OK |
| Filter | `/filter/` | Dashboard page | OK |
| Hedge | `/hedge/` | Strategy page | OK |
| Macro | `/macro/` | Data page | OK |
| Policy | `/policy/` | Dashboard page | OK |
| Realtime | `/realtime/` | Prices page | OK |
| Regime | `/regime/` | Dashboard page | OK |
| Rotation | `/rotation/` | Analysis page | OK |
| Sector | `/sector/` | Analysis page | OK |
| Sentiment | `/sentiment/` | Redirect to dashboard | OK (302 -> 200) |
| Signal | `/signal/` | Manage page | OK |
| Strategy | `/strategy/` | List page | OK |

### 1.2 Routes Requiring Sub-path (Root 404)

以下模块的根路径返回 404，需要访问具体子路径：

| Module | Root Status | Working Sub-paths |
|--------|-------------|-------------------|
| Equity | 404 | `/equity/screen/`, `/equity/pool/`, `/equity/detail/<code>/` |
| Fund | 404 | `/fund/dashboard/`, `/fund/screen/`, `/fund/rank/` |
| Asset Analysis | 404 | `/asset-analysis/screen/`, `/asset-analysis/pool-summary/` |
| Simulated Trading | 404 | `/simulated-trading/dashboard/`, `/simulated-trading/my-accounts/` |
| AI Provider | 404 | `/ai/manage/`, `/ai/logs/`, `/ai/detail/` |

### 1.3 Unmounted Modules

以下模块未在 `core/urls.py` 中挂载为独立页面路由：

| Module | API Only | Notes |
|--------|----------|-------|
| Alpha | Yes | 仅 API，挂载在 `/api/alpha/` |
| Prompt | Partial | `/prompt/` 有页面路由 |
| Task Monitor | Yes | 仅 API，挂载在 `/api/system/` |

---

## 2. API Routes

### 2.1 Core System APIs

| Path | View | Status |
|------|------|--------|
| `/api/health/` | health_view | OK |
| `/api/schema/` | SpectacularAPIView | OK |
| `/api/docs/` | Swagger UI | OK |
| `/api/redoc/` | ReDoc | OK |

### 2.2 Module APIs with Root Access

| Module | Root Path | Status |
|--------|-----------|--------|
| Audit | `/api/audit/` | OK |
| Backtest | `/api/backtest/` | OK |
| Factor | `/api/factor/` | OK |
| Hedge | `/api/hedge/` | OK |
| Macro | `/api/macro/` | OK |
| Policy | `/api/policy/` | OK |
| Realtime | `/api/realtime/` | OK |
| Regime | `/api/regime/` | OK |
| Rotation | `/api/rotation/` | OK |
| Sector | `/api/sector/` | OK |
| Sentiment | `/api/sentiment/` | OK (Fixed) |
| Signal | `/api/signal/` | OK |
| Strategy | `/api/strategy/` | OK |

### 2.3 Module APIs Requiring Sub-path (Root 404)

以下 API 模块根路径返回 404，需使用具体端点：

| Module | Root Status | Working Endpoints |
|--------|-------------|-------------------|
| Account | 404 | `/api/account/api/`, `/api/account/login/`, `/api/account/profile/` |
| Alpha | 404 | `/api/alpha/scores/`, `/api/alpha/health/`, `/api/alpha/providers/status/` |
| Equity | 404 | `/api/equity/api/` (ViewSet) |
| Fund | 404 | `/api/fund/api/multidim-screen/` |
| Asset Analysis | 404 | `/api/asset-analysis/multidim-screen/`, `/api/asset-analysis/pool-summary/` |
| Simulated Trading | 404 | `/api/simulated-trading/api/accounts/`, `/api/simulated-trading/api/fee-configs/` |
| System (Task Monitor) | 404 | `/api/system/status/<id>/`, `/api/system/list/`, `/api/system/celery/health/` |

---

## 3. UAT Test Configuration Updates Required

### 3.1 Remove/Update Outdated Paths

原测试配置中的以下路径需要更新：

| Old Path | Issue | Correct Path |
|----------|-------|--------------|
| `/macro/indicator/` | 404 | `/macro/data/` |
| `/regime/state/` | 404 | `/regime/dashboard/` |
| `/signal/list/` | 404 | `/signal/manage/` |
| `/policy/manage/` | 404 | `/policy/events/` or `/policy/dashboard/` |
| `/backtest/history/` | 404 | `/backtest/` or `/backtest/list/` |
| `/simulated-trading/positions/` | 404 | `/simulated-trading/my-accounts/` |
| `/filter/manage/` | 404 | `/filter/dashboard/` |
| `/sector/analysis/` | 404 | `/sector/` |
| `/strategy/list/` | 404 | `/strategy/` |
| `/realtime/monitor/` | 404 | `/realtime/` or `/realtime/prices/` |
| `/alpha/` | 404 | N/A (API only, use `/api/alpha/scores/`) |
| `/api/account/` | 404 | `/api/account/api/` |
| `/api/equity/` | 404 | `/api/equity/api/` |
| `/api/fund/` | 404 | `/api/fund/api/multidim-screen/` |
| `/api/asset-analysis/` | 404 | `/api/asset-analysis/multidim-screen/` |
| `/api/simulated-trading/` | 404 | `/api/simulated-trading/api/accounts/` |
| `/api/alpha/` | 404 | `/api/alpha/scores/` |
| `/api/system/` | 404 | `/api/system/list/` or `/api/system/dashboard/` |

---

## 4. Recommendations

### 4.1 Add Root Path Redirects (P2)

建议为以下模块添加根路径重定向，提升用户体验：

```python
# equity/urls.py
path('', RedirectView.as_view(url='/equity/screen/', permanent=False), name='home'),

# fund/urls.py
path('', RedirectView.as_view(url='/fund/dashboard/', permanent=False), name='home'),

# asset_analysis/urls.py
path('', RedirectView.as_view(url='/asset-analysis/screen/', permanent=False), name='home'),

# simulated_trading/urls.py
path('', RedirectView.as_view(url='/simulated-trading/dashboard/', permanent=False), name='home'),
```

### 4.2 API Root Endpoint Standardization (P3)

考虑为所有 API 模块添加根路径的健康检查或列表端点，保持一致性。

---

## 5. Verification Commands

```bash
# 验证所有页面路由
python -c "
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings.development'
import django
django.setup()
from django.urls import resolve

paths = ['/dashboard/', '/macro/data/', '/regime/dashboard/', ...]
for p in paths:
    try:
        resolve(p)
        print(f'[OK] {p}')
    except:
        print(f'[404] {p}')
"

# 验证所有 API 路由
curl http://127.0.0.1:8000/api/health/
curl http://127.0.0.1:8000/api/schema/
curl http://127.0.0.1:8000/api/regime/

# 自动校验基线（CI 可直接运行）
python scripts/validate_uat_route_baseline.py
```

---

**Document Revision:** 1.0
**Next Review:** After route restructuring

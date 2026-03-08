# AgomSAAF 系统改进方案
## 从"不顺手"到"自动化决策助手"

> **制定时间**：2026-01-21
> **目标**：解决用户痛点，实现"自动给出宏观经济形势指引和资产配置参考"

---

## 一、核心问题诊断

### 用户痛点
1. **Dashboard响应慢** - 每次访问都重算Regime（5-10秒延迟）
2. **无主动通知** - Policy P3变化、Regime变化用户不知道
3. **缺少决策支持** - 只告诉"Regime是什么"，不告诉"应该买什么"
4. **AI助手不稳定** - 强依赖外部配置，可能完全不可用

### 根本原因
- **缓存缺失**：`apps/dashboard/application/use_cases.py:119-133` 每次重算
- **通知缺失**：`notify_regime_change` 仅记录日志，未实际发送
- **决策缺失**：没有从 Regime → 具体配置比例 的映射
- **降级不足**：`_fallback_insights()` 规则过于简单

---

## 二、改进优先级路线图

### 🚀 阶段1（1周）：性能与可用性 - P0痛点

#### 1.1 Redis缓存层（解决5-10秒延迟）
**影响**：Dashboard加载时间从5-10秒降至0.1秒（90%+提速）

**关键文件**：
- `core/settings/base.py:176-191` - 添加CACHES配置
- `apps/regime/application/use_cases.py:237-332` - CalculateRegimeUseCase添加缓存
- `apps/dashboard/application/use_cases.py:119-133` - GetDashboardDataUseCase使用缓存
- 新建 `shared/infrastructure/cache_service.py` - 统一缓存服务

**技术方案**：
```python
# 三层缓存架构
Layer 1: View缓存（30秒）- 整页缓存
Layer 2: Redis缓存（15分钟）- Regime计算、宏观数据
Layer 3: Database（永久）- RegimeLog表

# 缓存键设计
REGIME_CACHE_KEY = "regime:snapshot:{date}:{growth_ind}:{inflation_ind}"
MACRO_CACHE_KEY = "macro:{indicator_code}:{end_date}:{use_pit}"
DASHBOARD_CACHE_KEY = "dashboard:data:user:{user_id}"
```

**验证方法**：
1. 启动Redis（docker或本地）
2. 访问Dashboard两次，第二次应<100ms
3. 检查Redis键：`redis-cli KEYS regime:*`

---

#### 1.2 多渠道消息通知系统（解决"不知道环境变化"）
**影响**：Regime/Policy变化自动推送，用户及时调整策略

**关键文件**：
- 复用 `shared/infrastructure/alert_service.py` - 已完整实现Slack/Email/Console
- `apps/regime/application/tasks.py:112-166` - 修改`notify_regime_change()`实际发送
- 新建 `shared/application/notification_service.py` - 业务逻辑封装
- 新建 `shared/infrastructure/models.py` - NotificationModel（通知历史记录）
- `core/settings/base.py` - 添加SLACK_WEBHOOK_URL/EMAIL_CONFIG

**通知类型**：
- `regime_change` - Regime变化（WARNING级别）
- `policy_p3_alert` - Policy升至P3（CRITICAL级别）
- `daily_summary` - 每日宏观摘要（INFO级别，每天8:00）
- `signal_invalidated` - 信号证伪（WARNING级别）
- `macro_data_stale` - 数据过期（WARNING级别）

**技术方案**：
```python
# 通知架构
触发器 → NotificationService → MultiChannelAlertService → Slack/Email/Console

# 配置示例（settings）
SLACK_WEBHOOK_URL = env('SLACK_WEBHOOK_URL', default=None)
EMAIL_CONFIG = {
    'smtp_host': env('EMAIL_SMTP_HOST', default=''),
    'smtp_port': env('EMAIL_SMTP_PORT', default=587),
    'username': env('EMAIL_USERNAME', default=''),
    'password': env('EMAIL_PASSWORD', default=''),
    'from_email': env('EMAIL_FROM', default=''),
    'to_emails': env('EMAIL_TO', default='').split(','),
}
```

**验证方法**：
1. 配置Slack Webhook URL到.env
2. 手动触发Regime变化（修改PMI数据）
3. 检查Slack/邮箱是否收到通知
4. 检查NotificationModel表是否有记录

---

#### 1.3 AI助手三层降级策略（提升可用性至95%+）
**影响**：AI不可用时仍能提供规则建议，避免空白页面

**关键文件**：
- `apps/dashboard/application/use_cases.py:458-554` - 增强`_fallback_insights()`
- `apps/account/infrastructure/models.py` - InvestmentRuleModel扩展字段
- `apps/account/management/commands/init_rules.py` - 添加更多规则

**三层降级**：
```
Level 1: AI API（OpenAI/DeepSeek）- 优先级最高，缓存1小时
    ↓ 失败
Level 2: 本地规则引擎（增强版）- Regime+Policy组合规则
    ↓ 失败
Level 3: 静态建议库 - 预定义通用建议（100%可用）
```

**增强规则示例**：
```python
# Regime + Policy 组合规则（优先级1）
{
  'rule_type': 'regime_policy_combo',
  'conditions': {'regime': 'Stagflation', 'min_policy_level': 2},
  'advice': '🚨 滞胀期 + Policy P2/P3：强烈建议清空权益仓位'
}

# 匹配度 + 仓位 组合规则（优先级2）
{
  'rule_type': 'match_position_combo',
  'conditions': {'max_match_score': 40, 'min_invested_ratio': 0.7},
  'advice': '🚨 持仓严重不匹配且仓位过重，建议大幅减仓'
}

# 静态Regime建议（优先级3）
{
  'rule_type': 'static_regime',
  'conditions': {'regime': 'Recovery'},
  'advice': '经济复苏期，权益资产表现较好'
}
```

**验证方法**：
1. 关闭AI Provider配置
2. 访问Dashboard
3. 检查AI建议区域是否仍有内容（降级为规则）
4. 开启AI后检查是否切换回AI建议

---

### 🎯 阶段2（2周）：自动化决策引擎 - 核心功能

#### 2.1 资产配置建议引擎（最关键）
**影响**：告诉用户"买什么、卖什么、调多少"，直接可执行

**关键文件**：
- 新建 `apps/strategy/domain/allocation_matrix.py` - 配置矩阵（Regime×风险偏好）
- 新建 `apps/strategy/application/allocation_service.py` - 配置引擎
- `apps/dashboard/application/use_cases.py` - 扩展DashboardData结构
- `core/templates/dashboard/index.html:894+` - 前端展示配置建议

**配置矩阵设计**：
```python
# Regime: Recovery + 风险偏好: Aggressive
{
  "base_allocation": {
    "equity": 0.80,
    "fixed_income": 0.10,
    "commodity": 0.05,
    "cash": 0.05
  }
}

# Regime: Stagflation + 风险偏好: Conservative
{
  "base_allocation": {
    "equity": 0.05,      # 几乎清空
    "fixed_income": 0.40, # 短债
    "commodity": 0.10,    # 黄金
    "cash": 0.45
  }
}

# Policy调整系数
POLICY_ADJUSTMENT = {
  'P0': 1.0,   # 无调整
  'P1': 0.9,   # 权益×90%
  'P2': 0.7,   # 权益×70%
  'P3': 0.0,   # 清空权益
}
```

**输出格式**：
```json
{
  "current_allocation": {"equity": 0.65, "fixed_income": 0.20, "cash": 0.15},
  "target_allocation": {"equity": 0.20, "fixed_income": 0.40, "cash": 0.40},
  "specific_actions": [
    {
      "action": "sell",
      "asset_code": "000001.SH",
      "amount": 50000,
      "reason": "该资产与当前Stagflation环境不匹配（hostile）"
    },
    {
      "action": "buy",
      "asset_class": "fixed_income",
      "amount": 30000,
      "recommended_assets": ["511010.SH", "511030.SH"],
      "reason": "增加fixed_income配置以匹配Stagflation环境"
    }
  ],
  "expected_metrics": {
    "expected_return": 0.03,
    "expected_volatility": 0.12,
    "sharpe_ratio": 0.83
  }
}
```

**验证方法**：
1. 创建测试持仓（如65%权益+20%债券+15%现金）
2. 设置Regime为Stagflation
3. 访问Dashboard查看"资产配置建议"卡片
4. 检查建议是否包含：
   - 当前vs目标配置对比（饼图）
   - 具体调仓动作（表格）
   - 预期收益风险指标

---

#### 2.2 收益趋势图数据生成
**影响**：可视化收益曲线，便于用户跟踪策略表现

**关键文件**：
- 新建 `apps/account/application/performance_service.py` - 性能计算服务
- 新建 `apps/account/infrastructure/models.py` - PortfolioSnapshotModel（快照表）
- `apps/dashboard/application/use_cases.py:638` - 修复`performance_data`字段
- `core/templates/dashboard/index.html` - Chart.js收益趋势图

**技术方案**：
```python
# PortfolioSnapshotModel设计
class PortfolioSnapshotModel(models.Model):
    portfolio_id = models.IntegerField()
    snapshot_date = models.DateField()
    total_value = models.DecimalField()
    total_return = models.DecimalField()
    total_return_pct = models.FloatField()
    # 用于绘图

# 数据生成逻辑
def generate_performance_data(portfolio_id, days=30):
    snapshots = PortfolioSnapshotModel.objects.filter(
        portfolio_id=portfolio_id,
        snapshot_date__gte=date.today() - timedelta(days=days)
    ).order_by('snapshot_date')

    return {
        "dates": [s.snapshot_date.isoformat() for s in snapshots],
        "values": [float(s.total_value) for s in snapshots],
        "returns": [s.total_return_pct for s in snapshots],
    }
```

**验证方法**：
1. 运行Celery任务生成历史快照（模拟30天数据）
2. 访问Dashboard
3. 检查收益趋势图是否显示曲线
4. 测试不同时间范围（7天/30天/90天）

---

#### 2.3 每日宏观摘要推送
**影响**：用户每天8:00自动收到投资建议，无需手动登录

**关键文件**：
- 新建 `apps/dashboard/application/tasks.py` - daily_macro_summary任务
- `core/settings/base.py:193-288` - 添加CELERY_BEAT_SCHEDULE配置
- 复用 `shared/infrastructure/alert_service.py` - 发送渠道

**摘要内容**：
```
【AgomSAAF 每日投资摘要】- 2026-01-21

宏观环境：
  - Regime: Stagflation（概率45%）
  - 增长动量: -1.2（减速）
  - 通胀动量: +0.8（加速）
  - Policy档位: P1（轻度限制）

持仓分析：
  - 总资产: ¥125,340
  - 持仓匹配度: 35分（低）
  - 敌对资产: 3只（建议关注）

今日建议：
  1. 当前Stagflation环境不利成长股，建议减仓
  2. 考虑增加防御性资产配置（债券、黄金）
  3. 持仓中000001.SH与当前环境不匹配

查看详情: https://agomsaaf.com/dashboard/
```

**Celery配置**：
```python
CELERY_BEAT_SCHEDULE = {
    'daily-macro-summary': {
        'task': 'apps.dashboard.application.tasks.send_daily_summary',
        'schedule': crontab(hour=8, minute=0),  # 每天8:00
    }
}
```

**验证方法**：
1. 手动触发任务：`celery -A core call apps.dashboard.application.tasks.send_daily_summary`
2. 检查Slack/邮箱是否收到摘要
3. 配置CELERY_BEAT，等待次日8:00验证

---

### 🎨 阶段3（1个月）：用户体验完善

#### 3.1 可视化证伪规则编辑器
**关键文件**：
- 新建 `core/templates/signal/rule_editor.html` - 可视化编辑器
- `apps/signal/interface/views.py` - 规则编辑API

**当前问题**：需填写JSON，如：
```json
{
  "logic": "AND",
  "conditions": [
    {"indicator": "PMI", "condition": "lt", "threshold": 50, "duration": 2}
  ]
}
```

**改进后**：可视化表单
```
[条件1] PMI [小于] [50] 连续 [2] 期
[逻辑] AND
[条件2] CPI [大于] [3.0] 连续 [1] 期
```

---

#### 3.2 Regime历史对比页面
**关键文件**：
- 新建 `core/templates/regime/history.html` - 历史对比页面
- 新建 `apps/regime/interface/views.py` - regime_history_view

**功能**：
- 时间轴展示Regime变化
- 对比当前vs 1个月前/3个月前/1年前
- 叠加政策事件时间点

---

#### 3.3 Celery Worker自启动配置
**关键文件**：
- 新建 `scripts/start_celery.ps1` - PowerShell启动脚本
- 新建 `docs/celery_autostart.md` - 自启动文档

**Windows自启动方案**：
```powershell
# start_celery.ps1
cd .
.\agomsaaf\Scripts\activate
celery -A core worker -l info --pool=solo
```

配置为Windows计划任务，登录时自动运行。

---

### 🏗️ 阶段4（3个月）：生产就绪

#### 4.1 PostgreSQL迁移
- 性能提升：SQLite不支持并发写入
- 数据安全：WAL模式→事务级ACID

#### 4.2 用户权限管理
- 角色：管理员/分析师/普通用户
- 权限：信号批准、配置修改、数据同步

#### 4.3 审计日志完善
- 完善 `apps/audit/` 模块
- 记录所有操作（登录、创建信号、调仓）

#### 4.4 监控告警系统
- Prometheus + Grafana
- 监控指标：Celery任务延迟、API响应时间、数据新鲜度

---

## 三、预期效果

### 性能提升
- Dashboard加载时间：**5-10秒 → 0.1秒（90%+提速）**
- 缓存命中率：**0% → 90%+**
- AI API调用成本：**减少70%+**（缓存+降级）

### 用户体验提升
- 决策支持：**被动查看 → 主动推送**（每日摘要）
- 配置建议：**无 → 具体到"买什么、卖多少"**
- 操作门槛：**需懂JSON → 可视化配置**
- 通知覆盖：**0% → 100%**（Slack/邮件/系统内）

### 系统可靠性提升
- AI可用性：**60% → 95%+**（三层降级）
- 数据新鲜度：**无监控 → 自动告警**
- Regime计算：**无缓存 → 15分钟缓存**

---

## 四、潜在风险与缓解

### 技术风险
1. **Redis依赖** - 缓解：主从复制 + 降级到数据库
2. **AI API成本** - 缓解：严格限流（10次/天）+ 缓存
3. **缓存一致性** - 缓解：合理TTL + 主动失效

### 业务风险
4. **配置建议准确性** - 缓解：免责声明 + 回测数据支撑
5. **通知疲劳** - 缓解：可配置偏好 + 智能降频

### 性能风险
6. **缓存雪崩** - 缓解：TTL抖动 + 分布式锁
7. **快照计算量** - 缓解：异步生成 + 增量计算

---

## 五、实施计划

### Week 1-2：阶段1（性能优化）
- [ ] Day 1-2: Redis缓存层实现
- [ ] Day 3-4: 消息通知系统集成
- [ ] Day 5-7: AI助手降级增强
- [ ] 验证：Dashboard<100ms，通知成功率90%+

### Week 3-4：阶段2 Phase 1（核心功能）
- [ ] Day 8-12: 资产配置建议引擎
- [ ] Day 13-14: 收益趋势图数据生成
- [ ] 验证：配置建议准确性，趋势图显示正常

### Week 5-6：阶段2 Phase 2（自动化）
- [ ] Day 15-17: 每日宏观摘要推送
- [ ] Day 18-21: 证伪规则编辑器
- [ ] 验证：每天8:00收到摘要，编辑器可用

### Week 7-8：阶段3（体验优化）
- [ ] Day 22-24: Regime历史对比页面
- [ ] Day 25-28: Celery自启动配置
- [ ] 验证：历史对比功能，Worker开机自启

### Month 3：阶段4（生产就绪）
- [ ] Week 9-10: PostgreSQL迁移
- [ ] Week 11: 用户权限管理
- [ ] Week 12: 审计日志 + 监控告警

---

## 六、关键文件清单

### 立即需要修改（阶段1）
1. `core/settings/base.py` - CACHES配置、SLACK_WEBHOOK、EMAIL_CONFIG
2. `apps/dashboard/application/use_cases.py` - 缓存集成、AI降级增强
3. `apps/regime/application/use_cases.py` - Regime计算缓存
4. `apps/regime/application/tasks.py` - notify_regime_change实际发送
5. `shared/infrastructure/cache_service.py` - 新建，统一缓存服务
6. `shared/application/notification_service.py` - 新建，通知业务逻辑
7. `shared/infrastructure/models.py` - 新建，NotificationModel

### 稍后创建（阶段2）
8. `apps/strategy/domain/allocation_matrix.py` - 配置矩阵
9. `apps/strategy/application/allocation_service.py` - 配置引擎
10. `apps/account/application/performance_service.py` - 性能计算
11. `apps/account/infrastructure/models.py` - PortfolioSnapshotModel
12. `apps/dashboard/application/tasks.py` - daily_summary任务

---

## 七、验证测试计划

### 阶段1验证
```bash
# 1. Redis缓存验证
redis-cli KEYS regime:*
# 期望：看到缓存键

# 2. Dashboard性能测试
time curl http://localhost:8000/dashboard/
# 期望：第二次<100ms

# 3. 通知测试
python manage.py shell
>>> from shared.infrastructure.alert_service import create_default_alert_service
>>> service = create_default_alert_service(slack_webhook='YOUR_WEBHOOK')
>>> service.send_alert('warning', 'Test', 'Regime changed to Stagflation')
# 期望：Slack收到消息
```

### 阶段2验证
```bash
# 4. 配置建议测试
# 访问Dashboard，检查"资产配置建议"卡片
# 期望：显示当前vs目标配置对比 + 具体调仓动作

# 5. 收益趋势图测试
# 访问Dashboard，检查"收益趋势"图表
# 期望：显示30天收益曲线

# 6. 每日摘要测试
celery -A core call apps.dashboard.application.tasks.send_daily_summary
# 期望：8:00收到邮件/Slack摘要
```

---

## 八、回滚方案

### Feature Flag设计
```python
# core/settings/base.py
FEATURE_FLAGS = {
    'USE_REDIS_CACHE': env.bool('USE_REDIS_CACHE', default=True),
    'USE_NOTIFICATION': env.bool('USE_NOTIFICATION', default=True),
    'USE_ALLOCATION_ENGINE': env.bool('USE_ALLOCATION_ENGINE', default=True),
}

# 使用示例
if settings.FEATURE_FLAGS['USE_REDIS_CACHE']:
    # 使用缓存
else:
    # 直接计算
```

### 数据库迁移回滚
```bash
# 回滚到上一个迁移
python manage.py migrate shared 0001

# 查看迁移历史
python manage.py showmigrations
```

---

## 九、附录：系统当前架构诊断

### 已有基础设施（可复用）
1. **alert_service.py** - 完整的Slack/Email/Console多渠道告警，只需封装业务逻辑
2. **Celery配置** - 已配置12个定时任务，可扩展
3. **四层架构** - Domain/Application/Infrastructure/Interface清晰分离
4. **测试覆盖** - 263个测试，100%通过率

### 关键痛点总结
1. **性能瓶颈**：Dashboard每次重算Regime（`use_cases.py:119-133`）
2. **通知缺失**：`notify_regime_change`仅记录日志，未实际发送
3. **决策缺失**：无从Regime→具体配置比例的映射
4. **降级不足**：`_fallback_insights()`规则过于简单

---

**总结**：本改进方案将AgomSAAF从"需手动查看、响应慢、无指引"转变为"自动推送、秒级响应、直接给出配置建议"的自动化决策助手，核心聚焦用户痛点，分阶段实施，风险可控。


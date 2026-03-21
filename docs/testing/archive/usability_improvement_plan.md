# AgomTradePro 易用性改进规划
## 让用户快速上手，真正用起来

> **制定时间**：2026-01-21
> **核心目标**：从"看不懂、不知道该干啥"变成"打开就知道怎么做"

---

## 一、当前易用性问题

### 用户痛点（按严重程度排序）

#### 🔴 P0 - 致命问题（导致用户放弃使用）
1. **看了Regime，不知道该干什么**
   - 显示"当前是Stagflation"，但用户不知道应该买什么、卖什么
   - 缺少"可执行的操作指引"
   - **影响**：用户看完数据后还得自己研究，门槛太高

2. **Dashboard加载太慢（5-10秒）**
   - 每次打开都要等待
   - 用户以为系统卡死了
   - **影响**：用户不愿意频繁使用

3. **AI助手可能完全空白**
   - 强依赖外部配置（OpenAI/DeepSeek API）
   - 配置失败时建议区域空白
   - **影响**：用户觉得系统不完整

#### 🟡 P1 - 严重问题（影响使用效率）
4. **被动查看，缺少主动推送**
   - 用户需要手动登录才能看到宏观环境变化
   - Regime从Recovery变成Stagflation时，用户不知道
   - **影响**：错过调仓时机

5. **需要懂JSON才能设置证伪规则**
   - 创建投资信号时，证伪逻辑要填JSON格式
   - 普通用户不会写
   - **影响**：只有技术用户能用信号管理功能

6. **收益趋势图是空的**
   - Dashboard有"收益趋势"图表框架，但无数据
   - 用户看不到策略表现
   - **影响**：无法跟踪投资效果

---

## 二、易用性改进优先级

### 🥇 第一优先级：资产配置建议引擎（核心功能）

**改进目标**：告诉用户"买什么、卖什么、调多少"

**当前状态**：
- Dashboard显示：Regime: Stagflation，增长↓，通胀↑
- 用户反应：所以呢？我该干什么？

**改进后**：
- Dashboard显示：
  ```
  【资产配置建议】基于当前Stagflation环境

  当前配置 → 目标配置
  权益  65%  →  20%  （⚠️ 需减仓45%）
  债券  20%  →  40%  （✓ 需加仓20%）
  现金  15%  →  40%  （✓ 需加仓25%）

  具体操作（按优先级）：
  1. 卖出 000001.SH  50,000元  （成长股与当前环境不匹配）
  2. 卖出 600519.SH  30,000元  （消费股需求放缓）
  3. 买入 511010.SH  30,000元  （国债ETF，防御性资产）
  4. 买入 518880.SH  20,000元  （黄金ETF，对冲通胀）

  预期效果：
  - 预期年化收益：3-5%（低于牛市，但控制风险）
  - 预期波动率：12%（降低50%）
  - 夏普比率：0.83
  ```

**实施步骤**：
1. 创建 `apps/strategy/domain/allocation_matrix.py` - 定义16种配置矩阵
   - 4种Regime × 4种风险偏好（Aggressive/Moderate/Conservative/Defensive）
   - 每种组合定义权益/债券/商品/现金比例

2. 创建 `apps/strategy/application/allocation_service.py` - 配置计算服务
   - 输入：当前Regime、用户风险偏好、Policy档位
   - 输出：目标配置 + 具体调仓操作 + 推荐资产

3. 扩展 `apps/dashboard/application/use_cases.py` - 集成配置建议
   - 在DashboardData中新增 `allocation_advice` 字段
   - 调用AllocationService生成建议

4. 前端展示 `core/templates/dashboard/index.html`
   - 新增"资产配置建议"卡片
   - 饼图对比（当前 vs 目标）
   - 操作清单表格

**验证标准**：
- [ ] 用户打开Dashboard，5秒内理解"该干什么"
- [ ] 新手用户无需培训，看懂操作建议
- [ ] 点击"一键调仓"，自动执行建议操作（未来扩展）

**开发工作量**：2-3天

---

### 🥈 第二优先级：Redis缓存层（性能优化）

**改进目标**：Dashboard从5-10秒加载变成<0.1秒

**当前状态**：
- 每次访问Dashboard都重新计算Regime
- `apps/dashboard/application/use_cases.py:119-133` 每次调用CalculateRegimeUseCase
- HP滤波 + Kalman滤波计算耗时5-10秒

**改进后**：
- 首次访问：计算并缓存（5-10秒）
- 后续访问：直接读缓存（<0.1秒）
- 缓存15分钟后自动过期，保证数据新鲜度

**技术方案**：
```python
# 三层缓存架构
Layer 1: View缓存（30秒）
  - 缓存整个Dashboard页面HTML
  - 用户刷新页面时秒开

Layer 2: Redis缓存（15分钟）
  - 缓存Regime计算结果
  - 缓存宏观数据序列
  - 缓存AI建议（1小时）

Layer 3: Database（永久）
  - RegimeLog表（历史记录）
  - PortfolioSnapshot表（持仓快照）
```

**实施步骤**：
1. 配置Redis `core/settings/base.py`
   ```python
   CACHES = {
       'default': {
           'BACKEND': 'django.core.cache.backends.redis.RedisCache',
           'LOCATION': env('REDIS_URL', default='redis://127.0.0.1:6379/1'),
           'TIMEOUT': 900,  # 15分钟
       }
   }
   ```

2. 创建缓存服务 `shared/infrastructure/cache_service.py`
   ```python
   class CacheService:
       @staticmethod
       def get_regime(date, growth_ind, inflation_ind):
           key = f"regime:{date}:{growth_ind}:{inflation_ind}"
           return cache.get(key)

       @staticmethod
       def set_regime(date, growth_ind, inflation_ind, data):
           key = f"regime:{date}:{growth_ind}:{inflation_ind}"
           cache.set(key, data, timeout=900)  # 15分钟
   ```

3. 修改 `apps/regime/application/use_cases.py`
   ```python
   def execute(self, request):
       # 先查缓存
       cached = CacheService.get_regime(...)
       if cached:
           return cached

       # 未命中，计算
       result = self._calculate_regime(...)

       # 写入缓存
       CacheService.set_regime(..., result)
       return result
   ```

4. 修改 `apps/dashboard/application/use_cases.py`
   - 使用缓存版本的Regime计算

**验证标准**：
- [ ] 首次访问Dashboard：5-10秒（正常）
- [ ] 第二次访问Dashboard：<0.1秒（缓存命中）
- [ ] Redis中存在缓存键：`redis-cli KEYS regime:*`

**开发工作量**：1-2天

**依赖**：需要安装Redis（docker或本地）

---

### 🥉 第三优先级：AI助手降级增强（可靠性）

**改进目标**：AI助手永不空白，始终有建议

**当前状态**：
- 优先调用AI API（OpenAI/DeepSeek）
- 失败后调用 `_fallback_insights()` - 但规则太简单
- 可能出现空建议

**改进后 - 三层降级**：
```
Level 1: AI API（最智能）
  - 优先使用，缓存1小时
  - 成本高，限流10次/天
  ↓ 失败
Level 2: 增强规则引擎（次优）
  - Regime + Policy 组合规则
  - 匹配度 + 仓位 组合规则
  - 覆盖90%常见场景
  ↓ 失败
Level 3: 静态建议库（保底）
  - 预定义的通用建议
  - 100%可用，永不空白
```

**规则示例**：
```python
# Level 2 增强规则
ENHANCED_RULES = [
    {
        'priority': 1,
        'type': 'regime_policy_combo',
        'conditions': {
            'regime': 'Stagflation',
            'min_policy_level': 2  # P2或P3
        },
        'advice': '🚨 滞胀期 + 政策收紧：强烈建议清空权益仓位，转入现金或短债'
    },
    {
        'priority': 2,
        'type': 'match_position_combo',
        'conditions': {
            'max_match_score': 40,
            'min_invested_ratio': 0.7
        },
        'advice': '⚠️ 持仓严重不匹配（{match_score}分）且仓位过重（{invested_ratio}），建议大幅减仓'
    },
    {
        'priority': 3,
        'type': 'static_regime',
        'conditions': {'regime': 'Recovery'},
        'advice': '📈 经济复苏期，权益资产表现较好，可适度加仓成长股'
    },
    {
        'priority': 3,
        'type': 'static_regime',
        'conditions': {'regime': 'Stagflation'},
        'advice': '🛡️ 滞胀期，建议持有防御性资产（债券、黄金）'
    }
]

# Level 3 静态建议（最后保底）
STATIC_FALLBACK = [
    "当前宏观环境已更新，请关注Regime变化",
    "定期查看持仓与Regime的匹配度",
    "重大政策事件可能影响市场，请保持警惕"
]
```

**实施步骤**：
1. 扩展数据库 `apps/account/infrastructure/models.py`
   - InvestmentRuleModel新增字段：`rule_type`, `priority`, `conditions`

2. 初始化规则 `apps/account/management/commands/init_rules.py`
   - 预置20+条规则覆盖常见场景

3. 增强降级逻辑 `apps/dashboard/application/use_cases.py:458-554`
   ```python
   def _generate_ai_insights(self, ...):
       # Level 1: AI API
       try:
           ai_result = self._call_ai_api(...)
           if ai_result:
               cache.set(f'ai_insights:{hash}', ai_result, 3600)
               return ai_result
       except Exception as e:
           logger.warning(f"AI调用失败: {e}")

       # Level 2: 增强规则引擎
       rule_insights = self._enhanced_fallback_insights(...)
       if rule_insights:
           return rule_insights

       # Level 3: 静态保底
       return STATIC_FALLBACK

   def _enhanced_fallback_insights(self, regime, policy_level, match_score, invested_ratio):
       insights = []
       for rule in ENHANCED_RULES:
           if self._check_rule_conditions(rule, regime, policy_level, match_score, invested_ratio):
               advice = rule['advice'].format(
                   match_score=match_score,
                   invested_ratio=f"{invested_ratio*100:.0f}%"
               )
               insights.append(advice)
       return insights if insights else STATIC_FALLBACK
   ```

**验证标准**：
- [ ] AI配置关闭时，建议区域仍有内容
- [ ] Stagflation + P3 组合时，显示"清空权益"建议
- [ ] 持仓匹配度<40且仓位>70%时，显示"大幅减仓"建议

**开发工作量**：1天

---

### 🏅 第四优先级：每日宏观摘要推送（自动化）

**改进目标**：用户每天8:00自动收到投资建议，无需登录

**当前状态**：
- 用户需要主动登录查看
- 错过Regime变化时机

**改进后**：
- 每天8:00自动发送邮件/Slack消息
- 内容包括：宏观环境、持仓分析、今日建议

**摘要示例**：
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 AgomTradePro 每日投资摘要
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 2026-01-21 星期二

【宏观环境】
🌍 Regime: Stagflation（概率45%）
  - 增长动量: -1.2 ↓（经济减速）
  - 通胀动量: +0.8 ↑（通胀加速）
🏛️ Policy档位: P1（轻度限制）
  - 最新政策：央行上调存款准备金率0.5%

【持仓分析】
💰 总资产: ¥125,340 （昨日-0.8%）
📊 配置: 权益65% | 债券20% | 现金15%
⚠️ 匹配度: 35分（低，不适合当前环境）
❌ 敌对资产: 3只（建议关注）
  - 000001.SZ 平安银行（金融股）
  - 600519.SH 贵州茅台（消费股）
  - 300750.SZ 宁德时代（成长股）

【今日建议】
1. 🚨 当前Stagflation环境不利成长股，建议减仓
2. 🛡️ 考虑增加防御性资产配置（债券、黄金）
3. ⚠️ 持仓中000001.SZ与当前环境严重不匹配

【快捷操作】
👉 查看详细配置建议: https://agomtradepro.com/dashboard/
👉 一键调仓: https://agomtradepro.com/signal/quick-adjust/
👉 查看Regime历史: https://agomtradepro.com/regime/history/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
本邮件由 AgomTradePro 自动生成
取消订阅 | 调整推送时间 | 反馈建议
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**实施步骤**：
1. 创建任务 `apps/dashboard/application/tasks.py`
   ```python
   @shared_task
   def send_daily_summary():
       users = User.objects.filter(is_active=True)
       for user in users:
           # 生成摘要
           summary = generate_summary(user)

           # 发送邮件
           send_mail(
               subject=f'AgomTradePro 每日投资摘要 - {date.today()}',
               message=summary,
               from_email=settings.EMAIL_FROM,
               recipient_list=[user.email]
           )

           # 发送Slack（如果配置）
           if user.profile.slack_webhook:
               send_slack(user.profile.slack_webhook, summary)
   ```

2. 配置定时任务 `core/settings/base.py`
   ```python
   CELERY_BEAT_SCHEDULE = {
       'daily-macro-summary': {
           'task': 'apps.dashboard.application.tasks.send_daily_summary',
           'schedule': crontab(hour=8, minute=0),
       }
   }
   ```

3. 用户配置 `apps/account/infrastructure/models.py`
   ```python
   class AccountProfileModel(models.Model):
       ...
       enable_daily_summary = models.BooleanField(default=True)
       summary_time = models.TimeField(default='08:00')
       summary_channels = models.JSONField(default=list)  # ['email', 'slack']
   ```

**验证标准**：
- [ ] 每天8:00收到邮件
- [ ] 摘要内容完整（宏观+持仓+建议）
- [ ] 链接可点击跳转

**开发工作量**：1天

**依赖**：邮件服务配置（SMTP）

---

### 🎖️ 第五优先级：Regime/Policy变化实时通知

**改进目标**：重大变化（Regime切换、Policy P3）立即通知用户

**通知场景**：
1. **Regime变化**（WARNING级别）
   - Recovery → Stagflation
   - 立即通知，建议调整持仓

2. **Policy升至P3**（CRITICAL级别）
   - 政策极度收紧，风险极高
   - 立即通知，建议清仓

3. **信号证伪**（WARNING级别）
   - 用户的投资信号被证伪
   - 通知检查持仓

4. **数据过期**（INFO级别）
   - 宏观数据超过7天未更新
   - 提醒管理员同步

**通知示例**：
```
【AgomTradePro 风险告警】🚨

Regime重大变化：Recovery → Stagflation

⚠️ 影响：
  - 增长动量转负（-1.2）
  - 通胀动量转正（+0.8）

📊 当前持仓风险：
  - 匹配度从78分降至35分
  - 3只持仓资产变为"敌对"状态

💡 建议操作：
  1. 立即查看资产配置建议
  2. 考虑减仓成长股（000001.SZ等）
  3. 增配防御性资产（债券、黄金）

👉 查看详情: https://agomtradepro.com/dashboard/
```

**实施步骤**：
1. 创建通知服务 `shared/application/notification_service.py`
   ```python
   class NotificationService:
       def __init__(self):
           self.alert_service = create_default_alert_service(
               slack_webhook=settings.SLACK_WEBHOOK_URL,
               email_config=settings.EMAIL_CONFIG
           )

       def notify_regime_change(self, old_regime, new_regime, user):
           title = f"Regime变化: {old_regime} → {new_regime}"
           message = self._format_regime_change_message(...)
           self.alert_service.send_alert('warning', title, message)

       def notify_policy_p3(self, policy_event, user):
           title = "🚨 政策档位升至P3"
           message = self._format_policy_p3_message(...)
           self.alert_service.send_alert('critical', title, message)
   ```

2. 集成到任务 `apps/regime/application/tasks.py`
   ```python
   @shared_task
   def notify_regime_change(regime_log_id):
       regime_log = RegimeLog.objects.get(id=regime_log_id)

       # 获取上一个Regime
       previous = RegimeLog.objects.filter(
           observed_at__lt=regime_log.observed_at
       ).order_by('-observed_at').first()

       # 如果Regime变化
       if previous and previous.dominant_regime != regime_log.dominant_regime:
           notification_service = NotificationService()
           users = User.objects.filter(is_active=True)
           for user in users:
               notification_service.notify_regime_change(
                   previous.dominant_regime,
                   regime_log.dominant_regime,
                   user
               )
   ```

3. 创建通知历史表 `shared/infrastructure/models.py`
   ```python
   class NotificationModel(models.Model):
       user = models.ForeignKey(User, on_delete=models.CASCADE)
       type = models.CharField(max_length=50)  # regime_change, policy_p3
       title = models.CharField(max_length=200)
       message = models.TextField()
       level = models.CharField(max_length=20)  # info, warning, critical
       channels = models.JSONField()  # ['email', 'slack']
       sent_at = models.DateTimeField(auto_now_add=True)
       read = models.BooleanField(default=False)
   ```

**验证标准**：
- [ ] 手动触发Regime变化，收到通知
- [ ] 通知内容完整（变化、影响、建议）
- [ ] NotificationModel表有记录

**开发工作量**：1天

**依赖**：复用现有 `shared/infrastructure/alert_service.py`

---

## 三、实施路线图

### 第1周：核心功能（P0问题）
**目标**：让用户知道"该干什么"

- [ ] **Day 1-3**: 资产配置建议引擎
  - Domain层：AllocationMatrix定义
  - Application层：AllocationService实现
  - Dashboard集成：配置建议卡片
  - 验证：用户能看到可执行的调仓建议

- [ ] **Day 4-5**: Redis缓存层
  - 配置Redis连接
  - 实现CacheService
  - Regime计算集成缓存
  - 验证：Dashboard加载<0.1秒

- [ ] **Day 6-7**: AI助手降级增强
  - 扩展规则数据库
  - 实现增强降级逻辑
  - 验证：AI关闭时仍有建议

**里程碑1**：用户打开Dashboard，秒开 + 看到明确的操作建议

---

### 第2周：自动化推送（P1问题）
**目标**：让用户"不用登录也知道"

- [ ] **Day 8-10**: 每日宏观摘要推送
  - 实现摘要生成逻辑
  - 配置邮件模板
  - 配置Celery定时任务
  - 验证：每天8:00收到邮件

- [ ] **Day 11-12**: Regime/Policy变化通知
  - 实现NotificationService
  - 集成到Regime计算任务
  - 集成到Policy事件
  - 验证：变化时立即收到通知

- [ ] **Day 13-14**: 收益趋势图数据生成
  - 创建PortfolioSnapshotModel
  - 实现快照生成任务
  - 前端图表展示
  - 验证：Dashboard显示30天收益曲线

**里程碑2**：用户每天自动收到摘要，重大变化立即通知

---

### 第3-4周：体验优化（P2问题）
**目标**：降低使用门槛

- [ ] **Week 3**: 可视化证伪规则编辑器
  - 前端表单设计
  - 规则构建器组件
  - 后端规则解析
  - 验证：无需JSON也能创建信号

- [ ] **Week 4**: Regime历史对比页面
  - 历史数据查询接口
  - 时间轴可视化
  - 政策事件标注
  - 验证：可对比不同时期Regime

**里程碑3**：普通用户（非技术）也能轻松使用

---

## 四、成功标准

### 定量指标
- [ ] Dashboard加载时间：**5-10秒 → <0.1秒（提速90%+）**
- [ ] AI建议可用性：**60% → 95%+（三层降级）**
- [ ] 用户日均登录次数：**0.5次 → 3次**（因为快+有价值）
- [ ] 新手上手时间：**30分钟 → 5分钟**

### 定性指标
- [ ] **用户能5秒内理解该干什么**（看配置建议）
- [ ] **用户愿意每天使用**（因为有自动推送+秒开）
- [ ] **非技术用户也能用**（无需懂JSON/代码）
- [ ] **用户感觉"被照顾"**（主动推送，而非被动查看）

---

## 五、关键文件清单

### 第1周需要创建/修改的文件

**新建文件**：
1. `apps/strategy/domain/allocation_matrix.py` - 配置矩阵定义
2. `apps/strategy/application/allocation_service.py` - 配置计算服务
3. `shared/infrastructure/cache_service.py` - 统一缓存服务
4. `apps/account/management/commands/init_enhanced_rules.py` - 增强规则初始化

**修改文件**：
5. `core/settings/base.py` - 添加CACHES配置
6. `apps/dashboard/application/use_cases.py` - 集成配置建议、缓存、增强降级
7. `apps/regime/application/use_cases.py` - Regime计算集成缓存
8. `core/templates/dashboard/index.html` - 新增配置建议卡片

### 第2周需要创建/修改的文件

**新建文件**：
9. `apps/dashboard/application/tasks.py` - 每日摘要任务
10. `shared/application/notification_service.py` - 通知业务逻辑
11. `shared/infrastructure/models.py` - NotificationModel
12. `apps/account/application/performance_service.py` - 性能计算服务
13. `apps/account/infrastructure/models.py` - PortfolioSnapshotModel

**修改文件**：
14. `apps/regime/application/tasks.py` - 集成通知服务
15. `core/settings/base.py` - 添加CELERY_BEAT_SCHEDULE

---

## 六、风险与缓解

### 技术风险
1. **Redis依赖** - 缓解：开发环境可降级为同步模式（CELERY_TASK_ALWAYS_EAGER）
2. **邮件服务** - 缓解：优先Slack，邮件可选
3. **配置建议准确性** - 缓解：添加免责声明，标注"仅供参考"

### 业务风险
4. **通知疲劳** - 缓解：用户可配置推送频率
5. **建议失效** - 缓解：每次基于最新Regime实时计算

---

## 七、快速启动指南（给开发者）

### 环境准备
```bash
# 1. 安装Redis（可选，开发环境可跳过）
docker run -d -p 6379:6379 redis:alpine

# 2. 配置环境变量
# .env文件添加：
REDIS_URL=redis://127.0.0.1:6379/1
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_USERNAME=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
EMAIL_FROM=agomtradepro@example.com
EMAIL_TO=user1@example.com,user2@example.com

# 3. 初始化增强规则
python manage.py init_enhanced_rules

# 4. 启动Celery Worker（用于定时任务）
celery -A core worker -l info --pool=solo

# 5. 启动Celery Beat（用于定时调度）
celery -A core beat -l info
```

### 验证步骤
```bash
# 验证1: Redis缓存
redis-cli KEYS regime:*

# 验证2: Dashboard性能
time curl http://localhost:8000/dashboard/

# 验证3: 手动触发每日摘要
python manage.py shell
>>> from apps.dashboard.application.tasks import send_daily_summary
>>> send_daily_summary.delay()

# 验证4: 查看配置建议
# 访问 http://localhost:8000/dashboard/
# 检查"资产配置建议"卡片是否显示
```

---

## 八、总结

**核心理念**：从"给数据"到"给建议"

**before**：
- 用户打开Dashboard，看到Regime: Stagflation
- 用户自己研究：Stagflation该买什么？
- 用户放弃使用：太麻烦了

**after**：
- 用户打开Dashboard（秒开）
- 立即看到：卖出000001.SH，买入511010.SH
- 用户点击"一键调仓"，完成操作
- 用户每天8:00收到摘要，无需登录
- 用户被系统照顾，而非被系统折磨

**预期效果**：
- 新手也能用（5分钟上手）
- 老手更爱用（效率提升10倍）
- 系统有温度（主动推送，而非冰冷的数据）

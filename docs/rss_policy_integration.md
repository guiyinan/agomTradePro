# RSS政策事件集成功能文档

## 概述

本文档描述了AgomSAAF项目中的RSS抓取功能，该功能从多个RSS源自动抓取政策信息，并通过关键词匹配自动识别政策档位（P0-P3），生成PolicyEvent记录。

## 功能特性

### 核心功能

1. **多RSS源支持**：支持配置多个RSSHub源
2. **代理配置**：每个RSS源可独立配置代理服务器
3. **自动档位识别**：基于关键词规则自动匹配政策档位
4. **去重机制**：通过URL/GUID自动去重
5. **定时抓取**：Celery Beat定时任务调度
6. **内容提取**：可选配置是否提取文章完整内容
7. **管理界面**：Django Admin + REST API
8. **抓取日志**：详细的抓取日志和状态监控

### 政策档位说明

| 档位 | 名称 | 描述 | 市场行动 |
|------|------|------|----------|
| P0 | 常态 | 无重大政策干预 | 正常运行 |
| P1 | 预警 | 政策信号出现，尚未落地 | 提升现金10% |
| P2 | 干预 | 实质性政策出台 | 暂停信号48h，现金20% |
| P3 | 危机 | 极端政策或市场熔断 | 人工接管，全仓现金 |

## 架构设计

### 四层架构

```
apps/policy/
├── domain/              # Domain层：实体和业务规则
│   ├── entities.py     # RSSSourceConfig, RSSItem, ProxyConfig
│   └── rules.py        # PolicyLevelKeywordRule, DEFAULT_KEYWORD_RULES
│
├── infrastructure/      # Infrastructure层：数据访问和适配器
│   ├── models.py       # RSSSourceConfigModel, PolicyLevelKeywordModel, RSSFetchLog
│   ├── repositories.py # RSSRepository
│   └── adapters/       # RSS适配器
│       ├── base.py     # RSSAdapterProtocol
│       └── feedparser_adapter.py
│
├── application/         # Application层：用例编排
│   ├── use_cases.py    # FetchRSSUseCase
│   ├── tasks.py        # Celery任务
│   └── services.py     # PolicyLevelMatcher档位匹配
│
└── interface/          # Interface层：API和管理界面
    ├── admin.py        # Django Admin
    ├── serializers.py  # DRF序列化器
    ├── views.py        # API视图
    └── urls.py         # 路由配置
```

## 数据库Schema

### RSS源配置表 (rss_source_config)

```sql
CREATE TABLE rss_source_config (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    url VARCHAR(500) NOT NULL,
    category VARCHAR(20) NOT NULL,  -- gov_docs, central_bank, mof, csrc, media, other
    is_active BOOLEAN DEFAULT TRUE,
    fetch_interval_hours INTEGER DEFAULT 6,
    extract_content BOOLEAN DEFAULT FALSE,

    -- 代理配置
    proxy_enabled BOOLEAN DEFAULT FALSE,
    proxy_host VARCHAR(200),
    proxy_port INTEGER,
    proxy_username VARCHAR(100),
    proxy_password VARCHAR(200),
    proxy_type VARCHAR(10) DEFAULT 'http',  -- http, https, socks5

    -- 解析器配置
    parser_type VARCHAR(20) DEFAULT 'feedparser',
    timeout_seconds INTEGER DEFAULT 30,
    retry_times INTEGER DEFAULT 3,

    -- 状态监控
    last_fetch_at TIMESTAMP,
    last_fetch_status VARCHAR(20),
    last_error_message TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 政策档位关键词规则表 (policy_level_keywords)

```sql
CREATE TABLE policy_level_keywords (
    id SERIAL PRIMARY KEY,
    level VARCHAR(2) NOT NULL,  -- P0, P1, P2, P3
    keywords JSON NOT NULL,  -- ["降息", "降准", ...]
    weight INTEGER DEFAULT 1,
    category VARCHAR(50),  -- 可选：按RSS源分类应用规则
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### RSS抓取日志表 (rss_fetch_log)

```sql
CREATE TABLE rss_fetch_log (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES rss_source_config(id),
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL,  -- success, error, partial
    items_count INTEGER DEFAULT 0,
    new_items_count INTEGER DEFAULT 0,
    error_message TEXT,
    fetch_duration_seconds FLOAT
);
```

## 使用指南

### 1. 初始化数据

#### 初始化RSS源

```bash
agomsaaf/Scripts/python.exe scripts/init_rss_sources.py
```

默认RSS源：
- 国务院政府文件库
- 央行公告
- 证监会公告
- 财政部文件

#### 初始化关键词规则

```bash
agomsaaf/Scripts/python.exe scripts/init_policy_keywords.py
```

默认关键词：
- P3: 熔断、紧急、救市、危机、恐慌、系统性风险
- P2: 降息、降准、加息、刺激、干预、MLF、逆回购...
- P1: 酝酿、研究、考虑、拟、或将、讨论...

### 2. Django Admin管理

访问 `http://127.0.0.1:8000/admin/` 管理RSS源和关键词规则。

#### RSS源管理

1. 进入 `Policy › RSS 源配置`
2. 点击 `增加 RSS 源配置` 添加新源
3. 配置参数：
   - **基本信息**：名称、URL、分类、是否启用
   - **抓取配置**：间隔、解析器、超时、重试
   - **代理配置**：代理服务器设置（可选）
   - **状态监控**：查看最后抓取时间和状态

#### 批量操作

- **🔄 测试抓取选中源**：手动触发Celery任务测试抓取
- **✅ 批量启用**：批量启用RSS源
- **❌ 批量禁用**：批量禁用RSS源

#### 关键词规则管理

1. 进入 `Policy › 政策档位关键词规则`
2. 添加或编辑关键词规则
3. 配置参数：
   - **档位**：P0/P1/P2/P3
   - **关键词**：JSON数组格式
   - **权重**：匹配权重（数值越大优先级越高）
   - **适用分类**：留空表示适用于所有RSS源

### 3. Celery Beat配置

在Django Admin的 `Periodic tasks` 中配置定时任务：

#### RSS抓取任务

- **任务**: `apps.policy.application.tasks.fetch_rss_sources`
- **调度**: 每6小时执行一次（Interval: 6 hours）
- **参数**: `{"source_id": null}`  # null表示抓取所有启用的源

#### 日志清理任务

- **任务**: `apps.policy.application.tasks.cleanup_old_rss_logs`
- **调度**: 每周日凌晨2点（Crontab: 0 2 * * 0）
- **参数**: `[90]`  # 保留90天日志

### 4. REST API

#### RSS源管理

```
# 获取所有RSS源
GET /api/policy/api/rss/sources/

# 创建RSS源
POST /api/policy/api/rss/sources/
{
    "name": "政府文件库",
    "url": "https://rsshub.app/gov/zhengce/zhengceku/bmwj",
    "category": "gov_docs",
    "is_active": true,
    "fetch_interval_hours": 12
}

# 手动触发抓取
POST /api/policy/api/rss/sources/{id}/trigger_fetch/

# 抓取所有源
POST /api/policy/api/rss/sources/fetch_all/
```

#### 抓取日志

```
# 获取抓取日志
GET /api/policy/api/rss/logs/?source={source_id}
```

#### 关键词规则

```
# 获取所有规则
GET /api/policy/api/rss/keywords/

# 创建规则
POST /api/policy/api/rss/keywords/
{
    "level": "P2",
    "keywords": ["降息", "降准"],
    "weight": 1,
    "category": "central_bank"
}
```

## 档位匹配逻辑

### 匹配流程

1. 从数据库加载启用的关键词规则
2. 按RSS源分类过滤规则（分类+通用规则）
3. 统计RSS条目标题中各档位关键词出现次数
4. 计算各档位得分（关键词出现次数 × 权重）
5. 返回得分最高的档位

### 匹配示例

| 标题 | 匹配关键词 | 档位 | 得分 |
|------|-----------|------|------|
| 央行决定下调存款准备金率 | 降准(×1), 准备金(×2) | P2 | 3 |
| 央行拟适时降息 | 降息(×1), 拟(×1), 适时(×1) | P1 | 3 |
| 市场恐慌加剧央行紧急救市 | 恐慌(×1), 救市(×1), 紧急(×1) | P3 | 3 |

### 无匹配处理

- 如果RSS条目标题中没有任何匹配的关键词，该条目将被跳过
- 只有成功匹配档位的条目才会创建PolicyEvent

## 代理配置

### 代理类型支持

- HTTP代理
- HTTPS代理
- SOCKS5代理

### 配置步骤

1. 在RSS源配置中启用代理：`proxy_enabled = True`
2. 填写代理信息：
   - `proxy_host`: 代理服务器地址
   - `proxy_port`: 代理端口
   - `proxy_username`: 代理用户名（可选）
   - `proxy_password`: 代理密码（可选）
   - `proxy_type`: 代理类型（http/https/socks5）

### 示例配置

```
代理地址: proxy.example.com
代理端口: 8080
用户名: user
密码: pass
类型: http
```

## 监控和告警

### 抓取状态监控

在Django Admin的RSS抓取日志中可以查看：
- 抓取时间
- 抓取状态（成功/失败/部分成功）
- 抓取条目数
- 新增事件数
- 耗时
- 错误信息

### 自动告警

当RSS抓取生成P2/P3档位事件时，系统会自动触发告警（如果配置了Alert Service）。

### 手动测试

通过Django Admin的批量操作功能可以手动触发测试抓取，验证配置是否正确。

## 故障排查

### 常见问题

#### 1. RSS抓取失败

**症状**：`last_fetch_status = error`

**排查步骤**：
1. 检查RSS URL是否可访问
2. 检查网络连接和代理配置
3. 查看错误信息：`last_error_message`
4. 增加超时时间：`timeout_seconds`
5. 检查Celery Worker是否运行

#### 2. 没有生成PolicyEvent

**症状**：抓取成功但 `new_items_count = 0`

**排查步骤**：
1. 检查关键词规则是否配置
2. 检查RSS条目标题是否包含关键词
3. 查看Celery日志，检查档位匹配结果
4. 检查是否已存在相同URL的记录（去重）

#### 3. 关键词匹配不准确

**解决方案**：
1. 调整关键词列表
2. 增加关键词权重
3. 添加特定分类的关键词规则
4. 启用 `extract_content` 从正文中提取信息

#### 4. Celery任务不执行

**排查步骤**：
1. 检查Celery Worker是否运行：`celery -A core worker -l info`
2. 检查Celery Beat是否运行：`celery -A core beat -l info`
3. 检查Periodic Tasks配置：Django Admin › Periodic tasks
4. 查看Celery日志

## 最佳实践

1. **合理设置抓取频率**：避免频繁抓取导致被封IP
2. **使用代理**：对于海外RSS源，建议使用代理
3. **定期更新关键词**：根据政策变化调整关键词规则
4. **监控抓取日志**：定期检查抓取状态和错误信息
5. **测试新源**：添加新RSS源后先手动测试再启用
6. **定期清理日志**：避免日志表过大影响性能

## 开发说明

### 添加新的RSS适配器

1. 在 `apps/policy/infrastructure/adapters/` 创建新适配器文件
2. 继承 `BaseRSSAdapter` 实现 `fetch()` 方法
3. 在 `apps/policy/application/use_cases.py` 的 `FetchRSSUseCase` 中注册适配器

### 扩展关键词匹配逻辑

1. 编辑 `apps/policy/application/services.py`
2. 修改 `PolicyLevelMatcher` 类的匹配逻辑
3. 支持更复杂的匹配规则（如正则表达式、上下文分析等）

## 相关文件

| 文件 | 说明 |
|------|------|
| `apps/policy/domain/entities.py` | RSS相关实体定义 |
| `apps/policy/domain/rules.py` | 默认关键词规则 |
| `apps/policy/infrastructure/models.py` | ORM模型定义 |
| `apps/policy/infrastructure/adapters/rss_adapter.py` | RSS适配器基类 |
| `apps/policy/infrastructure/adapters/feedparser_adapter.py` | feedparser实现 |
| `apps/policy/application/services.py` | 档位匹配服务 |
| `apps/policy/application/use_cases.py` | FetchRSSUseCase |
| `apps/policy/application/tasks.py` | Celery任务 |
| `apps/policy/interface/admin.py` | Django Admin配置 |
| `scripts/init_rss_sources.py` | RSS源初始化脚本 |
| `scripts/init_policy_keywords.py` | 关键词规则初始化脚本 |

## 版本历史

- v1.0.0 (2026-01-01): 初始版本
  - 支持RSSHub源
  - feedparser适配器
  - 关键词档位匹配
  - Django Admin管理
  - REST API
  - Celery定时任务

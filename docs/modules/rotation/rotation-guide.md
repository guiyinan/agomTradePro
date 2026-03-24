# Rotation 模块指南

> **最后更新**: 2026-03-22

## 概述

Rotation 模块实现基于 Regime 的板块轮动策略，提供资产配置建议。

## 架构

```
apps/rotation/
├── domain/          # 轮动实体、策略逻辑
├── application/     # 用例编排、DTO
├── infrastructure/  # 数据存储、服务
└── interface/       # API 端点
```

## API 端点

| 端点 | 说明 |
|------|------|
| `GET /api/rotation/assets/` | 资产类别 |
| `GET /api/rotation/configs/` | 配置 |
| `GET /api/rotation/signals/` | 轮动信号 |
| `GET /api/rotation/account-configs/` | 账户配置列表 |
| `POST /api/rotation/account-configs/` | 创建账户配置 |
| `POST account-config detail action: apply-template` | 对指定账户配置应用预设模板 |
| `POST /api/rotation/` | 执行操作 |

## 管理命令

```bash
# 初始化轮动配置
python manage.py init_rotation
```

## 轮动策略

基于 Regime 四象限（增长/通胀）的板块配置：
- 再膨胀 → 商品、金融
- 滞胀 → 能源、公用事业
- 衰退下行 → 债券、防御
- 复苏上行 → 成长、消费

## 新增功能 (V3.6)

### 账户配置管理
- 支持为每个账户单独配置轮动参数
- 账户级风险容忍度设置
- 预设模板快速应用

### MCP 工具
- `rotation_get_assets` - 获取资产类别
- `rotation_get_configs` - 获取配置
- `rotation_get_account_configs` - 获取账户配置

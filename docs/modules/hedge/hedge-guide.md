# Hedge 模块指南

> **最后更新**: 2026-03-22

## 概述

Hedge 模块提供对冲策略管理，支持期货对冲计算和配对交易。

## 架构

```
apps/hedge/
├── domain/          # 对冲实体、策略逻辑
├── application/     # 用例编排、DTO
├── infrastructure/  # 数据存储、服务
└── interface/       # API 端点
```

## API 端点

| 端点 | 说明 |
|------|------|
| `GET /api/hedge/pairs/` | 对冲配对 |
| `GET /api/hedge/correlations/` | 相关性分析 |
| `GET /api/hedge/snapshots/` | 对冲快照 |
| `GET /api/hedge/alerts/` | 对冲告警 |
| `POST /api/hedge/` | 执行操作 |

## 数据模型

### HedgePortfolioSnapshot
- 对冲组合快照，记录每日对冲状态
- 字段：trade_date, portfolio_value, hedge_ratio, delta, gamma 等

## 管理命令

```bash
# 初始化对冲配置
python manage.py init_hedge
```

## 对冲工具

- 股指期货 (IF/IC/IH)
- 国债期货 (T/TF/TS)
- 商品期货

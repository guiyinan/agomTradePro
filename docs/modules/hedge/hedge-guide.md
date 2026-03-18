# Hedge 模块指南

> **最后更新**: 2026-02-06

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
| `GET /hedge/api/pairs/` | 对冲配对 |
| `GET /hedge/api/correlations/` | 相关性分析 |
| `GET /hedge/api/snapshots/` | 对冲快照 |
| `GET /hedge/api/alerts/` | 对冲告警 |
| `POST /hedge/api/` | 执行操作 |

## 管理命令

```bash
# 初始化对冲配置
python manage.py init_hedge
```

## 对冲工具

- 股指期货 (IF/IC/IH)
- 国债期货 (T/TF/TS)
- 商品期货

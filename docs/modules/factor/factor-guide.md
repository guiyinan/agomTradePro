# Factor 模块指南

> **最后更新**: 2026-02-06

## 概述

Factor 模块提供因子管理功能，支持因子计算、分析、IC/ICIR 评估。

## 架构

```
apps/factor/
├── domain/          # 因子实体、计算逻辑
├── application/     # 用例编排、DTO
├── infrastructure/  # 数据存储、服务
└── interface/       # API 端点
```

## API 端点

| 端点 | 说明 |
|------|------|
| `GET /api/factor/definitions/` | 因子定义 |
| `GET /api/factor/configs/` | 配置 |
| `POST /api/factor/` | 执行操作 |

## 管理命令

```bash
# 初始化因子
python manage.py init_factors
```

## 因子类型

- 价值因子
- 成长因子
- 质量因子
- 动量因子
- 情绪因子

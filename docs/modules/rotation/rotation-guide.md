# Rotation 模块指南

> **最后更新**: 2026-02-06

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
| `GET /rotation/api/assets/` | 资产类别 |
| `GET /rotation/api/configs/` | 配置 |
| `GET /rotation/api/signals/` | 轮动信号 |
| `POST /rotation/api/` | 执行操作 |

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

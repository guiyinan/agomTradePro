"""
Share Application - 账户公开分享模块

四层架构：
- Domain: 分享实体、披露级别枚举、短码生成服务
- Application: 用例编排、DTOs
- Infrastructure: ORM 模型、数据仓储
- Interface: API 视图、序列化器、URL 路由
"""
default_app_config = 'apps.share.apps.ShareConfig'

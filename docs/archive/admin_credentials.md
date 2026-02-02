# AgomSAAF 管理员账户凭证

> **警告**: 此文件包含敏感信息，请勿提交到公开仓库！

## 初始管理员账户

| 项目 | 值 |
|------|-----|
| 用户名 | `admin` |
| 密码 | `Aa123456` |
| 邮箱 | `admin@agomsaaf.local` |

## 访问地址

- **Admin 后台**: http://127.0.0.1:8000/admin/

## 安全建议

1. **首次登录后请立即修改密码**
2. 生产环境请使用强密码
3. 建议启用双因素认证
4. 定期更换密码

## 重置密码

如果忘记密码，可以通过以下命令重置：

```bash
agomsaaf/Scripts/python manage.py changepassword admin
```

或创建新的超级用户：

```bash
agomsaaf/Scripts/python manage.py createsuperuser
```

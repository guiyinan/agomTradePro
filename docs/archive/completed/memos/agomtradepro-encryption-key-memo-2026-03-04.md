# AGOMTRADEPRO_ENCRYPTION_KEY 配置备忘（2026-03-04）

## 1. 本次已完成

- 已在本机项目根目录 `.env` 中写入 `AGOMTRADEPRO_ENCRYPTION_KEY`。
- 已在模板文件补齐占位变量：
  - `.env.example`
  - `deploy/.env.vps.example`

## 2. 变量用途

`AGOMTRADEPRO_ENCRYPTION_KEY` 用于 AI Provider API Key 的静态加密存储。  
未配置时，系统会拒绝新的 API Key 写入（避免明文落库）。

## 3. 本地开发配置

1. 确保 `.env` 存在（项目根目录）。
2. 配置：

```env
AGOMTRADEPRO_ENCRYPTION_KEY=你的44位Fernet密钥
```

3. 生成新密钥（如需轮换）：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 4. VPS/生产配置

VPS Docker Compose 使用 `deploy/.env`，请在该文件中配置同名变量：

```env
AGOMTRADEPRO_ENCRYPTION_KEY=你的44位Fernet密钥
```

修改后重启 `web` 服务使其生效。

## 5. 验证方法

1. Django shell 检查变量是否加载：

```bash
python manage.py shell -c "from django.conf import settings; print(bool(settings.AGOMTRADEPRO_ENCRYPTION_KEY))"
```

2. 执行关键回归（建议）：

```bash
pytest -q tests/unit/test_ai_provider_encryption_guardrails.py
```

## 6. 轮换建议

1. 先生成新 key 并更新运行环境。
2. 使用管理命令重加密存量：

```bash
python manage.py encrypt_api_keys --force
```

3. 验证业务读写与 AI Provider 相关测试通过后，再清理旧密钥留存。

## 7. 安全注意

- 不要把真实 `AGOMTRADEPRO_ENCRYPTION_KEY` 提交到 Git。
- `.env` / `deploy/.env` 必须仅在受控环境保存。

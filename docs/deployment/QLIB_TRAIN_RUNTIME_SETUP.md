# Qlib 训练运行时搭建与接入指南

> 最后更新: 2026-03-13
> 适用目标: 让 AgomSAAF 真正训练出 `model.pkl`，并接入现有 Admin / Celery / Alpha 推理链路

---

## 1. 先说结论

当前项目已经具备这几部分能力：

- Django Admin 可发起训练任务
- Celery 有独立训练队列 `qlib_train`
- 训练成功后会写出 `model.pkl`
- 训练产物可写入 `QlibModelRegistryModel`
- 训练完成后可选自动激活

但是，**训练是否真的能跑通，取决于 Qlib 运行时环境**。

在当前这台机器上，我已经确认两个硬阻塞：

1. 当前 Python 是 `3.13`
2. 当前环境无法安装 `pyqlib`
3. 当前 Qlib 数据目录也不存在

所以结论很明确：

**不要把 Qlib 真训练跑在当前 Windows + Python 3.13 解释器里。**

推荐方案是单独准备一个 **Qlib 训练运行时**，再接入本系统。

---

## 2. 推荐架构

推荐你采用下面这套分层：

### 2.1 Web / Django 主系统

职责：

- 提供 Admin 前端
- 提供训练任务提交入口
- 管理模型注册表
- 管理激活状态
- 提供推理和缓存刷新

### 2.2 Qlib 训练运行时

职责：

- 安装 `pyqlib`
- 持有 Qlib 数据目录
- 消费 `qlib_train` Celery 队列
- 执行真实模型训练
- 写出 `model.pkl`

### 2.3 推荐部署位置

优先级从高到低：

1. Linux Docker 容器
2. WSL2 Ubuntu 环境
3. 独立 Linux 训练机
4. 独立 Conda Python 3.10/3.11 环境

不推荐：

- 直接在当前 Windows Python 3.13 环境里跑

---

## 3. 系统如何接这个训练运行时

当前项目里的关键配置已经有了：

- `QLIB_PROVIDER_URI`
- `QLIB_MODEL_PATH`
- Celery route:
  - `apps.alpha.application.tasks.qlib_train_model -> qlib_train`
  - `apps.alpha.application.tasks.qlib_predict_scores -> qlib_infer`

也就是说，只要训练运行时满足下面 3 件事，就能接进来：

1. 能访问同一个 Django 项目配置和数据库
2. 能访问同一个 Redis / Celery broker
3. 能访问或共享同一个 `QLIB_MODEL_PATH`

---

## 4. 最推荐方案: Docker 单独训练容器

这是最稳的做法。

### 4.1 目标

单独起一个只负责训练的容器，使用：

- Python 3.10 或 3.11
- `pyqlib`
- `lightgbm`
- `torch`（如果你要 LSTM/MLP）
- 同一个 Redis
- 同一个 Django 配置
- 挂载 Qlib 数据目录
- 挂载模型输出目录

### 4.2 最小要求

训练容器必须满足：

- 能执行 `celery -A core worker -Q qlib_train`
- 能导入 `qlib`
- 能访问 `QLIB_PROVIDER_URI`
- 能写入 `QLIB_MODEL_PATH`

### 4.3 现成文件

项目里现在已经补了可直接使用的文件：

- `docker/Dockerfile.qlib-train`
- `docker/docker-compose.qlib-train.yml`
- `deploy/.env.qlib-train.example`
- `scripts/start-qlib-train-runtime.sh`
- `scripts/stop-qlib-train-runtime.sh`
- `scripts/start-qlib-train-runtime.ps1`
- `scripts/stop-qlib-train-runtime.ps1`

### 4.4 推荐目录挂载

建议把下面两个目录持久化：

```text
./runtime/qlib_data      -> 容器内 /root/.qlib/qlib_data
./runtime/qlib_models    -> 容器内 /models/qlib
```

这样：

- Qlib 数据不会丢
- 训练出的 `model.pkl` 会落在宿主机
- Django 主系统和训练容器都能共享模型目录

### 4.5 一键启动

#### Linux / macOS / WSL

```bash
sh scripts/start-qlib-train-runtime.sh
```

#### Windows PowerShell

```powershell
.\scripts\start-qlib-train-runtime.ps1
```

首次运行会自动：

1. 复制 `deploy/.env.qlib-train.example` 到 `deploy/.env.qlib-train`
2. 创建：
   - `runtime/qlib_data`
   - `runtime/qlib_models`
3. 构建并启动 `agomsaaf_qlib_train_worker`

停止命令：

```bash
sh scripts/stop-qlib-train-runtime.sh
```

或：

```powershell
.\scripts\stop-qlib-train-runtime.ps1
```

### 4.6 首次启动前要改的配置

至少检查：

- `deploy/.env.qlib-train` 里的 `SECRET_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `QLIB_PROVIDER_URI`
- `QLIB_MODEL_PATH`

说明：

- 默认 `REDIS_URL=redis://host.docker.internal:6379/0`
- 默认 `DATABASE_URL=sqlite:////app/db.sqlite3`
- 如果你的 Django 用的是 PostgreSQL，本文件里要改成实际连接串

---

## 5. 次优方案: WSL2 单独训练环境

如果你不想马上改 Docker，可以先用 WSL2。

### 5.1 适用场景

- 当前主系统在 Windows
- 希望尽量保留本地开发体验
- 训练运行时单独放到 Ubuntu

### 5.2 推荐版本

- Ubuntu 22.04
- Python 3.10
- Conda 或 venv 都可以

### 5.3 基本步骤

```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv build-essential git

python3.10 -m venv ~/venvs/agomsaaf-qlib
source ~/venvs/agomsaaf-qlib/bin/activate

pip install -U pip setuptools wheel
pip install pyqlib lightgbm pandas numpy scipy
pip install celery redis django
```

然后把项目目录、Redis、数据库和模型目录接起来。

### 5.4 启动训练 worker

```bash
cd /path/to/agomSAAF
export DJANGO_SETTINGS_MODULE=core.settings.production
export QLIB_PROVIDER_URI=$HOME/.qlib/qlib_data/cn_data
export QLIB_MODEL_PATH=/path/to/shared/models/qlib

celery -A core worker -l info -Q qlib_train --concurrency=1 --max-tasks-per-child=1
```

---

## 6. Qlib 数据怎么准备

当前系统训练前还需要 `QLIB_PROVIDER_URI` 指向有效数据目录。

项目里已有相关命令和脚本：

- `python manage.py init_qlib_data --check`
- `python scripts/prepare_qlib_training_data.py --universe csi300 --start-date 2020-01-01`

### 6.1 训练前最低要求

至少要有：

- 股票池数据
- 日线 OHLCV 数据
- Qlib 可读取的二进制格式

### 6.2 推荐准备流程

```bash
python scripts/prepare_qlib_training_data.py --universe csi300 --start-date 2020-01-01
python manage.py init_qlib_data --check
```

如果 `init_qlib_data --check` 过不了，就不要开始训练。

---

## 7. 与当前 Admin 前端如何配合

现在前端已经支持：

### 7.1 发起训练

入口：

```text
/admin/alpha/qlibmodelregistrymodel/
```

右上角按钮：

- `发起训练`
- `导入模型`

### 7.2 前端训练的真实执行路径

点击 `发起训练` 后，系统会：

1. 收集训练参数
2. 投递 Celery 任务到 `qlib_train`
3. 由训练运行时 worker 消费
4. 真实训练并产出 `model.pkl`
5. 写入 `QlibModelRegistryModel`
6. 如勾选则自动激活

也就是说：

**前端只是入口，真正决定“能不能训练出来”的，是后面的训练运行时。**

---

## 8. 训练成功后的产物和路径

成功后，模型会落到：

```text
<QLIB_MODEL_PATH>/<model_name>/<artifact_hash>/model.pkl
```

当前系统还会写：

```text
config.json
metrics.json
feature_schema.json
data_version.txt
```

并注册到：

- `QlibModelRegistryModel`

---

## 9. 验证训练链路是否真的通了

建议按下面的顺序验收。

### 9.1 环境检查

```bash
python -c "import qlib; print(qlib.__version__)"
python manage.py init_qlib_data --check
```

### 9.2 Worker 检查

确认有训练 worker 在跑：

```bash
celery -A core worker -l info -Q qlib_train --concurrency=1 --max-tasks-per-child=1
```

### 9.3 提交训练

两种方式都可以：

#### 方式 A: Admin

在 Admin 页面点击 `发起训练`

#### 方式 B: 命令行

```bash
python manage.py train_qlib_model --name lgb_csi300 --type LGBModel --async
```

### 9.4 验证产物

```bash
python manage.py list_models
```

并检查磁盘上是否已有：

```text
<QLIB_MODEL_PATH>/<model_name>/<artifact_hash>/model.pkl
```

### 9.5 验证推理

训练成功后再做一次：

```bash
python manage.py bootstrap_alpha_cold_start --universes csi300
```

如果这里能跑通，才算这套训练链路真正闭环。

---

## 10. 当前代码层面的注意点

有两个口径需要你知道：

### 10.1 异步训练路径优先

当前真正应该使用的是：

- Admin 发起训练
- 或 `train_qlib_model --async`

因为异步任务里的训练路径接的是真实训练逻辑。

### 10.2 同步命令不要当最终验收依据

当前 `apps/alpha/management/commands/train_qlib_model.py` 的同步路径里还留有 mock 痕迹，不适合当“生产已验证训练链路”的唯一依据。

所以当前正确姿势是：

- 把前端入口接到异步任务
- 用独立 Qlib 训练运行时消费 `qlib_train`

---

## 11. 建议的最终接入方案

如果你要的是“业务上能长期用”的方案，我建议就按下面做：

1. Django 主系统继续跑你现在的 Web / API / Admin
2. 单独加一个 `qlib-train-worker` 运行时
3. Python 固定到 3.10
4. Qlib 数据目录独立挂载
5. 模型目录独立挂载
6. 训练完成后由当前系统负责注册、激活、验证、冷启动

这样可以同时满足：

- 前端好用
- 模型能真训练
- 运行时隔离
- 后续容易运维

---

## 12. 一句话建议

**不要在当前 Windows Python 3.13 里硬跑 Qlib 训练。**

正确做法是给 AgomSAAF 单独配一个 Python 3.10 的 Qlib 训练运行时，再把它接到现有 Admin + Celery + 模型目录上。

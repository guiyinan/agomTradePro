# Qlib 模型导入说明

> 最后更新: 2026-03-13

本文回答 3 个实际问题:

1. `model.pkl` 从哪来
2. Django Admin 导入页到底接受什么
3. 这东西有没有“模板”

---

## 1. `model.pkl` 从哪来

`model.pkl` 不是手写文件，也不是一个可以照着填的文本模板。

它是一个 **Python pickle 二进制模型产物**，本质上是训练后的模型对象序列化文件。当前项目的加载方式就是：

- 推理时直接 `pickle.load(...)`
- 默认文件名就是 `model.pkl`

对应代码：

- `apps/alpha/application/tasks.py`
- `apps/alpha/management/commands/train_qlib_model.py`

### 推荐来源

优先级从高到低：

1. 用本项目训练链路生成
2. 用你外部独立的 Qlib / LightGBM / PyTorch 训练环境导出
3. 其它离线实验环境产出的兼容 pickle 文件

### 项目内生成方式

当前项目内的标准命令：

```bash
python manage.py train_qlib_model --name lgb_csi300 --type LGBModel
```

训练后会在 `QLIB_MODEL_PATH` 下生成 artifact 目录，典型结构如下：

```text
/models/qlib/<model_name>/<artifact_hash>/
  model.pkl
  config.json
  metrics.json
  data_version.txt
```

说明：

- `model.pkl` 是实际模型文件
- `artifact_hash` 是版本标识
- `config.json` / `metrics.json` / `data_version.txt` 是元数据

### 外部环境导出方式

如果你不是在这个 Django 项目里训练，而是在独立 notebook、研究机或量化训练机里训练，只要最终能导出一个 **当前 Python 环境可成功 `pickle.load()` 的模型对象**，也可以导入。

常见来源包括：

- Qlib 训练后的 LightGBM 模型
- Qlib 训练后的 PyTorch/LSTM/MLP 模型对象
- 你自己封装并用 pickle 保存的兼容预测对象

---

## 2. Admin 导入页接受什么

现在后台已经支持从 Admin 导入：

```text
/admin/alpha/qlibmodelregistrymodel/
```

列表页右上角有“导入模型”按钮。

导入页会要求你填写这些字段：

- `model.pkl` 文件
- `model_name`
- `model_type`
- `universe`
- `feature_set_id`
- `label_id`
- `data_version`
- 可选：`IC / ICIR / Rank IC`
- 可选：`train_config JSON`

导入后系统会自动做这些事：

1. 计算上传文件的 SHA256，作为 `artifact_hash`
2. 把文件保存到：

```text
<QLIB_MODEL_PATH>/<model_name>/<artifact_hash>/model.pkl
```

3. 自动生成：

```text
config.json
metrics.json
data_version.txt
```

4. 写入 `QlibModelRegistryModel`
5. 如果勾选“导入后立即激活”，就直接切成当前生产模型

---

## 3. 有没有模板

### 3.1 `model.pkl` 本身没有模板

没有。

原因很简单：它是二进制模型权重/对象，不是 YAML、JSON、CSV 这种“照着填”的配置文件。你不能拿一个空模板改几行字就变成可用模型。

### 3.2 有“目录模板”和“元数据模板”

如果你只是想知道导入包应该长什么样，可以按下面这个最小结构准备：

```text
<any-temp-dir>/
  model.pkl
  config.json          # 可选，admin 会自动补
  metrics.json         # 可选，admin 会自动补
  data_version.txt     # 可选，admin 会自动补
```

其中：

- `model.pkl` 必须由训练环境产出
- 另外 3 个文件就算没有，Admin 导入时也会自动生成

### 3.3 `train_config JSON` 可参考的最小模板

如果你不知道 Admin 里的 `train_config JSON` 怎么填，可以先用这个最小模板：

```json
{
  "source": "admin_import",
  "trainer": "external_qlib",
  "notes": "imported from offline training environment"
}
```

如果你有更完整的训练参数，也可以写进去：

```json
{
  "source": "admin_import",
  "trainer": "external_qlib",
  "train_start": "2020-01-01",
  "train_end": "2025-12-31",
  "learning_rate": 0.01,
  "epochs": 100,
  "features": "Alpha360",
  "label": "return_5d"
}
```

---

## 4. 最小可用导入标准

一个能被当前系统接受的最小导入包，至少满足：

1. 文件名是 `model.pkl`
2. 文件能被当前服务环境 `pickle.load()` 成功加载
3. 训练环境和线上环境的 Python / 依赖版本不要差太大
4. `model_type`、`universe`、`feature_set_id`、`label_id` 这些元数据和你真实训练过程一致

---

## 5. 当前限制

当前系统对导入模型做的是“注册 + 激活”，**不是完整兼容性验收**。

这意味着：

- Admin 能成功导入，不代表一定能成功推理
- 如果外部训练环境和线上运行环境差异很大，`pickle.load()` 可能成功，但预测时仍可能失败
- `pickle` 本身有安全风险，不应导入来源不可信的文件

所以生产使用建议：

1. 先导入
2. 再激活
3. 立即跑一次 Alpha 冷启动或推理验证

推荐验证命令：

```bash
python manage.py list_models --active
python manage.py bootstrap_alpha_cold_start --universes csi300
```

---

## 6. 建议的实际工作流

### 方案 A: 在项目内训练

```bash
python manage.py init_qlib_data --check
python manage.py train_qlib_model --name lgb_csi300 --type LGBModel
python manage.py list_models
python manage.py activate_model <artifact_hash>
python manage.py bootstrap_alpha_cold_start --universes csi300
```

### 方案 B: 外部训练后导入

1. 在外部环境训练并导出 `model.pkl`
2. 进入 `/admin/alpha/qlibmodelregistrymodel/`
3. 点击“导入模型”
4. 上传 `model.pkl` 并填写元数据
5. 选择是否立即激活
6. 导入完成后跑一次 Alpha 冷启动验证

---

## 7. 一句话结论

`model.pkl` 没有“空模板”。

它只能来自真实训练产物或兼容的离线导出模型；当前 Admin 已经支持把这样的文件导入、注册并激活，文本文档里能模板化的只有目录结构和元数据，而不是模型文件本身。

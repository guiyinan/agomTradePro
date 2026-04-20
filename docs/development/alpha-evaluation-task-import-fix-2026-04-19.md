# Alpha Evaluation Task Import Fix

## 背景

执行 `apps.alpha.application.tasks.qlib_evaluate_model` 时，评估任务会在运行期导入 `cache_evaluation` 与模型注册表。

## 修复

- 将 `apps.alpha.application.tasks` 中 `qlib_evaluate_model` 的相对导入从三级 `...` 修正为二级 `..`
- 避免错误跳到 `apps.infrastructure`，导致 `ModuleNotFoundError`

## 验证

- 新增单元测试覆盖 `qlib_evaluate_model.apply(...)`
- 测试确认指标可正常回写 `QlibModelRegistryModel.ic / icir / rank_ic`

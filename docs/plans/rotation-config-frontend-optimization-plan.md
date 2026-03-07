# 资产轮动策略配置前端优化计划

> **创建日期**: 2026-03-07
> **修订日期**: 2026-03-07（全面修订，补充账户级配置架构）
> **状态**: 待实施
> **预计工作量**: 12-16 小时

---

## Context（背景）

用户希望优化前端展示，让**每个账户/模拟账户**能够：
1. **独立配置风险偏好** - 每个账户有自己的 risk_tolerance，不能共用用户级全局设置
2. **可视化配置各象限资产比例** - 将 `regime_allocations` JSON 字段替换为滑块 UI
3. **不能有硬编码** - 资产代码、模板权重、象限名称均从数据库读取
4. **方便用户和 MCP 配置** - 提供清晰的 REST API，MCP 可以直接读写账户级配置

**现有架构问题（修订新增）：**
- `RotationConfigModel` 是全局共享配置，多账户共用，**无法独立配置**
- `risk_tolerance` 在 `AccountProfileModel` 上，是用户级（一人一个），**不是账户/模拟盘级别**
- `SimulatedAccountModel`（真正的账户实体）没有风险偏好字段，也没有 rotation 配置关联
- 预设模板数据如果写在 `views.py` 里属于硬编码，违反项目规则

---

## 架构设计：两层配置模型

```
全局层（模板层）               账户层（实例层）
─────────────────              ────────────────────────────────
RotationConfigModel            PortfolioRotationConfigModel
（共享模板/基线配置）     →    （每账户独立一份，覆盖象限配置）
name, strategy_type            account (FK → SimulatedAccountModel)
regime_allocations             risk_tolerance  ← 账户级独立
asset_universe                 regime_allocations  ← 账户级独立覆盖
...                            base_config (FK → RotationConfigModel, 可选)
```

- **全局层**：`RotationConfigModel`，作为可复用的模板，管理员或高级用户维护
- **账户层**：`PortfolioRotationConfigModel`，每个 `SimulatedAccountModel` 独立一份，保存该账户自己的 regime 配置和风险偏好
- 账户层可引用全局模板（`base_config`）作为初始值，也可完全独立

---

## 目标

1. 新建数据模型支持每账户独立 rotation 配置
2. 将 JSON textarea 转换为可视化象限编辑器（滑块 UI）
3. 支持从数据库预设模板加载（无硬编码）
4. 提供 MCP 可用的完整 REST API
5. 象限名称、资产列表均动态从 API 读取

---

## 实现方案

---

### Phase 0: 数据模型设计（前置，最关键）

#### 0.1 新建 PortfolioRotationConfigModel

**修改文件**: `apps/rotation/infrastructure/models.py`

```python
from django.core.validators import MinValueValidator, MaxValueValidator

class PortfolioRotationConfigModel(models.Model):
    """
    账户级轮动配置表

    每个投资组合账户（SimulatedAccountModel）独立一份。
    保存该账户的风险偏好和各象限资产配置，不与其他账户共享。
    """
    account = models.OneToOneField(
        'simulated_trading.SimulatedAccountModel',
        on_delete=models.CASCADE,
        related_name='rotation_config',
        verbose_name="投资组合账户"
    )
    base_config = models.ForeignKey(
        RotationConfigModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='account_instances',
        verbose_name="基础模板（可选）"
    )

    RISK_TOLERANCE_CHOICES = [
        ('conservative', '保守型'),
        ('moderate', '稳健型'),
        ('aggressive', '激进型'),
    ]
    risk_tolerance = models.CharField(
        max_length=20,
        choices=RISK_TOLERANCE_CHOICES,
        default='moderate',
        verbose_name="风险偏好"
    )

    # 该账户的象限配置，格式：{regime_name: {asset_code: weight}}
    # 权重为小数（0.0-1.0），每个象限权重之和必须为 1.0
    regime_allocations = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="象限资产配置"
    )

    # 是否启用轮动自动调仓
    is_enabled = models.BooleanField(
        default=False,
        verbose_name="启用轮动"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'portfolio_rotation_config'
        verbose_name = '账户轮动配置'
        verbose_name_plural = '账户轮动配置'

    def __str__(self):
        return f"{self.account.account_name} - {self.risk_tolerance}"
```

#### 0.2 预设模板数据写入数据库（不硬编码在 views.py）

**新建模型**: `RotationTemplateModel`（在 `apps/rotation/infrastructure/models.py`）

```python
class RotationTemplateModel(models.Model):
    """
    预设模板表

    保守/稳健/激进三种模板的数据存储在数据库，
    通过 init_rotation.py 管理命令初始化，不硬编码在代码中。
    """
    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="模板名称"
    )
    key = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="模板标识（conservative/moderate/aggressive）"
    )
    description = models.TextField(blank=True, verbose_name="模板描述")

    # 格式：{regime_name: {asset_code: weight}}
    regime_allocations = models.JSONField(
        default=dict,
        verbose_name="象限配置"
    )

    display_order = models.IntegerField(default=0, verbose_name="展示顺序")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rotation_template'
        verbose_name = '轮动预设模板'
        verbose_name_plural = '轮动预设模板'
        ordering = ['display_order']

    def __str__(self):
        return self.name
```

#### 0.3 更新初始化命令

**修改文件**: `apps/rotation/management/commands/init_rotation.py`

在现有初始化逻辑中增加 `RotationTemplateModel` 的预设数据写入：

```python
# 从 AssetClassModel 查询已有资产（不硬编码代码）
# 按 category 筛选后组合权重，存入 RotationTemplateModel
# 三种模板：conservative / moderate / aggressive
# 各象限名称从 regime 模块的 RegimeQuadrant 枚举中读取
```

#### 0.4 创建数据库迁移

**新建文件**: `apps/rotation/migrations/0002_portfolio_rotation_config.py`

---

### Phase 1: 象限可视化编辑器组件

#### 1.1 创建 JavaScript 组件

**新建文件**: `apps/rotation/static/rotation/js/quadrant_editor.js`

核心功能：
- 从 API 动态读取象限名称（`/api/rotation/regimes/`）和资产列表（`/api/rotation/asset-classes/`），**不在 JS 中硬编码**
- 4 个象限 Tab 切换
- 每个象限的资产权重滑块（0-100%）+ 数字输入框双向绑定
- 实时权重总和验证（必须 = 100%）
- 模板加载：从 `/api/rotation/templates/` 获取模板列表，应用到各象限

```javascript
class RotationQuadrantEditor {
    constructor(containerSelector, hiddenInputSelector) {
        this.container = document.querySelector(containerSelector);
        this.hiddenInput = document.querySelector(hiddenInputSelector);
        this.regimes = [];       // 从 API 加载
        this.assets = [];        // 从 API 加载
        this.allocations = {};   // {regime: {asset_code: weight(0-1)}}
        this.currentRegime = null;
    }

    async init() {
        // 并行加载象限列表和资产列表
        const [regimes, assets] = await Promise.all([
            this.fetchRegimes(),
            this.fetchAssets(),
        ]);
        this.regimes = regimes;
        this.assets = assets;
        this.render();
    }

    async fetchRegimes() {
        const res = await fetch('/api/rotation/regimes/');
        return res.json();  // ['Recovery', 'Overheat', 'Stagflation', 'Deflation']
    }

    async fetchAssets() {
        const res = await fetch('/api/rotation/asset-classes/?is_active=true');
        const data = await res.json();
        return data.results || data;
    }

    updateWeightSum(regime) {
        const sum = Object.values(this.allocations[regime] || {})
            .reduce((a, b) => a + b, 0);
        const valid = Math.abs(sum - 1.0) < 0.01;
        // 更新 UI 状态指示器
        return valid;
    }

    syncToHiddenInput() {
        // 将 allocations 同步到隐藏的 JSON input
        this.hiddenInput.value = JSON.stringify(this.allocations);
    }

    loadFromValue(value) {
        // 从已有 JSON 数据初始化编辑器
        if (value) this.allocations = JSON.parse(value);
        this.render();
    }
}
```

#### 1.2 创建 CSS 样式

**新建文件**: `apps/rotation/static/rotation/css/quadrant_editor.css`

```css
/* 象限 Tab 样式 */
/* 资产滑块样式 */
/* 权重总和验证状态样式（valid/invalid） */
/* 模板按钮样式 */
```

---

### Phase 2: 增强 Modal 表单（账户级配置）

#### 2.1 新建账户轮动配置页面 / Modal 入口

**新建文件**: `apps/rotation/templates/rotation/account_config.html`

**或修改文件**: `apps/rotation/templates/rotation/configs.html`

改造要点：

1. 账户选择区：从 `SimulatedAccountModel` 获取当前用户的账户列表（包含 real 和 simulated 类型），每个账户卡片显示当前 rotation 配置状态。

2. 编辑 Modal 扩展为 3 个 Tab：
   - **Tab 1 - 基本信息**: 账户名称（只读展示）、风险偏好（保守/稳健/激进下拉）、是否启用轮动（开关）
   - **Tab 2 - 象限配置**: 引入 `quadrant_editor.html` 组件，支持模板加载和手动调整
   - **Tab 3 - 配置预览**: 只读展示当前配置的 JSON 摘要，方便 debug 和 MCP 查看

3. 模板下拉框数据从 API 读取（不在模板中硬编码）：
   ```html
   <select id="riskTemplate" onchange="loadTemplate(this.value)">
     <option value="">自定义</option>
     <!-- 由 JS 从 /api/rotation/templates/ 动态填充 -->
   </select>
   ```

#### 2.2 模板组件

**新建文件**: `apps/rotation/templates/rotation/components/quadrant_editor.html`

```html
<!-- 可复用的象限编辑器组件 -->
<!-- 包含隐藏的 JSON 输入域，供表单提交 -->
<input type="hidden" id="regimeAllocationsJson" name="regime_allocations">
<div id="quadrantEditorContainer"></div>
<script>
const editor = new RotationQuadrantEditor(
    '#quadrantEditorContainer',
    '#regimeAllocationsJson'
);
editor.init();
</script>
```

---

### Phase 3: 后端 API 增强

#### 3.1 账户级 rotation 配置 CRUD（最核心）

**修改文件**: `apps/rotation/interface/views.py`

新建 `PortfolioRotationConfigViewSet`：

```python
class PortfolioRotationConfigViewSet(viewsets.ModelViewSet):
    """
    账户级轮动配置 API

    每个账户独立一份配置，支持完整 CRUD。
    MCP 可通过此 API 读写任意账户的 rotation 配置。
    """
    serializer_class = PortfolioRotationConfigSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # 只返回当前用户的账户配置
        return PortfolioRotationConfigModel.objects.filter(
            account__user=self.request.user
        )

    def perform_create(self, serializer):
        # 验证账户属于当前用户
        account = serializer.validated_data['account']
        if account.user != self.request.user:
            raise PermissionDenied("无权配置他人账户")
        serializer.save()

    @action(detail=True, methods=['post'], url_path='apply-template')
    def apply_template(self, request, pk=None):
        """
        应用预设模板到此账户配置

        请求体: {"template_key": "conservative"}
        """
        config = self.get_object()
        template_key = request.data.get('template_key')

        try:
            template = RotationTemplateModel.objects.get(key=template_key, is_active=True)
        except RotationTemplateModel.DoesNotExist:
            return Response({'error': '模板不存在'}, status=404)

        config.regime_allocations = template.regime_allocations
        config.risk_tolerance = template_key  # conservative/moderate/aggressive
        config.save()

        return Response(PortfolioRotationConfigSerializer(config).data)

    @action(detail=False, methods=['get'], url_path='by-account/(?P<account_id>[^/.]+)')
    def by_account(self, request, account_id=None):
        """
        按账户 ID 查询配置（MCP 友好接口）

        GET /api/rotation/account-configs/by-account/{account_id}/
        """
        try:
            config = PortfolioRotationConfigModel.objects.get(
                account_id=account_id,
                account__user=request.user
            )
            return Response(PortfolioRotationConfigSerializer(config).data)
        except PortfolioRotationConfigModel.DoesNotExist:
            return Response({'detail': '该账户尚未配置轮动'}, status=404)
```

#### 3.2 预设模板 API

**修改文件**: `apps/rotation/interface/views.py`

新建 `RotationTemplateViewSet`（只读）：

```python
class RotationTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """
    预设模板 API（从数据库读取，不硬编码）

    GET /api/rotation/templates/          - 所有模板列表
    GET /api/rotation/templates/{id}/     - 模板详情
    """
    queryset = RotationTemplateModel.objects.filter(is_active=True)
    serializer_class = RotationTemplateSerializer
    permission_classes = [IsAuthenticated]
```

#### 3.3 象限名称 API

**修改文件**: `apps/rotation/interface/views.py`

新建简单视图（从 regime 模块读取象限定义，不硬编码）：

```python
@api_view(['GET'])
def get_regime_list(request):
    """
    返回系统支持的象限名称列表

    前端编辑器动态加载 Tab 标签，不在 JS 中硬编码。
    从 regime 模块读取 RegimeQuadrant 枚举定义。

    GET /api/rotation/regimes/
    """
    from apps.regime.domain.entities import RegimeQuadrant
    regimes = [q.value for q in RegimeQuadrant]
    return Response(regimes)
```

#### 3.4 增强 rotation_configs_view 上下文

**修改文件**: `apps/rotation/interface/views.py` - `rotation_configs_view`

增加到 context：
```python
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

context = {
    # ... 现有字段 ...
    # 新增：当前用户的所有账户及其 rotation 配置状态
    'user_accounts': SimulatedAccountModel.objects.filter(
        user=request.user, is_active=True
    ).select_related('rotation_config'),
    # 新增：可用资产列表（从数据库读取）
    'assets': AssetClassModel.objects.filter(is_active=True),
}
```

#### 3.5 更新 API URL 注册

**修改文件**: `apps/rotation/interface/api_urls.py`

```python
router.register(r'account-configs', PortfolioRotationConfigViewSet, basename='account-rotation-config')
router.register(r'templates', RotationTemplateViewSet, basename='rotation-template')

urlpatterns = router.urls + [
    path('regimes/', get_regime_list, name='regime-list'),
]
```

---

### Phase 4: 序列化器

**修改文件**: `apps/rotation/interface/serializers.py`

新增：

```python
class PortfolioRotationConfigSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source='account.account_name', read_only=True)
    account_type = serializers.CharField(source='account.account_type', read_only=True)

    class Meta:
        model = PortfolioRotationConfigModel
        fields = [
            'id', 'account', 'account_name', 'account_type',
            'base_config', 'risk_tolerance', 'regime_allocations',
            'is_enabled', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_regime_allocations(self, value):
        """验证每个象限的权重之和为 1.0（允许 0.01 误差）"""
        for regime, allocations in value.items():
            total = sum(allocations.values())
            if abs(total - 1.0) > 0.01:
                raise serializers.ValidationError(
                    f"象限 {regime} 的权重之和为 {total:.2f}，必须为 1.0"
                )
        return value


class RotationTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RotationTemplateModel
        fields = ['id', 'key', 'name', 'description', 'regime_allocations', 'display_order']
```

---

### Phase 5: 初始化数据（替代硬编码模板）

**修改文件**: `apps/rotation/management/commands/init_rotation.py`

在现有初始化命令中增加 `RotationTemplateModel` 数据写入，**权重数据从文件/配置读取而非代码内联**：

```python
def handle(self, *args, **options):
    self._init_asset_classes()   # 已有
    self._init_rotation_configs()  # 已有
    self._init_risk_templates()    # 新增

def _init_risk_templates(self):
    """
    初始化预设模板。
    资产代码从已存在的 AssetClassModel 查询，不硬编码。
    如果资产不存在则跳过（容错）。
    """
    # 从 AssetClassModel 查出各类资产代码
    equity_codes = list(
        AssetClassModel.objects.filter(category='equity', is_active=True)
        .values_list('code', flat=True)[:3]
    )
    bond_codes = list(
        AssetClassModel.objects.filter(category='bond', is_active=True)
        .values_list('code', flat=True)[:2]
    )
    commodity_codes = list(
        AssetClassModel.objects.filter(category='commodity', is_active=True)
        .values_list('code', flat=True)[:1]
    )
    currency_codes = list(
        AssetClassModel.objects.filter(category='currency', is_active=True)
        .values_list('code', flat=True)[:1]
    )

    # 基于资产类型比例生成模板，不依赖具体代码
    templates = _build_templates(equity_codes, bond_codes, commodity_codes, currency_codes)

    for template_data in templates:
        RotationTemplateModel.objects.update_or_create(
            key=template_data['key'],
            defaults=template_data
        )
    self.stdout.write(self.style.SUCCESS(f"初始化 {len(templates)} 个预设模板"))
```

---

## 关键文件清单

| 操作 | 文件路径 |
|------|----------|
| **新建** | `apps/rotation/infrastructure/models.py` → 新增 `PortfolioRotationConfigModel`、`RotationTemplateModel` |
| **新建** | `apps/rotation/migrations/0002_portfolio_rotation_config.py` |
| **新建** | `apps/rotation/static/rotation/js/quadrant_editor.js` |
| **新建** | `apps/rotation/static/rotation/css/quadrant_editor.css` |
| **新建** | `apps/rotation/templates/rotation/components/quadrant_editor.html` |
| **新建** | `apps/rotation/templates/rotation/account_config.html` |
| **修改** | `apps/rotation/templates/rotation/configs.html` |
| **修改** | `apps/rotation/interface/views.py` |
| **修改** | `apps/rotation/interface/serializers.py` |
| **修改** | `apps/rotation/interface/api_urls.py` |
| **修改** | `apps/rotation/management/commands/init_rotation.py` |

---

## MCP 使用的 API 接口

MCP 可通过以下接口以编程方式配置各账户的轮动策略，无需操作 UI：

```
# 查看当前用户所有账户的 rotation 配置
GET  /api/rotation/account-configs/

# 查看特定账户配置
GET  /api/rotation/account-configs/by-account/{account_id}/

# 创建账户配置
POST /api/rotation/account-configs/
Body: {"account": 1, "risk_tolerance": "moderate", "regime_allocations": {...}, "is_enabled": true}

# 更新账户配置（包括 regime_allocations）
PUT  /api/rotation/account-configs/{id}/
PATCH /api/rotation/account-configs/{id}/

# 应用预设模板
POST /api/rotation/account-configs/{id}/apply-template/
Body: {"template_key": "conservative"}

# 查看可用模板（来自数据库，不硬编码）
GET  /api/rotation/templates/

# 查看象限列表（来自 regime 模块枚举）
GET  /api/rotation/regimes/

# 查看可配置资产列表
GET  /api/rotation/asset-classes/?is_active=true
```

---

## 用户操作流程

### 为账户配置轮动（新流程）

1. 用户访问 `/rotation/configs/`
2. 页面展示用户所有账户（real + simulated），每个账户显示当前轮动配置状态
3. 点击账户卡片的"配置轮动"
4. Modal 打开：
   - Tab 1 - 基本信息：选择风险偏好、开启/关闭轮动
   - Tab 2 - 象限配置：从 API 加载象限列表和资产列表，显示滑块编辑器；可选择预设模板（数据来自 DB）
   - Tab 3 - 配置预览：只读 JSON 摘要
5. 调整各象限资产权重，实时显示权重总和
6. 权重总和达到 100% 后允许保存
7. 提交到 `POST/PUT /api/rotation/account-configs/`

### 编辑现有配置

1. 账户卡片显示"当前：稳健型 | 轮动已启用"
2. 点击"编辑"，Modal 从 `GET /api/rotation/account-configs/by-account/{id}/` 加载现有配置
3. 象限编辑器显示已保存的权重
4. 调整后保存

---

## 技术要点

### 1. 权重验证（前后端双重）

**前端（实时）**:
```javascript
updateWeightSum(regime) {
    const allocs = this.allocations[regime] || {};
    const sum = Object.values(allocs).reduce((a, b) => a + b, 0);
    const valid = Math.abs(sum - 1.0) < 0.01;
    this._renderSumIndicator(regime, sum, valid);
    return valid;
}
```

**后端（保存时）**:
```python
# serializers.py → validate_regime_allocations()
for regime, allocations in value.items():
    total = sum(allocations.values())
    if abs(total - 1.0) > 0.01:
        raise ValidationError(f"象限 {regime} 权重之和为 {total:.2f}，必须为 1.0")
```

### 2. 资产与象限动态加载（不硬编码）

```javascript
async init() {
    // 并行请求，不在 JS 中硬编码任何资产代码或象限名称
    const [regimes, assets, templates] = await Promise.all([
        fetch('/api/rotation/regimes/').then(r => r.json()),
        fetch('/api/rotation/asset-classes/?is_active=true').then(r => r.json()),
        fetch('/api/rotation/templates/').then(r => r.json()),
    ]);
    this.regimes = regimes;
    this.assets = assets.results || assets;
    this.templates = templates.results || templates;
    this.render();
}
```

### 3. 模板应用

```javascript
async applyTemplate(templateKey) {
    // 直接使用已加载的模板数据，无需再次请求
    const template = this.templates.find(t => t.key === templateKey);
    if (!template) return;
    this.allocations = JSON.parse(JSON.stringify(template.regime_allocations));
    this.render();
    this.syncToHiddenInput();
}
```

### 4. 滑块与数字输入框双向绑定

```javascript
bindSliderInput(slider, input, regime, assetCode) {
    slider.oninput = () => {
        input.value = slider.value;
        this.allocations[regime][assetCode] = parseFloat(slider.value) / 100;
        this.updateWeightSum(regime);
        this.syncToHiddenInput();
    };
    input.onchange = () => {
        slider.value = input.value;
        this.allocations[regime][assetCode] = parseFloat(input.value) / 100;
        this.updateWeightSum(regime);
        this.syncToHiddenInput();
    };
}
```

---

## 验证计划

### 1. 数据层验证

```bash
# 迁移
python manage.py makemigrations rotation
python manage.py migrate

# 初始化数据
python manage.py init_rotation
```

### 2. API 验证

```bash
# 模板 API（从数据库读取，不硬编码）
curl -H "Authorization: ..." http://localhost:8000/api/rotation/templates/

# 象限列表（从 regime 模块读取）
curl -H "Authorization: ..." http://localhost:8000/api/rotation/regimes/

# 创建账户配置
curl -X POST http://localhost:8000/api/rotation/account-configs/ \
  -H "Content-Type: application/json" \
  -H "Authorization: ..." \
  -d '{"account": 1, "risk_tolerance": "moderate", "regime_allocations": {}, "is_enabled": false}'

# 应用模板
curl -X POST http://localhost:8000/api/rotation/account-configs/1/apply-template/ \
  -d '{"template_key": "conservative"}'

# MCP 按账户 ID 查询
curl http://localhost:8000/api/rotation/account-configs/by-account/1/
```

### 3. 前端功能验证

- [ ] 象限 Tab 从 API 动态生成（不硬编码）
- [ ] 资产滑块从 DB 资产列表动态生成
- [ ] 模板下拉从 DB 模板列表动态填充
- [ ] 权重总和实时计算，< 100% 时禁用保存按钮
- [ ] 加载现有配置时，滑块正确还原已保存权重
- [ ] 不同账户之间配置完全独立
- [ ] MCP API 可独立读写，不依赖 UI

### 4. 独立性验证

```bash
# 验证两个账户的配置互相独立
# 账户 1 设为 conservative，账户 2 设为 aggressive
# 修改账户 1 不影响账户 2
```

---

## 工作量估计

| 阶段 | 工作内容 | 预计时间 |
|------|----------|----------|
| Phase 0 | 数据模型 + 迁移 + 初始化命令 | 3-4 小时 |
| Phase 1 | 象限编辑器组件 (JS/CSS/HTML) | 3-4 小时 |
| Phase 2 | 账户配置页面 + Modal 改造 | 2-3 小时 |
| Phase 3 | 后端 API + ViewSet + URL 注册 | 2-3 小时 |
| Phase 4 | 序列化器 + 验证逻辑 | 1 小时 |
| Phase 5 | 初始化数据脚本 | 1 小时 |
| **总计** | | **12-16 小时** |

---

## 相关文档

- [Rotation 模块指南](../modules/rotation/rotation-guide.md)
- [前端设计指南](../architecture/frontend_design_guide.md)
- [策略模块文档](../modules/strategy/position-management.md)

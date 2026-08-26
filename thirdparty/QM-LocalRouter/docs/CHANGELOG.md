# 更新日志 (Changelog)

## 2026-07-11

---

### 后端更新

#### 1. VPN 全局代理兼容修复

**文件**: `backend/app/services/forwarder.py`

**问题**: 当用户开启 VPN 全局代理时，VPN 会设置系统环境变量 `HTTP_PROXY` / `HTTPS_PROXY`。httpx 默认读取这些环境变量（`trust_env=True`），导致所有出站请求经过 VPN 代理转发，而代理链路可能无法正确连接到上游 API 服务（如 api.openai.com），造成连接失败。

**修复**: 在所有 7 处 `httpx.AsyncClient` 创建时显式添加 `trust_env=False` 参数，忽略系统代理环境变量，直接连接上游服务器。

```python
# 修复前
async with httpx.AsyncClient(timeout=timeout) as client:

# 修复后
async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
```

涉及的 7 个方法：
- `forward()` — 非流式请求转发
- `forward_stream()` — 流式请求转发
- `forward_image()` — 图片生成请求转发
- `forward_tts()` — TTS 语音合成请求转发（OpenAI 协议 + Gemini 协议各 1 处）
- `forward_video()` — 视频生成请求转发
- `forward_video_get()` — 视频任务状态查询

---

#### 2. 新增「按 Token 限额切换」路由策略

##### 2.1 数据库模型扩展

**文件**: `backend/app/models/strategy.py`

`Strategy` 模型新增两列：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `rule_token_threshold` | Integer | 0 | Token 阈值，0 表示不限 |
| `rule_token_period` | String(20) | "per_day" | 统计周期：`per_minute` / `per_5min` / `per_day` / `per_month` |

##### 2.2 数据库自动迁移

**文件**: `backend/app/database.py`

在 `_add_missing_columns()` 函数中新增 2 行迁移语句，确保旧数据库自动添加新列：

```python
("strategies", "rule_token_threshold", "INTEGER DEFAULT 0"),
("strategies", "rule_token_period", "VARCHAR(20) DEFAULT 'per_day'"),
```

##### 2.3 Pydantic Schema 更新

**文件**: `backend/app/schemas/schemas.py`

- `StrategyCreate.lb_strategy` 正则验证从 `^(round_robin|weighted|random|failover|priority)$` 扩展为 `^(round_robin|weighted|random|failover|priority|token_threshold)$`
- `StrategyCreate` 新增字段：`rule_token_threshold: int = 0`、`rule_token_period: str = "per_day"`
- `StrategyUpdate` 新增字段：`rule_token_threshold: Optional[int] = None`、`rule_token_period: Optional[str] = None`
- `StrategyOut` 新增字段：`rule_token_threshold: int = 0`、`rule_token_period: str = "per_day"`

##### 2.4 Rule Token Tracker — 内存时间窗口计数器

**文件**: `backend/app/services/balancer.py`

新增 `RuleTokenTracker` 类，参照已有的 `KeyUsageTracker` 设计，按 `(strategy_id, rule_id)` 追踪每个规则的 Token 消耗：

```python
class RuleTokenTracker:
    PERIOD_SECONDS = {
        "per_minute": 60,
        "per_5min": 300,
        "per_day": 86400,
        "per_month": 2592000,
    }

    def is_over_threshold(self, strategy_id, rule_id, threshold, period) -> bool:
        # 判断该规则在当前时间窗口内是否超过 Token 阈值

    def record_usage(self, strategy_id, rule_id, tokens, period):
        # 记录 Token 用量，窗口过期自动重置
```

全局实例 `_rule_token_tracker` 供 proxy 层调用。

##### 2.5 Balancer 选择逻辑扩展

**文件**: `backend/app/services/balancer.py` — `Balancer.select_rule()`

新增 `token_threshold` 分支：

```python
elif method == "token_threshold":
    threshold = strategy.rule_token_threshold
    period = strategy.rule_token_period or "per_day"
    # 过滤出未超阈值的规则
    eligible = [r for r in rules if not _rule_token_tracker.is_over_threshold(
        strategy.id, r.id, threshold, period
    )]
    if not eligible:
        eligible = rules  # 全部超阈值则回退（best effort）
    return eligible[0]  # 取优先级最高的规则
```

**选择逻辑**: 在未超阈值的规则中，按优先级（priority 值最小）选择。当所有规则都超阈值时，回退到全部规则（与 key switch 行为一致）。

##### 2.6 Proxy 层 Token 用量记录

**文件**: `backend/app/routers/proxy.py`

在请求成功完成后，将实际消耗的 Token 数记录到 `_rule_token_tracker`：

- `_handle_non_stream()`: 从响应体 `usage.total_tokens` 获取并记录
- `_handle_stream()`: 从 SSE 最后一个 chunk 的 `usage` 字段获取并记录

```python
if strategy.lb_strategy == "token_threshold" and total_tok > 0:
    _rule_token_tracker.record_usage(
        strategy.id, rule.id, total_tok, strategy.rule_token_period or "per_day"
    )
```

---

### 前端更新

#### 1. 路由策略页面扩展

**文件**: `frontend/src/pages/Strategies.tsx`

##### 1.1 新增表单字段

`form` state 新增：
- `rule_token_threshold: 0` — Token 阈值输入
- `rule_token_period: 'per_day'` — 统计周期选择

`openCreate()`、`openEdit()`、`save()` 以及"由模型创建策略"对话框的表单初始化均已同步新增字段。

##### 1.2 新增负载均衡选项

`lbOptions` 数组新增：
```typescript
{ value: 'token_threshold', label: 'Token 限额', desc: '达到 Token 阈值后切换到下一模型' }
```

新增 `tokenPeriodOptions` 数组：
```typescript
[
  { value: 'per_minute', label: '每分钟' },
  { value: 'per_5min', label: '每5分钟' },
  { value: 'per_day', label: '每天' },
  { value: 'per_month', label: '每月' },
]
```

##### 1.3 条件输入 UI

当负载均衡策略选择"Token 限额"时，自动展开配置面板：
- **Token 阈值** — 数字输入框，带提示文字
- **统计周期** — 下拉选择（每分钟 / 每5分钟 / 每天 / 每月）

##### 1.4 策略卡片 Badge

策略列表中，当 `lb_strategy === 'token_threshold'` 且阈值 > 0 时，显示绿色 badge：
```
Token 限额: 100,000 / 每天
```

---

#### 2. 国际化翻译扩展

**文件**: `frontend/src/i18n/zh-CN.json`、`frontend/src/i18n/en-US.json`

新增 11 个翻译键：

| Key | 中文 | English |
|-----|------|---------|
| `strategies.optionTokenThreshold` | Token 限额 | Token Limit |
| `strategies.optionTokenThresholdDesc` | 达到 Token 阈值后切换到下一模型 | Switch when token usage reaches threshold |
| `strategies.tokenThreshold` | Token 阈值 | Token Threshold |
| `strategies.tokenThresholdDesc` | 模型在周期内消耗的 Token 数达到此值后自动切换 | Auto-switch when token consumption reaches this value within the period |
| `strategies.tokenPeriod` | 统计周期 | Statistics Period |
| `strategies.tokenPeriodMinute` | 每分钟 | Per Minute |
| `strategies.tokenPeriod5Min` | 每5分钟 | Per 5 Minutes |
| `strategies.tokenPeriodDay` | 每天 | Daily |
| `strategies.tokenPeriodMonth` | 每月 | Monthly |
| `strategies.tokenThresholdHint` | 当前周期内 Token 消耗达到此值时自动切换到下一个优先级的模型 | Switch to next priority model when token usage reaches this value within the current period |

---

### 涉及文件总览

| 文件 | 变更类型 |
|------|----------|
| `backend/app/services/forwarder.py` | 修复：7 处 httpx 客户端添加 `trust_env=False` |
| `backend/app/models/strategy.py` | 新增：2 个数据库列 |
| `backend/app/database.py` | 新增：2 行自动迁移 |
| `backend/app/schemas/schemas.py` | 新增：Schema 字段 + 正则扩展 |
| `backend/app/services/balancer.py` | 新增：`RuleTokenTracker` 类 + `token_threshold` 选择分支 |
| `backend/app/routers/proxy.py` | 新增：流式/非流式 Token 用量记录 |
| `frontend/src/pages/Strategies.tsx` | 新增：选项 + UI + Badge |
| `frontend/src/i18n/zh-CN.json` | 新增：11 个中文翻译键 |
| `frontend/src/i18n/en-US.json` | 新增：11 个英文翻译键 |

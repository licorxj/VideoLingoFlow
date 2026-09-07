# API 密钥统一管理与调用规范

> 本文是**后续接口代码开发的强制规范**：第三方能力（ASR/TTS/生图/视频生成/OCR/人声分离/AIGC/LLM 等）的 API Key 必须通过统一的「密钥管理」体系保存与读取，禁止把明文密钥写进随软件分发的配置文件。
> 实现入口：`backend/config/credential_store.py`（后端）、`frontend/src/components/shared/SecretPicker.tsx`（前端）。

---

## 1. 设计概述

```
┌─────────────────────────────────────────────┐
│ 配置文件（随软件分发 / 随 git 更新）              │
│  config.yaml / *_interfaces.json              │
│  api_key: "secret://OPENAI_API_KEY"   ←只存引用 │
└──────────────────┬──────────────────────────┘
                   │ 调用处 resolve()
┌──────────────────▼──────────────────────────┐
│ 用户私有数据库 data/control-plane.db           │
│  cp_credentials 表：name(唯一)/value/purpose  │
│  ← 不随分发、git 更新不覆盖、不被前端读取明文      │
└─────────────────────────────────────────────┘
```

三个关键不变量：

1. **配置文件里永远只有引用名**（`secret://NAME`），不落明文。
2. **前端永远拿不到明文**：所有下发到前端的 config 都经过 `mask_deep` 脱敏（`sk-a******7890`），引用名原样保留。
3. **调用处永远拿到真实值**：读取统一走 `ConfigManager.get()` 或各 `*_interface_manager` 的 `get()/list_all()/get_enabled()`，出口自动把引用解析为真实密钥（带 30s 进程内缓存）。

---

## 2. 引用格式与命名规范

| 项 | 规范 |
|---|---|
| 格式 | `secret://<NAME>`，如 `secret://OPENAI_API_KEY` |
| NAME 字符 | 仅字母/数字/下划线，字母开头；存储时统一转大写（`WHISPERX_LOCAL_HF_TOKEN`） |
| 命名建议 | `<服务商>_<用途>`，如 `OPENAI_API_KEY`、`HF_TOKEN`、`BAILIAN_SDK_API_KEY` |
| `purpose` 字段 | 必填说明用途，如「302.AI 聚合平台，用于 LLM 与 TTS」，密钥管理页与选择弹窗都会展示 |
| 多 key 存储 | 一个密钥条目的值支持**多行**（每行一个 key）。开启「轮询」后每次调用自动 round-robin 切换（游标由密钥管理器维护、节流回写 DB，重启可续）；关闭轮询则固定使用当前下标的 key，可在管理页手动切换。老数据（单 key 纯文本）自动兼容 |
| 唯一性 | NAME 全局唯一，**可被多处配置引用**（例如同一个 302 key 同时供 ASR/TTS 使用） |

---

## 3. 后端读取规范（调用处怎么取 key）

### 3.1 正确姿势

```python
# ✅ 走 ConfigManager——str 与 dict/list 都会自动解析 secret:// 引用
from backend.config.config_manager import config
cfg = config.get("llm")                    # dict，内部 api_key 已是真实值
key = config.get("aigc.runninghub.api_key")  # str，已解析

# ✅ 走 interface manager——get()/list_all()/get_enabled() 出口已解析
mgr = get_asr_interface_manager()
iface = mgr.get(iface_id)                  # config 中的引用已还原
for iface in mgr.get_enabled():            # 同样已解析
    key = iface["config"].get("api_key")
```

解析逻辑在 `backend/config/config_manager.py` 的 `_resolve_secret()`：值以 `secret://` 开头才查库（缓存 30s），普通字符串原样返回，无额外开销。

### 3.2 强制红线（反面教材，均为已修复或禁止的模式）

```python
# ❌ 直接 json.load 读 interfaces JSON —— 拿到的是 secret:// 引用，调用必失败
with open("backend/config/asr_interfaces.json") as f:
    data = json.load(f)
# 反例：历史上 s02_asr.py 的 _load_default_interface_config、confucius4_wrapper.py

# ❌ 用 get_all()/get_snapshot() 后取密钥——这两个方法不解析（供前端展示用）
cfg = config.get_all()["llm"]["api_key"]

# ❌ 绕过出口直接摸 manager 内部字典
mgr._interfaces[iface_id]["config"]["api_key"]

# ❌ 把明文密钥写死在代码 / config.yaml / interfaces JSON / 工作流 JSON 里
```

**自检方法**：新增读取密钥的代码时，`grep` 确认取值路径上没有直接 `json.load`、没有 `get_all()/get_snapshot()`、没有 `_interfaces[`。

---

## 4. 后端写入规范（API 层）

### 4.1 响应必须脱敏

任何把接口 config / 全局 config 下发给前端的 `return`，都要包一层 `mask_deep`：

```python
from backend.config.credential_store import mask_deep

return {"interfaces": mask_deep(mgr.list_all())}      # ✅
return {"interface": mask_deep(iface)}                # ✅
return {"config": mask_deep(config.get_all())}        # ✅ 全局设置
```

`mask_deep` 只对白名单字段名脱敏（`api_key`、`sdk_api_key`、`hf_token`、`wallet_api_key`、`router_api_key`、`token`、`password` 等，见 `credential_store.SECRET_FIELD_NAMES`），`secret://` 引用名原样保留，`custom_params` 里的 `key` 参数名不受影响。

### 4.2 掩码回写保护（已内建，勿绕过）

前端未修改密钥时会把下发的掩码串原样提交回来。Manager 的 `update()` 已统一接入 `merge_preserving_masked()`：新值是掩码串时沿用旧值，**掩码永远不会写进配置文件**。自己实现 update 逻辑时必须同样处理：

```python
from backend.config.credential_store import merge_preserving_masked

if "config" in data:
    iface["config"] = merge_preserving_masked(iface.get("config") or {}, data["config"] or {})
```

---

## 5. 密钥管理 API（`/api/credentials`）

| 端点 | 说明 |
|---|---|
| `GET /api/credentials` | 列表（默认脱敏）；`?keyword=` 搜索、`?reveal=true` 返回明文（仅编辑回填） |
| `POST /api/credentials` | 创建 `{name, value, purpose, rotate}`；`value` 为多行文本（每行一个 key）；名称非法/重复返回 400 |
| `GET /api/credentials/{id}` | 详情；`?reveal=true` 取明文（多 key 以换行返回） |
| `PUT /api/credentials/{id}` | 更新（可改名/改值/改用途说明/开关轮询 `rotate`） |
| `DELETE /api/credentials/{id}` | 删除 |
| `GET /api/credentials/usage/{id}` | 返回该密钥被哪些配置路径引用（删除前提示用） |

核心函数（`backend/config/credential_store.py`）：`to_ref/from_ref/is_secret_ref/resolve/resolve_deep/mask_value/mask_deep/mask_value`、`get_raw`（带缓存）、`invalidate`（写操作后自动失效缓存）。

---

## 6. 前端规范（设置页怎么写 key 输入）

**一律使用密钥匹配控件，禁止明文 `<input type="password">`。**

```tsx
// ✅ 静态表单：用 SecretField 替换原来的密钥输入框
import { SecretField } from "@/components/shared/SecretPicker";

<SecretField
  label="API 密钥"
  value={config.api_key || ""}
  onChange={(v) => uc("api_key", v)}   // v 为 "secret://NAME" 引用（清除时为 ""）
/>
```

```tsx
// ✅ 动态表单（rows 数组渲染）：按字段名分支
import { SecretField, isSecretRowKey } from "@/components/shared/SecretPicker";

{getParamRows().map((row) => (
  <div key={row.key}>
    {isSecretRowKey(row.key) ? (
      <SecretField label={row.label} hint={row.description}
        value={(config as any)[row.key] ?? ""} onChange={(v) => uc(row.key, v)} />
    ) : (
      /* 原有普通 input */
    )}
  </div>
))}
```

组件能力：展示已绑定的密钥名（点击按钮弹出选择器，可搜索、可选已有、**可快捷新建**）；对历史明文值显示"建议改为引用"警告；一键解除绑定。`onChange` 只在用户确认选择/解绑时触发，不会自动回传掩码。

---

## 7. 新增接口域的开发检查清单

除《接口添加指南.md》四件套外，涉及密钥的部分必须完成：

- [ ] Manager：`get()/list_all()/get_enabled()` 出口套 `resolve_deep`；`update()` 对 config 套 `merge_preserving_masked`
- [ ] API：所有返回接口 config 的端点套 `mask_deep`
- [ ] 步骤/引擎：**只**通过 Manager 或 `config.get()` 取配置，禁止直接读 JSON/YAML
- [ ] 前端编辑器：密钥字段用 `SecretField`（静态）或 `isSecretRowKey`（动态表单）
- [ ] `_default_config` 模板中密钥字段留空 `""`（不要写示例 key）

---

## 8. 历史数据迁移与运维

```bash
python scripts/migrate_secrets_to_db.py          # 预演：列出将迁移的明文密钥
python scripts/migrate_secrets_to_db.py --apply  # 执行：入库 + 配置替换为引用（原文件备份 *.bak）
```

- 迁移后请重启后端使引用生效；历史明文已进过磁盘/可能进过 git，建议在服务商侧**轮换一次**。
- **备份语义变化**：配置导出文件只有引用名，导入到另一台机器后需在目标机「密钥管理」重建，或一并拷贝 `data/control-plane.db`。
- Pi Agent 的 `custom_api_key` 存放于 `pi_sessions.db`（同为用户私有库），暂未纳入本体系。
- pyannote 等 gated 模型的 HF token：接口配置 `hf_token`（可绑 `HF_TOKEN` 密钥）→ 环境变量 `HF_TOKEN`/`HUGGING_FACE_HUB_TOKEN` → 本地模型缓存（无需 token）。

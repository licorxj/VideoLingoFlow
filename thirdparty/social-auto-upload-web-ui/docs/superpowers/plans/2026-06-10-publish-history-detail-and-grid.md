# 发布历史详情页 + 列表卡片网格 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把发布历史列表改为 4 列自适应卡片网格，新增 `/publish-history/:batchId` 详情页（复用 `AccountSidebar` readonly 模式），后端新增单批次查询端点。

**Architecture:** 后端 1 个新端点（读现有 `publish_batches` + `publish_details`）；前端 2 个新共用组件（ChannelSummary/PublishStats）；1 个组件重构（AccountSidebar 加 `mode` prop）；1 个新视图（PublishHistoryDetail）；1 个视图重构（PublishHistory 改卡片网格）。

**Tech Stack:** 后端 Flask + SQLite（已有）；前端 Vue 3 + Element Plus + Pinia（已有）。UI 实施阶段必须调用 `ui-ux-pro-max-skill` 相关 skill 协助设计（**这是用户 2026-06-10 明确要求**）。

**依赖前置：** 无新增依赖。沿用现有框架。

---

## Phase 1 — 后端

### Task 1: 单批次查询端点（GET /api/v2/history/<batch_id>）

**Files:**
- Create: `backend/tests/test_history_detail_endpoint.py`
- Modify: `backend/ext_api/__init__.py` (紧跟现有 `get_history` 之后，约 410 行)

- [ ] **Step 1: 写失败测试（5 个用例）**

创建 `backend/tests/test_history_detail_endpoint.py`：

```python
"""
测试 GET /api/v2/history/<batch_id> 单批次详情端点。
- 200：返回 batch + items（与列表 item 结构一致）
- 404：不存在的 batch_id
- 200 + items=[]：存在 batch 但无明细
- 账号已删除但 detail 仍保留 account_name 历史值
- duration 计算：started_at+finished_at 有 → 整数秒；缺 → null
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS publish_batches (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    video_material_id TEXT DEFAULT '',
    image_material_ids TEXT DEFAULT '[]',
    landscape_cover_material_id TEXT DEFAULT '',
    portrait_cover_material_id TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    account_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    schedule_time TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS publish_details (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    account_id INTEGER,
    account_name TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    account_configs TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    error_message TEXT NOT NULL DEFAULT '',
    publish_url TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES publish_batches(id) ON DELETE CASCADE
);
"""


class TestHistoryDetailEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        os.environ['SAU_DATA_DIR'] = cls._tmpdir
        cls.DB_PATH = Path(cls._tmpdir) / "db" / "database.db"
        cls.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(cls.DB_PATH))
        conn.executescript(_SCHEMA_SQL)
        # b1: 3 账号全成功，b1 本身 started_at/finished_at 都有
        conn.execute(
            "INSERT INTO publish_batches (id, type, title, status, account_count, success_count, failed_count, created_at, started_at, finished_at) "
            "VALUES ('b1', 'video', '测试视频', 'success', 3, 3, 0, '2026-06-01 10:00:00', '2026-06-01 10:00:00', '2026-06-01 10:00:08')"
        )
        # b2: 2 账号 1 失败
        conn.execute(
            "INSERT INTO publish_batches (id, type, title, status, account_count, success_count, failed_count, created_at) "
            "VALUES ('b2', 'image', '测试图文', 'partial', 2, 1, 1, '2026-06-02 10:00:00')"
        )
        # b3: 存在但无明细
        conn.execute(
            "INSERT INTO publish_batches (id, type, title, status, account_count, success_count, failed_count, created_at) "
            "VALUES ('b3', 'video', '空批次', 'pending', 0, 0, 0, '2026-06-03 10:00:00')"
        )
        # b1 的 3 个明细，d1 给了 started/finished（duration=8s）
        conn.execute("INSERT INTO publish_details (id, batch_id, account_id, account_name, platform, account_configs, status, started_at, finished_at) VALUES ('d1', 'b1', 101, '账号A', '抖音', '{\"title\":\"测试视频\"}', 'success', '2026-06-01 10:00:00', '2026-06-01 10:00:08')")
        conn.execute("INSERT INTO publish_details (id, batch_id, account_id, account_name, platform, account_configs, status) VALUES ('d2', 'b1', 102, '账号B', '小红书', '{\"title\":\"测试视频\"}', 'success')")
        # d3: account_id=999（已删除账号）但 account_name 保留
        conn.execute("INSERT INTO publish_details (id, batch_id, account_id, account_name, platform, account_configs, status) VALUES ('d3', 'b1', 999, '账号C(已删)', 'B站', '{}', 'success')")
        # b2 的明细
        conn.execute("INSERT INTO publish_details (id, batch_id, account_id, account_name, platform, account_configs, status) VALUES ('d4', 'b2', 201, '账号D', '抖音', '{}', 'success')")
        conn.execute("INSERT INTO publish_details (id, batch_id, account_id, account_name, platform, account_configs, status, error_message) VALUES ('d5', 'b2', 202, '账号E', '小红书', '{}', 'failed', 'cookie 过期')")
        conn.commit()
        conn.close()
        from ext_api import app
        cls.client = app.test_client()

    def setUp(self):
        self._db_path_patch = patch('ext_api.DB_PATH', self.DB_PATH)
        self._db_path_patch.start()

    def tearDown(self):
        self._db_path_patch.stop()

    def test_returns_batch_with_items(self):
        """存在 batch + items：200，data 包含 batch 字段 + items 数组，account_configs 已反序列化"""
        resp = self.client.get('/api/v2/history/b1')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['code'], 200)
        data = body['data']
        self.assertEqual(data['id'], 'b1')
        self.assertEqual(data['title'], '测试视频')
        self.assertEqual(data['account_count'], 3)
        self.assertEqual(len(data['items']), 3)
        # d1 的 account_configs 已被反序列化为 dict
        d1 = next(d for d in data['items'] if d['id'] == 'd1')
        self.assertEqual(d1['account_configs'], {'title': '测试视频'})
        # d1 计算出 duration=8
        self.assertEqual(d1['duration'], 8)
        # d2 没有 started/finished，duration=None
        d2 = next(d for d in data['items'] if d['id'] == 'd2')
        self.assertIsNone(d2['duration'])

    def test_404_when_batch_not_found(self):
        """不存在的 batch：404，code=404，msg 含"不存在\""""
        resp = self.client.get('/api/v2/history/does-not-exist')
        self.assertEqual(resp.status_code, 404)
        body = resp.get_json()
        self.assertEqual(body['code'], 404)
        self.assertIn('不存在', body['msg'])

    def test_empty_items(self):
        """存在 batch 但无明细：200，items=[]"""
        resp = self.client.get('/api/v2/history/b3')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['code'], 200)
        self.assertEqual(body['data']['id'], 'b3')
        self.assertEqual(body['data']['items'], [])

    def test_deleted_account_keeps_account_name(self):
        """账号已删除（account_id 在 store 找不到）：200，item.account_name 仍保留历史值"""
        resp = self.client.get('/api/v2/history/b1')
        body = resp.get_json()
        d3 = next(d for d in body['data']['items'] if d['id'] == 'd3')
        self.assertEqual(d3['account_id'], 999)
        self.assertEqual(d3['account_name'], '账号C(已删)')

    def test_failed_item_includes_error_message(self):
        """失败 item 含 error_message 字段"""
        resp = self.client.get('/api/v2/history/b2')
        body = resp.get_json()
        d5 = next(d for d in body['data']['items'] if d['id'] == 'd5')
        self.assertEqual(d5['status'], 'failed')
        self.assertEqual(d5['error_message'], 'cookie 过期')
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend
python -m pytest tests/test_history_detail_endpoint.py -v
```

Expected: 全部 5 个用例 FAIL（端点未实现 → 404 / AttributeError）。

- [ ] **Step 3: 实现端点**

编辑 `backend/ext_api/__init__.py`，在 `@ext_api.route('/history', methods=['GET'])` 函数（结束于约 409 行 `return jsonify({...})` 之后）后插入：

```python
@ext_api.route('/history/<batch_id>', methods=['GET'])
def get_history_batch(batch_id):
    """获取单个发布批次详情（含所有明细）

    Response 200:
        {"code": 200, "data": <Batch with items>}
    Response 404:
        {"code": 404, "msg": "记录不存在或已被删除"}
    """
    try:
        conn = _db_conn()
        row = conn.execute(
            "SELECT * FROM publish_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if not row:
            conn.close()
            return jsonify({"code": 404, "msg": "记录不存在或已被删除"}), 404

        b = dict(row)
        detail_rows = conn.execute(
            "SELECT * FROM publish_details WHERE batch_id = ? ORDER BY created_at ASC",
            (batch_id,)
        ).fetchall()
        items = []
        for d in detail_rows:
            dd = dict(d)
            try:
                dd['account_configs'] = json.loads(dd.get('account_configs', '{}'))
            except json.JSONDecodeError:
                dd['account_configs'] = {}
            if dd.get('started_at') and dd.get('finished_at'):
                try:
                    s = datetime.fromisoformat(dd['started_at'])
                    f = datetime.fromisoformat(dd['finished_at'])
                    dd['duration'] = int((f - s).total_seconds())
                except (ValueError, TypeError):
                    dd['duration'] = None
            else:
                dd['duration'] = None
            dd['personalized'] = compute_personalized(
                dd.get('account_configs') or {}, b
            )
            items.append(dd)
        conn.close()

        # 兜底封面：batch 列 material_id 为空时，从第一个 detail 的 account_configs 取
        fallback_cover_url = ''
        if items:
            first_cfg = items[0].get('account_configs') or {}
            fallback_cover_url = (
                _resolve_cover_from_path(first_cfg.get('thumbnailLandscape', ''))
                or _resolve_cover_from_path(first_cfg.get('thumbnailPortrait', ''))
            )

        data = {
            'id': b['id'],
            'type': b['type'],
            'title': b.get('title', ''),
            'description': b.get('description', ''),
            'landscape_cover_material_id': b.get('landscape_cover_material_id', ''),
            'portrait_cover_material_id': b.get('portrait_cover_material_id', ''),
            'cover_url': _resolve_cover_url(b.get('landscape_cover_material_id', ''))
                        or _resolve_cover_url(b.get('portrait_cover_material_id', ''))
                        or fallback_cover_url,
            'account_count': b.get('account_count', 0),
            'success_count': b.get('success_count', 0),
            'failed_count': b.get('failed_count', 0),
            'status': b.get('status', 'pending'),
            'schedule_time': b.get('schedule_time', ''),
            'created_at': _to_beijing_time(b.get('created_at')),
            'started_at': _to_beijing_time(b.get('started_at')),
            'finished_at': _to_beijing_time(b.get('finished_at')),
            'items': items,
        }
        return jsonify({"code": 200, "data": data})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)}), 500
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
python -m pytest tests/test_history_detail_endpoint.py -v
```

Expected: 5 个用例全部 PASS。

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
python -m pytest tests/ -v
```

Expected: 全部 PASS（不影响 `test_history_endpoint.py` 等已有测试）。

- [ ] **Step 6: 提交**

```bash
git add backend/ext_api/__init__.py backend/tests/test_history_detail_endpoint.py
git commit -m "feat(history): 新增 GET /api/v2/history/<batch_id> 单批次详情端点

返回 batch 字段 + items 明细数组。账号已删除时保留历史 account_name。
404 时返回 HTTP 404 + body code:404，与现有 ext_api 错误格式一致。
包含 5 个单测覆盖 200/404/空 items/已删账号/duration 计算。
```

---

## Phase 2 — 前端 API 层

### Task 2: 添加 historyApi.getBatch

**Files:**
- Modify: `frontend/src/api/v2.js` (在 `historyApi` 对象里加一行)

- [ ] **Step 1: 添加 getBatch 方法**

编辑 `frontend/src/api/v2.js`，把 `historyApi` 替换为：

```js
// 发布历史
export const historyApi = {
  getHistory(params) {
    // params: { type?: 'video'|'image', status?, timeRange?, startDate?, endDate?, page, pageSize }
    // 返回: data.items = [{id, type, title, ..., items: [{id, account_name, platform, status, ...}]}, ...]
    return http.get('/api/v2/history', params)
  },
  getBatch(batchId) {
    return http.get(`/api/v2/history/${batchId}`)
  },
}
```

- [ ] **Step 2: 提交**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui
git add frontend/src/api/v2.js
git commit -m "feat(api): historyApi.getBatch(batchId) 包装单批次详情端点"
```

---

## Phase 3 — 前端共用组件

> **本阶段所有 UI 实现任务在写代码前必须先调用 Skill `ui-ux-pro-max-skill`（或当前可用的 ui-ux-pro-max 技能），把建议落地到代码再提交。**

### Task 3: ChannelSummary.vue（渠道徽章 + marquee）

**Files:**
- Create: `frontend/src/components/ChannelSummary.vue`

- [ ] **Step 1: 加载 UI 技能**

```text
在终端输入：/ui-ux-pro-max-skill
让该 skill 给"渠道徽章行（×N 平台 pill）"的设计建议（间距、溢出 marquee 动画、品牌色处理）。
```

按 skill 建议继续下一步。

- [ ] **Step 2: 实现组件**

创建 `frontend/src/components/ChannelSummary.vue`：

```vue
<template>
  <div class="channel-summary">
    <div
      class="channels-track"
      :class="{ 'channels-marquee': isOverflow }"
      :ref="el => setRef(el)"
    >
      <span v-for="ch in channels" :key="ch.platform" class="channel-tag">
        <img v-if="ch.logo" :src="ch.logo" class="channel-icon" :alt="ch.name" />
        <span>{{ ch.name }} × {{ ch.count }}</span>
      </span>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, watch } from 'vue'

const props = defineProps({
  channels: { type: Array, required: true },
  overflowKey: { type: [String, Number], default: '' },
})

const trackEl = ref(null)
const isOverflow = ref(false)

function setRef(el) {
  if (el) trackEl.value = el
}

function checkOverflow() {
  if (!trackEl.value) return
  isOverflow.value = trackEl.value.scrollWidth > trackEl.value.parentElement.clientWidth
}

watch(
  () => [props.channels, props.overflowKey],
  () => {
    nextTick(checkOverflow)
  },
  { immediate: true, deep: true }
)
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.channel-summary {
  overflow: hidden;
}

.channels-track {
  display: inline-flex;
  gap: 6px;
  white-space: nowrap;
}

.channels-marquee {
  animation: channels-marquee 8s linear infinite;
}

.channel-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: $text-secondary;
  background: rgba(255, 255, 255, 0.06);
  padding: 2px 8px;
  border-radius: 10px;
  flex-shrink: 0;
}

.channel-icon {
  width: 14px;
  height: 14px;
  border-radius: 2px;
  object-fit: contain;
}

@keyframes channels-marquee {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
</style>
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/ChannelSummary.vue
git commit -m "feat(components): ChannelSummary.vue 渠道徽章 + 溢出 marquee"
```

---

### Task 4: PublishStats.vue（4 指标占位）

**Files:**
- Create: `frontend/src/components/PublishStats.vue`

- [ ] **Step 1: 加载 UI 技能**

```text
/ui-ux-pro-max-skill
让 skill 给出"4 指标占位卡（播放/点赞/收藏/评论）"的视觉建议（图标大小、间距、占位色、tooltip 风格）。
```

- [ ] **Step 2: 实现组件**

创建 `frontend/src/components/PublishStats.vue`：

```vue
<template>
  <div class="publish-stats">
    <div v-for="item in metrics" :key="item.key" class="stat-item">
      <el-tooltip
        :content="'数据统计功能开发中'"
        placement="top"
        :disabled="false"
      >
        <div class="stat-inner">
          <el-icon class="stat-icon" :size="16">
            <component :is="item.icon" />
          </el-icon>
          <span class="stat-label">{{ item.label }}</span>
          <span class="stat-value">{{ formatValue(item.value) }}</span>
        </div>
      </el-tooltip>
    </div>
  </div>
</template>

<script setup>
import { VideoPlay, Star, Collection, ChatLineRound } from '@element-plus/icons-vue'

const props = defineProps({
  views: { type: [Number, String, null], default: null },
  likes: { type: [Number, String, null], default: null },
  favorites: { type: [Number, String, null], default: null },
  comments: { type: [Number, String, null], default: null },
})

const metrics = [
  { key: 'views', label: '播放', value: props.views, icon: VideoPlay },
  { key: 'likes', label: '点赞', value: props.likes, icon: Star },
  { key: 'favorites', label: '收藏', value: props.favorites, icon: Collection },
  { key: 'comments', label: '评论', value: props.comments, icon: ChatLineRound },
]

function formatValue(v) {
  if (v == null) return '--'
  if (typeof v === 'number') {
    if (v >= 10000) return (v / 10000).toFixed(1) + 'w'
    return v.toLocaleString('zh-CN')
  }
  return v
}
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.publish-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.stat-item {
  border: 1px solid $border;
  border-radius: $radius-base;
  background: rgba(255, 255, 255, 0.02);
  padding: 12px 14px;
  transition: $transition-base;

  &:hover {
    border-color: $border-active;
  }
}

.stat-inner {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stat-icon {
  color: $text-muted;
  flex-shrink: 0;
}

.stat-label {
  font-size: 12px;
  color: $text-muted;
  flex: 1;
}

.stat-value {
  font-size: 14px;
  font-weight: 600;
  color: $text-primary;
  font-variant-numeric: tabular-nums;
}
</style>
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/PublishStats.vue
git commit -m "feat(components): PublishStats.vue 4 指标占位卡（值=null 时显示 --）"
```

---

## Phase 4 — AccountSidebar 重构

### Task 5: AccountSidebar 加 mode prop + 模板分支

**Files:**
- Modify: `frontend/src/components/AccountSidebar.vue`（在 script setup defineProps 加 `mode`；模板用 `v-if="mode === 'edit'"` 包裹 footer/remove/override 元素）

- [ ] **Step 1: 加载 UI 技能**

```text
/ui-ux-pro-max-skill
让 skill 给出"账号列表 readonly 模式的视觉建议"（是否去掉 group 高亮、状态点是否要更醒目、间距是否需要调整）。
```

- [ ] **Step 2: 修改 defineProps**

把 `defineProps({...})` 整个对象改为：

```js
defineProps({
  mode: {
    type: String,
    default: 'edit',
    validator: v => ['edit', 'readonly'].includes(v),
  },
  accountGroups: { type: Array, required: true },
  totalCount: { type: Number, required: true },
  selectedPlatform: { type: String, default: null },
  selectedAccountId: { type: [Number, String], default: null },
  expandedGroups: { type: Set, required: true },
  publishAccountIds: { type: Set, required: true },
  hasAccountOverride: { type: Function, required: true },
})
```

- [ ] **Step 3: 模板分支化（sidebar-footer、account-remove、has-override 角标）**

在模板中找到 `<div class="sidebar-footer">` 整段（"+ 添加账号"），在它的开标签 `<div class="sidebar-footer">` 上加 `v-if="mode === 'edit'"`，关闭的 `</div>` 不动。

找到 `<el-icon v-if="hasAccountOverride(account.id)" class="override-icon" ...>` 整段，包裹在 `v-if="mode === 'edit'"` 容器中（或者直接给该 `<el-icon>` 加 `v-if="hasAccountOverride(account.id) && mode === 'edit'"`）。

找到 `<el-icon class="account-remove" @click.stop="$emit('remove-account', account.id)"><Close /></el-icon>` 整段，同理加 `v-if="mode === 'edit'"`。

- [ ] **Step 4: group-accounts 列表过滤条件 + group-count 徽章分支化**

在 `v-for="account in group.accounts.filter(...)"` 那行（PublishCenter 调用场景的过滤）改为：

```vue
v-for="account in group.accounts.filter(a => mode === 'readonly' ? true : publishAccountIds.has(a.id))"
```

在 `<span class="group-count">{{ group.accounts.filter(a => publishAccountIds.has(a.id)).length }}</span>` 那行改为：

```vue
<span class="group-count">{{ mode === 'readonly' ? group.accounts.length : group.accounts.filter(a => publishAccountIds.has(a.id)).length }}</span>
```

- [ ] **Step 5: 提交（不改调用方，让 PublishCenter 显式传 mode）**

```bash
git add frontend/src/components/AccountSidebar.vue
git commit -m "refactor(AccountSidebar): 新增 mode='edit'|'readonly' prop，模板按 mode 分支渲染"
```

---

### Task 6: PublishCenter 调用方显式传 mode='edit'（无行为变化）

**Files:**
- Modify: `frontend/src/views/PublishCenter.vue` (AccountSidebar 调用块，约 4-16 行)

- [ ] **Step 1: 添加 mode='edit' 显式 prop**

把现有 AccountSidebar 调用块：

```vue
<AccountSidebar
  :account-groups="accountGroups"
  ...
/>
```

改为：

```vue
<AccountSidebar
  :mode="'edit'"
  :account-groups="accountGroups"
  :total-count="totalCount"
  :selected-platform="selectedPlatform"
  :selected-account-id="selectedAccountId"
  :expanded-groups="expandedGroups"
  :publish-account-ids="publishAccountIds"
  :has-account-override="hasAccountOverride"
  @toggle-group="toggleGroup"
  @select-account="selectAccount"
  @remove-account="removePublishAccount"
  @open-account-dialog="accountDialogVisible = true"
/>
```

- [ ] **Step 2: 手动回归 — 启动后端 + 前端 dev server，验证 PublishCenter 流程**

```bash
# 终端 1：后端
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend
python3 app.py

# 终端 2：前端
cd /home/czy/workspace/ai/social-auto-upload-web-ui/frontend
npm run dev
```

浏览器打开 `http://localhost:5173/#/publish-center`，验证：
- 左侧账号列表正常渲染
- 点平台分组可展开/收起
- 点账号选中状态切换
- 已选账号的 `×` 移除按钮存在且可点
- 「+ 添加账号」按钮存在

任何一项失败 → 修复 AccountSidebar 模板分支直到通过。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/PublishCenter.vue
git commit -m "refactor(PublishCenter): AccountSidebar 显式传 mode='edit'，无行为变化"
```

---

## Phase 5 — 详情页

### Task 7: PublishHistoryDetail.vue + 路由

**Files:**
- Create: `frontend/src/views/PublishHistoryDetail.vue`
- Modify: `frontend/src/router/index.js`

- [ ] **Step 1: 加载 UI 技能**

```text
/ui-ux-pro-max-skill
让 skill 给出"详情页（顶栏 + 左账号栏 + 右 4 区块主区）"的视觉建议：留白节奏、卡片圆角、强调色、失败降级的红色卡样式。
```

- [ ] **Step 2: 创建 PublishHistoryDetail.vue**

创建 `frontend/src/views/PublishHistoryDetail.vue`：

```vue
<template>
  <div class="publish-history-detail">
    <!-- 顶部导航条 -->
    <header class="page-header">
      <el-button link :icon="ArrowLeft" @click="goBack">返回</el-button>
      <div class="header-info">
        <h1 class="batch-title">{{ batch?.title || '加载中...' }}</h1>
        <span v-if="batch" class="status-tag" :class="`status-${batch.status}`">
          {{ statusLabel(batch.status) }}
        </span>
        <span v-if="batch?.created_at" class="header-time">{{ formatTime(batch.created_at) }}</span>
      </div>
    </header>

    <div class="detail-body">
      <!-- 左侧：账号栏 -->
      <aside v-if="batch" class="detail-sidebar">
        <AccountSidebar
          :mode="'readonly'"
          :account-groups="readonlyAccountGroups"
          :total-count="batchAccounts.length"
          :selected-platform="null"
          :selected-account-id="selectedAccountId"
          :expanded-groups="expandedGroups"
          :publish-account-ids="readonlyPublishAccountIds"
          :has-account-override="() => false"
          @toggle-group="toggleGroup"
          @select-account="selectAccount"
        />
      </aside>

      <!-- 右侧：主区域 -->
      <main class="detail-main" v-loading="loading">
        <!-- 5xx 重试条 -->
        <div v-if="error" class="error-bar">
          <el-icon><WarningFilled /></el-icon>
          <span>{{ error }}</span>
          <el-button size="small" @click="fetchDetail">重试</el-button>
        </div>

        <!-- 空状态 -->
        <div v-else-if="!selectedItem" class="empty-state">
          <el-icon class="empty-icon"><DocumentRemove /></el-icon>
          <p>该批次暂无账号数据</p>
          <p v-if="batchAccounts.length === 0 && batch?.account_count > 0" class="empty-hint">
            该批次的账号已被全部删除，请前往
            <router-link to="/account-management">账号管理</router-link>
            查看
          </p>
        </div>

        <template v-else>
          <!-- 1. 账号信息头 -->
          <section class="account-header">
            <div class="avatar" :style="{ borderColor: currentPlatformConfig?.color || '#666' }">
              {{ selectedAccount?.name?.charAt(0) || '?' }}
            </div>
            <div class="header-text">
              <div class="line-1">
                <span class="account-name">{{ selectedAccount?.name || '已删除账号' }}</span>
                <span v-if="currentPlatformConfig" class="platform-badge" :style="{ background: currentPlatformConfig.color + '20', color: currentPlatformConfig.color }">
                  {{ currentPlatformConfig.name }}
                </span>
                <span class="status-tag" :class="`status-${selectedItem.status}`">{{ statusLabel(selectedItem.status) }}</span>
              </div>
              <div class="line-2">
                <span class="meta-time">{{ formatTime(selectedItem.created_at) }}</span>
                <span v-if="selectedItem.duration" class="meta-time">耗时 {{ formatDuration(selectedItem.duration) }}</span>
              </div>
            </div>
            <a
              v-if="selectedItem.status === 'success' && selectedItem.publish_url"
              :href="selectedItem.publish_url"
              target="_blank"
              rel="noopener noreferrer"
              class="view-link"
            >
              查看发布作品 →
            </a>
          </section>

          <!-- 2. 内容快照 -->
          <section v-if="selectedItem.status === 'failed'" class="content-snapshot failed">
            <div class="failed-icon">
              <el-icon :size="40"><CircleCloseFilled /></el-icon>
            </div>
            <div class="failed-text">
              <h3>发布失败</h3>
              <p>{{ selectedItem.error_message || '未知错误' }}</p>
            </div>
          </section>
          <section v-else class="content-snapshot">
            <div class="snapshot-cover">
              <img v-if="getCoverUrl(selectedItem)" :src="getCoverUrl(selectedItem)" :alt="batch?.title" />
              <div v-else class="cover-placeholder">
                <el-icon :size="40"><Picture /></el-icon>
              </div>
            </div>
            <div class="snapshot-body">
              <h3 class="snapshot-title">{{ getCfgField(selectedItem, 'title') || batch?.title || '无标题' }}</h3>
              <p class="snapshot-desc">{{ getCfgField(selectedItem, 'description') || batch?.description || '无描述' }}</p>
              <div v-if="getCfgField(selectedItem, 'tags')?.length" class="snapshot-tags">
                <el-tag v-for="t in getCfgField(selectedItem, 'tags')" :key="t" size="small" effect="plain">#{{ t }}</el-tag>
              </div>
              <div v-if="getCfgField(selectedItem, 'creationDeclaration')" class="snapshot-meta">
                <span class="meta-label">作品声明</span>
                <span>{{ getCfgField(selectedItem, 'creationDeclaration') }}</span>
              </div>
              <div v-if="getCfgField(selectedItem, 'scheduleTime')" class="snapshot-meta">
                <span class="meta-label">定时发布时间</span>
                <span>{{ getCfgField(selectedItem, 'scheduleTime') }}</span>
              </div>
            </div>
          </section>

          <!-- 3. 数据统计 -->
          <section class="data-stats">
            <h3 class="section-title">数据统计</h3>
            <PublishStats />
          </section>

          <!-- 4. 批次元信息 -->
          <section class="batch-meta">
            <el-collapse v-model="metaOpen">
              <el-collapse-item title="批次元信息" name="meta">
                <div class="meta-grid">
                  <div class="meta-item">
                    <span class="meta-label">批次 ID</span>
                    <span class="meta-value">
                      <code>{{ batch?.id }}</code>
                      <el-button link size="small" @click="copyBatchId">复制</el-button>
                    </span>
                  </div>
                  <div class="meta-item">
                    <span class="meta-label">定时发布时间</span>
                    <span class="meta-value">{{ batch?.schedule_time || '未设置' }}</span>
                  </div>
                  <div class="meta-item">
                    <span class="meta-label">开始时间</span>
                    <span class="meta-value">{{ batch?.started_at || '—' }}</span>
                  </div>
                  <div class="meta-item">
                    <span class="meta-label">结束时间</span>
                    <span class="meta-value">{{ batch?.finished_at || '—' }}</span>
                  </div>
                  <div class="meta-item">
                    <span class="meta-label">账号数</span>
                    <span class="meta-value">
                      批次记录 {{ batch?.account_count }} ·
                      实际展示 {{ batchAccounts.length }}
                    </span>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </section>
        </template>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, WarningFilled, DocumentRemove, CircleCloseFilled, Picture } from '@element-plus/icons-vue'
import { useAccountStore } from '@/stores/account'
import { accountApi } from '@/api/account'
import { historyApi } from '@/api/v2'
import { platformList, getPlatformByKey } from '@/config/platforms'
import AccountSidebar from '@/components/AccountSidebar.vue'
import PublishStats from '@/components/PublishStats.vue'

const route = useRoute()
const router = useRouter()
const accountStore = useAccountStore()

const batch = ref(null)
const loading = ref(false)
const error = ref('')
const selectedAccountId = ref(null)
const metaOpen = ref([])
const expandedGroups = reactive(new Set())
const readonlyPublishAccountIds = new Set()  // 空 Set，AccountSidebar 内部不过滤

const batchAccounts = computed(() => {
  if (!batch.value) return []
  return accountStore.accounts.filter(a =>
    batch.value.items.some(it => it.account_id === a.id)
  )
})

const readonlyAccountGroups = computed(() => {
  return platformList
    .map(p => ({
      key: p.key,
      name: p.name,
      logo: p.logo,
      color: p.color,
      letter: p.letter,
      accounts: batchAccounts.value.filter(a => a.platform === p.name),
    }))
    .filter(g => g.accounts.length > 0)
})

const selectedItem = computed(() => {
  if (!batch.value || !selectedAccountId.value) return null
  return batch.value.items.find(it => it.account_id === selectedAccountId.value) || null
})

const selectedAccount = computed(() => {
  if (!selectedItem.value) return null
  return accountStore.accounts.find(a => a.id === selectedItem.value.account_id) || null
})

const currentPlatformConfig = computed(() => {
  if (!selectedAccount.value) return null
  const key = platformList.find(p => p.name === selectedAccount.value.platform)?.key
  return key ? getPlatformByKey(key) : null
})

function getCfgField(item, field) {
  return item?.account_configs?.[field]
}

function getCoverUrl(item) {
  if (!item) return ''
  const cfg = item.account_configs || {}
  const stored = cfg.coverLandscape?.stored_path || cfg.coverPortrait?.stored_path
  if (stored) {
    const cleaned = stored.replace(/^uploads\//, '')
    return `http://${window.location.hostname}:5409/uploads/${cleaned}`
  }
  return batch.value?.cover_url || ''
}

function statusLabel(status) {
  return ({
    pending: '等待中',
    running: '发布中',
    success: '全部成功',
    partial: '部分失败',
    failed: '全部失败',
    cancelled: '已取消',
  }[status] || status)
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatDuration(s) {
  if (s == null) return ''
  if (s < 60) return `${s}秒`
  return `${Math.floor(s / 60)}分${s % 60}秒`
}

async function copyBatchId() {
  try {
    await navigator.clipboard.writeText(batch.value.id)
    ElMessage.success('已复制批次 ID')
  } catch (e) {
    ElMessage.error('复制失败')
  }
}

function goBack() {
  router.push('/publish-history')
}

function toggleGroup(key) {
  if (expandedGroups.has(key)) expandedGroups.delete(key)
  else expandedGroups.add(key)
}

function selectAccount(account /*, group */) {
  selectedAccountId.value = account.id
}

async function fetchDetail() {
  error.value = ''
  loading.value = true
  try {
    const res = await historyApi.getBatch(route.params.batchId)
    // 拦截器只在 data.code === 200 时 resolve，否则 reject；到这里就是成功
    batch.value = res.data
    // 默认选中：找第一个 account_id 在 store 里能找到的 item
    const firstValid = batch.value.items.find(it =>
      it.account_id != null &&
      accountStore.accounts.some(a => a.id === it.account_id)
    )
    if (firstValid) selectedAccountId.value = firstValid.account_id
    // 展开所有有账号的组
    readonlyAccountGroups.value.forEach(g => expandedGroups.add(g.key))
  } catch (e) {
    // 拦截器已经 toast（4xx 用后端 msg，5xx 用通用文案）；这里只补行为
    if (e?.response?.status === 404) {
      // 批次不存在 → 跳回列表
      router.replace('/publish-history')
    } else if (e?.response?.status >= 500 || !e?.response) {
      // 服务端错误或网络错误 → 主区域顶部红条 + 重试按钮
      error.value = '加载失败，请稍后重试'
    } else {
      // 其它 4xx（401/403 等）→ 红条
      error.value = e.message || '加载失败'
    }
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  // 串行：先加载账号 store，再拉详情
  try {
    if (accountStore.accounts.length === 0) {
      const res = await accountApi.getAccounts()
      accountStore.setAccounts(res.data || [])
    }
  } catch (e) {
    console.error('加载账号列表失败:', e)
  }
  await fetchDetail()
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.publish-history-detail {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: $bg-base;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 16px;
  height: 56px;
  padding: 0 24px;
  border-bottom: 1px solid $border;
  background: $bg-elevated;
  flex-shrink: 0;

  .header-info {
    display: flex;
    align-items: center;
    gap: 12px;
    flex: 1;
    min-width: 0;
  }

  .batch-title {
    font-size: 16px;
    font-weight: 600;
    color: $text-primary;
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 400px;
  }

  .header-time {
    font-size: 12px;
    color: $text-muted;
  }
}

.detail-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.detail-sidebar {
  width: 232px;
  flex-shrink: 0;
  overflow-y: auto;
}

.detail-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 24px 28px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.status-tag {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;

  &.status-success, &.status-partial {
    background: rgba(82, 196, 26, 0.15);
    color: #67c23a;
  }
  &.status-failed {
    background: rgba(245, 108, 108, 0.15);
    color: #f56c6c;
  }
  &.status-running {
    background: rgba(64, 158, 255, 0.15);
    color: #409eff;
  }
  &.status-pending, &.status-cancelled {
    background: rgba(0, 0, 0, 0.06);
    color: $text-muted;
  }
}

.error-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: rgba(245, 108, 108, 0.1);
  border: 1px solid rgba(245, 108, 108, 0.3);
  border-radius: $radius-base;
  color: #f56c6c;
  font-size: 14px;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: $text-muted;
  text-align: center;
  gap: 8px;

  .empty-icon {
    font-size: 48px;
    opacity: 0.5;
  }

  p {
    margin: 0;
    font-size: 14px;
  }

  .empty-hint {
    font-size: 12px;
    a { color: $brand-start; }
  }
}

// 1. 账号信息头
.account-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: $bg-elevated;
  border: 1px solid $border;
  border-radius: $radius-card;

  .avatar {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: rgba(139, 92, 246, 0.15);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    color: #c4b5fd;
    font-weight: 700;
    border: 2px solid transparent;
    flex-shrink: 0;
  }

  .header-text {
    flex: 1;
    min-width: 0;

    .line-1 {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 4px;
    }

    .account-name {
      font-size: 16px;
      font-weight: 600;
      color: $text-primary;
    }

    .platform-badge {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 10px;
      font-weight: 500;
    }

    .line-2 {
      display: flex;
      gap: 12px;
      font-size: 12px;
      color: $text-muted;
    }
  }

  .view-link {
    color: $brand-start;
    font-size: 13px;
    text-decoration: none;
    flex-shrink: 0;
    &:hover { text-decoration: underline; }
  }
}

// 2. 内容快照
.content-snapshot {
  display: flex;
  gap: 16px;
  padding: 16px 20px;
  background: $bg-elevated;
  border: 1px solid $border;
  border-radius: $radius-card;

  .snapshot-cover {
    flex-shrink: 0;
    width: 160px;
    aspect-ratio: 16/9;
    background: $bg-surface;
    border-radius: 8px;
    overflow: hidden;
    position: relative;

    img { width: 100%; height: 100%; object-fit: cover; }

    .cover-placeholder {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      color: $text-muted;
    }
  }

  .snapshot-body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .snapshot-title {
    font-size: 15px;
    font-weight: 600;
    color: $text-primary;
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .snapshot-desc {
    font-size: 13px;
    color: $text-secondary;
    margin: 0;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .snapshot-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .snapshot-meta {
    display: flex;
    gap: 8px;
    font-size: 12px;
    color: $text-secondary;

    .meta-label {
      color: $text-muted;
    }
  }

  &.failed {
    display: flex;
    align-items: center;
    gap: 16px;
    background: rgba(245, 108, 108, 0.05);
    border-color: rgba(245, 108, 108, 0.3);

    .failed-icon { color: #f56c6c; flex-shrink: 0; }
    .failed-text h3 { color: #f56c6c; font-size: 16px; margin: 0 0 4px; }
    .failed-text p { color: $text-secondary; font-size: 13px; margin: 0; }
  }
}

// 3. 数据统计
.data-stats {
  background: $bg-elevated;
  border: 1px solid $border;
  border-radius: $radius-card;
  padding: 16px 20px;

  .section-title {
    font-size: 14px;
    font-weight: 600;
    color: $text-primary;
    margin: 0 0 12px;
  }
}

// 4. 批次元信息
.batch-meta {
  background: $bg-elevated;
  border: 1px solid $border;
  border-radius: $radius-card;
  padding: 0 20px;

  .meta-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 12px 24px;
  }

  .meta-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px 0;
  }

  .meta-label {
    font-size: 12px;
    color: $text-muted;
  }

  .meta-value {
    font-size: 13px;
    color: $text-secondary;
    display: flex;
    align-items: center;
    gap: 8px;

    code {
      font-family: monospace;
      font-size: 12px;
      background: rgba(255, 255, 255, 0.05);
      padding: 1px 6px;
      border-radius: 4px;
    }
  }
}
</style>
```

- [ ] **Step 3: 添加路由**

编辑 `frontend/src/router/index.js`，在 routes 数组里加一条（紧跟 `/publish-history` 之后）：

```js
{ path: '/publish-history/:batchId', name: 'PublishHistoryDetail', component: () => import('../views/PublishHistoryDetail.vue') },
```

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/PublishHistoryDetail.vue frontend/src/router/index.js
git commit -m "feat(history): 新增详情页 PublishHistoryDetail + 路由 /publish-history/:batchId"
```

---

## Phase 6 — 列表卡片网格重构

### Task 8: PublishHistory.vue 改卡片网格 + 删展开视图

**Files:**
- Modify: `frontend/src/views/PublishHistory.vue` (template、script、style 三段都改)

- [ ] **Step 1: 加载 UI 技能**

```text
/ui-ux-pro-max-skill
让 skill 给出"批次卡片网格（4 列自适应、含封面+标题+渠道徽章+时间+状态+4 指标）"的视觉建议。
```

- [ ] **Step 2: 重写 template**

把 `<div class="cards-list" v-loading="loading">` 整段（含 `.batch-card` / `.card-main` / `.card-details` / `.detail-card` / `.card-cover` / `.card-body` 全部）替换为：

```vue
<!-- 卡片网格 -->
<div class="cards-grid" v-loading="loading">
  <div v-if="!loading && batches.length === 0" class="empty-state">
    <el-icon class="empty-icon"><Clock /></el-icon>
    <p>暂无发布记录</p>
  </div>
  <div
    v-for="batch in batches"
    :key="batch.id"
    class="batch-card"
    @click="goDetail(batch.id)"
  >
    <div class="card-cover">
      <img v-if="batch.cover_url" :src="batch.cover_url" :alt="batch.title" />
      <div v-else class="cover-placeholder">
        <el-icon :size="32"><Picture /></el-icon>
      </div>
    </div>
    <div class="card-body">
      <h3 class="card-title">{{ batch.title || '无标题' }}</h3>
      <ChannelSummary
        :channels="computeChannelsSummary(batch.items)"
        :overflow-key="batch.id"
      />
      <div class="card-meta">
        <span class="meta-time">{{ formatCardTime(batch.created_at) }}</span>
        <span class="status-tag" :class="`status-${batch.status}`">{{ statusLabel(batch.status) }}</span>
      </div>
      <div class="card-stats">
        <PublishStats />
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: 重写 script setup**

把现有 script setup 中 `toggleExpand`、`expandedBatchId`、所有 `getCoverUrl` / `getCfgField` 相关 helper（保留 `statusLabel` / `formatRelativeTime`），改为：

```js
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Clock, Picture } from '@element-plus/icons-vue'
import { historyApi, statsApi } from '@/api/v2'
import { platformList, getPlatformByKey } from '@/config/platforms'
import ChannelSummary from '@/components/ChannelSummary.vue'
import PublishStats from '@/components/PublishStats.vue'

const router = useRouter()
const batches = ref([])
const stats = ref({ total: 0, successRate: 0, monthlyTotal: 0 })
const loading = ref(false)

// Filters
const timeRange = ref('all')
const typeFilter = ref('all')
const platformFilter = ref('all')
const statusFilter = ref('all')
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

function computeChannelsSummary(items) {
  const groups = {}
  for (const it of items || []) {
    const key = it.platform
    if (!groups[key]) {
      const cfg = getPlatformByKey(
        platformList.find(p => p.name === key)?.key
      )
      groups[key] = { platform: key, name: it.platform, count: 0, logo: cfg?.logo || null }
    }
    groups[key].count++
  }
  return Object.values(groups)
}

function statusLabel(status) {
  return ({
    pending: '等待中',
    running: '发布中',
    success: '全部成功',
    partial: '部分失败',
    failed: '全部失败',
    cancelled: '已取消',
  }[status] || status)
}

function formatCardTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = (now - d) / 1000
  if (diff < 86400) {
    if (diff < 60) return '刚刚'
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
    return `${Math.floor(diff / 3600)} 小时前`
  }
  const pad = n => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function fetchHistory() {
  loading.value = true
  try {
    const params = { page: currentPage.value, pageSize: pageSize.value }
    if (timeRange.value !== 'all') params.timeRange = timeRange.value
    if (typeFilter.value !== 'all') params.type = typeFilter.value
    if (platformFilter.value !== 'all') params.platform = platformFilter.value
    if (statusFilter.value !== 'all') params.status = statusFilter.value
    const res = await historyApi.getHistory(params)
    if (res.code === 200) {
      batches.value = res.data?.items || []
      total.value = res.data?.total || 0
    }
  } catch (e) {
    console.error('Failed to fetch history:', e)
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const res = await statsApi.getStats()
    if (res.code === 200 && res.data) {
      const d = res.data
      stats.value = {
        total: d.total ?? d.tasks?.total ?? 0,
        successRate: d.successRate ?? d.tasks?.successRate ?? 0,
        monthlyTotal: d.monthlyTotal ?? 0,
      }
    }
  } catch (e) {
    console.error('Failed to fetch stats:', e)
  }
}

const handlePageChange = (page) => { currentPage.value = page; fetchHistory() }
const handleSizeChange = (size) => { pageSize.value = size; currentPage.value = 1; fetchHistory() }
const handleFilterChange = () => { currentPage.value = 1; fetchHistory() }

function goDetail(batchId) {
  router.push(`/publish-history/${batchId}`)
}

onMounted(() => { fetchHistory(); fetchStats() })
```

- [ ] **Step 4: 重写 style 段（替换 cards-list 之后所有 .batch-card / .card-* / .card-details / .detail-*）**

找到 `.cards-list` 那段 CSS，把 `display: flex; flex-direction: column; gap: 12px;` 替换为：

```scss
.cards-grid {
  margin-top: 24px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.batch-card {
  border: 1px solid $border;
  border-radius: $radius-card;
  background: $bg-elevated;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;

  &:hover {
    border-color: rgba($brand-start, 0.5);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
    transform: translateY(-1px);
  }
}

.card-cover {
  width: 100%;
  aspect-ratio: 16/9;
  background: $bg-surface;
  overflow: hidden;
  position: relative;
  flex-shrink: 0;

  img { width: 100%; height: 100%; object-fit: cover; }

  .cover-placeholder {
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    color: $text-muted;
  }
}

.card-body {
  padding: 12px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: $text-primary;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: $text-muted;
  flex-wrap: wrap;
}

.meta-time {
  font-variant-numeric: tabular-nums;
}

.status-tag {
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;

  &.status-success, &.status-partial {
    background: rgba(82, 196, 26, 0.15); color: #67c23a;
  }
  &.status-failed {
    background: rgba(245, 108, 108, 0.15); color: #f56c6c;
  }
  &.status-running {
    background: rgba(64, 158, 255, 0.15); color: #409eff;
  }
  &.status-pending, &.status-cancelled {
    background: rgba(0, 0, 0, 0.06); color: $text-muted;
  }
}

.card-stats {
  margin-top: 4px;
}
```

**删除：** `.card-main`、`.card-cover` 的旧定义（在 batch-card 块内，已被新定义覆盖）、`.card-details`、`.detail-card`、`.detail-cover`、`.detail-body`、`.detail-head`、`.detail-platform`、`.detail-title`、`.detail-desc`、`.detail-tags`、`.detail-foot`、`.detail-error` 等所有 `.card-details` 和 `.detail-*` 相关的 CSS。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/PublishHistory.vue
git commit -m "refactor(PublishHistory): 列表改 4 列自适应卡片网格，删展开视图

单卡：封面 / 标题 / 渠道徽章 / 时间+状态 / 4 指标占位。整卡可点进详情。"
```

---

## Phase 7 — 端到端验证

### Task 9: 手工 e2e 验证（5 个场景）

**Files:** 无（仅执行 + 视觉确认）

- [ ] **Step 1: 启动 dev 环境**

```bash
# 终端 1
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend
python3 app.py

# 终端 2
cd /home/czy/workspace/ai/social-auto-upload-web-ui/frontend
npm run dev
```

- [ ] **Step 2: 场景 1 — 列表网格**

打开 `http://localhost:5173/#/publish-history`：
- 卡片为 4 列网格（窗口 ≥ 1200px），缩窄浏览器到 800px 应为 2 列，500px 应为 1 列
- 每张卡有：封面 / 标题 / 渠道徽章 / 时间 / 状态 / 4 个 `--` 指标
- 整张卡可点；hover 边框高亮

任何一项异常 → 修复 PublishHistory.vue。

- [ ] **Step 3: 场景 2 — 详情页账号切换**

发布一次含 ≥2 账号的批次（手动触发）：
- 点击列表卡进入详情
- 左侧 AccountSidebar readonly 模式：footer / `×` / override 角标**不**出现，所有平台分组默认展开
- 默认选中第一个有效账号；点其他账号切换右侧主区内容
- 失败账号：内容快照降级为红色失败卡，无封面/无内容字段

- [ ] **Step 4: 场景 3 — 直接 URL 访问**

浏览器地址栏改为 `http://localhost:5173/#/publish-history/<刚才发布的 batch id>`，回车：
- 详情页正确加载，账号栏、主区 4 区块齐全
- F5 刷新：依然正常

- [ ] **Step 5: 场景 4 — 404**

把 URL 末尾改成 `does-not-exist`，回车：
- toast 提示"记录不存在或已被删除"，跳回列表

- [ ] **Step 6: 场景 5 — PublishCenter 回归**

打开 `http://localhost:5173/#/publish-center`：
- 左侧 AccountSidebar 行为完全与之前一致（footer / `×` / override 角标正常）
- 选中账号、展开/收起、添加账号按钮都可正常工作

任何一项异常 → 修复相应组件后重新走 5 个场景。

- [ ] **Step 7: 提交验证报告（如有 bug 修复需要新 commit）**

如果以上 5 个场景全部通过，无需 commit。如果中间修复了 bug：

```bash
git add -A
git commit -m "fix(history): e2e 走查发现的问题修复

[列出具体修复点]"
```

---

## Phase 8 — 文档收尾

### Task 10: 更新更新日志（如有 changelog 维护）

**Files:** 修改 `frontend/src/views/Changelog.vue` 或项目维护的 changelog 文件（按需）

- [ ] **Step 1: 检查 changelog 维护位置**

```bash
ls /home/czy/workspace/ai/social-auto-upload-web-ui/frontend/src/views/Changelog.vue
cat /home/czy/workspace/ai/social-auto-upload-web-ui/frontend/src/views/Changelog.vue | head -50
```

如果是按日期分组 + 条目列表的格式，加一条新条目：

```markdown
### 2026-06-10
- 发布历史：列表改 4 列卡片网格，新增详情页（含账号切换、数据统计占位）
- 发布历史：详情页复用 AccountSidebar readonly 模式
```

- [ ] **Step 2: 提交（如有变更）**

```bash
git add frontend/src/views/Changelog.vue
git commit -m "docs(changelog): 发布历史详情页 + 列表卡片网格"
```

---

## 验收清单

- [ ] 9 个 commit 全部通过
- [ ] `pytest backend/tests/` 全部通过（含 5 个新增测试）
- [ ] 5 个手工 e2e 场景全部通过
- [ ] `git log --oneline | head -10` 显示本计划 9 个 commit

## 风险与回退

- **AccountSidebar 重构影响 PublishCenter** → Task 6 Step 2 强制手动回归，任一异常立即修复
- **卡片网格 CSS 错位** → 用 `auto-fill, minmax(280px, 1fr)` 自然断点，无 media query，测试各种窗口宽度
- **详情页直接刷新时 accountStore 还没好** → onMounted 串行：先 setAccounts 再 fetchDetail

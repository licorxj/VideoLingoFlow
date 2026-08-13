# 发布历史重设计 + 一键填写封面修复 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将发布历史从 4 张旧表合并为 `publish_batches`（主表） + `publish_details`（明细表），重写发布历史页为卡片式 UI，并修复一键填写对话框的封面 bug。

**Architecture:** 主-子表模式统一视频/图文发布记录。前端在 `publishAll()` 入口生成 UUID 作为 `publish_batches.id`，循环 N 个账号每次调一次后端（视频用 `/postVideo`、图文用 `/api/image-publish/publish`），每次调用插 1 行 `publish_details`（共享同一 `batch_id`）。`GET /api/v2/history` 走 `publish_batches` GROUP BY 主查询 + 一次明细子查询，返回卡片 + 嵌套明细结构。发布历史页（`PublishHistory.vue`）完全重写为卡片列表，点击展开内联明细。

**Tech Stack:** Python 3.14 + Flask + sqlite3（后端）；Vue 3 + Vite + Element Plus（前端）；pytest（后端单测）；TDD 流程；frequent commits。

**Spec 引用：** `docs/superpowers/specs/2026-06-08-publish-history-redesign-design.md`

---

## 全局前置

**严格范围**（来自 spec §1.3）：本计划只动以下文件，其他一律不动。

**涉及文件清单**：
- 后端：`backend/init_db.py`、`backend/app.py`、`backend/blueprints/image_publish_bp.py`、`backend/blueprints/materials_bp.py`、`backend/ext_api/__init__.py`、`backend/ext_api/task_queue.py`、`backend/tests/test_publish_templates.py`、`backend/tests/test_record_publish_account_configs.py`
- 前端：`frontend/src/views/PublishHistory.vue`、`frontend/src/components/OneClickFillDialog.vue`、`frontend/src/views/PublishCenter.vue`、`frontend/src/views/ImagePublish.vue`、`frontend/src/views/TaskCenter.vue`、`frontend/src/api/v2.js`

**不动文件**（明确划线）：
- `backend/impl/*`（所有平台实现）
- `backend/_browser.py`、`_utils.py`、`conf.py`、`storage.py`、`registry.py`
- 草稿相关代码
- 其他 Vue 组件

---

## Phase 1：Schema 迁移

### Task 1：替换 schema（删 4 旧 + 加 2 新）

**Files:**
- Modify: `backend/init_db.py:44-172`（删 4 张旧表 CREATE + 加 2 张新表 CREATE）
- Modify: `backend/init_db.py:179-210`（删对应 `migrate_database()` 块里的 publish_tasks 相关迁移）

- [ ] **Step 1: 删除 4 张旧表的 CREATE TABLE 块**

在 `backend/init_db.py` 里删除以下 4 个 `cursor.execute("""CREATE TABLE IF NOT EXISTS ...""")` 块（按行号）：

- 第 45-63 行：`publish_tasks`
- 第 65-75 行：`publish_logs`
- 第 102-114 行：`image_publish_tasks`
- 第 116-130 行：`image_publish_logs`

- [ ] **Step 2: 添加 `publish_batches` CREATE TABLE 块**

在 `image_records` 块（145-154 行）之后、`materials` 块（157-172 行）之前，插入：

```python
    # 阶段二：发布主记录表（每次"发布"=1 行）
    cursor.execute("""
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
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_publish_batches_created ON publish_batches(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_publish_batches_status ON publish_batches(status)")

    # 阶段二：发布明细表（每个账号 1 行）
    cursor.execute("""
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
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_publish_details_batch ON publish_details(batch_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_publish_details_status ON publish_details(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_publish_details_platform ON publish_details(platform)")
```

- [ ] **Step 3: 删除 `migrate_database()` 里 publish_tasks 相关的迁移块**

在 `backend/init_db.py:179-210` 的 `migrate_database()` 函数里，删除以下 try/except 块（184-189 行的 avatar 块保留）：
- 第 191-196 行：`publish_tasks 添加 thumbnail_path 列` 块
- 第 198-203 行：`publish_tasks 添加 account_configs 列` 块

- [ ] **Step 4: 验证 schema 语法**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -c "import ast; ast.parse(open('init_db.py', encoding='utf-8').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: 验证 init_db 运行（用临时 db）**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -c "
import os, sys, tempfile
sys.path.insert(0, '.')
os.environ['SAU_DATA_DIR'] = tempfile.mkdtemp()
from init_db import init_database
init_database()
import sqlite3
conn = sqlite3.connect(os.path.join(os.environ['SAU_DATA_DIR'], 'db/database.db'))
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\").fetchall()]
print('Tables:', tables)
assert 'publish_batches' in tables
assert 'publish_details' in tables
assert 'publish_tasks' not in tables
assert 'publish_logs' not in tables
assert 'image_publish_tasks' not in tables
assert 'image_publish_logs' not in tables
print('OK')
"
```

Expected: `Tables: [...]` 含 `publish_batches`、`publish_details`，不含其他 4 张旧表

- [ ] **Step 6: 提交**

```bash
git add backend/init_db.py
git commit -m "refactor(db): 合并发布历史为 publish_batches + publish_details 两表

删除 publish_tasks / publish_logs / image_publish_tasks / image_publish_logs。
新增 publish_batches (主表) + publish_details (明细表 FK→主表)。
不做数据迁移（功能尚未正式使用）。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Phase 2：后端读取端点

### Task 2：新增 `GET /api/materials/{id}`（一键填写封面修复基础）

**Files:**
- Modify: `backend/blueprints/materials_bp.py:253-269`（在 DELETE 端点之前新增 GET 端点）

- [ ] **Step 1: 在 materials_bp.py 写新端点（先复制 storage 模式）**

读 `backend/blueprints/materials_bp.py:180-237`（`list_files`），看它怎么用 `get_storage_by_type` 和 `item_storage.get_url`。

- [ ] **Step 2: 在 DELETE 端点（line 253）之前插入新 GET 端点**

```python
@materials_bp.route("/<material_id>", methods=["GET"])
def get_material(material_id: str):
    from storage import get_storage_by_type
    conn = _get_db()
    row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"code": 404, "msg": "素材不存在"}), 404
    item = dict(row)
    storage = get_storage_by_type(item.get("storage_type", "local"))
    item["url"] = storage.get_url(item["stored_path"])
    item["thumbnail_url"] = (
        storage.get_url(item["thumbnail_path"]) if item.get("thumbnail_path") else None
    )
    return jsonify({"code": 200, "data": item})
```

- [ ] **Step 3: 语法检查**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -c "import ast; ast.parse(open('blueprints/materials_bp.py', encoding='utf-8').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 启服务，手动测一下端点**

先重启后端（如果没运行则启动）：
```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 app.py &
sleep 3
```

测一个不存在的 id：
```bash
curl -s http://localhost:5409/api/materials/不存在id | python3 -m json.tool
```

Expected: `{"code": 404, "msg": "素材不存在"}`

测一个真实 id（从素材库选一个）：
```bash
curl -s http://localhost:5409/api/materials/$(sqlite3 /home/czy/workspace/ai/social-auto-upload-web-ui/data/db/database.db "SELECT id FROM materials LIMIT 1") | python3 -m json.tool
```

Expected: `{"code": 200, "data": {..., "url": "...", "thumbnail_url": ...}}`

- [ ] **Step 5: 停止后端**

```bash
lsof -i :5409 | grep -v "^COMMAND" | awk '{print $2}' | xargs -r kill -9
```

- [ ] **Step 6: 提交**

```bash
git add backend/blueprints/materials_bp.py
git commit -m "feat(materials): 新增 GET /api/materials/{id} 端点

供一键填写对话框封面修复用。返回素材的 url + thumbnail_url。
其他逻辑不动。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3：TDD 实现 `GET /api/v2/history`（读新表）

**Files:**
- Create: `backend/tests/test_history_endpoint.py`
- Modify: `backend/ext_api/__init__.py:259-328`（重写 `get_history` 端点）

- [ ] **Step 1: 先写失败测试**

创建 `backend/tests/test_history_endpoint.py`：

```python
"""
测试 GET /api/v2/history 读 publish_batches + publish_details 的行为。
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

# 把 backend 目录加进 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# 用临时数据目录跑测试
_tmpdir = tempfile.mkdtemp()
os.environ['SAU_DATA_DIR'] = _tmpdir
DB_PATH = Path(_tmpdir) / "db" / "database.db"


def _setup_db():
    """初始化临时 DB 并塞 2 个 batch（一个 3 账号全部成功，一个 2 账号 1 失败）"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 引用 ext_api 的 _db_conn 会自动调 _ensure_tables，但 publish_batches/publish_details
    # 是 init_db.py 里的，需要先跑 init
    from init_db import init_database
    init_database()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("INSERT INTO publish_batches (id, type, title, status, account_count, success_count, failed_count, created_at) VALUES ('b1', 'video', '测试视频1', 'success', 3, 3, 0, '2026-06-01 10:00:00')")
    conn.execute("INSERT INTO publish_batches (id, type, title, status, account_count, success_count, failed_count, created_at) VALUES ('b2', 'image', '测试图文1', 'partial', 2, 1, 1, '2026-06-02 10:00:00')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('d1', 'b1', '账号A', '抖音', '{\"title\":\"测试视频1\"}', 'success')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('d2', 'b1', '账号B', '小红书', '{\"title\":\"测试视频1\"}', 'success')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('d3', 'b1', '账号C', 'B站', '{\"title\":\"测试视频1\"}', 'success')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('d4', 'b2', '账号D', '抖音', '{}', 'success')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('d5', 'b2', '账号E', '小红书', '{}', 'failed')")
    conn.commit()
    conn.close()


class TestHistoryEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_db()
        from ext_api import app
        cls.client = app.test_client()

    def test_returns_batches_with_items(self):
        """应返回 batch 列表，每个含 items 明细子数组"""
        resp = self.client.get('/api/v2/history')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['code'], 200)
        self.assertIn('items', data['data'])
        items = data['data']['items']
        self.assertEqual(len(items), 2)
        # 最新的 b2 排第一
        self.assertEqual(items[0]['id'], 'b2')
        self.assertEqual(items[0]['type'], 'image')
        self.assertEqual(len(items[0]['items']), 2)

    def test_filter_by_type(self):
        """type=video 只返回视频 batch"""
        resp = self.client.get('/api/v2/history?type=video')
        data = resp.get_json()
        items = data['data']['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['type'], 'video')
        self.assertEqual(len(items[0]['items']), 3)

    def test_items_have_required_fields(self):
        """items 子项必须有 id/account_name/platform/status"""
        resp = self.client.get('/api/v2/history')
        items = resp.get_json()['data']['items']
        first_item = items[0]['items'][0]
        for field in ('id', 'account_name', 'platform', 'status'):
            self.assertIn(field, first_item)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_history_endpoint.py -v 2>&1 | tail -20
```

Expected: 测试失败，因为 `get_history` 仍读旧表（返回空或错误）

- [ ] **Step 3: 重写 `get_history` 端点**

读 `backend/ext_api/__init__.py:259-328` 当前 `get_history` 实现。整段替换为：

```python
@ext_api.route('/history', methods=['GET'])
def get_history():
    """获取发布历史（按批次分组），支持分页、平台/状态/类型过滤

    Query: type=video|image (可选), page=1, pageSize=20
    """
    type_ = request.args.get('type')
    status = request.args.get('status')
    platform = request.args.get('platform')  # 暂未使用，留扩展
    time_range = request.args.get('timeRange')
    start_date = request.args.get('startDate')
    end_date = request.args.get('endDate')
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('pageSize', 20))
    offset = (page - 1) * page_size

    if time_range and not start_date:
        now = datetime.now()
        if time_range == 'today':
            start_date = now.strftime('%Y-%m-%d')
        elif time_range == '7days':
            start_date = (now - timedelta(days=7)).strftime('%Y-%m-%d')
        elif time_range == '30days':
            start_date = (now - timedelta(days=30)).strftime('%Y-%m-%d')

    conditions = []
    params = []
    if type_ in ('video', 'image'):
        conditions.append("type = ?")
        params.append(type_)
    if status:
        conditions.append("status = ?")
        params.append(status)
    if start_date:
        conditions.append("created_at >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("created_at <= ?")
        params.append(end_date)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    try:
        conn = _db_conn()
        total = conn.execute(f"SELECT COUNT(*) FROM publish_batches {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM publish_batches {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset]
        ).fetchall()
        batches = [dict(r) for r in rows]

        # 拿当前页所有 batch_id 的明细，一次 IN 查询
        if batches:
            batch_ids = [b['id'] for b in batches]
            placeholders = ','.join('?' * len(batch_ids))
            detail_rows = conn.execute(
                f"SELECT * FROM publish_details WHERE batch_id IN ({placeholders}) ORDER BY created_at ASC",
                batch_ids
            ).fetchall()
            details_by_batch: dict[str, list] = {}
            for d in detail_rows:
                dd = dict(d)
                try:
                    dd['account_configs'] = json.loads(dd.get('account_configs', '{}'))
                except json.JSONDecodeError:
                    dd['account_configs'] = {}
                # 计算 duration
                if dd.get('started_at') and dd.get('finished_at'):
                    try:
                        s = datetime.fromisoformat(dd['started_at'])
                        f = datetime.fromisoformat(dd['finished_at'])
                        dd['duration'] = int((f - s).total_seconds())
                    except (ValueError, TypeError):
                        dd['duration'] = None
                else:
                    dd['duration'] = None
                details_by_batch.setdefault(dd['batch_id'], []).append(dd)
        else:
            details_by_batch = {}

        items = []
        for b in batches:
            items.append({
                'id': b['id'],
                'type': b['type'],
                'title': b.get('title', ''),
                'description': b.get('description', ''),
                'landscape_cover_material_id': b.get('landscape_cover_material_id', ''),
                'portrait_cover_material_id': b.get('portrait_cover_material_id', ''),
                'account_count': b.get('account_count', 0),
                'success_count': b.get('success_count', 0),
                'failed_count': b.get('failed_count', 0),
                'status': b.get('status', 'pending'),
                'schedule_time': b.get('schedule_time', ''),
                'created_at': _to_beijing_time(b.get('created_at')),
                'started_at': _to_beijing_time(b.get('started_at')),
                'finished_at': _to_beijing_time(b.get('finished_at')),
                'items': details_by_batch.get(b['id'], []),
            })

        conn.close()
        return jsonify({
            "code": 200,
            "data": {"items": items, "total": total, "page": page, "pageSize": page_size}
        })
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)}), 500
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_history_endpoint.py -v 2>&1 | tail -15
```

Expected: 3 个测试都 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/tests/test_history_endpoint.py backend/ext_api/__init__.py
git commit -m "feat(api): GET /api/v2/history 改读 publish_batches + publish_details

按批次分组返回：每个 item 含 1 个 batch 的汇总信息 + items[] 明细数组。
支持 type/status/timeRange 过滤 + 分页。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4：TDD 实现 `GET /api/v2/publish-templates`（一键填写列表）

**Files:**
- Create: `backend/tests/test_publish_templates_v2.py`（新文件，不动旧的 test_publish_templates.py）
- Modify: `backend/ext_api/__init__.py:775-870`（重写 `get_publish_templates` 端点）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_publish_templates_v2.py`：

```python
"""
测试 GET /api/v2/publish-templates 读新表的行为。
旧的 test_publish_templates.py 仍要更新（Task 5），但本次先新建针对新表语义的测试。
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_tmpdir = tempfile.mkdtemp()
os.environ['SAU_DATA_DIR'] = _tmpdir
DB_PATH = Path(_tmpdir) / "db" / "database.db"


def _setup():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    from init_db import init_database
    init_database()
    conn = sqlite3.connect(str(DB_PATH))
    # 1 个视频 batch：1 个 detail 带 account_configs
    conn.execute("INSERT INTO publish_batches (id, type, title, status, account_count, success_count, created_at) VALUES ('bv1', 'video', '可复用视频', 'success', 1, 1, '2026-06-01')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('dv1', 'bv1', '账号A', '抖音', '{\"title\":\"可复用视频\",\"description\":\"描述\",\"tags\":[\"标签1\"]}', 'success')")
    # 1 个图文 batch
    conn.execute("INSERT INTO publish_batches (id, type, title, status, account_count, success_count, created_at) VALUES ('bi1', 'image', '可复用图文', 'success', 1, 1, '2026-06-02')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('di1', 'bi1', '账号B', '抖音', '{\"title\":\"可复用图文\"}', 'success')")
    # 1 个失败的 batch：不应被返回
    conn.execute("INSERT INTO publish_batches (id, type, title, status, account_count, success_count, created_at) VALUES ('bx1', 'video', '失败视频', 'failed', 1, 0, '2026-06-03')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('dx1', 'bx1', '账号C', '抖音', '{}', 'failed')")
    conn.commit()
    conn.close()


class TestPublishTemplatesV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup()
        from ext_api import app
        cls.client = app.test_client()

    def test_video_type_returns_video_batches(self):
        resp = self.client.get('/api/v2/publish-templates?type=video')
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data['code'], 200)
        items = data['data']['list']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['type'], 'video')
        self.assertEqual(items[0]['title'], '可复用视频')
        # account_configs 取第一个 detail 的
        self.assertEqual(items[0]['account_configs'].get('title'), '可复用视频')
        self.assertEqual(len(items[0]['channels']), 1)
        self.assertEqual(items[0]['channels'][0]['platform'], '抖音')

    def test_image_type_returns_image_batches(self):
        resp = self.client.get('/api/v2/publish-templates?type=image')
        items = resp.get_json()['data']['list']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['type'], 'image')

    def test_failed_batches_excluded(self):
        """status=failed 的 batch 不应在 templates 列表里（因为 EXIST 过滤 + status IN）"""
        resp = self.client.get('/api/v2/publish-templates?type=video')
        items = resp.get_json()['data']['list']
        ids = [i['id'] for i in items]
        self.assertNotIn('bx1', ids)

    def test_missing_type_returns_400(self):
        resp = self.client.get('/api/v2/publish-templates')
        self.assertEqual(resp.status_code, 400)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_publish_templates_v2.py -v 2>&1 | tail -10
```

Expected: 测试失败（端点仍读旧表）

- [ ] **Step 3: 重写 `get_publish_templates` 端点**

读 `backend/ext_api/__init__.py:775-870` 当前实现。整段替换为：

```python
@ext_api.route('/publish-templates', methods=['GET'])
def get_publish_templates():
    """一键填写：从历史成功/部分成功批次里取可复用的 per-channel 配置。

    Query: type=video|image (必填), page=1, page_size=20
    """
    import json as _json
    type_ = request.args.get('type', '').strip()
    if type_ not in ('video', 'image'):
        return jsonify({"code": 400, "msg": "type 必须是 video 或 image"}), 400

    try:
        page = int(request.args.get('page', 1))
        page_size = min(int(request.args.get('page_size', 20)), 100)
    except ValueError:
        return jsonify({"code": 400, "msg": "page / page_size 必须是整数"}), 400

    offset = (page - 1) * page_size
    conn = _db_conn()

    # 主查询：所有有 detail 带 account_configs 的成功/部分成功 batch
    rows = conn.execute(
        """SELECT b.id, b.type, b.title, b.description,
                  b.landscape_cover_material_id, b.portrait_cover_material_id,
                  b.video_material_id, b.image_material_ids,
                  b.created_at
           FROM publish_batches b
           WHERE b.type = ?
             AND b.status IN ('success', 'partial')
             AND EXISTS (SELECT 1 FROM publish_details d
                         WHERE d.batch_id = b.id AND d.account_configs != '{}')
           ORDER BY b.created_at DESC
           LIMIT ? OFFSET ?""",
        (type_, page_size, offset)
    ).fetchall()
    total = conn.execute(
        """SELECT COUNT(*) FROM publish_batches b
           WHERE b.type = ? AND b.status IN ('success', 'partial')
             AND EXISTS (SELECT 1 FROM publish_details d
                         WHERE d.batch_id = b.id AND d.account_configs != '{}')""",
        (type_,)
    ).fetchone()[0]
    conn.close()

    items = []
    for r in rows:
        # 拿第一个 detail 的 account_configs（用作可复用模板）
        # 单次小查询，按 batch_id 升序拿第一条
        dconn = _db_conn()
        first_detail = dconn.execute(
            "SELECT account_configs, platform FROM publish_details WHERE batch_id = ? "
            "AND account_configs != '{}' ORDER BY created_at ASC LIMIT 1",
            (r['id'],)
        ).fetchone()
        # 拿所有 platform 作 channels 列表
        all_platforms = dconn.execute(
            "SELECT DISTINCT platform FROM publish_details WHERE batch_id = ?",
            (r['id'],)
        ).fetchall()
        dconn.close()

        configs = _json.loads((first_detail['account_configs'] if first_detail else None) or '{}')
        channels = [{'platform': p['platform']} for p in all_platforms if p['platform']]

        items.append({
            "id": r['id'],
            "type": r['type'],
            "title": r['title'] or '',
            "description": r['description'] or '',
            "thumbnail_path": r['landscape_cover_material_id'] or r['portrait_cover_material_id'] or '',
            "first_image_id": (r['image_material_ids'] or '[]'),
            "video_material_id": r['video_material_id'] or '',
            "channels": channels,
            "account_configs": configs,
            "created_at": r['created_at'],
        })

    return jsonify({
        "code": 200,
        "data": {
            "list": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    })
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_publish_templates_v2.py -v 2>&1 | tail -10
```

Expected: 4 个测试都 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/tests/test_publish_templates_v2.py backend/ext_api/__init__.py
git commit -m "feat(api): publish-templates 改读 publish_batches

从主表批量拉取，按 batch_id 关联第一条有 account_configs 的 detail。
仅返回 status IN ('success','partial') 的批次。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5：更新已有测试文件（test_publish_templates.py + test_record_publish_account_configs.py）

**Files:**
- Modify: `backend/tests/test_publish_templates.py`
- Modify: `backend/tests/test_record_publish_account_configs.py`

- [ ] **Step 1: 读 `backend/tests/test_publish_templates.py` 全文**

理解它现在怎么 INSERT 旧表、断言什么。

- [ ] **Step 2: 改写 fixture 和断言**

把 INSERT `publish_tasks` 改为 INSERT `publish_batches` + `publish_details`。把断言改用新 schema 的字段。

如果原测试断言 `account_configs` 字段存在，新测试应该断言它在 `publish_details.account_configs`。

如果测试还引用了 `image_publish_tasks` / `image_publish_logs`，改成新表。

- [ ] **Step 3: 跑测试确认通过**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_publish_templates.py tests/test_record_publish_account_configs.py -v 2>&1 | tail -15
```

Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add backend/tests/test_publish_templates.py backend/tests/test_record_publish_account_configs.py
git commit -m "test: 迁移 publish-templates/account-configs 测试到新表

INSERT/断言改用 publish_batches + publish_details schema。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Phase 3：后端写入端点

### Task 6：TDD 重写 `/postVideo` 写入路径

**Files:**
- Modify: `backend/app.py:638-665`（`_record_publish` 和 `_update_publish_result` 函数）
- Modify: `backend/app.py:691-745`（`_before_publish` 和 `_after_publish` 函数）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_postvideo_writes.py`：

```python
"""测试 /postVideo 写入 publish_batches + publish_details"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_tmpdir = tempfile.mkdtemp()
os.environ['SAU_DATA_DIR'] = _tmpdir
DB_PATH = Path(_tmpdir) / "db" / "database.db"


def _setup():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    from init_db import init_database
    init_database()


class TestPostVideoWrites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup()
        # 启动一个最小 Flask app，注册 ext_api
        from ext_api import app as ext_app
        from flask import Flask
        cls.app = Flask(__name__)
        cls.app.register_blueprint(ext_app)
        cls.client = cls.app.test_client()

    def test_post_video_creates_batch_and_detail(self):
        """一次 /postVideo 应插 1 行 publish_batches + 1 行 publish_details"""
        resp = self.client.post('/postVideo', json={
            'type': 3,  # 抖音
            'title': '测试视频',
            'description': '描述',
            'fileList': ['/tmp/fake.mp4'],
            'accountList': ['/tmp/fake_cookie.json'],
            'tags': ['标签1'],
            'batchId': 'batch-uuid-1',
            'videoMaterialId': 'mat-vid-1',
            'landscapeCoverMaterialId': 'mat-cover-l-1',
            'portraitCoverMaterialId': 'mat-cover-p-1',
        })
        # 视频发布可能因为 /tmp/fake.mp4 不存在而失败（500），
        # 但 _before_publish 已经先插了 batch + detail
        # 关键是测试数据写入是否正确，不在意发布结果
        conn = sqlite3.connect(str(DB_PATH))
        batches = conn.execute("SELECT * FROM publish_batches WHERE id = 'batch-uuid-1'").fetchall()
        details = conn.execute("SELECT * FROM publish_details WHERE batch_id = 'batch-uuid-1'").fetchall()
        conn.close()
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0][1], 'video')  # type
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0][1], 'batch-uuid-1')  # batch_id
        self.assertIn('mat-vid-1', details[0][6])  # account_configs 含 videoMaterialId


if __name__ == '__main__':
    unittest.main()
```

注意：测试断言用 `details[0][6]` 是不稳定的。改为：

```python
# 改用列名查找
cols = [d[0] for d in cursor.description]  # 这要改用 Row 对象
```

更稳妥的写法（替换上面整段 `test_post_video_creates_batch_and_detail`）：

```python
    def test_post_video_creates_batch_and_detail(self):
        resp = self.client.post('/postVideo', json={
            'type': 3,
            'title': '测试视频',
            'description': '描述',
            'fileList': ['/tmp/fake.mp4'],
            'accountList': ['/tmp/fake_cookie.json'],
            'tags': ['标签1'],
            'batchId': 'batch-uuid-1',
            'videoMaterialId': 'mat-vid-1',
            'landscapeCoverMaterialId': 'mat-cover-l-1',
            'portraitCoverMaterialId': 'mat-cover-p-1',
        })
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        batch = conn.execute("SELECT * FROM publish_batches WHERE id = 'batch-uuid-1'").fetchone()
        details = conn.execute("SELECT * FROM publish_details WHERE batch_id = 'batch-uuid-1'").fetchall()
        conn.close()
        self.assertIsNotNone(batch, "publish_batches 行应存在")
        self.assertEqual(batch['type'], 'video')
        self.assertEqual(batch['title'], '测试视频')
        self.assertEqual(batch['video_material_id'], 'mat-vid-1')
        self.assertEqual(len(details), 1)
        d = details[0]
        self.assertEqual(d['batch_id'], 'batch-uuid-1')
        self.assertEqual(d['account_configs'], json.dumps({
            'title': '测试视频', 'description': '描述', 'tags': ['标签1'],
            'videoMaterialId': 'mat-vid-1',
            'landscapeCoverMaterialId': 'mat-cover-l-1',
            'portraitCoverMaterialId': 'mat-cover-p-1',
        }, ensure_ascii=False))
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_postvideo_writes.py -v 2>&1 | tail -10
```

Expected: FAIL（_before_publish 仍写旧表，旧表已 drop，会报错）

- [ ] **Step 3: 重写 `_record_publish` 和 `_update_publish_result` 函数**

读 `backend/app.py:638-665`，整段替换 `_record_publish`：

```python
def _record_publish(batch_id, detail_id, platform, account_name, account_id,
                    video_path, title, description, tags, status, started_at,
                    account_configs, video_material_id='',
                    landscape_cover_material_id='',
                    portrait_cover_material_id=''):
    """插 1 行 publish_batches（如果不存在）+ 1 行 publish_details"""
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            # batch 用 INSERT OR IGNORE，多次同 batchId 调用只插一次
            conn.execute(
                """INSERT OR IGNORE INTO publish_batches
                   (id, type, title, description, video_material_id,
                    landscape_cover_material_id, portrait_cover_material_id,
                    account_count, status, created_at, updated_at)
                   VALUES (?, 'video', ?, ?, ?, ?, ?, 0, 'pending', ?, ?)""",
                (batch_id, title, description, video_material_id,
                 landscape_cover_material_id, portrait_cover_material_id,
                 started_at, started_at)
            )
            conn.execute(
                """INSERT INTO publish_details
                   (id, batch_id, account_id, account_name, platform, account_configs,
                    status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (detail_id, batch_id, account_id, account_name, platform,
                 json.dumps(account_configs, ensure_ascii=False), status, started_at)
            )
    except Exception as e:
        logger.info(f"[History] 记录发布失败: {e}")


def _update_publish_result(detail_id, status, finished_at, error_message=""):
    """更新 1 行 publish_details + 聚合 publish_batches 状态"""
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute(
                "UPDATE publish_details SET status=?, finished_at=?, error_message=? WHERE id=?",
                (status, finished_at, error_message, detail_id)
            )
            # 拿 batch_id
            row = conn.execute(
                "SELECT batch_id FROM publish_details WHERE id=?", (detail_id,)
            ).fetchone()
            if not row:
                return
            batch_id = row[0]
            # 聚合：算 success/failed 数量，更新 batch 状态
            counts = conn.execute(
                """SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_n,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_n
                   FROM publish_details WHERE batch_id=?""",
                (batch_id,)
            ).fetchone()
            total, succ, fail = counts[0], counts[1] or 0, counts[2] or 0
            if total == 0:
                batch_status = 'pending'
            elif fail == 0:
                batch_status = 'success'
            elif succ == 0:
                batch_status = 'failed'
            else:
                batch_status = 'partial'
            conn.execute(
                """UPDATE publish_batches
                   SET status=?, success_count=?, failed_count=?, account_count=?,
                       finished_at=?, updated_at=?
                   WHERE id=?""",
                (batch_status, succ, fail, total, finished_at, finished_at, batch_id)
            )
    except Exception as e:
        logger.info(f"[History] 更新发布结果失败: {e}")
```

注意 `DB_PATH` 在 `app.py` 里有定义（在文件顶部附近），确认下它指向 `_get_db_path()` 而不是新临时目录。如果用了 `DB_PATH = _get_db_path()`，那就对了（它读环境变量 `SAU_DATA_DIR`）。

- [ ] **Step 4: 重写 `_before_publish` 函数**

读 `backend/app.py:691-721` 当前实现。整段替换为：

```python
@app.before_request
def _before_publish():
    if request.path == '/postVideo' and request.method == 'POST':
        data = request.get_json(silent=True)
        if not data:
            return
        now = datetime.now().isoformat()
        batch_id = data.get('batchId') or str(uuid.uuid4())
        detail_id = str(uuid.uuid4())
        platform_type = data.get('type', 0)
        account_list = data.get('accountList', [])
        file_list = data.get('fileList', [])

        account_name = ''
        account_id = data.get('accountId')
        if account_list:
            account_path = account_list[0]
            account_name = data.get('accountName') or Path(account_path).stem or account_path

        # account_configs 存：除了 fileList/accountList/type/thumbnail*/scheduleTime 之外的所有字段
        excluded = {'fileList', 'accountList', 'type', 'thumbnail', 'thumbnailLandscape',
                    'thumbnailPortrait', 'scheduleTime', 'batchId', 'videoMaterialId',
                    'landscapeCoverMaterialId', 'portraitCoverMaterialId',
                    'accountId', 'accountName'}
        account_configs = {k: v for k, v in data.items() if k not in excluded}

        _record_publish(
            batch_id=batch_id,
            detail_id=detail_id,
            platform=PLATFORM_MAP.get(platform_type, '未知'),
            account_id=account_id,
            account_name=account_name,
            video_path=file_list[0] if file_list else '',
            title=data.get('title', ''),
            description=data.get('description', ''),
            tags=data.get('tags', []),
            status='running',
            started_at=now,
            account_configs=account_configs,
            video_material_id=data.get('videoMaterialId', ''),
            landscape_cover_material_id=data.get('landscapeCoverMaterialId', ''),
            portrait_cover_material_id=data.get('portraitCoverMaterialId', ''),
        )
        g.publish_detail_id = detail_id
        g.publish_start_time = now
```

`PLATFORM_MAP` 在 app.py 顶部已定义。如果没定义 `PLATFORM_ID_TO_KEY`，就不需要管它（已被 exclude）。

- [ ] **Step 5: 重写 `_after_publish` 函数**

读 `backend/app.py:724-745` 当前实现。整段替换为：

```python
@app.after_request
def _after_publish(response):
    if request.path == '/postVideo' and hasattr(g, 'publish_detail_id'):
        now = datetime.now().isoformat()
        if response.status_code == 200:
            try:
                resp_data = json.loads(response.get_data(as_text=True))
                if resp_data.get('code') == 200:
                    _update_publish_result(g.publish_detail_id, 'success', now)
                else:
                    _update_publish_result(g.publish_detail_id, 'failed', now, resp_data.get('msg', ''))
            except (json.JSONDecodeError, ValueError):
                _update_publish_result(g.publish_detail_id, 'success', now)
        else:
            error_msg = ''
            try:
                resp_data = json.loads(response.get_data(as_text=True))
                error_msg = resp_data.get('msg', '')
            except (json.JSONDecodeError, ValueError):
                error_msg = f'HTTP {response.status_code}'
            _update_publish_result(g.publish_detail_id, 'failed', now, error_msg)
    return response
```

- [ ] **Step 6: 跑测试确认通过**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_postvideo_writes.py -v 2>&1 | tail -10
```

Expected: PASS

- [ ] **Step 7: 跑全部测试确认没破坏其他东西**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/ -v 2>&1 | tail -25
```

Expected: 全部 PASS（如果旧的 test_publish_templates.py 等还没迁移，可能 FAIL — 这是预期的，留到 Task 5 + 后续任务处理）

- [ ] **Step 8: 提交**

```bash
git add backend/app.py backend/tests/test_postvideo_writes.py
git commit -m "refactor(api): /postVideo 改写 publish_batches + publish_details

_before_publish 插 1 batch + 1 detail；_after_publish 聚合 batch 状态。
接受新参数：batchId, videoMaterialId, landscapeCoverMaterialId, portraitCoverMaterialId。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7：TDD 重写 `/api/image-publish/publish` 写入路径

**Files:**
- Modify: `backend/blueprints/image_publish_bp.py:37-220`（`publish_images` 端点）

- [ ] **Step 1: 读 `backend/blueprints/image_publish_bp.py:37-220` 全文**

理解现有逻辑（插 image_publish_tasks + image_publish_logs + 实际发布）。

- [ ] **Step 2: 写失败测试**

创建 `backend/tests/test_image_publish_endpoint.py`：

```python
"""测试 /api/image-publish/publish 写入新表的行为"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_tmpdir = tempfile.mkdtemp()
os.environ['SAU_DATA_DIR'] = _tmpdir
DB_PATH = Path(_tmpdir) / "db" / "database.db"


def _setup():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    from init_db import init_database
    init_database()


class TestImagePublishEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup()
        from image_publish_bp import app
        cls.app = app
        cls.client = app.test_client()

    def test_creates_batch_and_detail(self):
        """单次 /api/image-publish/publish 应插 1 batch + 1 detail（type='image'）"""
        resp = self.client.post('/api/image-publish/publish', json={
            'image_ids': [],  # 空也行，只要单账号 + batchId 就能写
            'account_configs': [{
                'account_id': 1,
                'platform': 'douyin',
                'filePath': '/tmp/fake_cookie.json',
                'title': '测试图文',
                'description': '描述',
                'tags': ['标签1'],
            }],
            'batchId': 'batch-img-1',
            'landscapeCoverMaterialId': '',
            'portraitCoverMaterialId': 'mat-cover-p-1',
        })
        # 不在意 200 还是 4xx，关键是数据写入
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        batch = conn.execute("SELECT * FROM publish_batches WHERE id = 'batch-img-1'").fetchone()
        details = conn.execute("SELECT * FROM publish_details WHERE batch_id = 'batch-img-1'").fetchall()
        conn.close()
        self.assertIsNotNone(batch)
        self.assertEqual(batch['type'], 'image')
        self.assertEqual(batch['portrait_cover_material_id'], 'mat-cover-p-1')
        self.assertEqual(len(details), 1)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_image_publish_endpoint.py -v 2>&1 | tail -10
```

Expected: FAIL（端点仍写旧表，旧表已 drop）

- [ ] **Step 4: 重写 `publish_images` 端点**

读 `backend/blueprints/image_publish_bp.py:37-220`。整段替换。重点改动：

- 接受单个 `account_configs`（dict）而不是 list
- 接受 `batchId` / `landscapeCoverMaterialId` / `portraitCoverMaterialId`
- 插 1 行 `publish_batches` + 1 行 `publish_details`（type='image'）
- 不再插 `image_publish_tasks` / `image_publish_logs`

骨架（参考 /postVideo 的 `_record_publish`）：

```python
@image_publish_bp.route('/publish', methods=['POST'])
def publish_images():
    data = request.get_json()
    if not data:
        return jsonify({"code": 400, "msg": "请求数据不能为空"}), 400

    image_ids = data.get('image_ids', [])
    config = data.get('account_configs')
    batch_id = data.get('batchId') or str(uuid.uuid4())
    detail_id = str(uuid.uuid4())

    if not config or not isinstance(config, dict):
        return jsonify({"code": 400, "msg": "account_configs 必须是单个账号配置 dict"}), 400
    if not image_ids and not config.get('filePath'):
        return jsonify({"code": 400, "msg": "缺少 image_ids 或 filePath"}), 400

    now = datetime.now().isoformat()
    platform = config.get('platform', '未知')
    account_id = config.get('account_id')
    account_name = config.get('account_name') or Path(config.get('filePath', '')).stem
    title = config.get('title', '')
    description = config.get('description', '')
    tags = config.get('tags', [])

    # account_configs JSON：除了 image_ids / batchId / 封面字段外的所有配置
    excluded = {'image_ids', 'batchId', 'landscapeCoverMaterialId', 'portraitCoverMaterialId'}
    account_configs = {k: v for k, v in config.items() if k not in excluded}

    try:
        conn = _get_db()
        conn.execute(
            """INSERT OR IGNORE INTO publish_batches
               (id, type, title, description, image_material_ids,
                landscape_cover_material_id, portrait_cover_material_id,
                account_count, status, created_at, updated_at)
               VALUES (?, 'image', ?, ?, ?, ?, ?, 0, 'pending', ?, ?)""",
            (batch_id, title, description, json.dumps(image_ids, ensure_ascii=False),
             data.get('landscapeCoverMaterialId', ''),
             data.get('portraitCoverMaterialId', ''),
             now, now)
        )
        conn.execute(
            """INSERT INTO publish_details
               (id, batch_id, account_id, account_name, platform, account_configs,
                status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'running', ?)""",
            (detail_id, batch_id, account_id, account_name, platform,
             json.dumps(account_configs, ensure_ascii=False), now)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        return jsonify({"code": 500, "msg": f"写入失败: {e}"}), 500

    # ... 实际发布逻辑（取图片路径、调 platform.publish_image 等）保留 ...
    # 但发布成功/失败后要更新 publish_details.status + 聚合 batch 状态
    # （具体实现参考原端点 line 90-218，保留实际执行代码）
    # 最后：
    final_status = 'success' if success else 'failed'
    _update_image_publish_detail(detail_id, final_status, error_message=err)
```

新增 helper（在端点外）：

```python
def _update_image_publish_detail(detail_id, status, error_message=""):
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute(
                "UPDATE publish_details SET status=?, finished_at=?, error_message=? WHERE id=?",
                (status, datetime.now().isoformat(), error_message, detail_id)
            )
            row = conn.execute("SELECT batch_id FROM publish_details WHERE id=?", (detail_id,)).fetchone()
            if not row: return
            batch_id = row[0]
            counts = conn.execute(
                """SELECT COUNT(*), SUM(CASE WHEN status='success' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END)
                   FROM publish_details WHERE batch_id=?""",
                (batch_id,)
            ).fetchone()
            total, succ, fail = counts[0], counts[1] or 0, counts[2] or 0
            if total == 0: bs = 'pending'
            elif fail == 0: bs = 'success'
            elif succ == 0: bs = 'failed'
            else: bs = 'partial'
            conn.execute(
                """UPDATE publish_batches
                   SET status=?, success_count=?, failed_count=?, account_count=?,
                       finished_at=?, updated_at=?
                   WHERE id=?""",
                (bs, succ, fail, total, datetime.now().isoformat(),
                 datetime.now().isoformat(), batch_id)
            )
    except Exception as e:
        logger.info(f"[image_publish] 更新失败: {e}")
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_image_publish_endpoint.py -v 2>&1 | tail -10
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/blueprints/image_publish_bp.py backend/tests/test_image_publish_endpoint.py
git commit -m "refactor(api): /api/image-publish/publish 改写新表

单次调用插 1 batch + 1 detail（type='image'）。
前端循环 N 个账号每次调一次，共享 batchId。
删除对 image_publish_tasks / image_publish_logs 的引用。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8：重写 `/api/image-publish/drafts/execute-publish` 端点

**Files:**
- Modify: `backend/blueprints/image_publish_bp.py:470-??`（`execute_publish` 端点）

- [ ] **Step 1: 读 `backend/blueprints/image_publish_bp.py:470` 起的 `execute_publish` 函数**

理解它和 `/publish` 的关系（似乎是从草稿发起的发布）。

- [ ] **Step 2: 同样的改造**

接受单账号 + batchId，插新表。复用 `_update_image_publish_detail` helper。

如果端点调用的是 `/publish`（共享代码），那 Task 7 已经覆盖了。检查一下：
- 如果 `execute-publish` 是独立的实现路径，单独改
- 如果它内部调用 `publish_images`，那 Task 7 已经处理

- [ ] **Step 3: 删除 `/api/image-publish/history` 端点（或重定向）**

读 `backend/blueprints/image_publish_bp.py:406-??` 的 `history` 端点。两种选择：
- 整段删除（前端切到 `/api/v2/history?type=image`）
- 改为重定向：`return redirect('/api/v2/history?type=image', code=301)`

选删除（更干净）。前端 Task 14 改用 `/api/v2/history?type=image`。

- [ ] **Step 4: 跑相关测试**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_image_publish_endpoint.py -v 2>&1 | tail -10
```

Expected: 仍 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/blueprints/image_publish_bp.py
git commit -m "refactor(api): execute-publish 同步新表；删除 /history 端点

历史查询统一走 /api/v2/history?type=image。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9：TDD 重写 `task_queue.py`（PublishTask 数据类 + 写入）

**Files:**
- Modify: `backend/ext_api/task_queue.py:37-321`（PublishTask 数据类 + _insert_db + _update_db）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_task_queue_writes.py`：

```python
"""测试 TaskQueue.add_task 写入新表的行为"""
import os
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_tmpdir = tempfile.mkdtemp()
os.environ['SAU_DATA_DIR'] = _tmpdir
DB_PATH = Path(_tmpdir) / "db" / "database.db"


def _setup():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    from init_db import init_database
    init_database()


class TestTaskQueueWrites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup()
        from task_queue import PublishTask, TaskStatus
        cls.PublishTask = PublishTask
        cls.TaskStatus = TaskStatus

    def test_publish_task_has_batch_id_field(self):
        t = self.PublishTask(batch_id='abc-123')
        self.assertEqual(t.batch_id, 'abc-123')

    def test_to_dict_includes_batch_id(self):
        t = self.PublishTask(batch_id='abc-123', title='t', platform='抖音')
        d = t.to_dict()
        self.assertEqual(d['batch_id'], 'abc-123')

    def test_insert_creates_batch_and_detail(self):
        t = self.PublishTask(
            batch_id='qbatch-1',
            platform='抖音',
            platform_type=3,
            account_name='账号A',
            account_cookie_path='/tmp/cookie.json',
            video_path='/tmp/v.mp4',
            title='t',
            description='d',
            tags=['a', 'b'],
        )
        # 直接调 _insert_db（不走 queue 启动）
        from task_queue import task_queue
        # task_queue 是模块级 singleton，可能已起线程；我们绕开它，只测 _insert_db
        # 改：手动建一个临时 task_queue 实例
        from task_queue import TaskQueue
        tq = TaskQueue(max_concurrent=1)
        tq._insert_db(t)
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        batch = conn.execute("SELECT * FROM publish_batches WHERE id = 'qbatch-1'").fetchone()
        details = conn.execute("SELECT * FROM publish_details WHERE batch_id = 'qbatch-1'").fetchall()
        conn.close()
        self.assertIsNotNone(batch)
        self.assertEqual(batch['type'], 'video')
        self.assertEqual(len(details), 1)
        d = details[0]
        self.assertEqual(d['account_name'], '账号A')
        self.assertEqual(d['platform'], '抖音')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_task_queue_writes.py -v 2>&1 | tail -10
```

Expected: FAIL

- [ ] **Step 3: 在 PublishTask 数据类加 `batch_id` 字段**

读 `backend/ext_api/task_queue.py:37-90`。修改：

```python
@dataclass
class PublishTask:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    batch_id: str = ''                       # 新增
    platform: str = ""
    platform_type: int = 0
    account_name: str = ""
    account_cookie_path: str = ""
    video_path: str = ""
    title: str = ""
    description: str = ""
    thumbnail_path: str = ""
    tags: list = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    error_message: str = ""
    publish_url: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
```

更新 `to_dict` 和 `from_row` 处理 `batch_id`。

- [ ] **Step 4: 重写 `_insert_db`**

读 `backend/ext_api/task_queue.py:283-299`。整段替换：

```python
def _insert_db(self, task: PublishTask):
    """插 1 行 publish_batches（如果不存在）+ 1 行 publish_details"""
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            # batch 插一次，多次同 batch_id 跳过
            conn.execute(
                """INSERT OR IGNORE INTO publish_batches
                   (id, type, title, description, video_material_id,
                    landscape_cover_material_id, portrait_cover_material_id,
                    account_count, status, created_at, updated_at)
                   VALUES (?, 'video', ?, ?, '', '', '', 0, 'pending', ?, ?)""",
                (task.batch_id or task.id, task.title, task.description,
                 task.created_at, task.created_at)
            )
            # account_configs：把 task 字段打包成 JSON
            cfg = {
                'title': task.title,
                'description': task.description,
                'tags': task.tags,
                'thumbnail_path': task.thumbnail_path,
                'platform_type': task.platform_type,
            }
            conn.execute(
                """INSERT INTO publish_details
                   (id, batch_id, account_id, account_name, platform, account_configs,
                    status, created_at)
                   VALUES (?, ?, NULL, ?, ?, ?, ?, ?)""",
                (task.id, task.batch_id or task.id, task.account_name, task.platform,
                 json.dumps(cfg, ensure_ascii=False), task.status, task.created_at)
            )
    except Exception as e:
        logger.info(f"[TaskQueue] 插入数据库失败: {e}")
```

- [ ] **Step 5: 重写 `_update_db`**

读 `backend/ext_api/task_queue.py:301-313`。整段替换：

```python
def _update_db(self, task: PublishTask):
    """更新 1 行 publish_details + 聚合 publish_batches 状态"""
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute(
                """UPDATE publish_details
                   SET status=?, retry_count=?, error_message=?, publish_url=?,
                       started_at=?, finished_at=?
                   WHERE id=?""",
                (task.status, task.retry_count, task.error_message, task.publish_url,
                 task.started_at, task.finished_at, task.id)
            )
            # 聚合
            row = conn.execute(
                "SELECT batch_id FROM publish_details WHERE id=?", (task.id,)
            ).fetchone()
            if not row: return
            batch_id = row[0]
            counts = conn.execute(
                """SELECT COUNT(*),
                          SUM(CASE WHEN status='success' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END)
                   FROM publish_details WHERE batch_id=?""",
                (batch_id,)
            ).fetchone()
            total, succ, fail = counts[0], counts[1] or 0, counts[2] or 0
            if total == 0: bs = 'pending'
            elif fail == 0: bs = 'success'
            elif succ == 0: bs = 'failed'
            else: bs = 'partial'
            now = datetime.now().isoformat()
            conn.execute(
                """UPDATE publish_batches
                   SET status=?, success_count=?, failed_count=?, account_count=?,
                       finished_at=?, updated_at=?
                   WHERE id=?""",
                (bs, succ, fail, total, task.finished_at or now, now, batch_id)
            )
    except Exception as e:
        logger.info(f"[TaskQueue] 更新数据库失败: {e}")
```

- [ ] **Step 6: 跑测试确认通过**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_task_queue_writes.py -v 2>&1 | tail -10
```

Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add backend/ext_api/task_queue.py backend/tests/test_task_queue_writes.py
git commit -m "refactor(task-queue): PublishTask + _insert_db/_update_db 改写新表

加 batch_id 字段；_insert_db 插 1 batch + 1 detail；_update_db 聚合状态。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 10：TDD 重写 `/api/v2/tasks` 读取端点

**Files:**
- Modify: `backend/ext_api/__init__.py:84-170`（`get_tasks`、`get_task`、`create_task` 端点）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_tasks_endpoint.py`：

```python
"""测试 /api/v2/tasks 读新表的行为（TaskCenter 用）"""
import os
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_tmpdir = tempfile.mkdtemp()
os.environ['SAU_DATA_DIR'] = _tmpdir
DB_PATH = Path(_tmpdir) / "db" / "database.db"


def _setup():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    from init_db import init_database
    init_database()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("INSERT INTO publish_batches (id, type, title, status, account_count, created_at) VALUES ('tb1', 'video', 'batch', 'running', 2, '2026-06-01')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('td1', 'tb1', '账号A', '抖音', '{}', 'running')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('td2', 'tb1', '账号B', '小红书', '{}', 'pending')")
    conn.execute("INSERT INTO publish_batches (id, type, title, status, account_count, created_at) VALUES ('tb2', 'video', 'batch2', 'success', 1, '2026-06-02')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('td3', 'tb2', '账号C', '抖音', '{}', 'success')")
    conn.commit()
    conn.close()


class TestTasksEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup()
        from ext_api import app
        cls.client = app.test_client()

    def test_get_tasks_returns_details_with_batch_id(self):
        """返回的每条 task 必须是 publish_details 行（含 batch_id 字段）"""
        resp = self.client.get('/api/v2/tasks')
        data = resp.get_json()
        items = data['data']['list']
        self.assertGreaterEqual(len(items), 3)
        for it in items:
            self.assertIn('batch_id', it)
            self.assertIn('account_name', it)
            self.assertIn('platform', it)
            self.assertIn('status', it)

    def test_get_tasks_filter_by_status(self):
        resp = self.client.get('/api/v2/tasks?status=running')
        items = resp.get_json()['data']['list']
        for it in items:
            self.assertEqual(it['status'], 'running')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_tasks_endpoint.py -v 2>&1 | tail -10
```

Expected: FAIL

- [ ] **Step 3: 重写 `get_tasks` 和 `get_task` 端点**

读 `backend/ext_api/__init__.py:84-170` 当前实现。把 `get_tasks` 改为读 `publish_details`（带 batch_id 关联）：

```python
@ext_api.route('/tasks', methods=['GET'])
def get_tasks():
    """获取任务列表（读 publish_details，每行 = 1 个账号 × 1 个平台）"""
    status = request.args.get('status')
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('pageSize', 20))
    offset = (page - 1) * page_size

    try:
        conn = _db_conn()
        where = ""
        params = []
        if status and status != 'all':
            where = "WHERE d.status = ?"
            params.append(status)

        total = conn.execute(
            f"SELECT COUNT(*) FROM publish_details d {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT d.*, b.title AS batch_title, b.type AS batch_type
                FROM publish_details d
                LEFT JOIN publish_batches b ON d.batch_id = b.id
                {where}
                ORDER BY d.created_at DESC LIMIT ? OFFSET ?""",
            params + [page_size, offset]
        ).fetchall()

        tasks = []
        for row in rows:
            d = dict(row)
            try:
                d['account_configs'] = json.loads(d.get('account_configs', '{}'))
            except json.JSONDecodeError:
                d['account_configs'] = {}
            tasks.append(d)

        conn.close()
        return jsonify({"code": 200, "data": {"list": tasks, "total": total, "page": page, "pageSize": page_size}})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)}), 500


@ext_api.route('/tasks/<detail_id>', methods=['GET'])
def get_task(detail_id):
    """获取单个任务（按 publish_details.id 查）"""
    try:
        conn = _db_conn()
        row = conn.execute(
            """SELECT d.*, b.title AS batch_title, b.type AS batch_type
               FROM publish_details d
               LEFT JOIN publish_batches b ON d.batch_id = b.id
               WHERE d.id = ?""",
            (detail_id,)
        ).fetchone()
        conn.close()
        if not row:
            return jsonify({"code": 404, "msg": "任务不存在"}), 404
        d = dict(row)
        try:
            d['account_configs'] = json.loads(d.get('account_configs', '{}'))
        except json.JSONDecodeError:
            d['account_configs'] = {}
        return jsonify({"code": 200, "data": d})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)}), 500
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/test_tasks_endpoint.py -v 2>&1 | tail -10
```

Expected: PASS

- [ ] **Step 5: 跑全部测试**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/ -v 2>&1 | tail -30
```

Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add backend/ext_api/__init__.py backend/tests/test_tasks_endpoint.py
git commit -m "refactor(api): /api/v2/tasks 改读 publish_details（含 batch_id）

TaskCenter 显示的每行任务 = 1 个账号 × 1 个平台。
返回字段含 batch_id 关联到 publish_batches。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Phase 4：前端适配

### Task 11：改 `frontend/src/api/v2.js` — historyApi 响应结构

**Files:**
- Modify: `frontend/src/api/v2.js`

- [ ] **Step 1: 读 `frontend/src/api/v2.js` 全文**

理解 historyApi 当前返回什么结构。

- [ ] **Step 2: 更新 historyApi 文档注释**

```js
// 发布历史
export const historyApi = {
  getHistory(params) {
    // params: { type?: 'video'|'image', status?, timeRange?, startDate?, endDate?, page, pageSize }
    // 返回: data.items = [{id, type, title, ..., items: [{id, account_name, platform, status, ...}]}, ...]
    return http.get('/api/v2/history', params)
  },
}
```

无需改方法本身（响应结构变化由 PublishHistory.vue 处理）。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/v2.js
git commit -m "docs(api): 更新 historyApi 注释，反映新响应结构

items[] 改为 batch 列表，每个含嵌套 items[] 明细。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 12：改 `PublishCenter.vue` 生成 batchId + 传素材 ID

**Files:**
- Modify: `frontend/src/views/PublishCenter.vue:1333-1428`（`publishAll` 函数中 `allTasks.push` 之后的循环）

- [ ] **Step 1: 读 `PublishCenter.vue:1333-1354`（allTasks 构建）和 `PublishCenter.vue:1356-1428`（循环 publish 部分）**

理解现状。

- [ ] **Step 2: 在 `allTasks.push` 之前生成 batchId**

修改 `PublishCenter.vue:1347` 附近：

```js
// 新增
const batchId = (crypto.randomUUID && crypto.randomUUID()) || (Date.now().toString(36) + '-' + Math.random().toString(36).slice(2))
const videoMaterialId = commonConfig.videoLandscape?.id || commonConfig.videoPortrait?.id || ''
const landscapeCoverMaterialId = commonConfig.coverLandscape?.id || ''
const portraitCoverMaterialId = commonConfig.coverPortrait?.id || ''

for (let i = 0; i < allTasks.length; i++) {
  // ...
  const publishData = {
    // ... 原有字段保留 ...
    batchId,                       // 新增
    videoMaterialId,               // 新增
    landscapeCoverMaterialId,      // 新增
    portraitCoverMaterialId,       // 新增
    accountId: account.id,         // 新增（如果有）
  }
  // ...
}
```

- [ ] **Step 3: 跑前端构建确认无错**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/frontend && npm run build 2>&1 | tail -10
```

Expected: 构建成功，0 error

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/PublishCenter.vue
git commit -m "feat(publish): PublishCenter.publishAll 生成 batchId + 传素材 ID

每次一键发布：前端生成 UUID 作为 batchId；视频/横竖版封面素材 ID
随每次 /postVideo 调用发给后端。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 13：改 `ImagePublish.vue` 循环 N 次 + 传 batchId

**Files:**
- Modify: `frontend/src/views/ImagePublish.vue`（找到 publishAll 函数，类似 PublishCenter 改造）

- [ ] **Step 1: 读 `ImagePublish.vue` 全文**

找 publishAll 函数。

- [ ] **Step 2: 改成循环 N 次 + 生成 batchId**

类似 Task 12，区别：
- 每次循环调 `/api/image-publish/publish`，`account_configs` 传单账号 dict
- 共享同一个 batchId
- 传 `landscapeCoverMaterialId` / `portraitCoverMaterialId`

参考 PublishCenter 的 `allTasks.push` + 循环模式。

- [ ] **Step 3: 跑前端构建确认无错**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/frontend && npm run build 2>&1 | tail -10
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/ImagePublish.vue
git commit -m "feat(image-publish): ImagePublish 循环 N 次 + 传 batchId

每次发布：前端循环 N 个账号，每次调一次 /api/image-publish/publish
（单账号 + 共享 batchId）。封面素材 ID 一并传。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 14：修 `OneClickFillDialog.vue` 封面 bug

**Files:**
- Modify: `frontend/src/components/OneClickFillDialog.vue:92-111`

- [ ] **Step 1: 读 `OneClickFillDialog.vue:82-121`（`load` 函数）**

- [ ] **Step 2: 把 `/api/materials/list?id=X` 改为 `/api/materials/X`**

修改 `OneClickFillDialog.vue:92-108`：

```js
} else if (item.type === 'image' && item.first_image_id) {
  try {
    const m = await http.get(`/api/materials/${item.first_image_id}`)
    const mat = m.data
    if (mat) {
      item.coverSrc = mat.stored_path
        ? `${window.location.protocol}//${window.location.hostname}:5409/${mat.stored_path.replace(/^\/+/, '')}`
        : mat.url || ''
    } else {
      item.coverSrc = ''
    }
  } catch (_) {
    item.coverSrc = ''
  }
}
```

- [ ] **Step 3: 跑前端构建确认无错**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/frontend && npm run build 2>&1 | tail -10
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/OneClickFillDialog.vue
git commit -m "fix(frontend): OneClickFillDialog 封面图改用单素材端点

旧逻辑调用 /api/materials/list?id=X，但 list 端点不识别 id 参数，
会静默返回第一页第一条素材。原素材 ID 失效导致封面错乱。
改用新加的 GET /api/materials/{id} 端点。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 15：改 `TaskCenter.vue` 响应结构适配

**Files:**
- Modify: `frontend/src/views/TaskCenter.vue`

- [ ] **Step 1: 读 `TaskCenter.vue:140-240`**

理解现状展示什么字段。

- [ ] **Step 2: 适配新响应**

新响应中 `task.id` 是 `publish_details.id`，有 `batch_id` 字段关联批次。

如果有显示 batch 标题/批次的列（task.batch_title），TaskCenter 可以展示。

如果列名映射用 `row.title`（publish_tasks 字段），新响应里这个字段在 `batch_title` 下了。改映射。

- [ ] **Step 3: 跑前端构建**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/frontend && npm run build 2>&1 | tail -10
```

Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/TaskCenter.vue
git commit -m "refactor(frontend): TaskCenter 适配 publish_details 响应

行项目数据从 publish_details 来，含 batch_id 关联批次。
字段名映射适配。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 16：完全重写 `PublishHistory.vue` 为卡片式 UI

**Files:**
- Modify: `frontend/src/views/PublishHistory.vue`（整段重写）

- [ ] **Step 1: 备份当前实现关键点**

读 `frontend/src/views/PublishHistory.vue:1-260`（全文件前段），记录：
- 当前过滤器（timeRange / platformFilter / statusFilter）
- 当前 fetchHistory + fetchStats 调用模式
- 当前 pagination
- 现有样式 / 主题变量引用（`@use '@/styles/variables.scss' as *;`）

- [ ] **Step 2: 重写 template — 卡片列表 + 展开**

完全替换 template 块（约 line 1-199）。新结构：

```vue
<template>
  <div class="publish-history-page">
    <h1 class="page-title">发布历史</h1>
    <p class="page-subtitle">回顾所有发布记录</p>

    <!-- 3 Stat cards：保留原 stat-purple / stat-blue / stat-cyan 三个区块 -->
    <div class="stat-cards">
      <div class="stat-card stat-purple">
        <div class="stat-top">
          <div class="stat-icon"><el-icon><Upload /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.total }}</div>
            <div class="stat-label">总发布数</div>
          </div>
        </div>
      </div>
      <div class="stat-card stat-blue">
        <div class="stat-top">
          <div class="stat-icon"><el-icon><CircleCheck /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.successRate }}%</div>
            <div class="stat-label">成功率</div>
          </div>
        </div>
      </div>
      <div class="stat-card stat-cyan">
        <div class="stat-top">
          <div class="stat-icon"><el-icon><Calendar /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.monthlyTotal }}</div>
            <div class="stat-label">本月发布</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Filter 工具栏：加 typeFilter -->
    <div class="filter-card">
      <div class="filter-row">
        <div class="filter-controls">
          <el-select v-model="timeRange" placeholder="时间范围" class="filter-select" @change="handleFilterChange">
            <el-option label="今天" value="today" />
            <el-option label="最近7天" value="7days" />
            <el-option label="最近30天" value="30days" />
            <el-option label="全部" value="all" />
          </el-select>
          <el-select v-model="typeFilter" placeholder="类型" class="filter-select" @change="handleFilterChange">
            <el-option label="全部" value="all" />
            <el-option label="视频" value="video" />
            <el-option label="图文" value="image" />
          </el-select>
          <el-select v-model="platformFilter" placeholder="平台" class="filter-select" @change="handleFilterChange">
            <el-option label="全部" value="all" />
            <el-option v-for="p in platformList" :key="p.key" :label="p.name" :value="p.key" />
          </el-select>
          <el-select v-model="statusFilter" placeholder="状态" class="filter-select" @change="handleFilterChange">
            <el-option label="全部" value="all" />
            <el-option label="全部成功" value="success" />
            <el-option label="部分失败" value="partial" />
            <el-option label="全部失败" value="failed" />
          </el-select>
        </div>
        <el-button class="refresh-btn" :icon="Refresh" @click="fetchHistory" :loading="loading">刷新</el-button>
      </div>
    </div>

    <!-- Cards list (替代表格) -->
    <div class="cards-list" v-loading="loading">
      <div v-if="!loading && batches.length === 0" class="empty-state">
        <el-icon class="empty-icon"><Clock /></el-icon>
        <p>暂无发布记录</p>
      </div>
      <div v-for="batch in batches" :key="batch.id" class="batch-card" :class="{ 'is-expanded': expandedBatchId === batch.id }">
        <!-- 卡片主行 -->
        <div class="card-main" @click="toggleExpand(batch.id)">
          <div class="card-cover">
            <img v-if="batch.cover_url" :src="batch.cover_url" :alt="batch.title" />
            <div v-else class="cover-placeholder"><el-icon :size="32"><Picture /></el-icon></div>
          </div>
          <div class="card-body">
            <div class="card-title">{{ batch.title || '无标题' }}</div>
            <div class="card-desc">{{ (batch.description || '').slice(0, 100) }}</div>
            <div class="card-meta">
              <span class="meta-item">{{ batch.account_count }}账号 {{ batch.success_count }}成功 {{ batch.failed_count }}失败</span>
              <span class="status-tag" :class="`status-${batch.status}`">{{ statusLabel(batch.status) }}</span>
              <span class="meta-item">{{ formatRelativeTime(batch.created_at) }}</span>
            </div>
          </div>
        </div>
        <!-- 展开的明细 -->
        <div v-if="expandedBatchId === batch.id" class="card-details">
          <div v-for="d in batch.items" :key="d.id" class="detail-row">
            <span class="detail-status" :class="`status-${d.status}`">{{ d.status === 'success' ? '✓' : d.status === 'failed' ? '✗' : '○' }}</span>
            <span class="detail-name">{{ d.account_name }}</span>
            <span class="detail-platform">· {{ d.platform }}</span>
            <span class="detail-duration" v-if="d.duration">· {{ formatDuration(d.duration) }}</span>
            <a v-if="d.publish_url" :href="d.publish_url" target="_blank" rel="noopener noreferrer" @click.stop>[链接]</a>
            <div v-if="d.status === 'failed' && d.error_message" class="detail-error">错误：{{ d.error_message }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div class="pagination-wrapper" v-if="total > 0">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
        background
      />
    </div>
  </div>
</template>
```

- [ ] **Step 3: 重写 script — 新 state + 新 fetch**

替换 setup 块（约 line 200-300）。新 state：

```js
const batches = ref([])
const expandedBatchId = ref(null)
const typeFilter = ref('all')  // 新增

const fetchHistory = async () => {
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

const toggleExpand = (id) => {
  expandedBatchId.value = expandedBatchId.value === id ? null : id
}

const statusLabel = (status) => ({
  pending: '等待中', running: '发布中', success: '全部成功',
  partial: '部分失败', failed: '全部失败', cancelled: '已取消',
}[status] || status)

const formatRelativeTime = (iso) => { /* 复制 OneClickFillDialog 的版本 */ }
const formatDuration = (s) => s < 60 ? `${s}秒` : `${Math.floor(s/60)}分${s%60}秒`
const resolveCoverUrl = (batch) => {
  const id = batch.landscape_cover_material_id || batch.portrait_cover_material_id
  if (!id) return ''
  return `${window.location.protocol}//${window.location.hostname}:5409/api/materials/file/${id}`
}
```

注意：封面 URL 需要解析 material_id → url。如果 material_id 存的是 path 而非真 ID，需要后端配合。前端先做 fallback：调 `/api/materials/{id}` 拿 url。

更简单的实现：后端 `/api/v2/history` 响应里直接返 cover URL（不返 material_id）。后端解析 material_id → materials.stored_path → 拼 URL。

如果后端还没返这个 URL，前端可以懒加载：用 `v-if` 触发 `fetch('/api/materials/{id}')` 拿 url。

简化起见，前端用 material_id 拼路径：`/api/materials/file/{material_id}`，但这个端点不存在。需要：
- 改后端 `/api/v2/history` 返 cover URL（推荐）
- 或加新端点 `/api/materials/file/{id}`

为了本任务保持前端独立性，**后端补 cover URL 字段**作为补充：修改 Task 3 实现的 `/api/v2/history`，加 `cover_url` 字段（解析 landscape → portrait 顺序）。

回到 Task 3 修改 `get_history` 端点的 items 生成部分，加：

```python
'cover_url': _resolve_cover_url(b.get('landscape_cover_material_id', ''))
                or _resolve_cover_url(b.get('portrait_cover_material_id', '')),
```

helper（在端点外）：

```python
def _resolve_cover_url(material_id: str) -> str:
    if not material_id:
        return ''
    try:
        conn = _db_conn()
        row = conn.execute("SELECT stored_path FROM materials WHERE id = ?", (material_id,)).fetchone()
        conn.close()
        if not row:
            return ''
        return f"/api/materials/file/{row['stored_path']}"
    except Exception:
        return ''
```

然后重跑 Task 3 测试确认仍 PASS。提交作为 Task 3 的 amend 或新 commit。

- [ ] **Step 4: 重写 style — 卡片样式**

在 `<style lang="scss" scoped>` 块加：

```scss
.cards-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.batch-card {
  border: 1px solid $border;
  border-radius: 12px;
  background: $bg-elevated;
  overflow: hidden;
  transition: all 0.2s;
  &:hover { border-color: $brand-start; }
  &.is-expanded { border-color: $brand-start; }
}
.card-main {
  display: flex;
  gap: 16px;
  padding: 16px;
  cursor: pointer;
}
.card-cover {
  flex-shrink: 0;
  width: 160px;
  aspect-ratio: 16/9;
  background: $bg-surface;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  img { width: 100%; height: 100%; object-fit: cover; }
  .cover-placeholder {
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    color: $text-muted;
  }
}
.card-body { flex: 1; min-width: 0; }
.card-title {
  font-size: 16px; font-weight: 600;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.card-desc {
  font-size: 13px; color: $text-secondary; margin: 6px 0 12px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-meta {
  display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
  font-size: 12px; color: $text-muted;
}
.status-tag {
  padding: 2px 8px; border-radius: 4px; font-size: 11px;
  &.status-success, &.status-partial { background: rgba(82,196,26,0.15); color: #67c23a; }
  &.status-failed { background: rgba(245,108,108,0.15); color: #f56c6c; }
  &.status-running { background: rgba(64,158,255,0.15); color: #409eff; }
  &.status-pending { background: rgba(0,0,0,0.06); color: $text-muted; }
}
.card-details {
  border-top: 1px solid $border;
  padding: 12px 16px;
  background: $bg-surface;
}
.detail-row {
  display: flex; gap: 8px; align-items: center;
  padding: 6px 0;
  font-size: 13px;
  flex-wrap: wrap;
  .detail-status { width: 18px; text-align: center; font-weight: 600;
    &.status-success { color: #67c23a; }
    &.status-failed { color: #f56c6c; }
  }
  .detail-error {
    flex-basis: 100%; color: #f56c6c; font-size: 12px;
    margin-left: 26px;
  }
}
```

- [ ] **Step 5: 跑前端构建**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/frontend && npm run build 2>&1 | tail -10
```

Expected: 构建成功

- [ ] **Step 6: 启动 dev server，手动验证**

```bash
# 后端
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 app.py &
sleep 3
# 前端
cd /home/czy/workspace/ai/social-auto-upload-web-ui/frontend && npm run dev
```

浏览器打开 http://localhost:5173/publish-history，确认：
- 卡片显示（如果 DB 里没数据，先用 PublishCenter 跑一次发布）
- 点击卡片展开明细
- 过滤器工作
- 分页器工作

- [ ] **Step 7: 提交**

```bash
git add frontend/src/views/PublishHistory.vue backend/ext_api/__init__.py
git commit -m "feat(frontend): PublishHistory 整页重写为卡片式 UI

收起态：封面 + 标题 + 描述 + 账号汇总 + 状态徽标 + 时间
点击展开：内联明细列表（账号/平台/耗时/状态/错误/publish_url 链接）
后端 /api/v2/history 响应补 cover_url 字段（解析 material_id → URL）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Phase 5：端到端验证

### Task 17：端到端冒烟测试

- [ ] **Step 1: 启服务**

```bash
lsof -i :5409 -i :5173 2>/dev/null | grep LISTEN | awk '{print $2}' | xargs -r kill -9
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 app.py &
sleep 3
cd /home/czy/workspace/ai/social-auto-upload-web-ui/frontend && npm run dev &
sleep 3
```

- [ ] **Step 2: 跑全部后端测试**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python3 -m pytest tests/ -v 2>&1 | tail -40
```

Expected: 全部 PASS

- [ ] **Step 3: 跑前端构建**

```bash
cd /home/czy/workspace/ai/social-auto-upload-web-ui/frontend && npm run build 2>&1 | tail -5
```

Expected: 0 error

- [ ] **Step 4: 手工冒烟（Playwright 或浏览器）**

测试场景：
1. 打开 `/publish-center`，选 2 个账号，点击发布
2. 打开 `/publish-history`，确认看到 1 张卡片（不是 2 张），展开后看到 2 行明细
3. 打开 `/image-publish`，选 2 个图文账号，发布
4. 回到 `/publish-history`，确认视频和图文都显示（按 typeFilter 过滤）
5. 打开视频发布页，点"从历史一键填写"，确认视频封面正常
6. 打开图文发布页，点"一键填写"，确认图文封面**正常显示**（关键 bug fix 验证）
7. 打开 `/task-center`，确认任务列表正常

- [ ] **Step 5: 停止服务并提交（如果改了任何东西）**

```bash
lsof -i :5409 -i :5173 2>/dev/null | grep LISTEN | awk '{print $2}' | xargs -r kill -9
# 如果无改动跳过 commit
```

---

## 实施顺序总结

1. **Task 1** Schema 迁移
2. **Task 2** 新增 `GET /api/materials/{id}`（独立）
3. **Task 3** `GET /api/v2/history` 重写
4. **Task 4** `GET /api/v2/publish-templates` 重写
5. **Task 5** 迁移已有测试
6. **Task 6** `/postVideo` 写路径重写
7. **Task 7** `/api/image-publish/publish` 写路径重写
8. **Task 8** `execute-publish` + 删除 `/history` 端点
9. **Task 9** `task_queue.py` 重写
10. **Task 10** `/api/v2/tasks` 读路径重写
11. **Task 11-16** 前端（顺序：API 注释、PublishCenter、ImagePublish、OneClickFillDialog、TaskCenter、PublishHistory）
12. **Task 17** 端到端验证

**关键依赖**：
- Task 1 必须最先（schema 是所有读写的前提）
- Task 2-5 可以并行（互不依赖，只依赖 Task 1）
- Task 6-10 可以并行（互不依赖，只依赖 Task 1）
- Task 11-16 依赖 Task 3, 4, 10（后端响应结构稳定）
- Task 17 最后

**TDD 顺序**：每个 Task 内的"写测试 → 跑测试（fail） → 改代码 → 跑测试（pass） → commit"五步是 TDD 强制流程。

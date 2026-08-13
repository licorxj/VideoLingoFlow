# 发布历史重设计 + 一键填写封面修复 — 设计 spec

日期：2026-06-08
作者：与用户协作完成
状态：已设计，待用户审阅

## 1. 背景与目标

### 1.1 当前问题

| # | 问题 | 严重性 |
|---|---|---|
| A | 一次点击"发布"对应 N 个账号 → `publish_tasks` 写 N 行，但 N 行之间无关联，发布历史页只能看到 N 个独立条目，无法整体回看 | 高 |
| B | `image_publish_tasks`（批次） + `image_publish_logs`（明细）是主-子结构，与视频的扁平结构不一致，代码两套 | 中 |
| C | 一键填写对话框（图文物料场景）封面显示不出来 | 中 |
| D | `publish_logs` 表在 schema 里被声明，但全代码库无任何引用 | 低（死代码） |

### 1.2 目标

1. 把视频和图文的发布记录统一成"主表 + 明细表"的标准结构
2. 4 张旧表（`publish_tasks`、`publish_logs`、`image_publish_tasks`、`image_publish_logs`）整表删除
3. 发布历史页（`PublishHistory.vue`）完全重写为卡片式 UI
4. 修一键填写对话框的封面 bug

### 1.3 严格范围

> **本设计只动发布历史相关的表与代码逻辑。其他模块（平台实现、登录、素材库等）一律不动。**

## 2. 数据模型

### 2.1 新表：`publish_batches`（发布主记录表）

每次点击"发布"= 1 行。

```sql
CREATE TABLE IF NOT EXISTS publish_batches (
    id TEXT PRIMARY KEY,                          -- UUID，前端生成
    type TEXT NOT NULL,                           -- 'video' | 'image'

    -- 共有字段
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',

    -- 内容字段（按 type 选用）
    video_material_id TEXT DEFAULT '',            -- 视频发布用
    image_material_ids TEXT DEFAULT '[]',         -- 图文发布用 (JSON 列表)

    -- 封面字段（横/竖版，按平台支持选用）
    landscape_cover_material_id TEXT DEFAULT '',  -- 横版封面素材 ID
    portrait_cover_material_id TEXT DEFAULT '',   -- 竖版封面素材 ID

    -- 整体状态
    status TEXT NOT NULL DEFAULT 'pending',       -- pending|running|success|partial|failed|cancelled
    account_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,

    -- 定时
    schedule_time TEXT DEFAULT '',

    -- 时间
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_publish_batches_created
    ON publish_batches(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_publish_batches_status
    ON publish_batches(status);
```

### 2.2 新表：`publish_details`（发布明细表，每个账号 1 行）

每次发布选了几个账号 = 几行。

```sql
CREATE TABLE IF NOT EXISTS publish_details (
    id TEXT PRIMARY KEY,                          -- UUID
    batch_id TEXT NOT NULL,                       -- FK → publish_batches.id

    -- 账号维度
    account_id INTEGER,                           -- 账号表 ID（图文物料场景下需要）
    account_name TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',

    -- 每账号独立的表单数据（JSON）
    -- 视频：{title, description, tags, videoFormat, enableTimer, scheduleTime, aiContent, ...}
    -- 图文：{title, description, tags, imageIds, enableTimer, scheduleTime, ...}
    -- 一键填写直接复用此字段
    account_configs TEXT NOT NULL DEFAULT '{}',

    -- 状态
    status TEXT NOT NULL DEFAULT 'pending',       -- pending|running|success|failed|cancelled
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    error_message TEXT NOT NULL DEFAULT '',

    -- 创作中心作品详情页链接（预留字段，发布成功后回填）
    publish_url TEXT NOT NULL DEFAULT '',

    -- 时间
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,

    FOREIGN KEY (batch_id) REFERENCES publish_batches(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_publish_details_batch
    ON publish_details(batch_id);
CREATE INDEX IF NOT EXISTS idx_publish_details_status
    ON publish_details(status);
CREATE INDEX IF NOT EXISTS idx_publish_details_platform
    ON publish_details(platform);
```

### 2.3 删除的 4 张旧表

```sql
DROP TABLE IF EXISTS publish_tasks;
DROP TABLE IF EXISTS publish_logs;
DROP TABLE IF EXISTS image_publish_tasks;
DROP TABLE IF EXISTS image_publish_logs;
```

**不做数据迁移**。发布历史功能尚未正式投入使用，历史数据直接丢弃。

### 2.4 不动的表

- `materials`（素材库）— 仍被 `publish_batches.{landscape,portrait}_cover_material_id`、`video_material_id`、`image_material_ids` 引用
- `drafts` / `image_drafts`（草稿）— 与发布记录无关
- `user_info`、`settings`、`file_records`、`image_records` — 无关

## 3. 后端改动

### 3.1 涉及文件

| 文件 | 改动 |
|---|---|
| `backend/init_db.py` | 删除 4 张旧表 CREATE；新增 2 张新表 CREATE；删除对应 `migrate_database()` 块 |
| `backend/app.py` | `_before_publish` / `_after_publish` / `_record_publish` / `_update_publish_result` 改写：写新表 |
| `backend/blueprints/image_publish_bp.py` | 全面改写：`/publish` 端点 INSERT 新表；`/history` 端点删掉或重定向到 `/api/v2/history` |
| `backend/ext_api/__init__.py` | `/api/v2/history`、`/api/v2/publish-templates`、`/api/v2/tasks` 改读新表 |
| `backend/ext_api/task_queue.py` | `PublishTask` 数据类加 `batch_id`；`_insert_db` / `_update_db` 改写：写新表（一次插 1 batch + 1 detail）；`_notify_status` 改为监听 publish_details |
| `backend/blueprints/materials_bp.py` | 新增 `GET /api/materials/{id}` 端点（供一键填写封面修复） |
| `backend/tests/test_publish_templates.py` | 测试表名更新 |
| `backend/tests/test_record_publish_account_configs.py` | 测试表名更新 |
| `frontend/src/views/TaskCenter.vue` | 响应结构适配：行项目数据从 `publish_details` 来（带 `batch_id` 关联） |

### 3.2 不动的文件

- 所有 `backend/impl/<platform>/platform.py` — 平台实现不变
- `backend/_browser.py` / `_utils.py` / `conf.py` / `storage.py` / `registry.py` — 公共模块不变
- `backend/blueprints/materials_bp.py` **只新增 `GET /api/materials/{id}` 端点**，其他逻辑不动

### 3.3 `/postVideo` 改造

请求体新增字段：

```json
{
  "type": 3,
  "title": "...",
  "description": "...",
  "tags": [...],
  "fileList": ["..."],
  "videoFormat": "portrait",
  "accountList": ["..."],
  "thumbnailLandscape": "uploads/...",
  "thumbnailPortrait": "uploads/...",
  "enableTimer": 0,
  "scheduleTime": "",
  "batchId": "uuid-...",          // 新增（前端生成）
  "videoMaterialId": "...",      // 新增（前端从素材库选的视频 ID）
  "landscapeCoverMaterialId": "...",   // 新增
  "portraitCoverMaterialId": "...",    // 新增
  // ... 其他平台相关字段保留 ...
}
```

`_before_publish` 流程：

```python
# 1. 取 batchId（前端带过来，没有就生成一个新 UUID —— 给直调 /postVideo 的脚本兜底）
batch_id = data.get('batchId') or str(uuid.uuid4())

# 2. 解析素材 ID → 路径（用 storage.resolve_material_path 或类似）
video_path = _resolve_material_path(file_list[0])
landscape = _resolve_material_path(data.get('thumbnailLandscape', ''))
portrait = _resolve_material_path(data.get('thumbnailPortrait', ''))

# 3. 解析 account_id（从前端带过来，或从 accountList[0] 解析）
account_id = data.get('accountId')  # 前端传
account_name = data.get('accountName') or Path(account_list[0]).stem

# 4. INSERT publish_batches（ON CONFLICT 跳过 — 同一 batchId 的 N 次调用只插一次）
INSERT OR IGNORE INTO publish_batches
  (id, type, title, description, video_material_id,
   landscape_cover_material_id, portrait_cover_material_id,
   account_count, status, created_at, updated_at)
VALUES (?, 'video', ?, ?, ?, ?, ?, ?, 'pending', ?, ?)

# 5. INSERT publish_details（每次调用一行）
detail_id = str(uuid.uuid4())
INSERT INTO publish_details
  (id, batch_id, account_id, account_name, platform, account_configs,
   status, created_at)
VALUES (?, ?, ?, ?, ?, ?, 'running', ?)

# 把 detail_id 存到 g 上，after_request 用
g.publish_detail_id = detail_id
```

`_after_publish` 流程：

```python
if response.status_code == 200 and code == 200:
    UPDATE publish_details SET status='success', finished_at=?, publish_url=? WHERE id=?
else:
    UPDATE publish_details SET status='failed', finished_at=?, error_message=? WHERE id=?

# 然后聚合 batch 状态
UPDATE publish_batches
SET status = (CASE
    WHEN success_count = account_count THEN 'success'
    WHEN success_count = 0 THEN 'failed'
    ELSE 'partial'
  END),
  success_count = (SELECT COUNT(*) FROM publish_details
                   WHERE batch_id = ? AND status='success'),
  failed_count = (SELECT COUNT(*) FROM publish_details
                  WHERE batch_id = ? AND status='failed'),
  finished_at = ?
WHERE id = ?
```

### 3.4 `/api/image-publish/publish` 改造

**改造为循环 N 次调用**（与 `/postVideo` 模式一致）：

- 前端 `ImagePublish.vue` 的 `publishAll` 改为循环 N 个账号、每次调一次
- 后端 `/api/image-publish/publish` 接受单个账号 + `batchId`，INSERT 1 行 `publish_batches` + 1 行 `publish_details`
- 不再插 `image_publish_tasks` / `image_publish_logs`

请求体新增字段：

```json
{
  "image_ids": ["..."],
  "account_configs": { /* 单个账号的配置 */ },
  "batchId": "uuid-...",
  "landscapeCoverMaterialId": "...",
  "portraitCoverMaterialId": "..."
}
```

### 3.5 `GET /api/v2/history` 改造

请求：`?type=video|image&page=1&page_size=20`，`type` 不传时合并视频+图文。

响应：

```json
{
  "code": 200,
  "data": {
    "items": [
      {
        "id": "batch-uuid",
        "type": "video",
        "title": "我的视频",
        "description": "...",
        "cover": "http://host:5409/...",          // 横版封面 URL，缺则用竖版
        "landscape_cover": "...",
        "portrait_cover": "...",
        "account_count": 3,
        "success_count": 2,
        "failed_count": 1,
        "status": "partial",
        "schedule_time": "",
        "created_at": "2026-06-08T12:00:00+08:00",
        "started_at": "...",
        "finished_at": "...",
        "items": [
          {
            "id": "detail-uuid",
            "account_id": 101,
            "account_name": "账号A",
            "platform": "抖音",
            "status": "success",
            "error_message": "",
            "publish_url": "",
            "started_at": "...",
            "finished_at": "...",
            "duration": 130
          }
          // ...
        ]
      }
    ],
    "total": 100,
    "page": 1,
    "page_size": 20
  }
}
```

SQL：

```sql
-- 主查询：分页 + 排序
SELECT b.* FROM publish_batches b
WHERE [b.type = ?]  -- 可选过滤
ORDER BY b.created_at DESC
LIMIT ? OFFSET ?

-- 总数
SELECT COUNT(*) FROM publish_batches [WHERE type = ?]

-- 明细子查询：按 batch_id 拿 N 行 detail
SELECT * FROM publish_details
WHERE batch_id IN (?, ?, ...)  -- 当前页所有 batch_id
ORDER BY created_at ASC
```

### 3.6 `GET /api/v2/publish-templates`（一键填写）

请求：`?type=video|image&page=1&page_size=20`，从 `publish_batches` 读：

```sql
SELECT b.id, b.type, b.title, b.description,
       b.landscape_cover_material_id, b.portrait_cover_material_id,
       b.video_material_id, b.image_material_ids,
       b.created_at
FROM publish_batches b
WHERE b.status IN ('success', 'partial')  -- 至少部分成功
  AND EXISTS (SELECT 1 FROM publish_details d
              WHERE d.batch_id = b.id AND d.account_configs != '{}')
  [AND b.type = ?]
ORDER BY b.created_at DESC
LIMIT ? OFFSET ?
```

每个 `batch` 对应一个"可复用模板"，模板的 `account_configs` 取**第一个 detail** 的（因为一键填写是复制到当前账号的，跟原账号可能不同）。

返回结构：

```json
{
  "code": 200,
  "data": {
    "list": [
      {
        "id": "batch-uuid",
        "type": "video",
        "title": "...",
        "description": "...",
        "thumbnail_path": "横版封面解析后的相对路径",
        "first_image_id": null,
        "channels": [{"platform": "抖音"}, {"platform": "小红书"}],
        "account_configs": { /* 第一个 detail 的 account_configs */ },
        "created_at": "..."
      }
    ],
    "total": 100,
    "page": 1,
    "page_size": 20
  }
}
```

## 4. 前端改动

### 4.1 涉及文件

| 文件 | 改动 |
|---|---|
| `frontend/src/views/PublishHistory.vue` | 完全重写为卡片列表（详见 §5） |
| `frontend/src/components/OneClickFillDialog.vue` | 修封面 bug：把 `/api/materials/list?id=X` 改为 `/api/materials/X`（用现成的 GET 单素材端点） |
| `frontend/src/views/PublishCenter.vue` | `publishAll()` 开头生成 `batchId = crypto.randomUUID()`，每次 `/postVideo` 调用都带上 `batchId` + `videoMaterialId` + `landscapeCoverMaterialId` + `portraitCoverMaterialId` |
| `frontend/src/views/ImagePublish.vue` | `publishAll()` 同样逻辑；改为循环 N 次调 `/api/image-publish/publish`（每次单账号 + 同样的 `batchId`） |
| `frontend/src/api/v2.js` | `historyApi.getHistory` 响应结构适配（items 是 batches，每个含 sub-items） |

### 4.2 不动的文件

- 所有其他 Vue 组件、stores、router、utils
- 平台相关的下拉/表单组件
- 草稿/账号/素材库管理页面

## 5. UI：发布历史卡片式页面

完全重写 `PublishHistory.vue`，原表格 UI 整段替换。

### 5.1 卡片布局（收起态）

```
┌────────────────────────────────────────────────┐
│  ┌──────┐  我的视频标题                          │
│  │      │  描述摘要两行截断…                       │
│  │ 封面 │  3账号 2成功 1失败                       │
│  │      │  ⏱ 部分失败  · 2分钟前  · 总耗时 2分35秒   │
│  └──────┘                                         │
└────────────────────────────────────────────────┘
```

- 封面图：横版封面缩略图（缺则用竖版，再缺则用占位图）
- 标题：单行截断
- 描述：2 行截断
- 账号汇总：`X账号 Y成功 Z失败`（如 `3账号 2成功 1失败`）
- 状态徽标：pending / running / success / partial / failed / cancelled
- 时间：相对时间（"X 分钟前"）
- 总耗时：所有 detail 的 `finished_at - started_at` 之和

### 5.2 卡片布局（展开态）

点击卡片向下展开（不离开列表）：

```
┌────────────────────────────────────────────────┐
│  ┌──────┐  我的视频标题                  [收起▲] │
│  │ 封面 │  ...                                      │
│  └──────┘                                          │
├────────────────────────────────────────────────┤
│  ✓ 账号A · 抖音       · 2分10秒 · 成功  [链接]     │
│  ✓ 账号B · 小红书     · 1分45秒 · 成功  [链接]     │
│  ✗ 账号C · B站        · 0分30秒 · 失败             │
│    错误：登录已过期                                  │
└────────────────────────────────────────────────┘
```

- 账号名 + 平台 + 耗时 + 状态图标
- 失败时显示错误信息
- 成功时有 `publish_url`（预留字段，目前为空）
- 点击其他卡片或页面空白处收起当前展开

### 5.3 过滤与分页

- 顶部：时间范围（今天/7天/30天/全部）、类型（视频/图文/全部）、状态（全部/成功/部分失败/失败）下拉
- 底部：分页器（10/20/50 条/页）
- 默认按 `created_at DESC`

## 6. 一键填写封面修复

**根因**：`OneClickFillDialog.vue:94` 调用 `/api/materials/list?id={first_image_id}` 想按 id 过滤，但 `materials_bp.py:180-237` 的 list 接口只支持 `type`/`keyword`/`page`/`page_size`——`id` 参数被静默忽略，返回的是第一页第一条素材（而不是该 id 对应的素材），所以封面图错乱。

**修复**（两处改动）：

1. **后端**：在 `backend/blueprints/materials_bp.py` 新增 `GET /api/materials/{id}` 端点（约 10 行）：

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

2. **前端**：`OneClickFillDialog.vue` 把 `/api/materials/list?id=X` 改为新端点：

```js
} else if (item.type === 'image' && item.first_image_id) {
  const m = await http.get(`/api/materials/${item.first_image_id}`)
  const mat = m.data
  if (mat) {
    item.coverSrc = mat.stored_path
      ? `${window.location.protocol}//${window.location.hostname}:5409/${mat.stored_path.replace(/^\/+/, '')}`
      : mat.url || ''
  } else {
    item.coverSrc = ''
  }
}
```

**视频场景不受影响**——视频封面的 `buildVideoCoverUrl` 用的是 `thumbnail_path` 字段，无需改。

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 删除旧表后，正在运行的发布任务写入失败 | 实施前停服；改完前后端都重启后再放开 |
| 测试 fixture 引用旧表名 | 同步更新 `test_publish_templates.py`、`test_record_publish_account_configs.py` |
| 现有发布历史页用户收藏的 URL | URL 不变（`/publish-history`），只是内部重写为卡片 |
| 一键填写的 `account_configs` 字段在新表里仍可读 | 保持 JSON 形态不变，前端无需迁移 |
| 新字段 `landscape_cover_material_id` / `portrait_cover_material_id` 没有现成填充路径 | PublishCenter 在 publishAll 阶段把 `commonConfig.coverLandscape?.id` / `coverPortrait?.id` 一并发给后端 |

## 8. 测试计划

- **后端单测**：更新 `test_publish_templates.py`、`test_record_publish_account_configs.py`，覆盖：
  - 视频/图文发布后 `publish_batches` + `publish_details` 写入正确
  - 聚合状态（success/partial/failed）计算正确
  - `GET /api/v2/history` 分组 + 分页正确
  - `GET /api/v2/publish-templates` 返回正确的第一批 detail 的 `account_configs`
- **前端 e2e**（gstack `/qa` + Playwright）：
  - 打开 `/publish-history`，确认卡片渲染
  - 点击卡片，确认展开明细
  - 打开一键填写对话框，确认封面图正常显示（视频封面、图文物料封面各一组）
  - 一次发布 3 账号，确认发布历史只生成 1 张卡片
- **手工冒烟**：
  - 视频 1 文件 + 3 账号 → DB 有 1 batch + 3 detail
  - 图文 1 文件 + 2 账号 → DB 有 1 batch + 2 detail
  - 一次发布中途 1 账号失败 → 卡片显示 "2成功 1失败"，状态 "partial"

## 9. 不在范围

- 平台实现（`backend/impl/*`）一律不动
- 素材库（`materials` 表、`materials_bp.py`）不动
- 登录、Cookie 校验、个人资料同步不动
- 草稿功能（`drafts`、`image_drafts`）不动
- 抽帧、定时发布功能本身不动（仅消费其结果）
- `mcp__social-auto-upload__*` MCP 工具不动
- 桌面打包（Tauri）不动

## 10. 实施步骤（高层）

1. 更新 `init_db.py` schema（删 4 旧 + 加 2 新）
2. 更新 `app.py` 中 `/postVideo` 的写入路径
3. 更新 `blueprints/image_publish_bp.py` 的写入路径
4. 更新 `ext_api/__init__.py` 的读取路径
5. 更新 `ext_api/task_queue.py` 的 `PublishTask` 数据类与 `_insert_db` / `_update_db`
6. 更新测试文件
7. 改 `PublishHistory.vue` 卡片化
8. 改 `OneClickFillDialog.vue` 封面 bug
9. 改 `PublishCenter.vue` / `ImagePublish.vue` 传 `batchId` + 素材 ID
10. 改 `frontend/src/api/v2.js` 响应适配
11. 启服务，跑单测 + e2e

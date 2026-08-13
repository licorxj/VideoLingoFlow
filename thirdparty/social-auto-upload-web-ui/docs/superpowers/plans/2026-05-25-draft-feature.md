# Draft Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a complete draft system — backend persistence, multi-draft management, draft box page with card layout, and 1:1 state restoration for the publish page.

**Architecture:** New `drafts` SQLite table + RESTful CRUD API under `/api/v2/drafts`. Frontend gets a new `DraftBox.vue` page, sidebar menu entry, and `draft.js` API module. PublishCenter.vue gains save-to-server and restore-from-server logic, replacing the current broken localStorage approach.

**Tech Stack:** Python/Flask (backend), Vue 3 + Element Plus (frontend), SQLite (storage)

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `frontend/src/api/draft.js` | Draft API client (CRUD) |
| `frontend/src/views/DraftBox.vue` | Draft box page with card grid layout |

### Modified files
| File | What changes |
|------|-------------|
| `backend/init_db.py` | Add `drafts` table creation |
| `backend/ext_api/__init__.py` | Add 5 draft CRUD route handlers |
| `frontend/src/App.vue` | Add sidebar menu item for 草稿箱 |
| `frontend/src/router/index.js` | Add `/drafts` route |
| `frontend/src/views/PublishCenter.vue` | Replace saveDraft, add loadDraft/restoreDraft, button style, import draft API |

---

## Task 1: Backend — Add drafts table

**Files:**
- Modify: `backend/init_db.py`

- [ ] **Step 1: Add drafts table to `init_database()`**

In `backend/init_db.py`, after the `settings` table creation block (after line 81), add:

```python
    # 草稿箱表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT DEFAULT '',
        cover_path TEXT DEFAULT '',
        draft_data TEXT DEFAULT '{}',
        channels_summary TEXT DEFAULT '[]',
        video_duration REAL DEFAULT 0,
        video_file_size INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
```

- [ ] **Step 2: Verify table creation**

Run: `cd /home/czy/workspace/ai/social-auto-upload-web-ui/backend && python init_db.py`

Then verify: `sqlite3 db/database.db ".schema drafts"`

Expected output: the `CREATE TABLE drafts(...)` statement.

- [ ] **Step 3: Commit**

```bash
git add backend/init_db.py
git commit -m "功能: 新增草稿箱数据库表"
```

---

## Task 2: Backend — Add draft CRUD API

**Files:**
- Modify: `backend/ext_api/__init__.py`

- [ ] **Step 1: Add draft routes at end of file (before the last existing route)**

In `backend/ext_api/__init__.py`, append the following after the `update_settings()` function (after line 391):

```python
# ========== 草稿箱 ==========

@ext_api.route('/drafts', methods=['GET'])
def get_drafts():
    """获取草稿列表"""
    try:
        conn = _db_conn()
        rows = conn.execute(
            "SELECT id, title, cover_path, channels_summary, video_duration, video_file_size, created_at, updated_at FROM drafts ORDER BY updated_at DESC"
        ).fetchall()
        drafts = []
        for row in rows:
            d = dict(row)
            try:
                d['channels_summary'] = json.loads(d.get('channels_summary', '[]'))
            except json.JSONDecodeError:
                d['channels_summary'] = []
            drafts.append(d)
        conn.close()
        return jsonify({"code": 200, "data": drafts})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)}), 500


@ext_api.route('/drafts', methods=['POST'])
def create_draft():
    """创建草稿"""
    data = request.get_json()
    if not data or not data.get('draft_data'):
        return jsonify({"code": 400, "msg": "草稿数据不能为空"}), 400

    draft_data = data['draft_data']
    title = _extract_draft_title(draft_data)
    cover_path = _extract_draft_cover(draft_data)
    channels_summary = _extract_channels_summary(draft_data)
    video_duration = _extract_video_duration(draft_data)
    video_file_size = _extract_video_file_size(draft_data)

    try:
        conn = _db_conn()
        cursor = conn.execute(
            """INSERT INTO drafts (title, cover_path, draft_data, channels_summary, video_duration, video_file_size)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, cover_path, json.dumps(draft_data, ensure_ascii=False),
             json.dumps(channels_summary, ensure_ascii=False),
             video_duration, video_file_size)
        )
        conn.commit()
        draft_id = cursor.lastrowid
        conn.close()
        return jsonify({"code": 200, "data": {"id": draft_id, "title": title}})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)}), 500


@ext_api.route('/drafts/<int:draft_id>', methods=['GET'])
def get_draft(draft_id):
    """获取草稿详情"""
    try:
        conn = _db_conn()
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        conn.close()
        if not row:
            return jsonify({"code": 404, "msg": "草稿不存在"}), 404
        d = dict(row)
        try:
            d['channels_summary'] = json.loads(d.get('channels_summary', '[]'))
        except json.JSONDecodeError:
            d['channels_summary'] = []
        return jsonify({"code": 200, "data": d})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)}), 500


@ext_api.route('/drafts/<int:draft_id>', methods=['PUT'])
def update_draft(draft_id):
    """更新草稿"""
    data = request.get_json()
    if not data or not data.get('draft_data'):
        return jsonify({"code": 400, "msg": "草稿数据不能为空"}), 400

    draft_data = data['draft_data']
    title = _extract_draft_title(draft_data)
    cover_path = _extract_draft_cover(draft_data)
    channels_summary = _extract_channels_summary(draft_data)
    video_duration = _extract_video_duration(draft_data)
    video_file_size = _extract_video_file_size(draft_data)

    try:
        conn = _db_conn()
        changes = conn.execute(
            """UPDATE drafts SET title=?, cover_path=?, draft_data=?, channels_summary=?,
               video_duration=?, video_file_size=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (title, cover_path, json.dumps(draft_data, ensure_ascii=False),
             json.dumps(channels_summary, ensure_ascii=False),
             video_duration, video_file_size, draft_id)
        ).rowcount
        conn.commit()
        conn.close()
        if changes == 0:
            return jsonify({"code": 404, "msg": "草稿不存在"}), 404
        return jsonify({"code": 200, "data": {"id": draft_id, "title": title}})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)}), 500


@ext_api.route('/drafts/<int:draft_id>', methods=['DELETE'])
def delete_draft(draft_id):
    """删除草稿"""
    try:
        conn = _db_conn()
        changes = conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,)).rowcount
        conn.commit()
        conn.close()
        if changes == 0:
            return jsonify({"code": 404, "msg": "草稿不存在"}), 404
        return jsonify({"code": 200, "msg": "草稿已删除"})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)}), 500


# ---------- Draft metadata extraction helpers ----------

def _extract_draft_title(draft_data):
    """从草稿数据中提取标题（第一个非空的平台标题）"""
    pc = draft_data.get('platformConfigs', {})
    for key in ['douyin', 'xiaohongshu', 'kuaishou', 'bilibili', 'channels',
                'baijiahao', 'tiktok', 'youtube', 'iqiyi', 'tencent_video']:
        title = pc.get(key, {}).get('title', '')
        if title and title.strip():
            return title.strip()[:100]
    return '无标题'


def _extract_draft_cover(draft_data):
    """从草稿数据中提取封面路径"""
    cc = draft_data.get('commonConfig', {})
    for key in ['coverPortrait', 'coverLandscape']:
        cover = cc.get(key)
        if cover and cover.get('path'):
            return cover['path']
    return ''


def _extract_channels_summary(draft_data):
    """从草稿数据中提取渠道摘要（按平台分组计数）"""
    account_ids = draft_data.get('publishAccountIds', [])
    if not account_ids:
        return []

    platform_map = {
        'xiaohongshu': '小红书', 'channels': '视频号', 'douyin': '抖音',
        'kuaishou': '快手', 'bilibili': 'B站', 'baijiahao': '百家号',
        'tiktok': 'TikTok', 'youtube': 'YouTube', 'iqiyi': '爱奇艺',
        'tencent_video': '腾讯视频',
    }

    try:
        conn = _db_conn()
        placeholders = ','.join(['?'] * len(account_ids))
        rows = conn.execute(
            f"SELECT id, type FROM user_info WHERE id IN ({placeholders})",
            account_ids
        ).fetchall()
        conn.close()

        type_to_platform = {v: k for k, v in {
            'xiaohongshu': 1, 'channels': 2, 'douyin': 3,
            'kuaishou': 4, 'bilibili': 5,
        }.items()}

        platform_counts = {}
        for row in rows:
            pkey = type_to_platform.get(row['type'])
            if pkey:
                platform_counts[pkey] = platform_counts.get(pkey, 0) + 1

        return [{"platform": k, "name": platform_map.get(k, k), "count": v}
                for k, v in platform_counts.items()]
    except Exception:
        return []


def _extract_video_duration(draft_data):
    """从草稿数据中提取视频时长（暂存0，后续可从抽帧结果中获取）"""
    return 0


def _extract_video_file_size(draft_data):
    """从草稿数据中提取视频文件大小"""
    cc = draft_data.get('commonConfig', {})
    for key in ['videoPortrait', 'videoLandscape']:
        video = cc.get(key)
        if video and video.get('size'):
            return video['size']
    return 0
```

- [ ] **Step 2: Verify API starts**

Run: `cd /home/czy/workspace/ai/social-auto-upload-web-ui && python -c "from backend.ext_api import ext_api; print([r.rule for r in ext_api.url_map.iter_rules() if 'draft' in r.rule])"`

Expected: list containing `/api/v2/drafts` and `/api/v2/drafts/<int:draft_id>`.

- [ ] **Step 3: Commit**

```bash
git add backend/ext_api/__init__.py
git commit -m "功能: 新增草稿箱增删改查API接口"
```

---

## Task 3: Frontend — Draft API module

**Files:**
- Create: `frontend/src/api/draft.js`

- [ ] **Step 1: Create draft API module**

Create `frontend/src/api/draft.js`:

```js
import { http } from '@/utils/request'

export const draftApi = {
  getDrafts() {
    return http.get('/api/v2/drafts')
  },
  createDraft(data) {
    return http.post('/api/v2/drafts', data)
  },
  getDraft(id) {
    return http.get(`/api/v2/drafts/${id}`)
  },
  updateDraft(id, data) {
    return http.put(`/api/v2/drafts/${id}`, data)
  },
  deleteDraft(id) {
    return http.delete(`/api/v2/drafts/${id}`)
  },
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/draft.js
git commit -m "功能: 新增草稿箱前端API模块"
```

---

## Task 4: Frontend — Sidebar menu + route

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/router/index.js`

- [ ] **Step 1: Add route in `frontend/src/router/index.js`**

After the Material Management route (line 13), add:

```js
  { path: '/drafts', name: 'DraftBox', component: () => import('../views/DraftBox.vue'), meta: { icon: 'Document', title: '草稿箱' } },
```

- [ ] **Step 2: Add sidebar menu item in `frontend/src/App.vue`**

In the imports (line 81-83), add `Document` to the icon imports:

```js
import {
  HomeFilled, User, Picture, Upload,
  Clock, Setting, Expand, Fold, UserFilled, Document
} from '@element-plus/icons-vue'
```

In the `navItems` array (lines 90-97), add after the Material Management entry (after line 93):

```js
  { path: '/drafts', icon: Document, title: '草稿箱' },
```

- [ ] **Step 3: Verify sidebar renders**

Start the dev server and confirm the "草稿箱" menu item appears in the sidebar between "素材管理" and "发布中心". The route will 404 until DraftBox.vue is created — that's expected.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.vue frontend/src/router/index.js
git commit -m "功能: 新增草稿箱侧边栏菜单和路由"
```

---

## Task 5: Frontend — DraftBox.vue page

**Files:**
- Create: `frontend/src/views/DraftBox.vue`

This is the largest task. The page shows a card grid of all saved drafts.

- [ ] **Step 1: Create DraftBox.vue**

Create `frontend/src/views/DraftBox.vue`:

```vue
<template>
  <div class="draft-box">
    <div class="draft-header">
      <h2>草稿箱</h2>
      <span class="draft-count">{{ drafts.length }} 个草稿</span>
    </div>

    <!-- Empty state -->
    <div v-if="!loading && drafts.length === 0" class="empty-state">
      <el-empty description="还没有保存的草稿">
        <el-button type="primary" @click="router.push('/publish-center')">去发布视频</el-button>
      </el-empty>
    </div>

    <!-- Card grid -->
    <div v-else class="draft-grid">
      <div v-for="draft in drafts" :key="draft.id" class="draft-card">
        <!-- Cover thumbnail -->
        <div class="card-cover">
          <img
            v-if="draft.cover_path"
            :src="getCoverUrl(draft.cover_path)"
            alt="封面"
          />
          <div v-else class="cover-placeholder">
            <el-icon :size="32"><Picture /></el-icon>
          </div>
          <!-- Duration badge -->
          <span v-if="draft.video_duration" class="duration-badge">
            {{ formatDuration(draft.video_duration) }}
          </span>
        </div>

        <!-- Card body -->
        <div class="card-body">
          <div class="card-title">{{ draft.title || '无标题' }}</div>

          <!-- Channels summary -->
          <div class="card-channels">
            <template v-for="ch in draft.channels_summary" :key="ch.platform">
              <span class="channel-tag">
                <img
                  v-if="getPlatformLogo(ch.platform)"
                  :src="getPlatformLogo(ch.platform)"
                  class="channel-icon"
                />
                {{ ch.name }} × {{ ch.count }}
              </span>
            </template>
          </div>

          <!-- Meta info -->
          <div class="card-meta">
            <span v-if="draft.video_file_size">{{ formatFileSize(draft.video_file_size) }}</span>
            <span>{{ formatTime(draft.updated_at) }}</span>
          </div>
        </div>

        <!-- Card actions -->
        <div class="card-actions">
          <el-button size="small" type="primary" @click="editDraft(draft.id)">
            <el-icon><Edit /></el-icon> 编辑
          </el-button>
          <el-button size="small" @click="confirmDelete(draft.id)">
            <el-icon><Delete /></el-icon> 删除
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Picture, Edit, Delete } from '@element-plus/icons-vue'
import { draftApi } from '@/api/draft'
import { getPlatformByKey } from '@/config/platforms'

const router = useRouter()
const drafts = ref([])
const loading = ref(true)

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5409'

function getCoverUrl(path) {
  if (!path) return ''
  if (path.startsWith('http')) return path
  return `${apiBaseUrl}${path.startsWith('/') ? '' : '/'}${path}`
}

function getPlatformLogo(platformKey) {
  const p = getPlatformByKey(platformKey)
  return p?.logo || null
}

function formatDuration(seconds) {
  if (!seconds) return ''
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatFileSize(bytes) {
  if (!bytes) return ''
  if (bytes >= 1024 * 1024 * 1024) return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
  if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / 1024).toFixed(0) + ' KB'
}

function formatTime(isoString) {
  if (!isoString) return ''
  const date = new Date(isoString)
  const now = new Date()
  const diff = now - date
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (hours < 24) return `${hours} 小时前`
  if (days < 7) return `${days} 天前`
  return date.toLocaleDateString('zh-CN')
}

function editDraft(id) {
  router.push(`/publish-center?draft=${id}`)
}

async function confirmDelete(id) {
  try {
    await ElMessageBox.confirm('确定删除这个草稿吗？', '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await draftApi.deleteDraft(id)
    ElMessage.success('草稿已删除')
    await loadDrafts()
  } catch {
    // cancelled or error
  }
}

async function loadDrafts() {
  loading.value = true
  try {
    const resp = await draftApi.getDrafts()
    drafts.value = resp.data || []
  } catch (e) {
    console.error('Failed to load drafts:', e)
  } finally {
    loading.value = false
  }
}

onMounted(loadDrafts)
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.draft-box {
  padding: 24px;
  min-height: 100%;
}

.draft-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;

  h2 {
    margin: 0;
    font-size: 20px;
    font-weight: 600;
    color: $text-primary;
  }

  .draft-count {
    font-size: 13px;
    color: $text-muted;
  }
}

.empty-state {
  display: flex;
  justify-content: center;
  padding: 80px 0;
}

.draft-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.draft-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid $border;
  border-radius: $radius-lg;
  overflow: hidden;
  transition: $transition-base;

  &:hover {
    border-color: rgba(255, 255, 255, 0.15);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  }
}

.card-cover {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: rgba(255, 255, 255, 0.03);
  overflow: hidden;

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .cover-placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: $text-muted;
  }

  .duration-badge {
    position: absolute;
    bottom: 8px;
    right: 8px;
    background: rgba(0, 0, 0, 0.7);
    color: #fff;
    font-size: 12px;
    padding: 2px 6px;
    border-radius: 4px;
  }
}

.card-body {
  padding: 12px 16px;
}

.card-title {
  font-size: 14px;
  font-weight: 500;
  color: $text-primary;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 8px;
}

.card-channels {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
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
}

.channel-icon {
  width: 14px;
  height: 14px;
  border-radius: 2px;
}

.card-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: $text-muted;
}

.card-actions {
  display: flex;
  gap: 8px;
  padding: 0 16px 12px;
}
</style>
```

- [ ] **Step 2: Verify page renders**

Start the dev server, navigate to the 草稿箱 page. The empty state should display correctly. The route and sidebar should work.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/DraftBox.vue
git commit -m "功能: 新增草稿箱页面（卡片布局）"
```

---

## Task 6: Frontend — Rewrite PublishCenter save/restore logic

**Files:**
- Modify: `frontend/src/views/PublishCenter.vue`

This is the most complex task. It replaces the localStorage save with server API, adds draft restoration, and updates the button style.

- [ ] **Step 1: Add draft API import**

In `frontend/src/views/PublishCenter.vue`, at the import section (after line 655), add:

```js
import { draftApi } from '@/api/draft'
import { useRoute } from 'vue-router'
```

And add `useRoute` usage after `appStore.loadAutoFillTitle()` (line 660):

```js
const route = useRoute()
```

Also add `onMounted` to the Vue imports (line 644):

```js
import { ref, reactive, computed, nextTick, watch, onMounted } from 'vue'
```

- [ ] **Step 2: Add currentDraftId state**

After `publishAccountIds` (line 976), add:

```js
const currentDraftId = ref(null) // null = new draft mode, number = editing existing draft
```

- [ ] **Step 3: Replace `saveDraft()` function**

Replace the entire `saveDraft()` function (lines 1213-1232) with:

```js
async function saveDraft() {
  try {
    const draftData = {
      commonConfig: {
        topics: [...commonConfig.topics],
        videoLandscape: commonConfig.videoLandscape
          ? { name: commonConfig.videoLandscape.name, path: commonConfig.videoLandscape.path, url: commonConfig.videoLandscape.url, size: commonConfig.videoLandscape.size, type: commonConfig.videoLandscape.type }
          : null,
        videoPortrait: commonConfig.videoPortrait
          ? { name: commonConfig.videoPortrait.name, path: commonConfig.videoPortrait.path, url: commonConfig.videoPortrait.url, size: commonConfig.videoPortrait.size, type: commonConfig.videoPortrait.type }
          : null,
        coverLandscape: commonConfig.coverLandscape
          ? { name: commonConfig.coverLandscape.name, path: commonConfig.coverLandscape.path, url: commonConfig.coverLandscape.url, size: commonConfig.coverLandscape.size, type: commonConfig.coverLandscape.type, _fromFrame: commonConfig.coverLandscape._fromFrame }
          : null,
        coverPortrait: commonConfig.coverPortrait
          ? { name: commonConfig.coverPortrait.name, path: commonConfig.coverPortrait.path, url: commonConfig.coverPortrait.url, size: commonConfig.coverPortrait.size, type: commonConfig.coverPortrait.type, _fromFrame: commonConfig.coverPortrait._fromFrame }
          : null,
      },
      platformConfigs: JSON.parse(JSON.stringify(platformConfigs)),
      accountOverrides: JSON.parse(JSON.stringify(accountOverrides)),
      publishAccountIds: [...publishAccountIds],
      selectedPlatform: selectedPlatform.value,
      selectedAccountId: selectedAccountId.value,
      expandedGroups: [...expandedGroups.value],
      videoModeTab: videoModeTab.value,
    }

    if (currentDraftId.value) {
      await draftApi.updateDraft(currentDraftId.value, { draft_data: draftData })
      ElMessage.success('草稿已更新')
    } else {
      const resp = await draftApi.createDraft({ draft_data: draftData })
      currentDraftId.value = resp.data.id
      ElMessage.success('草稿已保存')
    }
  } catch (e) {
    ElMessage.error('草稿保存失败')
  }
}
```

- [ ] **Step 4: Add `restoreDraft()` function**

After the new `saveDraft()`, add:

```js
async function restoreDraft(draftId) {
  try {
    const resp = await draftApi.getDraft(draftId)
    const data = resp.data
    const dd = data.draft_data
    if (!dd) {
      ElMessage.error('草稿数据为空')
      return
    }

    // Restore commonConfig
    if (dd.commonConfig) {
      if (dd.commonConfig.topics) commonConfig.topics = dd.commonConfig.topics
      if (dd.commonConfig.videoLandscape) commonConfig.videoLandscape = dd.commonConfig.videoLandscape
      if (dd.commonConfig.videoPortrait) commonConfig.videoPortrait = dd.commonConfig.videoPortrait
      if (dd.commonConfig.coverLandscape) commonConfig.coverLandscape = dd.commonConfig.coverLandscape
      if (dd.commonConfig.coverPortrait) commonConfig.coverPortrait = dd.commonConfig.coverPortrait
    }

    // Restore platformConfigs (deep merge to preserve any new fields)
    if (dd.platformConfigs) {
      for (const [key, val] of Object.entries(dd.platformConfigs)) {
        if (platformConfigs[key]) {
          Object.assign(platformConfigs[key], val)
        }
      }
    }

    // Restore accountOverrides
    if (dd.accountOverrides) {
      Object.keys(accountOverrides).forEach(k => delete accountOverrides[k])
      Object.assign(accountOverrides, dd.accountOverrides)
    }

    // Restore publishAccountIds
    if (dd.publishAccountIds) {
      publishAccountIds.clear()
      dd.publishAccountIds.forEach(id => publishAccountIds.add(id))
    }

    // Restore expandedGroups
    if (dd.expandedGroups) {
      expandedGroups.value = new Set(dd.expandedGroups)
    }

    // Restore selectedPlatform
    if (dd.selectedPlatform) {
      selectedPlatform.value = dd.selectedPlatform
    }

    // Restore videoModeTab
    if (dd.videoModeTab) {
      videoModeTab.value = dd.videoModeTab
    }

    // Set draft editing mode
    currentDraftId.value = draftId

    // Re-extract frames for videos (async, non-blocking)
    if (commonConfig.videoLandscape) {
      triggerFrameExtraction(commonConfig.videoLandscape, 'landscape')
    }
    if (commonConfig.videoPortrait) {
      triggerFrameExtraction(commonConfig.videoPortrait, 'portrait')
    }

    ElMessage.success('草稿已恢复')
  } catch (e) {
    ElMessage.error('草稿恢复失败')
  }
}
```

- [ ] **Step 5: Add `onMounted` hook to check for draft query param**

After the `restoreDraft` function, add:

```js
onMounted(() => {
  const draftId = route.query.draft
  if (draftId) {
    restoreDraft(Number(draftId))
  }
})
```

- [ ] **Step 6: Update button template**

Replace the "保存草稿" button at line 81:

Old:
```html
<span class="text-btn cursor-pointer" @click="saveDraft">保存草稿</span>
```

New:
```html
<button class="draft-btn" @click="saveDraft">
  <el-icon><Document /></el-icon>
  {{ currentDraftId ? '更新草稿' : '保存草稿' }}
</button>
```

Add `Document` to the icon imports at line 645:

```js
import { Upload, ArrowDown, ArrowRight, Picture, VideoCameraFilled, Check, Close, InfoFilled, Promotion, StarFilled, Delete, Document } from '@element-plus/icons-vue'
```

- [ ] **Step 7: Add `.draft-btn` styles**

In the `<style>` section, add the draft button style near other button styles:

```scss
.draft-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 16px;
  height: 36px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: $radius-base;
  background: rgba(255, 255, 255, 0.06);
  color: $text-secondary;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: $transition-base;

  &:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: rgba(255, 255, 255, 0.25);
    color: $text-primary;
  }
}
```

- [ ] **Step 8: Verify end-to-end flow**

1. Start dev server + backend
2. Go to Publish Center, fill in some data (title, select accounts)
3. Click "保存草稿" — should save to backend and show success
4. Button should change to "更新草稿"
5. Go to 草稿箱 — should see the draft card
6. Click "编辑" on the card — should navigate to Publish Center with all data restored
7. Modify something, click "更新草稿" — should update the existing draft
8. Go back to 草稿箱 — changes should be reflected

- [ ] **Step 9: Commit**

```bash
git add frontend/src/views/PublishCenter.vue
git commit -m "功能: 发布中心草稿功能改为服务端存储，支持草稿恢复"
```

---

## Verification Checklist

After all tasks are complete:

- [ ] Backend: `sqlite3 backend/db/database.db ".schema drafts"` shows the table
- [ ] Backend: `curl http://localhost:5409/api/v2/drafts` returns `{"code": 200, "data": []}`
- [ ] Frontend: Sidebar shows "草稿箱" menu item between 素材管理 and 发布中心
- [ ] Frontend: 草稿箱 page renders empty state when no drafts
- [ ] Frontend: Save Draft button saves to backend (check `curl http://localhost:5409/api/v2/drafts`)
- [ ] Frontend: Draft box shows card with cover, title, channel badges, time
- [ ] Frontend: Edit draft restores all state 1:1 (videos, covers with `_fromFrame`, platform configs, account overrides, selected accounts, expanded groups, video tab)
- [ ] Frontend: Frame extraction re-triggers on draft restore
- [ ] Frontend: "保存草稿" changes to "更新草稿" after loading a draft
- [ ] Frontend: Delete draft works with confirmation dialog

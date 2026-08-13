# Draft Feature Design

## Context

The publish page has a "Save Draft" button that only writes to localStorage and never reads back. It supports only one draft, misses critical state (selected accounts, UI state, frame selection), and there is no draft management UI. This design adds a complete draft system: backend persistence, multi-draft support, a draft box page with card layout, and 1:1 state restoration.

---

## Data Model

### drafts table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Primary key |
| `title` | TEXT | Draft title (first non-empty platform title) |
| `cover_path` | TEXT | Cover image path (for card thumbnail) |
| `draft_data` | TEXT | Complete state JSON (see below) |
| `channels_summary` | TEXT | JSON array for card display: `[{"platform":"douyin","count":2},...]` |
| `video_duration` | REAL | Video duration in seconds |
| `video_file_size` | INTEGER | Video file size in bytes |
| `created_at` | DATETIME DEFAULT CURRENT_TIMESTAMP | Creation time |
| `updated_at` | DATETIME DEFAULT CURRENT_TIMESTAMP | Last update time |

### draft_data JSON structure

```json
{
  "commonConfig": {
    "videoLandscape": { "name", "path", "url", "size", "type" } | null,
    "videoPortrait": { "name", "path", "url", "size", "type" } | null,
    "coverLandscape": { "name", "path", "url", "size", "type", "_fromFrame" } | null,
    "coverPortrait": { "name", "path", "url", "size", "type", "_fromFrame" } | null,
    "topics": ["tag1", "tag2"]
  },
  "platformConfigs": {
    "douyin": { "title", "description", "productTitle", "productLink", "aiContent", "isOriginal", "scheduleTime", "visibility", "allowDownload", "videoFormat" },
    "xiaohongshu": { ... },
    "kuaishou": { ... },
    "bilibili": { ... },
    "channels": { ... },
    "baijiahao": { ... },
    "tiktok": { ... },
    "youtube": { ... },
    "iqiyi": { ... },
    "tencent_video": { ... }
  },
  "accountOverrides": { "<accountId>": { ...override fields } },
  "publishAccountIds": [1, 2, 3],
  "selectedPlatform": "douyin" | null,
  "selectedAccountId": 123 | null,
  "expandedGroups": ["douyin", "bilibili"],
  "videoModeTab": "portrait" | "landscape"
}
```

Why a single JSON column:
- Platform configs change frequently (new platforms, new fields); JSON is flexible
- Restore is a single deserialize operation, no column mapping needed
- Card display columns (title, cover_path, channels_summary, video_duration, video_file_size) are extracted and stored as separate columns for efficient list queries

---

## Backend API

All endpoints under the existing `ext_api` Blueprint at `/api/v2/`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v2/drafts` | List all drafts (returns summary fields for cards) |
| `POST` | `/api/v2/drafts` | Create a new draft |
| `GET` | `/api/v2/drafts/:id` | Get full draft data (for restoration) |
| `PUT` | `/api/v2/drafts/:id` | Update an existing draft |
| `DELETE` | `/api/v2/drafts/:id` | Delete a draft |

### Request/Response Details

**POST /api/v2/drafts** (create)
```json
// Request body
{
  "draft_data": { ... full state ... }
}
// Server extracts: title, cover_path, channels_summary, video_duration, video_file_size from draft_data
// Response: { "id": 1, "title": "...", "created_at": "..." }
```

**PUT /api/v2/drafts/:id** (update)
```json
// Request body
{
  "draft_data": { ... full state ... }
}
// Server re-extracts metadata columns
// Response: { "id": 1, "title": "...", "updated_at": "..." }
```

**GET /api/v2/drafts** (list)
```json
// Response
[
  {
    "id": 1,
    "title": "My video title",
    "cover_path": "/uploads/cover1.jpg",
    "channels_summary": [{"platform": "douyin", "count": 2}],
    "video_duration": 120.5,
    "video_file_size": 52428800,
    "created_at": "2026-05-25T10:00:00",
    "updated_at": "2026-05-25T10:30:00"
  }
]
```

**GET /api/v2/drafts/:id** (get full)
```json
// Response
{
  "id": 1,
  "draft_data": { ... complete state ... },
  "title": "...",
  "cover_path": "...",
  "channels_summary": [...],
  "video_duration": 120.5,
  "created_at": "...",
  "updated_at": "..."
}
```

### Files to modify
- `backend/init_db.py` — add `drafts` table creation
- `backend/ext_api/__init__.py` — add draft CRUD routes

---

## Frontend

### A. "Save Draft" button style

**File**: `frontend/src/views/PublishCenter.vue` (line 81)

Change from plain `<span class="text-btn">` to a proper secondary-style button with an icon (e.g., `Document` or `Collection` icon from Element Plus). Visually subordinate to the "Publish" action.

### B. Left sidebar menu

**File**: `frontend/src/App.vue` (navItems array, lines 90-99)

Add a "Draft Box" menu item with:
- Icon: `Document` or `Files`
- Label: "草稿箱"
- Route: `/drafts`
- Position: after Material Management, before Publish History

**File**: `frontend/src/router/index.js`

Add route:
```js
{ path: '/drafts', name: 'DraftBox', component: () => import('../views/DraftBox.vue') }
```

### C. Draft Box page (new file: `frontend/src/views/DraftBox.vue`)

Card grid layout showing all saved drafts. Each card displays:
- Cover thumbnail (from `cover_path`)
- Draft title
- Channel icons + account counts per channel (from `channels_summary`)
- Video duration (formatted mm:ss)
- File size (formatted MB/KB)
- Last saved time (relative, e.g., "3 hours ago")
- Action buttons: Edit (jumps to publish page), Delete (with confirmation)

### D. Edit draft flow

1. User clicks "Edit" on a draft card
2. Router navigates to `/publish-center?draft=<id>`
3. PublishCenter.vue `onMounted` checks for `draft` query param
4. If present, calls `GET /api/v2/drafts/:id` to fetch full data
5. Restores all reactive state from `draft_data`:
   - `commonConfig` (videos, covers with `_fromFrame`, topics)
   - `platformConfigs`
   - `accountOverrides`
   - `publishAccountIds` (convert array back to Set)
   - `expandedGroups` (convert array back to Set)
   - `selectedPlatform`
   - `videoModeTab`
6. Triggers `triggerFrameExtraction()` for each video to re-derive frames
7. Stores `currentDraftId` in component state
8. "Save Draft" button text changes to "Update Draft"
9. On click, calls `PUT /api/v2/drafts/:id` instead of `POST /api/v2/drafts`
10. After successful publish, optionally prompt to delete the draft

### E. Draft API module (new file: `frontend/src/api/draft.js`)

```js
// GET /api/v2/drafts
export function getDrafts() { ... }
// POST /api/v2/drafts
export function createDraft(data) { ... }
// GET /api/v2/drafts/:id
export function getDraft(id) { ... }
// PUT /api/v2/drafts/:id
export function updateDraft(id, data) { ... }
// DELETE /api/v2/drafts/:id
export function deleteDraft(id) { ... }
```

### Files to create
- `frontend/src/views/DraftBox.vue`
- `frontend/src/api/draft.js`

### Files to modify
- `frontend/src/views/PublishCenter.vue` — button style, save logic, restore logic
- `frontend/src/App.vue` — add sidebar menu item
- `frontend/src/router/index.js` — add `/drafts` route

---

## Restoration Sequence

When loading a draft for editing:

```
1. Fetch draft data from API
2. Restore commonConfig (videos, covers, topics)
3. Restore platformConfigs (deep merge)
4. Restore accountOverrides (deep merge)
5. Restore publishAccountIds (array → Set)
6. Restore expandedGroups (array → Set)
7. Restore selectedPlatform, selectedAccountId, videoModeTab
8. Trigger frame extraction for landscape video (if present)
9. Trigger frame extraction for portrait video (if present)
10. Set currentDraftId for update mode
11. Update button text to "Update Draft"
```

Steps 8-9 are async. The frames will populate after extraction completes. The `_fromFrame` property on covers ensures the correct frame is highlighted in the CoverCard component once frames are available.

---

## Edge Cases

- **Video/cover file deleted**: On restore, check if file paths still exist. If not, show a warning and clear the reference.
- **Account deleted**: On restore, the account IDs in `publishAccountIds` that no longer exist in the backend will simply not appear in the sidebar (already handled by current account loading logic). No special handling needed.
- **Stale platform config**: New platform fields added after draft was saved will use defaults (reactive initialization handles missing keys).
- **Concurrent edits**: Single-user app, no concurrent access concern.

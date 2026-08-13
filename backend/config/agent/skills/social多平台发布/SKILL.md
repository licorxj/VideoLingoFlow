---
name: "social多平台发布"
description: "指导调用本项目 thirdparty/social-auto-upload-web-ui 内的千帆云递 MCP，完成多平台社交媒体发布。具备 MCP 连通检查、启动 MCP、账号/素材/草稿/视频图文发布/任务/历史等工具调用能力。当用户要做平台发布、调用千帆云递 MCP、或需要启动/检查该 MCP 服务时使用。"
---

# Social 多平台发布（千帆云递 MCP）

本 Skill 指导小 Pi 调用本项目内置的社交媒体自动发布 MCP（千帆云递 QianFan Sync），完成账号登录、素材管理、草稿、视频/图文发布、任务跟踪等平台发布任务。

## 1. 服务位置与端口

| 组件 | 位置（相对 PROJECT_ROOT） | 端口 |
|---|---|---|
| Flask 后端 | `thirdparty/social-auto-upload-web-ui/backend/` | 5409（自动探测，失败时递增） |
| MCP 服务 | `thirdparty/social-auto-upload-web-ui/backend-mcp/` | 5410（SSE） |
| 前端 | `thirdparty/social-auto-upload-web-ui/frontend/` | Vite 开发端口 |

- MCP 通过 HTTP 调用后端（默认 `BACKEND_URL=http://localhost:5409`），发布类操作由后端驱动 Playwright/CloakBrowser 完成。
- MCP 配置从 `backend-mcp/.env` 读取（复制 `.env.example` 生成），关键项：
  `BACKEND_URL=http://localhost:5409`、`MCP_PORT=5410`、`TRANSPORT_MODE=both`、`DB_PATH=../data/db/database.db`。
- 传输模式：`stdio` / `sse` / `both`。SSE 模式接入点为 `http://localhost:5410/sse`，若后端配置了 MCP API Token 则需在请求头带 `Authorization: Bearer <token>` 或 `?token=`。

## 2. 连通检查（先检查再使用）

调用任何工具前，先确认 MCP 与后端可达：

1. 检查 Flask 后端：
   ```
   GET http://localhost:5409/
   ```
   应返回 200 与 HTML/JSON；若失败提示用户先启动千帆云递后端。
2. 检查 MCP SSE 端点（仅 SSE/both 模式）：
   ```
   GET http://localhost:5410/sse
   ```
   无 Token 时直接建立 SSE 连接；有 Token 时需带 Bearer。握手成功即连通。
3. 进程级检查：确认 `backend-mcp` 的 `node` 进程与 `backend` 的 Python 进程在运行；未运行时按下节启动。

若连通失败，按顺序排查：后端是否启动 → `backend-mcp/.env` 是否存在 → `npm install` 是否完成 → 端口 5409/5410 是否被占用。

## 3. 启动 MCP 服务

```powershell
# 首次使用先安装依赖（项目根 = backend-mcp 目录）
cd thirdparty/social-auto-upload-web-ui/backend-mcp
npm install

# 开发模式（tsx watch，自动重载）
npm run dev

# 生产模式
npm run build
npm start
```

- 启动前确认后端 Flask 已在 5409 端口运行；MCP 只是代理，依赖后端。
- `TRANSPORT_MODE=both` 时同时提供 stdio 与 SSE；仅用 stdio 时 MCP 不需要独立端口。
- 启动日志会在 `[MCP] Server ready` 前输出 `Backend URL`、`Auth enabled` 等，可据此确认配置。

## 4. MCP 工具清单与调用规范

以下工具由 `backend-mcp/src/tools/` 注册，通过 MCP 协议调用。

### 4.1 账号（accounts）
| 工具 | 说明 | 关键参数 |
|---|---|---|
| `account_login` | 登录指定平台账号，会打开浏览器 | `type`(1=小红书,2=视频号,3=抖音,4=快手,5=B站,6=百家号,7=TikTok,8=YouTube,9=腾讯视频,10=爱奇艺)、`account_id?` |
| `account_list` | 获取所有账号列表 | 无 |
| `account_check` | 检查账号 Cookie 是否有效 | `id` |
| `account_delete` | 删除账号 | `id` |

### 4.2 素材（materials）
| 工具 | 说明 | 关键参数 |
|---|---|---|
| `material_upload` | 上传图片/视频素材 | `file_path`(本地路径) |
| `material_list` | 素材列表，支持筛选分页 | `type?`(all/video/image)、`keyword?`、`page?`、`page_size?` |
| `material_delete` | 删除素材 | `id` |
| `material_get_info` | 素材详细信息（URL/缩略图/大小） | `id` |
| `material_download` | 获取素材可访问 URL | `id` |

### 4.3 草稿（drafts）
| 工具 | 说明 | 关键参数 |
|---|---|---|
| `draft_list` | 草稿列表 | `type?`(video/image) |
| `draft_get` | 草稿详情 | `id` |
| `draft_create` | 创建草稿 | `type`、`draft_data`(JSON) |
| `draft_update` | 更新草稿 | `id`、`draft_data`(JSON) |
| `draft_delete` | 删除草稿 | `id` |

### 4.4 发布（publish）
| 工具 | 说明 | 关键参数 |
|---|---|---|
| `video_publish` | 发布视频到指定平台 | `type`(1-10 平台编号)、`title`、`material_id?` 或 `fileList?`、`account_id?`/`accountList?`、`tags?`、`description?`、封面参数、定时/声明参数 |
| `image_publish` | 发布图文内容到指定平台 | `image_ids`、`cover_material_id?`/`cover_path?`、`account_configs`(账号+平台+标题描述标签数组) |

**video_publish 必确认项（发布前必须向用户确认）：**
1. 作品声明：各平台字段不同——小红书/抖音/快手用 `aiContent`（下拉值）+ `isOriginal`；视频号/TikTok 用 `aiContent`（"true"/"false"）+ `isOriginal`；B站/腾讯视频/爱奇艺用 `creationDeclaration`；百家号加 `supplementaryDeclaration`；YouTube 用 `audience` + `alteredContent`。
2. 是否定时发布：需要则传 `enableTimer=true` + `scheduleTime`（格式 `yyyy-MM-dd HH:mm:ss`）。
3. 封面图：横版 `thumbnailLandscape`/`thumbnailLandscape_material_id`、竖版 `thumbnailPortrait`/`thumbnailPortrait_material_id`（从素材库选或提供本地路径）。

**image_publish 必确认项：** 封面图（`cover_material_id` 或 `cover_path`）、作品声明、是否定时（`scheduleTime`）。发布为真实发布（内部 `dry_run=false`），不要假设只预览。

### 4.5 任务（tasks）
| 工具 | 说明 | 关键参数 |
|---|---|---|
| `task_list` | 发布任务列表 | `status?`(pending/queued/running/success/failed/cancelled/all)、`page?`、`page_size?` |
| `task_get_status` | 单任务状态/进度/结果 | `task_id` |
| `task_cancel` | 取消任务 | `task_id` |
| `task_retry` | 重试失败任务 | `task_id` |
| `task_stream` | 订阅任务状态 SSE | `idle_timeout_seconds?` |

### 4.6 发布扩展（publish_extra）
| 工具 | 说明 | 关键参数 |
|---|---|---|
| `publish_history` | 发布历史 | `platform?`(xiaohongshu/channels/douyin/kuaishou/bilibili…)、`status?`、`time_range?`(today/7days/30days)、`start_date?`/`end_date?`、`page?`、`page_size?` |
| `publish_stats` | 发布统计（总数/成功率/平台分布/7天趋势） | 无 |
| `queue_status` | 发布队列状态 | 无 |

### 4.7 设置（settings）
| 工具 | 说明 | 关键参数 |
|---|---|---|
| `settings_get` | 获取系统设置（含 MCP API Token 等） | 无 |
| `settings_update` | 更新系统设置 | `settings`(键值对) |

### 4.8 更新日志（changelog）
| 工具 | 说明 | 关键参数 |
|---|---|---|
| `changelog_list` | 系统更新日志（按日期倒序） | 无 |

## 5. 推荐发布流程

1. **连通检查**：按第 2 节确认后端与 MCP 可达，未启动则按第 3 节启动。
2. **准备账号**：`account_list` 查看账号；缺失时 `account_login` 引导扫码/浏览器登录，用 `account_check` 确认 Cookie 有效。
3. **准备素材**：`material_upload` 上传视频/图片，`material_list` 确认；或让用户提供本地路径。
4. **确认发布信息**：向用户确认标题、描述、标签、封面（横版+竖版）、作品声明、是否定时。
5. **执行发布**：`video_publish` 或 `image_publish`，优先传 `material_id`/`account_id`。
6. **跟踪结果**：`task_list`/`task_get_status` 查看状态，失败用 `task_retry` 重试，`publish_history`/`publish_stats` 汇总结果。

## 6. 注意事项

- 发布是真实操作（视频/图文会实际投递到平台），**每次发布前必须与用户二次确认平台、账号、标题与声明**，不要自动发布。
- `material_id`/`account_id` 查询上限为前 100 条，找不到时用 `material_list`/`account_list` 翻页或用 `keyword` 过滤。
- `material_upload` 的 `file_path` 是本地路径；AI 客户端无持久化文件系统时应优先用素材库 ID 引用。
- 平台编号 `type` 全局一致：1=小红书, 2=视频号, 3=抖音, 4=快手, 5=B站, 6=百家号, 7=TikTok, 8=YouTube, 9=腾讯视频, 10=爱奇艺。
- 涉及账号登录会打开真实浏览器，涉及发布会投递到真实平台，均需明确获得用户同意。

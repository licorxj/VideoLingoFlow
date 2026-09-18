"""Publish service HTTP client - direct calls to social-auto-upload backend.

Calls the Flask backend on port 5409 directly (not via MCP protocol on 5410).
"""
import os
from typing import Any, Dict, Generator, List, Optional

import requests


# ═══════════════════════════════════════════
# 内容声明映射
# ═══════════════════════════════════════════
# VideoLingo 发布节点的 declaration 值域：
#   "" / ai_generated / repost / fictional / marketing / personal_opinion
# 需映射为 social-auto-upload-web-ui 各平台自己的声明字段名与文案，依据：
#   - 前端 frontend/src/config/platforms.js 的 settingsFields
#   - 后端 backend/services/draft_merge.py 的 DECLARATION_PLATFORMS（草稿校验字段名）
#   - 后端 app.py /postVideo 读取的顶层字段（aiContent / creationDeclaration / ...）
# 未列出的平台（weibo/alipay/toutiao 等）本节点暂不投射声明。
_DECLARATION_NONE_KS = "内容无需添加声明"  # 快手约定的「无需声明」值（不可用空串）

# social 平台 key → (目标字段名, {VideoLingo 值: 平台文案})
_DECLARATION_TEXT_FIELDS = {
    "xiaohongshu": ("aiContent", {
        "ai_generated": "笔记含AI合成内容",
        "fictional": "虚构演绎，仅供娱乐",
        "marketing": "内容包含营销广告",
        "repost": "内容来源声明",
    }),
    "channels": ("channelsMarkTag", {
        "ai_generated": "含AI生成内容",
        "fictional": "内容为虚构剧情，仅供娱乐",
        "personal_opinion": "个人观点，仅供参考",
        "marketing": "内容包含营销广告",
        "repost": "内容为转载",
    }),
    "douyin": ("aiContent", {
        "ai_generated": "内容由AI生成",
        "personal_opinion": "内容为个人观点或见解",
        "repost": "内容为转载信息",
        "marketing": "内容含营销推广信息",
        "fictional": "虚构演绎，仅供娱乐",
    }),
    "kuaishou": ("aiContent", {
        "ai_generated": "内容为AI生成",
        "fictional": "演绎情节，仅供娱乐",
        "personal_opinion": "个人观点，仅供参考",
        "repost": "素材来源于网络",
        # 快手无「营销」选项，退回无需声明
        "marketing": _DECLARATION_NONE_KS,
    }),
    "bilibili": ("creationDeclaration", {
        "ai_generated": "含AI生成内容",
        "fictional": "含虚构演绎内容",
        "marketing": "内容含营销信息",
        "personal_opinion": "个人观点，仅供参考",
        "repost": "内容为转载",
    }),
    "baijiahao": ("creationDeclaration", {
        "ai_generated": "含AI生成内容",
        "repost": "内容为转载",
        "fictional": "含虚构演绎内容",
        "marketing": "内容含营销信息",
        "personal_opinion": "个人观点，仅供参考",
    }),
    "tencent_video": ("creationDeclaration", {
        # 腾讯视频为多选，值需为数组
        "ai_generated": ["内容由AI生成"],
        "fictional": ["剧情演绎，仅供娱乐"],
        "personal_opinion": ["个人观点，仅供参考"],
        "repost": ["取材网络，谨慎甄别"],
    }),
    "iqiyi": ("creationDeclaration", {
        "ai_generated": "含AI生成内容",
        "fictional": "含虚构演绎内容",
        "marketing": "内容含营销信息",
        "repost": "内容为转载",
        "personal_opinion": "个人观点，仅供参考",
    }),
}

# 布尔型声明字段：ai_generated / fictional 视为「含合成或加工内容」
_DECLARATION_BOOL_FIELDS = {
    "tiktok": "aiContent",
    "youtube": "alteredContent",
}

# VideoLingo platform_config.py 的内部 key 与 social key 的差异
_PLATFORM_KEY_ALIASES = {"shipinhao": "channels", "tengxun": "tencent_video"}

# 声明为空时仍需写入「无需声明」下拉的平台（其余平台留空交给前端默认值）
_DECLARATION_REQUIRED_NONE = {"kuaishou": ("aiContent", _DECLARATION_NONE_KS)}


def build_declaration_fields(platform_key: str, declaration: str) -> dict:
    """把 VideoLingo 的 declaration 映射为 social 平台的声明字段。

    Args:
        platform_key: social 侧平台 key（channels/douyin/...），兼容 shipinhao/tengxun 别名。
        declaration: "" / ai_generated / repost / fictional / marketing / personal_opinion。

    Returns:
        {字段名: 值}；无法映射时返回空 dict（不覆盖平台原有默认值）。
    """
    key = (platform_key or "").strip().lower()
    key = _PLATFORM_KEY_ALIASES.get(key, key)
    value_key = (declaration or "").strip()

    if not value_key:
        required = _DECLARATION_REQUIRED_NONE.get(key)
        return {required[0]: required[1]} if required else {}

    bool_field = _DECLARATION_BOOL_FIELDS.get(key)
    if bool_field:
        return {bool_field: value_key in ("ai_generated", "fictional")}

    entry = _DECLARATION_TEXT_FIELDS.get(key)
    if not entry:
        return {}
    field_name, mapping = entry
    value = mapping.get(value_key)
    return {field_name: value} if value is not None else {}


class PublishClient:
    """HTTP client for the social-auto-upload backend service."""

    DEFAULT_BASE_URL = "http://localhost:5409"

    def __init__(self, base_url: Optional[str] = None, timeout: int = 600):
        self._base_url = (base_url or os.getenv("SOCIAL_BACKEND_URL", self.DEFAULT_BASE_URL)).rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        # Don't set Content-Type globally — it conflicts with multipart/form-data file uploads
        self._json_headers = {"Content-Type": "application/json"}

    # ─── HTTP primitives ───

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        resp = self._session.get(f"{self._base_url}{path}", params=params, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: Optional[dict] = None) -> dict:
        resp = self._session.post(f"{self._base_url}{path}", json=data, headers=self._json_headers, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, data: Optional[dict] = None) -> dict:
        resp = self._session.put(f"{self._base_url}{path}", json=data, headers=self._json_headers, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> dict:
        resp = self._session.delete(f"{self._base_url}{path}", timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    # ═══════════════════════════════════════════
    # Account Management
    # ═══════════════════════════════════════════

    def list_accounts(self) -> List[dict]:
        """Get all platform accounts (normalized to dicts)."""
        result = self._get("/getAccounts")
        raw = []
        if isinstance(result, dict):
            raw = result.get("data", result.get("accounts", []))
        elif isinstance(result, list):
            raw = result
        accounts = []
        for item in raw:
            if isinstance(item, dict):
                accounts.append(item)
            elif isinstance(item, list) and len(item) >= 4:
                accounts.append({
                    "id": item[0],
                    "type": item[1],
                    "cookie_file": item[2],
                    "name": item[3],
                    "status": item[4] if len(item) > 4 else 0,
                    "avatar": item[5] if len(item) > 5 else "",
                })
        return accounts

    def get_valid_accounts(self) -> List[dict]:
        """Get accounts with cookie validity check (slower)."""
        result = self._get("/getValidAccounts")
        raw = []
        if isinstance(result, dict):
            raw = result.get("data", result.get("accounts", []))
        elif isinstance(result, list):
            raw = result
        accounts = []
        for item in raw:
            if isinstance(item, dict):
                accounts.append(item)
            elif isinstance(item, list) and len(item) >= 4:
                accounts.append({
                    "id": item[0],
                    "type": item[1],
                    "cookie_file": item[2],
                    "name": item[3],
                    "status": item[4] if len(item) > 4 else 0,
                    "avatar": item[5] if len(item) > 5 else "",
                })
        return accounts

    def check_account(self, account_id: str) -> dict:
        """Check if account cookie is valid."""
        return self._get("/checkAccount", {"id": account_id})

    def delete_account(self, account_id: str) -> dict:
        """Delete an account."""
        return self._get("/deleteAccount", {"id": account_id})

    def update_account_info(self, account_id: str, account_type: Optional[int] = None,
                            username: Optional[str] = None) -> dict:
        """Update account info (type, username)."""
        payload: dict = {"account_id": account_id}
        if account_type is not None:
            payload["type"] = account_type
        if username is not None:
            payload["username"] = username
        return self._post("/updateUserinfo", payload)

    def sync_profile(self, account_id: str) -> dict:
        """Sync account avatar and nickname from platform."""
        return self._post("/syncProfile", {"account_id": account_id})

    def open_creator_center(self, account_id: str) -> dict:
        """Open platform creator center for an account."""
        return self._post("/openCreatorCenter", {"account_id": account_id})

    def upload_cookie(self, file_path: str) -> dict:
        """Upload a cookie JSON file."""
        with open(file_path, "rb") as f:
            resp = self._session.post(
                f"{self._base_url}/uploadCookie",
                files={"file": (os.path.basename(file_path), f)},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json()

    # ═══════════════════════════════════════════
    # Tags
    # ═══════════════════════════════════════════

    def list_tags(self) -> dict:
        """Get all tags."""
        return self._get("/api/tags")

    def create_tag(self, name: str, color: Optional[str] = None) -> dict:
        """Create a tag."""
        payload: dict = {"name": name}
        if color:
            payload["color"] = color
        return self._post("/api/tags", payload)

    def delete_tag(self, tag_id: int) -> dict:
        """Delete a tag."""
        return self._delete(f"/api/tags/{tag_id}")

    def get_account_tags(self, account_id: int) -> dict:
        """Get tags for an account."""
        return self._get(f"/api/accounts/{account_id}/tags")

    def set_account_tags(self, account_id: int, tag_ids: List[int]) -> dict:
        """Set tags for an account (replaces existing)."""
        return self._put(f"/api/accounts/{account_id}/tags", {"tag_ids": tag_ids})

    def batch_set_account_tags(self, account_ids: List[int], tag_ids: List[int]) -> dict:
        """Batch append tags to multiple accounts."""
        return self._put("/api/accounts/batch/tags", {"account_ids": account_ids, "tag_ids": tag_ids})

    # ═══════════════════════════════════════════
    # Video Publishing
    # ═══════════════════════════════════════════

    @staticmethod
    def _platform_key_of(platform_type: int) -> str:
        """平台 type 数字 → 平台 key（1→xiaohongshu …）。"""
        try:
            from backend.publish.platform_config import PLATFORMS
            return (PLATFORMS.get(platform_type) or {}).get("key", "")
        except Exception:
            return ""

    def publish_video(
        self,
        type: int,
        title: str,
        file_paths: List[str],
        account_list: List[str],
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        thumbnail_landscape: Optional[str] = None,
        thumbnail_portrait: Optional[str] = None,
        is_draft: bool = False,
        schedule_time: Optional[str] = None,
        is_original: bool = False,
        video_format: str = "",
        declaration: str = "",
        **kwargs,
    ) -> dict:
        """Publish video to a platform.

        Args:
            type: Platform type ID (e.g. 3 for Douyin).
            title: Video title.
            file_paths: List of video file paths.
            account_list: List of cookie file names (NOT account IDs!).
            description: Video description.
            tags: List of tags.
            thumbnail_landscape: Landscape cover image path.
            thumbnail_portrait: Portrait cover image path.
            is_draft: If True, save as platform draft instead of publishing.
            schedule_time: Schedule time string "YYYY-MM-DD HH:mm:ss".
            is_original: Mark as original content.
            video_format: "portrait" or "landscape".
            declaration: Content declaration (e.g. "ai_generated", "repost", "fictional", "marketing", "personal_opinion").
        """
        payload = {
            "type": type,
            "title": title,
            "fileList": file_paths,
            "accountList": account_list,
        }
        if description:
            payload["description"] = description
        if tags:
            payload["tags"] = tags
        if thumbnail_landscape:
            payload["thumbnail"] = thumbnail_landscape
            payload["thumbnailLandscape"] = thumbnail_landscape
        if thumbnail_portrait:
            payload["thumbnailPortrait"] = thumbnail_portrait
        if video_format:
            payload["videoFormat"] = video_format
        if is_draft:
            payload["isDraft"] = True
        if schedule_time:
            payload["enableTimer"] = True
            payload["scheduleTime"] = schedule_time
        if is_original:
            payload["isOriginal"] = True
        # 内容声明：映射为 social 平台认识的字段名（aiContent / creationDeclaration / ...）
        payload.update(build_declaration_fields(self._platform_key_of(type), declaration))
        payload.update(kwargs)
        print(f"[Publish] /postVideo: type={type}, title='{title}', "
              f"accounts={account_list}, isDraft={is_draft}, videoFormat={video_format}", flush=True)
        return self._post("/postVideo", payload)

    def publish_video_batch(self, videos: List[dict]) -> dict:
        """Batch publish videos (JSON array, executed sequentially)."""
        return self._post("/postVideoBatch", videos)

    # ═══════════════════════════════════════════
    # Materials
    # ═══════════════════════════════════════════

    def upload_material(self, file_path: str, upload_timeout: int = 1800) -> dict:
        """Upload a media material file.

        Args:
            file_path: Local path to the media file.
            upload_timeout: Timeout in seconds for upload (default 30min for large videos).

        Returns: {id, original_filename, stored_path, file_type, mime_type, file_size, url}
        """
        file_size = os.path.getsize(file_path)
        print(f"[Publish] Uploading material: {os.path.basename(file_path)} ({file_size / 1024 / 1024:.1f} MB)", flush=True)
        with open(file_path, "rb") as f:
            resp = self._session.post(
                f"{self._base_url}/api/materials/upload",
                files={"file": (os.path.basename(file_path), f)},
                timeout=upload_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            result = data.get("data", data)
            print(f"[Publish] Upload OK: id={result.get('id', '?')}, stored_path={result.get('stored_path', '?')}", flush=True)
            return result

    def list_materials(self, material_type: str = "all", keyword: str = "",
                       page: int = 1, page_size: int = 20) -> dict:
        """List materials with filtering and pagination."""
        return self._get("/api/materials/list", {
            "type": material_type,
            "keyword": keyword,
            "page": str(page),
            "page_size": str(page_size),
        })

    def get_material(self, material_id: str) -> dict:
        """Get a single material by ID."""
        return self._get(f"/api/materials/{material_id}")

    def delete_material(self, material_id: str) -> dict:
        """Delete a material."""
        return self._delete(f"/api/materials/{material_id}")

    def probe_material(self, material_id: str) -> dict:
        """Probe a material for duration/size info."""
        return self._post(f"/api/materials/{material_id}/probe")

    def upload_chunked_init(self, filename: str, total_size: int, total_chunks: int) -> dict:
        """Initialize a chunked upload session (for large files)."""
        return self._post("/api/uploads/init", {
            "filename": filename,
            "total_size": total_size,
            "total_chunks": total_chunks,
        })

    def upload_chunk(self, upload_id: str, chunk_index: int, chunk_data: bytes) -> dict:
        """Upload a single chunk."""
        resp = self._session.post(
            f"{self._base_url}/api/uploads/chunk",
            data={"upload_id": upload_id, "index": str(chunk_index)},
            files={"chunk": (f"chunk_{chunk_index}", chunk_data)},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def upload_chunked_merge(self, upload_id: str, original_filename: str) -> dict:
        """Merge all chunks into a final material."""
        return self._post("/api/uploads/merge", {
            "upload_id": upload_id,
            "original_filename": original_filename,
        })

    def upload_chunked_status(self, upload_id: str) -> dict:
        """Check which chunks have been uploaded (for resume)."""
        return self._get("/api/uploads/status", {"upload_id": upload_id})

    def upload_chunked_cancel(self, upload_id: str) -> dict:
        """Cancel a chunked upload and clean up."""
        return self._delete(f"/api/uploads/?upload_id={upload_id}")

    # ═══════════════════════════════════════════
    # Drafts
    # ═══════════════════════════════════════════

    def list_drafts(self, draft_type: str = "video") -> dict:
        """List drafts."""
        return self._get("/api/v2/drafts", {"type": draft_type})

    def get_draft(self, draft_id: str) -> dict:
        """Get draft details."""
        return self._get(f"/api/v2/drafts/{draft_id}")

    def create_draft(self, draft_type: str, draft_data: dict) -> dict:
        """Create a publish draft."""
        return self._post("/api/v2/drafts", {"type": draft_type, "draft_data": draft_data})

    def create_video_draft(
        self,
        title: str,
        file_paths: List[str],
        account_ids: List[int],
        platform_key: str,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        thumbnail_landscape: Optional[str] = None,
        thumbnail_portrait: Optional[str] = None,
        schedule_time: Optional[str] = None,
        video_orientation: str = "landscape",
        is_original: bool = False,
        declaration: str = "",
    ) -> dict:
        """Create a local video draft (visible in the UI draft box).

        Uploads files to materials system first, then constructs draft_data
        matching PublishCenter.vue's expected structure.
        """
        # VideoLingo 内部 key（shipinhao/tengxun）需归一为 social 的键（channels/tencent_video），
        # 否则草稿的平台勾选（platformChecked）与展开状态会因键名不匹配而丢失
        platform_key = _PLATFORM_KEY_ALIASES.get(
            (platform_key or "").strip().lower(), (platform_key or "").strip().lower()
        )

        def _to_material_obj(file_path: str, label: str = "file") -> Optional[dict]:
            if not file_path or not os.path.exists(file_path):
                print(f"[Publish] Skip {label}: path empty or not found ({file_path})", flush=True)
                return None
            try:
                mat = self.upload_material(file_path)
                stored_path = mat.get("stored_path", "")
                if not stored_path:
                    print(f"[Publish] Warning: {label} upload returned empty stored_path", flush=True)
                obj = {
                    "id": mat.get("id", ""),
                    "name": mat.get("original_filename", os.path.basename(file_path)),
                    "stored_path": stored_path,
                    "url": mat.get("url", ""),
                    "size": mat.get("file_size", 0),
                    "type": mat.get("mime_type", "application/octet-stream"),
                }
                print(f"[Publish] {label} material obj: id={obj['id']}, stored_path={obj['stored_path']}", flush=True)
                return obj
            except Exception as e:
                print(f"[Publish] ERROR uploading {label} ({file_path}): {e}", flush=True)
                return None

        video_obj = _to_material_obj(file_paths[0] if file_paths else "", "video")
        cover_landscape_obj = _to_material_obj(thumbnail_landscape, "cover_landscape")
        cover_portrait_obj = _to_material_obj(thumbnail_portrait, "cover_portrait")
        if cover_landscape_obj and not cover_portrait_obj:
            cover_portrait_obj = dict(cover_landscape_obj)
        elif cover_portrait_obj and not cover_landscape_obj:
            cover_landscape_obj = dict(cover_portrait_obj)

        common_config: dict = {}
        if video_obj:
            common_config["videoLandscape"] = video_obj
            common_config["videoPortrait"] = dict(video_obj)
        if cover_landscape_obj:
            common_config["coverLandscape"] = cover_landscape_obj
        if cover_portrait_obj:
            common_config["coverPortrait"] = cover_portrait_obj

        platform_config: dict = {"title": title or ""}
        if description:
            platform_config["description"] = description
        if tags:
            platform_config["tags"] = tags
        if schedule_time:
            platform_config["scheduleTime"] = schedule_time
        if is_original:
            platform_config["isOriginal"] = True
        # videoFormat: 'portrait' or 'landscape' — required by draft_merge for publish
        if video_orientation:
            platform_config["videoFormat"] = video_orientation

        all_platform_keys = [
            "xiaohongshu", "channels", "douyin", "kuaishou", "bilibili",
            "baijiahao", "tiktok", "youtube", "iqiyi", "tencent_video",
            "weibo", "alipay", "toutiao",
        ]
        # 每平台叠加各自的内容声明字段（xiaohongshu→aiContent、bilibili→creationDeclaration、
        # youtube→alteredContent 等），字段名与 social 前端 platforms.js 保持一致
        platform_configs = {}
        for k in all_platform_keys:
            cfg = dict(platform_config)
            cfg.update(build_declaration_fields(k, declaration))
            platform_configs[k] = cfg

        platform_checked = {k: False for k in all_platform_keys}
        account_checked: Dict[str, bool] = {}
        for acc_id in account_ids:
            account_checked[str(acc_id)] = True
            if platform_key in platform_checked:
                platform_checked[platform_key] = True

        draft_data = {
            "commonConfig": common_config,
            "platformConfigs": platform_configs,
            "platformOverrides": {},
            "accountOverrides": {},
            "platformChecked": platform_checked,
            "accountChecked": account_checked,
            "publishAccountIds": account_ids,
            "selectedPlatform": platform_key,
            "selectedAccountId": None,
            "expandedGroups": [platform_key],
            "videoModeTab": video_orientation,
        }
        # Log draft summary before saving
        cc = common_config
        print(f"[Publish] Creating draft: title='{title}', accounts={account_ids}, "
              f"video={'OK' if cc.get('videoLandscape') else 'MISSING'}, "
              f"cover_l={'OK' if cc.get('coverLandscape') else 'MISSING'}, "
              f"cover_p={'OK' if cc.get('coverPortrait') else 'MISSING'}", flush=True)
        return self.create_draft("video", draft_data)

    def update_draft(self, draft_id: str, draft_data: dict) -> dict:
        """Update a draft."""
        return self._put(f"/api/v2/drafts/{draft_id}", draft_data)

    def delete_draft(self, draft_id: str) -> dict:
        """Delete a draft."""
        return self._delete(f"/api/v2/drafts/{draft_id}")

    def batch_publish_drafts(self, draft_ids: List[int]) -> dict:
        """Batch publish drafts (1-30, each draft x account enqueues a task)."""
        return self._post("/api/v2/drafts/batch-publish", {"draft_ids": draft_ids})

    def batch_delete_drafts(self, draft_ids: List[int]) -> dict:
        """Batch delete drafts (1-30)."""
        return self._session.request(
            "DELETE", f"{self._base_url}/api/v2/drafts/batch",
            json={"draft_ids": draft_ids}, timeout=self._timeout,
        ).json()

    # ═══════════════════════════════════════════
    # Tasks
    # ═══════════════════════════════════════════

    def list_tasks(self, status: str = "all", page: int = 1, page_size: int = 20) -> dict:
        """List publish tasks."""
        return self._get("/api/v2/tasks", {
            "status": status,
            "page": str(page),
            "page_size": str(page_size),
        })

    def get_task_status(self, task_id: str) -> dict:
        """Get task status."""
        return self._get(f"/api/v2/tasks/{task_id}")

    def cancel_task(self, task_id: str) -> dict:
        """Cancel a task."""
        return self._post(f"/api/v2/tasks/{task_id}/cancel")

    def retry_task(self, task_id: str) -> dict:
        """Retry a failed task."""
        return self._post(f"/api/v2/tasks/{task_id}/retry")

    # ═══════════════════════════════════════════
    # History & Stats
    # ═══════════════════════════════════════════

    def get_publish_stats(self) -> dict:
        """Get publish statistics."""
        return self._get("/api/v2/stats")

    def get_queue_status(self) -> dict:
        """Get queue status."""
        return self._get("/api/v2/queue/status")

    def get_publish_history(
        self,
        platform: Optional[str] = None,
        status: Optional[str] = None,
        time_range: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """Get publish history."""
        params: dict = {"page": str(page), "page_size": str(page_size)}
        if platform:
            params["platform"] = platform
        if status:
            params["status"] = status
        if time_range:
            params["time_range"] = time_range
        return self._get("/api/v2/history", params)

    def get_history_detail(self, batch_id: str) -> dict:
        """Get a single publish batch detail."""
        return self._get(f"/api/v2/history/{batch_id}")

    def delete_history(self, batch_id: str) -> dict:
        """Delete a single publish history record."""
        return self._delete(f"/api/v2/history/{batch_id}")

    def batch_delete_history(self, batch_ids: List[str]) -> dict:
        """Batch delete publish history (1-50)."""
        return self._session.request(
            "DELETE", f"{self._base_url}/api/v2/history/batch",
            json={"batch_ids": batch_ids}, timeout=self._timeout,
        ).json()

    # ═══════════════════════════════════════════
    # Settings
    # ═══════════════════════════════════════════

    def get_settings(self) -> dict:
        """Get system settings."""
        return self._get("/api/v2/settings")

    def update_settings(self, settings: dict) -> dict:
        """Update system settings."""
        return self._put("/api/v2/settings", settings)

    # ═══════════════════════════════════════════
    # Video Frame Extraction
    # ═══════════════════════════════════════════

    def extract_frames(self, material_id: Optional[str] = None,
                       video_path: Optional[str] = None,
                       interval: float = 1.0) -> dict:
        """Trigger video frame extraction."""
        payload: dict = {"interval": interval}
        if material_id:
            payload["material_id"] = material_id
        if video_path:
            payload["video_path"] = video_path
        return self._post("/api/extract-frames", payload)

    def get_frames_status(self, material_id: Optional[str] = None,
                          video_path: Optional[str] = None) -> dict:
        """Check frame extraction status."""
        params: dict = {}
        if material_id:
            params["material_id"] = material_id
        if video_path:
            params["video_path"] = video_path
        return self._get("/api/frames-status", params)

    def get_frames(self, material_id: Optional[str] = None,
                   video_path: Optional[str] = None) -> dict:
        """Get extracted frames list."""
        params: dict = {}
        if material_id:
            params["material_id"] = material_id
        if video_path:
            params["video_path"] = video_path
        return self._get("/api/frames", params)

    def get_frame_image(self, material_id: Optional[str] = None,
                        video_path: Optional[str] = None,
                        seconds: float = 0,
                        thumbnail: bool = False) -> dict:
        """Get a specific frame image by timestamp."""
        params: dict = {"seconds": str(seconds), "thumbnail": str(thumbnail).lower()}
        if material_id:
            params["material_id"] = material_id
        if video_path:
            params["video_path"] = video_path
        return self._get("/api/frame-image", params)

    # ═══════════════════════════════════════════
    # Templates
    # ═══════════════════════════════════════════

    def get_publish_templates(self, template_type: str = "video") -> dict:
        """Get reusable publish config templates from history."""
        return self._get("/api/v2/publish-templates", {"type": template_type})

    # ═══════════════════════════════════════════
    # Health & System
    # ═══════════════════════════════════════════

    def is_available(self) -> bool:
        """Check if the backend service is reachable."""
        try:
            resp = self._session.get(f"{self._base_url}/api/v2/stats", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def health_check(self) -> dict:
        """Detailed health check with diagnostics."""
        return self._get("/api/health")

    def get_system_info(self) -> dict:
        """Get system info (version, cache size)."""
        return self._get("/api/system-info")

    def clear_cache(self) -> dict:
        """Clear backend caches (frames/logs/S3)."""
        return self._post("/api/clear-cache")


# --- Singleton ---
_client: Optional[PublishClient] = None


def get_publish_client() -> PublishClient:
    """Get or create the singleton PublishClient instance."""
    global _client
    if _client is None:
        _client = PublishClient()
    return _client

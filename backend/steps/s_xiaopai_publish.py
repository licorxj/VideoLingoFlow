"""s_xiaopai_publish: 小Pi助手作品发布节点，自动准备发布数据并调用发布服务"""
import json
import os
import subprocess
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


def _resolve_path(value, task_dir: str = "") -> str:
    """Resolve a file path to absolute path."""
    if not value or not isinstance(value, str):
        return ""
    candidate = value.strip()
    if os.path.isabs(candidate) and os.path.isfile(candidate):
        return candidate
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            return rel
    return ""


def _read_json_file(path: str) -> dict:
    """Read and parse a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _apply_affix(text: str, affix: str, mode) -> str:
    """Apply prefix or suffix to text."""
    if not affix or not text:
        return text
    # Normalize mode: handle list, dict, or non-string types
    if isinstance(mode, list):
        mode = mode[0] if mode else "suffix"
    if isinstance(mode, dict):
        mode = mode.get("value", "suffix")
    mode = str(mode).strip().lower()
    if mode == "prefix":
        return affix + text
    return text + affix


def _detect_video_orientation(video_path: str) -> str:
    """Use ffprobe to detect video orientation.

    Returns "landscape" if width >= height, "portrait" if height > width.
    Falls back to "landscape" if detection fails.
    """
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            info = json.loads(result.stdout)
            streams = info.get("streams", [])
            if streams:
                w = streams[0].get("width", 1920)
                h = streams[0].get("height", 1080)
                return "portrait" if h > w else "landscape"
    except Exception:
        pass
    return "landscape"


class S_XiaopaiPublish(BaseStep):
    step_id = "s_xiaopai_publish"
    step_name = "小派作品发布"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        path = os.path.join(task_dir, "output", f"xiaopai_publish_result_{node_id}.json")
        return os.path.exists(path)

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # --- 1. Read config ---
        account_ids = node_config.get("account_ids", [])
        if isinstance(account_ids, str):
            account_ids = [account_ids] if account_ids else []
        if not account_ids:
            raise ValueError("未选择发布账号。请在节点配置中选择发布账号，或到发布标签页添加账号。")

        title = node_config.get("title", "").strip()
        title_affix = node_config.get("title_affix", "").strip()
        title_affix_mode = node_config.get("title_affix_mode", "suffix")
        if isinstance(title_affix_mode, list):
            title_affix_mode = title_affix_mode[0] if title_affix_mode else "suffix"

        description = node_config.get("description", "").strip()
        desc_affix = node_config.get("desc_affix", "").strip()
        desc_affix_mode = node_config.get("desc_affix_mode", "suffix")
        if isinstance(desc_affix_mode, list):
            desc_affix_mode = desc_affix_mode[0] if desc_affix_mode else "suffix"

        tags_str = node_config.get("tags", "").strip()
        publish_mode = node_config.get("publish_mode", "publish")
        if isinstance(publish_mode, list):
            publish_mode = publish_mode[0] if publish_mode else "publish"
        declaration = node_config.get("declaration", "")
        if isinstance(declaration, list):
            declaration = declaration[0] if declaration else ""
        schedule_enabled = node_config.get("schedule_enabled", False)
        schedule_time = node_config.get("schedule_time", "").strip()
        is_original = node_config.get("is_original", False)

        # --- 2. Resolve video input ---
        video_path = _resolve_path(step_inputs.get("video", ""), task_dir)
        if not video_path:
            raise FileNotFoundError("未找到视频文件。请连接视频输入。")

        # --- 3. Detect video orientation (landscape / portrait) ---
        video_orientation = _detect_video_orientation(video_path)
        if callback:
            callback(10, f"视频方向: {'竖版' if video_orientation == 'portrait' else '横版'}")

        # --- 4. Resolve optional cover images (landscape / portrait) ---
        cover_landscape = _resolve_path(step_inputs.get("cover_landscape", ""), task_dir)
        cover_portrait = _resolve_path(step_inputs.get("cover_portrait", ""), task_dir)

        # --- 5. Read upstream JSON for title/description if not set ---
        json_path = _resolve_path(step_inputs.get("json", ""), task_dir)
        upstream_tags = []
        if json_path:
            try:
                content = _read_json_file(json_path)
                if not title:
                    title = content.get("title") or content.get("tittle") or ""
                if not description:
                    description = content.get("description") or content.get("hook") or content.get("summary") or ""
                # Parse upstream tags
                raw_tags = content.get("tags")
                if isinstance(raw_tags, list):
                    upstream_tags = [str(t).strip() for t in raw_tags if t]
                elif isinstance(raw_tags, str) and raw_tags.strip():
                    upstream_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
                else:
                    upstream_tags = []
            except Exception:
                upstream_tags = []

        if not title:
            raise ValueError("未设置标题。请在节点配置中填写标题，或连接包含标题的JSON输入。")

        # --- 5. Apply title/description prefix/suffix ---
        print(f"[XiaopaiPublish] BEFORE affix: title={title!r}, title_affix={title_affix!r}, title_affix_mode={title_affix_mode!r} (type={type(title_affix_mode).__name__})", flush=True)
        title = _apply_affix(title, title_affix, title_affix_mode)
        print(f"[XiaopaiPublish] AFTER affix: title={title!r}", flush=True)
        description = _apply_affix(description, desc_affix, desc_affix_mode)

        # --- 6. Parse and merge tags (user + upstream) ---
        user_tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
        merged_tags = list(dict.fromkeys(user_tags + upstream_tags))  # dedupe, user first
        tags = merged_tags if merged_tags else None

        # --- 7. Prepare schedule (convert datetime-local format) ---
        actual_schedule = None
        if schedule_enabled and schedule_time:
            # datetime-local produces "YYYY-MM-DDThh:mm", convert to "YYYY-MM-DD HH:mm:ss"
            actual_schedule = schedule_time.replace("T", " ")
            if len(actual_schedule.split(":")) == 2:
                actual_schedule += ":00"

        # --- 8. Determine platform type from first account ---
        from backend.publish.mcp_client import get_publish_client
        client = get_publish_client()

        # Resolve account info to get platform type
        all_accounts = client.list_accounts()
        account_map = {str(a.get("id") or a.get("account_id", "")): a for a in all_accounts}

        first_account = account_map.get(account_ids[0])
        if not first_account:
            # Try matching without string conversion
            for a in all_accounts:
                if str(a.get("id")) == account_ids[0] or str(a.get("account_id")) == account_ids[0]:
                    first_account = a
                    break

        if not first_account:
            raise ValueError(f"找不到账号 ID: {account_ids[0]}。请检查账号是否存在。")

        platform_type = first_account.get("type", 0)

        from backend.publish.platform_config import PLATFORMS
        platform_key = PLATFORMS.get(platform_type, {}).get("key", "unknown")

        if callback:
            mode_labels = {"publish": "发布视频", "platform_draft": "保存平台草稿", "local_draft": "保存本地草稿"}
            callback(30, f"{mode_labels.get(publish_mode, '处理')}到 {len(account_ids)} 个账号...")

        # --- 9. Execute based on publish_mode ---
        results = []
        errors = []

        if publish_mode == "local_draft":
            # Save as local draft (visible in the UI draft box)
            print(f"[XiaopaiPublish] local_draft: video={video_path}, "
                  f"cover_l={cover_landscape or '(none)'}, cover_p={cover_portrait or '(none)'}", flush=True)
            try:
                account_ids_int = [int(aid) for aid in account_ids]
                result = client.create_video_draft(
                    title=title,
                    file_paths=[video_path],
                    account_ids=account_ids_int,
                    platform_key=platform_key,
                    description=description if description else None,
                    tags=tags,
                    thumbnail_landscape=cover_landscape if cover_landscape else None,
                    thumbnail_portrait=cover_portrait if cover_portrait else None,
                    schedule_time=actual_schedule,
                    video_orientation=video_orientation,
                    is_original=is_original,
                    declaration=declaration,
                )
                results.append({"status": "success", "result": result})
            except Exception as e:
                errors.append({"status": "error", "error": str(e)})
        else:
            # publish or platform_draft: call publish_video per account
            is_platform_draft = (publish_mode == "platform_draft")
            # Resolve account IDs to cookie file names
            account_cookie_files = []
            for acc_id in account_ids:
                acc = account_map.get(acc_id)
                if acc:
                    cookie_file = acc.get("filePath") or acc.get("cookie_file", "")
                    if cookie_file:
                        account_cookie_files.append(cookie_file)
                    else:
                        print(f"[XiaopaiPublish] Warning: account {acc_id} has no cookie file", flush=True)
                else:
                    print(f"[XiaopaiPublish] Warning: account {acc_id} not found in account map", flush=True)

            if not account_cookie_files:
                errors.append({"status": "error", "error": "No valid cookie files found for accounts"})
            else:
                try:
                    result = client.publish_video(
                        type=platform_type,
                        title=title,
                        file_paths=[video_path],
                        account_list=account_cookie_files,
                        description=description if description else None,
                        tags=tags,
                        thumbnail_landscape=cover_landscape if cover_landscape else None,
                        thumbnail_portrait=cover_portrait if cover_portrait else None,
                        is_draft=is_platform_draft,
                        schedule_time=actual_schedule,
                        is_original=is_original,
                        video_format=video_orientation,
                        declaration=declaration,
                    )
                    results.append({"accounts": account_cookie_files, "status": "success", "result": result})
                except Exception as e:
                    errors.append({"accounts": account_cookie_files, "status": "error", "error": str(e)})

        if callback:
            callback(80, "保存结果...")

        # --- 10. Save result ---
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f"xiaopai_publish_result_{node_id}.json"
        output_path = os.path.join(output_dir, output_filename)

        publish_output = {
            "publish_params": {
                "title": title,
                "description": description,
                "tags": tags,
                "publish_mode": publish_mode,
                "schedule_time": actual_schedule,
                "is_original": is_original,
                "video_orientation": video_orientation,
                "video_path": video_path,
                "cover_landscape": cover_landscape,
                "cover_portrait": cover_portrait,
                "title_affix": title_affix,
                "title_affix_mode": title_affix_mode,
                "desc_affix": desc_affix,
                "desc_affix_mode": desc_affix_mode,
                "platform_type": platform_type,
                "platform_key": platform_key,
                "account_ids": account_ids,
            },
            "platform_type": platform_type,
            "total_accounts": len(account_ids),
            "success": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors if errors else None,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(publish_output, f, ensure_ascii=False, indent=2)

        result_text = json.dumps(publish_output, ensure_ascii=False, indent=2)

        if callback:
            callback(100, f"发布完成: {len(results)}成功, {len(errors)}失败")

        return {
            "artifacts": [f"output/{output_filename}"],
            "outputs": {
                "text": result_text,
                "result_file": f"output/{output_filename}",
            },
        }
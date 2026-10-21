"""s_video_publish: Publish video to social platforms via the publish service layer."""
import json
import os
import re
import subprocess
from contextlib import contextmanager
from typing import Callable, Dict, Iterator, Optional

from backend.steps.base_step import BaseStep
from backend.steps.io_resolve import resolve_json_input


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
    # 兼容中英文值
    if mode in ("prefix", "前缀", "pre"):
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
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


# Windows 文件名非法字符 + 控制字符
_ILLEGAL_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# 草稿名称最大长度（留出后缀与扩展名空间）
_MAX_DRAFT_NAME_LEN = 60


def _sanitize_draft_name(text: str, max_len: int = _MAX_DRAFT_NAME_LEN) -> str:
    """把任务名/发布标题清洗为可安全用作文件名的文本。

    - 替换 Windows 非法字符（``\\ / : * ? " < > |``）与控制字符
    - 压缩连续空白、去掉首尾的点/空白（Windows 不允许点结尾）
    - 超长截断
    """
    name = _ILLEGAL_NAME_CHARS.sub("_", (text or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")
    return name


def _task_name_of(task_dir: str) -> str:
    """读取 task.json 的 task_name（任务名），缺失时兜底工作区目录名。"""
    task_json = os.path.join(task_dir, "task.json")
    if os.path.exists(task_json):
        try:
            with open(task_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            name = str(data.get("task_name") or "").strip()
            if name:
                return name
        except Exception as e:
            print(f"[VideoPublish] 读取 task.json 任务名失败: {e}", flush=True)
    return os.path.basename(os.path.normpath(task_dir))


def _build_draft_staging(base_name: str, video_path: str,
                         cover_landscape: str, cover_portrait: str) -> Dict[str, str]:
    """按草稿基名生成 ``{原路径: 临时路径}`` 映射（仅本地草稿模式使用）。

    命名规则：
    - 视频：``{基名}{原扩展名}``
    - 封面：横竖各一张时为 ``{基名}_封面横`` / ``{基名}_封面竖``；
      横竖共用同一张图时为 ``{基名}_封面``
    """
    staging: Dict[str, str] = {}
    if not base_name:
        return staging

    def _target(path: str, suffix: str) -> str:
        ext = os.path.splitext(path)[1] or ""
        return os.path.join(os.path.dirname(path), f"{base_name}{suffix}{ext}")

    if video_path:
        dst = _target(video_path, "")
        if dst != video_path:
            staging[video_path] = dst

    same_cover = (
        bool(cover_landscape) and bool(cover_portrait)
        and os.path.normpath(cover_landscape) == os.path.normpath(cover_portrait)
    )
    if same_cover:
        dst = _target(cover_landscape, "_封面")
        if dst != cover_landscape:
            staging[cover_landscape] = dst
    else:
        if cover_landscape:
            dst = _target(cover_landscape, "_封面横")
            if dst != cover_landscape:
                staging[cover_landscape] = dst
        if cover_portrait:
            dst = _target(cover_portrait, "_封面竖")
            if dst != cover_portrait and dst not in staging.values():
                staging[cover_portrait] = dst
    return staging


@contextmanager
def _staged_draft_files(staging: Dict[str, str]) -> Iterator[None]:
    """把待推送文件临时改名为草稿名称，退出时（含异常）恢复原名。

    同目录重命名是元数据操作，不复制文件内容：推送期间第三方拿到的
    文件名即草稿名称（方便在素材库/草稿箱里标识任务），退出后工作流内
    其他节点引用的原路径依然有效。
    """
    renamed = []
    try:
        for src, dst in staging.items():
            if not src or not dst or src == dst or not os.path.isfile(src):
                continue
            try:
                if os.path.exists(dst):
                    os.remove(dst)
                os.rename(src, dst)
                renamed.append((src, dst))
                print(f"[VideoPublish] 草稿命名: {os.path.basename(src)} -> {os.path.basename(dst)}", flush=True)
            except OSError as e:
                print(f"[VideoPublish] Warning: 草稿命名失败({src} -> {dst}): {e}", flush=True)
        yield
    finally:
        for src, dst in renamed:
            try:
                if not os.path.exists(dst):
                    continue
                if os.path.exists(src):
                    # 原名已被占用：保留草稿名文件，避免覆盖工作流产物
                    print(f"[VideoPublish] Warning: 恢复失败，原文件已存在: {src}", flush=True)
                    continue
                os.rename(dst, src)
                print(f"[VideoPublish] 草稿命名已恢复: {os.path.basename(dst)} -> {os.path.basename(src)}", flush=True)
            except OSError as e:
                print(f"[VideoPublish] Warning: 恢复原名失败({dst} -> {src}): {e}", flush=True)


class S_VideoPublish(BaseStep):
    step_id = "s_video_publish"
    step_name = "视频发布"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        path = os.path.join(task_dir, "output", f"publish_result_{node_id}.json")
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
        draft_name_mode = node_config.get("draft_name_mode", "task_name")
        if isinstance(draft_name_mode, list):
            draft_name_mode = draft_name_mode[0] if draft_name_mode else "task_name"
        draft_name_mode = str(draft_name_mode or "").strip() or "task_name"
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

        # --- 5. 读取上游 JSON（标题/描述/标签），兼容内存数据 / 文件路径 / 内联 JSON ---
        json_input = step_inputs.get("json")
        content = None
        if isinstance(json_input, (dict, list)):
            content = json_input
        elif isinstance(json_input, str) and json_input.strip():
            try:
                content = resolve_json_input(json_input, task_dir)
            except ValueError:
                content = None
        if content is not None:
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
        else:
            upstream_tags = []

        if not title:
            raise ValueError("未设置标题。请在节点配置中填写标题，或连接包含标题的JSON输入。")

        # --- 5. Apply title/description prefix/suffix ---
        print(f"[VideoPublish] BEFORE affix: title={title!r}, title_affix={title_affix!r}, title_affix_mode={title_affix_mode!r} (type={type(title_affix_mode).__name__})", flush=True)
        title = _apply_affix(title, title_affix, title_affix_mode)
        print(f"[VideoPublish] AFTER affix: title={title!r}", flush=True)
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

        # --- 8.5 草稿名称（仅本地草稿模式）：任务名 / 发布标题 ---
        draft_base = ""
        if publish_mode == "local_draft":
            name_source = title if draft_name_mode == "publish_title" else _task_name_of(task_dir)
            draft_base = _sanitize_draft_name(name_source) or "draft"

        if callback:
            mode_labels = {"publish": "发布视频", "platform_draft": "保存平台草稿", "local_draft": "保存本地草稿"}
            callback(30, f"{mode_labels.get(publish_mode, '处理')}到 {len(account_ids)} 个账号...")

        # --- 9. Execute based on publish_mode ---
        results = []
        errors = []

        if publish_mode == "local_draft":
            # Save as local draft (visible in the UI draft box)
            print(f"[VideoPublish] local_draft: video={video_path}, "
                  f"cover_l={cover_landscape or '(none)'}, cover_p={cover_portrait or '(none)'}, "
                  f"draft_base={draft_base!r}", flush=True)
            try:
                account_ids_int = [int(aid) for aid in account_ids]
                # 推送期间把文件临时改名为草稿名称，退出 with 后恢复原名，
                # 保证工作流内其他节点对原产物的引用不受影响
                staging = _build_draft_staging(draft_base, video_path, cover_landscape, cover_portrait)
                staged_video = staging.get(video_path, video_path)
                staged_l = staging.get(cover_landscape, cover_landscape)
                staged_p = staging.get(cover_portrait, cover_portrait)
                with _staged_draft_files(staging):
                    result = client.create_video_draft(
                        title=title,
                        file_paths=[staged_video],
                        account_ids=account_ids_int,
                        platform_key=platform_key,
                        description=description if description else None,
                        tags=tags,
                        thumbnail_landscape=staged_l if staged_l else None,
                        thumbnail_portrait=staged_p if staged_p else None,
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
                        print(f"[VideoPublish] Warning: account {acc_id} has no cookie file", flush=True)
                else:
                    print(f"[VideoPublish] Warning: account {acc_id} not found in account map", flush=True)

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
        output_filename = f"publish_result_{node_id}.json"
        output_path = os.path.join(output_dir, output_filename)

        publish_output = {
            "publish_params": {
                "title": title,
                "description": description,
                "tags": tags,
                "publish_mode": publish_mode,
                "draft_name_mode": draft_name_mode if publish_mode == "local_draft" else "",
                "draft_base_name": draft_base,
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

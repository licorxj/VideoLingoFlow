"""s_lcwr_watermark_removal: 调用 LCWR 本地 API 去除视频/图片中的水印与字幕。

流程：解析输入媒体 -> 复制到任务 cache 目录 -> 生成 {媒体名}_subpoint.json（区域坐标+片头片尾）
-> POST /tasks 提交 -> 轮询 /tasks/{task_id} 直到终态 -> 输出到任务 output 目录。
LCWR 本地 API 详见 docs/去水印LCWR接口API调用文档.md。
"""
import json
import os
import shutil
import time
from typing import Callable, Optional

import requests

from backend.steps.base_step import BaseStep

LCWR_DOWNLOAD_URL = "https://qinmuzhifang.feishu.cn/wiki/IkBVwfe72iEVLTkhVQ0cW0mvnBc"
DEFAULT_BASE_URL = "http://localhost:1120"
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".ts", ".m4v"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
POLL_INTERVAL = 2.0  # 秒
POLL_TIMEOUT = int(os.getenv("LCWR_POLL_TIMEOUT", str(4 * 3600)))  # 默认最长等待 4 小时


def _clamp01(value, fallback=0.0) -> float:
    try:
        v = float(value)
    except (ValueError, TypeError):
        return fallback
    return max(0.0, min(1.0, v))


def _normalize_regions(regions) -> list:
    """清洗前端传来的区域列表：{start:[x1,y1], end:[x2,y2], frame_range:[]}，坐标归一化并保证左上<=右下。"""
    if isinstance(regions, str):
        try:
            regions = json.loads(regions)
        except (ValueError, TypeError):
            regions = []
    if not isinstance(regions, list):
        return []
    cleaned = []
    for r in regions:
        if not isinstance(r, dict):
            continue
        start = r.get("start")
        end = r.get("end")
        if not isinstance(start, (list, tuple)) or not isinstance(end, (list, tuple)) or len(start) < 2 or len(end) < 2:
            continue
        x1, y1 = _clamp01(start[0]), _clamp01(start[1])
        x2, y2 = _clamp01(end[0]), _clamp01(end[1])
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        if x2 - x1 < 0.001 or y2 - y1 < 0.001:
            continue
        frame_range = r.get("frame_range") or []
        if not isinstance(frame_range, list):
            frame_range = []
        cleaned.append({"start": [x1, y1], "end": [x2, y2], "frame_range": frame_range})
    return cleaned


def _resolve_media(task_dir: str, step_inputs: dict):
    """解析输入媒体（视频优先，其次图片）。返回绝对路径或 None。"""
    candidates = []
    for key in ("video", "image"):
        raw = step_inputs.get(key, "")
        if raw:
            p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
            candidates.append(p)

    # 回退扫描任务目录中的输入媒体
    for folder in ("cache", "output"):
        base = os.path.join(task_dir, folder)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            low = name.lower()
            if low.startswith("input_video") or low.startswith("input_image"):
                candidates.append(os.path.join(base, name))
        if not candidates:
            for name in sorted(os.listdir(base)):
                ext = os.path.splitext(name)[1].lower()
                if ext in VIDEO_EXTS or ext in IMAGE_EXTS:
                    candidates.append(os.path.join(base, name))

    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


class S_LcwrWatermarkRemoval(BaseStep):
    step_id = "s_lcwr_watermark_removal"
    step_name = "LCWR 去水印"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        out_dir = os.path.join(task_dir, "output")
        if not os.path.isdir(out_dir):
            return False
        return any(f.startswith(f"lcwr_out_{node_id}.") for f in os.listdir(out_dir))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        from backend.control_plane.runtime import TaskCancelledError

        node_id = getattr(self, "_node_id", "unknown")
        cfg = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        base_url = str(cfg.get("lcwr_base_url") or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL
        model = cfg.get("model") or "bernini"
        if isinstance(model, list):
            model = model[0] if model else "bernini"
        model = str(model).strip() or "bernini"
        regions = _normalize_regions(cfg.get("regions") or [])
        skip_head_sec = float(cfg.get("skip_head_sec") or 0)
        skip_tail_sec = float(cfg.get("skip_tail_sec") or 0)
        skip_tail_mode = str(cfg.get("skip_tail_mode") or "from_end").strip() or "from_end"

        # --- 1. 解析输入媒体 ---
        media = _resolve_media(task_dir, step_inputs)
        if not media:
            raise FileNotFoundError(
                "未找到输入媒体：请为节点连接视频或图片输入（也可由输入节点提供）。"
                "若暂无视频，可在节点内通过黑帧预设框选区域。"
            )
        src_ext = os.path.splitext(media)[1].lower()
        is_video = src_ext in VIDEO_EXTS
        if not is_video and src_ext not in IMAGE_EXTS:
            raise ValueError(f"不支持的媒体格式：{src_ext}")

        if callback:
            callback(5, f"输入媒体：{os.path.basename(media)}")

        # --- 2. 复制到任务 cache 目录（保持任务目录自包含），同目录生成 _subpoint.json ---
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        source_name = os.path.basename(media)
        local_media = os.path.join(cache_dir, source_name)
        try:
            if os.path.abspath(media) != os.path.abspath(local_media):
                shutil.copy2(media, local_media)
        except OSError as exc:
            raise RuntimeError(f"复制输入媒体失败：{exc}") from exc

        media_name = os.path.splitext(source_name)[0]
        subpoint_path = os.path.join(cache_dir, f"{media_name}_subpoint.json")
        subpoint = {
            "video_path": local_media,
            "coordinates": regions,
            "skip_head_sec": skip_head_sec,
            "skip_tail_sec": skip_tail_sec,
            "skip_tail_mode": skip_tail_mode,
        }
        try:
            with open(subpoint_path, "w", encoding="utf-8") as f:
                json.dump(subpoint, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            raise RuntimeError(f"写入 _subpoint.json 失败：{exc}") from exc

        if not regions:
            raise ValueError("未框选任何去除区域：请在节点面板中通过鼠标框选水印/字幕区域（可多选）")

        # --- 3. 健康检查 ---
        if callback:
            callback(10, "检查 LCWR 服务...")
        try:
            health = requests.get(f"{base_url}/health", timeout=5)
            if health.status_code != 200:
                raise RuntimeError(f"LCWR 服务异常（HTTP {health.status_code}）")
        except requests.RequestException:
            raise RuntimeError(
                f"无法连接 LCWR 本地 API（{base_url}）。请先安装并启动 LCWR 软件：{LCWR_DOWNLOAD_URL}，"
                "然后右键「启动LCWR-API.bat」以管理员身份运行。"
            )

        # --- 4. 提交任务 ---
        out_ext = src_ext if (is_video and src_ext in VIDEO_EXTS) or (not is_video and src_ext in IMAGE_EXTS) else ".mp4"
        output_media = os.path.join(cache_dir, f"lcwr_out_{node_id}{out_ext}")
        payload = {
            "video_path": local_media,
            "model": model,
            "output_path": output_media,
        }
        if callback:
            callback(15, f"提交 LCWR 任务（模型：{model}）...")
        try:
            resp = requests.post(f"{base_url}/tasks", json=payload, timeout=30)
        except requests.RequestException as exc:
            raise RuntimeError(f"提交 LCWR 任务失败：{exc}") from exc
        if resp.status_code not in (200, 201, 202):
            detail = ""
            try:
                detail = resp.json().get("detail", "")
            except (ValueError, AttributeError):
                detail = resp.text[:200]
            raise RuntimeError(f"LCWR 提交任务失败（HTTP {resp.status_code}）：{detail}")
        try:
            lcwr_task_id = resp.json().get("task_id") or resp.json().get("id")
        except ValueError:
            lcwr_task_id = None
        if not lcwr_task_id:
            raise RuntimeError(f"LCWR 未返回任务 ID：{resp.text[:200]}")

        # --- 5. 轮询任务状态 ---
        if callback:
            callback(18, f"任务已入队：{lcwr_task_id}")
        last_pct = -1
        start_ts = time.monotonic()
        while True:
            if cancel_callback and cancel_callback():
                raise TaskCancelledError("任务已被用户取消")
            if time.monotonic() - start_ts > POLL_TIMEOUT:
                raise RuntimeError("LCWR 处理超时，已等待超过限制时长")
            try:
                st_resp = requests.get(f"{base_url}/tasks/{lcwr_task_id}", timeout=15)
                st = st_resp.json()
            except (requests.RequestException, ValueError) as exc:
                raise RuntimeError(f"查询 LCWR 任务状态失败：{exc}") from exc
            status = st.get("status")
            if status == "running":
                try:
                    pct = int(st.get("progress") or 0)
                except (ValueError, TypeError):
                    pct = 0
                if pct != last_pct and callback:
                    detail = str(st.get("progress_detail") or "")[:60]
                    callback(18 + int(pct * 0.8), f"LCWR 处理中 {pct}% {detail}".strip())
                    last_pct = pct
            elif status == "completed":
                if callback:
                    callback(100, "处理完成")
                break
            elif status == "error":
                raise RuntimeError(f"LCWR 处理失败：{st.get('message') or '未知错误'}")
            elif status == "cancelled":
                raise RuntimeError("LCWR 任务已被取消")
            time.sleep(POLL_INTERVAL)

        # --- 6. 校验输出并搬移到 output 目录 ---
        if not os.path.isfile(output_media):
            alt = st.get("output_video_path") if st else None
            if alt and os.path.isfile(alt):
                output_media = alt
            else:
                raise RuntimeError("LCWR 未生成输出文件")
        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)
        final_name = f"lcwr_out_{node_id}{os.path.splitext(output_media)[1] or out_ext}"
        final_path = os.path.join(out_dir, final_name)
        try:
            if os.path.abspath(output_media) != os.path.abspath(final_path):
                shutil.move(output_media, final_path)
        except OSError:
            shutil.copy2(output_media, final_path)

        return {
            "artifacts": [f"output/{final_name}"],
            "outputs": {
                "video": f"output/{final_name}" if is_video else "",
                "image": f"output/{final_name}" if not is_video else "",
            },
        }

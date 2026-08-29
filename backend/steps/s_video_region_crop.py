# -*- coding: utf-8 -*-
"""
视频截取区域节点（Step）

输入：
- video : 待截取区域视频（required）

输出：
- video : 截取出的区域视频（mp4，H.264；音频流拷贝保留原始数据）
- json  : 截取坐标 / 时段信息 json，供「视频区域贴片」节点贴回原视频使用

行为：
- 按配置的区域大小、区域位置、时段从原视频中截取一块矩形区域，用于局部处理。
- 区域大小可选预设比例（512x512 / 1280x760 / 1920x1080 等）或手动输入宽高。
- 区域位置为九宫格之一（左上 / 中上 / 右上 / 左中 / 居中 / 右中 / 左下 / 中下 / 右下）。
- 时段：开始时间（秒）；结束时间支持「顺数」(绝对结束时间) 或「倒数」(距视频结尾 N 秒)。
- 说明：像素级裁剪必须经视频滤镜重新编码；本节点在重新编码视频的同时用 -c:a copy
  保留原始音频流数据。当截取区域等于整帧（未真正裁剪）时，走 -c copy 流拷贝，
  完全保留原始编码与流数据。
"""
import json
import os
import subprocess

from backend.steps.base_step import BaseStep


def _to_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _ffprobe_info(video_path: str):
    """返回 (width, height, duration)；获取失败返回 (0, 0, 0.0)。"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "stream=width,height,codec_type",
             "-show_entries", "format=duration",
             "-of", "json", video_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        if r.returncode != 0:
            return 0, 0, 0.0
        info = json.loads(r.stdout)
        width = height = 0
        for st in info.get("streams", []):
            if st.get("codec_type") == "video" and not width:
                width = int(st.get("width", 0) or 0)
                height = int(st.get("height", 0) or 0)
        duration = 0.0
        fmt = info.get("format", {})
        if fmt.get("duration"):
            try:
                duration = float(fmt["duration"])
            except (TypeError, ValueError):
                duration = 0.0
        return width, height, duration
    except Exception:
        return 0, 0, 0.0


_CROP_PRESETS = {
    "512x512": (512, 512),
    "1280x760": (1280, 760),
    "1920x1080": (1920, 1080),
}

_POSITIONS = {
    "top-left":     ("left",   "top"),
    "top-center":   ("center", "top"),
    "top-right":    ("right",  "top"),
    "middle-left":  ("left",   "center"),
    "center":       ("center", "center"),
    "middle-right": ("right",  "center"),
    "bottom-left":   ("left",   "bottom"),
    "bottom-center": ("center", "bottom"),
    "bottom-right":  ("right",  "bottom"),
}


def _compute_crop_box(sw, sh, cw, ch, hx, vy):
    """根据九宫格位置计算裁剪框 (x, y, cw, ch)，并保证不超出源画面。"""
    cw = int(cw)
    ch = int(ch)
    if sw and cw > sw:
        cw = sw
    if sh and ch > sh:
        ch = sh
    x_left, x_center, x_right = 0, max(0, (sw - cw) // 2), max(0, sw - cw)
    y_top, y_center, y_bottom = 0, max(0, (sh - ch) // 2), max(0, sh - ch)
    x = {"left": x_left, "center": x_center, "right": x_right}[hx]
    y = {"top": y_top, "center": y_center, "bottom": y_bottom}[vy]
    return x, y, cw, ch


class S_VideoRegionCrop(BaseStep):
    step_id = "video_region_crop"
    step_name = "视频截取区域"
    dependencies = []

    # ------------------------------------------------------------------
    # 输入解析
    # ------------------------------------------------------------------
    def _resolve_video_path(self, task_dir: str) -> str:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        raw = step_inputs.get("video", "")
        if raw:
            p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
            if os.path.isfile(p):
                return p
        cache_dir = os.path.join(task_dir, "cache")
        if os.path.isdir(cache_dir):
            for name in sorted(os.listdir(cache_dir)):
                if name.startswith("input_video") or name.lower().endswith(
                    (".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv")
                ):
                    return os.path.join(cache_dir, name)
        return ""

    # ------------------------------------------------------------------
    # 断点 / 产物管理
    # ------------------------------------------------------------------
    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        cache_dir = os.path.join(task_dir, "cache")
        if not os.path.isdir(cache_dir):
            return False
        return os.path.isfile(os.path.join(cache_dir, f"video_region_crop_{node_id}.mp4"))

    def validate_inputs(self, task_dir: str) -> bool:
        return bool(self._resolve_video_path(task_dir))

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, task_dir, callback=None, cancel_callback=None):
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}

        # --- 1. 读取配置 ---
        crop_size = node_config.get("crop_size", "1280x760")
        if crop_size == "custom":
            cw = int(_to_float(node_config.get("crop_width"), 0))
            ch = int(_to_float(node_config.get("crop_height"), 0))
        else:
            cw, ch = _CROP_PRESETS.get(crop_size, (1280, 760))
        if cw <= 0 or ch <= 0:
            raise ValueError("切取区域大小无效，请检查预设或手动输入的宽高。")

        pos = node_config.get("crop_position", "center")
        hx, vy = _POSITIONS.get(pos, ("center", "center"))

        start = max(0.0, _to_float(node_config.get("start_time"), 0.0))
        end_mode = node_config.get("end_mode", "absolute")

        # --- 2. 解析输入视频 ---
        video_path = self._resolve_video_path(task_dir)
        if not video_path:
            raise FileNotFoundError("未找到输入视频：请连接视频输入端口，或确保 cache 中存在视频文件")

        sw, sh, src_duration = _ffprobe_info(video_path)
        if sw <= 0 or sh <= 0:
            raise ValueError("无法获取视频分辨率，请确认视频文件有效。")
        if src_duration <= 0:
            src_duration = 0.0

        if callback:
            try:
                callback(5, f"源视频: {sw}x{sh}, 时长 {src_duration:.1f}s")
            except Exception:
                pass

        # --- 3. 计算裁剪框 ---
        x, y, cw, ch = _compute_crop_box(sw, sh, cw, ch, hx, vy)

        # --- 4. 计算时段 ---
        if end_mode == "countdown":
            cd = _to_float(node_config.get("end_countdown"), 0.0)
            end = (src_duration - cd) if cd > 0 else src_duration
        else:
            et = _to_float(node_config.get("end_time"), 0.0)
            end = et if et > 0 else src_duration
        end = max(start, min(end, src_duration)) if src_duration else end
        duration = max(0.0, end - start)
        if duration <= 0:
            raise ValueError("截取时段无效：结束时间需大于开始时间。")

        # --- 5. 执行 ffmpeg 裁剪 ---
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        out_name = f"video_region_crop_{node_id}.mp4"
        out_path = os.path.join(cache_dir, out_name)
        rel_video = os.path.join("cache", out_name)

        # 整帧（未真正裁剪）→ 流拷贝，保留原始编码与流数据
        full_frame = (cw >= sw and ch >= sh)
        if full_frame:
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{start:.3f}", "-i", video_path,
                "-t", f"{duration:.3f}",
                "-c", "copy", "-avoid_negative_ts", "make_zero",
                out_path,
            ]
        else:
            vf = f"crop={cw}:{ch}:{x}:{y}"
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{start:.3f}", "-i", video_path,
                "-t", f"{duration:.3f}",
                "-vf", vf,
                "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
                "-c:a", "copy", "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                out_path,
            ]

        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("用户取消截取")

        if callback:
            try:
                callback(20, f"截取区域: {cw}x{ch} @ ({x},{y}), 时段 {start:.1f}s~{end:.1f}s")
            except Exception:
                pass

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        except FileNotFoundError:
            raise RuntimeError("未找到 ffmpeg，请先安装 ffmpeg 并加入 PATH。")
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg 截取区域失败: {r.stderr[-800:]}")

        # --- 6. 写出坐标 JSON（供「视频区域贴合」节点使用）---
        info = {
            "source_width": sw,
            "source_height": sh,
            "crop_width": cw,
            "crop_height": ch,
            "x": x,
            "y": y,
            "position": pos,
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "duration": round(duration, 3),
            "full_frame": full_frame,
            "cropped_video": rel_video,
            "node_id": node_id,
        }
        rel_json = os.path.join("cache", f"video_region_crop_{node_id}.json")
        abs_json = os.path.join(task_dir, rel_json)
        with open(abs_json, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)

        if callback:
            try:
                callback(100, f"完成: {out_name}")
            except Exception:
                pass

        return {
            "artifacts": [rel_video, rel_json],
            "outputs": {
                "video": rel_video,
                "json": rel_json,
            },
        }

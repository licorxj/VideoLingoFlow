# -*- coding: utf-8 -*-
"""
视频区域贴片节点（Step）

输入：
- main_video  : 主视频（背景视频，required）
- patch_video : 贴片视频（来自「视频截取区域」节点的 video 输出，required）
- patch_json  : 贴片坐标信息 json（来自「视频截取区域」节点的 json 输出，required）

输出：
- video : 贴合后的视频（mp4，H.264；主视频音频流拷贝保留原始数据）

行为：
- 按坐标 json 中的 x/y/crop_width/crop_height，将贴片视频叠加到主视频对应区域。
- 贴片视频大于贴片区域时，自动缩放到区域大小；不大于时按原尺寸叠加（不放大）。
- 贴合必然经过滤镜重编码，输出统一编码为 H.264，因此主/贴片编码差异被自动统一；
  主视频音频以 -c:a copy 保留原始流数据。
- 时段：默认「来自上游配置 json」（取 json.start_time）；也可切「自由输入起始点」手动指定。
  贴片仅在 [起始点, 起始点+贴片时长] 窗口内显示，其余时段仅显示主视频。
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


class S_VideoRegionComposite(BaseStep):
    step_id = "video_region_composite"
    step_name = "视频区域贴片"
    dependencies = []

    # ------------------------------------------------------------------
    # 输入解析
    # ------------------------------------------------------------------
    def _resolve(self, task_dir: str, port: str) -> str:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        raw = step_inputs.get(port, "")
        if raw:
            p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
            if os.path.isfile(p):
                return p
        return ""

    # ------------------------------------------------------------------
    # 断点 / 产物管理
    # ------------------------------------------------------------------
    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        cache_dir = os.path.join(task_dir, "cache")
        if not os.path.isdir(cache_dir):
            return False
        return os.path.isfile(os.path.join(cache_dir, f"video_region_composite_{node_id}.mp4"))

    def validate_inputs(self, task_dir: str) -> bool:
        return bool(self._resolve(task_dir, "main_video") and self._resolve(task_dir, "patch_video"))

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, task_dir, callback=None, cancel_callback=None):
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}

        main_path = self._resolve(task_dir, "main_video")
        patch_path = self._resolve(task_dir, "patch_video")
        json_path = self._resolve(task_dir, "patch_json")
        if not main_path:
            raise FileNotFoundError("未连接主视频输入。")
        if not patch_path:
            raise FileNotFoundError("未连接贴片视频输入。")
        if not json_path:
            raise FileNotFoundError("未连接贴片坐标 json 输入。")

        # --- 1. 读取坐标 json ---
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                coord = json.load(f)
        except Exception as e:
            raise ValueError(f"贴片坐标 json 解析失败: {e}")
        try:
            x = int(coord["x"])
            y = int(coord["y"])
            cw = int(coord["crop_width"])
            ch = int(coord["crop_height"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("贴片坐标 json 缺少有效的 x / y / crop_width / crop_height。")
        if cw <= 0 or ch <= 0:
            raise ValueError("贴片区域大小无效（crop_width / crop_height 必须为正）。")

        # --- 2. 解析视频信息 ---
        mw, mh, m_dur = _ffprobe_info(main_path)
        pw, ph, p_dur = _ffprobe_info(patch_path)
        if mw <= 0 or mh <= 0:
            raise ValueError("无法获取主视频分辨率。")

        if callback:
            try:
                callback(10, f"主视频 {mw}x{mh}, 贴片 {pw}x{ph}, 区域 {cw}x{ch} @ ({x},{y})")
            except Exception:
                pass

        # --- 3. 计算贴合时段 ---
        time_source = node_config.get("time_source", "from_json")
        if time_source == "manual":
            start = max(0.0, _to_float(node_config.get("manual_start"), 0.0))
        else:
            start = max(0.0, _to_float(coord.get("start_time"), 0.0))

        patch_dur = p_dur if p_dur > 0 else _to_float(coord.get("duration"), 0.0)
        end = start + patch_dur
        if m_dur > 0:
            end = min(end, m_dur)

        # --- 4. 构造 filter_complex ---
        # 贴片大于区域才缩放（不放大）；否则原尺寸叠加
        if pw > cw or ph > ch:
            vinput = f"[1:v]scale={cw}:{ch}[ovl]"
        else:
            vinput = "[1:v]null[ovl]"
        overlay = (
            f"[0:v][ovl]overlay={x}:{y}"
            f":enable='between(t,{start:.3f},{end:.3f})'[v]"
        )
        filter_complex = vinput + ";" + overlay

        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        out_name = f"video_region_composite_{node_id}.mp4"
        out_path = os.path.join(cache_dir, out_name)
        rel_video = os.path.join("cache", out_name)

        cmd = [
            "ffmpeg", "-y",
            "-i", main_path,
            "-i", patch_path,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
            "-c:a", "copy", "-movflags", "+faststart",
            out_path,
        ]

        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("用户取消贴片")

        if callback:
            try:
                callback(30, f"贴合窗口: {start:.1f}s ~ {end:.1f}s")
            except Exception:
                pass

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        except FileNotFoundError:
            raise RuntimeError("未找到 ffmpeg，请先安装 ffmpeg 并加入 PATH。")
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg 视频区域贴片失败: {r.stderr[-800:]}")

        if callback:
            try:
                callback(100, f"完成: {out_name}")
            except Exception:
                pass

        return {
            "artifacts": [rel_video],
            "outputs": {"video": rel_video},
        }

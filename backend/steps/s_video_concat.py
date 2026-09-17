"""s_video_concat: 视频拼接节点。

将「主视频 / 片段1~3 / 封面图」按前端配置一次性拼装为单个 ffmpeg 命令并一次性完成：
- segment_order: 视频片段拼接顺序（主视频、片段1/2/3 的排序）
- scale_mode: 片段尺寸缩放方式（stretch 拉伸 / crop 裁切填充）
- cover_position / cover_duration: 封面图插入位置（开头/结尾）与停留时长（none 不插入）
所有视频统一缩放到首个参考视频的分辨率与帧率后拼接，封面图以静帧形式插入，
输出拼接后的单个视频文件。
"""
import json
import os
import shutil
import subprocess
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.utils.video_ops import run_ffmpeg_with_progress
from backend.utils.video_encoder import build_video_encode_args


_FORMAT_EXT = {"mp4": "mp4", "mkv": "mkv", "webm": "webm", "mov": "mov", "avi": "avi"}
_SEGMENT_PORTS = ["main", "segment1", "segment2", "segment3"]
_SEGMENT_LABELS = {
    "main": "主视频",
    "segment1": "片段1",
    "segment2": "片段2",
    "segment3": "片段3",
}


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def _resolve_path(raw, task_dir: str) -> Optional[str]:
    """支持 str / dict{path} / list[...] → 首个真实存在的文件路径。"""
    candidates: list = []
    if isinstance(raw, str):
        if raw:
            candidates = [raw]
    elif isinstance(raw, dict):
        for k in ("path", "file", "file_path", "url"):
            v = raw.get(k)
            if isinstance(v, str) and v:
                candidates.append(v)
                break
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, str) and item:
                candidates.append(item)
            elif isinstance(item, dict):
                for k in ("path", "file", "file_path", "url"):
                    v = item.get(k)
                    if isinstance(v, str) and v:
                        candidates.append(v)
                        break
    for cand in candidates:
        p = cand if os.path.isabs(cand) else os.path.join(task_dir, cand)
        if os.path.isfile(p):
            return p
    return None


def _probe(path: str) -> dict:
    """用 ffprobe 获取宽高、时长、帧率、是否含音轨。"""
    info = {"width": 0, "height": 0, "duration": 0.0, "fps": 30.0, "has_audio": False}
    exe = _ffprobe()
    if not exe:
        return info
    try:
        cmd = [exe, "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", path]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        data = json.loads(res.stdout or "{}")
        if "format" in data and data["format"].get("duration"):
            try:
                info["duration"] = float(data["format"]["duration"])
            except (TypeError, ValueError):
                info["duration"] = 0.0
        vw = vh = 0
        for s in data.get("streams", []):
            if s.get("codec_type") == "video" and vw == 0:
                try:
                    vw = int(s.get("width", 0) or 0)
                except (TypeError, ValueError):
                    vw = 0
                try:
                    vh = int(s.get("height", 0) or 0)
                except (TypeError, ValueError):
                    vh = 0
                r = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/0"
                try:
                    num, den = r.split("/")
                    fps = float(num) / float(den) if float(den) else 0.0
                    if fps > 0:
                        info["fps"] = fps
                except (ValueError, ZeroDivisionError):
                    pass
            elif s.get("codec_type") == "audio":
                info["has_audio"] = True
        if vw and vh:
            info["width"], info["height"] = vw, vh
    except Exception:
        pass
    return info


class S_VideoConcat(BaseStep):
    step_id = "video_concat"
    step_name = "视频拼接"
    dependencies = []

    # ------------------------------------------------------------------
    # 断点 / 输入校验
    # ------------------------------------------------------------------
    def check_artifact(self, task_dir: str) -> bool:
        output_dir = os.path.join(task_dir, "output")
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        prefix = f"video_concat{node_suffix}."
        return os.path.isdir(output_dir) and any(
            name.startswith(prefix) for name in os.listdir(output_dir)
        )

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        for port in _SEGMENT_PORTS + ["cover"]:
            if _resolve_path(step_inputs.get(port), task_dir):
                return True
        return False

    # ------------------------------------------------------------------
    # filter_complex 拼装
    # ------------------------------------------------------------------
    @staticmethod
    def _scale_expr(scale_mode: str, w: int, h: int) -> str:
        if scale_mode == "crop":
            return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
        return f"scale={w}:{h}:force_original_aspect_ratio=disable"

    def _build_filter(self, clips: list, scale_mode: str, w: int, h: int, fps: float) -> str:
        """根据 clips（已含 idx 顺序）生成 filter_complex 字符串。"""
        parts: list = []
        vlabels: list = []
        alabels: list = []
        scale_expr = self._scale_expr(scale_mode, w, h)
        for c in clips:
            idx = c["idx"]
            if c["kind"] == "video":
                parts.append(
                    f"[{idx}:v]{scale_expr},setsar=1,fps={fps},format=yuv420p[v{idx}]"
                )
                if c["has_audio"]:
                    parts.append(
                        f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo[a{idx}]"
                    )
                else:
                    parts.append(
                        f"anullsrc=r=48000:cl=stereo:d={c['duration']:.3f}[a{idx}]"
                    )
            else:  # 封面静帧
                parts.append(
                    f"[{idx}:v]{scale_expr},setsar=1,fps={fps},format=yuv420p,"
                    f"trim=duration={c['duration']:.3f},setpts=PTS-STARTPTS[v{idx}]"
                )
                parts.append(
                    f"anullsrc=r=48000:cl=stereo:d={c['duration']:.3f}[a{idx}]"
                )
            vlabels.append(f"[v{idx}]")
            alabels.append(f"[a{idx}]")
        # concat 滤镜要求输入按「视频0、音频0、视频1、音频1…」交错排列
        interleaved = []
        for i in range(len(vlabels)):
            interleaved.append(vlabels[i])
            interleaved.append(alabels[i])
        n = len(vlabels)
        parts.append("".join(interleaved) + f"concat=n={n}:v=1:a=1[outv][outa]")
        return ";".join(parts)

    # ------------------------------------------------------------------
    # 带进度 / 取消的 ffmpeg 执行
    # ------------------------------------------------------------------
    def _run_ffmpeg(self, cmd, duration, callback, cancel_callback, timeout=86400):
        run_ffmpeg_with_progress(
            cmd, duration, callback, cancel_callback, timeout=timeout, label="拼接"
        )

    # ------------------------------------------------------------------
    # 资源保护（防「拼接长高清视频吃满内存/CPU」）
    # ------------------------------------------------------------------
    def _limits(self, node_config: dict) -> tuple:
        """解析资源限制：拼接策略 / 线程数上限 / 最长时长(分钟)。"""
        strategy = str(node_config.get("concat_strategy") or "low_memory").strip() or "low_memory"
        try:
            threads = int(node_config.get("ffmpeg_threads") or 0)
        except (TypeError, ValueError):
            threads = 0
        try:
            max_minutes = int(node_config.get("max_duration_minutes") or 0)
        except (TypeError, ValueError):
            max_minutes = 0
        return strategy, max(0, min(threads, 64)), max(0, max_minutes)

    @staticmethod
    def _resource_args(threads: int, mux_queue: int = 4096) -> list:
        """限制 ffmpeg 资源占用的通用参数。

        * ``-threads``：限制编解码线程数，避免多段高清拼接吃满全部 CPU；
        * ``-max_muxing_queue_size``：限制封装队列长度，防止多路输入 / 各段时长
          不均等时封装队列无界增长导致内存暴涨（ffmpeg 经典 OOM 来源）。
        """
        args = ["-max_muxing_queue_size", str(mux_queue)]
        if threads > 0:
            args = ["-threads", str(threads), *args]
        return args

    @staticmethod
    def _ensure_disk_space(target_dir: str, needed_bytes: float, margin: float = 1.3) -> None:
        """产物落地前检查磁盘余量，不足时快速失败并给出可执行提示。"""
        if needed_bytes <= 0:
            return
        try:
            free = shutil.disk_usage(target_dir).free
        except OSError:
            return
        if free < needed_bytes * margin:
            raise RuntimeError(
                f"磁盘可用空间不足：本次拼接预计需要约 {needed_bytes * margin / 1048576:.0f} MB，"
                f"当前仅剩 {free / 1048576:.0f} MB，已中止以免写坏输出。"
                f"请清理磁盘后重试，或改用较小的分辨率 / 时长。"
            )

    def _standardize_clip(self, clip: dict, w: int, h: int, fps: float,
                          scale_mode: str, out_path: str, threads: int) -> list:
        """单个片段的标准化转码命令（低内存模式用）。

        所有中间文件必须**参数完全一致**（编码器 / profile / 分辨率 / 帧率 /
        像素格式 / 时间基 / 音频采样率与声道），否则 concat demuxer 无法流拷贝。
        无音轨片段统一补静音轨，避免「有的段有音轨、有的没有」导致拼接失败。
        """
        scale_expr = self._scale_expr(scale_mode, w, h)
        duration = float(clip.get("duration") or 0)
        is_image = clip["kind"] == "image"
        cmd = [_ffmpeg(), "-y"]
        if is_image:
            # 静帧输入统一帧率与时长，避免 -loop 1 无限产帧
            cmd += ["-loop", "1", "-framerate", f"{fps}", "-t", f"{duration:.3f}"]
        cmd += ["-i", clip["path"]]
        need_silence = is_image or not clip.get("has_audio")
        if need_silence:
            cmd += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        cmd += ["-vf", f"{scale_expr},setsar=1,fps={fps},format=yuv420p", "-map", "0:v:0"]
        if need_silence:
            cmd += ["-map", "1:a:0", "-shortest"]
        else:
            cmd += ["-map", "0:a:0", "-af", "aresample=48000,aformat=channel_layouts=stereo"]
        # 全局「使用显卡加速(NVENC)」开启时自动改用 h264_nvenc（与单次滤镜模式一致）
        cmd += [
            *build_video_encode_args("libx264", crf=23, preset="veryfast"),
            "-pix_fmt", "yuv420p",
            "-video_track_timescale", "90000",
            "-c:a", "aac", "-ar", "48000", "-ac", "2",
            *self._resource_args(threads),
            "-progress", "pipe:1", "-nostats",
            out_path,
        ]
        return cmd

    def _concat_by_copy(self, part_paths: list, list_path: str, output_path: str,
                        total_dur: float, callback, cancel_callback, threads: int) -> None:
        """用 concat demuxer 流拷贝合并中间文件（不重新编码，几乎不占资源）。"""
        lines = []
        for path in part_paths:
            escaped = str(path).replace("\\", "/").replace("'", r"'\''")
            lines.append(f"file '{escaped}'")
        with open(list_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        cmd = [
            _ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy",
            *self._resource_args(threads),
            "-progress", "pipe:1", "-nostats",
            output_path,
        ]
        self._run_ffmpeg(cmd, total_dur, callback, cancel_callback)

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, task_dir, callback=None, cancel_callback=None):
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        order = node_config.get("segment_order") or list(_SEGMENT_PORTS)
        if not isinstance(order, list):
            order = list(_SEGMENT_PORTS)
        scale_mode = node_config.get("scale_mode") or "stretch"
        cover_position = node_config.get("cover_position") or "none"
        try:
            cover_duration = float(node_config.get("cover_duration", 3) or 3)
        except (ValueError, TypeError):
            cover_duration = 3.0
        cover_duration = max(0.1, min(60.0, cover_duration))
        output_format = (node_config.get("output_format") or "mp4").strip().lower() or "mp4"
        ext = _FORMAT_EXT.get(output_format, "mp4")

        # 1) 解析视频片段（按排序）
        video_clips = []
        for port in order:
            if port not in _SEGMENT_PORTS:
                continue
            p = _resolve_path(step_inputs.get(port), task_dir)
            if p:
                meta = _probe(p)
                video_clips.append({"path": p, "meta": meta})

        # 2) 解析封面图
        cover_path = (
            _resolve_path(step_inputs.get("cover"), task_dir)
            if cover_position in ("start", "end") else None
        )

        if not video_clips and not cover_path:
            raise FileNotFoundError("未找到任何有效输入：请连接主视频/片段/封面图中的至少一个")

        # 3) 探测目标分辨率与帧率（首个视频，否则封面图）
        target = None
        for vc in video_clips:
            m = vc["meta"]
            if m["width"] and m["height"]:
                target = m
                break
        if target is None and cover_path:
            target = _probe(cover_path)
        if target is None or not target["width"] or not target["height"]:
            raise RuntimeError("无法探测参考视频/图片尺寸，无法确定输出分辨率")
        out_w, out_h = target["width"], target["height"]
        fps = target.get("fps") or 30.0

        # 4) 组装最终 clips 顺序（含封面插入）
        clips: list = []
        for vc in video_clips:
            m = vc["meta"]
            clips.append({
                "kind": "video",
                "path": vc["path"],
                "duration": m["duration"] or 1.0,
                "has_audio": m["has_audio"],
            })
        if cover_path and cover_position in ("start", "end"):
            cover_clip = {
                "kind": "image",
                "path": cover_path,
                "duration": cover_duration,
                "has_audio": False,
            }
            if cover_position == "start":
                clips.insert(0, cover_clip)
            else:
                clips.append(cover_clip)

        for i, c in enumerate(clips):
            c["idx"] = i

        total_dur = sum(c["duration"] for c in clips)

        # 5) 资源保护预检：规模上限 + 磁盘余量（快速失败，避免跑一半把机器拖垮）
        strategy, threads, max_minutes = self._limits(node_config)
        if max_minutes > 0 and total_dur > max_minutes * 60:
            raise RuntimeError(
                f"拼接总时长约 {total_dur / 60:.1f} 分钟，超过节点配置的上限 {max_minutes} 分钟。"
                f"如确需处理长视频，请在节点「最长时长上限」中调大或设为 0（不限制）。"
            )
        low_memory = strategy != "single_pass"
        input_bytes = sum(
            os.path.getsize(c["path"]) for c in clips if os.path.isfile(c["path"])
        )
        # 低内存模式还要落中间文件，磁盘需求更高
        self._ensure_disk_space(task_dir, input_bytes * (1.5 if low_memory else 0.5))

        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"video_concat{node_suffix}.{ext}")
        output_rel = f"output/video_concat{node_suffix}.{ext}"

        if callback:
            try:
                callback(5, f"开始拼接（{len(clips)} 段，{out_w}x{out_h}，缩放={scale_mode}，"
                           f"策略={'低内存' if low_memory else '单次滤镜'}）")
            except Exception:
                callback(5, "开始拼接")

        if low_memory:
            # 低内存模式：逐段标准化转码（内存峰值 ≈ 单段）→ concat 流拷贝（零编码）。
            # 避免 filter_complex 同时解码全部输入，这是长高清视频吃满内存的主因。
            cache_dir = os.path.join(task_dir, "cache")
            os.makedirs(cache_dir, exist_ok=True)
            part_paths: list = []
            for index, clip in enumerate(clips):
                part_path = os.path.join(cache_dir, f"video_concat{node_suffix}_part{index:02d}.mp4")
                if callback:
                    try:
                        callback(int(5 + 85 * index / len(clips)),
                                 f"标准化片段 {index + 1}/{len(clips)}")
                    except Exception:
                        pass
                part_cmd = self._standardize_clip(
                    clip, out_w, out_h, fps, scale_mode, part_path, threads
                )
                self._run_ffmpeg(part_cmd, clip["duration"], None, cancel_callback)
                if not os.path.exists(part_path) or os.path.getsize(part_path) == 0:
                    raise RuntimeError(f"第 {index + 1} 个片段标准化失败，未生成有效中间文件")
                part_paths.append(part_path)
            list_path = os.path.join(cache_dir, f"concat_list{node_suffix}.txt")
            self._concat_by_copy(
                part_paths, list_path, output_path, total_dur, callback, cancel_callback, threads
            )
            # 拼接成功后回收中间文件，避免占满磁盘（失败时保留，便于排查）
            for path in part_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass
            try:
                os.remove(list_path)
            except OSError:
                pass
        else:
            # 单次滤镜模式（仅适合短片段）：一次命令完成，避免多次转码
            filter_str = self._build_filter(clips, scale_mode, out_w, out_h, fps)
            cmd = [_ffmpeg(), "-y"]
            for c in clips:
                if c["kind"] == "image":
                    # 静帧限定帧率与时长，避免 -loop 1 无限产帧
                    cmd += ["-loop", "1", "-framerate", f"{fps}", "-t", f"{c['duration']:.3f}"]
                cmd += ["-i", c["path"]]
            cmd += [
                "-filter_complex", filter_str,
                "-map", "[outv]", "-map", "[outa]",
                # 全局「使用显卡加速 (NVIDIA NVENC)」开启时自动改用 h264_nvenc
                *build_video_encode_args("libx264", crf=23, preset="veryfast"),
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000",
                *self._resource_args(threads),
                "-progress", "pipe:1", "-nostats",
                output_path,
            ]
            self._run_ffmpeg(cmd, total_dur, callback, cancel_callback)

        if not os.path.exists(output_path):
            raise RuntimeError("视频拼接完成但未找到输出文件: " + output_path)

        if callback:
            try:
                callback(100, "视频拼接完成")
            except Exception:
                pass
        return {
            "artifacts": [output_rel],
            "outputs": {"video": output_rel},
        }

"""基于 OpenCV 的视频局部变速工具。

处理流程（异步流水线，低内存占用）：
1. 异步预读取下一段帧（后台线程），同时处理写入当前段
2. 对当前段执行变速处理（跳帧/光流插针），逐帧写入输出视频
3. 写入完成立即释放当前段内存，然后处理下一段
4. 光流法插针使用多线程加速
5. 帧写入优先用 ffmpeg(libx264) 管道编码，OpenCV mp4v 仅作兜底
   （mp4v 编码质量低，变速跳帧后帧间预测失败会导致花屏）
"""
import os
import gc
import shutil
import subprocess
import threading
import cv2
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional, Callable

from backend.utils.video_speed_manifest import VideoSpeedManifest, VideoSpeedSegmentManifest


# ───────────────── 光流插针 ─────────────────

def interpolate_frame(prev_frame: np.ndarray, next_frame: np.ndarray, alpha: float) -> np.ndarray:
    """使用光流法在两帧之间插值生成中间帧。"""
    if alpha <= 0.01:
        return prev_frame.copy()
    if alpha >= 0.99:
        return next_frame.copy()

    gray_prev = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    gray_next = cv2.cvtColor(next_frame, cv2.COLOR_BGR2GRAY)

    flow = cv2.calcOpticalFlowFarneback(
        gray_prev, gray_next, None,
        pyr_scale=0.5, levels=3, winsize=15,
        iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
    )

    h, w = prev_frame.shape[:2]
    flow_map = np.column_stack([
        np.repeat(np.arange(w), h),
        np.tile(np.arange(h), w),
    ]).reshape(h, w, 2).astype(np.float32)

    flow_fwd = (flow_map + flow * alpha).astype(np.float32)
    flow_bwd = (flow_map + flow * (alpha - 1.0)).astype(np.float32)

    warped_prev = cv2.remap(prev_frame, flow_fwd, None, cv2.INTER_LINEAR)
    warped_next = cv2.remap(next_frame, flow_bwd, None, cv2.INTER_LINEAR)

    return cv2.addWeighted(warped_prev, 1.0 - alpha, warped_next, alpha, 0)


# ───────────────── 帧写入器（ffmpeg libx264 优先，cv2 mp4v 兜底） ─────────────────

class _FFmpegPipeWriter:
    """通过管道把原始帧交给 ffmpeg 编码为 H.264。

    接口与 cv2.VideoWriter 对齐（isOpened / write / release），
    每次 write 严格对应一帧输入，保证帧数/时间戳与上游逻辑一致。
    """

    def __init__(self, output_path: str, fps: float, width: int, height: int):
        self._proc: Optional[subprocess.Popen] = None
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return
        cmd = [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{int(width)}x{int(height)}",
            "-pix_fmt", "bgr24",
            "-r", f"{fps:.6f}",
            "-i", "pipe:0",
            "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path,
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._proc = None

    def isOpened(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and self._proc.stdin is not None

    def write(self, frame: np.ndarray) -> None:
        if not self.isOpened():
            raise RuntimeError("ffmpeg 帧写入器已关闭，视频编码失败")
        self._proc.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())

    def release(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except OSError:
            pass
        try:
            ret = self._proc.wait(timeout=600)
            if ret != 0:
                print(f"  ⚠ ffmpeg 视频编码退出码: {ret}")
        except subprocess.TimeoutExpired:
            self._proc.kill()
        finally:
            self._proc = None


def _create_frame_writer(output_path: str, fps: float, width: int, height: int):
    """创建帧写入器：优先 ffmpeg(libx264)，失败回退 cv2 VideoWriter(mp4v)。

    cv2.VideoWriter 的 mp4v(MPEG-4 Part 2) 编码质量低，且变速跳帧后
    帧间预测误差会在变速片段内产生马赛克/花屏；改用 libx264 可消除。
    """
    if width % 2 == 0 and height % 2 == 0:
        writer = _FFmpegPipeWriter(output_path, fps, width, height)
        if writer.isOpened():
            print("  - 帧写入器: ffmpeg(libx264)")
            return writer
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, fps, (int(width), int(height)))
    if writer.isOpened():
        print("  - 帧写入器: OpenCV(mp4v) 兜底（画质较低）")
    return writer


# ───────────────── 逐段变速处理（写入器直接写入，不缓存） ─────────────────

def _read_segment_frames(
    cap: cv2.VideoCapture, start_frame: int, end_frame: int, batch_size: int
) -> np.ndarray:
    """从 VideoCapture 中读取指定帧范围，返回 (N, H, W, 3) 数组。"""
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    n_frames = end_frame - start_frame
    batch_list = []
    remaining = n_frames
    while remaining > 0:
        cnt = min(batch_size, remaining)
        frames_batch = []
        for _ in range(cnt):
            ret, frame = cap.read()
            if not ret:
                break
            frames_batch.append(frame)
        if not frames_batch:
            break
        batch_list.append(np.stack(frames_batch))
        remaining -= len(frames_batch)
    if batch_list:
        return np.concatenate(batch_list, axis=0)
    return np.empty((0,), dtype=np.uint8)


def _process_and_write_segment(
    writer: cv2.VideoWriter,
    frames: np.ndarray,
    task_type: str,
    speed_ratio: float,
    output_count: int,
    num_workers: int,
) -> int:
    """处理一个片段的帧并直接写入 VideoWriter，返回写入帧数。"""
    n_input = len(frames)
    if n_input == 0 or output_count <= 0:
        return 0

    if task_type == "normal":
        # 正常片段：直接逐帧写入，无需复制
        for i in range(n_input):
            writer.write(frames[i])
        return n_input

    # speed 片段：计算输出帧的源位置映射
    output_frames = []
    if speed_ratio >= 1.0:
        # 加速：跳帧（不需要额外内存分配，直接引用源帧切片）
        for i in range(output_count):
            src_pos = i * (n_input - 1) / max(output_count - 1, 1) if output_count > 1 else 0
            src_idx = min(int(src_pos), n_input - 1)
            output_frames.append(("copy", src_idx))
    else:
        # 减速：可能需要光流插针
        for i in range(output_count):
            src_pos = i * (n_input - 1) / max(output_count - 1, 1) if output_count > 1 else 0
            src_idx = int(src_pos)
            alpha = src_pos - src_idx
            if src_idx >= n_input - 1:
                output_frames.append(("copy", n_input - 1))
            elif alpha < 0.01:
                output_frames.append(("copy", src_idx))
            else:
                output_frames.append(("interp", src_idx, alpha))

    # 多线程处理需要插针的帧
    interp_items = [(i, item) for i, item in enumerate(output_frames) if item[0] == "interp"]
    interp_results = {}

    if interp_items and num_workers > 1:
        def _do_interp(item):
            idx, (_, src_idx, alpha) = item
            return idx, interpolate_frame(frames[src_idx], frames[src_idx + 1], alpha)

        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = [pool.submit(_do_interp, item) for item in interp_items]
            for f in as_completed(futures):
                idx, frame = f.result()
                interp_results[idx] = frame

    # 顺序写入
    written = 0
    for i, item in enumerate(output_frames):
        if item[0] == "copy":
            writer.write(frames[item[1]])
        else:
            if i in interp_results:
                writer.write(interp_results[i])
            else:
                # 单线程回退
                _, src_idx, alpha = item
                frame = interpolate_frame(frames[src_idx], frames[src_idx + 1], alpha)
                writer.write(frame)
        written += 1

    return written


# ───────────────── 主入口 ─────────────────

def adjust_video_speed_segments(
    input_path: str,
    output_path: str,
    speed_segments: List[Tuple],
    progress_callback: Optional[Callable[[int, str], None]] = None,
    batch_size: int = 64,
    num_workers: int = 0,
    return_manifest: bool = False,
) -> Optional[str]:
    """OpenCV 读取 + 局部变速，ffmpeg(libx264) 编码输出（无 ffmpeg 时回退 OpenCV mp4v）。

    异步流水线：预读取下一段帧（后台线程）同时处理写入当前段，写完立即释放内存。

    Args:
        input_path: 输入视频路径
        output_path: 输出视频路径
        speed_segments: 变速片段列表 [(start_sec, end_sec, speed_ratio), ...]
        progress_callback: 可选的进度回调 callback(percent, message)
        batch_size: 帧读取批次大小
        num_workers: 处理线程数，0=CPU核心数的一半

    Returns:
        输出视频路径，失败返回 None
    """
    if num_workers <= 0:
        num_workers = max(1, (os.cpu_count() or 4) // 2)

    # ── 打开输入视频 ──
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise Exception(f"无法打开视频: {input_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_input_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_duration = total_input_frames / fps if fps > 0 else 0

    if fps <= 0 or total_input_frames <= 0:
        cap.release()
        raise Exception("无法读取视频参数")

    # ── 构建处理任务列表 ──
    speed_segments = sorted(speed_segments, key=lambda x: x[0])
    tasks = []  # [{type, start_frame, end_frame, output_count, ratio}, ...]
    cur_time = 0.0

    for item_idx, item in enumerate(speed_segments):
        start, end, ratio = item[:3]
        seg_index = item[3] if len(item) > 3 else item_idx
        if start > cur_time + 0.0001:
            sf = round(cur_time * fps)
            ef = round(start * fps)
            if ef > sf:
                tasks.append({
                    "type": "normal",
                    "start_frame": sf, "end_frame": ef,
                    "output_count": ef - sf, "ratio": 1.0,
                    "source_start": cur_time, "source_end": start,
                    "segment_index": None,
                })
        sf = round(start * fps)
        ef = round(end * fps)
        if ef > sf:
            out_count = max(1, round((ef - sf) / ratio))
            tasks.append({
                "type": "speed",
                "start_frame": sf, "end_frame": ef,
                "output_count": out_count, "ratio": ratio,
                "source_start": start, "source_end": end,
                "segment_index": int(seg_index),
            })
        cur_time = end

    if cur_time < video_duration - 0.0001:
        sf = round(cur_time * fps)
        ef = total_input_frames
        if ef > sf:
            tasks.append({
                "type": "normal",
                "start_frame": sf, "end_frame": ef,
                "output_count": ef - sf, "ratio": 1.0,
                "source_start": cur_time, "source_end": video_duration,
                "segment_index": None,
            })

    if not tasks:
        cap.release()
        import shutil
        shutil.copy2(input_path, output_path)
        if return_manifest:
            return VideoSpeedManifest(
                output_path=output_path,
                fps=fps,
                total_input_frames=total_input_frames,
                total_output_frames=total_input_frames,
                input_duration=video_duration,
                output_duration=video_duration,
                segments=[],
            ).to_dict()
        return output_path

    total_input_to_read = sum(t["end_frame"] - t["start_frame"] for t in tasks)
    total_output_frames = sum(t["output_count"] for t in tasks)
    print(f"  - 输入: {total_input_frames} 帧, {fps:.2f} fps, {video_duration:.2f}s")
    print(f"  - 任务: {len(tasks)} 段, 需读取 {total_input_to_read} 帧, 输出 {total_output_frames} 帧")
    print(f"  - 并行线程数: {num_workers}")

    def _report(pct: int, msg: str):
        print(f"    {msg}")
        if progress_callback:
            progress_callback(pct, msg)

    # ══════════════════════════════════════════════════
    # 异步流水线：后台线程预读取下一段 → 主线程处理写入当前段 → 释放
    # ══════════════════════════════════════════════════
    _report(25, "开始异步流水线处理视频...")

    # 用第二个 VideoCapture 做异步预读取（避免线程间争抢同一个 cap）
    cap_ahead = cv2.VideoCapture(input_path)
    if not cap_ahead.isOpened():
        cap.release()
        raise Exception(f"无法打开预读取视频: {input_path}")

    writer = _create_frame_writer(output_path, fps, width, height)
    if not writer.isOpened():
        cap.release()
        cap_ahead.release()
        raise Exception(f"无法创建输出视频: {output_path}")

    written_total = 0
    read_total = 0
    speed_manifests = []

    # 预读取结果容器（线程安全通过事件同步）
    _ahead_lock = threading.Lock()
    _ahead_data = [None, None]  # [frames, tidx] or None
    _ahead_done = threading.Event()
    _ahead_error = [None]

    def _ahead_read(tidx: int):
        """后台线程：读取指定片段的帧。"""
        try:
            task = tasks[tidx]
            sf = task["start_frame"]
            ef = task["end_frame"]
            frames = _read_segment_frames(cap_ahead, sf, ef, batch_size)
            with _ahead_lock:
                _ahead_data[0] = frames
                _ahead_data[1] = tidx
        except Exception as e:
            _ahead_error[0] = e
        finally:
            _ahead_done.set()

    def _start_ahead_read(tidx: int):
        """启动后台预读取。"""
        _ahead_done.clear()
        _ahead_data[0] = None
        _ahead_data[1] = None
        _ahead_error[0] = None
        t = threading.Thread(target=_ahead_read, args=(tidx,), daemon=True)
        t.start()

    def _get_ahead_frames():
        """等待预读取完成，返回 (frames, tidx)。"""
        _ahead_done.wait()
        if _ahead_error[0]:
            raise _ahead_error[0]
        with _ahead_lock:
            return _ahead_data[0], _ahead_data[1]

    # ── 预读取第 0 段 ──
    if tasks:
        _start_ahead_read(0)

    for tidx, task in enumerate(tasks):
        seg_label = f"段 {tidx + 1}/{len(tasks)} ({task['type']}, ratio={task['ratio']:.2f})"

        # 获取当前段帧（来自预读取）
        frames, got_idx = _get_ahead_frames()
        assert got_idx == tidx, f"预读取顺序错误: 期望 {tidx}, 得到 {got_idx}"
        read_total += (task["end_frame"] - task["start_frame"])
        pct = 25 + int(read_total / max(total_input_to_read, 1) * 35)
        _report(pct, f"  读取 {seg_label}: {len(frames)} 帧")

        # 启动下一段的异步预读取（如果还有下一段）
        next_idx = tidx + 1
        if next_idx < len(tasks):
            _start_ahead_read(next_idx)

        # 处理+写入当前段（与下一段的读取并行执行）
        n_written = _process_and_write_segment(
            writer, frames, task["type"], task["ratio"],
            task["output_count"], num_workers,
        )
        output_start = written_total / fps if fps > 0 else 0.0
        written_total += n_written
        output_end = written_total / fps if fps > 0 else output_start
        if task["type"] == "speed":
            speed_manifests.append(VideoSpeedSegmentManifest(
                index=int(task.get("segment_index") or 0),
                start=float(task.get("source_start") or 0),
                end=float(task.get("source_end") or 0),
                speed_ratio=float(task["ratio"]),
                start_frame=int(task["start_frame"]),
                end_frame=int(task["end_frame"]),
                input_frames=int(task["end_frame"] - task["start_frame"]),
                output_frames=int(n_written),
                actual_duration=float(n_written / fps if fps > 0 else 0.0),
                output_start=float(output_start),
                output_end=float(output_end),
            ))
        pct = 60 + int(written_total / max(total_output_frames, 1) * 35)
        _report(pct, f"  写入 {seg_label}: {n_written} 帧 (累计 {written_total}/{total_output_frames})")

        # 立即释放当前段帧数据
        del frames
        gc.collect()

    cap.release()
    cap_ahead.release()
    writer.release()

    # 最终进度
    output_duration = written_total / fps if fps > 0 else 0
    _report(100, f"  完成: {written_total} 帧, {output_duration:.2f}s")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise Exception(f"输出视频文件无效: {output_path}")

    if return_manifest:
        return VideoSpeedManifest(
            output_path=output_path,
            fps=fps,
            total_input_frames=total_input_frames,
            total_output_frames=written_total,
            input_duration=video_duration,
            output_duration=output_duration,
            segments=speed_manifests,
        ).to_dict()
    return output_path


# ───────────────── 向后兼容入口 ─────────────────

def adjust_video_speed_segment(
    input_path: str, output_path: str,
    start_time: float, end_time: float, speed_ratio: float,
    **kwargs,
) -> float:
    """对单个片段进行变速（向后兼容接口）。"""
    result = adjust_video_speed_segments(
        input_path, output_path,
        [(start_time, end_time, speed_ratio)],
    )
    if result:
        cap = cv2.VideoCapture(result)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        return frames / fps if fps > 0 else 0
    return 0


def calculate_video_speed_segments(
    segments: List[dict],
    speed_min: float = 1.0,
    speed_max: float = 1.5,
    gap_threshold: float = 0.1,
) -> List[Tuple[float, float, float]]:
    """计算需要视频变速的片段列表。"""
    speed_segments = []
    for seg in segments:
        if not seg.get("overflow"):
            continue
        start = seg.get("start", 0)
        end = seg.get("end", start)
        duration = end - start
        if duration <= 0:
            continue
        real_dur = seg.get("adjusted_duration") or seg.get("real_duration", duration)
        raw_speed = seg.get("raw_speed_factor", 1.0)
        if raw_speed > speed_max:
            audio_adjusted_dur = real_dur / speed_max
            video_speed_ratio = audio_adjusted_dur / duration
            video_speed_ratio = max(1.05, min(video_speed_ratio, 2.0))
            speed_segments.append((start, end, video_speed_ratio))
            print(f"  - 片段 {seg.get('index')}: 视频变速 {video_speed_ratio:.3f}x "
                  f"({start:.2f}s-{end:.2f}s)")
    return speed_segments

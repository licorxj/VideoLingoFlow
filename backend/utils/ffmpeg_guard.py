"""ffmpeg 资源保护辅助：统一「线程 / 封装队列限制 + 自适应超时 + 磁盘与时长预检」。

背景
----
多个视频重编码节点此前各自拼 ffmpeg 命令，普遍缺失资源约束，在长 / 高清视频下
容易吃满 CPU、封装队列无界增长导致内存暴涨，表现为系统卡死甚至进程 OOM。
本模块把这几类保护集中为可复用的小工具，新节点应直接复用，避免重复踩坑。

设计原则
--------
* 只提供**无副作用**的参数拼装与校验辅助，不接管命令构建（各节点 cmd 差异大）；
* 执行仍统一走 ``video_ops.run_ffmpeg_with_progress``（流式输出 + 进度 + 协作取消），
  不要再用 ``subprocess.run(capture_output=True)`` 直接跑长任务。
"""
from __future__ import annotations

import os
import shutil


def resource_args(threads: int | None = None, mux_queue: int = 4096) -> list:
    """ffmpeg 资源限制参数。

    * ``-threads`` / ``-filter_threads``：限制编解码与滤镜线程数，避免多核机器上
      重编码吃满全部 CPU 导致系统卡顿（``threads <= 0`` 时交给 ffmpeg 自动决定）；
    * ``-max_muxing_queue_size``：限制封装队列长度，防止多路输入 / 各段时长不均等
      时封装队列无界增长导致内存暴涨（ffmpeg 经典 OOM 来源）。

    ``threads=None`` 时读取环境变量 ``FFMPEG_MAX_THREADS``：
    - 未设置或空：默认 ``max(1, cpu_count // 2)``（本机单卡批量友好，给 GPU/系统留核）
    - ``0``：不限制（交给 ffmpeg 自动）
    - 正整数：按该值限流
    """
    if threads is None:
        raw = os.getenv("FFMPEG_MAX_THREADS", "").strip()
        if not raw:
            try:
                threads = max(1, (os.cpu_count() or 4) // 2)
            except Exception:
                threads = 0
        else:
            try:
                threads = max(0, int(raw))
            except (TypeError, ValueError):
                threads = 0
    args = ["-max_muxing_queue_size", str(int(mux_queue))]
    if threads and int(threads) > 0:
        args = ["-threads", str(int(threads)), "-filter_threads", str(int(threads)), *args]
    return args


def apply_resource_args(cmd: list | tuple, threads: int | None = None, mux_queue: int = 4096) -> list:
    """把 resource_args 插入已拼好的 ffmpeg 命令（幂等）。

    规则：若命令已含 ``-threads`` / ``-max_muxing_queue_size`` 则原样返回；
    否则插在最后一个参数（通常是输出路径）之前，避免破坏 filter/out 顺序。
    """
    if not cmd:
        return list(cmd or [])
    cmd = list(cmd)
    if any(a in ("-threads", "-max_muxing_queue_size") for a in cmd):
        return cmd
    args = resource_args(threads=threads, mux_queue=mux_queue)
    if len(cmd) >= 2:
        return [*cmd[:-1], *args, cmd[-1]]
    return [*cmd, *args]


def adaptive_timeout(duration: float, configured: float = 0.0,
                     minimum: float = 600.0, factor: float = 10.0, base: float = 300.0) -> float:
    """按视频时长自适应估算超时（秒）。

    固定超时有两难：过短则长视频必然失败；过长（如 ffmpeg 默认 86400s = 24h）
    则进程异常挂起时形同卡死。这里取「配置值」与「时长 × factor + base」的较大者，
    并保证不低于 ``minimum``；拿不到时长时退化为 ``minimum``（或配置值）。
    """
    floor = float(minimum)
    configured = float(configured or 0)
    try:
        dur = float(duration)
    except (TypeError, ValueError):
        dur = 0.0
    if dur > 0:
        return max(configured, dur * float(factor) + float(base), floor)
    return max(configured, floor)


def ensure_disk_space(target_dir: str, needed_bytes: float, margin: float = 1.3) -> None:
    """产物落地前检查磁盘余量，不足时快速失败并给出可执行提示。"""
    if needed_bytes is None or needed_bytes <= 0:
        return
    try:
        free = shutil.disk_usage(target_dir).free
    except OSError:
        return
    if free < needed_bytes * float(margin):
        raise RuntimeError(
            f"磁盘可用空间不足：本次处理预计需要约 {needed_bytes * margin / 1048576:.0f} MB，"
            f"当前仅剩 {free / 1048576:.0f} MB，已中止以免写坏输出。"
            f"请清理磁盘后重试，或降低分辨率 / 质量。"
        )


def duration_limit_guard(limit_minutes, video_duration: float, label: str = "视频") -> None:
    """检查视频时长是否超过节点配置的上限，超限时抛出可读错误。"""
    try:
        limit = int(limit_minutes or 0)
    except (TypeError, ValueError):
        return
    if limit > 0 and video_duration and video_duration > limit * 60:
        raise RuntimeError(
            f"{label}时长约 {video_duration / 60:.1f} 分钟，超过节点配置的上限 {limit} 分钟。"
            f"如确需处理，请把该节点「最长时长上限」调大或设为 0（不限制）。"
        )


def coerce_threads(value, default: int = 0, maximum: int = 64) -> int:
    """把节点配置里的线程上限收敛为 [0, maximum] 的整数（0 = 自动/env 默认）。"""
    try:
        threads = int(value)
    except (TypeError, ValueError):
        threads = default
    return max(0, min(threads, maximum))
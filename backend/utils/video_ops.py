"""Video operation utilities using ffmpeg."""
import subprocess
import os
from typing import Optional


def get_video_duration(path: str) -> float:
    """Get video duration in seconds."""
    cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def extract_audio(video_path: str, audio_path: str):
    """Extract audio from video."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        audio_path
    ]
    subprocess.run(cmd, capture_output=True, timeout=120)


def extract_last_frame(video_path: str, output_path: str) -> str:
    """Use ffmpeg to extract the last frame of a video as an image.

    Returns the output image path on success. Raises RuntimeError on failure
    (missing ffmpeg, invalid video, or empty output).
    """
    if not video_path or not os.path.isfile(video_path):
        raise RuntimeError(f"extract_last_frame: 视频文件不存在: {video_path}")
    duration = get_video_duration(video_path)
    # 取倒数第 2 帧附近，避免恰好落点超出时长导致抽不到帧
    seek = max(0.0, duration - 0.04) if duration > 0 else 0.0
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{seek:.3f}",
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise RuntimeError("extract_last_frame: 未找到 ffmpeg，请先安装 ffmpeg。")
    except subprocess.TimeoutExpired:
        raise RuntimeError("extract_last_frame: 抽取尾帧超时（60s）。")
    if result.returncode != 0 or not os.path.exists(output_path):
        err = (result.stderr or result.stdout or "")[:400]
        raise RuntimeError(f"extract_last_frame: ffmpeg 失败: {err}")
    return output_path


def merge_audio_video(video_path: str, audio_path: str, output_path: str):
    """Merge audio track with video."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
        "-c:v", "copy", "-c:a", "aac",
        "-map", "0:v:0", "-map", "1:a:0",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, timeout=600)


def run_ffmpeg_with_progress(cmd, duration: float, callback=None, cancel_callback=None,
                             timeout: int = 86400, label: str = "处理") -> None:
    """执行 ffmpeg 命令并按 ``-progress pipe:1`` 输出上报进度。

    ``cmd`` 需已包含 ``-progress pipe:1 -nostats``。协作取消时终止进程并抛出
    TaskCancelledError；超时或非 0 退出码抛出带 stderr 尾部的 RuntimeError。
    ``label`` 用于进度/错误文案（如 "转码"、"缩放"）。
    """
    import threading
    import time

    from backend.control_plane.runtime import TaskCancelledError

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    stderr_chunks = []
    last = {"pct": 0}

    def _progress_reader():
        try:
            for line in proc.stdout:
                s = line.strip()
                if s.startswith("out_time_ms="):
                    try:
                        ms = int(s.split("=", 1)[1])
                    except ValueError:
                        continue
                    cur = ms / 1_000_000.0
                    pct = min(99, int(cur / duration * 100)) if duration and duration > 0 else last["pct"]
                    last["pct"] = pct
                    if callback:
                        try:
                            callback(pct, f"{label}中 {cur:.1f}s / {duration:.1f}s")
                        except Exception:
                            pass
                elif s == "progress=end":
                    last["pct"] = 100
                    if callback:
                        try:
                            callback(100, f"{label}完成")
                        except Exception:
                            pass
        except Exception:
            pass

    def _stderr_reader():
        try:
            for line in proc.stderr:
                stderr_chunks.append(line)
        except Exception:
            pass

    t1 = threading.Thread(target=_progress_reader, daemon=True)
    t2 = threading.Thread(target=_stderr_reader, daemon=True)
    t1.start()
    t2.start()

    elapsed = 0.0
    while True:
        rc = proc.poll()
        if rc is not None:
            break
        if cancel_callback is not None and cancel_callback():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise TaskCancelledError(f"用户取消{label}")
        time.sleep(0.5)
        elapsed += 0.5
        if elapsed > timeout:
            proc.kill()
            raise RuntimeError(f"{label}超时（超过 {int(timeout)} 秒）")

    t1.join(timeout=2)
    t2.join(timeout=2)
    stderr_text = "".join(stderr_chunks)
    if proc.returncode != 0:
        snippet = stderr_text[-1500:] if stderr_text else ""
        raise RuntimeError(f"ffmpeg {label}失败（返回码 {proc.returncode}）：\n{snippet}")

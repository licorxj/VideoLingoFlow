"""s_video_quick_edit: 视频快剪节点。

封装 satloot-video-tools 的 video_tools.py CLI（基于 ffmpeg 的本地视频小工具集）：
压缩、剪切、合并、提取音频、转格式、转 GIF、截图、改分辨率、调速、去声音、
配背景音乐、加文字水印、烧录字幕、旋转翻转、查看信息。

节点面板用一个「功能」下拉框选择要做的操作，选中后才显示该功能对应的参数；
执行时把选中的功能与参数翻译成 video_tools.py 子命令，结果文件解析后作为
video 输出（连同文字摘要 result）。
"""
import os
import re
import subprocess
import sys
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

# backend/video_tools/video_tools.py（与 vt_core.py 同目录）
_SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "video_tools")
VIDEO_TOOLS = os.path.join(_SKILL_DIR, "video_tools.py")

# 功能 action 值 -> video_tools.py 子命令
ACTION_CMD = {
    "info": "info",
    "compress": "compress",
    "cut": "cut",
    "merge": "merge",
    "audio": "audio",
    "convert": "convert",
    "gif": "gif",
    "snapshot": "snapshot",
    "resize": "resize",
    "speed": "speed",
    "mute": "mute",
    "bgm": "bgm",
    "text": "text",
    "subtitle": "subtitle",
    "rotate": "rotate",
}

_PROGRESS_RE = re.compile(r"处理中[:：]\s*(\d+)%")
_NEWFILE_RE = re.compile(r"完成！新文件[:：]\s*([^\n\r]+)")
_SNAP_FOLDER_RE = re.compile(r"都在[:：]\s*([^\n\r]+)")


def _resolve_path(task_dir: str, p):
    if not p:
        return None
    p = str(p).strip()
    if not p:
        return None
    if not os.path.isabs(p):
        p = os.path.join(task_dir, p)
    return os.path.normpath(p)


def _opt(cfg, key, default=None):
    v = cfg.get(key)
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return default
    return v


class S_VideoQuickEdit(BaseStep):
    step_id = "video_quick_edit"
    step_name = "视频快剪"
    dependencies = []
    artifacts = []

    def check_artifact(self, task_dir: str) -> bool:
        return True

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    # ──────────────────────────────────────────────
    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        action = _opt(node_config, "action")
        if not action or action not in ACTION_CMD:
            raise ValueError(f"「视频快剪」未选择有效的功能（当前 action={action!r}）。请在节点面板选择一项功能。")
        cmd_name = ACTION_CMD[action]

        if not os.path.isfile(VIDEO_TOOLS):
            raise FileNotFoundError(f"未找到视频工具脚本：{VIDEO_TOOLS}")

        out_dir = os.path.join(task_dir, "处理后")
        os.makedirs(out_dir, exist_ok=True)

        args = [sys.executable, VIDEO_TOOLS, "--out-dir", out_dir]
        ffmpeg_dir = _opt(node_config, "ffmpeg_dir")
        if ffmpeg_dir:
            args += ["--ffmpeg", str(ffmpeg_dir)]
        args.append(cmd_name)

        video = _resolve_path(task_dir, step_inputs.get("video"))

        if action == "merge":
            vids = [_resolve_path(task_dir, step_inputs.get(k))
                    for k in ("video", "video_b", "video_c", "video_d")]
            vids = [v for v in vids if v and os.path.isfile(v)]
            if len(vids) < 2:
                raise FileNotFoundError("合并至少需要两个视频：请连接 video / video_b / video_c / video_d 中的至少两个。")
            args += vids
        else:
            if not video or not os.path.isfile(video):
                raise FileNotFoundError(f"缺少输入视频（video）。当前：{video!r}")
            args.append(video)

        self._append_action_args(action, node_config, step_inputs, task_dir, args)

        if callback:
            callback(5, f"视频快剪 · {cmd_name} 准备执行")

        try:
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", cwd=task_dir,
            )
        except Exception as e:  # 启动失败（如 python 不可用）
            raise RuntimeError(f"启动视频工具失败：{e}")

        out_lines: list[str] = []
        last_pct = 0
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                out_lines.append(line)
                m = _PROGRESS_RE.search(line)
                if m:
                    pct = int(m.group(1))
                    last_pct = max(last_pct, pct)
                    if callback:
                        callback(min(95, 5 + int(last_pct * 0.9)), line)
                elif callback and line.strip():
                    callback(min(95, 5 + int(last_pct * 0.9)), line[:80])
                if cancel_callback and proc.poll() is None:
                    try:
                        if bool(cancel_callback()):
                            proc.terminate()
                    except Exception:
                        pass
        except Exception:
            proc.kill()
            raise
        rc = proc.wait()

        stdout = "\n".join(out_lines)
        if rc != 0:
            err = "\n".join(ln for ln in out_lines if ln.startswith(("出错了：", "下一步：")))
            raise RuntimeError(
                f"视频快剪（{cmd_name}）执行失败（退出码 {rc}）：\n{err or stdout[-800:]}"
            )

        # 解析结果路径
        video_out = ""
        m = _NEWFILE_RE.search(stdout)
        if m:
            video_out = m.group(1).strip()
        elif action == "snapshot":
            m2 = _SNAP_FOLDER_RE.search(stdout)
            if m2:
                video_out = m2.group(1).strip()

        artifacts = []
        if video_out and os.path.isfile(video_out):
            try:
                artifacts.append(os.path.relpath(video_out, task_dir))
            except Exception:
                pass

        if callback:
            callback(100, "视频快剪完成")
        return {
            "artifacts": artifacts,
            "outputs": {
                "video": video_out,
                "result": stdout,
            },
        }

    # ──────────────────────────────────────────────
    def _append_action_args(self, action, cfg, step_inputs, task_dir, args):
        if action == "compress":
            mode = _opt(cfg, "compress_mode", "size")
            if mode == "quality":
                args += ["--quality", _opt(cfg, "compress_quality", "中")]
            else:
                size_mb = _opt(cfg, "size_mb")
                if size_mb is not None:
                    args += ["--size-mb", str(size_mb)]
                else:
                    args += ["--quality", _opt(cfg, "compress_quality", "中")]

        elif action == "cut":
            args += ["--start", str(_opt(cfg, "cut_start", "0"))]
            cut_mode = _opt(cfg, "cut_mode", "end")
            if cut_mode == "length":
                length = _opt(cfg, "cut_length")
                if length is not None:
                    args += ["--length", str(length)]
            else:
                end = _opt(cfg, "cut_end")
                if end is not None:
                    args += ["--end", str(end)]
            if _opt(cfg, "precise"):
                args += ["--precise"]

        elif action == "audio":
            args += ["--quality", _opt(cfg, "audio_quality", "中")]

        elif action == "convert":
            args += ["--to", _opt(cfg, "convert_to", "mp4")]

        elif action == "gif":
            args += ["--start", str(_opt(cfg, "gif_start", "0"))]
            gif_mode = _opt(cfg, "gif_mode", "length")
            if gif_mode == "end":
                end = _opt(cfg, "gif_end")
                if end is not None:
                    args += ["--end", str(end)]
            else:
                length = _opt(cfg, "gif_length")
                if length is not None:
                    args += ["--length", str(length)]
            width = _opt(cfg, "gif_width")
            if width is not None:
                args += ["--width", str(width)]
            fps = _opt(cfg, "gif_fps")
            if fps is not None:
                args += ["--fps", str(fps)]

        elif action == "snapshot":
            snap_mode = _opt(cfg, "snap_mode", "cover")
            if snap_mode == "at":
                at = _opt(cfg, "snap_at")
                if at is not None:
                    args += ["--at", str(at)]
            elif snap_mode == "every":
                every = _opt(cfg, "snap_every")
                if every is not None:
                    args += ["--every", str(every)]

        elif action == "resize":
            to = _opt(cfg, "resize_to", "1080P")
            if to:
                args += ["--to", str(to)]

        elif action == "speed":
            rate = _opt(cfg, "rate")
            if rate is not None:
                args += ["--rate", str(rate)]

        elif action == "bgm":
            music = _resolve_path(task_dir, step_inputs.get("music"))
            if not music or not os.path.isfile(music):
                raise FileNotFoundError(f"配乐缺少背景音乐（music）。当前：{music!r}")
            args += ["--music", music]
            if _opt(cfg, "keep_voice"):
                args += ["--keep-voice"]
            vol = _opt(cfg, "music_volume")
            if vol is not None:
                args += ["--music-volume", str(vol)]

        elif action == "text":
            text = _opt(cfg, "text")
            if not text:
                raise ValueError("加文字水印需要填写「文字内容」。")
            args += ["--text", str(text)]
            pos = _opt(cfg, "text_pos")
            if pos:
                args += ["--pos", str(pos)]
            size = _opt(cfg, "text_size")
            if size:
                args += ["--size", str(size)]
            opacity = _opt(cfg, "opacity")
            if opacity is not None:
                args += ["--opacity", str(opacity)]

        elif action == "subtitle":
            srt = _resolve_path(task_dir, step_inputs.get("subtitle"))
            if not srt or not os.path.isfile(srt):
                raise FileNotFoundError(f"烧录字幕缺少字幕文件（subtitle）。当前：{srt!r}")
            args += ["--srt", srt]
            size = _opt(cfg, "subtitle_size")
            if size:
                args += ["--size", str(size)]

        elif action == "rotate":
            how = _opt(cfg, "rotate_how")
            if not how:
                raise ValueError("旋转/翻转需要选择方式（右转90 / 左转90 / 180 / 水平翻转 / 垂直翻转）。")
            args += ["--how", str(how)]

        # info / mute / merge：无需额外参数

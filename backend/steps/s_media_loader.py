# -*- coding: utf-8 -*-
"""
媒体加载器节点（Step）：视频加载器 / 图片加载器 / 音频加载器

作用：在节点卡片上选择或输入媒体文件路径，卡片内直接预览（视频/音频可播放暂停，
图片可全屏），并把所选文件的绝对路径输出给下游节点。不拷贝、不转码、不落盘。

与「文件加载」节点的区别：
  1. 按媒体类型校验扩展名，防止把 .txt 接到视频加载器上；
  2. 校验文件确实存在且可读，避免把无效路径传给下游；
  3. 文件名保留原始基名（含扩展名），便于下游按扩展名判定类型。

输入：可选 any（接入时忽略，输出始终为配置中的文件路径）。
输出：filepath —— 媒体文件的绝对路径字符串。
"""
import os

from backend.steps.base_step import BaseStep


class _MediaLoaderBase(BaseStep):
    """媒体加载器公共实现：子类只需给出节点元信息与允许的扩展名。"""

    dependencies = []
    media_label = "媒体"
    ext_groups: tuple = ()

    @property
    def allowed_exts(self) -> tuple:
        """展开后的全部允许扩展名（小写，含点）。"""
        out = []
        for group in self.ext_groups:
            if isinstance(group, str):
                out.append(group.lower())
            else:
                out.extend(str(item).lower() for item in group)
        return tuple(out)

    def _ext_choices(self) -> list:
        """供前端原生文件对话框使用的 [标签, 模式] 列表（按分组给出通配）。"""
        return [[f"{self.media_label}文件", f"*{ext}"] for ext in self.allowed_exts]

    def check_artifact(self, task_dir: str) -> bool:
        # 本节点不落盘，内存输出即视为完成。
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir, callback=None, cancel_callback=None):
        node_config = getattr(self, "_node_config", {}) or {}
        raw = str(node_config.get("filePath", "") or "").strip()

        if not raw:
            message = f"未选择{self.media_label}文件"
            self._progress(callback, 100, message)
            # 与「文件加载」节点保持一致：未选择时输出空路径，不直接失败
            return {"outputs": {"filepath": ""}}

        abspath = os.path.abspath(os.path.expanduser(raw))

        ext = os.path.splitext(abspath)[1].lower()
        allowed = self.allowed_exts
        if allowed and ext not in allowed:
            pretty = "、".join(sorted(allowed))
            raise ValueError(
                f"{self.step_name}需要{self.media_label}文件（扩展名 {pretty}），"
                f"当前文件为 {ext or '无扩展名'}：{os.path.basename(abspath)}"
            )

        if not os.path.exists(abspath):
            raise FileNotFoundError(f"{self.media_label}文件不存在：{abspath}")
        if not os.path.isfile(abspath):
            raise ValueError(f"所选路径不是文件：{abspath}")
        if os.path.getsize(abspath) == 0:
            raise ValueError(f"{self.media_label}文件为空（0 字节）：{abspath}")

        self._progress(callback, 100, f"已加载{self.media_label}：{os.path.basename(abspath)}")
        # 不落盘：直接以内联文件路径作为输出，在节点间内存传递。
        return {"outputs": {"filepath": abspath}}

    @staticmethod
    def _progress(callback, percent: int, message: str) -> None:
        if not callback:
            return
        try:
            callback(percent, message)
        except Exception:
            pass


class StepVideoLoader(_MediaLoaderBase):
    step_id = "s_video_loader"
    step_name = "视频加载"
    media_label = "视频"
    ext_groups = (
        # 常见容器格式
        (".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg", ".ts"),
        # 便于部分工具识别
        (".m2ts", ".mts", ".3gp", ".3g2", ".vob", ".rm", ".rmvb", ".asf", ".ogv", ".f4v"),
    )


class StepImageLoader(_MediaLoaderBase):
    step_id = "s_image_loader"
    step_name = "图片加载"
    media_label = "图片"
    ext_groups = (
        (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"),
        (".ico", ".jfif", ".avif", ".heic", ".heif", ".svg"),
    )


class StepAudioLoader(_MediaLoaderBase):
    step_id = "s_audio_loader"
    step_name = "音频加载"
    media_label = "音频"
    ext_groups = (
        (".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".oga", ".opus", ".wma"),
        (".aiff", ".aif", ".amr", ".ape", ".mid", ".midi", ".mka", ".ac3", ".dts"),
    )
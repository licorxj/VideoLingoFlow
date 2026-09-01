"""
VideoGen Base - 所有视频生成接口的基础抽象类。
定义统一的接口方法, 供 VideoGenFactory 调度。
"""
import logging

logger = logging.getLogger(__name__)


class VideoGenBase:
    """视频生成接口基类。"""

    def __init__(self, config: dict):
        self.config = config

    def generate(self, prompt: str, output_dir: str, model: str = "",
                 negative_prompt: str = "", resolution: str = "720P",
                 duration: int = 5, num_videos: int = 1, ref_images: list = None,
                 ref_videos: list = None, audio=None, mode: str = "txt2video",
                 api_key: str = "", ratio: str = "16:9", ref_audios: list = None,
                 **kwargs) -> list:
        """
        生成视频。子类必须实现。

        Args:
            prompt: 提示词
            output_dir: 输出目录
            model: 模型名称 (modelName)
            negative_prompt: 反向提示词
            resolution: 分辨率 (如 720P / 1080P / 4K)
            ratio: 宽高比 (如 16:9；图生视频-首/尾帧场景由引擎强制 adaptive)
            duration: 时长 (秒)
            num_videos: 生成数量
            ref_images: 参考图路径/URL 列表
            ref_videos: 参考视频路径/URL 列表
            ref_audios: 参考音频路径/URL 列表（Seedance 全模态参考生视频能力）
            audio: 声音开关 (None 走模型默认 / True / False / "on"/"off"/"keep_original"/"model_default")
            mode: 生成类型（能力类型，按官方文档映射）：
                  - txt2video : 文生视频（纯文本）
                  - img2video : 图生视频-首帧（1 张参考图, role=first_frame）
                  - flf2video : 图生视频-首尾帧（2 张参考图, role=first_frame/last_frame）
                  - autovideo : 全模态参考生视频（reference_image + reference_video + reference_audio 任意组合）
            api_key: API Key
        Returns:
            生成的视频文件本地路径列表
        """
        raise NotImplementedError("子类必须实现 generate 方法")

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
                 api_key: str = "", **kwargs) -> list:
        """
        生成视频。子类必须实现。

        Args:
            prompt: 提示词
            output_dir: 输出目录
            model: 模型名称 (modelName)
            negative_prompt: 反向提示词
            resolution: 分辨率 (如 720P / 1080P)
            duration: 时长 (秒)
            num_videos: 生成数量
            ref_images: 参考图路径/URL 列表
            ref_videos: 参考视频路径/URL 列表
            audio: 声音开关 (None 走模型默认 / True / False / "on"/"off"/"keep_original")
            mode: 生成类型 (txt2video / img2video / flf2video / autovideo)
            api_key: API Key
        Returns:
            生成的视频文件本地路径列表
        """
        raise NotImplementedError("子类必须实现 generate 方法")

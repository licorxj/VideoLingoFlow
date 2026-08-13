"""AIGC 能力模块：从 Infinite-Canvas 迁移的 ComfyUI / RunningHub / 即梦 能力调用逻辑。

设计原则：
- 自包含：不依赖 IC 的全局变量与 env 文件，全部配置来自 VL 的 settings（config.yaml）。
- 即梦沿用 IC 的本地 CLI（dreamina）子进程调用方式。
"""
from backend.aigc.comfyui_service import ComfyUIService
from backend.aigc.runninghub_service import RunningHubService
from backend.aigc.jimeng_service import JimengService

__all__ = ["ComfyUIService", "RunningHubService", "JimengService"]

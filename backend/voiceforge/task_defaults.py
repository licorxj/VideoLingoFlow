"""晴沐配音谷（VoiceForge）任务派发相关的默认参数：并发上限与失败重试。

全部从全局配置读取，用户可在「配音谷设置页 → 合成与导出」中调整；
未配置时回退到与业务匹配的内置默认值（并发 3、重试 2 次、间隔 1 秒）。
"""
from backend.config.config_manager import config


def synthesis_concurrency() -> int:
    """同时在途的句子合成任务上限（全局，保护 TTS 接口不被瞬时打满）。"""
    try:
        value = int(config.get("voiceforge.synthesis.concurrency") or 3)
    except (TypeError, ValueError):
        value = 3
    return min(max(value, 1), 32)


def synthesis_retry_count() -> int:
    """单句合成失败后的自动重试次数（不含首次尝试）。"""
    try:
        value = int(config.get("voiceforge.synthesis.retry_count") or 2)
    except (TypeError, ValueError):
        value = 2
    return min(max(value, 0), 5)


def synthesis_retry_delay() -> float:
    """单句合成自动重试前的等待秒数。"""
    try:
        value = float(config.get("voiceforge.synthesis.retry_delay") or 1.0)
    except (TypeError, ValueError):
        value = 1.0
    return min(max(value, 0.0), 30.0)

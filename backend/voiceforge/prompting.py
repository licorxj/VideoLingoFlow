"""晴沐配音谷（VoiceForge）的 LLM Prompt 组装与默认参数集中管理。

设计要点：
1. Prompt 统一走 scope=voiceforge 的 Prompt 预设，用户可在「配音谷设置页」自行编辑；
   预设缺失或渲染失败时自动回退到各调用点的内置硬编码 Prompt，保证功能始终可用。
2. TTS 配音接口与 LLM 接口本身不在配音谷内配置，统一由本项目全局设置 / 大模型路由器管理。
3. 配音谷专属默认参数（导出格式、句间静音、AI 文本上限、各步骤温度）统一从全局配置读取。
"""
from typing import Optional

from backend.config.config_manager import config

# 配音谷 AI 能力对应的 Prompt 预设 id（与 config/prompt_templates.json 中 scope=voiceforge 的条目一致）
PROMPT_SENTENCE_SPLIT = "voiceforge_sentence_split"
PROMPT_DIALOGUE_EXTRACT = "voiceforge_dialogue_extract"
PROMPT_CHAPTER_SPLIT = "voiceforge_chapter_split"
PROMPT_SCRIPT_ANALYSIS = "voiceforge_script_analysis"
PROMPT_EMOTION_DESIGN = "voiceforge_emotion_design"
PROMPT_VOICE_PARAMS = "voiceforge_voice_params"

# 每个 AI 能力默认的采样温度（用户在设置页可覆盖）
DEFAULT_TEMPERATURES = {
    PROMPT_SENTENCE_SPLIT: 0.1,
    PROMPT_DIALOGUE_EXTRACT: 0.2,
    PROMPT_CHAPTER_SPLIT: 0.2,
    PROMPT_SCRIPT_ANALYSIS: 0.3,
    PROMPT_EMOTION_DESIGN: 0.4,
    PROMPT_VOICE_PARAMS: 0.2,
}


def assemble_prompt(prompt_id: str, data: dict):
    """按预设 id 渲染 Prompt。

    返回 (system_prompt, user_prompt)；预设不存在或渲染结果为空时返回 (None, None)，
    由调用方回退到内置硬编码 Prompt。
    """
    try:
        from backend.prompts.prompt_service import get_prompt_service

        result = get_prompt_service().assemble_prompt(prompt_id, data)
    except Exception:
        return None, None
    if not result or not result.get("found"):
        return None, None
    system_prompt = (result.get("system_prompt") or "").strip() or None
    user_prompt = (result.get("user_prompt") or "").strip() or None
    if not user_prompt:
        return None, None
    return system_prompt, user_prompt


def temperature_for(prompt_id: str) -> float:
    """读取某 AI 能力的采样温度，未配置时回退到内置默认值。"""
    value = config.get(f"voiceforge.llm.{prompt_id}.temperature")
    try:
        return float(value)
    except (TypeError, ValueError):
        return DEFAULT_TEMPERATURES.get(prompt_id, 0.3)


def export_default_format() -> str:
    """合并导出时的默认音频格式。"""
    value = str(config.get("voiceforge.export.format") or "wav").lower()
    return value if value in {"wav", "mp3", "flac"} else "wav"


def export_default_gap_seconds() -> float:
    """合并导出时的默认句间静音（秒），上限 3 秒与导出接口约束一致。"""
    try:
        value = float(config.get("voiceforge.export.gap_seconds") or 0)
    except (TypeError, ValueError):
        value = 0.0
    return min(max(value, 0.0), 3.0)


def text_source_limit() -> int:
    """AI 文本处理（分句 / 对话提取 / 分章 / 剧本分析）的单次字符上限。"""
    try:
        value = int(config.get("voiceforge.text.source_limit") or 100000)
    except (TypeError, ValueError):
        value = 100000
    return max(1000, value)


def default_max_sentence_length() -> int:
    """AI 智能断句的默认单句长度。"""
    try:
        value = int(config.get("voiceforge.text.max_sentence_length") or 200)
    except (TypeError, ValueError):
        value = 200
    return min(max(value, 20), 2000)


def default_chapter_max_chars() -> int:
    """AI 章节分割的默认每章字数。"""
    try:
        value = int(config.get("voiceforge.text.chapter_max_chars") or 3000)
    except (TypeError, ValueError):
        value = 3000
    return min(max(value, 200), 100000)


def limit_source(value: str, maximum: Optional[int] = None) -> str:
    """按配置上限裁剪并校验待处理文本。"""
    source = (value or "").strip()
    if not source:
        raise ValueError("没有可处理的文本")
    limit = maximum if maximum is not None else text_source_limit()
    if len(source) > limit:
        raise ValueError(f"文本超过处理上限（{limit} 字）")
    return source

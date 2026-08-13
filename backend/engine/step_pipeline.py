"""
Step pipeline registry and task type mapping.
Defines all available steps, their dependencies, and which steps each task type needs.
"""

# Step registry: step_id -> {deps: [list of step_ids]}
STEP_REGISTRY: dict = {
    "s01_download":       {"deps": []},
    "s02_asr":            {"deps": ["s01_download"]},
    "s03_sentence_split": {"deps": ["s02_asr"]},
    "s04_summarize":      {"deps": ["s03_sentence_split"]},
    "s05_translate":      {"deps": ["s04_summarize"]},
    "s06_subtitle_gen":   {"deps": ["s05_translate"]},
    "s07_merge_sub_vid":  {"deps": ["s06_subtitle_gen"]},
    "s08_dub_task":       {"deps": ["s06_subtitle_gen"]},
    "s09_tts":            {"deps": ["s08_dub_task"]},
    "s10_merge_audio":    {"deps": ["s09_tts"]},
    "s11_merge_dub_vid":  {"deps": ["s10_merge_audio"]},
    "s12_cover":          {"deps": ["s07_merge_sub_vid"]},
    "s13_watermark":      {"deps": ["s11_merge_dub_vid"]},
}

# Task type -> ordered list of step_ids to execute
TASK_TYPE_STEPS: dict = {
    "subtitle_only": [
        "s01_download", "s02_asr", "s03_sentence_split",
        "s04_summarize", "s05_translate", "s06_subtitle_gen",
    ],
    "subtitle_video": [
        "s01_download", "s02_asr", "s03_sentence_split",
        "s04_summarize", "s05_translate", "s06_subtitle_gen",
        "s07_merge_sub_vid",
    ],
    "full_dubbing": [
        "s01_download", "s02_asr", "s03_sentence_split",
        "s04_summarize", "s05_translate", "s06_subtitle_gen",
        "s07_merge_sub_vid", "s08_dub_task", "s09_tts",
        "s10_merge_audio", "s11_merge_dub_vid",
    ],
    "post_production": [
        "s12_cover", "s13_watermark",
    ],
}

# Display names for steps
STEP_NAMES: dict = {
    "s01_download": "下载/导入视频",
    "s02_asr": "语音识别(ASR)",
    "s03_sentence_split": "句子分割",
    "s04_summarize": "内容总结",
    "s05_translate": "逐句翻译",
    "s06_subtitle_gen": "字幕生成",
    "s07_merge_sub_vid": "字幕烧录",
    "s08_dub_task": "配音任务生成",
    "s09_tts": "语音合成(TTS)",
    "s10_merge_audio": "音频合并",
    "s11_merge_dub_vid": "配音视频合成",
    "s12_cover": "封面设计",
    "s13_watermark": "水印添加",
}

# Task type display names
TASK_TYPE_NAMES: dict = {
    "subtitle_only": "仅生成字幕",
    "subtitle_video": "字幕+视频",
    "full_dubbing": "完整配音",
    "post_production": "后期制作",
}


def get_steps_for_task(task_type: str) -> list:
    """Return ordered list of step IDs for a given task type."""
    return TASK_TYPE_STEPS.get(task_type, [])


def get_step_dependencies(step_id: str) -> list:
    """Return direct dependencies of a step."""
    return STEP_REGISTRY.get(step_id, {}).get("deps", [])


def validate_task_type(task_type: str) -> bool:
    return task_type in TASK_TYPE_STEPS

"""
Step registry: maps step IDs to step class instances.
Import all step modules and register them here.
"""
from backend.steps.s00_platform_download import S00PlatformDownload
from backend.steps.s01_download import S01Download
from backend.steps.s02_asr import S02ASR
from backend.steps.s03_sentence_split import S03SentenceSplit
from backend.steps.s_sentence_preprocess import S_SentencePreprocess
from backend.steps.s04_summarize import S04Summarize
from backend.steps.s05_translate import S05Translate
from backend.steps.s06_subtitle_gen import S06SubtitleGen
from backend.steps.s07_subtitle_align import S07SubtitleAlign
from backend.steps.s07_merge_sub_video import S07MergeSubVideo
from backend.steps.s08_dub_task import S08DubTask
from backend.steps.s09_tts import S09TTS
from backend.steps.s10_merge_audio import S10MergeAudio
from backend.steps.s_merge_dub import S_MergeDub
from backend.steps.s11_merge_dub_video import S11MergeDubVideo
from backend.steps.s12_cover import S12Cover
from backend.steps.s13_watermark import S13Watermark
from backend.steps.s14_output import StepOutput
from backend.steps.s15_extract_audio import StepExtractAudio
from backend.steps.s16_vocal_separation import StepVocalSeparation
from backend.steps.s17_track_separation import S17TrackSeparation
from backend.steps.s_path_to_title import S_PathToTitle
from backend.steps.s_file_rename import S_FileRename
from backend.steps.s_timed_delay import S_TimedDelay
from backend.steps.s_run_wait import S_RunWait
from backend.steps.s_editor_agent import S_EditorAgent
from backend.steps.s_llm_request import S_LLMRequest
from backend.steps.s_http_request import S_HttpRequest
from backend.steps.s_pi_agent import S_PiAgent
from backend.steps.s_imagegen import S_ImageGen
from backend.steps.s_video_frame_extract import S_VideoFrameExtract
from backend.steps.s_video_publish import S_VideoPublish
from backend.steps.s_xiaopai_publish import S_XiaopaiPublish
from backend.steps.s_resolve_path import S_ResolvePath
from backend.steps.s_translate_task_name import S_TranslateTaskName
from backend.steps.s_json_to_text import S_JsonToText
from backend.steps.s_json_editor import S_JsonEditor
from backend.steps.s_json_visual_editor import S_JsonVisualEditor
from backend.steps.s_text_editor import S_TextEditor
from backend.steps.s_subtitle_editor import S_SubtitleEditor
from backend.steps.s_video_split import S_VideoSplit
from backend.steps.s_cutia import S_Cutia
from backend.steps.s_lcwr_watermark_removal import S_LcwrWatermarkRemoval
from backend.steps.passthrough_step import PassthroughStep

# Step ID -> instance mapping
_STEPS = {
    "s00_platform_download": S00PlatformDownload(),
    "platform_download": S00PlatformDownload(),
    "s01_download": S01Download(),
    "s02_asr": S02ASR(),
    "asr": S02ASR(),
    "s03_sentence_split": S03SentenceSplit(),
    "sentence_split": S03SentenceSplit(),
    "s_sentence_preprocess": S_SentencePreprocess(),
    "sentence_preprocess": S_SentencePreprocess(),
    "s04_summarize": S04Summarize(),
    "summarize": S04Summarize(),
    "s05_translate": S05Translate(),
    "translate": S05Translate(),
    "s06_subtitle_gen": S06SubtitleGen(),
    "subtitle_gen": S06SubtitleGen(),
    "s07_subtitle_align": S07SubtitleAlign(),
    "subtitle_align": S07SubtitleAlign(),
    "s07_merge_sub_video": S07MergeSubVideo(),
    "merge_sub_video": S07MergeSubVideo(),
    "s08_dub_task": S08DubTask(),
    "dub_task": S08DubTask(),
    "s09_tts": S09TTS(),
    "tts": S09TTS(),
    "s10_merge_audio": S10MergeAudio(),
    "merge_audio": S10MergeAudio(),
    "merge_dub": S_MergeDub(),
    "s11_merge_dub_video": S11MergeDubVideo(),
    "merge_dub_video": S11MergeDubVideo(),
    "s12_cover": S12Cover(),
    "cover": S12Cover(),
    "s13_watermark": S13Watermark(),
    "watermark": S13Watermark(),
    "path_to_title": S_PathToTitle(),
    "track_separation": S17TrackSeparation(),
    "file_rename": S_FileRename(),
    "timed_delay": S_TimedDelay(),
    "s_run_wait": S_RunWait(),
    "run_wait": S_RunWait(),
    "editor_agent": S_EditorAgent(),
    # Legacy node type aliases
    "s15_extract_audio": StepExtractAudio(),
    "extract_audio": StepExtractAudio(),
    # UI-only / preview nodes
    "video_preview": PassthroughStep(),
    "image_preview": PassthroughStep(),
    # 其余真实执行节点（与 thread_scheduler.NODE_STEP_MAP 对齐）
    "s14_output": StepOutput(),
    "output": StepOutput(),
    "s16_vocal_separation": StepVocalSeparation(),
    "vocal_separation": StepVocalSeparation(),
    "s_llm_request": S_LLMRequest(),
    "llm_request": S_LLMRequest(),
    "s_http_request": S_HttpRequest(),
    "http_request": S_HttpRequest(),
    "pi_agent": S_PiAgent(),
    "s_imagegen": S_ImageGen(),
    "image_gen": S_ImageGen(),
    "s_video_frame_extract": S_VideoFrameExtract(),
    "video_frame_extract": S_VideoFrameExtract(),
    "s_video_publish": S_VideoPublish(),
    "video_publish": S_VideoPublish(),
    "s_xiaopai_publish": S_XiaopaiPublish(),
    "xiaopai_publish": S_XiaopaiPublish(),
    "s_resolve_path": S_ResolvePath(),
    "resolve_path": S_ResolvePath(),
    "s_translate_task_name": S_TranslateTaskName(),
    "translate_task_name": S_TranslateTaskName(),
    "s_json_to_text": S_JsonToText(),
    "json_to_text": S_JsonToText(),
    "s_json_editor": S_JsonEditor(),
    "json_editor": S_JsonEditor(),
    "s_json_visual_editor": S_JsonVisualEditor(),
    "json_visual_editor": S_JsonVisualEditor(),
    "s_text_editor": S_TextEditor(),
    "text_editor": S_TextEditor(),
    "s_subtitle_editor": S_SubtitleEditor(),
    "subtitle_editor": S_SubtitleEditor(),
    "s_video_split": S_VideoSplit(),
    "video_split": S_VideoSplit(),
    "s_cutia": S_Cutia(),
    "cutia": S_Cutia(),
    "s_lcwr_watermark_removal": S_LcwrWatermarkRemoval(),
    "lcwr_watermark_removal": S_LcwrWatermarkRemoval(),
}


def get_step_instance(step_id: str):
    return _STEPS.get(step_id)


def get_all_steps() -> dict:
    return dict(_STEPS)

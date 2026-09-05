"""
Step registry: maps step IDs to step class instances.
Import all step modules and register them here.
"""
from backend.steps.s00_platform_download import S00PlatformDownload
from backend.steps.s01_download import S01Download
from backend.steps.s02_asr import S02ASR
from backend.steps.s_asr_stages import S_ASRRecognize, S_ASRPostProcess
from backend.steps.s_audio_denoise import StepAudioDenoise
from backend.steps.s_audio_cut_by_subtitle import StepAudioCutBySubtitle
from backend.steps.s_aigc_comfyui import S_AIGC_ComfyUI
from backend.steps.s03_sentence_split import S03SentenceSplit
from backend.steps.s_sentence_preprocess import S_SentencePreprocess
from backend.steps.s_asr_result_validate import S_ASRResultValidate
from backend.steps.s_srt_to_json import S_SrtToJson
from backend.steps.s_track_mix import S_TrackMix
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
from backend.steps.s18_audio_transcode import StepAudioTranscode
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
from backend.steps.s_video_transcode import S_VideoTranscode
from backend.steps.s_video_cut_by_subtitle import StepVideoCutBySubtitle
from backend.steps.s_merge_outputs_to_list import StepMergeOutputsToList
from backend.steps.s_subtitle_position_search import S_SubtitlePositionSearch
from backend.steps.s_subtitle_recognition import S_SubtitleRecognition
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
from backend.steps.s_video_region_crop import S_VideoRegionCrop
from backend.steps.s_video_region_composite import S_VideoRegionComposite
from backend.steps.s_cutia import S_Cutia
from backend.steps.s_lcwr_watermark_removal import S_LcwrWatermarkRemoval
from backend.steps.s_media_to_url import S_MediaToUrl
from backend.steps.s_online_watermark_removal import S_OnlineWatermarkRemoval
from backend.steps.s_qm_virtual_mailbox import S_QmVirtualMailbox
from backend.steps.passthrough_step import PassthroughStep
from backend.steps.s_archive import S_ArchiveArtifacts
from backend.steps.s_ai_punctuate import S_AiPunctuate
from backend.steps.s_ai_subtitle_correct import S_AiSubtitleCorrect
from backend.steps.s_text_input import StepTextInput
from backend.steps.s_file_load import StepFileLoad
from backend.steps.s_image_mask import S_ImageMask
from backend.steps.s_srt_to_text import S_SrtToText
from backend.steps.s_ai_videogen import S_AiVideoGen
from backend.steps.s_audio_asset_library import S_AudioAssetLibrary
from backend.steps.s_seedream import (
    S_SeedreamTxt2Img, S_SeedreamImg2Img, S_SeedreamFusion,
    S_SeedreamGrid, S_SeedreamWebSearch, S_SeedreamLayer,
)
from backend.steps.s_seedance import (
    S_SeedanceTxt2Video, S_SeedanceImg2Video,
    S_SeedanceFlf2Video, S_SeedanceAutoVideo,
)
from backend.steps.s_hyperframes_creative import S_HyperFramesCreative
from backend.steps.s_hyperframes_render import S_HyperFramesRender
from backend.steps.s_hyperframes_cli import S_HyperFramesCli
from backend.steps.s_hyperframes_agent import S_HyperFramesAgent
from backend.steps.s_image_grid_split import S_ImageGridSplit

# Step ID -> instance mapping
_STEPS = {
    "s00_platform_download": S00PlatformDownload(),
    "platform_download": S00PlatformDownload(),
    "s01_download": S01Download(),
    "s02_asr": S02ASR(),
    "asr": S02ASR(),
    "s_asr_recognize": S_ASRRecognize(),
    "asr_recognize": S_ASRRecognize(),
    "s_asr_postprocess": S_ASRPostProcess(),
    "asr_postprocess": S_ASRPostProcess(),
    "s_audio_denoise": StepAudioDenoise(),
    "audio_denoise": StepAudioDenoise(),
    "s03_sentence_split": S03SentenceSplit(),
    "sentence_split": S03SentenceSplit(),
    "s_sentence_preprocess": S_SentencePreprocess(),
    "sentence_preprocess": S_SentencePreprocess(),
    "s_asr_result_validate": S_ASRResultValidate(),
    "asr_result_validate": S_ASRResultValidate(),
    "s_srt_to_json": S_SrtToJson(),
    "srt_to_json": S_SrtToJson(),
    "s_track_mix": S_TrackMix(),
    "track_mix": S_TrackMix(),
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
    "s18_audio_transcode": StepAudioTranscode(),
    "audio_transcode": StepAudioTranscode(),
    # UI-only / preview nodes
    "video_preview": PassthroughStep(),
    "image_preview": PassthroughStep(),
    "image_compare": PassthroughStep(),
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
    "aigc_comfyui": S_AIGC_ComfyUI(),
    "s_video_frame_extract": S_VideoFrameExtract(),
    "video_frame_extract": S_VideoFrameExtract(),
    "s_video_transcode": S_VideoTranscode(),
    "video_transcode": S_VideoTranscode(),
    "s_audio_cut_by_subtitle": StepAudioCutBySubtitle(),
    "audio_cut_by_subtitle": StepAudioCutBySubtitle(),
    "s_video_cut_by_subtitle": StepVideoCutBySubtitle(),
    "video_cut_by_subtitle": StepVideoCutBySubtitle(),
    "s_output_merge_list": StepMergeOutputsToList(),
    "output_merge_list": StepMergeOutputsToList(),
    "s_subtitle_position_search": S_SubtitlePositionSearch(),
    "subtitle_position_search": S_SubtitlePositionSearch(),
    "s_subtitle_recognition": S_SubtitleRecognition(),
    "subtitle_recognition": S_SubtitleRecognition(),
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
    "s_video_region_crop": S_VideoRegionCrop(),
    "video_region_crop": S_VideoRegionCrop(),
    "s_video_region_composite": S_VideoRegionComposite(),
    "video_region_composite": S_VideoRegionComposite(),
    "s_cutia": S_Cutia(),
    "cutia": S_Cutia(),
    "s_lcwr_watermark_removal": S_LcwrWatermarkRemoval(),
    "lcwr_watermark_removal": S_LcwrWatermarkRemoval(),
    "s_media_to_url": S_MediaToUrl(),
    "media_to_url": S_MediaToUrl(),
    "s_online_watermark_removal": S_OnlineWatermarkRemoval(),
    "online_watermark_removal": S_OnlineWatermarkRemoval(),
    "s_qm_virtual_mailbox": S_QmVirtualMailbox(),
    "qm_virtual_mailbox": S_QmVirtualMailbox(),
    "archive_artifacts": S_ArchiveArtifacts(),
    "ai_punctuate": S_AiPunctuate(),
    "ai_subtitle_correct": S_AiSubtitleCorrect(),
    "s_ai_subtitle_correct": S_AiSubtitleCorrect(),
    "s_text_input": StepTextInput(),
    "text_input": StepTextInput(),
    "s_file_load": StepFileLoad(),
    "file_load": StepFileLoad(),
    "s_image_mask": S_ImageMask(),
    "image_mask": S_ImageMask(),
    "s_srt_to_text": S_SrtToText(),
    "srt_to_text": S_SrtToText(),
    "s_ai_videogen": S_AiVideoGen(),
    "ai_video_gen": S_AiVideoGen(),
    "s_audio_asset_library": S_AudioAssetLibrary(),
    "audio_asset_library": S_AudioAssetLibrary(),
    # Seedream 生图能力节点（每种能力一个节点，置于 AI生成类节点 分组）
    "seedream_txt2img": S_SeedreamTxt2Img(),
    "seedream_img2img": S_SeedreamImg2Img(),
    "seedream_fusion": S_SeedreamFusion(),
    "seedream_grid": S_SeedreamGrid(),
    "seedream_websearch": S_SeedreamWebSearch(),
    "seedream_layer": S_SeedreamLayer(),
    # 图片宫格切割（AIGC 流程链 分组）
    "image_grid_split": S_ImageGridSplit(),
    "s_image_grid_split": S_ImageGridSplit(),
    # HyperFrames 系列节点（HTML 合成 → 渲染成片，置于 HyperFrames 节点 分组）
    "s_hyperframes_creative": S_HyperFramesCreative(),
    "hyperframes_creative": S_HyperFramesCreative(),
    "s_hyperframes_render": S_HyperFramesRender(),
    "hyperframes_render": S_HyperFramesRender(),
    "s_hyperframes_cli": S_HyperFramesCli(),
    "hyperframes_cli": S_HyperFramesCli(),
    "s_hyperframes_agent": S_HyperFramesAgent(),
    "hyperframes_agent": S_HyperFramesAgent(),
    # Seedance 视频生成能力节点（即梦品牌命名，置于 AI生成类节点 分组）
    "seedance_txt2video": S_SeedanceTxt2Video(),
    "seedance_img2video": S_SeedanceImg2Video(),
    "seedance_flf2video": S_SeedanceFlf2Video(),
    "seedance_autovideo": S_SeedanceAutoVideo(),
}


def get_step_instance(step_id: str):
    return _STEPS.get(step_id)


def new_step_instance(step_id: str):
    """创建步骤的独立实例（循环迭代并发执行时使用）。

    ``_STEPS`` 中的实例是模块级单例，``_run_node`` 会在执行前把 ``_node_id`` /
    ``_node_config`` / ``_step_inputs`` 直接写到实例上。并发跑同一节点类型的多个
    迭代时会互相覆盖，因此循环迭代必须各自持有独立实例。

    注册表中全部步骤类均为零参构造（backend/steps 下仅 s02_asr 与 s_asr_stages
    显式定义 __init__，均为空实现），故 ``type(instance)()`` 安全可用。
    构造失败时回退到注册表单例（退化为串行安全但不隔离）。
    """
    instance = _STEPS.get(step_id)
    if instance is None:
        return None
    try:
        return type(instance)()
    except Exception:
        return instance


def get_all_steps() -> dict:
    return dict(_STEPS)

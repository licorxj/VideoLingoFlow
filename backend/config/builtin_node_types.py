"""Single source of truth for built-in workflow node definitions."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

from backend.utils.hyperframes import WORKFLOW_ROUTES


BUILTIN_NODE_TYPES = [
    {
        "id": "input",
        "name": "输入",
        "execution_domain": "thread",
        "category": "io",
        "description": "导入文件或URL",
        "icon": "Upload",
        "color": "#3b82f6",
        "inputs": [],
        "outputs": [
            {"id": "video", "label": "视频", "type": "video"},
            {"id": "audio", "label": "音频", "type": "audio"},
            {"id": "subtitle", "label": "字幕", "type": "subtitle"},
            {"id": "url", "label": "URL", "type": "url"},
            {"id": "filepath", "label": "文件路径", "type": "any"},
            {"id": "no_input", "label": "不需要输入", "type": "any"},
        ],
        "defaultConfig": {
            "selectedTypes": ["video"],
            "videoPath": "",
            "audioPath": "",
            "subtitlePath": "",
            "url": "",
            "filePath": "",
            "source_language": "auto",
            "target_language": "zh",
            "copyInputs": True,
            "var1": "",
            "var1Required": False,
            "var2": "",
            "var2Required": False,
        },
        "configFields": [
            {"key": "selectedTypes", "label": "输入方式", "type": "chips", "options": [
                {"value": "video", "label": "视频"},
                {"value": "audio", "label": "音频"},
                {"value": "subtitle", "label": "字幕"},
                {"value": "url", "label": "URL"},
                {"value": "filepath", "label": "文件路径"},
            ]},
            {"key": "videoPath", "label": "视频文件", "type": "file", "placeholder": "选择或输入视频文件路径", "dependsOn": "selectedTypes", "dependsAnyValues": ["video"], "fileFilter": ["mp4", "avi", "mkv", "mov", "wmv", "flv", "webm"]},
            {"key": "audioPath", "label": "音频文件", "type": "audio-selector", "placeholder": "选择或输入音频文件路径", "dependsOn": "selectedTypes", "dependsAnyValues": ["audio"], "fileFilter": ["mp3", "wav", "flac", "aac", "ogg", "m4a"]},
            {"key": "subtitlePath", "label": "字幕文件", "type": "file", "placeholder": "选择或输入字幕文件路径", "dependsOn": "selectedTypes", "dependsAnyValues": ["subtitle"], "fileFilter": ["srt", "ass", "ssa", "sub", "txt"]},
            {"key": "url", "label": "URL", "type": "text", "placeholder": "输入视频/音频URL地址", "dependsOn": "selectedTypes", "dependsAnyValues": ["url"]},
            {"key": "filePath", "label": "文件路径", "type": "file", "placeholder": "选择或输入文件路径", "dependsOn": "selectedTypes", "dependsAnyValues": ["filepath"]},
            {"key": "source_language", "label": "输入语言", "type": "language-select", "colSpan": "half"},
            {"key": "target_language", "label": "输出语言", "type": "language-select", "colSpan": "half"},
            {"key": "copyInputs", "label": "复制输入文件到任务缓存", "type": "checkbox"},
            {"key": "var1", "label": "变量1", "type": "text", "placeholder": "输入变量1的值（可在下游节点中引用）", "colSpan": "half"},
            {"key": "var1Required", "label": "必填", "type": "checkbox", "colSpan": "half"},
            {"key": "var2", "label": "变量2", "type": "text", "placeholder": "输入变量2的值（可在下游节点中引用）", "colSpan": "half"},
            {"key": "var2Required", "label": "必填", "type": "checkbox", "colSpan": "half"},
        ],
    },
    {
        "id": "text_input",
        "name": "文本输入框",
        "execution_domain": "thread",
        "category": "io",
        "description": "提供一个大文本输入框，将其内容作为文本输出给下游（不落盘）",
        "icon": "Type",
        "color": "#3b82f6",
        "inputs": [
            {"id": "any", "label": "输入", "type": "any", "required": False},
        ],
        "outputs": [
            {"id": "text", "label": "文本", "type": "text"},
        ],
        "defaultConfig": {
            "text": "",
        },
    },
    {
        "id": "file_load",
        "name": "文件加载",
        "execution_domain": "thread",
        "category": "io",
        "description": "在卡片上选择或输入文件路径，输出该文件的绝对路径（不落盘）",
        "icon": "FolderOpen",
        "color": "#3b82f6",
        "inputs": [
            {"id": "any", "label": "输入", "type": "any", "required": False},
        ],
        "outputs": [
            {"id": "filepath", "label": "文件路径", "type": "any"},
        ],
        "defaultConfig": {
            "filePath": "",
        },
    },
    {
        "id": "image_mask",
        "name": "图片蒙版",
        "execution_domain": "thread",
        "category": "ai_gen",
        "description": "上游输入图片，在卡片上用画笔/矩形绘制蒙版，后端合成蒙版图并输出蒙版合成图与黑白蒙版",
        "icon": "Image",
        "color": "#ec4899",
        "inputs": [
            {"id": "image", "label": "图片", "type": "image", "required": False},
        ],
        "outputs": [
            {"id": "image", "label": "蒙版合成图", "type": "image"},
            {"id": "mask", "label": "蒙版", "type": "image"},
        ],
        "defaultConfig": {
            "mask": {"strokes": [], "rects": [], "color": "#ff3b30", "alpha": 0.5},
        },
    },
    {
        "id": "ai_video_gen",
        "name": "AI生视频",
        "execution_domain": "thread",
        "category": "ai_gen",
        "description": "根据提示词（文本或txt）、图片/图片列表、音频，调用视频生成接口生成视频；提示词前缀会拼接到连线提示词前",
        "icon": "Film",
        "color": "#a855f7",
        "inputs": [
            {"id": "prompt", "label": "提示词", "type": "text", "required": False},
            {"id": "images", "label": "图片/图片列表", "type": "image", "required": False},
            {"id": "audio", "label": "音频", "type": "audio", "required": False},
        ],
        "outputs": [
            {"id": "videos", "label": "视频", "type": "video"},
            {"id": "video", "label": "视频(首个)", "type": "video"},
            {"id": "last_frame", "label": "尾帧", "type": "image"},
        ],
        "defaultConfig": {
            "prompt_prefix": "",
            "interface": "",
            "model": "",
            "mode": "",
            "resolution": "720P",
            "duration": 5,
            "num_videos": 1,
            "sound": "on",
            "negative_prompt": "",
            "output_prefix": "video",
            "optimize_prompt": True,
            "poll_timeout": 1800,
            "extract_last_frame": False,
        },
    },
    {
        "id": "path_to_title",
        "name": "路径转标题",
        "execution_domain": "thread",
        "category": "file",
        "description": "从文件路径提取组件并拼装标题",
        "icon": "FileText",
        "color": "#8b5cf6",
        "inputs": [{"id": "any", "label": "输入", "type": "any", "required": False}],
        "outputs": [{"id": "text", "label": "标题", "type": "text"}],
        "defaultConfig": {"template": "{filename}", "read_from_input": False, "update_task_name": False},
        "configFields": [
            {"key": "read_from_input", "label": "读取输入文件路径", "type": "checkbox", "description": "勾选后直接读取输入节点的文件路径作为解析路径", "colSpan": "full"},
            {"key": "template", "label": "标题模板", "type": "text", "placeholder": "使用 {filename} {parent} {grandparent} 占位符", "colSpan": "full", "description": "点击下方标签插入占位符到模板中"},
            {"key": "update_task_name", "label": "同时命名任务名", "type": "checkbox", "description": "勾选后将拼接结果写入 task.json 的 task_name 字段", "colSpan": "full"},
        ],
    },
    {
        "id": "archive_artifacts",
        "name": "产物文件归档",
        "execution_domain": "thread",
        "category": "io",
        "description": "将上游多个产物文件归档到指定目录，支持复制/剪切、新建子文件夹、重命名与自动序号",
        "icon": "Archive",
        "color": "#3b82f6",
        "inputs": [
            {"id": "any", "label": "产物输入", "type": "any", "required": False, "multiple": True},
        ],
        "outputs": [
            {"id": "output", "label": "归档路径", "type": "any"},
        ],
        "defaultConfig": {
            "operation": "copy",
            "targetType": "output",
            "customPath": "",
            "useSubfolder": False,
            "subfolderNaming": "by_name",
            "renameEnabled": False,
            "renameMode": "seq",
            "prefix": "",
            "suffix": "",
        },
        "configFields": [
            {
                "key": "operation", "label": "归档操作", "type": "select", "colSpan": "half",
                "options": [
                    {"value": "copy", "label": "复制"},
                    {"value": "move", "label": "剪切"},
                ],
            },
            {
                "key": "targetType", "label": "目标文件夹", "type": "select", "colSpan": "half",
                "options": [
                    {"value": "output", "label": "任务 output 目录"},
                    {"value": "custom", "label": "自定义路径"},
                ],
            },
            {
                "key": "customPath", "label": "自定义目标路径", "type": "text",
                "placeholder": "相对任务目录（如 archive/clips）或绝对路径",
                "description": "支持相对任务目录（如 archive/clips）或绝对路径",
                "dependsOn": "targetType", "dependsValue": "custom", "colSpan": "full",
            },
            {
                "key": "useSubfolder", "label": "新建文件夹存放", "type": "toggle",
                "description": "勾选后在目标目录内新建子文件夹存放归档文件", "colSpan": "full",
            },
            {
                "key": "subfolderNaming", "label": "子文件夹命名", "type": "select", "colSpan": "full",
                "options": [
                    {"value": "by_name", "label": "以文件名新建"},
                    {"value": "seq", "label": "三位数序号自动升序"},
                ],
                "dependsOn": "useSubfolder", "dependsValue": True,
            },
            {
                "key": "renameEnabled", "label": "文件重命名", "type": "toggle",
                "description": "勾选后对归档文件进行重命名", "colSpan": "full",
            },
            {
                "key": "renameMode", "label": "重命名方式", "type": "select", "colSpan": "half",
                "options": [
                    {"value": "seq", "label": "三位数序号自动编号"},
                    {"value": "prefix", "label": "加指定前缀"},
                    {"value": "suffix", "label": "加指定后缀"},
                ],
                "dependsOn": "renameEnabled", "dependsValue": True,
            },
            {
                "key": "prefix", "label": "前缀", "type": "text", "placeholder": "文件名前缀",
                "dependsOn": "renameMode", "dependsValue": "prefix", "colSpan": "half",
            },
            {
                "key": "suffix", "label": "后缀", "type": "text", "placeholder": "文件名后缀",
                "dependsOn": "renameMode", "dependsValue": "suffix", "colSpan": "half",
            },
        ],
    },
    {
        "id": "ai_punctuate",
        "name": "AI标点补全",
        "execution_domain": "llm",
        "category": "translation",
        "description": "读取 ASR 结果 JSON，对识别全文进行 LLM 标点修复，支持按字数上限分批与上下文重叠处理",
        "icon": "SpellCheck",
        "color": "#10b981",
        "inputs": [
            {"id": "json", "label": "ASR JSON", "type": "json", "required": False, "color": "#6366f1"},
        ],
        "outputs": [
            {"id": "output", "label": "ASR JSON", "type": "json", "color": "#6366f1"},
            {"id": "text", "label": "修复全文TXT", "type": "text", "color": "#8b5cf6"},
        ],
        "defaultConfig": {
            "maxChars": "2000",
            "langSource": "from_asr",
            "manualLang": "",
        },
        "configFields": [
            {
                "key": "maxChars", "label": "LLM请求字数上限", "type": "select", "colSpan": "half",
                "options": [
                    {"value": "1000", "label": "1000 字"},
                    {"value": "2000", "label": "2000 字"},
                    {"value": "3000", "label": "3000 字"},
                    {"value": "4000", "label": "4000 字"},
                    {"value": "8000", "label": "8000 字"},
                ],
            },
            {
                "key": "langSource", "label": "识别语音来源", "type": "select", "colSpan": "half",
                "options": [
                    {"value": "from_input", "label": "来之输入节点"},
                    {"value": "from_asr", "label": "来之asr识别语音"},
                    {"value": "manual", "label": "手动输入"},
                ],
            },
            {
                "key": "manualLang", "label": "语言代码", "type": "text", "placeholder": "如 zh / en",
                "dependsOn": "langSource", "dependsValue": "manual", "colSpan": "half",
            },
        ],
    },
    {
        "id": "ai_subtitle_correct",
        "name": "AI字幕纠错",
        "execution_domain": "llm",
        "category": "translation",
        "description": "读取 ASR JSON，按字数上限切分后请求 LLM（vlf-02）修复识别错误、去除空格并修正标点；专有名词可辅助识别。prompt 可在 Prompt 工程中修改。",
        "icon": "Sparkles",
        "color": "#10b981",
        "inputs": [
            {"id": "json", "label": "ASR JSON", "type": "json", "required": False, "color": "#6366f1"},
        ],
        "outputs": [
            {"id": "output", "label": "ASR JSON", "type": "json", "color": "#6366f1"},
            {"id": "text", "label": "纠错全文TXT", "type": "text", "color": "#8b5cf6"},
        ],
        "defaultConfig": {
            "maxChars": "2000",
            "properNouns": "",
        },
    },
    {
        "id": "platform_download",
        "name": "平台视频下载",
        "execution_domain": "process",
        "category": "network_request",
        "description": "使用 yt-dlp 下载平台视频",
        "icon": "Download",
        "color": "#06b6d4",
        "inputs": [{"id": "url", "label": "URL", "type": "url", "required": True}],
        "outputs": [
            {"id": "video", "label": "视频", "type": "video"},
            {"id": "subtitle", "label": "字幕", "type": "subtitle"},
            {"id": "image", "label": "封面", "type": "image"},
            {"id": "filename", "label": "下载文件名", "type": "text"},
        ],
        "defaultConfig": {"download_subs": False, "download_cover": False, "resolution": "best", "cookie_file": "", "use_as_task_name": False},
        "configFields": [
            {"key": "download_subs", "label": "下载字幕", "type": "checkbox"},
            {"key": "download_cover", "label": "下载封面", "type": "checkbox"},
            {"key": "use_as_task_name", "label": "记录为任务名称", "type": "checkbox", "colSpan": "full"},
            {"key": "resolution", "label": "下载分辨率", "type": "select", "options": [
                {"value": "best", "label": "最佳质量"},
                {"value": "1080p", "label": "1080P"},
                {"value": "720p", "label": "720P"},
            ]},
            {"key": "cookie_file", "label": "Cookie 文件", "type": "file", "placeholder": "选择 cookie.txt 文件（可选）", "fileFilter": ["txt"]},
        ],
    },
    {
        "id": "extract_audio",
        "name": "音频分离",
        "execution_domain": "thread",
        "category": "audio",
        "description": "从视频中分离提取音频",
        "icon": "Music",
        "color": "#10b981",
        "inputs": [{"id": "video", "label": "视频", "type": "video", "required": True}],
        "outputs": [{"id": "audio", "label": "音频", "type": "audio"}],
        "defaultConfig": {"format": "auto"},
        "configFields": [
            {"key": "format", "label": "保存格式", "type": "select", "colSpan": "half", "options": [
                {"value": "auto", "label": "源质量 (流复制)"},
                {"value": "wav", "label": "WAV (无损)"},
                {"value": "mp3", "label": "MP3"},
                {"value": "m4a", "label": "M4A (AAC)"},
                {"value": "flac", "label": "FLAC (无损)"},
                {"value": "ogg", "label": "OGG"},
            ]},
        ],
    },
    {
        "id": "vocal_separation",
        "name": "人声分离",
        "execution_domain": "process",
        "category": "audio",
        "description": "将音频中的人声和背景音乐分离",
        "icon": "Mic2",
        "color": "#8b5cf6",
        "inputs": [{"id": "audio", "label": "音频", "type": "audio", "required": True}],
        "outputs": [
            {"id": "audio", "label": "人声", "type": "audio", "color": "#10b981"},
            {"id": "background", "label": "背景音乐", "type": "audio", "color": "#f59e0b"},
        ],
        "defaultConfig": {"method": "spleeter", "model": "", "format": "wav"},
        "configFields": [
            {"key": "method", "label": "分离接口", "type": "api-select", "apiEndpoint": "/api/separation-interfaces/enabled", "optionLabel": "name", "optionValue": "id", "colSpan": "full"},
            {"key": "model", "label": "分离模型", "type": "api-select", "apiEndpoint": "/api/separation-interfaces/config-fields?scope=vocal", "dependsOn": "method", "optionLabel": "label", "optionValue": "value", "placeholder": "留空则使用接口默认模型", "colSpan": "full"},
            {"key": "format", "label": "输出格式", "type": "select", "colSpan": "half", "options": [
                {"value": "", "label": "跟随全局设置"},
                {"value": "wav", "label": "WAV (无损)"},
                {"value": "mp3", "label": "MP3"},
            ]},
        ],
    },
    {
        "id": "track_separation",
        "name": "音轨分离",
        "execution_domain": "process",
        "category": "audio",
        "description": "将音频分离为6轨：人声/贝斯/鼓/吉他/钢琴/其他",
        "icon": "Music2",
        "color": "#8b5cf6",
        "inputs": [{"id": "audio", "label": "音频", "type": "audio", "required": True}],
        "outputs": [
            {"id": "vocals", "label": "人声", "type": "audio"},
            {"id": "bass", "label": "贝斯", "type": "audio"},
            {"id": "drums", "label": "鼓", "type": "audio"},
            {"id": "guitar", "label": "吉他", "type": "audio"},
            {"id": "piano", "label": "钢琴", "type": "audio"},
            {"id": "other", "label": "其他", "type": "audio"},
        ],
        "defaultConfig": {"method": "demucs", "model": "htdemucs_6s", "format": "wav"},
        "configFields": [
            {"key": "method", "label": "分离接口", "type": "api-select", "apiEndpoint": "/api/separation-interfaces/enabled", "optionLabel": "name", "optionValue": "id", "colSpan": "full"},
            {"key": "model", "label": "分离模型", "type": "api-select", "apiEndpoint": "/api/separation-interfaces/config-fields", "dependsOn": "method", "optionLabel": "label", "optionValue": "value", "placeholder": "留空则使用接口默认模型", "colSpan": "full"},
            {"key": "format", "label": "输出格式", "type": "select", "colSpan": "half", "options": [
                {"value": "wav", "label": "WAV (无损)"},
                {"value": "mp3", "label": "MP3"},
            ]},
        ],
    },
    {
        "id": "audio_enhance",
        "name": "音频增强",
        "execution_domain": "process",
        "category": "audio",
        "description": "通过音频增强接口/模型处理音频（去混响、降噪、音质增强），输出增强后的音频",
        "icon": "Sparkles",
        "color": "#0ea5e9",
        "inputs": [{"id": "audio", "label": "音频", "type": "audio", "required": True}],
        "outputs": [
            {"id": "audio", "label": "增强音频", "type": "audio", "color": "#10b981"},
            {"id": "background", "label": "残差/副产物", "type": "audio", "color": "#f59e0b"},
            {"id": "extra", "label": "第三路输出", "type": "audio", "color": "#6366f1"},
        ],
        "defaultConfig": {"method": "mdx_net_onnx", "model": "", "format": "wav"},
        "configFields": [
            {"key": "method", "label": "增强接口", "type": "api-select", "apiEndpoint": "/api/separation-interfaces/enabled?scope=enhancement", "optionLabel": "name", "optionValue": "id", "colSpan": "full"},
            {"key": "model", "label": "增强模型", "type": "api-select", "apiEndpoint": "/api/separation-interfaces/config-fields?scope=enhancement", "dependsOn": "method", "optionLabel": "label", "optionValue": "value", "placeholder": "留空则使用接口的默认增强模型", "colSpan": "full"},
            {"key": "format", "label": "输出格式", "type": "select", "colSpan": "half", "options": [
                {"value": "", "label": "跟随全局设置"},
                {"value": "wav", "label": "WAV (无损)"},
                {"value": "mp3", "label": "MP3"},
            ]},
        ],
    },
    {
        "id": "audio_transcode",
        "name": "音频质量转码",
        "execution_domain": "thread",
        "category": "audio",
        "description": "转换音频格式、采样率、位深、声道和码率",
        "icon": "AudioLines",
        "color": "#0ea5e9",
        "inputs": [{"id": "audio", "label": "音频", "type": "audio", "required": True}],
        "outputs": [{"id": "audio", "label": "转码音频", "type": "audio"}],
        "defaultConfig": {"format": "wav", "sample_rate": "", "bit_depth": "", "channels": "", "bitrate": ""},
        "configFields": [
            {"key": "format", "label": "输出格式", "type": "select", "options": [
                {"value": "wav", "label": "WAV (无损)"},
                {"value": "mp3", "label": "MP3"},
                {"value": "flac", "label": "FLAC (无损)"},
                {"value": "m4a", "label": "M4A"},
            ]},
            {"key": "sample_rate", "label": "采样率", "type": "select", "colSpan": "half", "options": [
                {"value": "", "label": "跟随全局设置"},
                {"value": "16000", "label": "16000 Hz ★推荐（语音识别/ASR）"},
                {"value": "44100", "label": "44100 Hz ★推荐（标准/人声分离）"},
                {"value": "48000", "label": "48000 Hz"},
            ]},
            {"key": "bit_depth", "label": "位深", "type": "select", "colSpan": "half", "options": [
                {"value": "", "label": "跟随全局设置"},
                {"value": "16", "label": "16 bit ★推荐"},
                {"value": "24", "label": "24 bit"},
            ]},
            {"key": "channels", "label": "声道", "type": "select", "colSpan": "half", "options": [
                {"value": "", "label": "跟随全局设置"},
                {"value": "1", "label": "单声道 ★推荐（语音）"},
                {"value": "2", "label": "立体声"},
            ]},
            {"key": "bitrate", "label": "码率 (kbps)", "type": "select", "colSpan": "half", "options": [
                {"value": "", "label": "跟随全局设置"},
                {"value": "128", "label": "128 kbps"},
                {"value": "192", "label": "192 kbps ★推荐"},
                {"value": "256", "label": "256 kbps"},
                {"value": "320", "label": "320 kbps"},
            ]},
        ],
    },
    {
        "id": "asr",
        "name": "语音识别 (ASR)",
        "execution_domain": "process",
        "category": "translation",
        "description": "从音频/视频中提取文字，支持 WhisperX / Qwen3-ASR 等引擎",
        "icon": "Mic",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "asr_audio", "label": "ASR音源", "type": "audio", "required": True},
            {"id": "vocal_audio", "label": "人声音源", "type": "audio"},
        ],
        "outputs": [{"id": "subtitle", "label": "ASR结果JSON", "type": "json"}],
        "defaultConfig": {
            "engine": "",
            "language": "auto",
            "model": "",
            "compute_type": "",
            "batch_size": 0,
            "word_timestamps": True,
            "vad_onset": 0.500,
            "vad_offset": 0.363,
            "hotwords_enabled": False,
            "hotwords": "",
            "post_vad": True,
            "post_alignment": True,
            "post_diarization": False,
        },
        "configFields": [
            {"key": "engine", "label": "ASR 引擎", "type": "api-select", "colSpan": "half", "apiEndpoint": "/api/asr-interfaces/enabled", "placeholder": "跟随全局配置"},
            {"key": "language", "label": "识别语言", "type": "select", "colSpan": "half", "placeholder": "跟随输入节点", "options": [
                {"value": "from_input", "label": "来自输入节点"},
                {"value": "auto", "label": "自动检测 (auto)"},
                {"value": "zh", "label": "中文 (zh)"},
                {"value": "en", "label": "英语 (en)"},
                {"value": "ja", "label": "日语 (ja)"},
                {"value": "ko", "label": "韩语 (ko)"},
                {"value": "fr", "label": "法语 (fr)"},
                {"value": "de", "label": "德语 (de)"},
                {"value": "es", "label": "西班牙语 (es)"},
                {"value": "pt", "label": "葡萄牙语 (pt)"},
                {"value": "ru", "label": "俄语 (ru)"},
            ]},
            {"key": "model", "label": "模型", "type": "api-select", "colSpan": "half", "apiEndpoint": "/api/asr-interfaces/models", "dependsOn": "engine", "placeholder": "默认"},
            {"key": "compute_type", "label": "计算精度", "type": "api-select", "colSpan": "half", "apiEndpoint": "/api/asr-interfaces/config-fields", "dependsOn": "engine", "placeholder": "跟随全局配置"},
            {"key": "batch_size", "label": "批处理大小", "type": "text", "colSpan": "half", "placeholder": "0=自动检测GPU显存"},
            {"key": "word_timestamps", "label": "启用词级时间戳对齐", "type": "checkbox", "colSpan": "half"},
            {"key": "vad_onset", "label": "VAD 起始阈值", "type": "text", "colSpan": "half", "placeholder": "0.500"},
            {"key": "vad_offset", "label": "VAD 结束阈值", "type": "text", "colSpan": "half", "placeholder": "0.363"},
            {"key": "hotwords_enabled", "label": "附加热词", "type": "checkbox", "colSpan": "half"},
            {"key": "hotwords", "label": "热词", "type": "hotwords", "colSpan": "half", "dependsOn": "hotwords_enabled", "placeholder": "多个热词用;分隔，或点击右侧按钮加载txt文件"},
            {"key": "post_vad", "label": "执行 VAD 断句", "type": "checkbox", "colSpan": "half", "hint": "引擎不内置时按全局设置的 VAD 引擎补执行；不勾选则跳过"},
            {"key": "post_alignment", "label": "执行时间戳对齐", "type": "checkbox", "colSpan": "half", "hint": "引擎不内置时按全局设置的对齐引擎补执行；不勾选则跳过"},
            {"key": "post_diarization", "label": "执行说话人识别", "type": "checkbox", "colSpan": "half", "hint": "引擎不内置时按全局设置的说话人引擎补执行；不勾选则跳过"},
        ],
    },
    {
        "id": "asr_recognize",
        "name": "ASR识别",
        "execution_domain": "process",
        "category": "translation",
        "description": "仅执行语音识别（不执行后处理），输出原始识别结果供下游 ASR后处理 节点继续处理",
        "icon": "Mic",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "asr_audio", "label": "ASR音源", "type": "audio", "required": True},
            {"id": "vocal_audio", "label": "人声音源", "type": "audio"},
        ],
        "outputs": [{"id": "subtitle", "label": "ASR识别结果JSON", "type": "json"}],
        "defaultConfig": {
            "engine": "",
            "language": "auto",
            "model": "",
            "compute_type": "",
            "batch_size": 0,
            "word_timestamps": True,
            "hotwords_enabled": False,
            "hotwords": "",
        },
        "configFields": [
            {"key": "engine", "label": "ASR 引擎", "type": "api-select", "colSpan": "half", "apiEndpoint": "/api/asr-interfaces/enabled", "placeholder": "跟随全局配置"},
            {"key": "language", "label": "识别语言", "type": "select", "colSpan": "half", "placeholder": "跟随输入节点", "options": [
                {"value": "from_input", "label": "来自输入节点"},
                {"value": "auto", "label": "自动检测 (auto)"},
                {"value": "zh", "label": "中文 (zh)"},
                {"value": "en", "label": "英语 (en)"},
                {"value": "ja", "label": "日语 (ja)"},
                {"value": "ko", "label": "韩语 (ko)"},
                {"value": "fr", "label": "法语 (fr)"},
                {"value": "de", "label": "德语 (de)"},
                {"value": "es", "label": "西班牙语 (es)"},
                {"value": "pt", "label": "葡萄牙语 (pt)"},
                {"value": "ru", "label": "俄语 (ru)"},
            ]},
            {"key": "model", "label": "模型", "type": "api-select", "colSpan": "half", "apiEndpoint": "/api/asr-interfaces/models", "dependsOn": "engine", "placeholder": "默认"},
            {"key": "compute_type", "label": "计算精度", "type": "api-select", "colSpan": "half", "apiEndpoint": "/api/asr-interfaces/config-fields", "dependsOn": "engine", "placeholder": "跟随全局配置"},
            {"key": "batch_size", "label": "批处理大小", "type": "text", "colSpan": "half", "placeholder": "0=自动检测GPU显存"},
            {"key": "word_timestamps", "label": "启用词级时间戳对齐", "type": "checkbox", "colSpan": "half"},
            {"key": "hotwords_enabled", "label": "附加热词", "type": "checkbox", "colSpan": "half"},
            {"key": "hotwords", "label": "热词", "type": "hotwords", "colSpan": "half", "dependsOn": "hotwords_enabled", "placeholder": "多个热词用;分隔，或点击右侧按钮加载txt文件"},
        ],
    },
    {
        "id": "audio_asset_library",
        "name": "音频素材库",
        "execution_domain": "process",
        "category": "asset",
        "description": "从 URL、本地路径或晴沐配音谷素材库（ID）获取音频素材，下载/复制到当前工作文件夹；输出素材路径与素材全信息 JSON。",
        "icon": "Music",
        "color": "#a855f7",
        "inputs": [
            {"id": "any", "label": "来源", "type": "any", "required": False}
        ],
        "outputs": [
            {"id": "audio", "label": "素材路径", "type": "audio"},
            {"id": "info", "label": "素材全信息JSON", "type": "json"}
        ],
        "defaultConfig": {
            "source": "",
            "asset_name": ""
        }
    },
    {
        "id": "image_asset_library",
        "name": "图片素材库",
        "execution_domain": "process",
        "category": "asset",
        "description": "从公共图片素材库选择素材（记录素材ID），执行时回查详情并复制到当前工作文件夹；输出素材路径与素材全信息 JSON。",
        "icon": "Image",
        "color": "#74b9ff",
        "inputs": [
            {"id": "any", "label": "来源", "type": "any", "required": False}
        ],
        "outputs": [
            {"id": "image", "label": "素材路径", "type": "image"},
            {"id": "info", "label": "素材全信息JSON", "type": "json"}
        ],
        "defaultConfig": {
            "source": "",
            "asset_name": ""
        }
    },
    {
        "id": "video_asset_library",
        "name": "视频素材库",
        "execution_domain": "process",
        "category": "asset",
        "description": "从公共视频素材库选择素材（记录素材ID），执行时回查详情并复制到当前工作文件夹；输出素材路径与素材全信息 JSON。",
        "icon": "Video",
        "color": "#55efc4",
        "inputs": [
            {"id": "any", "label": "来源", "type": "any", "required": False}
        ],
        "outputs": [
            {"id": "video", "label": "素材路径", "type": "video"},
            {"id": "info", "label": "素材全信息JSON", "type": "json"}
        ],
        "defaultConfig": {
            "source": "",
            "asset_name": ""
        }
    },
    {
        "id": "character_asset_library",
        "name": "角色素材库",
        "execution_domain": "process",
        "category": "asset",
        "description": "从公共角色库选择角色（记录角色ID），执行时回查角色详情并把多视角图文件夹复制到工作目录；输出素材路径（图片文件夹）与角色全信息 JSON。",
        "icon": "UserRound",
        "color": "#fdcb6e",
        "inputs": [
            {"id": "any", "label": "来源", "type": "any", "required": False}
        ],
        "outputs": [
            {"id": "path", "label": "素材路径(图片文件夹)", "type": "filepath"},
            {"id": "info", "label": "素材全信息JSON", "type": "json"}
        ],
        "defaultConfig": {
            "source": "",
            "asset_name": ""
        }
    },
    {
        "id": "voice_asset_library",
        "name": "音色素材库",
        "execution_domain": "process",
        "category": "asset",
        "description": "从晴沐配音谷音色库选择音色（记录音色ID），执行时回查音色详情并把设计样音复制到工作目录；输出素材路径（试听音频）与音色全信息 JSON。",
        "icon": "AudioLines",
        "color": "#a29bfe",
        "inputs": [
            {"id": "any", "label": "来源", "type": "any", "required": False}
        ],
        "outputs": [
            {"id": "audio", "label": "素材路径(试听音频)", "type": "audio"},
            {"id": "info", "label": "素材全信息JSON", "type": "json"}
        ],
        "defaultConfig": {
            "source": "",
            "asset_name": ""
        }
    },
    {
        "id": "material_storage",
        "name": "素材入库",
        "execution_domain": "thread",
        "category": "asset",
        "description": "将接入的视频/图片/音频素材归档到项目公共素材库并写入数据库。后端自动识别素材类型，按前端设置的素材属性（名称/分组标签/自定义标签/描述）入库，支持视频、图片、音频三种类型。",
        "icon": "LibraryBig",
        "color": "#84cc16",
        "inputs": [
            {"id": "media", "label": "素材", "type": "any", "required": False}
        ],
        "outputs": [
            {"id": "material", "label": "素材路径", "type": "any"},
            {"id": "library_ref", "label": "素材库引用", "type": "text"},
            {"id": "asset_type", "label": "素材类型", "type": "text"},
            {"id": "asset_id", "label": "素材ID", "type": "text"}
        ],
        "defaultConfig": {
            "asset_name": "",
            "group_tags": "",
            "custom_tags": "",
            "description": ""
        },
        "configFields": [
            {"key": "asset_name", "label": "素材名称", "type": "text",
             "placeholder": "留空则使用文件名", "description": "入库后在素材库中显示的素材名称"},
            {"key": "group_tags", "label": "分组标签", "type": "text",
             "placeholder": "逗号分隔，如：宣传片,产品", "description": "按分组归类素材，便于素材库筛选"},
            {"key": "custom_tags", "label": "自定义标签", "type": "text",
             "placeholder": "逗号分隔，如：高清,竖屏", "description": "自定义检索标签（音频素材会作为素材标签写入）"},
            {"key": "description", "label": "素材描述", "type": "textarea",
             "placeholder": "对素材的补充说明", "description": "素材的备注信息，入库后记录在素材库"}
        ]
    },
    {
        "id": "voice_character",
        "name": "新建音色角色",
        "execution_domain": "process",
        "category": "asset",
        "description": "LLM 根据角色描述/面板设计生成朗读提示词与TTS指令，合成角色默认音色片段与多情绪片段，并写入配音谷音色库；输出音色ID、主片段音频与全信息JSON。",
        "icon": "UserRoundPlus",
        "color": "#e17055",
        "inputs": [
            {"id": "description", "label": "角色描述文本", "type": "any", "required": False},
            {"id": "design_json", "label": "角色设计JSON", "type": "json", "required": False}
        ],
        "outputs": [
            {"id": "voice_id", "label": "音色ID", "type": "text"},
            {"id": "audio", "label": "音色主片段音频", "type": "audio"},
            {"id": "info", "label": "音色全信息JSON", "type": "json"}
        ],
        "defaultConfig": {
            "design_source": "input",
            "panel": {
                "name": "",
                "age": "",
                "personality": "",
                "dialect": "",
                "occupation_background": "",
                "voice_description": ""
            },
            "tts_mode": "voice_design",
            "interface_id": "voxcpm",
            "reference_audio": "",
            "generate_emotions": False
        }
    },
    {
        "id": "asr_postprocess",
        "name": "ASR后处理",
        "execution_domain": "process",
        "category": "translation",
        "description": "对上游 ASR 结果执行 VAD断句 / 时间戳对齐 / 说话人识别 / 标点恢复，可逐阶段勾选并单独选择模型",
        "icon": "SlidersHorizontal",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "subtitle", "label": "ASR结果JSON", "type": "json", "required": True, "color": "#6366f1"},
            {"id": "asr_audio", "label": "ASR音源", "type": "audio"},
            {"id": "vocal_audio", "label": "人声音源", "type": "audio"},
            {"id": "alignment_audio", "label": "对齐音源", "type": "audio"},
        ],
        "outputs": [{"id": "subtitle", "label": "后处理结果JSON", "type": "json", "color": "#6366f1"}],
        "defaultConfig": {
            "run_vad": True,
            "run_alignment": True,
            "run_diarization": False,
            "force_rerun": False,
            "vad_engine": "",
            "vad_onset": 0.500,
            "vad_offset": 0.363,
            "alignment_engine": "",
            "alignment_model": "",
            "dtype": "",
            "diarize_engine": "",
            "diarize_model": "",
            "num_speakers": "",
            "min_speakers": "",
            "max_speakers": "",
            "run_punctuation": False,
            "punc_engine": "",
        },
        "configFields": [
            {"key": "run_vad", "label": "执行 VAD 断句", "type": "checkbox", "colSpan": "half"},
            {"key": "vad_engine", "label": "VAD 引擎", "type": "select", "colSpan": "half", "dependsOn": "run_vad", "placeholder": "跟随全局设置", "options": [
                {"value": "", "label": "跟随全局设置"},
                {"value": "silero", "label": "Silero"},
                {"value": "fsmn", "label": "FSMN (FunASR)"},
                {"value": "webrtc", "label": "WebRTC"},
            ]},
            {"key": "vad_onset", "label": "VAD 起始阈值", "type": "text", "colSpan": "half", "dependsOn": "run_vad", "placeholder": "0.500"},
            {"key": "vad_offset", "label": "VAD 结束阈值", "type": "text", "colSpan": "half", "dependsOn": "run_vad", "placeholder": "0.363"},
            {"key": "run_alignment", "label": "执行时间戳对齐", "type": "checkbox", "colSpan": "half"},
            {"key": "alignment_engine", "label": "对齐引擎", "type": "select", "colSpan": "half", "dependsOn": "run_alignment", "placeholder": "跟随全局设置", "options": [
                {"value": "", "label": "跟随全局设置"},
                {"value": "whisperx", "label": "WhisperX"},
                {"value": "qwen3", "label": "Qwen3 ForcedAligner"},
                {"value": "funasr", "label": "FunASR CT-Aligner"},
            ]},
            {"key": "alignment_model", "label": "对齐模型", "type": "text", "colSpan": "half", "dependsOn": "run_alignment", "placeholder": "默认模型"},
            {"key": "dtype", "label": "计算精度 (Qwen3)", "type": "select", "colSpan": "half", "dependsOn": "run_alignment", "placeholder": "默认", "options": [
                {"value": "", "label": "默认"},
                {"value": "bfloat16", "label": "bfloat16"},
                {"value": "float16", "label": "float16"},
                {"value": "float32", "label": "float32"},
            ]},
            {"key": "run_diarization", "label": "执行说话人识别", "type": "checkbox", "colSpan": "half"},
            {"key": "diarize_engine", "label": "说话人引擎", "type": "select", "colSpan": "half", "dependsOn": "run_diarization", "placeholder": "跟随全局设置", "options": [
                {"value": "", "label": "跟随全局设置"},
                {"value": "diarize", "label": "Diarize (纯本地/无需Key)"},
                {"value": "pyannote", "label": "Pyannote"},
                {"value": "cam++", "label": "CAM++ (FunASR)"},
            ]},
            {"key": "diarize_model", "label": "说话人模型", "type": "text", "colSpan": "half", "dependsOn": "run_diarization", "placeholder": "默认模型"},
            {"key": "num_speakers", "label": "说话人数(精确)", "type": "text", "colSpan": "half", "dependsOn": "run_diarization", "placeholder": "留空自动"},
            {"key": "min_speakers", "label": "最少说话人数", "type": "text", "colSpan": "half", "dependsOn": "run_diarization", "placeholder": "留空自动"},
            {"key": "max_speakers", "label": "最多说话人数", "type": "text", "colSpan": "half", "dependsOn": "run_diarization", "placeholder": "留空自动"},
            {"key": "run_punctuation", "label": "执行标点恢复", "type": "checkbox", "colSpan": "half", "hint": "智能兜底：文本已有标点或非中英语言时自动跳过"},
            {"key": "punc_engine", "label": "标点恢复引擎", "type": "select", "colSpan": "half", "dependsOn": "run_punctuation", "placeholder": "跟随全局设置", "options": [
                {"value": "", "label": "跟随全局设置"},
                {"value": "ct_punc", "label": "CT-Punc (FunASR)"},
            ]},
            {"key": "force_rerun", "label": "强制重新执行（忽略已有后处理结果）", "type": "checkbox", "hint": "默认关闭：上游结果已含有效 VAD/词级时间戳/说话人标注时自动跳过对应阶段"},
        ],
    },
    {
        "id": "sentence_split",
        "name": "句子分割",
        "execution_domain": "thread",
        "category": "translation",
        "description": "将ASR结果按标点和长度分割为独立句子，保留单词级时间戳",
        "icon": "Scissors",
        "color": "#8b5cf6",
        "inputs": [{"id": "subtitle", "label": "ASR结果JSON", "type": "json", "required": True, "color": "#6366f1"}],
        "outputs": [
            {"id": "subtitle", "label": "分割结果JSON", "type": "json", "color": "#6366f1"},
            {"id": "text", "label": "句子文本", "type": "text", "color": "#8b5cf6"},
        ],
        "defaultConfig": {
            "processing_language": "from_input",
            "max_sentence_length": 30,
            "use_llm_split": True,
            "split_sentence_ends": True,
            "split_clause_breaks": True,
            "merge_min_duration": 0.5,
            "merge_max_gap": 0.5,
            "pause_split_threshold": 1.0,
            "split_on_speaker": False,
            "merge_short_enabled": True,
            "merge_gap_enabled": True,
            "pause_split_enabled": True,
        },
        "configFields": [
            {"key": "processing_language", "label": "处理语言", "type": "select", "options": [
                {"value": "from_input", "label": "来自输入节点"},
                {"value": "auto", "label": "自动检测 (auto)"},
                {"value": "zh", "label": "中文 (zh)"},
                {"value": "en", "label": "英语 (en)"},
                {"value": "ja", "label": "日语 (ja)"},
                {"value": "ko", "label": "韩语 (ko)"},
                {"value": "fr", "label": "法语 (fr)"},
                {"value": "de", "label": "德语 (de)"},
                {"value": "es", "label": "西班牙语 (es)"},
                {"value": "pt", "label": "葡萄牙语 (pt)"},
                {"value": "ru", "label": "俄语 (ru)"},
            ]},
            {"key": "max_sentence_length", "label": "最大句子长度（以中文长度基准设置，其他语言自动按照权重调整）", "type": "text", "placeholder": "默认 30"},
            {"key": "split_sentence_ends", "label": "句末类标点切割", "type": "checkbox", "colSpan": "half", "hint": "按句末标点切割所有句子"},
            {"key": "split_clause_breaks", "label": "句中类标点切割", "type": "checkbox", "colSpan": "half", "hint": "按句中标点继续切割过长句子"},
            {"key": "split_on_speaker", "label": "说话人切换时切割", "type": "checkbox", "hint": "仅当 ASR 含多说话人时生效；单人视频无副作用"},
            {"key": "use_llm_split", "label": "AI兜底切割长句", "type": "checkbox"},
            {"key": "merge_min_duration", "label": "最短句段合并阈值(秒)", "type": "text", "placeholder": "默认 1.0", "colSpan": "half"},
            {"key": "merge_short_enabled", "label": "启用最短句段合并", "type": "checkbox", "colSpan": "half"},
            {"key": "merge_max_gap", "label": "句子间隔小于*秒合并(秒)", "type": "text", "placeholder": "默认 0.5", "colSpan": "half"},
            {"key": "merge_gap_enabled", "label": "启用相邻间隙合并", "type": "checkbox", "colSpan": "half"},
            {"key": "pause_split_threshold", "label": "停顿大于*秒断句(秒)", "type": "text", "placeholder": "默认 2.0", "colSpan": "half"},
            {"key": "pause_split_enabled", "label": "执行", "type": "checkbox", "colSpan": "half"},
        ],
    },
    {
        "id": "sentence_preprocess",
        "name": "断句预处理",
        "execution_domain": "thread",
        "category": "translation",
        "description": "基于全文文本（ASR JSON 或长文本 TXT）按 ASR分段/标点符号/AI 三种方法重新断句，生成更可靠的初始 segments，可选重建句子级时间戳",
        "icon": "Scissors",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "json", "label": "ASR结果JSON", "type": "json", "required": False},
            {"id": "text", "label": "长文本TXT", "type": "text", "required": False},
        ],
        "outputs": [
            {"id": "subtitle", "label": "断句预处理JSON", "type": "json", "color": "#6366f1"},
            {"id": "word_index", "label": "词级时间戳表", "type": "json", "color": "#10b981"},
        ],
        "defaultConfig": {
            "processing_language": "from_input",
            "method": "ai",
            "split_on_speaker": True,
            "llm_max_chars": 5000,
        },
        "configFields": [
            {"key": "processing_language", "label": "处理语言", "type": "select", "options": [
                {"value": "from_input", "label": "来自输入节点"},
                {"value": "auto", "label": "自动检测 (auto)"},
                {"value": "zh", "label": "中文 (zh)"},
                {"value": "en", "label": "英语 (en)"},
                {"value": "ja", "label": "日语 (ja)"},
                {"value": "ko", "label": "韩语 (ko)"},
                {"value": "fr", "label": "法语 (fr)"},
                {"value": "de", "label": "德语 (de)"},
                {"value": "es", "label": "西班牙语 (es)"},
                {"value": "pt", "label": "葡萄牙语 (pt)"},
                {"value": "ru", "label": "俄语 (ru)"},
            ]},
            {"key": "method", "label": "断句预处理方法", "type": "select", "options": [
                {"value": "asr", "label": "ASR分段"},
                {"value": "punct", "label": "标点符号断句"},
                {"value": "ai", "label": "AI断句"},
            ]},
            {"key": "split_on_speaker", "label": "多人会话切割", "type": "checkbox", "hint": "仅当 JSON 输入含多说话人信息时生效"},
            {"key": "llm_max_chars", "label": "LLM请求字数上限", "type": "text", "placeholder": "默认 5000，留空使用全局LLM字数限制"},
        ],
    },
    {
        "id": "asr_result_validate",
        "name": "ASR结果校验",
        "execution_domain": "thread",
        "category": "translation",
        "description": "校验 ASR JSON 中 text / segments / words 的一致性：先校验 text 与压平 segments（去标点空格后顺序匹配），再校验压平 segments 与压平 words。校验通过则原样透传输出，不通过则抛出错误并指明错误点。",
        "icon": "ShieldCheck",
        "color": "#10b981",
        "inputs": [
            {"id": "json", "label": "ASR结果JSON", "type": "json", "required": True}
        ],
        "outputs": [
            {"id": "json", "label": "ASR结果JSON(透传)", "type": "json", "color": "#10b981"}
        ],
        "defaultConfig": {},
        "configFields": []
    },
    {
        "id": "summarize",
        "name": "内容总结",
        "execution_domain": "process",
        "category": "translation",
        "description": "总结上下文、提取术语表",
        "icon": "Brain",
        "color": "#8b5cf6",
        "inputs": [{"id": "text", "label": "句子文本", "type": "text", "required": True}],
        "outputs": [{"id": "subtitle", "label": "总结结果JSON", "type": "json"}],
        "defaultConfig": {"summary_length": 3000, "use_custom_terminology": False, "custom_terminology_file": ""},
        "configFields": [
            {"key": "summary_length", "label": "总结文本长度", "type": "text", "placeholder": "默认 3000 字符"},
            {"key": "use_custom_terminology", "label": "自定义术语表", "type": "toggle", "defaultValue": False,
             "description": "勾选后加载自定义术语表JSON文件，与AI提取的术语合并"},
            {"key": "custom_terminology_file", "label": "术语表JSON文件", "type": "file", "placeholder": "选择术语表JSON文件",
             "fileFilter": ["*.json"]},
        ],
    },
    {
        "id": "translate",
        "name": "逐句翻译",
        "execution_domain": "process",
        "category": "translation",
        "description": "AI驱动的高质量翻译",
        "icon": "Languages",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "subtitle", "label": "切割句子JSON", "type": "json", "required": True},
            {"id": "summary", "label": "总结结果JSON", "type": "json"},
        ],
        "outputs": [
            {"id": "subtitle", "label": "直译结果JSON", "type": "json", "color": "#3b82f6"},
            {"id": "reflect", "label": "反思翻译JSON", "type": "json", "color": "#10b981"},
        ],
        "defaultConfig": {"processing_language": "from_input", "target_language": "from_input", "batch_char_limit": "", "reflect_translate": "follow_global", "translation_style": ""},
        "configFields": [
            {"key": "processing_language", "label": "处理语言", "type": "select", "colSpan": "half", "options": [
                {"value": "from_input", "label": "来自输入节点"},
                {"value": "auto", "label": "自动检测 (auto)"},
                {"value": "zh", "label": "中文 (zh)"},
                {"value": "en", "label": "英语 (en)"},
                {"value": "ja", "label": "日语 (ja)"},
                {"value": "ko", "label": "韩语 (ko)"},
                {"value": "fr", "label": "法语 (fr)"},
                {"value": "de", "label": "德语 (de)"},
                {"value": "es", "label": "西班牙语 (es)"},
                {"value": "pt", "label": "葡萄牙语 (pt)"},
                {"value": "ru", "label": "俄语 (ru)"},
            ]},
            {"key": "target_language", "label": "目标语言", "type": "select", "colSpan": "half", "options": [
                {"value": "from_input", "label": "来自输入节点"},
                {"value": "zh", "label": "中文 (zh)"},
                {"value": "en", "label": "英语 (en)"},
                {"value": "ja", "label": "日语 (ja)"},
                {"value": "ko", "label": "韩语 (ko)"},
                {"value": "fr", "label": "法语 (fr)"},
                {"value": "de", "label": "德语 (de)"},
                {"value": "es", "label": "西班牙语 (es)"},
                {"value": "pt", "label": "葡萄牙语 (pt)"},
                {"value": "ru", "label": "俄语 (ru)"},
            ]},
            {"key": "batch_char_limit", "label": "单批次请求字数上限", "type": "text", "placeholder": "留空则读取全局LLM字数限制"},
            {"key": "reflect_translate", "label": "是否反思翻译", "type": "select", "options": [
                {"value": "follow_global", "label": "跟随全局设置"},
                {"value": "yes", "label": "是"},
                {"value": "no", "label": "否"},
            ]},
            {"key": "translation_style", "label": "翻译风格", "type": "text", "placeholder": "留空则使用全局设置"},
        ],
    },
    {
        "id": "subtitle_gen",
        "name": "字幕生成",
        "execution_domain": "thread",
        "category": "translation",
        "description": "兼容句子分割、逐句翻译、双语对齐结果并生成字幕文件",
        "icon": "FileText",
        "color": "#8b5cf6",
        "inputs": [{"id": "subtitle", "label": "句子/翻译/对齐JSON", "type": "json", "required": True}],
        "outputs": [
            {"id": "subtitle", "label": "译文字幕", "type": "subtitle"},
            {"id": "original", "label": "原文字幕", "type": "subtitle"},
            {"id": "bilingual", "label": "双语字幕", "type": "subtitle"},
        ],
        "defaultConfig": {
            "file_prefix": "",
            "filter_punctuation": False,
            "punctuation_replace_mode": "space",
            "processing_language": "from_source",
        },
        "configFields": [
            {"key": "file_prefix", "label": "文件名前缀", "type": "text", "placeholder": "可选，如 video1_"},
            {"key": "filter_punctuation", "label": "是否过滤标点", "type": "checkbox"},
            {
                "key": "punctuation_replace_mode",
                "label": "标点替换模式",
                "type": "select",
                "dependsOn": "filter_punctuation",
                "options": [
                    {"value": "space", "label": "空格"},
                    {"value": "remove", "label": "去除"},
                ],
            },
            {
                "key": "processing_language",
                "label": "处理语言",
                "type": "select",
                "dependsOn": "filter_punctuation",
                "options": [
                    {"value": "from_source", "label": "来自输入的源语言"},
                    {"value": "from_target", "label": "来自输入的目标语言"},
                    {"value": "auto", "label": "自动检测 (auto)"},
                    {"value": "zh", "label": "中文 (zh)"},
                    {"value": "en", "label": "英语 (en)"},
                    {"value": "ja", "label": "日语 (ja)"},
                    {"value": "ko", "label": "韩语 (ko)"},
                    {"value": "fr", "label": "法语 (fr)"},
                    {"value": "de", "label": "德语 (de)"},
                    {"value": "es", "label": "西班牙语 (es)"},
                    {"value": "pt", "label": "葡萄牙语 (pt)"},
                    {"value": "ru", "label": "俄语 (ru)"},
                ],
            },
        ],
    },
    {
        "id": "dub_task",
        "name": "生成配音任务",
        "execution_domain": "thread",
        "category": "translation",
        "description": "将带时间戳的句子 JSON 包装为可编辑的 TTS 任务单",
        "icon": "Mic2",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "subtitle", "label": "句子时间戳JSON", "type": "json", "required": False},
            {"id": "text_file", "label": "文本文件", "type": "text", "required": False},
        ],
        "outputs": [
            {"id": "text", "label": "TTS任务单JSON", "type": "json"},
            {"id": "pandas", "label": "TTS任务表", "type": "pandas"},
        ],
        "defaultConfig": {
            "ai_read_tone": False,
            "normalize_chinese_read_text": False,
            "ai_dialect_colloquial": False,
            "dialect_name": "四川话",
            "min_sentence_duration": 0.2,
            "speed_predict_reduce": False,
        },
        "configFields": [
            {"key": "ai_read_tone", "label": "AI设计朗读语气", "type": "checkbox", "description": "启用后由 LLM 为每句补充朗读情绪语气描述"},
            {"key": "normalize_chinese_read_text", "label": "中文朗读文本归一化", "type": "checkbox", "description": "仅在目标朗读语言为中文时生效，将数字、单位、符号等规范化为汉字读法"},
            {"key": "ai_dialect_colloquial", "label": "AI方言口语化", "type": "checkbox", "description": "启用后由 LLM 按方言特色改写朗读文本"},
            {"key": "dialect_name", "label": "方言", "type": "text", "placeholder": "四川话", "dependsOn": "ai_dialect_colloquial", "description": "填写目标方言名称，启用方言口语化时写入任务单(方言)列"},
            {"key": "speed_predict_reduce", "label": "语速预测+句子缩减", "type": "checkbox", "description": "启用后预测每句 TTS 朗读时长（多语言兼容），预测时长远大于句子时间槽时由 LLM 缩减朗读文本；短句（中文<3字/英文<2词）不缩减"},
            {"key": "min_sentence_duration", "label": "单句最短时长(秒)", "type": "number", "colSpan": "half", "min": 0, "max": 5, "step": 0.05, "defaultValue": 0.2, "description": "执行前单句时长检测阈值：任意单句时长小于该值(秒)将报错，默认0.2秒"},
        ],
    },
    {
        "id": "dub_visual_check",
        "name": "配音审听及微调",
        "execution_domain": "thread",
        "category": "translation",
        "description": "读取上游配音任务 JSON，打开审听页面逐句试听与微调：可修改朗读文本/指令、更换参考音频、按语速重生单条或批量重生；本节点把上游输入 JSON 透传到输出（json），可选等待审听完成后再继续下游。",
        "icon": "ListMusic",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "json", "label": "配音任务JSON", "type": "json", "required": False}
        ],
        "outputs": [
            {"id": "json", "label": "配音任务JSON", "type": "json"}
        ],
        "defaultConfig": {
            "wait_audition": False,
            "wait_seconds": 600,
        },
        "configFields": [
            {"key": "open_check", "label": "打开检查页面", "type": "button",
             "description": "打开配音微调弹窗：分页列出每条配音，支持勾选、试听、更换参考音频、单条/批量重生与 TTS 接口设置"},
            {"key": "wait_audition", "label": "是否等待审听", "type": "checkbox",
             "description": "勾选后本节点进入等待：在检查页完成试听微调，到达等待时长后自动透传输入 JSON 到输出并继续下游"},
            {"key": "wait_seconds", "label": "等待时间（秒）", "type": "number",
             "min": 1, "max": 86400, "colSpan": "half",
             "dependsOn": "wait_audition", "dependsValue": True,
             "placeholder": "600",
             "description": "等待审听的最长时间（秒），到期后自动继续；仅在勾选「是否等待审听」时生效"},
        ],
    },
    {
        "id": "tts",
        "name": "语音合成 (TTS)",
        "execution_domain": "process",
        "category": "ai_gen",
        "description": "文本转语音，支持多种TTS模式",
        "icon": "Volume2",
        "color": "#10b981",
        "inputs": [
            {"id": "text", "label": "TTS任务单JSON", "type": "json", "required": True},
            {"id": "pandas", "label": "TTS任务表", "type": "pandas"},
            {"id": "source_audio", "label": "原始音频(切割参考)", "type": "audio"},
        ],
        "outputs": [
            {"id": "text", "label": "TTS任务单JSON", "type": "json"},
            {"id": "pandas", "label": "TTS任务表", "type": "pandas"},
        ],
        "defaultConfig": {
            "tts_mode": ["preset_voice"],
            "tts_engine": "",
            "clone_source": "fixed",
            "cc_colloquial_desc": "",
            "ref_audio_path": "",
            "ref_audio_role_1": "",
            "ref_audio_role_2": "",
            "ref_audio_role_3": "",
            "ref_audio_role_4": "",
            "voice_role_1": "",
            "voice_role_2": "",
            "voice_role_3": "",
            "voice_role_4": "",
            "voice_design_role_1_desc": "",
            "voice_design_role_2_desc": "",
            "voice_design_role_3_desc": "",
            "voice_design_role_4_desc": "",
            "speed_regenerate": True,
            "speed_rounds": 1,
            "ai_subtitle_reduction": True,
            "ai_rounds": 1,
            "overwrite_generate": False,
        },
        "configFields": [
            {"key": "tts_mode", "label": "TTS 模式", "type": "chips", "singleSelect": True, "chipColor": "#10b981", "options": [
                {"value": "preset_voice", "label": "预置角色"},
                {"value": "clone", "label": "克隆"},
                {"value": "controllable_clone", "label": "指令克隆"},
                {"value": "voice_design", "label": "音色设计"},
            ]},
            {"key": "tts_engine", "label": "配音引擎", "type": "api-select", "dependsOn": "tts_mode", "apiEndpoint": "/api/tts-interfaces/by-mode/{tts_mode}", "placeholder": "跟随全局配置", "optionLabel": "name", "optionValue": "id"},
            {"key": "clone_source", "label": "克隆音频来源", "type": "select", "dependsOn": "tts_mode", "dependsAnyValues": ["clone", "controllable_clone"], "options": [
                {"value": "fixed", "label": "固定克隆音频"},
                {"value": "multi_role", "label": "多角色模式"},
                {"value": "per_segment", "label": "原文逐段参考"},
            ]},
            {"key": "ref_audio_path", "label": "参考音频路径", "type": "audio-selector", "dependsOn": "clone_source", "dependsValue": "fixed", "placeholder": "选择参考音频文件", "fileFilter": ["wav", "mp3", "flac", "ogg"]},
            {"key": "cc_colloquial_desc", "label": "口语化描述", "type": "text", "dependsOn": "tts_mode", "dependsAnyValues": ["controllable_clone"], "placeholder": "例如：用四川话说", "colSpan": "full",
             "description": "拼接在可控克隆指令最前面，自动补逗号分隔；留空不拼接"},
            {"key": "ref_audio_role_1", "label": "角色1参考音频", "type": "audio-selector", "dependsOn": "clone_source", "dependsValue": "multi_role", "placeholder": "角色1的参考音频", "fileFilter": ["wav", "mp3", "flac", "ogg"]},
            {"key": "ref_audio_role_2", "label": "角色2参考音频", "type": "audio-selector", "dependsOn": "clone_source", "dependsValue": "multi_role", "placeholder": "角色2的参考音频", "fileFilter": ["wav", "mp3", "flac", "ogg"]},
            {"key": "ref_audio_role_3", "label": "角色3参考音频", "type": "audio-selector", "dependsOn": "clone_source", "dependsValue": "multi_role", "placeholder": "角色3的参考音频", "fileFilter": ["wav", "mp3", "flac", "ogg"]},
            {"key": "ref_audio_role_4", "label": "角色4参考音频", "type": "audio-selector", "dependsOn": "clone_source", "dependsValue": "multi_role", "placeholder": "角色4的参考音频", "fileFilter": ["wav", "mp3", "flac", "ogg"]},
            {"key": "voice_role_1", "label": "朗读者1音色", "type": "api-select", "dependsOn": "tts_mode", "dependsAnyValues": ["preset_voice"], "apiEndpoint": "/api/tts-interfaces/{tts_engine}/voices", "placeholder": "选择音色"},
            {"key": "voice_role_2", "label": "朗读者2音色", "type": "api-select", "dependsOn": "tts_mode", "dependsAnyValues": ["preset_voice"], "apiEndpoint": "/api/tts-interfaces/{tts_engine}/voices", "placeholder": "选择音色"},
            {"key": "voice_role_3", "label": "朗读者3音色", "type": "api-select", "dependsOn": "tts_mode", "dependsAnyValues": ["preset_voice"], "apiEndpoint": "/api/tts-interfaces/{tts_engine}/voices", "placeholder": "选择音色"},
            {"key": "voice_role_4", "label": "朗读者4音色", "type": "api-select", "dependsOn": "tts_mode", "dependsAnyValues": ["preset_voice"], "apiEndpoint": "/api/tts-interfaces/{tts_engine}/voices", "placeholder": "选择音色"},
            {"key": "voice_design_role_1_desc", "label": "角色1音色描述", "type": "text", "dependsOn": "tts_mode", "dependsAnyValues": ["voice_design"], "placeholder": "描述角色1的音色特征"},
            {"key": "voice_design_role_2_desc", "label": "角色2音色描述", "type": "text", "dependsOn": "tts_mode", "dependsAnyValues": ["voice_design"], "placeholder": "描述角色2的音色特征"},
            {"key": "voice_design_role_3_desc", "label": "角色3音色描述", "type": "text", "dependsOn": "tts_mode", "dependsAnyValues": ["voice_design"], "placeholder": "描述角色3的音色特征"},
            {"key": "voice_design_role_4_desc", "label": "角色4音色描述", "type": "text", "dependsOn": "tts_mode", "dependsAnyValues": ["voice_design"], "placeholder": "描述角色4的音色特征"},
            {"key": "speed_regenerate", "label": "调速重生成", "type": "toggle", "defaultValue": True,
             "description": "配音后检查时长是否超出允许倍率，超出则带speed参数重新配音"},
            {"key": "speed_rounds", "label": "调速轮次", "type": "number", "defaultValue": 1, "min": 0, "max": 5, "step": 1, "inline": True,
             "description": "调速重生成的执行轮次，每轮都会重新检查并调整超出时间槽的配音"},
            {"key": "ai_subtitle_reduction", "label": "AI缩减字幕兜底", "type": "toggle", "defaultValue": True,
             "description": "调速重配后仍超时长的句子，调用LLM缩减朗读文本并重新配音"},
            {"key": "ai_rounds", "label": "缩减轮次", "type": "number", "defaultValue": 1, "min": 0, "max": 5, "step": 1, "inline": True,
             "description": "AI缩减字幕的执行轮次，每轮都会重新检查并缩减超出时间槽的文本"},
            {"key": "overwrite_generate", "label": "覆盖已有音频", "type": "toggle", "defaultValue": False,
             "description": "勾选后即使音频文件已存在也会重新生成，不勾选则跳过已存在的音频"},
        ],
    },
    {
        "id": "merge_sub_video",
        "name": "字幕烧录",
        "execution_domain": "thread",
        "category": "video",
        "description": "将字幕烧录到视频",
        "icon": "Film",
        "color": "#3b82f6",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": True},
            {"id": "subtitle", "label": "字幕", "type": "subtitle", "required": True},
            {"id": "audio", "label": "背景音乐", "type": "audio"},
            {"id": "dub", "label": "配音音频", "type": "audio"},
        ],
        "outputs": [{"id": "video", "label": "字幕视频", "type": "video"}],
        "defaultConfig": {"video_quality": "medium", "mute_original": False, "bgm_volume": 0.3, "dub_volume": 0.8, "fade_in": 0.5, "fade_out": 0.5},
        "configFields": [
            {"key": "preset_id", "label": "字幕样式预设", "type": "api-select", "apiUrl": "/api/subtitle-presets", "optionLabel": "name", "optionValue": "name", "description": "选择字幕样式预设，留空使用全局配置"},
            {"key": "mute_original", "label": "原视频静音", "type": "checkbox", "colSpan": "half", "description": "烧录字幕时是否将原视频音频静音"},
            {"key": "video_quality", "label": "视频质量", "type": "select", "colSpan": "half", "options": [
                {"label": "原始质量(copy)", "value": "copy"},
                {"label": "高质量(CRF18)", "value": "high"},
                {"label": "中等(CRF23)", "value": "medium"},
                {"label": "低质量(CRF28)", "value": "low"},
            ], "description": "视频编码质量，copy为原始质量（有字幕时自动回退到中等）"},
            {"key": "bgm_path", "label": "BGM 路径", "type": "text", "description": "背景音乐文件路径，留空则不混入BGM"},
            {"key": "dub_path", "label": "配音路径", "type": "text", "description": "配音音频文件路径，留空则不混入配音"},
            {"key": "bgm_volume", "label": "BGM 音量", "type": "slider", "colSpan": "half", "min": 0, "max": 1, "step": 0.05, "description": "背景音乐音量 (0~1)"},
            {"key": "dub_volume", "label": "配音响度", "type": "slider", "colSpan": "half", "min": 0, "max": 1, "step": 0.05, "description": "配音音量 (0~1)"},
            {"key": "fade_in", "label": "淡入(秒)", "type": "number", "colSpan": "half", "min": 0, "max": 10, "step": 0.1, "description": "配音淡入时间"},
            {"key": "fade_out", "label": "淡出(秒)", "type": "number", "colSpan": "half", "min": 0, "max": 10, "step": 0.1, "description": "配音淡出时间"},
        ],
    },
    {
        "id": "merge_audio",
        "name": "音视频配音对齐",
        "execution_domain": "thread",
        "category": "audio",
        "description": "基于原视频重新配音后，将配音片段按时间戳对齐到原视频的配音音视频对齐",
        "icon": "Merge",
        "color": "#10b981",
        "inputs": [
            {"id": "audio_manifest", "label": "配音任务清单", "type": "json", "required": True},
            {"id": "video", "label": "输入视频", "type": "video"},
        ],
        "outputs": [
            {"id": "audio", "label": "合并音频", "type": "audio"},
            {"id": "dub_srt", "label": "配音字幕", "type": "subtitle"},
            {"id": "dub_bilingual_srt", "label": "双语字幕", "type": "subtitle"},
            {"id": "video_adjusted", "label": "调速视频", "type": "video"},
        ],
        "defaultConfig": {"video_speed_adjust": False, "speed_min": "", "speed_max": "", "gap_threshold": "", "speed_limit": "", "fast_limit": "", "audio_format": "", "audio_bitrate": ""},
        "configFields": [
            {"key": "speed_min", "label": "音频最小变速倍数", "type": "text", "colSpan": "half", "placeholder": "留空读取全局 video.speed.min，默认 1.0",
             "description": "音频变速的最小倍数，低于此值不加速"},
            {"key": "speed_max", "label": "音频最大变速倍数", "type": "text", "colSpan": "half", "placeholder": "留空读取全局 video.speed.max，默认 1.5",
             "description": "音频变速的最大倍数，超出部分需要视频变速或截断"},
            {"key": "gap_threshold", "label": "说话间隙占用最大比例", "type": "text", "placeholder": "留空读取全局 video.speed.gap_threshold，默认 0.1",
             "description": "允许占用段后间隙的比例 (0~1)，用于扩展可用时长"},
            {"key": "video_speed_adjust", "label": "启用视频变速", "type": "toggle", "defaultValue": False,
             "description": "对缩减后仍超长的片段，对视频进行局部变速以匹配配音时长"},
            {"key": "speed_limit", "label": "视频变速最大倍率", "type": "text", "colSpan": "half", "placeholder": "留空读取全局 video.speed.limit，默认 2.0",
             "description": "视频变速的最大倍率上限"},
            {"key": "fast_limit", "label": "视频减速最小倍率", "type": "text", "colSpan": "half", "placeholder": "留空读取全局 video.speed.fast_limit，默认 2.0",
             "description": "视频局部变速的最小倍率"},
            {"key": "audio_format", "label": "输出音频格式", "type": "select", "colSpan": "half", "options": [
                {"label": "跟随全局设置", "value": ""},
                {"label": "WAV (无损)", "value": "wav"},
                {"label": "MP3", "value": "mp3"},
                {"label": "FLAC (无损压缩)", "value": "flac"},
            ], "description": "配音音频输出格式，留空跟随全局设置"},
            {"key": "audio_bitrate", "label": "音频码率(kbps)", "type": "text", "colSpan": "half", "placeholder": "留空读取全局 audio.bitrate，默认 320",
             "description": "MP3/FLAC 输出码率，WAV 格式忽略此项"},
            {"key": "subtitle_filter_punctuation", "label": "是否过滤标点", "type": "checkbox",
             "description": "勾选后对字幕文本中的标点符号进行过滤/替换"},
            {"key": "subtitle_punctuation_mode", "label": "标点替换模式", "type": "select", "options": [
                {"label": "空格", "value": "space"},
                {"label": "去除", "value": "remove"},
            ], "description": "标点的替换方式：空格=替换为空格，去除=直接删除"},
        ],
    },
    {
        "id": "merge_dub",
        "name": "配音拼接",
        "execution_domain": "thread",
        "category": "audio",
        "description": "适用于无时间戳要求的纯文本配音片段的合并，按顺序拼接各段配音音频并生成配音字幕",
        "icon": "Merge",
        "color": "#14b8a6",
        "inputs": [
            {"id": "audio", "label": "音频片段路径", "type": "audio", "required": False},
            {"id": "audio_manifest", "label": "配音任务单JSON", "type": "json", "required": False},
        ],
        "outputs": [
            {"id": "audio", "label": "合并配音音频", "type": "audio"},
            {"id": "dub_srt", "label": "配音字幕", "type": "subtitle"},
        ],
        "defaultConfig": {"audio_format": "", "audio_bitrate": "", "silence_interval": 0.5},
        "configFields": [
            {"key": "audio_format", "label": "输出音频格式", "type": "select", "colSpan": "half", "options": [
                {"label": "跟随全局设置", "value": ""},
                {"label": "WAV (无损)", "value": "wav"},
                {"label": "MP3", "value": "mp3"},
                {"label": "FLAC (无损压缩)", "value": "flac"},
            ], "description": "合并后配音音频的输出格式，留空跟随全局设置"},
            {"key": "audio_bitrate", "label": "音频码率(kbps)", "type": "text", "colSpan": "half", "placeholder": "留空读取全局 audio.bitrate，默认 320",
             "description": "MP3/FLAC 输出码率，WAV 格式忽略此项"},
            {"key": "silence_interval", "label": "片段间静音间隔(秒)", "type": "number", "defaultValue": 0.5, "min": 0, "max": 10, "step": 0.1,
             "description": "相邻配音片段之间插入的静音时长"},
        ],
    },
    {
        "id": "track_mix",
        "name": "音轨混响",
        "execution_domain": "thread",
        "category": "audio",
        "description": "将最多四路音频（主音轨、背景音乐、音轨3、音轨4）按设置的响度、淡入淡出与循环混合后输出。总时长支持「最长」或「以主音轨为准」两种模式。主音轨固定不循环，其余音轨可循环以填充总时长。",
        "icon": "AudioLines",
        "color": "#10b981",
        "inputs": [
            {"id": "main_audio", "label": "主音轨", "type": "audio", "required": True},
            {"id": "bgm", "label": "背景音乐", "type": "audio"},
            {"id": "track3", "label": "音轨3", "type": "audio"},
            {"id": "track4", "label": "音轨4", "type": "audio"}
        ],
        "outputs": [
            {"id": "audio", "label": "混音结果", "type": "audio", "color": "#10b981"}
        ],
        "defaultConfig": {
            "duration_mode": "longest",
            "main_volume": 1.0,
            "main_fade_in": 0.3,
            "main_fade_out": 0.3,
            "bgm_volume": 0.3,
            "bgm_fade_in": 1.0,
            "bgm_fade_out": 1.0,
            "bgm_loop": True,
            "track3_volume": 0.5,
            "track3_fade_in": 0.3,
            "track3_fade_out": 0.3,
            "track3_loop": False,
            "track4_volume": 0.5,
            "track4_fade_in": 0.3,
            "track4_fade_out": 0.3,
            "track4_loop": False,
            "audio_format": "wav",
            "audio_bitrate": "192"
        },
        "configFields": [
            {"key": "duration_mode", "label": "总时长模式", "type": "select", "colSpan": "full",
             "options": [
                {"label": "最长（以最长音轨为准）", "value": "longest"},
                {"label": "以主音轨为准", "value": "main"}
             ], "description": "输出音频总时长：最长=与最长的输入音轨等长；主音轨=仅与主音轨等长"},
            {"key": "main_volume", "label": "主音轨·响度", "type": "slider", "colSpan": "third", "min": 0, "max": 2, "step": 0.05, "defaultValue": 1.0, "description": "主音轨音量增益（1.0=原始）"},
            {"key": "main_fade_in", "label": "主音轨·淡入(秒)", "type": "number", "colSpan": "third", "min": 0, "max": 30, "step": 0.1, "defaultValue": 0.3},
            {"key": "main_fade_out", "label": "主音轨·淡出(秒)", "type": "number", "colSpan": "third", "min": 0, "max": 30, "step": 0.1, "defaultValue": 0.3},
            {"key": "bgm_volume", "label": "背景音乐·响度", "type": "slider", "colSpan": "third", "min": 0, "max": 2, "step": 0.05, "defaultValue": 0.3},
            {"key": "bgm_fade_in", "label": "背景音乐·淡入(秒)", "type": "number", "colSpan": "third", "min": 0, "max": 30, "step": 0.1, "defaultValue": 1.0},
            {"key": "bgm_fade_out", "label": "背景音乐·淡出(秒)", "type": "number", "colSpan": "third", "min": 0, "max": 30, "step": 0.1, "defaultValue": 1.0},
            {"key": "bgm_loop", "label": "背景音乐·循环", "type": "toggle", "colSpan": "third", "defaultValue": True, "description": "时长不足时循环播放以填充总时长"},
            {"key": "track3_volume", "label": "音轨3·响度", "type": "slider", "colSpan": "third", "min": 0, "max": 2, "step": 0.05, "defaultValue": 0.5},
            {"key": "track3_fade_in", "label": "音轨3·淡入(秒)", "type": "number", "colSpan": "third", "min": 0, "max": 30, "step": 0.1, "defaultValue": 0.3},
            {"key": "track3_fade_out", "label": "音轨3·淡出(秒)", "type": "number", "colSpan": "third", "min": 0, "max": 30, "step": 0.1, "defaultValue": 0.3},
            {"key": "track3_loop", "label": "音轨3·循环", "type": "toggle", "colSpan": "third", "defaultValue": False},
            {"key": "track4_volume", "label": "音轨4·响度", "type": "slider", "colSpan": "third", "min": 0, "max": 2, "step": 0.05, "defaultValue": 0.5},
            {"key": "track4_fade_in", "label": "音轨4·淡入(秒)", "type": "number", "colSpan": "third", "min": 0, "max": 30, "step": 0.1, "defaultValue": 0.3},
            {"key": "track4_fade_out", "label": "音轨4·淡出(秒)", "type": "number", "colSpan": "third", "min": 0, "max": 30, "step": 0.1, "defaultValue": 0.3},
            {"key": "track4_loop", "label": "音轨4·循环", "type": "toggle", "colSpan": "third", "defaultValue": False},
            {"key": "audio_format", "label": "输出格式", "type": "select", "colSpan": "half", "options": [
                {"label": "WAV (无损)", "value": "wav"},
                {"label": "MP3", "value": "mp3"},
                {"label": "FLAC (无损压缩)", "value": "flac"}
            ], "description": "混音输出格式，默认 WAV"},
            {"key": "audio_bitrate", "label": "MP3码率(kbps)", "type": "text", "colSpan": "half", "placeholder": "默认 192",
             "description": "仅 MP3 生效，WAV/FLAC 忽略"}
        ]
    },
    {
        "id": "merge_dub_video",
        "name": "音视频合成",
        "execution_domain": "thread",
        "category": "video",
        "description": "将输入音频合成到视频，可设置原视频是否静音、输入音频的响度与淡入淡出。",
        "icon": "Clapperboard",
        "color": "#3b82f6",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": True},
            {"id": "audio", "label": "音频", "type": "audio", "required": True},
        ],
        "outputs": [{"id": "video", "label": "合成后视频", "type": "video"}],
        "defaultConfig": {
            "video_mute": True,
            "audio_volume": 1.0,
            "audio_fade_in": 0.0,
            "audio_fade_out": 0.0
        },
        "configFields": [
            {"key": "video_mute", "label": "原视频静音", "type": "toggle", "colSpan": "full", "defaultValue": True,
             "description": "开启：仅使用输入音频；关闭：将原视频音轨与输入音频混合"},
            {"key": "audio_volume", "label": "输入音频·响度", "type": "slider", "colSpan": "half", "min": 0, "max": 2, "step": 0.05, "defaultValue": 1.0,
             "description": "输入音频音量增益（1.0=原始）"},
            {"key": "audio_fade_in", "label": "输入音频·淡入(秒)", "type": "number", "colSpan": "half", "min": 0, "max": 30, "step": 0.1, "defaultValue": 0.0},
            {"key": "audio_fade_out", "label": "输入音频·淡出(秒)", "type": "number", "colSpan": "half", "min": 0, "max": 30, "step": 0.1, "defaultValue": 0.0}
        ],
    },
    {
        "id": "video_concat",
        "name": "视频拼接",
        "execution_domain": "thread",
        "category": "video",
        "description": "将主视频/片段1~3/封面图按设定顺序与缩放方式一次性拼装为单个视频，封面图可选插入开头或结尾。",
        "icon": "Clapperboard",
        "color": "#3b82f6",
        "inputs": [
            {"id": "main", "label": "主视频", "type": "video", "required": False},
            {"id": "segment1", "label": "片段1", "type": "video", "required": False},
            {"id": "segment2", "label": "片段2", "type": "video", "required": False},
            {"id": "segment3", "label": "片段3", "type": "video", "required": False},
            {"id": "cover", "label": "封面图", "type": "image", "required": False}
        ],
        "outputs": [{"id": "video", "label": "拼接视频", "type": "video"}],
        "defaultConfig": {
            "segment_order": ["main", "segment1", "segment2", "segment3"],
            "scale_mode": "stretch",
            "cover_position": "start",
            "cover_duration": 3,
            "output_format": "mp4"
        },
        "configFields": [
            {"key": "segment_order", "label": "片段排序", "type": "reorder-list",
             "options": [
                 {"value": "main", "label": "主视频"},
                 {"value": "segment1", "label": "片段1"},
                 {"value": "segment2", "label": "片段2"},
                 {"value": "segment3", "label": "片段3"}
             ],
             "description": "调整主视频与片段1/2/3 的拼接先后顺序（上下箭头排序）"},
            {"key": "scale_mode", "label": "片段尺寸缩放方式", "type": "select", "options": [
                 {"value": "stretch", "label": "拉伸（填满，可能变形）"},
                 {"value": "crop", "label": "裁切（等比覆盖，裁剪多余）"}
             ], "description": "各片段统一缩放到参考视频分辨率的方式"},
            {"key": "cover_position", "label": "封面图位置", "type": "select", "options": [
                 {"value": "none", "label": "不插入"},
                 {"value": "start", "label": "开头"},
                 {"value": "end", "label": "结尾"}
             ]},
            {"key": "cover_duration", "label": "封面时长(秒)", "type": "number", "min": 0.1, "max": 60,
             "colSpan": "half", "dependsOn": "cover_position", "dependsValue": ["start", "end"],
             "placeholder": "3"},
            {"key": "output_format", "label": "输出格式", "type": "select", "colSpan": "half", "options": [
                 {"value": "mp4", "label": "MP4"},
                 {"value": "mkv", "label": "MKV"},
                 {"value": "mov", "label": "MOV"},
                 {"value": "webm", "label": "WebM"},
                 {"value": "avi", "label": "AVI"}
             ]}
        ],
    },
    {
        "id": "cover",
        "name": "AI封面设计",
        "execution_domain": "thread",
        "category": "ai_gen",
        "description": "根据内容JSON生成封面文生图提示词，支持AI设计和自定义描述两种模式",
        "icon": "Image",
        "color": "#ec4899",
        "inputs": [{"id": "json", "label": "内容JSON", "type": "json", "required": True}],
        "outputs": [{"id": "prompt", "label": "封面提示词", "type": "text"}],
        "defaultConfig": {
            "custom_title_enabled": False,
            "custom_title": "",
            "custom_subtitle_enabled": False,
            "custom_subtitle": "",
            "design_mode": "ai_design",
            "ai_prompt": "你是一位专业的短视频封面设计师和文生图提示词专家。请根据以下视频内容信息，设计一张吸引人的短视频封面画面，并输出详细的文生图提示词。\n\n要求：\n1. 画面风格：适合短视频平台的视觉风格，色彩鲜明、对比强烈，具有视觉冲击力\n2. 标题字体：主标题使用粗体大字，醒目突出，字体风格与内容主题匹配\n3. 标题颜色：根据画面整体色调选择高对比度的颜色，确保可读性\n4. 标题位置：主标题居中或偏上，副标题在主标题下方，不遮挡画面主体\n5. 背景融合：标题与背景自然融合，可使用阴影、描边或半透明底色增强可读性\n6. 画面构图：简洁大气，留出标题空间，主体突出\n\n请直接输出文生图提示词（英文），不需要额外解释。提示词应包含画面描述、风格、色调、构图、文字排版等完整信息。",
            "custom_prompt": "A visually striking short video cover image, cinematic style, vibrant colors, bold composition. Main title \"{title}\" displayed prominently in large bold white text with dark shadow, centered upper area. Subtitle \"{subtitle}\" in smaller elegant font below the main title. Dynamic background with rich textures and depth of field, professional digital art quality, 4K resolution.",
        },
        "configFields": [
            {"key": "custom_title_enabled", "label": "自定义标题", "type": "checkbox", "colSpan": "half"},
            {"key": "custom_title", "label": "标题文本", "type": "text", "placeholder": "输入自定义标题", "dependsOn": "custom_title_enabled", "dependsValue": True},
            {"key": "custom_subtitle_enabled", "label": "自定义副标题", "type": "checkbox", "colSpan": "half"},
            {"key": "custom_subtitle", "label": "副标题文本", "type": "text", "placeholder": "输入自定义副标题", "dependsOn": "custom_subtitle_enabled", "dependsValue": True},
            {"key": "design_mode", "label": "封面设计模式", "type": "chips", "singleSelect": True, "chipColor": "#ec4899", "options": [
                {"value": "ai_design", "label": "AI设计封面"},
                {"value": "custom_prompt", "label": "自定义描述"},
            ]},
            {"key": "ai_prompt", "label": "AI设计封面提示词", "type": "textarea", "placeholder": "留空使用默认提示词...", "dependsOn": "design_mode", "dependsValue": "ai_design"},
            {"key": "custom_prompt", "label": "文生图提示词", "type": "textarea", "placeholder": "输入文生图提示词，使用 {title} 和 {subtitle} 引用标题...", "dependsOn": "design_mode", "dependsValue": "custom_prompt", "chips": [{"value": "{title}", "label": "主标题"}, {"value": "{subtitle}", "label": "副标题"}]},
        ],
    },
    {
        "id": "watermark",
        "name": "水印添加",
        "execution_domain": "thread",
        "category": "video",
        "description": "为视频添加水印",
        "icon": "Stamp",
        "color": "#6b7280",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": True},
            {"id": "image", "label": "水印图片", "type": "image"},
        ],
        "outputs": [{"id": "video", "label": "最终视频", "type": "video"}],
        "defaultConfig": {"enabled": False, "position": "bottom-right", "opacity": 0.5},
        "configFields": [
            {"key": "enabled", "label": "启用水印", "type": "checkbox"},
            {"key": "position", "label": "位置", "type": "select", "options": [
                {"value": "top-left", "label": "左上角"},
                {"value": "top-right", "label": "右上角"},
                {"value": "bottom-left", "label": "左下角"},
                {"value": "bottom-right", "label": "右下角"},
                {"value": "center", "label": "居中"},
            ]},
            {"key": "opacity", "label": "透明度", "type": "text", "placeholder": "0.5"},
        ],
    },
    {
        "id": "output",
        "name": "输出",
        "execution_domain": "thread",
        "category": "io",
        "description": "导出文件",
        "icon": "Download",
        "color": "#ef4444",
        "inputs": [{"id": "any", "label": "输入", "type": "any"}],
        "outputs": [],
        "defaultConfig": {"outputDir": "", "fileName": "", "suffix": "", "autoIncrement": True},
        "configFields": [
            {"key": "outputDir", "label": "输出目录", "type": "file", "placeholder": "留空使用默认目录", "fileFilter": []},
            {"key": "fileName", "label": "自定义文件名", "type": "text", "placeholder": "留空使用原文件名"},
            {"key": "suffix", "label": "文件名后缀", "type": "text", "placeholder": "如 _cn、_dubbed"},
            {"key": "autoIncrement", "label": "同名文件自动加序号", "type": "checkbox"},
        ],
    },
    {
        "id": "subtitle_align",
        "name": "译文断句和双语对齐",
        "execution_domain": "thread",
        "category": "translation",
        "description": "对超长译文进行断句并与原文对齐，调整时间戳",
        "icon": "AlignLeft",
        "color": "#8b5cf6",
        "inputs": [{"id": "subtitle", "label": "翻译结果JSON", "type": "json", "required": True}],
        "outputs": [{"id": "subtitle", "label": "对齐结果JSON", "type": "json"}],
        "defaultConfig": {"max_subtitle_length": 30},
        "configFields": [{"key": "max_subtitle_length", "label": "译文单行最大字符数", "type": "text", "placeholder": "默认 20 字符"}],
    },
    {
        "id": "video_preview",
        "name": "视频预览器",
        "execution_domain": "thread",
        "category": "preview",
        "description": "预览视频和字幕，支持标题设置、快捷调整字体大小和位置",
        "icon": "Play",
        "color": "#14b8a6",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video"},
            {"id": "subtitle", "label": "译文字幕", "type": "subtitle"},
            {"id": "original", "label": "原文字幕", "type": "subtitle"},
            {"id": "bilingual", "label": "双语字幕", "type": "subtitle"},
            {"id": "list", "label": "列表输入", "type": "any", "required": False, "description": "接入列表（如多产物/合并列表节点）时，竖向依次展示多个视频"},
        ],
        "outputs": [],
        "defaultConfig": {
            "title": "",
            "fontSize": 12,
            "fontFamily": "sans-serif",
            "fontColor": "#ffffff",
            "backgroundColor": "rgba(0,0,0,0.6)",
            "subtitlePosition": "bottom",
        },
        "configFields": [],
    },
    {
        "id": "image_preview",
        "name": "图片预览器",
        "execution_domain": "thread",
        "category": "preview",
        "description": "预览图片结果",
        "icon": "Eye",
        "color": "#14b8a6",
        "inputs": [{"id": "image", "label": "图片", "type": "image"}, {"id": "list", "label": "列表输入", "type": "any", "required": False, "description": "接入列表（如多产物/合并列表节点）时，竖向依次展示多张图片"}],
        "outputs": [],
        "defaultConfig": {"fit": "contain"},
        "configFields": [
            {"key": "fit", "label": "适应方式", "type": "select", "options": [
                {"value": "contain", "label": "包含"},
                {"value": "cover", "label": "覆盖"},
                {"value": "fill", "label": "填充"},
                {"value": "none", "label": "原始大小"},
            ]},
        ],
    },
    {
        "id": "image_compare",
        "name": "图片对比",
        "execution_domain": "thread",
        "category": "preview",
        "description": "叠加对比两张图片：图片2在上、图片1在下，鼠标横向拖动分割线去除上层蒙版，快速对比图形差异；默认上层蒙版只显示右半部，分割线居中",
        "icon": "Columns2",
        "color": "#14b8a6",
        "inputs": [
            {"id": "image1", "label": "图片1（下层）", "type": "any", "required": False},
            {"id": "image2", "label": "图片2（上层）", "type": "any", "required": False},
        ],
        "outputs": [
            {"id": "image", "label": "图片", "type": "any"},
        ],
        "defaultConfig": {"fit": "contain"},
        "configFields": [
            {"key": "fit", "label": "适应方式", "type": "select", "options": [
                {"value": "contain", "label": "包含"},
                {"value": "cover", "label": "覆盖"},
                {"value": "fill", "label": "填充"},
                {"value": "none", "label": "原始大小"},
            ]},
        ],
    },
    {
        "id": "llm_request",
        "name": "通用LLM请求",
        "execution_domain": "process",
        "category": "ai_gen",
        "description": "通用 LLM 请求，支持文本/图片输入，可配置 prompt、模型、温度等",
        "icon": "Brain",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "text", "label": "文本输入", "type": "text"},
            {"id": "image", "label": "图片输入", "type": "image"},
            {"id": "json", "label": "JSON输入", "type": "json"},
        ],
        "outputs": [
            {"id": "result", "label": "结果文件", "type": "json"},
            {"id": "text", "label": "文本结果", "type": "text"},
        ],
        "defaultConfig": {
            "model": "",
            "system_prompt": "",
            "user_prompt": "{input_text}",
            "temperature": 0.7,
            "response_json": False,
            "log_request": False,
        },
        "configFields": [
            {"key": "model", "label": "模型名称", "type": "text",
             "placeholder": "留空使用全局默认模型", "colSpan": "half"},
            {"key": "temperature", "label": "温度", "type": "slider",
             "min": 0, "max": 2, "step": 0.1, "colSpan": "half"},
            {"key": "system_prompt", "label": "System Prompt", "type": "textarea",
             "placeholder": "系统提示词..."},
            {"key": "user_prompt", "label": "User Prompt", "type": "textarea",
             "placeholder": "用户提示词，使用 {input_text} 引用文本输入...",
             "chips": [
                 {"value": "{input_text}", "label": "输入文本"},
                 {"value": "{input_json}", "label": "JSON数据"},
                 {"value": "{source_language}", "label": "输入语言"},
                 {"value": "{target_language}", "label": "输出语言"},
             ]},
            {"key": "response_json", "label": "JSON 格式输出", "type": "checkbox", "colSpan": "half"},
            {"key": "log_request", "label": "请求日志打印", "type": "checkbox", "colSpan": "half"},
        ],
    },
    {
        "id": "http_request",
        "name": "网络请求",
        "execution_domain": "process",
        "category": "network_request",
        "description": "执行可配置的 HTTP 网络请求，支持请求体占位符、重试和响应保存",
        "icon": "Globe",
        "color": "#0f766e",
        "inputs": [
            {"id": "input_1", "label": "输入 1", "type": "any", "required": False},
            {"id": "input_2", "label": "输入 2", "type": "any", "required": False},
            {"id": "input_3", "label": "输入 3", "type": "any", "required": False},
            {"id": "request_data", "label": "请求 Data", "type": "json", "required": False},
        ],
        "outputs": [
            {"id": "result", "label": "结果文件", "type": "any"},
            {"id": "json", "label": "JSON 结果", "type": "json"},
            {"id": "text", "label": "文本结果", "type": "text"},
            {"id": "status", "label": "状态码", "type": "text"},
        ],
        "defaultConfig": {
            "request_client": "requests", "url": "", "method": "GET", "headers": "{}", "body_type": "json", "body": "",
            "browser_impersonation": "none", "ignore_connected_inputs": False, "retry_enabled": False, "retry_count": 3,
            "retry_interval": 1, "timeout": 30, "success_status_codes": "200-299", "output_format": "auto",
        },
        "configFields": [
            {"key": "request_client", "label": "请求客户端", "type": "select", "colSpan": "third", "options": [{"value": "requests", "label": "requests 请求"}, {"value": "httpx", "label": "http 请求"}, {"value": "curl", "label": "curl 请求"}]},
            {"key": "method", "label": "请求方法", "type": "select", "colSpan": "third", "options": [{"value": "GET", "label": "GET"}, {"value": "POST", "label": "POST"}, {"value": "PUT", "label": "PUT"}, {"value": "PATCH", "label": "PATCH"}, {"value": "DELETE", "label": "DELETE"}, {"value": "HEAD", "label": "HEAD"}, {"value": "OPTIONS", "label": "OPTIONS"}]},
            {"key": "output_format", "label": "输出格式", "type": "select", "colSpan": "third", "options": [{"value": "auto", "label": "自动识别"}, {"value": "json", "label": "JSON"}, {"value": "text", "label": "文本"}]},
            {"key": "url", "label": "请求 URL", "type": "text", "placeholder": "https://api.example.com/v1/resource"},
            {"key": "headers", "label": "请求头", "type": "textarea", "placeholder": "{\n  \"Authorization\": \"Bearer token\"\n}"},
            {"key": "browser_impersonation", "label": "模拟浏览器", "type": "select", "colSpan": "half", "options": [{"value": "none", "label": "不模拟"}, {"value": "chrome", "label": "Chrome"}, {"value": "edge", "label": "Edge"}, {"value": "firefox", "label": "Firefox"}, {"value": "safari", "label": "Safari"}]},
            {"key": "body_type", "label": "请求体格式", "type": "select", "colSpan": "half", "options": [{"value": "json", "label": "JSON"}, {"value": "text", "label": "文本"}]},
            {"key": "body", "label": "请求体", "type": "textarea", "placeholder": "在请求体中使用下方标签引用连线输入", "chips": [{"value": "{input_1}", "label": "输入 1"}, {"value": "{input_2}", "label": "输入 2"}, {"value": "{input_3}", "label": "输入 3"}, {"value": "{request_data}", "label": "请求 Data"}]},
            {"key": "ignore_connected_inputs", "label": "忽略连线输入", "type": "toggle", "description": "勾选后不会读取任何连线输入"},
            {"key": "retry_enabled", "label": "失败时重试", "type": "toggle", "colSpan": "half"},
            {"key": "retry_count", "label": "重试次数", "type": "number", "min": 0, "max": 20, "colSpan": "half", "dependsOn": "retry_enabled", "dependsValue": True},
            {"key": "retry_interval", "label": "重试间隔（秒）", "type": "number", "min": 0, "max": 300, "colSpan": "half", "dependsOn": "retry_enabled", "dependsValue": True},
            {"key": "timeout", "label": "超时时长（秒）", "type": "number", "min": 1, "max": 1800, "colSpan": "half"},
            {"key": "success_status_codes", "label": "成功状态码", "type": "text", "placeholder": "200-299 或 200,201,2xx", "colSpan": "half"},
        ],
    },
    {
        "id": "image_gen",
        "name": "AI生图",
        "execution_domain": "process",
        "category": "ai_gen",
        "description": "AI图像生成，支持文生图和图生图模式，集成多种生图接口和模型",
        "icon": "Paintbrush",
        "color": "#f59e0b",
        "inputs": [
            {"id": "text", "label": "文本输入", "type": "text"},
            {"id": "image", "label": "图片输入", "type": "image"},
            {"id": "resolution", "label": "分辨率", "type": "text", "required": False},
            {"id": "aspect_ratio", "label": "比例", "type": "text", "required": False},
        ],
        "outputs": [
            {"id": "images", "label": "图片列表", "type": "json"},
            {"id": "text", "label": "首张图片", "type": "image"},
        ],
        "defaultConfig": {
            "mode": "txt2img",
            "interface": "",
            "model": "",
            "resolution": "1K",
            "aspect_ratio": "1:1",
            "num_images": 1,
            "custom_prompt_enabled": False,
            "custom_prompt": "",
            "output_prefix": "img",
        },
        "configFields": [
            {"key": "mode", "label": "生图模式", "type": "chips", "singleSelect": True,
             "chipColor": "#f59e0b",
             "options": [{"value": "txt2img", "label": "文生图"}, {"value": "img2img", "label": "图生图"}, {"value": "fusion", "label": "多图融合"}, {"value": "grid", "label": "组图输出"}, {"value": "i2grid", "label": "单图生组图"}, {"value": "refs2grid", "label": "多参考图生组图"}, {"value": "websearch", "label": "联网搜索生图"}]},
            {"key": "interface", "label": "接口选择", "type": "api-select",
             "apiEndpoint": "/api/imagegen-interfaces/enabled", "optionLabel": "name", "optionValue": "id"},
            {"key": "model", "label": "模型选择", "type": "api-select",
             "apiEndpoint": "/api/imagegen-interfaces/{interface}/models-for-node?mode={mode}",
             "dependsOn": "interface", "placeholder": "请选择模型"},
            {"key": "resolution", "label": "分辨率", "type": "api-select", "colSpan": "half",
             "apiEndpoint": "/api/imagegen-interfaces/{interface}/schema?model={model}",
             "dependsOn": "model", "placeholder": "自动"},
            {"key": "aspect_ratio", "label": "图片比例", "type": "api-select", "colSpan": "half",
             "apiEndpoint": "/api/imagegen-interfaces/{interface}/schema?model={model}",
             "dependsOn": "model", "placeholder": "1:1"},
            {"key": "num_images", "label": "生成数量", "type": "number", "min": 1, "max": 10, "colSpan": "half"},
            {"key": "custom_prompt_enabled", "label": "自定义提示词", "type": "checkbox", "colSpan": "half"},
            {"key": "custom_prompt", "label": "自定义提示词", "type": "textarea",
             "dependsOn": "custom_prompt_enabled", "dependsValue": True,
             "placeholder": "输入自定义生图提示词..."},
            {"key": "output_prefix", "label": "输出文件名前缀", "type": "text", "colSpan": "half",
             "placeholder": "img"},
        ],
    },
    {
        "id": "editor_agent",
        "name": "剪辑AI Agent",
        "execution_domain": "process",
        "category": "agent",
        "description": "接收上游剪辑项目JSON，按编辑指令对时间线二次精选，输出精选后的剪辑json",
        "icon": "Clapperboard",
        "color": "#10b981",
        "inputs": [
            {"id": "project", "label": "剪辑项目", "type": "json"},
            {"id": "text", "label": "编辑指令", "type": "text"},
        ],
        "outputs": [
            {"id": "project", "label": "剪辑项目", "type": "json"},
            {"id": "artifacts", "label": "运行记录", "type": "json"},
            {"id": "result", "label": "执行结果", "type": "text"},
        ],
        "defaultConfig": {
            "instruction": "",
            "expert_role": "auto",
        },
        "configFields": [
            {"key": "instruction", "label": "编辑指令", "type": "textarea", "placeholder": "例如：将配音加入时间线并添加开场标题"},
            {"key": "expert_role", "label": "专家角色", "type": "select", "options": [
                {"value": "auto", "label": "自动导演"},
                {"value": "general", "label": "通用剪辑"},
                {"value": "design", "label": "视觉设计"},
                {"value": "audio", "label": "音频编辑"},
                {"value": "editing", "label": "剪辑顾问"},
                {"value": "storytelling", "label": "叙事导演"},
            ]},
            {"key": "imagegen_iface_id", "label": "生图接口", "type": "api-select", "colSpan": "half",
             "apiEndpoint": "/api/imagegen-interfaces/enabled",
             "placeholder": "自动（按能力选择）"},
            {"key": "imagegen_model", "label": "生图模型", "type": "api-select", "colSpan": "half",
             "dependsOn": "imagegen_iface_id",
             "apiEndpoint": "/api/imagegen-interfaces/{imagegen_iface_id}/models-for-node?mode=txt2img",
             "placeholder": "跟随接口默认"},
            {"key": "videogen_iface_id", "label": "生视频接口", "type": "api-select", "colSpan": "half",
             "apiEndpoint": "/api/videogen-interfaces/enabled",
             "placeholder": "自动（按能力选择）"},
            {"key": "videogen_model", "label": "生视频模型", "type": "api-select", "colSpan": "half",
             "dependsOn": "videogen_iface_id",
             "apiEndpoint": "/api/videogen-interfaces/{videogen_iface_id}/models-for-node?mode=t2v",
             "placeholder": "跟随接口默认"},
        ],
    },
    {
        "id": "project_init",
        "name": "剪辑项目初始化",
        "execution_domain": "thread",
        "category": "cutia",
        "description": "收集上游素材并构造初始剪辑JSON（默认时间线骨架+素材清单），供「Cutia 交互剪辑」接力整理筛选",
        "icon": "Clapperboard",
        "color": "#0ea5e9",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video"},
            {"id": "audio", "label": "音频", "type": "audio"},
            {"id": "image", "label": "图片", "type": "image"},
            {"id": "subtitle", "label": "字幕", "type": "subtitle"},
        ],
        "outputs": [
            {"id": "project", "label": "初始剪辑项目", "type": "json"},
        ],
        "defaultConfig": {
            "arrange_tracks": True,
        },
        "configFields": [
            {"key": "arrange_tracks", "label": "是否将素材加入轨道", "type": "checkbox", "colSpan": "half",
             "description": "关闭时只导入素材清单，不自动编排到时间线"},
        ],
    },
    {
        "id": "add_media_to_library",
        "name": "添加素材到剪辑",
        "execution_domain": "thread",
        "category": "video",
        "description": "将任意类型素材注册到剪辑工作台的素材库（不写入时间线轨道），供后续剪辑操作调用",
        "icon": "LibraryBig",
        "color": "#0d9488",
        "inputs": [
            {"id": "project", "label": "剪辑项目", "type": "json"},
            {"id": "media", "label": "素材", "type": "any"},
        ],
        "outputs": [
            {"id": "project", "label": "剪辑项目", "type": "json"},
        ],
        "defaultConfig": {},
        "configFields": [],
    },
    {
        "id": "add_track_media",
        "name": "添加剪辑素材到轨道",
        "execution_domain": "thread",
        "category": "cutia",
        "description": "接收任意类型素材，按所选类型添加到剪辑项目轨道（可新建轨道/轨道尾部/自定义插入点），输出剪辑项目JSON",
        "icon": "Layers",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "project", "label": "剪辑项目", "type": "json"},
            {"id": "media", "label": "素材", "type": "any"},
        ],
        "outputs": [
            {"id": "project", "label": "剪辑项目", "type": "json"},
        ],
        "defaultConfig": {
            "media_type": "video",
            "new_track": False,
            "track_name": "",
            "insert_mode": "end",
            "insert_time": 0,
            "static_duration": 3,
            "pos_x": 0,
            "pos_y": 0,
            "scale": 1,
            "rotate": 0,
            "opacity": 1,
            "volume": 1,
            "muted": False,
            "content": "",
            "font_size": 5,
            "font_family": "Arial",
            "color": "#ffffff",
            "background_color": "rgba(0, 0, 0, 0.7)",
            "text_align": "center",
            "font_weight": "normal",
        },
        "configFields": [
            {"key": "media_type", "label": "素材类型", "type": "select", "options": [
                {"value": "video", "label": "视频"},
                {"value": "audio", "label": "音频"},
                {"value": "image", "label": "图片"},
                {"value": "text", "label": "文字"},
            ]},
            {"key": "new_track", "label": "新建轨道添加", "type": "checkbox", "colSpan": "half"},
            {"key": "track_name", "label": "新轨道名称", "type": "text", "colSpan": "half",
             "dependsOn": "new_track", "placeholder": "留空自动命名"},
            {"key": "insert_mode", "label": "插入时间点", "type": "select", "options": [
                {"value": "end", "label": "插入到轨道尾部"},
                {"value": "custom", "label": "自定义插入点时间"},
            ]},
            {"key": "insert_time", "label": "插入点时间（秒）", "type": "number", "min": 0, "step": 0.1,
             "colSpan": "half", "dependsOn": "insert_mode", "dependsValue": "custom"},
            {"key": "static_duration", "label": "素材时长（秒）", "type": "number", "min": 0.1, "step": 0.1,
             "colSpan": "half", "placeholder": "仅图片/文字生效",
             "dependsOn": "media_type", "dependsValue": ["image", "text"]},
            {"key": "pos_x", "label": "X 坐标", "type": "number", "step": 1,
             "colSpan": "half", "dependsOn": "media_type", "dependsValue": ["video", "image", "text"]},
            {"key": "pos_y", "label": "Y 坐标", "type": "number", "step": 1,
             "colSpan": "half", "dependsOn": "media_type", "dependsValue": ["video", "image", "text"]},
            {"key": "scale", "label": "缩放", "type": "number", "min": 0.1, "step": 0.1,
             "colSpan": "half", "dependsOn": "media_type", "dependsValue": ["video", "image"]},
            {"key": "rotate", "label": "旋转（度）", "type": "number", "step": 1,
             "colSpan": "half", "dependsOn": "media_type", "dependsValue": ["video", "image"]},
            {"key": "opacity", "label": "不透明度", "type": "number", "min": 0, "max": 1, "step": 0.05,
             "colSpan": "half", "dependsOn": "media_type", "dependsValue": ["video", "image"]},
            {"key": "volume", "label": "音量", "type": "number", "min": 0, "max": 2, "step": 0.1,
             "colSpan": "half", "dependsOn": "media_type", "dependsValue": "audio"},
            {"key": "muted", "label": "静音", "type": "checkbox", "colSpan": "half",
             "dependsOn": "media_type", "dependsValue": "audio"},
            {"key": "content", "label": "文字内容", "type": "textarea",
             "dependsOn": "media_type", "dependsValue": "text"},
            {"key": "font_size", "label": "字号", "type": "number", "min": 1, "step": 1,
             "colSpan": "half", "dependsOn": "media_type", "dependsValue": "text"},
            {"key": "font_family", "label": "字体", "type": "text", "colSpan": "half",
             "dependsOn": "media_type", "dependsValue": "text"},
            {"key": "color", "label": "文字颜色", "type": "text", "colSpan": "half",
             "dependsOn": "media_type", "dependsValue": "text", "placeholder": "#ffffff"},
            {"key": "background_color", "label": "背景颜色", "type": "text", "colSpan": "half",
             "dependsOn": "media_type", "dependsValue": "text", "placeholder": "rgba(0, 0, 0, 0.7)"},
            {"key": "text_align", "label": "对齐方式", "type": "select", "colSpan": "half",
             "dependsOn": "media_type", "dependsValue": "text", "options": [
                 {"value": "left", "label": "左对齐"},
                 {"value": "center", "label": "居中"},
                 {"value": "right", "label": "右对齐"},
             ]},
            {"key": "font_weight", "label": "字重", "type": "select", "colSpan": "half",
             "dependsOn": "media_type", "dependsValue": "text", "options": [
                 {"value": "normal", "label": "常规"},
                 {"value": "bold", "label": "加粗"},
             ]},
        ],
    },
    {
        "id": "cutia",
        "name": "推送到剪辑台",
        "execution_domain": "thread",
        "category": "cutia",
        "description": "将剪辑项目JSON推送到剪辑工作台并发起系统提醒，等待剪辑后透传输出（素材编排由上游「剪辑项目初始化」完成）",
        "icon": "Clapperboard",
        "color": "#14b8a6",
        "inputs": [
            {"id": "project", "label": "剪辑项目", "type": "json"},
        ],
        "outputs": [
            {"id": "project", "label": "剪辑项目", "type": "json"},
        ],
        "defaultConfig": {
            "wait_seconds": 600,
        },
        "configFields": [
            {"key": "wait_seconds", "label": "等待剪辑时间（秒）", "type": "number", "min": 0, "colSpan": "half"},
        ],
    },
    {
        "id": "cutia_render",
        "name": "剪辑渲染",
        "execution_domain": "thread",
        "category": "cutia",
        "description": "接收上游精选后的剪辑项目JSON，无头加载并渲染导出成片，无需人工打开剪辑工作台",
        "icon": "Clapperboard",
        "color": "#f97316",
        "inputs": [
            {"id": "project", "label": "剪辑项目", "type": "json"},
        ],
        "outputs": [{"id": "video", "label": "渲染成片", "type": "video"}],
        "defaultConfig": {
            "export_format": "mp4",
            "quality": "high",
            "fps": 0,
            "include_audio": True,
            "browser_channel": "",
            "timeout_minutes": 60,
        },
        "configFields": [
            {"key": "export_format", "label": "导出格式", "type": "select", "options": [
                {"value": "mp4", "label": "MP4 (H.264)"},
                {"value": "webm", "label": "WebM (VP9)"},
            ]},
            {"key": "quality", "label": "画质", "type": "select", "options": [
                {"value": "low", "label": "低（体积最小）"},
                {"value": "medium", "label": "中（均衡）"},
                {"value": "high", "label": "高（推荐）"},
                {"value": "very_high", "label": "极高（体积最大）"},
            ]},
            {"key": "fps", "label": "帧率", "type": "number", "min": 0, "max": 60, "colSpan": "half",
             "placeholder": "0 表示跟随项目设置"},
            {"key": "include_audio", "label": "包含音频", "type": "checkbox", "colSpan": "half"},
            {"key": "browser_channel", "label": "浏览器通道", "type": "text", "colSpan": "half",
             "placeholder": "留空用内置 Chromium；需要 H.264 可填 chrome"},
            {"key": "timeout_minutes", "label": "超时（分钟）", "type": "number", "min": 1, "max": 720, "colSpan": "half"},
        ],
    },
    {
        "id": "video_frame_extract",
        "name": "视频抽帧",
        "execution_domain": "thread",
        "category": "video",
        "description": "从视频指定时间点提取帧图片，支持避开字幕",
        "icon": "Camera",
        "color": "#06b6d4",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video"},
            {"id": "srt", "label": "字幕", "type": "subtitle"},
        ],
        "outputs": [
            {"id": "image", "label": "帧图片", "type": "image"},
        ],
        "defaultConfig": {
            "video_source": "input_node",
            "time_point": 1.0,
            "time_mode": "positive",
            "avoid_subtitles": False,
        },
        "configFields": [
            {"key": "video_source", "label": "视频源", "type": "chips", "singleSelect": True,
             "chipColor": "#06b6d4",
             "options": [{"value": "input_node", "label": "来自输入节点"}, {"value": "connection", "label": "来自节点连线"}]},
            {"key": "time_point", "label": "截取时间点(秒)", "type": "text", "colSpan": "half",
             "placeholder": "如 5.0 或 120"},
            {"key": "time_mode", "label": "时间模式", "type": "select", "colSpan": "half",
             "options": [{"value": "positive", "label": "正数(从头)"}, {"value": "negative", "label": "倒数(从尾)"}]},
            {"key": "avoid_subtitles", "label": "避开字幕", "type": "checkbox"},
        ],
    },
    {
        "id": "subtitle_position_search",
        "name": "OCR字幕查找",
        "execution_domain": "thread",
        "category": "video",
        "description": "定位视频字幕区域：支持 OCR 自动查找（输出标注帧与相对坐标 JSON），也可手动框选字幕位置并设置片头片尾跳过时间",
        "icon": "Captions",
        "color": "#f59e0b",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video"},
        ],
        "outputs": [
            {"id": "image", "label": "标注帧", "type": "image"},
            {"id": "json", "label": "字幕坐标JSON", "type": "json"},
        ],
        "defaultConfig": {
            "model": "",
            "ocr_version": "",
            "model_type": "",
            "custom_model_name": "",
            "position_mode": "ocr",
            "manual_box": {},
            "skip_head_sec": 0,
            "skip_tail_sec": 0,
            "direction": "horizontal",
            "position": "lower",
            "position_ratio": "0.6-0.8",
            "frame_interval": 20,
            "clean_cache": True,
        },
        "configFields": [
            {"key": "model", "label": "OCR接口", "type": "api-select",
             "apiEndpoint": "/api/ocr-interfaces/enabled", "optionLabel": "name", "optionValue": "id",
             "placeholder": "跟随全局配置", "colSpan": "half"},
            {"key": "ocr_version", "label": "模型版本", "type": "select", "colSpan": "half",
             "options": [{"value": "", "label": "跟随接口默认"}, {"value": "PP-OCRv6", "label": "PP-OCRv6"},
                         {"value": "PP-OCRv5", "label": "PP-OCRv5"}, {"value": "PP-OCRv4", "label": "PP-OCRv4"},
                         {"value": "custom", "label": "自定义"}]},
            {"key": "model_type", "label": "模型尺寸", "type": "select", "colSpan": "half",
             "options": [{"value": "", "label": "跟随接口默认"}, {"value": "small", "label": "small（均衡）"},
                         {"value": "mobile", "label": "mobile"}, {"value": "tiny", "label": "tiny（最快）"},
                         {"value": "server", "label": "server（更高精度）"}]},
            {"key": "custom_model_name", "label": "自定义模型名", "type": "text", "colSpan": "half",
             "dependsOn": "ocr_version", "dependsValue": "custom",
             "placeholder": "输入完整模型名",
             "description": "非空时原样覆盖版本/尺寸，需自行确保模型文件存在"},
            {"key": "direction", "label": "字幕方向", "type": "select", "colSpan": "half",
             "options": [{"value": "horizontal", "label": "水平"}, {"value": "vertical", "label": "竖直"}]},
            # 字幕位置：同一 key，按方向显示不同名称（上下/左右）
            {"key": "position", "label": "字幕位置", "type": "select", "colSpan": "half",
             "dependsOn": "direction", "dependsValue": "horizontal",
             "options": [{"value": "upper", "label": "上半段"}, {"value": "lower", "label": "下半段"}, {"value": "ratio", "label": "比例范围"}]},
            {"key": "position", "label": "字幕位置", "type": "select", "colSpan": "half",
             "dependsOn": "direction", "dependsValue": "vertical",
             "options": [{"value": "upper", "label": "左半段"}, {"value": "lower", "label": "右半段"}, {"value": "ratio", "label": "比例范围"}]},
            {"key": "position_ratio", "label": "位置比例", "type": "text", "colSpan": "half",
             "dependsOn": "position", "dependsValue": "ratio",
             "placeholder": "如 0.6-0.8",
             "description": "水平方向为 y 坐标比例，竖直方向为 x 坐标比例"},
            {"key": "frame_interval", "label": "抽帧步长", "type": "number", "colSpan": "half",
             "min": 1, "placeholder": "默认 20"},
            {"key": "clean_cache", "label": "清理缓存", "type": "checkbox", "colSpan": "half",
             "description": "结束后删除抽帧缓存"},
        ],
    },
    {
        "id": "subtitle_recognition",
        "name": "OCR字幕识别",
        "execution_domain": "thread",
        "category": "video",
        "description": "按字幕区域坐标用 OCR 识别字幕内容与时间轴，输出 ASR 格式结果 JSON",
        "icon": "Captions",
        "color": "#10b981",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": True},
            {"id": "json", "label": "字幕区域坐标", "type": "json"},
        ],
        "outputs": [
            {"id": "subtitle", "label": "识别结果JSON(ASR)", "type": "json", "color": "#6366f1"},
        ],
        "defaultConfig": {
            "model": "",
            "ocr_version": "",
            "model_type": "",
            "custom_model_name": "",
            "initial_interval": 20,
            "boundary_precision_ms": 200,
            "tilt_threshold_deg": 8.0,
        },
        "configFields": [
            {"key": "model", "label": "OCR接口", "type": "api-select",
             "apiEndpoint": "/api/ocr-interfaces/enabled", "optionLabel": "name", "optionValue": "id",
             "placeholder": "跟随全局配置", "colSpan": "half"},
            {"key": "ocr_version", "label": "模型版本", "type": "select", "colSpan": "half",
             "options": [{"value": "", "label": "跟随接口默认"}, {"value": "PP-OCRv6", "label": "PP-OCRv6"},
                         {"value": "PP-OCRv5", "label": "PP-OCRv5"}, {"value": "PP-OCRv4", "label": "PP-OCRv4"},
                         {"value": "custom", "label": "自定义"}]},
            {"key": "model_type", "label": "模型尺寸", "type": "select", "colSpan": "half",
             "options": [{"value": "", "label": "跟随接口默认"}, {"value": "small", "label": "small（均衡）"},
                         {"value": "mobile", "label": "mobile"}, {"value": "tiny", "label": "tiny（最快）"},
                         {"value": "server", "label": "server（更高精度）"}]},
            {"key": "custom_model_name", "label": "自定义模型名", "type": "text", "colSpan": "half",
             "dependsOn": "ocr_version", "dependsValue": "custom",
             "placeholder": "输入完整模型名",
             "description": "非空时原样覆盖版本/尺寸，需自行确保模型文件存在"},
            {"key": "initial_interval", "label": "初次抽帧间隔", "type": "number", "colSpan": "half",
             "min": 1, "placeholder": "默认 20", "description": "初次检查抽帧间隔（帧）"},
            {"key": "boundary_precision_ms", "label": "边界精度(毫秒)", "type": "number", "colSpan": "half",
             "min": 1, "placeholder": "默认 200", "description": "字幕首尾边界精细化步长"},
            {"key": "tilt_threshold_deg", "label": "倾角过滤阈值(度)", "type": "number", "colSpan": "half",
             "min": 0, "step": 0.5, "placeholder": "默认 8",
             "description": "文本框长边倾角超过该值视为非字幕"},
        ],
    },
    {
        "id": "video_publish",
        "name": "视频发布",
        "execution_domain": "process",
        "category": "utility",
        "description": "将视频发布到指定社交平台，支持多平台分发、定时发布、草稿模式",
        "icon": "Share2",
        "color": "#10b981",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": True},
            {"id": "cover_landscape", "label": "横屏封面", "type": "image"},
            {"id": "cover_portrait", "label": "竖屏封面", "type": "image"},
            {"id": "json", "label": "标题/描述", "type": "json"},
        ],
        "outputs": [
            {"id": "text", "label": "发布结果", "type": "text"},
            {"id": "result_file", "label": "结果文件", "type": "file"},
        ],
        "defaultConfig": {
            "account_ids": [],
            "title": "",
            "title_affix": "",
            "title_affix_mode": "suffix",
            "description": "",
            "desc_affix": "",
            "desc_affix_mode": "suffix",
            "tags": "",
            "is_original": False,
            "publish_mode": "publish",
            "schedule_enabled": False,
            "schedule_time": "",
        },
        "configFields": [
            {"key": "account_ids", "label": "选择发布账号", "type": "account-select",
             "apiEndpoint": "/api/publish/accounts/all",
             "placeholder": "请选择发布账号"},
            {"key": "title", "label": "视频标题", "type": "text", "placeholder": "留空则从上游JSON读取"},
            {"key": "title_affix", "label": "标题附加文本", "type": "text", "placeholder": "输入要附加到标题的文本", "colSpan": "half"},
            {"key": "title_affix_mode", "label": "附加位置", "type": "select", "colSpan": "half",
             "options": [{"value": "prefix", "label": "前缀"}, {"value": "suffix", "label": "后缀"}]},
            {"key": "description", "label": "视频描述", "type": "textarea", "placeholder": "留空则从上游JSON读取"},
            {"key": "desc_affix", "label": "描述附加文本", "type": "text", "placeholder": "输入要附加到描述的文本", "colSpan": "half"},
            {"key": "desc_affix_mode", "label": "附加位置", "type": "select", "colSpan": "half",
             "options": [{"value": "prefix", "label": "前缀"}, {"value": "suffix", "label": "后缀"}]},
            {"key": "tags", "label": "标签(逗号分隔)", "type": "text", "placeholder": "标签1,标签2,标签3", "colSpan": "half"},
            {"key": "is_original", "label": "原创内容", "type": "checkbox", "colSpan": "half"},
            {"key": "publish_mode", "label": "发布方式", "type": "select",
             "options": [
                 {"value": "publish", "label": "直接发布"},
                 {"value": "platform_draft", "label": "存为平台草稿"},
                 {"value": "local_draft", "label": "存为本地草稿"},
             ]},
            {"key": "declaration", "label": "内容声明", "type": "select", "options": [
                {"value": "", "label": "无需声明"},
                {"value": "ai_generated", "label": "含AI生成内容"},
                {"value": "repost", "label": "内容为转载"},
                {"value": "fictional", "label": "含虚构演绎内容"},
                {"value": "marketing", "label": "内容含营销信息"},
                {"value": "personal_opinion", "label": "个人观点，仅供参考"},
            ], "description": "声明视频内容属性，发布时传递给平台"},
            {"key": "schedule_enabled", "label": "定时发布", "type": "checkbox", "colSpan": "half"},
            {"key": "schedule_time", "label": "定时时间", "type": "datetime-local",
             "dependsOn": "schedule_enabled", "dependsValue": True},
        ],
    },
    {
        "id": "xiaopai_publish",
        "name": "小派作品发布",
        "execution_domain": "process",
        "category": "utility",
        "description": "小Pi助手作品发布节点，自动准备发布数据并调用发布服务",
        "icon": "Send",
        "color": "#06b6d4",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": True},
            {"id": "cover_landscape", "label": "横屏封面", "type": "image"},
            {"id": "cover_portrait", "label": "竖屏封面", "type": "image"},
            {"id": "json", "label": "标题/描述", "type": "json"},
        ],
        "outputs": [
            {"id": "text", "label": "发布结果", "type": "text"},
            {"id": "result_file", "label": "结果文件", "type": "file"},
        ],
        "defaultConfig": {
            "account_ids": [],
            "title": "",
            "title_affix": "",
            "title_affix_mode": "suffix",
            "description": "",
            "desc_affix": "",
            "desc_affix_mode": "suffix",
            "tags": "",
            "is_original": False,
            "publish_mode": "publish",
            "schedule_enabled": False,
            "schedule_time": "",
        },
        "configFields": [
            {"key": "account_ids", "label": "选择发布账号", "type": "account-select",
             "apiEndpoint": "/api/publish/accounts/all",
             "placeholder": "请选择发布账号"},
            {"key": "title", "label": "视频标题", "type": "text", "placeholder": "留空则从上游JSON读取"},
            {"key": "title_affix", "label": "标题附加文本", "type": "text", "placeholder": "输入要附加到标题的文本", "colSpan": "half"},
            {"key": "title_affix_mode", "label": "附加位置", "type": "select", "colSpan": "half",
             "options": [{"value": "prefix", "label": "前缀"}, {"value": "suffix", "label": "后缀"}]},
            {"key": "description", "label": "视频描述", "type": "textarea", "placeholder": "留空则从上游JSON读取"},
            {"key": "desc_affix", "label": "描述附加文本", "type": "text", "placeholder": "输入要附加到描述的文本", "colSpan": "half"},
            {"key": "desc_affix_mode", "label": "附加位置", "type": "select", "colSpan": "half",
             "options": [{"value": "prefix", "label": "前缀"}, {"value": "suffix", "label": "后缀"}]},
            {"key": "tags", "label": "标签(逗号分隔)", "type": "text", "placeholder": "标签1,标签2,标签3", "colSpan": "half"},
            {"key": "is_original", "label": "原创内容", "type": "checkbox", "colSpan": "half"},
            {"key": "publish_mode", "label": "发布方式", "type": "select",
             "options": [
                 {"value": "publish", "label": "直接发布"},
                 {"value": "platform_draft", "label": "存为平台草稿"},
                 {"value": "local_draft", "label": "存为本地草稿"},
             ]},
            {"key": "declaration", "label": "内容声明", "type": "select", "options": [
                {"value": "", "label": "无需声明"},
                {"value": "ai_generated", "label": "含AI生成内容"},
                {"value": "repost", "label": "内容为转载"},
                {"value": "fictional", "label": "含虚构演绎内容"},
                {"value": "marketing", "label": "内容含营销信息"},
                {"value": "personal_opinion", "label": "个人观点，仅供参考"},
            ], "description": "声明视频内容属性，发布时传递给平台"},
            {"key": "schedule_enabled", "label": "定时发布", "type": "checkbox", "colSpan": "half"},
            {"key": "schedule_time", "label": "定时时间", "type": "datetime-local",
             "dependsOn": "schedule_enabled", "dependsValue": True},
        ],
    },
    {
        "id": "resolve_path",
        "name": "取文件路径",
        "execution_domain": "thread",
        "category": "file",
        "description": "以相对路径拼接出项目文件夹内的特定文件路径",
        "icon": "FolderOpen",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "input", "label": "输入", "type": "any"},
        ],
        "outputs": [
            {"id": "output", "label": "路径", "type": "any"},
        ],
        "defaultConfig": {
            "relative_path": "",
        },
        "configFields": [
            {"key": "relative_path", "label": "相对路径", "type": "text",
             "placeholder": "例: output/video.mp4 或 cache/subtitle.srt"},
        ],
    },
    {
        "id": "json_to_text",
        "name": "JSON转文本",
        "execution_domain": "thread",
        "category": "utility",
        "description": "将JSON转换为文本文件，支持全量转文本或按key表达式取值",
        "icon": "FileText",
        "color": "#f97316",
        "inputs": [
            {"id": "json", "label": "JSON", "type": "json"},
        ],
        "outputs": [
            {"id": "text", "label": "文本文件", "type": "text"},
        ],
        "defaultConfig": {
            "mode": "full",
            "key_expr": "",
        },
        "configFields": [
            {"key": "mode", "label": "输出模式", "type": "select",
             "options": [
                 {"value": "full", "label": "全量转文本"},
                 {"value": "key", "label": "key取值"},
             ]},
            {"key": "key_expr", "label": "key表达式", "type": "text",
             "placeholder": "key0$key1$key2 (用$分隔层级)",
             "dependsOn": "mode", "dependsValue": "key"},
        ],
    },
    {
        "id": "json_editor",
        "name": "JSON编辑",
        "execution_domain": "thread",
        "category": "utility",
        "description": "按key表达式修改JSON中指定字段的值，覆盖保存原文件",
        "icon": "Edit3",
        "color": "#f97316",
        "inputs": [
            {"id": "json", "label": "JSON", "type": "json"},
            {"id": "text", "label": "修改值", "type": "text"},
        ],
        "outputs": [
            {"id": "json", "label": "JSON", "type": "json"},
        ],
        "defaultConfig": {
            "key_expr": "",
            "value_source": "auto",
            "custom_value": "",
        },
        "configFields": [
            {"key": "key_expr", "label": "key表达式", "type": "text",
             "placeholder": "key0$key1$key2 (用$分隔层级)"},
            {"key": "value_source", "label": "修改值来源", "type": "select",
             "options": [
                 {"value": "auto", "label": "自动（优先连线，回退自定义）"},
                 {"value": "input", "label": "连线输入"},
                 {"value": "custom", "label": "自定义输入"},
             ]},
            {"key": "custom_value", "label": "自定义输入值", "type": "text",
             "placeholder": "输入要设置的值"},
        ],
    },
    {
        "id": "json_get",
        "name": "JSON取值",
        "execution_domain": "thread",
        "category": "utility",
        "description": "按key表达式从输入JSON中取值，输出端口数量可在卡片上用+号任意增加（1~8），每个端口下对应一个取值表达式；结果以any类型输出，数据不落盘（内存流转给下游，并写入任务数据库）",
        "icon": "Braces",
        "color": "#f97316",
        "dynamicPorts": True,
        "inputs": [
            {"id": "json", "label": "JSON", "type": "json"},
        ],
        "outputs": [
            {"id": "out_1", "label": "取值1", "type": "any"},
        ],
        "defaultConfig": {
            "outputCount": 1,
            "key_exprs": [""],
        },
        "configFields": [
            {"key": "outputCount", "label": "输出端口数", "type": "number",
             "min": 1, "max": 8,
             "description": "通过节点卡片上的 + / - 控制（1~8），每个端口对应一个取值表达式"},
        ],
    },
    {
        "id": "srt_to_json",
        "name": "SRT字幕转json",
        "execution_domain": "thread",
        "category": "utility",
        "description": "将 SRT 字幕转换为 ASR 结果格式 JSON（包含 text 与 segments，不生成词级时间戳 words），可直接接入 ASR 结果校验、预处理等下游节点。输入为「字幕」类型，可连线「字幕生成」等字幕节点的输出（默认输出 .srt）。",
        "icon": "Subtitles",
        "color": "#f97316",
        "inputs": [
            {"id": "subtitle", "label": "字幕", "type": "subtitle", "required": True}
        ],
        "outputs": [
            {"id": "json", "label": "ASR结果JSON", "type": "json", "color": "#f97316"}
        ],
        "defaultConfig": {},
        "configFields": []
    },
    {
        "id": "srt_to_text",
        "name": "SRT转文本",
        "execution_domain": "thread",
        "category": "utility",
        "description": "将 SRT 字幕直接转换为纯文本：去掉序号与时间轴，提取每条字幕的文本内容，按原顺序拼接为 .txt 文本文件输出。输入为「字幕」类型，可连线「字幕生成」等字幕节点的输出（默认输出 .srt）。",
        "icon": "FileText",
        "color": "#f97316",
        "inputs": [
            {"id": "subtitle", "label": "字幕", "type": "subtitle", "required": True}
        ],
        "outputs": [
            {"id": "text", "label": "文本", "type": "text", "color": "#f97316"}
        ],
        "defaultConfig": {},
        "configFields": []
    },
    {
        "id": "json_visual_editor",
        "name": "JSON可视化编辑",
        "execution_domain": "thread",
        "category": "utility",
        "description": "可视化编辑 JSON，默认透传，可另存副本",
        "icon": "FileJson",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "json", "label": "JSON", "type": "json", "required": True},
        ],
        "outputs": [
            {"id": "json", "label": "JSON", "type": "json"},
        ],
        "defaultConfig": {
            "enable_copy": True,
            "edited_json": "",
        },
        "configFields": [
            {"key": "open_editor", "label": "打开 JSON 编辑页", "type": "button",
             "description": "打开可视化 JSON 编辑弹窗，载入输入 JSON"},
            {"key": "enable_copy", "label": "另存副本", "type": "checkbox", "colSpan": "half",
             "description": "勾选后另存带随机后缀的副本，不覆盖原文件；取消勾选则直接覆盖原 JSON 文件"},
        ],
    },
    {
        "id": "text_editor",
        "name": "文本编辑",
        "execution_domain": "thread",
        "category": "utility",
        "description": "可视化编辑文本，支持查找删除/替换/正则，默认透传，可另存副本",
        "icon": "FileText",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "text", "label": "文本", "type": "text", "required": True},
        ],
        "outputs": [
            {"id": "text", "label": "文本", "type": "text"},
        ],
        "defaultConfig": {
            "enable_copy": True,
            "edited_text": "",
        },
        "configFields": [
            {"key": "open_editor", "label": "打开文本编辑页", "type": "button",
             "description": "打开文本编辑弹窗，支持查找删除、查找替换、正则表达式查找替换"},
            {"key": "enable_copy", "label": "另存副本", "type": "checkbox", "colSpan": "half",
             "description": "勾选后另存带随机后缀的副本，不覆盖原文件；取消勾选则直接覆盖原文本文件"},
        ],
    },
    {
        "id": "text_concat",
        "name": "文本拼接",
        "execution_domain": "thread",
        "category": "utility",
        "description": "把「输入1 / 输入2 / 输入框文本」三个对象按卡片指定顺序拼接，连接符可选换行符/空格/自定义",
        "icon": "Combine",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "input1", "label": "输入1", "type": "text", "required": False},
            {"id": "input2", "label": "输入2", "type": "text", "required": False},
        ],
        "outputs": [
            {"id": "text", "label": "拼接文本", "type": "text"},
        ],
        "defaultConfig": {
            "custom_text": "",
            "order_1": "input1",
            "order_2": "input2",
            "order_3": "custom",
            "separator": "newline",
            "custom_separator": "",
        },
        "configFields": [
            {"key": "custom_text", "label": "输入框文本", "type": "textarea", "colSpan": "full",
             "placeholder": "自定义拼接文本；只有被选为第一/二/三位时才参与拼接",
             "description": "可选项之一，可与两个输入端口自由排序"},
            {"key": "order_1", "label": "第一位", "type": "select", "colSpan": "third", "options": [
                {"value": "input1", "label": "输入1"},
                {"value": "input2", "label": "输入2"},
                {"value": "custom", "label": "输入框文本"}]},
            {"key": "order_2", "label": "第二位", "type": "select", "colSpan": "third", "options": [
                {"value": "input1", "label": "输入1"},
                {"value": "input2", "label": "输入2"},
                {"value": "custom", "label": "输入框文本"}]},
            {"key": "order_3", "label": "第三位", "type": "select", "colSpan": "third", "options": [
                {"value": "input1", "label": "输入1"},
                {"value": "input2", "label": "输入2"},
                {"value": "custom", "label": "输入框文本"}]},
            {"key": "separator", "label": "拼接连接符号", "type": "select", "colSpan": "half", "options": [
                {"value": "newline", "label": "换行符"},
                {"value": "space", "label": "空格"},
                {"value": "custom", "label": "自定义"}]},
            {"key": "custom_separator", "label": "自定义连接符", "type": "text", "colSpan": "half",
             "dependsOn": "separator", "dependsValue": "custom",
             "placeholder": "例如：， / | / —— / 空则直接相连"},
        ],
    },
    {
        "id": "subtitle_editor",
        "name": "字幕编辑",
        "execution_domain": "thread",
        "category": "utility",
        "description": "逐条编辑字幕（文本/时间/合并/拆分），带视频预览，默认透传，可另存副本",
        "icon": "Subtitles",
        "color": "#f59e0b",
        "inputs": [
            {"id": "subtitle", "label": "字幕", "type": "subtitle", "required": True},
        ],
        "outputs": [
            {"id": "subtitle", "label": "字幕", "type": "subtitle"},
        ],
        "defaultConfig": {
            "enable_copy": True,
            "edited_subtitles": "",
        },
        "configFields": [
            {"key": "open_editor", "label": "打开字幕编辑页", "type": "button",
             "description": "打开字幕编辑弹窗：左侧字幕列表，右侧视频预览，时间轴同步"},
            {"key": "enable_copy", "label": "另存副本", "type": "checkbox", "colSpan": "half",
             "description": "勾选后另存带随机后缀的副本，不覆盖原文件；取消勾选则直接覆盖原字幕文件"},
        ],
    },
    {
        "id": "video_split",
        "name": "视频切割",
        "execution_domain": "thread",
        "category": "video",
        "description": "将视频按数量或时长切割为多段，支持静音点切割",
        "icon": "Scissors",
        "color": "#ef4444",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": True},
            {"id": "audio", "label": "音频", "type": "audio"},
        ],
        "outputs": [
            {"id": "video", "label": "切割片段", "type": "video"},
            {"id": "text", "label": "切割信息", "type": "text"},
        ],
        "defaultConfig": {
            "split_mode": "count",
            "segment_count": 2,
            "segment_duration": 60,
            "use_silence": False,
            "output_index": 1,
        },
        "configFields": [
            {"key": "split_mode", "label": "切割方式", "type": "select",
             "options": [
                 {"value": "count", "label": "按片段数量"},
                 {"value": "duration", "label": "按固定时长"},
             ]},
            {"key": "segment_count", "label": "片段数量", "type": "text",
             "dependsOn": "split_mode", "dependsValue": "count", "colSpan": "half"},
            {"key": "segment_duration", "label": "每段时长(秒)", "type": "text",
             "dependsOn": "split_mode", "dependsValue": "duration", "colSpan": "half"},
            {"key": "use_silence", "label": "寻找静音点切割", "type": "checkbox", "colSpan": "half"},
            {"key": "output_index", "label": "输出片段序号", "type": "text",
             "placeholder": "从1开始", "colSpan": "half"},
        ],
    },
    {
        "id": "video_clip_intro_outro",
        "name": "切割片头片尾",
        "execution_domain": "thread",
        "category": "video",
        "description": "从主视频中裁剪片头与片尾，输出裁剪后的主视频、片头片段、片尾片段（ffmpeg 流拷贝，不重新编码）",
        "icon": "Scissors",
        "color": "#f97316",
        "inputs": [
            {"id": "video", "label": "主视频", "type": "video", "required": True},
        ],
        "outputs": [
            {"id": "video", "label": "裁剪后主视频", "type": "video", "color": "#3b82f6"},
            {"id": "intro", "label": "片头片段", "type": "video", "color": "#10b981"},
            {"id": "outro", "label": "片尾片段", "type": "video", "color": "#a855f7"},
        ],
        "defaultConfig": {"trim_intro": False, "intro_duration": "5", "trim_outro": False, "outro_duration": "5"},
        "configFields": [
            {"key": "trim_intro", "label": "裁剪片头", "type": "checkbox", "colSpan": "half",
             "description": "勾选后从主视频开头裁掉「片头时长」秒"},
            {"key": "intro_duration", "label": "片头时长(秒)", "type": "text", "colSpan": "half",
             "placeholder": "正数，单位秒", "dependsOn": "trim_intro", "dependsValue": True,
             "description": "从开头裁掉的秒数，正数"},
            {"key": "trim_outro", "label": "裁剪片尾", "type": "checkbox", "colSpan": "half",
             "description": "勾选后从主视频结尾裁掉「片尾时长」秒"},
            {"key": "outro_duration", "label": "片尾切割点(秒)", "type": "text", "colSpan": "half",
             "placeholder": "正数或倒数(如 -5)", "dependsOn": "trim_outro", "dependsValue": True,
             "description": "片尾开始的切割点：正数=从该绝对秒处切断(之后为片尾)；负数=从结尾倒数该秒处切断(如 -108 表示从结尾倒数108秒处切断)"},
        ],
    },
    {
        "id": "video_dedupe",
        "name": "视频去重",
        "execution_domain": "thread",
        "category": "video",
        "description": "反平台查重变换：对视频做水平镜像、放大裁切、调速、调色/滤镜、加边框等画面变换以规避重复检测；不删内容，只改画面（ffmpeg 重编码）",
        "icon": "SlidersHorizontal",
        "color": "#22c55e",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": True},
        ],
        "outputs": [
            {"id": "video", "label": "去重视频", "type": "video"},
        ],
        "defaultConfig": {
            "flip_h": False,
            "zoom_crop": False, "zoom_factor": "1.08",
            "speed_change": False, "speed_ratio": "1.04",
            "apply_filter": False, "filter_preset": "color",
            "add_border": False, "border_size": "20",
            "output_format": "mp4", "video_quality": "medium",
        },
        "configFields": [
            {"key": "flip_h", "label": "水平镜像翻转", "type": "checkbox", "colSpan": "half",
             "description": "勾选后对画面做左右镜像翻转"},
            {"key": "zoom_crop", "label": "放大裁切", "type": "checkbox", "colSpan": "half",
             "description": "勾选后放大画面并居中裁切（等效拉近镜头，改变构图）"},
            {"key": "zoom_factor", "label": "放大倍数", "type": "text", "colSpan": "half",
             "placeholder": "1.01~2.0，默认1.08", "dependsOn": "zoom_crop", "dependsValue": True,
             "description": "放大裁切的倍率，限制 1.01~2.0"},
            {"key": "speed_change", "label": "调速", "type": "checkbox", "colSpan": "half",
             "description": "勾选后轻微改变播放速度（视频+音频同步变速）"},
            {"key": "speed_ratio", "label": "速度比例", "type": "text", "colSpan": "half",
             "placeholder": "0.5~2.0，>1加速", "dependsOn": "speed_change", "dependsValue": True,
             "description": "播放速度比例，>1 加速(如1.04)；<1 减速(如0.96)，限制0.5~2.0"},
            {"key": "apply_filter", "label": "调色/滤镜", "type": "checkbox", "colSpan": "half",
             "description": "勾选后施加轻量调色/滤镜，改变画面观感"},
            {"key": "filter_preset", "label": "滤镜预设", "type": "select", "colSpan": "half",
             "options": [
                {"label": "轻微调色", "value": "color"},
                {"label": "亮度微调", "value": "brightness"},
                {"label": "色相旋转", "value": "hue"},
                {"label": "锐化", "value": "sharpen"},
                {"label": "轻微模糊", "value": "blur"},
             ], "dependsOn": "apply_filter", "dependsValue": True,
             "description": "选择滤镜类型"},
            {"key": "add_border", "label": "加边框", "type": "checkbox", "colSpan": "half",
             "description": "勾选后四周加黑边，改变画面尺寸比例"},
            {"key": "border_size", "label": "边框像素", "type": "text", "colSpan": "half",
             "placeholder": "默认20", "dependsOn": "add_border", "dependsValue": True,
             "description": "黑边宽度（像素），每边均加此宽度"},
            {"key": "output_format", "label": "输出格式", "type": "select", "colSpan": "half", "options": [
                {"label": "mp4", "value": "mp4"},
                {"label": "mkv", "value": "mkv"},
                {"label": "mov", "value": "mov"},
                {"label": "webm", "value": "webm"},
                {"label": "avi", "value": "avi"},
                {"label": "flv", "value": "flv"},
            ], "description": "输出容器格式"},
            {"key": "video_quality", "label": "编码质量", "type": "select", "colSpan": "half", "options": [
                {"label": "高 (CRF18)", "value": "high"},
                {"label": "中 (CRF23)", "value": "medium"},
                {"label": "低 (CRF28)", "value": "low"},
            ], "description": "重新编码质量（CRF 越小质量越高）"},
        ],
    },
    {
        "id": "video_region_crop",
        "name": "视频截取区域",
        "execution_domain": "thread",
        "category": "video",
        "description": "从大分辨率视频中截取指定区域与时段，输出局部视频与坐标 JSON，供「视频区域贴片」节点贴回原视频做局部处理。",
        "icon": "Crop",
        "color": "#a855f7",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": True},
        ],
        "outputs": [
            {"id": "video", "label": "截取区域视频", "type": "video"},
            {"id": "json", "label": "截取坐标", "type": "json"},
        ],
        "defaultConfig": {
            "crop_size": "1280x760",
            "crop_width": 512,
            "crop_height": 512,
            "crop_position": "center",
            "start_time": 0,
            "end_mode": "absolute",
            "end_time": "",
            "end_countdown": 10,
        },
        "configFields": [
            {
                "key": "crop_size", "label": "切取区域大小", "type": "select",
                "options": [
                    {"value": "512x512", "label": "512 × 512"},
                    {"value": "1280x760", "label": "1280 × 760"},
                    {"value": "1920x1080", "label": "1920 × 1080"},
                    {"value": "custom", "label": "自定义(手动输入)"},
                ],
                "default": "1280x760",
            },
            {
                "key": "crop_width", "label": "区域宽度(像素)", "type": "number",
                "dependsOn": "crop_size", "dependsValue": "custom", "colSpan": "half", "min": 1,
            },
            {
                "key": "crop_height", "label": "区域高度(像素)", "type": "number",
                "dependsOn": "crop_size", "dependsValue": "custom", "colSpan": "half", "min": 1,
            },
            {
                "key": "crop_position", "label": "截取区域位置", "type": "select",
                "options": [
                    {"value": "top-left", "label": "左上"},
                    {"value": "top-center", "label": "中上"},
                    {"value": "top-right", "label": "右上"},
                    {"value": "middle-left", "label": "左中"},
                    {"value": "center", "label": "居中"},
                    {"value": "middle-right", "label": "右中"},
                    {"value": "bottom-left", "label": "左下"},
                    {"value": "bottom-center", "label": "中下"},
                    {"value": "bottom-right", "label": "右下"},
                ],
                "default": "center",
            },
            {
                "key": "start_time", "label": "开始时间(秒)", "type": "number",
                "default": 0, "min": 0, "colSpan": "half",
            },
            {
                "key": "end_mode", "label": "结束时间方式", "type": "select",
                "options": [
                    {"value": "absolute", "label": "顺数(绝对结束时间)"},
                    {"value": "countdown", "label": "倒数(距结尾时长)"},
                ],
                "default": "absolute", "colSpan": "half",
            },
            {
                "key": "end_time", "label": "结束时间(秒)", "type": "number",
                "dependsOn": "end_mode", "dependsValue": "absolute", "colSpan": "half", "min": 0,
            },
            {
                "key": "end_countdown", "label": "倒数时长(秒)", "type": "number",
                "dependsOn": "end_mode", "dependsValue": "countdown", "colSpan": "half", "min": 0,
            },
        ],
    },
    {
        "id": "video_region_composite",
        "name": "视频区域贴片",
        "execution_domain": "thread",
        "category": "video",
        "description": "将「视频截取区域」产出的局部视频按坐标贴回主视频。贴片大于区域时自动缩放，主/贴片编码不一致时统一重编码后贴合。",
        "icon": "Layers",
        "color": "#a855f7",
        "inputs": [
            {"id": "main_video", "label": "主视频", "type": "video", "required": True},
            {"id": "patch_video", "label": "贴片视频", "type": "video", "required": True},
            {"id": "patch_json", "label": "贴片坐标", "type": "json", "required": True},
        ],
        "outputs": [
            {"id": "video", "label": "贴合后视频", "type": "video"},
        ],
        "defaultConfig": {
            "time_source": "from_json",
            "manual_start": 0,
        },
        "configFields": [
            {
                "key": "time_source", "label": "贴合时间段来源", "type": "select",
                "options": [
                    {"value": "from_json", "label": "来自上游配置json"},
                    {"value": "manual", "label": "自由输入起始点"},
                ],
                "default": "from_json",
            },
            {
                "key": "manual_start", "label": "起始点(秒)", "type": "number",
                "dependsOn": "time_source", "dependsValue": "manual", "colSpan": "half", "min": 0,
            },
        ],
    },
    {
        "id": "file_rename",
        "name": "文件改名",
        "execution_domain": "thread",
        "category": "file",
        "description": "给输入文件改名，支持自定义文件名、前缀、后缀，或从输入端口动态获取文件名；重名时自动追加序号",
        "icon": "FileEdit",
        "color": "#f97316",
        "inputs": [
            {"id": "any", "label": "输入", "type": "any", "required": True},
            {"id": "name", "label": "文件名(来自输入)", "type": "text", "required": False},
        ],
        "outputs": [{"id": "any", "label": "输出", "type": "any"}],
        "defaultConfig": {
            "rename_mode": "suffix",
            "custom_name": "",
            "prefix": "",
            "suffix": "",
        },
        "configFields": [
            {"key": "rename_mode", "label": "改名方式", "type": "select", "options": [
                {"value": "custom", "label": "自定义文件名"},
                {"value": "prefix", "label": "添加前缀"},
                {"value": "suffix", "label": "添加后缀"},
                {"value": "from_input", "label": "来自输入(文本端口)"},
            ]},
            {"key": "custom_name", "label": "自定义文件名", "type": "text", "placeholder": "输入新文件名（不含扩展名）", "dependsOn": "rename_mode", "dependsValue": "custom"},
            {"key": "prefix", "label": "前缀", "type": "text", "placeholder": "添加到文件名前面", "dependsOn": "rename_mode", "dependsValue": "prefix"},
            {"key": "suffix", "label": "后缀", "type": "text", "placeholder": "添加到文件名后面", "dependsOn": "rename_mode", "dependsValue": "suffix"},
        ],
    },
    {
        "id": "timed_delay",
        "name": "定时执行",
        "execution_domain": "thread",
        "category": "flow_control",
        "description": "等待指定时间后继续执行，支持时间点和倒计时两种模式",
        "icon": "Clock",
        "color": "#6366f1",
        "inputs": [{"id": "any", "label": "输入", "type": "any", "required": False}],
        "outputs": [{"id": "any", "label": "输出", "type": "any"}],
        "defaultConfig": {
            "delay_mode": "countdown",
            "target_date": "",
            "target_time": "",
            "countdown_hours": 0,
            "countdown_minutes": 0,
            "countdown_seconds": 0,
            "random_tail_enabled": False,
            "random_min": 0,
            "random_max": 0,
        },
        "configFields": [
            {"key": "delay_mode", "label": "等待模式", "type": "select", "options": [
                {"value": "time_point", "label": "时间点"},
                {"value": "countdown", "label": "倒计时"},
            ]},
            {"key": "target_date", "label": "目标日期", "type": "date", "colSpan": "half", "dependsOn": "delay_mode", "dependsValue": "time_point"},
            {"key": "target_time", "label": "目标时间", "type": "time", "colSpan": "half", "dependsOn": "delay_mode", "dependsValue": "time_point"},
            {"key": "countdown_hours", "label": "小时", "type": "number", "min": 0, "max": 999, "colSpan": "third", "dependsOn": "delay_mode", "dependsValue": "countdown"},
            {"key": "countdown_minutes", "label": "分钟", "type": "number", "min": 0, "max": 59, "colSpan": "third", "dependsOn": "delay_mode", "dependsValue": "countdown"},
            {"key": "countdown_seconds", "label": "秒钟", "type": "number", "min": 0, "max": 59, "colSpan": "third", "dependsOn": "delay_mode", "dependsValue": "countdown"},
            {"key": "random_tail_enabled", "label": "随机追加尾数", "type": "checkbox", "colSpan": "full"},
            {"key": "random_min", "label": "最小秒数", "type": "number", "min": 0, "colSpan": "half", "dependsOn": "random_tail_enabled", "dependsValue": True},
            {"key": "random_max", "label": "最大秒数", "type": "number", "min": 0, "colSpan": "half", "dependsOn": "random_tail_enabled", "dependsValue": True},
        ],
    },
    {
        "id": "run_wait",
        "name": "运行等待",
        "execution_domain": "thread",
        "category": "flow_control",
        "description": "开启后等待指定时长，超时可选择抛出错误或标记完成继续；关闭则跳过并透传输入。进入等待时会发送系统通知提醒用户。",
        "icon": "Hourglass",
        "color": "#6366f1",
        "inputs": [{"id": "input", "label": "输入", "type": "any", "required": False}],
        "outputs": [{"id": "output", "label": "输出", "type": "any"}],
        "defaultConfig": {
            "enabled": False,
            "wait_seconds": 60,
            "timeout_action": "error",
        },
        "configFields": [
            {"key": "enabled", "label": "启用等待", "type": "toggle",
             "description": "开启后等待指定时长，超时按「超时操作」配置处理；关闭则跳过并透传输入"},
            {"key": "wait_seconds", "label": "等待时长（秒）", "type": "number",
             "min": 1, "max": 86400, "colSpan": "half",
             "dependsOn": "enabled", "dependsValue": True,
             "placeholder": "60"},
            {"key": "timeout_action", "label": "超时操作", "type": "select",
             "options": [
                 {"value": "error", "label": "抛出错误（结束工作流）"},
                 {"value": "complete", "label": "标记完成（继续执行下游）"},
             ],
             "colSpan": "full",
             "dependsOn": "enabled", "dependsValue": True},
        ],
    },
    {
        "id": "translate_task_name",
        "name": "翻译项目名称",
        "execution_domain": "thread",
        "category": "translation",
        "description": "将项目名称翻译为目标语言，可选择是否用译文替换任务名称",
        "icon": "Languages",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "input", "label": "输入", "type": "any"},
        ],
        "outputs": [
            {"id": "text", "label": "翻译结果", "type": "text"},
        ],
        "defaultConfig": {
            "replace_task_name": False,
        },
        "configFields": [
            {"key": "replace_task_name", "label": "将翻译后名称替换任务名称", "type": "checkbox"},
        ],
    },
    {
        "id": "get_task_info",
        "name": "获取任务信息",
        "execution_domain": "thread",
        "category": "flow_control",
        "description": "从 task.json 与输入节点配置读取任务元信息并作为文本输出：任务名称、输入语音、输出语言、变量1、变量2，供下游节点使用",
        "icon": "Info",
        "color": "#6366f1",
        "inputs": [{"id": "any", "label": "输入", "type": "any", "required": False}],
        "outputs": [
            {"id": "task_name", "label": "任务名称", "type": "text"},
            {"id": "input_language", "label": "输入语言", "type": "text"},
            {"id": "output_language", "label": "输出语言", "type": "text"},
            {"id": "var1", "label": "变量1", "type": "text"},
            {"id": "var2", "label": "变量2", "type": "text"},
        ],
        "defaultConfig": {},
        "configFields": [],
    },
    {
        "id": "aigc_comfyui",
        "name": "ComfyUI 生图",
        "execution_domain": "thread",
        "category": "aigc",
        "description": "调用本地/局域网 ComfyUI 实例运行工作流，支持文生图/图生图，参数来自「其他能力接口」设置",
        "icon": "Boxes",
        "color": "#22c55e",
        "inputs": [
            {"id": "text", "label": "提示词", "type": "text"},
            {"id": "reference_video", "label": "参考视频", "type": "video"},
            {"id": "first_frame", "label": "首帧", "type": "image"},
            {"id": "image2", "label": "图片2", "type": "image"},
            {"id": "image3", "label": "图片3", "type": "image"},
            {"id": "image4", "label": "图片4", "type": "image"},
            {"id": "last_frame", "label": "尾帧", "type": "image"},
        ],
        "outputs": [
            {"id": "images", "label": "产物列表", "type": "any"},
            {"id": "first", "label": "第一个产物", "type": "any"},
            {"id": "files", "label": "全部产物", "type": "any"},
        ],
        "defaultConfig": {
            "workflow_json": "Z-Image.json",
            "mode": "txt2img",
            "prompt_override": "",
            "resolution_mode": "preset",
            "resolution_preset": "1k",
            "width": 1024,
            "height": 1024,
            "resolution_custom": "",
            "aspect_ratio": "1:1",
            "num_images": 1,
            "node_params": "",
        },
        "configFields": [
            {"key": "workflow_json", "label": "工作流文件", "type": "text", "placeholder": "例如 Z-Image.json，放在 backend/aigc/workflows/", "colSpan": "full"},
            {"key": "mode", "label": "模式", "type": "chips", "singleSelect": True, "chipColor": "#22c55e", "options": [
                {"value": "txt2img", "label": "文生图"},
                {"value": "img2img", "label": "图生图"},
                {"value": "fusion", "label": "多图融合"},
                {"value": "grid", "label": "组图输出"},
                {"value": "i2grid", "label": "单图生组图"},
                {"value": "refs2grid", "label": "多参考图生组图"},
                {"value": "websearch", "label": "联网搜索生图"},
            ]},
            {"key": "prompt_override", "label": "覆盖提示词", "type": "textarea", "placeholder": "留空则使用连线输入的文本"},
            {"key": "resolution_mode", "label": "图片分辨率", "type": "chips", "singleSelect": True, "chipColor": "#22c55e", "options": [
                {"value": "preset", "label": "预设"},
                {"value": "size", "label": "长宽"},
                {"value": "custom", "label": "自定义"},
            ]},
            {"key": "resolution_preset", "label": "预设分辨率", "type": "select", "colSpan": "half", "dependsOn": "resolution_mode", "dependsValue": "preset", "options": [
                {"value": "1k", "label": "1K"},
                {"value": "2k", "label": "2K"},
                {"value": "3k", "label": "3K"},
                {"value": "4k", "label": "4K"},
            ]},
            {"key": "width", "label": "宽度(px)", "type": "number", "colSpan": "half", "min": 64, "max": 8192, "dependsOn": "resolution_mode", "dependsValue": "size"},
            {"key": "height", "label": "高度(px)", "type": "number", "colSpan": "half", "min": 64, "max": 8192, "dependsOn": "resolution_mode", "dependsValue": "size"},
            {"key": "resolution_custom", "label": "自定义分辨率", "type": "text", "colSpan": "half", "dependsOn": "resolution_mode", "dependsValue": "custom", "placeholder": "如 1920x1080 / 1080p / 1K"},
            {"key": "aspect_ratio", "label": "图片比例", "type": "select", "colSpan": "half", "options": [
                {"value": "1:1", "label": "1:1"},
                {"value": "16:9", "label": "16:9"},
                {"value": "9:16", "label": "9:16"},
                {"value": "4:3", "label": "4:3"},
                {"value": "3:4", "label": "3:4"},
                {"value": "3:2", "label": "3:2"},
                {"value": "2:3", "label": "2:3"},
                {"value": "21:9", "label": "21:9"},
            ]},
            {"key": "num_images", "label": "生成数量", "type": "number", "colSpan": "half", "min": 1, "max": 10, "description": "注入工作流 batch_size 类节点"},
            {"key": "node_params", "label": "节点参数(JSON)", "type": "textarea", "placeholder": "可选，例如 12 号节点的 inputs.seed 覆盖工作流输入", "colSpan": "full"},
        ],
    },
    {
        "id": "aigc_runninghub",
        "name": "RunningHub 生成",
        "execution_domain": "process",
        "category": "aigc",
        "description": "调用 RunningHub OpenAPI 运行工作流或 AI 应用，生成图片/视频，参数来自「其他能力接口」设置",
        "icon": "Cloudy",
        "color": "#0ea5e9",
        "inputs": [
            {"id": "text", "label": "提示词", "type": "text"},
            {"id": "reference_video", "label": "参考视频", "type": "video"},
            {"id": "first_frame", "label": "首帧", "type": "image"},
            {"id": "image2", "label": "图片2", "type": "image"},
            {"id": "image3", "label": "图片3", "type": "image"},
            {"id": "image4", "label": "图片4", "type": "image"},
            {"id": "last_frame", "label": "尾帧", "type": "image"},
        ],
        "outputs": [
            {"id": "images", "label": "产物列表", "type": "any"},
            {"id": "first", "label": "第一个产物", "type": "any"},
            {"id": "files", "label": "全部产物", "type": "any"},
        ],
        "defaultConfig": {
            "kind": "workflow",
            "entry_id": "",
            "prompt_override": "",
            "resolution_mode": "preset",
            "resolution_preset": "1k",
            "width": 1024,
            "height": 1024,
            "resolution_custom": "",
            "aspect_ratio": "1:1",
            "num_images": 1,
            "node_info_list": "",
        },
        "configFields": [
            {"key": "kind", "label": "任务类型", "type": "chips", "singleSelect": True, "chipColor": "#0ea5e9", "link": {"label": "访问 RunningHub", "url": "https://www.runninghub.cn?inviteCode=x6yzzpwl"}, "options": [
                {"value": "workflow", "label": "工作流"},
                {"value": "ai_app", "label": "AI 应用"},
            ]},
            {"key": "entry_id", "label": "工作流/应用 ID", "type": "text", "placeholder": "RunningHub 工作流 ID 或 AI 应用 webappId", "colSpan": "full"},
            {"key": "prompt_override", "label": "覆盖提示词", "type": "textarea", "placeholder": "留空则使用连线输入的文本"},
            {"key": "resolution_mode", "label": "图片分辨率", "type": "chips", "singleSelect": True, "chipColor": "#0ea5e9", "options": [
                {"value": "preset", "label": "预设"},
                {"value": "size", "label": "长宽"},
                {"value": "custom", "label": "自定义"},
            ]},
            {"key": "resolution_preset", "label": "预设分辨率", "type": "select", "colSpan": "half", "dependsOn": "resolution_mode", "dependsValue": "preset", "options": [
                {"value": "1k", "label": "1K"},
                {"value": "2k", "label": "2K"},
                {"value": "3k", "label": "3K"},
                {"value": "4k", "label": "4K"},
            ]},
            {"key": "width", "label": "宽度(px)", "type": "number", "colSpan": "half", "min": 64, "max": 8192, "dependsOn": "resolution_mode", "dependsValue": "size"},
            {"key": "height", "label": "高度(px)", "type": "number", "colSpan": "half", "min": 64, "max": 8192, "dependsOn": "resolution_mode", "dependsValue": "size"},
            {"key": "resolution_custom", "label": "自定义分辨率", "type": "text", "colSpan": "half", "dependsOn": "resolution_mode", "dependsValue": "custom", "placeholder": "如 1920x1080 / 1080p / 1K"},
            {"key": "aspect_ratio", "label": "图片比例", "type": "select", "colSpan": "half", "options": [
                {"value": "1:1", "label": "1:1"},
                {"value": "16:9", "label": "16:9"},
                {"value": "9:16", "label": "9:16"},
                {"value": "4:3", "label": "4:3"},
                {"value": "3:4", "label": "3:4"},
                {"value": "3:2", "label": "3:2"},
                {"value": "2:3", "label": "2:3"},
                {"value": "21:9", "label": "21:9"},
            ]},
            {"key": "num_images", "label": "生成数量", "type": "number", "colSpan": "half", "min": 1, "max": 10},
            {"key": "node_info_list", "label": "节点参数(JSON)", "type": "textarea", "placeholder": '可选，例如 [{"nodeId":"1","fieldName":"prompt","fieldValue":"cat"}]，节点已自动注入图片列表与分辨率参数', "colSpan": "full"},
        ],
    },
    {
        "id": "aigc_jimeng",
        "name": "即梦 CLI 生成",
        "execution_domain": "process",
        "category": "aigc",
        "description": "通过本地即梦(dreamina) CLI 生成图片或视频，支持文生图/图生图/文生视频/图生视频/首尾帧视频",
        "icon": "Wand2",
        "color": "#a855f7",
        "inputs": [
            {"id": "text", "label": "提示词", "type": "text"},
            {"id": "reference_video", "label": "参考视频", "type": "video"},
            {"id": "first_frame", "label": "首帧", "type": "image"},
            {"id": "image2", "label": "图片2", "type": "image"},
            {"id": "image3", "label": "图片3", "type": "image"},
            {"id": "image4", "label": "图片4", "type": "image"},
            {"id": "last_frame", "label": "尾帧", "type": "image"},
        ],
        "outputs": [
            {"id": "images", "label": "产物列表", "type": "any"},
            {"id": "first", "label": "第一个产物", "type": "any"},
            {"id": "files", "label": "全部产物", "type": "any"},
        ],
        "defaultConfig": {
            "mode": "image",
            "model": "",
            "prompt_override": "",
            "resolution_mode": "preset",
            "resolution_preset": "1k",
            "width": 1024,
            "height": 1024,
            "resolution_custom": "",
            "aspect_ratio": "1:1",
            "num_images": 1,
            "async_query": True,
        },
        "configFields": [
            {"key": "mode", "label": "生成类型", "type": "chips", "singleSelect": True, "chipColor": "#a855f7", "action": {"label": "安装即梦插件", "url": "/api/aigc/jimeng/install", "method": "POST"}, "options": [
                {"value": "image", "label": "文/图生图"},
                {"value": "video", "label": "文/图生视频"},
            ]},
            {"key": "model", "label": "模型名称", "type": "text", "placeholder": "图片：4.5 / 5.0Pro；视频：seedance2.0 等", "description": "留空使用 CLI 默认模型"},
            {"key": "prompt_override", "label": "覆盖提示词", "type": "textarea", "placeholder": "留空则使用连线输入的文本"},
            {"key": "resolution_mode", "label": "图片分辨率", "type": "chips", "singleSelect": True, "chipColor": "#a855f7", "options": [
                {"value": "preset", "label": "预设"},
                {"value": "size", "label": "长宽"},
                {"value": "custom", "label": "自定义"},
            ]},
            {"key": "resolution_preset", "label": "预设分辨率", "type": "select", "colSpan": "half", "dependsOn": "resolution_mode", "dependsValue": "preset", "options": [
                {"value": "1k", "label": "1K"},
                {"value": "2k", "label": "2K"},
                {"value": "3k", "label": "3K"},
                {"value": "4k", "label": "4K"},
            ]},
            {"key": "width", "label": "宽度(px)", "type": "number", "colSpan": "half", "min": 64, "max": 8192, "dependsOn": "resolution_mode", "dependsValue": "size"},
            {"key": "height", "label": "高度(px)", "type": "number", "colSpan": "half", "min": 64, "max": 8192, "dependsOn": "resolution_mode", "dependsValue": "size"},
            {"key": "resolution_custom", "label": "自定义分辨率", "type": "text", "colSpan": "half", "dependsOn": "resolution_mode", "dependsValue": "custom", "placeholder": "如 1920x1080 / 1080p / 1K"},
            {"key": "aspect_ratio", "label": "图片比例", "type": "select", "colSpan": "half", "options": [
                {"value": "1:1", "label": "1:1"},
                {"value": "16:9", "label": "16:9"},
                {"value": "9:16", "label": "9:16"},
                {"value": "4:3", "label": "4:3"},
                {"value": "3:4", "label": "3:4"},
                {"value": "3:2", "label": "3:2"},
                {"value": "2:3", "label": "2:3"},
                {"value": "21:9", "label": "21:9"},
            ]},
            {"key": "num_images", "label": "生成数量", "type": "number", "colSpan": "half", "min": 1, "max": 10, "description": "仅图片模式生效，逐张调用 CLI"},
            {"key": "async_query", "label": "提交后异步轮询结果", "type": "toggle", "defaultValue": True, "description": "关闭则仅返回提交结果（submit_id），需自行查询"},
        ],
    },
    {
        "id": "agi_project",
        "name": "项目立项·剧本创作",
        "execution_domain": "thread",
        "category": "agi_story",
        "description": "AI 漫剧·起始节点：创建创作项目并用 LLM 打好故事骨架（世界观/大纲/总剧本），产出 creation_id 贯穿下游全部节点",
        "icon": "Rocket",
        "color": "#db2777",
        "inputs": [
            {"id": "text", "label": "创意/要求", "type": "text"},
        ],
        "outputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "project", "label": "项目骨架", "type": "json"},
        ],
        "defaultConfig": {
            "project_name": "AI漫剧项目",
            "llm_model": "",
            "style_preset": "",
            "art_style_custom": "",
            "genre_tags": "",
            "art_style_tags": "",
            "audience_tags": "",
            "video_aspect_ratio": "16:9",
            "outline_prompt": "",
        },
        "configFields": [
            {"key": "llm_model", "label": "LLM 模型", "type": "text", "colSpan": "half", "placeholder": "留空使用全局 LLM 路由", "description": "本节点 LLM 请求使用的模型名"},
            {"key": "browse_project", "label": "浏览项目", "type": "button", "colSpan": "full", "description": "以思维导图方式可视化浏览项目骨架与各阶段产物（文本/图片/视频/音频）"},
            {"key": "project_name", "label": "项目名称", "type": "text", "colSpan": "half"},
            {"key": "style_preset", "label": "风格预设", "type": "api-select", "apiEndpoint": "/api/creation/style-presets", "optionLabel": "name", "optionValue": "id", "colSpan": "full", "description": "内置常见画风（日式/国漫/欧美/写实/水墨/像素等）；选中后题材/受众自动带出，画风写入【画风锁定】供全链路生图统一取用。下拉里没有想要的风格时，用下方「自定义画风」直接输入"},
            {"key": "art_style_custom", "label": "自定义画风", "type": "textarea", "colSpan": "full", "placeholder": "如：厚涂写实二次元，冷色调，电影级光影，真实材质；留空则用所选预设画风", "description": "直接输入画风描述，优先级最高；写入【画风锁定】后，人物/场景/道具/分镜等所有生图节点统一取用，保证风格一致"},
            {"key": "genre_tags", "label": "类型标签", "type": "text", "colSpan": "half", "placeholder": "逗号分隔，如 科幻,冒险"},
            {"key": "art_style_tags", "label": "画风标签", "type": "text", "colSpan": "half", "placeholder": "逗号分隔，如 赛博朋克"},
            {"key": "audience_tags", "label": "受众标签", "type": "text", "colSpan": "half"},
            {"key": "video_aspect_ratio", "label": "视频比例(尺寸)", "type": "select", "colSpan": "half", "options": [
                {"value": "9:16", "label": "9:16 竖屏"},
                {"value": "16:9", "label": "16:9 横屏"},
                {"value": "4:3", "label": "4:3"},
                {"value": "3:4", "label": "3:4"},
                {"value": "1:1", "label": "1:1"},
            ], "description": "整部漫剧默认画幅：场景概念图、分镜首尾帧、分镜视频未单独指定比例时均按此生成"},
            {"key": "outline_prompt", "label": "创意与要求", "type": "textarea", "colSpan": "full", "placeholder": "世界观方向、题材、体量等；也可从 text 端口传入"},
        ],
    },
    {
        "id": "agi_deepen",
        "name": "剧本深化",
        "execution_domain": "thread",
        "category": "agi_story",
        "description": "AI 漫剧·剧本深化：把项目骨架深化为严格格式化的设定书并入库——剧本简介、各章节内容规划(建章)、人物设计提炼(同名提炼/新增)、画风元素锁定(写入骨架供下游生图取用)",
        "icon": "PenLine",
        "color": "#db2777",
        "inputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "any"},
            {"id": "text", "label": "额外要求", "type": "text"},
        ],
        "outputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "bible", "label": "剧本设定书", "type": "json"},
            {"id": "synopsis", "label": "剧本简介", "type": "text"},
            {"id": "style_bible", "label": "画风锁定", "type": "text"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "llm_model": "",
            "num_chapters": 3,
            "num_characters": 3,
            "art_style_input": "",
            "extra_requirements": "",
            "require_screenplay": True,
            "replace_chapters": False,
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "连线传入 creation_id 时优先"},
            {"key": "llm_model", "label": "LLM 模型", "type": "text", "colSpan": "half", "placeholder": "留空使用全局 LLM 路由", "description": "本节点 LLM 请求使用的模型名"},
            {"key": "num_chapters", "label": "章节数量", "type": "number", "colSpan": "half", "min": 1, "max": 50},
            {"key": "num_characters", "label": "人物数量", "type": "number", "colSpan": "half", "min": 1, "max": 20},
            {"key": "art_style_input", "label": "画风人工指定", "type": "text", "colSpan": "full", "placeholder": "留空由 LLM 锁定"},
            {"key": "extra_requirements", "label": "额外要求", "type": "textarea", "colSpan": "full", "placeholder": "题材禁忌、体量、风格倾向等；也可从 text 端口传入"},
            {"key": "require_screenplay", "label": "强制格式化剧本", "type": "toggle", "defaultValue": True, "description": "章节内容规划必须写成格式化剧本（## S编号 | 内景/外景 · 地点 | 时间段 + 对白），不合规会自动纠错重试"},
            {"key": "replace_chapters", "label": "重置章节规划", "type": "toggle", "defaultValue": False, "description": "开启则先删除项目已有章节(含其下分镜！)再写入本章规划"},
        ],
    },
    {
        "id": "agi_character",
        "name": "人物资产创作",
        "execution_domain": "thread",
        "category": "agi_asset",
        "description": "AI 漫剧·人物资产创作：用 LLM 生成人物设定并写入创作项目，可发布到公共角色库并生成多视角图",
        "icon": "Users",
        "color": "#db2777",
        "inputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "any"},
            {"id": "text", "label": "创意简介", "type": "text"},
        ],
        "outputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "characters", "label": "人物设定", "type": "json"},
            {"id": "images", "label": "角色立绘", "type": "any"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "genre_tags": "",
            "num_characters": 4,
            "char_count_mode": "follow",
            "mode": "auto",
            "llm_model": "",
            "generate_images": False,
            "publish_to_library": True,
            "seed": "",
            "num_views": 3,
            "view_prompts": "正面全身,侧面半身,背面全身",
            "image_interface": "",
            "image_model": "",
            "image_resolution": "",
            "negative_prompt": "",
            "art_style_prompt": "",
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入 creation_id 时优先"},
            {"key": "llm_model", "label": "LLM 模型", "type": "text", "colSpan": "half", "placeholder": "留空使用全局 LLM 路由", "description": "本节点 LLM 请求使用的模型名"},
            {"key": "mode", "label": "资产来源", "type": "select", "colSpan": "half", "options": [
                {"value": "auto", "label": "自动(有剧本则提取)"}, {"value": "extract", "label": "从剧本提取"}, {"value": "generate", "label": "依创意生成"}],
                "description": "提取模式按人物姓名（场景按地点+时间段）去重复用，适合小说/剧本改编"},
            {"key": "char_count_mode", "label": "人物数量", "type": "select", "colSpan": "half", "options": [
                {"value": "follow", "label": "跟随项目"}, {"value": "manual", "label": "手动指定"}],
                "description": "跟随项目：由 LLM 依骨架与剧情决定人数（默认）；手动指定：固定数量"},
            {"key": "num_characters", "label": "指定数量", "type": "number", "colSpan": "half", "min": 1, "max": 20, "dependsOn": "char_count_mode", "dependsValue": "manual"},
            {"key": "genre_tags", "label": "发布标签", "type": "text", "placeholder": "逗号分隔，发布到公共角色库时使用", "colSpan": "half"},
            {"key": "art_style_prompt", "label": "画风补充提示词", "type": "textarea", "placeholder": "追加到生图/分镜提示词中的画风描述"},
            {"key": "generate_images", "label": "生成角色立绘", "type": "toggle", "defaultValue": False},
            {"key": "seed", "label": "生图种子(留空自动)", "type": "number", "colSpan": "half", "min": 0, "description": "固定种子可让角色立绘在重生成时保持一致；留空则由系统为角色分配并锁定"},
            {"key": "publish_to_library", "label": "发布到公共角色库", "type": "toggle", "defaultValue": True, "description": "开启后人物自动发布为公共角色，立绘以多视角图形式挂到角色库 images_dir"},
            {"key": "num_views", "label": "多视角数量", "type": "number", "colSpan": "half", "min": 1, "max": 6, "dependsOn": "publish_to_library", "dependsValue": True},
            {"key": "view_prompts", "label": "视角标签", "type": "text", "colSpan": "half", "placeholder": "逗号分隔，如 正面全身,侧面半身,背面全身", "dependsOn": "publish_to_library", "dependsValue": True},
            {"key": "image_interface", "label": "生图接口", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/enabled", "colSpan": "half"},
            {"key": "image_model", "label": "生图模型", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/{image_interface}/models-for-node?mode=txt2img", "dependsOn": "image_interface", "colSpan": "half", "placeholder": "跟随接口默认模型"},
            {"key": "image_resolution", "label": "出图分辨率", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/{image_interface}/param-options?model={image_model}", "dependsOn": "image_model", "colSpan": "half", "placeholder": "跟随模型默认"},
            {"key": "negative_prompt", "label": "反向提示词", "type": "textarea", "colSpan": "full", "placeholder": "留空则不使用（如：低质量, 多余手指, 文字水印）", "description": "透传给生图接口的 negative_prompt"},
        ],
    },
    {
        "id": "agi_voice",
        "name": "人物音色生产",
        "execution_domain": "process",
        "category": "agi_asset",
        "description": "AI 漫剧·人物音色生产：按「生成对象」为目标人物一次性设计 15~25 字台词，分别调用设计与克隆 TTS 接口合成音色样本，登记到配音谷音色库（vf:voices 引用）并绑定人物 voice_ref，打通分镜配音的音色克隆链路",
        "icon": "AudioWaveform",
        "color": "#db2777",
        "inputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "any"},
        ],
        "outputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "voices", "label": "音色清单", "type": "json"},
            {"id": "audio", "label": "样本音频", "type": "audio"},
            {"id": "failed", "label": "失败清单", "type": "json"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "llm_model": "",
            "target_mode": "all",
            "voice_targets": [],
            "default_mode": "design",
            "design_interface": "",
            "design_model": "",
            "clone_interface": "",
            "clone_model": "",
            "tts_speed": 1.0,
            "overwrite": False,
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入 creation_id 时优先"},
            {"key": "llm_model", "label": "LLM 模型", "type": "text", "colSpan": "half", "placeholder": "留空使用全局 LLM 路由", "description": "设计各人物朗读台词所用的模型"},
            {"key": "target_mode", "label": "生成对象", "type": "select", "colSpan": "half", "options": [
                {"value": "all", "label": "全部"},
                {"value": "list", "label": "列表选择"}],
                "description": "「列表选择」时读取项目已有角色，在下方清单里勾选要生成音色的人物"},
            {"key": "voice_targets", "label": "角色音色清单", "type": "voice-target-list", "colSpan": "full", "apiEndpoint": "/api/creation/{creation_id}/characters", "dependsOn": "target_mode", "dependsValue": "list", "description": "勾选列默认全选；设计模式为「设计」时无需参考音频，为「克隆」时必须选择参考音频"},
            {"key": "default_mode", "label": "新增角色默认模式", "type": "select", "colSpan": "half", "options": [
                {"value": "design", "label": "设计"},
                {"value": "clone", "label": "克隆"}],
                "dependsOn": "target_mode", "dependsValue": "list", "description": "清单里未显式设置模式时使用的默认设计模式"},
            {"key": "design_interface", "label": "音色设计接口", "type": "api-select", "apiEndpoint": "/api/tts-interfaces/enabled?mode=voice_design", "colSpan": "half", "description": "仅显示支持「音色设计」模式的已启用 TTS 接口"},
            {"key": "design_model", "label": "设计模型", "type": "api-select", "apiEndpoint": "/api/tts-interfaces/{design_interface}/models-for-node", "dependsOn": "design_interface", "colSpan": "half", "placeholder": "跟随接口默认模型"},
            {"key": "clone_interface", "label": "音色克隆接口", "type": "api-select", "apiEndpoint": "/api/tts-interfaces/enabled?mode=clone,controllable_clone", "colSpan": "half", "description": "仅显示支持「克隆/可控克隆」模式的已启用 TTS 接口"},
            {"key": "clone_model", "label": "克隆模型", "type": "api-select", "apiEndpoint": "/api/tts-interfaces/{clone_interface}/models-for-node", "dependsOn": "clone_interface", "colSpan": "half", "placeholder": "跟随接口默认模型"},
            {"key": "tts_speed", "label": "语速", "type": "number", "colSpan": "half", "min": 0.5, "max": 2.0, "step": 0.05, "placeholder": "1.0", "description": "样本与后续配音的语速基准（接口不支持时忽略）"},
            {"key": "overwrite", "label": "覆盖已有音色", "type": "toggle", "defaultValue": False},
        ],
    },
    {
        "id": "agi_scene",
        "name": "场景资产创作",
        "execution_domain": "process",
        "category": "agi_asset",
        "description": "AI 漫剧·场景资产创作：生成关键场景(地点/时间段/光影)并生成固定视角概念图，写入场景资产表并登记 scene_image 资产",
        "icon": "Image",
        "color": "#db2777",
        "inputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "any"},
            {"id": "text", "label": "补充描述", "type": "text"},
        ],
        "outputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "scene_ids", "label": "场景ID列表", "type": "json"},
            {"id": "scenes", "label": "场景清单", "type": "json"},
            {"id": "images", "label": "场景图", "type": "any"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "num_scenes": 6,
            "mode": "auto",
            "llm_model": "",
            "generate_images": True,
            "image_interface": "",
            "image_model": "",
            "image_resolution": "",
            "negative_prompt": "",
            "art_style_prompt": "",
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入 creation_id 时优先"},
            {"key": "llm_model", "label": "LLM 模型", "type": "text", "colSpan": "half", "placeholder": "留空使用全局 LLM 路由", "description": "本节点 LLM 请求使用的模型名"},
            {"key": "mode", "label": "资产来源", "type": "select", "colSpan": "half", "options": [
                {"value": "auto", "label": "自动(有剧本则提取)"}, {"value": "extract", "label": "从剧本提取"}, {"value": "generate", "label": "依创意生成"}],
                "description": "提取模式按人物姓名（场景按地点+时间段）去重复用，适合小说/剧本改编"},
            {"key": "num_scenes", "label": "场景数量", "type": "number", "colSpan": "half", "min": 1, "max": 30},
            {"key": "generate_images", "label": "生成场景图", "type": "toggle", "defaultValue": True},
            {"key": "art_style_prompt", "label": "画风补充提示词", "type": "textarea", "colSpan": "full"},
            {"key": "image_interface", "label": "生图接口", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/enabled", "colSpan": "half"},
            {"key": "image_model", "label": "生图模型", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/{image_interface}/models-for-node?mode=txt2img", "dependsOn": "image_interface", "colSpan": "half", "placeholder": "跟随接口默认模型"},
            {"key": "image_resolution", "label": "出图分辨率", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/{image_interface}/param-options?model={image_model}", "dependsOn": "image_model", "colSpan": "half", "placeholder": "跟随模型默认"},
            {"key": "negative_prompt", "label": "反向提示词", "type": "textarea", "colSpan": "full", "placeholder": "留空则不使用（如：低质量, 多余手指, 文字水印）", "description": "透传给生图接口的 negative_prompt"},
        ],
    },
    {
        "id": "agi_prop",
        "name": "道具资产创作",
        "execution_domain": "process",
        "category": "agi_asset",
        "description": "AI 漫剧·道具资产创作：从剧本提取/生成推动剧情的关键道具，生成白底单品图，写入道具资产表并登记 prop_image 资产",
        "icon": "Box",
        "color": "#db2777",
        "inputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "any"},
            {"id": "text", "label": "补充描述", "type": "text"},
        ],
        "outputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "prop_ids", "label": "道具ID列表", "type": "json"},
            {"id": "props", "label": "道具清单", "type": "json"},
            {"id": "images", "label": "道具图", "type": "any"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "num_props": 6,
            "mode": "auto",
            "llm_model": "",
            "generate_images": True,
            "image_interface": "",
            "image_model": "",
            "image_resolution": "",
            "negative_prompt": "",
            "art_style_prompt": "",
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入 creation_id 时优先"},
            {"key": "llm_model", "label": "LLM 模型", "type": "text", "colSpan": "half", "placeholder": "留空使用全局 LLM 路由", "description": "本节点 LLM 请求使用的模型名"},
            {"key": "mode", "label": "资产来源", "type": "select", "colSpan": "half", "options": [
                {"value": "auto", "label": "自动(有剧本则提取)"}, {"value": "extract", "label": "从剧本提取"}, {"value": "generate", "label": "依创意生成"}],
                "description": "提取模式按道具名去重复用，适合小说/剧本改编"},
            {"key": "num_props", "label": "道具数量", "type": "number", "colSpan": "half", "min": 1, "max": 30},
            {"key": "generate_images", "label": "生成道具图", "type": "toggle", "defaultValue": True},
            {"key": "art_style_prompt", "label": "画风补充提示词", "type": "textarea", "colSpan": "full"},
            {"key": "image_interface", "label": "生图接口", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/enabled", "colSpan": "half"},
            {"key": "image_model", "label": "生图模型", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/{image_interface}/models-for-node?mode=txt2img", "dependsOn": "image_interface", "colSpan": "half", "placeholder": "跟随接口默认模型"},
            {"key": "image_resolution", "label": "出图分辨率", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/{image_interface}/param-options?model={image_model}", "dependsOn": "image_model", "colSpan": "half", "placeholder": "跟随模型默认"},
            {"key": "negative_prompt", "label": "反向提示词", "type": "textarea", "colSpan": "full", "placeholder": "留空则不使用（如：低质量, 多余手指, 文字水印）", "description": "透传给生图接口的 negative_prompt"},
        ],
    },
    {
        "id": "agi_extract",
        "name": "资产自动提取",
        "execution_domain": "thread",
        "category": "agi_asset",
        "description": "AI 漫剧·资产自动提取：从格式化剧本一次性提取人物/场景/道具，按名去重入库（同名复用更新，新增写入一级资产表），对标 Drama extractor",
        "icon": "Sparkles",
        "color": "#db2777",
        "inputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "any"},
            {"id": "text", "label": "补充剧本", "type": "text"},
        ],
        "outputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "character_ids", "label": "人物ID列表", "type": "json"},
            {"id": "scene_ids", "label": "场景ID列表", "type": "json"},
            {"id": "prop_ids", "label": "道具ID列表", "type": "json"},
            {"id": "characters", "label": "人物清单", "type": "json"},
            {"id": "scenes", "label": "场景清单", "type": "json"},
            {"id": "props", "label": "道具清单", "type": "json"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "mode": "auto",
            "llm_model": "",
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入 creation_id 时优先"},
            {"key": "mode", "label": "提取模式", "type": "select", "colSpan": "half", "options": [
                {"value": "auto", "label": "自动(有剧本则提取)"}, {"value": "extract", "label": "从剧本提取"}, {"value": "generate", "label": "依创意生成"}]},
            {"key": "llm_model", "label": "LLM 模型", "type": "text", "colSpan": "half", "placeholder": "留空使用全局 LLM 路由", "description": "本节点 LLM 请求使用的模型名"},
        ],
    },
    {
        "id": "agi_prompt",
        "name": "生成提示词",
        "execution_domain": "thread",
        "category": "agi_asset",
        "description": "AI 漫剧·生成提示词：把资产描述结合整体画风生成 final_prompt 写入库（可调试/可人工改），供生图节点使用；资产类型选「分镜」时生成 image_prompt/video_prompt 供首尾帧与生视频节点消费",
        "icon": "Wand2",
        "color": "#db2777",
        "inputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "any"},
            {"id": "ids", "label": "资产ID列表(可选)", "type": "json"},
            {"id": "chapter_id", "label": "章节ID(分镜用)", "type": "text"},
            {"id": "chapter_ids", "label": "多章节ID列表(分镜用)", "type": "json"},
        ],
        "outputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "asset_type", "label": "资产类型", "type": "text"},
            {"id": "ids", "label": "资产ID列表", "type": "json"},
            {"id": "final_prompts", "label": "提示词结果", "type": "json"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "asset_type": "scene",
            "chapter_ids": "",
            "llm_model": "",
            "art_style_prompt": "",
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入 creation_id 时优先"},
            {"key": "asset_type", "label": "资产类型", "type": "select", "colSpan": "half", "options": [
                {"value": "character", "label": "人物"}, {"value": "scene", "label": "场景"}, {"value": "prop", "label": "道具"}, {"value": "shot", "label": "分镜（image_prompt/video_prompt）"}]},
            {"key": "llm_model", "label": "LLM 模型", "type": "text", "colSpan": "half", "placeholder": "留空使用全局 LLM 路由"},
            {"key": "art_style_prompt", "label": "画风补充提示词", "type": "textarea", "colSpan": "full"},
            {"key": "chapter_ids", "label": "章节ID列表（资产类型=分镜时生效，留空=全项目）", "type": "text", "colSpan": "full", "placeholder": "多个章节ID用逗号分隔"},
        ],
    },
    {
        "id": "agi_chapter",
        "name": "章节剧本",
        "execution_domain": "thread",
        "category": "agi_story",
        "description": "AI 漫剧·章节剧本：为创作项目生成若干章节（标题/原文/简述）并写入",
        "icon": "BookOpen",
        "color": "#db2777",
        "inputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "any"},
            {"id": "text", "label": "章节指引", "type": "text"},
        ],
        "outputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "chapter_id", "label": "章节ID", "type": "text"},
            {"id": "chapter_ids", "label": "章节ID列表", "type": "json"},
            {"id": "chapters", "label": "章节内容", "type": "json"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "num_chapters": 1,
            "llm_model": "",
            "chapter_title": "",
            "force": False,
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "章节管理目标项目；连线传入 creation_id 时优先"},
            {"key": "llm_model", "label": "LLM 模型", "type": "text", "colSpan": "half", "placeholder": "留空使用全局 LLM 路由", "description": "本节点 LLM 请求使用的模型名"},
            {"key": "num_chapters", "label": "章节数量", "type": "number", "colSpan": "half", "min": 1, "max": 50},
            {"key": "chapter_title", "label": "首章标题(可选)", "type": "text", "colSpan": "half"},
            {"key": "force", "label": "强制重生成", "type": "switch", "colSpan": "half", "description": "开启后忽略已就绪章节，全部重新生成（断点续跑默认跳过已完成项）"},
        ],
    },
    {
        "id": "agi_shot",
        "name": "分镜剧本",
        "execution_domain": "thread",
        "category": "agi_story",
        "description": "AI 漫剧·分镜剧本：为章节生成分镜（出场人物/场景/对话/音效设计）并写入",
        "icon": "Clapperboard",
        "color": "#db2777",
        "inputs": [
            {"id": "chapter_id", "label": "章节ID", "type": "any"},
            {"id": "text", "label": "分镜指引", "type": "text"},
        ],
        "outputs": [
            {"id": "chapter_id", "label": "章节ID", "type": "text"},
            {"id": "shot_ids", "label": "分镜ID列表", "type": "json"},
            {"id": "shots", "label": "分镜内容", "type": "json"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "chapter_id": "",
            "num_shots": 8,
            "llm_model": "",
            "force": False,
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入 chapter_id 时可省"},
            {"key": "chapter_id", "label": "章节", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/chapters", "optionLabel": "title", "optionValue": "id", "followPort": "chapter_id", "colSpan": "full", "description": "先选择创作项目；连线传入 chapter_id 时优先"},
            {"key": "llm_model", "label": "LLM 模型", "type": "text", "colSpan": "half", "placeholder": "留空使用全局 LLM 路由", "description": "本节点 LLM 请求使用的模型名"},
            {"key": "num_shots", "label": "分镜数量", "type": "number", "colSpan": "half", "min": 1, "max": 60},
            {"key": "force", "label": "强制重生成", "type": "switch", "colSpan": "half", "description": "开启后忽略已就绪分镜，全部重新生成（断点续跑默认跳过已完成项）"},
        ],
    },
    {
        "id": "agi_shot_prompt",
        "name": "组装分镜提示词",
        "execution_domain": "process",
        "category": "agi_shot",
        "description": "AI 漫剧·组装分镜提示词：把分镜用到的角色图/场景图/道具图按【image1】/【image2】顺序组装，细化为 8 个故事走向关键帧的生图提示词(JSON)，并产出有序参考图供「分镜首尾帧」图生图使用",
        "icon": "ScrollText",
        "color": "#ea580c",
        "inputs": [
            {"id": "shot_id", "label": "分镜ID(单个)", "type": "any"},
            {"id": "chapter_id", "label": "章节ID(批处理)", "type": "any"},
            {"id": "chapter_ids", "label": "多章节ID列表(可选)", "type": "json"},
        ],
        "outputs": [
            {"id": "shot_id", "label": "分镜ID", "type": "text"},
            {"id": "shot_ids", "label": "分镜ID列表", "type": "json"},
            {"id": "image_prompts", "label": "组装提示词", "type": "json"},
            {"id": "image_prompt_refs", "label": "有序参考图", "type": "json"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "chapter_id": "",
            "shot_id": "",
            "llm_model": "",
            "force": False,
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入时优先"},
            {"key": "chapter_id", "label": "章节(批处理)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/chapters", "optionLabel": "title", "optionValue": "id", "followPort": "chapter_id", "colSpan": "full", "description": "选择后整章批处理；连线传入时优先"},
            {"key": "shot_id", "label": "分镜(单个)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/shots?chapter_id={chapter_id}", "optionLabel": "label", "optionValue": "id", "colSpan": "full", "description": "先选择创作项目与章节；连线传入时优先"},
            {"key": "llm_model", "label": "LLM 模型", "type": "api-select", "apiEndpoint": "/api/llm/interfaces/enabled", "colSpan": "half", "placeholder": "跟随路由默认模型"},
            {"key": "force", "label": "强制重组装", "type": "switch", "colSpan": "full", "description": "开启后忽略已组装提示词，重新生成"},
        ],
    },
    {
        "id": "agi_shot_frames",
        "name": "分镜首尾帧",
        "execution_domain": "process",
        "category": "agi_shot",
        "description": "AI 漫剧·分镜首尾帧：为分镜生成首/尾帧概念图（可整章批处理），注入角色多视角图/场景图作为参考图保证一致性",
        "icon": "Frame",
        "color": "#db2777",
        "inputs": [
            {"id": "shot_id", "label": "分镜ID(单个)", "type": "any"},
            {"id": "chapter_id", "label": "章节ID(批处理)", "type": "any"},
            {"id": "chapter_ids", "label": "多章节ID列表(可选)", "type": "json"},
            {"id": "first_frame", "label": "首帧(可选)", "type": "image"},
            {"id": "last_frame", "label": "尾帧(可选)", "type": "image"},
        ],
        "outputs": [
            {"id": "shot_id", "label": "分镜ID", "type": "text"},
            {"id": "first_frame", "label": "首帧", "type": "image"},
            {"id": "last_frame", "label": "尾帧", "type": "image"},
            {"id": "shot_ids", "label": "分镜ID列表", "type": "json"},
            {"id": "first_frames", "label": "首帧列表", "type": "json"},
            {"id": "last_frames", "label": "尾帧列表", "type": "json"},
            {"id": "images", "label": "帧图", "type": "any"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "chapter_id": "",
            "shot_id": "",
            "generate_first": True,
            "generate_last": True,
            "use_char_ref": True,
            "use_scene_ref": True,
            "max_ref_images": 4,
            "gen_mode": "txt2img",
            "image_interface": "",
            "image_model": "",
            "img2img_model": "",
            "image_resolution": "",
            "negative_prompt": "",
            "art_style_prompt": "",
            "force": False,
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入时优先"},
            {"key": "chapter_id", "label": "章节(批处理)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/chapters", "optionLabel": "title", "optionValue": "id", "followPort": "chapter_id", "colSpan": "full", "description": "选择后整章批处理；连线传入时优先"},
            {"key": "shot_id", "label": "分镜(单个)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/shots?chapter_id={chapter_id}", "optionLabel": "label", "optionValue": "id", "colSpan": "full", "description": "先选择创作项目与章节；连线传入时优先"},
            {"key": "generate_first", "label": "生成首帧", "type": "toggle", "defaultValue": True},
            {"key": "generate_last", "label": "生成尾帧", "type": "toggle", "defaultValue": True},
            {"key": "use_char_ref", "label": "角色参考图", "type": "toggle", "defaultValue": True, "description": "按出场人物自动取角色库多视角图作为生图参考"},
            {"key": "use_scene_ref", "label": "场景参考图", "type": "toggle", "defaultValue": True},
            {"key": "max_ref_images", "label": "参考图上限", "type": "number", "colSpan": "half", "min": 0, "max": 8},
            {"key": "gen_mode", "label": "生图模式", "type": "select", "colSpan": "half", "options": [{"label": "文生图(txt2img)", "value": "txt2img"}, {"label": "图生图(img2img)", "value": "img2img"}], "description": "img2img 时优先使用「组装分镜提示词」产出的有序参考图(场景→道具→角色)，须配图生图接口"},
            {"key": "art_style_prompt", "label": "画风补充提示词", "type": "textarea", "colSpan": "full"},
            {"key": "image_interface", "label": "生图接口", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/enabled", "colSpan": "half", "description": "img2img 模式请选择支持图生图的接口"},
            {"key": "image_model", "label": "文生图模型", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/{image_interface}/models-for-node?mode=txt2img", "dependsOn": "image_interface", "colSpan": "half", "placeholder": "跟随接口默认模型"},
            {"key": "img2img_model", "label": "图生图模型", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/{image_interface}/models-for-node?mode=img2img", "dependsOn": "image_interface", "colSpan": "half", "placeholder": "图生图模型(留空用文生图模型)", "description": "仅 img2img 模式生效"},
            {"key": "image_resolution", "label": "出图分辨率", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/{image_interface}/param-options?model={image_model}", "dependsOn": "image_model", "colSpan": "half", "placeholder": "跟随模型默认"},
            {"key": "negative_prompt", "label": "反向提示词", "type": "textarea", "colSpan": "full", "placeholder": "留空则不使用（如：低质量, 多余手指, 文字水印）", "description": "透传给生图接口的 negative_prompt"},
            {"key": "force", "label": "强制重生成", "type": "switch", "colSpan": "full", "description": "开启后忽略已存在首尾帧，重新生图（默认跳过已完成分镜）"},
            {"key": "retry_failed", "label": "仅重试失败分镜", "type": "switch", "colSpan": "full", "description": "开启后只重跑「生成任务台账」中最近一次生图失败的分镜，已成功的分镜跳过（重试记录会串联原失败任务）"},
        ],
    },
    {
        "id": "agi_shot_video",
        "name": "分镜视频制作",
        "execution_domain": "process",
        "category": "agi_shot",
        "description": "AI 漫剧·分镜视频制作：以首/尾帧 + 画面描述(场景+运镜)做图生视频（可整章批处理），登记为 shot_video 资产",
        "icon": "Film",
        "color": "#db2777",
        "inputs": [
            {"id": "shot_id", "label": "分镜ID(单个)", "type": "any"},
            {"id": "chapter_id", "label": "章节ID(批处理)", "type": "any"},
            {"id": "chapter_ids", "label": "多章节ID列表(可选)", "type": "json"},
            {"id": "first_frame", "label": "首帧", "type": "image"},
            {"id": "last_frame", "label": "尾帧", "type": "image"},
            {"id": "text", "label": "视频提示词(可选)", "type": "text"},
        ],
        "outputs": [
            {"id": "shot_id", "label": "分镜ID", "type": "text"},
            {"id": "video", "label": "分镜视频", "type": "video"},
            {"id": "shot_ids", "label": "分镜ID列表", "type": "json"},
            {"id": "videos", "label": "视频列表", "type": "json"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "chapter_id": "",
            "shot_id": "",
            "video_interface": "",
            "video_model": "",
            "duration": 5,
            "resolution": "720P",
            "aspect_ratio": "",
            "camera_prompt": "",
            "negative_prompt": "",
            "num_videos": 1,
            "force": False,
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入时优先"},
            {"key": "chapter_id", "label": "章节(批处理)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/chapters", "optionLabel": "title", "optionValue": "id", "followPort": "chapter_id", "colSpan": "full", "description": "选择后整章批处理；连线传入时优先"},
            {"key": "shot_id", "label": "分镜(单个)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/shots?chapter_id={chapter_id}", "optionLabel": "label", "optionValue": "id", "colSpan": "full", "description": "先选择创作项目与章节；连线传入时优先"},
            {"key": "video_interface", "label": "生视频接口", "type": "api-select", "apiEndpoint": "/api/videogen-interfaces/enabled", "colSpan": "half"},
            {"key": "video_model", "label": "生视频模型", "type": "api-select", "apiEndpoint": "/api/videogen-interfaces/{video_interface}/models-for-node?mode=i2v", "dependsOn": "video_interface", "colSpan": "half", "placeholder": "跟随接口默认模型"},
            {"key": "camera_prompt", "label": "运镜提示词", "type": "text", "colSpan": "half", "placeholder": "如 缓慢推近，电影感镜头"},
            {"key": "duration", "label": "时长(秒)", "type": "number", "colSpan": "half", "min": 1, "max": 30, "description": "接口不支持的时长会回退到最接近档位"},
            {"key": "resolution", "label": "分辨率", "type": "api-select", "apiEndpoint": "/api/videogen-interfaces/{video_interface}/param-options?model={video_model}", "dependsOn": "video_model", "colSpan": "half", "placeholder": "跟随模型默认(720P)"},
            {"key": "aspect_ratio", "label": "比例", "type": "api-select", "apiEndpoint": "/api/videogen-interfaces/{video_interface}/param-options?model={video_model}", "dependsOn": "video_model", "colSpan": "half", "placeholder": "留空跟随项目立项比例"},
            {"key": "num_videos", "label": "生成数量", "type": "number", "colSpan": "half", "min": 1, "max": 4, "description": "每个分镜生成的候选视频数（部分接口仅支持 1）"},
            {"key": "negative_prompt", "label": "反向提示词", "type": "textarea", "colSpan": "full", "placeholder": "留空则不使用", "description": "透传给生视频接口的 negative_prompt"},
            {"key": "force", "label": "强制重生成", "type": "switch", "colSpan": "full", "description": "开启后忽略已存在视频，重新生成（默认跳过已完成分镜）"},
            {"key": "retry_failed", "label": "仅重试失败分镜", "type": "switch", "colSpan": "full", "description": "开启后只重跑「生成任务台账」中最近一次生视频失败的分镜，已成功的分镜跳过（重试记录会串联原失败任务）"},
        ],
    },
    {
        "id": "agi_shot_dub",
        "name": "分镜配音",
        "execution_domain": "process",
        "category": "agi_shot",
        "description": "AI 漫剧·分镜配音：按分镜对话逐句 TTS（依人物 voice_ref 音色克隆，可整章批处理），拼接配音并同步产出 SRT 字幕",
        "icon": "Mic",
        "color": "#db2777",
        "inputs": [
            {"id": "shot_id", "label": "分镜ID(单个)", "type": "any"},
            {"id": "chapter_id", "label": "章节ID(批处理)", "type": "any"},
            {"id": "chapter_ids", "label": "多章节ID列表(可选)", "type": "json"},
            {"id": "video", "label": "分镜视频(可选)", "type": "video"},
            {"id": "bgm", "label": "背景音乐(可选)", "type": "audio"},
        ],
        "outputs": [
            {"id": "shot_id", "label": "分镜ID", "type": "text"},
            {"id": "audio", "label": "配音片段", "type": "audio"},
            {"id": "voiceover", "label": "配音信息", "type": "json"},
            {"id": "shot_ids", "label": "分镜ID列表", "type": "json"},
            {"id": "audios", "label": "配音列表", "type": "json"},
            {"id": "subtitles", "label": "SRT字幕列表", "type": "json"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "chapter_id": "",
            "shot_id": "",
            "tts_interface": "",
            "tts_mode": "controllable_clone",
            "tts_model": "",
            "tts_voice": "",
            "tts_speed": 1.0,
            "tts_voice_design": "",
            "make_srt": True,
            "force": False,
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入时优先"},
            {"key": "chapter_id", "label": "章节(批处理)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/chapters", "optionLabel": "title", "optionValue": "id", "followPort": "chapter_id", "colSpan": "full", "description": "选择后整章批处理；连线传入时优先"},
            {"key": "shot_id", "label": "分镜(单个)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/shots?chapter_id={chapter_id}", "optionLabel": "label", "optionValue": "id", "colSpan": "full", "description": "先选择创作项目与章节；连线传入时优先"},
            {"key": "tts_interface", "label": "TTS 接口", "type": "api-select", "apiEndpoint": "/api/tts-interfaces/enabled", "colSpan": "half"},
            {"key": "tts_model", "label": "TTS 模型", "type": "api-select", "apiEndpoint": "/api/tts-interfaces/{tts_interface}/models-for-node", "dependsOn": "tts_interface", "colSpan": "half", "placeholder": "跟随接口默认模型"},
            {"key": "tts_mode", "label": "合成模式", "type": "select", "colSpan": "half", "options": [
                {"value": "preset_voice", "label": "预设音色"}, {"value": "voice_design", "label": "音色设计"}, {"value": "controllable_clone", "label": "指令克隆"}]},
            {"key": "tts_voice", "label": "预设音色", "type": "api-select", "apiEndpoint": "/api/tts-interfaces/{tts_interface}/voices", "dependsOn": "tts_mode", "dependsValue": "preset_voice", "colSpan": "half", "placeholder": "选音色（留空用接口默认）"},
            {"key": "tts_speed", "label": "语速", "type": "number", "colSpan": "half", "min": 0.5, "max": 2.0, "step": 0.05, "placeholder": "1.0", "description": "透传给 TTS 接口的 speed（接口不支持时忽略）"},
            {"key": "make_srt", "label": "生成SRT字幕", "type": "toggle", "defaultValue": True},
            {"key": "tts_voice_design", "label": "音色/克隆指令", "type": "textarea", "colSpan": "full", "placeholder": "人物无 voice_ref 时的回退指令文本"},
            {"key": "force", "label": "强制重生成", "type": "switch", "colSpan": "full", "description": "开启后忽略已存在配音，重新合成（默认跳过已完成分镜）"},
        ],
    },
    {
        "id": "agi_shot_export",
        "name": "分镜导出",
        "execution_domain": "process",
        "category": "agi_render",
        "description": "AI 漫剧·分镜导出：分镜视频+配音+BGM/音效混流成片，可烧录 SRT 字幕（可整章批处理），登记 shot_render 资产",
        "icon": "FileVideo",
        "color": "#db2777",
        "inputs": [
            {"id": "shot_id", "label": "分镜ID(单个)", "type": "any"},
            {"id": "chapter_id", "label": "章节ID(批处理)", "type": "any"},
            {"id": "chapter_ids", "label": "多章节ID列表(可选)", "type": "json"},
            {"id": "video", "label": "分镜视频", "type": "video"},
            {"id": "audio", "label": "配音", "type": "audio"},
            {"id": "bgm", "label": "背景音乐", "type": "audio"},
            {"id": "sfx", "label": "音效", "type": "audio"},
            {"id": "subtitle", "label": "SRT字幕(可选)", "type": "any"},
        ],
        "outputs": [
            {"id": "shot_id", "label": "分镜ID", "type": "text"},
            {"id": "render", "label": "分镜成片", "type": "video"},
            {"id": "shot_ids", "label": "分镜ID列表", "type": "json"},
            {"id": "renders", "label": "成片列表", "type": "json"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "chapter_id": "",
            "shot_id": "",
            "bgm_vol": 0.3,
            "dub_vol": 0.9,
            "fade_in": 0.3,
            "fade_out": 0.3,
            "mute_original": False,
            "burn_subtitle": False,
            "force": False,
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入时优先"},
            {"key": "chapter_id", "label": "章节(批处理)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/chapters", "optionLabel": "title", "optionValue": "id", "followPort": "chapter_id", "colSpan": "full", "description": "选择后整章批处理；连线传入时优先"},
            {"key": "shot_id", "label": "分镜(单个)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/shots?chapter_id={chapter_id}", "optionLabel": "label", "optionValue": "id", "colSpan": "full", "description": "先选择创作项目与章节；连线传入时优先"},
            {"key": "burn_subtitle", "label": "烧录字幕", "type": "toggle", "defaultValue": False, "description": "优先取配音资产旁的 SRT，烧录失败自动回退为无字幕成片"},
            {"key": "dub_vol", "label": "配音音量", "type": "slider", "colSpan": "half", "min": 0, "max": 1, "step": 0.05},
            {"key": "bgm_vol", "label": "BGM音量", "type": "slider", "colSpan": "half", "min": 0, "max": 1, "step": 0.05},
            {"key": "fade_in", "label": "淡入(秒)", "type": "number", "colSpan": "half", "min": 0, "max": 5, "step": 0.1},
            {"key": "fade_out", "label": "淡出(秒)", "type": "number", "colSpan": "half", "min": 0, "max": 5, "step": 0.1},
            {"key": "mute_original", "label": "静音原声", "type": "toggle", "defaultValue": False},
            {"key": "force", "label": "强制重生成", "type": "switch", "colSpan": "full", "description": "开启后忽略已存在成片，重新混流导出（默认跳过已完成分镜）"},
        ],
    },
    {
        "id": "agi_chapter_export",
        "name": "章节导出",
        "execution_domain": "process",
        "category": "agi_render",
        "description": "AI 漫剧·章节导出：拼接本章全部分镜成片为一个章节视频，登记 chapter_render 资产",
        "icon": "Layers",
        "color": "#db2777",
        "inputs": [
            {"id": "chapter_id", "label": "章节ID", "type": "any"},
            {"id": "chapter_ids", "label": "多章节ID列表(多章批量)", "type": "json"},
            {"id": "renders", "label": "分镜成片列表(可选)", "type": "any"},
            {"id": "video", "label": "单视频(可选)", "type": "video"},
        ],
        "outputs": [
            {"id": "chapter_id", "label": "章节ID", "type": "text"},
            {"id": "render", "label": "章节成片", "type": "video"},
            {"id": "chapter_ids", "label": "章节ID列表(批处理)", "type": "json"},
            {"id": "renders", "label": "章节成片列表(批处理)", "type": "json"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "chapter_id": "",
            "reuse_stitch_id": "",
            "resolution": "original",
            "aspect_ratio": "original",
            "transition": "none",
            "transition_duration": 0.4,
            "make_cover": False,
            "cover_duration": 3,
            "cover_prompt": "",
            "image_interface": "",
            "image_model": "",
            "image_resolution": "",
            "negative_prompt": "",
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "项目骨架数据源；连线传入时优先"},
            {"key": "chapter_id", "label": "章节", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/chapters", "optionLabel": "title", "optionValue": "id", "followPort": "chapter_id", "colSpan": "full", "description": "要导出的章节；连线传入 chapter_id 时优先"},
            {"key": "resolution", "label": "输出分辨率", "type": "select", "colSpan": "half", "options": [
                {"value": "original", "label": "原始分辨率"}, {"value": "480P", "label": "480P"}, {"value": "720P", "label": "720P"}, {"value": "1080P", "label": "1080P"}], "description": "将全部分镜成片统一缩放/补边到该分辨率"},
            {"key": "aspect_ratio", "label": "输出比例", "type": "select", "colSpan": "half", "options": [
                {"value": "original", "label": "原始比例"}, {"value": "16:9", "label": "16:9"}, {"value": "9:16", "label": "9:16"}, {"value": "1:1", "label": "1:1"}]},
            {"key": "transition", "label": "转场衔接", "type": "select", "colSpan": "half", "options": [
                {"value": "none", "label": "无（直接拼接）"}, {"value": "fade", "label": "交叉淡化"}, {"value": "fadeblack", "label": "淡出黑场"}, {"value": "smoothleft", "label": "左滑"}, {"value": "smoothright", "label": "右滑"}, {"value": "wipeup", "label": "上擦"}, {"value": "wipedown", "label": "下擦"}], "description": "分镜之间叠加转场效果（自动统一分辨率/帧率）"},
            {"key": "transition_duration", "label": "转场时长(秒)", "type": "number", "colSpan": "half", "min": 0.1, "max": 3, "step": 0.1},
            {"key": "make_cover", "label": "生成章节封面片头", "type": "switch", "colSpan": "half", "description": "用章节标题/简介生成封面图，作为章节成片开头的静态片头并登记 chapter_cover 资产"},
            {"key": "cover_duration", "label": "封面时长(秒)", "type": "number", "colSpan": "half", "min": 1, "max": 10, "step": 0.5},
            {"key": "reuse_stitch_id", "label": "重拼(拼接历史ID)", "type": "text", "colSpan": "full", "placeholder": "填入历史拼接记录 ID，可复用其分镜成片源", "description": "可重拼：沿用上次拼接的分镜成片源，仅更换转场/封面/分辨率重新拼接，不重新生成分镜视频"},
            {"key": "cover_prompt", "label": "封面提示词(可选)", "type": "textarea", "colSpan": "full"},
            {"key": "image_interface", "label": "生图接口", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/enabled", "colSpan": "half"},
            {"key": "image_model", "label": "封面模型", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/{image_interface}/models-for-node?mode=txt2img", "dependsOn": "image_interface", "colSpan": "half", "placeholder": "跟随接口默认模型"},
            {"key": "image_resolution", "label": "封面分辨率", "type": "api-select", "apiEndpoint": "/api/imagegen-interfaces/{image_interface}/param-options?model={image_model}", "dependsOn": "image_model", "colSpan": "half", "placeholder": "跟随模型默认"},
            {"key": "negative_prompt", "label": "反向提示词", "type": "textarea", "colSpan": "full", "placeholder": "留空则不使用", "description": "透传给封面生图接口的 negative_prompt"},
        ],
    },
    {
        "id": "pi_agent",
        "name": "小pi通用智能体",
        "execution_domain": "process",
        "category": "agent",
        "description": "将小 Pi 以工作流节点方式嵌入工作流：注入任务背景与输入输出契约，发起一次 Pi 会话并执行任务，产物保存到任务 cache 目录",
        "icon": "Bot",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "input_1", "label": "输入1", "type": "any", "required": False},
            {"id": "input_2", "label": "输入2", "type": "any", "required": False},
        ],
        "outputs": [
            {"id": "output_1", "label": "输出1", "type": "any"},
            {"id": "output_2", "label": "输出2", "type": "any"},
        ],
        "defaultConfig": {
            "inputCount": 2,
            "outputCount": 2,
            "skills": [],
            "mcps": [],
            "docs_path": "",
            "external_doc": "",
            "persona": "你是本项目的工作流节点执行者，执行我要求的任务，并按照需要输出产物。本次执行的任务是：",
            "output_items": [
                {"port": "输出1", "type": "text", "desc": ""},
                {"port": "输出2", "type": "json", "desc": ""},
            ],
        },
        "configFields": [
            {"key": "inputCount", "label": "输入端口数", "type": "number", "min": 1, "max": 8},
            {"key": "outputCount", "label": "输出端口数", "type": "number", "min": 1, "max": 8},
            {"key": "skills", "label": "可调用 Skill", "type": "multiselect", "placeholder": "自行选择（不指定时由智能体自行决定）", "options": [], "description": "本次任务推荐使用的 Skill，多选；留空表示由智能体自行选择"},
            {"key": "mcps", "label": "可调用 MCP", "type": "multiselect", "placeholder": "自行选择（不指定时由智能体自行决定）", "options": [], "description": "本次任务推荐使用的 MCP，多选；留空表示由智能体自行选择"},
            {"key": "docs_path", "label": "参考技能文档", "type": "api-select", "apiEndpoint": "/api/pi/settings/docs", "optionLabel": "name", "optionValue": "path", "placeholder": "不选择", "description": "单选一份能力文档作为本任务参考；留空表示不选择"},
            {"key": "external_doc", "label": "外部参考文档", "type": "file", "fileFilter": ["md"], "placeholder": "选择外部 .md 文档", "description": "可引入外部 Markdown 文档作为本任务参考"},
            {"key": "persona", "label": "人设设定", "type": "textarea", "placeholder": "你是本项目的工作流节点执行者，执行我要求的任务，并按照需要输出产物。本次执行的任务是：", "description": "节点内人设会拼接到小 Pi 全局默认人设之后"},
        ],
    },
    {
        "id": "lcwr_watermark_removal",
        "name": "LCWR 去水印",
        "execution_domain": "process",
        "category": "video",
        "description": "调用 LCWR 本地 API 去除视频/图片中的水印与字幕。需先安装并启动 LCWR 软件（下载地址：https://qinmuzhifang.feishu.cn/wiki/IkBVwfe72iEVLTkhVQ0cW0mvnBc），右键「启动LCWR-API.bat」以管理员身份运行本地 API（默认 http://localhost:1120）",
        "icon": "Eraser",
        "color": "#0ea5e9",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": False},
            {"id": "image", "label": "图片", "type": "image", "required": False},
        ],
        "outputs": [
            {"id": "video", "label": "视频", "type": "video"},
            {"id": "image", "label": "图片", "type": "image"},
        ],
        "defaultConfig": {
            "model": "bernini",
            "lcwr_base_url": "http://localhost:1120",
            "regions": [],
            "skip_head_sec": 0.0,
            "skip_tail_sec": 0.0,
            "skip_tail_mode": "from_end",
            "aspect_ratio": "16:9",
            "duration_sec": 10,
            "fps": 25,
        },
        "configFields": [
            {"key": "model", "label": "执行模型", "type": "select", "options": [
                {"value": "lama", "label": "LaMa（快速）"},
                {"value": "sttn", "label": "STTN（时空张量）"},
                {"value": "propainter", "label": "ProPainter（高质量）"},
                {"value": "diffueraser", "label": "DiffuEraser（扩散模型）"},
                {"value": "bernini", "label": "Bernini（旗舰）"},
                {"value": "online", "label": "LCWR在线模型"},
            ]},
            {"key": "lcwr_base_url", "label": "LCWR API 地址", "type": "text", "placeholder": "http://localhost:1120"},
            {"key": "aspect_ratio", "label": "视频比例（未接入视频时）", "type": "select", "options": [
                {"value": "16:9", "label": "16:9 横屏"},
                {"value": "9:16", "label": "9:16 竖屏"},
                {"value": "4:3", "label": "4:3"},
                {"value": "3:4", "label": "3:4"},
                {"value": "1:1", "label": "1:1 方形"},
                {"value": "21:9", "label": "21:9 宽屏"},
            ]},
            {"key": "skip_head_sec", "label": "片头跳过(秒)", "type": "number", "min": 0, "step": 0.5, "colSpan": "half"},
            {"key": "skip_tail_sec", "label": "片尾跳过(秒)", "type": "number", "min": 0, "step": 0.5, "colSpan": "half"},
            {"key": "skip_tail_mode", "label": "片尾计算方式", "type": "select", "options": [
                {"value": "from_end", "label": "从末尾向前数"},
                {"value": "from_head", "label": "从开头向后数"},
            ]},
        ],
    },
    {
        "id": "audio_denoise",
        "name": "声音降噪",
        "execution_domain": "thread",
        "category": "audio",
        "description": "对音频进行智能降噪处理，去除环境噪声、风噪、电流声等干扰",
        "icon": "AudioLines",
        "color": "#0ea5e9",
        "inputs": [
            {"id": "audio", "label": "音频", "type": "audio", "required": True},
        ],
        "outputs": [
            {"id": "audio", "label": "降噪音频", "type": "audio"},
        ],
        "defaultConfig": {
            "method": "ffmpeg",
            "noise_reduction_level": 0.5,
            "highpass_freq": 100,
            "lowpass_freq": 0,
            "output_format": "wav",
            "custom_command": "",
        },
        "configFields": [
            {
                "key": "method",
                "label": "降噪算法",
                "type": "select",
                "colSpan": "full",
                "options": [
                    {"value": "ffmpeg", "label": "FFmpeg 内置滤镜（快速，无需额外依赖）"},
                    {"value": "custom", "label": "自定义 ffmpeg 命令"},
                ],
            },
            {
                "key": "noise_reduction_level",
                "label": "降噪强度",
                "type": "slider",
                "colSpan": "full",
                "min": 0,
                "max": 1,
                "step": 0.05,
                "description": "0 = 不降噪，1 = 最大强度。值过高可能损伤人声清晰度",
            },
            {
                "key": "highpass_freq",
                "label": "高通滤波（去除低频噪声）",
                "type": "select",
                "colSpan": "half",
                "options": [
                    {"value": 0, "label": "不启用"},
                    {"value": 80, "label": "80 Hz（轻度）"},
                    {"value": 100, "label": "100 Hz ★推荐"},
                    {"value": 120, "label": "120 Hz（中度）"},
                    {"value": 150, "label": "150 Hz（激进）"},
                ],
            },
            {
                "key": "lowpass_freq",
                "label": "低通滤波（去除高频噪声）",
                "type": "select",
                "colSpan": "half",
                "options": [
                    {"value": 0, "label": "不启用"},
                    {"value": 7000, "label": "7000 Hz（轻度）"},
                    {"value": 8000, "label": "8000 Hz ★推荐"},
                    {"value": 10000, "label": "10000 Hz（中度）"},
                    {"value": 12000, "label": "12000 Hz（轻度保留）"},
                ],
            },
            {
                "key": "output_format",
                "label": "输出格式",
                "type": "select",
                "colSpan": "half",
                "options": [
                    {"value": "auto", "label": "跟随源格式"},
                    {"value": "wav", "label": "WAV（无损）★推荐"},
                    {"value": "mp3", "label": "MP3"},
                    {"value": "flac", "label": "FLAC（无损压缩）"},
                ],
            },
            {
                "key": "custom_command",
                "label": "自定义 ffmpeg 滤镜命令",
                "type": "textarea",
                "colSpan": "full",
                "placeholder": "afftdn=nf=-25:nr=15:nt=w",
                "description": "仅在「自定义 ffmpeg 命令」模式下生效。填写 ffmpeg -af 滤镜参数，如 afftdn=nf=-25:nr=15:nt=w 。系统会自动在前面拼接 -i {input}、在后面拼接 {output}",
                "dependsOn": "method",
                "dependsValue": "custom",
            },
        ],
    },
    {
        "id": "media_to_url",
        "name": "媒体转链接",
        "execution_domain": "thread",
        "category": "network_request",
        "description": "上传本地视频/图片到腾讯云 VOD，返回 URL 及完整媒体详情（尺寸/时长/码率等）保存为 JSON",
        "icon": "CloudUpload",
        "color": "#06b6d4",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video"},
            {"id": "image", "label": "图片", "type": "image"},
        ],
        "outputs": [
            {"id": "json", "label": "媒体详情", "type": "json"},
        ],
        "defaultConfig": {
            "timeout_sec": 300,
            "file_path": "",
            "normalize_video": False,
            "segment_duration": "30",
        },
        "configFields": [
            {"key": "file_path", "label": "手动指定文件路径", "type": "file", "placeholder": "可留空，优先使用节点连线输入", "colSpan": "full", "fileFilter": ["mp4", "mkv", "webm", "avi", "mov", "wmv", "flv", "m4v", "mpg", "mpeg", "png", "jpg", "jpeg", "webp", "bmp", "gif", "tiff", "tif"]},
            {"key": "normalize_video", "label": "标准化视频", "type": "checkbox", "description": "勾选后上传前将视频用 h264 重编码为 mp4，分辨率超过 1080p 时自动等比缩小至 1080p", "colSpan": "full"},
            {"key": "segment_duration", "label": "时长分段(分钟)", "type": "select", "colSpan": "half", "options": [
                {"value": "5", "label": "5 分钟"},
                {"value": "10", "label": "10 分钟"},
                {"value": "15", "label": "15 分钟"},
                {"value": "20", "label": "20 分钟"},
                {"value": "25", "label": "25 分钟"},
                {"value": "30", "label": "30 分钟"},
            ], "description": "视频超过该时长时按此分段上传（每段独立转链接，结果以列表写入），默认 30 分钟"},
            {"key": "timeout_sec", "label": "超时时间(秒)", "type": "number", "colSpan": "half", "placeholder": "默认 300", "description": "上传+等待URL的整体超时，超时后中断"},
        ],
    },
    {
        "id": "online_watermark_removal",
        "name": "在线去水印去字幕",
        "execution_domain": "thread",
        "category": "video",
        "description": "晴沐智坊提供的在线高质量去除视频中的水印服务，使用前确保注册登录晴沐智坊账号，使用将消耗软件的通用积分，确保积分足够视频消耗，1.3分钱每秒。详情访问晴沐hub：https://www.licorxj.online/capability-hub",
        "icon": "Eraser",
        "color": "#8b5cf6",
        "inputs": [
            {"id": "url_json", "label": "媒体详情JSON", "type": "json"},
        ],
        "outputs": [
            {"id": "video", "label": "去水印视频", "type": "video"},
            {"id": "json", "label": "任务记录", "type": "json"},
        ],
        "defaultConfig": {
            "watermark_regions": [],
            "resume_request_id": "",
            "wm_mode": "normal",
        },
        "configFields": [
            {"key": "wm_mode", "label": "去水印模式", "type": "select", "colSpan": "full", "options": [
                {"value": "normal", "label": "普通模式（normal）"},
                {"value": "protect", "label": "保护模式（protect）"},
            ], "description": "普通模式：标准去水印；保护模式：更保守地处理，降低误伤风险"},
        ],
    },
    {
        "id": "qm_virtual_mailbox",
        "name": "QM虚拟邮箱",
        "execution_domain": "thread",
        "category": "network_request",
        "description": "通过晴沐智坊虚拟邮箱，向已验证的转发目标发送验证码邮件。费用2分钱/条（云端处理）。使用前请确保已在网页端设置并验证转发目标。详情访问：https://www.licorxj.online/mail-forwarding",
        "icon": "Mail",
        "color": "#10b981",
        "inputs": [
            {"id": "text", "label": "文本内容", "type": "text"},
        ],
        "outputs": [
            {"id": "json", "label": "发送结果", "type": "json"},
        ],
        "defaultConfig": {
            "mailbox_id": "",
            "target_email": "",
            "prefix_content": "",
        },
        "configFields": [],
    },
    {
        "id": "video_transcode",
        "name": "视频转码",
        "execution_domain": "thread",
        "category": "video",
        "description": "使用 ffmpeg 对视频进行转码，支持容器格式、视频/音频编码、码率、分辨率、帧率、编码速度档与像素格式等参数配置",
        "icon": "Clapperboard",
        "color": "#ec4899",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": True},
        ],
        "outputs": [
            {"id": "video", "label": "转码视频", "type": "video"},
        ],
        "defaultConfig": {
            "output_format": "mp4",
            "video_mode": "reencode",
            "video_codec": "libx264",
            "crf": 23,
            "video_bitrate": "",
            "resolution": "",
            "fps": "",
            "preset": "medium",
            "pix_fmt": "yuv420p",
            "audio_mode": "reencode",
            "audio_codec": "aac",
            "audio_bitrate": "192k",
        },
        "configFields": [
            {
                "key": "output_format",
                "label": "输出格式",
                "type": "select",
                "colSpan": "full",
                "options": [
                    {"value": "mp4", "label": "MP4"},
                    {"value": "mkv", "label": "MKV"},
                    {"value": "webm", "label": "WebM"},
                    {"value": "mov", "label": "MOV"},
                    {"value": "avi", "label": "AVI"},
                    {"value": "flv", "label": "FLV"},
                ],
                "description": "封装容器格式，决定输出文件扩展名",
            },
            {
                "key": "video_mode",
                "label": "视频处理模式",
                "type": "chips",
                "singleSelect": True,
                "chipColor": "#ec4899",
                "options": [
                    {"value": "reencode", "label": "重新编码"},
                    {"value": "copy", "label": "流复制(不重编码)"},
                    {"value": "none", "label": "去除视频"},
                ],
                "description": "流复制：直接拷贝原始视频流，速度极快但无法修改画质/分辨率",
            },
            {
                "key": "video_codec",
                "label": "视频编码器",
                "type": "select",
                "colSpan": "half",
                "dependsOn": "video_mode",
                "dependsValue": "reencode",
                "options": [
                    {"value": "libx264", "label": "H.264 (libx264)"},
                    {"value": "libx265", "label": "H.265 (libx265)"},
                    {"value": "vp9", "label": "VP9 (libvpx-vp9)"},
                    {"value": "mpeg4", "label": "MPEG-4"},
                ],
                "description": "选择视频编码格式",
            },
            {
                "key": "crf",
                "label": "CRF 质量(0-51)",
                "type": "number",
                "colSpan": "half",
                "dependsOn": "video_mode",
                "dependsValue": "reencode",
                "description": "恒定质量因子，越小画质越好、体积越大。H.264/H.265 常用 18-28，VP9 常用 30-40",
            },
            {
                "key": "video_bitrate",
                "label": "视频码率",
                "type": "text",
                "colSpan": "half",
                "dependsOn": "video_mode",
                "dependsValue": "reencode",
                "placeholder": "如 2M / 4000k，留空则由 CRF 控制",
                "description": "指定固定码率；与 CRF 同时设置时以码率优先",
            },
            {
                "key": "resolution",
                "label": "分辨率(宽:高)",
                "type": "text",
                "colSpan": "half",
                "dependsOn": "video_mode",
                "dependsValue": "reencode",
                "placeholder": "如 1280:720，留空保持原分辨率",
                "description": "使用 scale 滤镜缩放，如 -2:720 表示按高度自适应宽度",
            },
            {
                "key": "fps",
                "label": "帧率",
                "type": "text",
                "colSpan": "half",
                "dependsOn": "video_mode",
                "dependsValue": "reencode",
                "placeholder": "如 30，留空保持原帧率",
            },
            {
                "key": "preset",
                "label": "编码速度档",
                "type": "select",
                "colSpan": "half",
                "dependsOn": "video_mode",
                "dependsValue": "reencode",
                "options": [
                    {"value": "ultrafast", "label": "ultrafast"},
                    {"value": "superfast", "label": "superfast"},
                    {"value": "veryfast", "label": "veryfast"},
                    {"value": "faster", "label": "faster"},
                    {"value": "fast", "label": "fast"},
                    {"value": "medium", "label": "medium"},
                    {"value": "slow", "label": "slow"},
                    {"value": "slower", "label": "slower"},
                    {"value": "veryslow", "label": "veryslow"},
                ],
                "description": "越快压缩率越低（文件越大），越慢画质/体积越优",
            },
            {
                "key": "pix_fmt",
                "label": "像素格式",
                "type": "select",
                "colSpan": "half",
                "dependsOn": "video_mode",
                "dependsValue": "reencode",
                "options": [
                    {"value": "yuv420p", "label": "yuv420p (兼容最广)"},
                    {"value": "yuv422p", "label": "yuv422p"},
                    {"value": "yuv444p", "label": "yuv444p"},
                    {"value": "nv12", "label": "nv12"},
                    {"value": "rgb24", "label": "rgb24"},
                ],
            },
            {
                "key": "audio_mode",
                "label": "音频处理模式",
                "type": "chips",
                "singleSelect": True,
                "chipColor": "#ec4899",
                "options": [
                    {"value": "reencode", "label": "重新编码"},
                    {"value": "copy", "label": "流复制(不重编码)"},
                    {"value": "none", "label": "去除音频"},
                ],
                "description": "流复制：直接拷贝原始音频流",
            },
            {
                "key": "audio_codec",
                "label": "音频编码器",
                "type": "select",
                "colSpan": "half",
                "dependsOn": "audio_mode",
                "dependsValue": "reencode",
                "options": [
                    {"value": "aac", "label": "AAC"},
                    {"value": "mp3", "label": "MP3 (libmp3lame)"},
                    {"value": "opus", "label": "Opus (libopus)"},
                ],
            },
            {
                "key": "audio_bitrate",
                "label": "音频码率",
                "type": "text",
                "colSpan": "half",
                "dependsOn": "audio_mode",
                "dependsValue": "reencode",
                "placeholder": "如 192k / 256k",
            },
        ],
    },
    {
        "id": "audio_cut_by_subtitle",
        "name": "按照字幕切割音频",
        "execution_domain": "thread",
        "category": "audio",
        "description": "按 srt 字幕或句子 json 的时间轴切割音频，输出片段清单 json 与各音频片段",
        "icon": "Scissors",
        "color": "#22c55e",
        "inputs": [
            {"id": "audio", "label": "音频", "type": "audio", "required": True},
            {"id": "srt", "label": "SRT字幕", "type": "subtitle"},
            {"id": "json", "label": "句子JSON", "type": "json"},
        ],
        "outputs": [
            {"id": "json", "label": "切割信息", "type": "json"},
            {"id": "audio_segments", "label": "音频片段清单", "type": "audio_manifest"},
        ],
        "defaultConfig": {
            "output_format": "wav",
            "expand": 0.05,
        },
        "configFields": [
            {
                "key": "output_format",
                "label": "输出格式",
                "type": "select",
                "options": [
                    {"value": "wav", "label": "WAV (PCM)"},
                    {"value": "mp3", "label": "MP3"},
                    {"value": "flac", "label": "FLAC"},
                    {"value": "m4a", "label": "M4A (AAC)"},
                    {"value": "ogg", "label": "OGG (Vorbis)"},
                ],
                "description": "切割后音频片段的封装与编码格式",
            },
            {
                "key": "expand",
                "label": "切割点外扩(秒)",
                "type": "number",
                "description": "每段在首尾各外扩的秒数，避免裁掉首尾音节",
            },
        ],
    },
    {
        "id": "video_cut_by_subtitle",
        "name": "按字幕切割视频",
        "execution_domain": "thread",
        "category": "video",
        "description": "按 srt 字幕或句子 json 的时间轴切割视频，输出片段清单 json 与各视频片段",
        "icon": "Scissors",
        "color": "#0ea5e9",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": True},
            {"id": "srt", "label": "SRT字幕", "type": "subtitle"},
            {"id": "json", "label": "句子JSON", "type": "json"},
        ],
        "outputs": [
            {"id": "json", "label": "切割信息", "type": "json"},
            {"id": "video_segments", "label": "视频片段清单", "type": "json"},
        ],
        "defaultConfig": {
            "output_format": "mp4",
            "expand": 0.05,
        },
        "configFields": [
            {
                "key": "output_format",
                "label": "输出格式",
                "type": "select",
                "options": [
                    {"value": "mp4", "label": "MP4 (H.264/AAC)"},
                    {"value": "mkv", "label": "MKV (H.264/AAC)"},
                    {"value": "mov", "label": "MOV (H.264/AAC)"},
                    {"value": "webm", "label": "WebM (VP9/Opus)"},
                ],
                "description": "切割后视频片段的封装与编码格式",
            },
            {
                "key": "expand",
                "label": "切割点外扩(秒)",
                "type": "number",
                "description": "每段在首尾各外扩的秒数，避免裁掉首尾画面",
            },
        ],
    },
    {
        "id": "output_merge_list",
        "name": "输出合并为列表",
        "execution_domain": "thread",
        "category": "utility",
        "description": "将多个上游节点的输出（文本或路径）合并为列表格式 JSON，内存传递、不落盘；输入端口数量可在卡片上动态加减",
        "icon": "ListOrdered",
        "color": "#64748b",
        "dynamicPorts": True,
        "inputs": [],
        "outputs": [
            {"id": "json", "label": "列表JSON", "type": "json"},
        ],
        "defaultConfig": {
            "inputCount": 2,
        },
        "configFields": [
            {
                "key": "inputCount",
                "label": "输入端口数",
                "type": "number",
                "min": 1,
                "max": 8,
                "description": "通过节点卡片上的 + / - 控制（1~8）",
            },
        ],
    },
    {
        "id": "loop",
        "name": "循环",
        "execution_domain": "thread",
        "category": "flow_control",
        "description": "接收一个列表作为迭代对象，逐条取出驱动循环体内的子流程执行；每次迭代的产物按序号记录在 manifest 清单中（选中若干已连线节点后创建循环体）",
        "icon": "Repeat",
        "color": "#6366f1",
        "inputs": [
            {"id": "items", "label": "迭代对象", "type": "json", "required": False},
        ],
        "outputs": [
            {"id": "results", "label": "产物清单", "type": "json"},
            {"id": "count", "label": "迭代总数", "type": "json"},
        ],
        "defaultConfig": {
            "itemsSource": "upstream",
            "inlineItems": "",
            "globPattern": "",
            "maxIterations": 0,
            "iterationConcurrency": 1,
            "onItemError": "stop",
            "itemAlias": "item",
            "indexAlias": "index",
        },
        "configFields": [
            {"key": "itemsSource", "label": "迭代对象来源", "type": "select", "options": [
                {"value": "upstream", "label": "上游连线输入"},
                {"value": "inline_json", "label": "内联 JSON 数组"},
                {"value": "directory_glob", "label": "目录文件匹配"},
            ], "description": "上游连线取 items 端口传入的列表；内联 JSON 直接填写数组；目录匹配按通配符扫描文件"},
            {"key": "inlineItems", "label": "内联 JSON 数组", "type": "textarea", "colSpan": "full",
             "dependsOn": "itemsSource", "dependsValue": "inline_json",
             "placeholder": '["a.mp4", "b.mp4"] 或 [{"path": "a.mp4"}, {"path": "b.mp4"}]'},
            {"key": "globPattern", "label": "目录通配符", "type": "text", "colSpan": "full",
             "dependsOn": "itemsSource", "dependsValue": "directory_glob",
             "placeholder": "D:/videos/*.mp4"},
            {"key": "maxIterations", "label": "最大迭代数", "type": "number", "min": 0, "max": 500, "step": 1, "colSpan": "half",
             "description": "0 表示不限制（受全局上限 LOOP_MAX_ITEMS=500 约束）"},
            {"key": "iterationConcurrency", "label": "并发数", "type": "slider", "min": 1, "max": 16, "step": 1, "colSpan": "half",
             "description": "同时处理的迭代条目数；串行填 1"},
            {"key": "onItemError", "label": "单项失败策略", "type": "select", "colSpan": "half", "options": [
                {"value": "stop", "label": "立即停止"},
                {"value": "skip", "label": "跳过并继续"},
                {"value": "collect_error", "label": "记录错误后继续"},
            ]},
            {"key": "itemAlias", "label": "条目变量名", "type": "text", "colSpan": "half",
             "placeholder": "item", "description": "循环体节点配置中以 {item} 引用当前条目"},
            {"key": "indexAlias", "label": "序号变量名", "type": "text", "colSpan": "half",
             "placeholder": "index", "description": "循环体节点配置中以 {index} / {index:03d} 引用当前序号"},
        ],
    },
    # ===== AI 漫剧·数据链：项目数据读写（让外部节点可介入漫剧生产链）=====
    {
        "id": "agi_query",
        "name": "项目数据查询",
        "execution_domain": "thread",
        "category": "agi_data",
        "description": "AI 漫剧·项目数据查询(只读)：按目标读取项目/章节/分镜/人物/场景/道具/素材，输出 JSON 与文本。用于把项目内的提示词、台词、设定取出来交给外部节点(LLM/生图/生视频/配音)加工，不修改任何数据",
        "icon": "Search",
        "color": "#0891b2",
        "inputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "chapter_id", "label": "章节ID(可选)", "type": "any"},
            {"id": "ids", "label": "记录ID(可选)", "type": "json"},
        ],
        "outputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "target", "label": "数据目标", "type": "text"},
            {"id": "count", "label": "记录数", "type": "number"},
            {"id": "ids", "label": "记录ID列表", "type": "json"},
            {"id": "items", "label": "数据(JSON)", "type": "json"},
            {"id": "text", "label": "数据(文本)", "type": "text"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "chapter_id": "",
            "target": "shots",
            "fields": "",
            "asset_kind": "",
            "status": "",
            "limit": 0,
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "数据来源项目；连线传入 creation_id 时优先"},
            {"key": "chapter_id", "label": "章节(可选)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/chapters", "optionLabel": "title", "optionValue": "id", "followPort": "chapter_id", "colSpan": "full", "description": "选择后只读该章；不选则跨整项目读取（分镜列表目标）"},
            {"key": "target", "label": "数据目标", "type": "select", "colSpan": "half", "options": [
                {"value": "creation", "label": "项目主数据"},
                {"value": "chapters", "label": "章节列表"},
                {"value": "chapter", "label": "单个章节(含分镜)"},
                {"value": "shots", "label": "分镜列表"},
                {"value": "shot", "label": "单个/多个分镜"},
                {"value": "characters", "label": "人物资产"},
                {"value": "scenes", "label": "场景资产"},
                {"value": "props", "label": "道具资产"},
                {"value": "assets", "label": "素材列表"},
            ], "description": "单个章节/分镜目标需连接或填写记录ID"},
            {"key": "fields", "label": "保留字段", "type": "text", "colSpan": "half", "placeholder": "如 id,index,dialogue,video_prompt", "description": "逗号分隔；留空返回全部字段"},
            {"key": "asset_kind", "label": "素材类型", "type": "text", "colSpan": "half", "placeholder": "如 shot_video / voiceover", "description": "仅「素材列表」目标生效；留空返回全部素材"},
            {"key": "status", "label": "状态过滤", "type": "text", "colSpan": "half", "placeholder": "如 pending / done", "description": "按记录 status 字段精确过滤；留空不过滤"},
            {"key": "limit", "label": "条数上限", "type": "number", "colSpan": "half", "min": 0, "max": 500, "description": "0 表示不限制"},
        ],
    },
    {
        "id": "agi_write",
        "name": "项目数据写入",
        "execution_domain": "thread",
        "category": "agi_data",
        "description": "AI 漫剧·项目数据写入(只写)：把外部处理结果回写到项目指定数据点。同一份补丁可批量应用到多个记录ID，也可用带 id 的数组逐条写回；字段需在该类记录的白名单内",
        "icon": "PencilLine",
        "color": "#0891b2",
        "inputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "ids", "label": "记录ID列表", "type": "json"},
            {"id": "data", "label": "写入数据(JSON)", "type": "json"},
        ],
        "outputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "target", "label": "数据目标", "type": "text"},
            {"id": "count", "label": "写入条数", "type": "number"},
            {"id": "ids", "label": "记录ID列表", "type": "json"},
            {"id": "updated", "label": "写入结果", "type": "json"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "target": "shot",
            "ids": "",
            "data": "",
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "目标项目；连线传入 creation_id 时优先"},
            {"key": "target", "label": "数据目标", "type": "select", "colSpan": "half", "options": [
                {"value": "creation", "label": "项目主数据"},
                {"value": "chapter", "label": "章节"},
                {"value": "shot", "label": "分镜"},
                {"value": "character", "label": "人物"},
                {"value": "scene", "label": "场景"},
                {"value": "prop", "label": "道具"},
                {"value": "asset", "label": "素材"},
            ], "description": "写入不存在的字段会直接报错，便于及早发现拼写问题"},
            {"key": "ids", "label": "记录ID(可留空)", "type": "text", "colSpan": "full", "placeholder": "逗号分隔多个ID", "description": "批量写同一份补丁时填写；已连接 ids 端口时以端口为准"},
            {"key": "data", "label": "写入数据", "type": "textarea", "colSpan": "full", "placeholder": "{\"video_prompt\": \"...\"} 或 [{\"id\": \"shot_x\", \"video_prompt\": \"...\"}]", "description": "JSON 对象=同一补丁批量写入 ids；JSON 数组=按每项 id 逐条写入；已连接 data 端口时以端口为准"},
        ],
    },
    {
        "id": "agi_asset_register",
        "name": "素材登记入库",
        "execution_domain": "thread",
        "category": "agi_data",
        "description": "AI 漫剧·素材登记入库(写素材)：把外部生图/生视频/配音等产物登记为项目资产，并按分镜/章节归属入库，供分镜导出与章节导出节点按分镜消费",
        "icon": "PackagePlus",
        "color": "#0891b2",
        "inputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "files", "label": "素材文件", "type": "any"},
            {"id": "shot_id", "label": "分镜ID(可选)", "type": "text"},
            {"id": "chapter_id", "label": "章节ID(可选)", "type": "any"},
        ],
        "outputs": [
            {"id": "creation_id", "label": "创作项目ID", "type": "text"},
            {"id": "count", "label": "登记数量", "type": "number"},
            {"id": "asset_ids", "label": "素材ID列表", "type": "json"},
            {"id": "assets", "label": "素材记录", "type": "json"},
            {"id": "paths", "label": "素材路径", "type": "json"},
        ],
        "defaultConfig": {
            "creation_id": "",
            "shot_id": "",
            "chapter_id": "",
            "asset_kind": "auto",
            "name": "",
            "ref_id": "",
            "duration_seconds": "",
            "description": "",
        },
        "configFields": [
            {"key": "creation_id", "label": "创作项目", "type": "api-select", "apiEndpoint": "/api/creation/list", "optionLabel": "name", "optionValue": "id", "followPort": "creation_id", "colSpan": "full", "description": "素材归属项目；连线传入 creation_id 时优先"},
            {"key": "chapter_id", "label": "章节(可选)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/chapters", "optionLabel": "title", "optionValue": "id", "followPort": "chapter_id", "colSpan": "full", "description": "素材归属章节；连线传入 chapter_id 时优先"},
            {"key": "shot_id", "label": "分镜(可选)", "type": "api-select", "apiEndpoint": "/api/creation/{creation_id}/shots?chapter_id={chapter_id}", "optionLabel": "label", "optionValue": "id", "colSpan": "full", "description": "素材归属分镜，导出时按分镜消费；连线传入 shot_id 时优先"},
            {"key": "asset_kind", "label": "素材类型", "type": "select", "colSpan": "half", "options": [
                {"value": "auto", "label": "自动(按扩展名)"},
                {"value": "shot_video", "label": "分镜视频"},
                {"value": "shot_render", "label": "分镜图"},
                {"value": "chapter_render", "label": "章节成片"},
                {"value": "chapter_cover", "label": "章节封面"},
                {"value": "character", "label": "人物图"},
                {"value": "scene_image", "label": "场景图"},
                {"value": "prop_image", "label": "道具图"},
                {"value": "voiceover", "label": "配音"},
                {"value": "bgm", "label": "背景音乐"},
                {"value": "sfx", "label": "音效"},
            ], "description": "自动：视频→shot_video，音频→voiceover，图片→shot_render"},
            {"key": "name", "label": "素材名称", "type": "text", "colSpan": "half", "placeholder": "留空用文件名；多文件时自动加序号"},
            {"key": "ref_id", "label": "关联ID", "type": "text", "colSpan": "half", "description": "可选，关联人物/场景/道具等记录ID"},
            {"key": "duration_seconds", "label": "时长(秒)", "type": "number", "colSpan": "half", "description": "音频/视频时长，可留空"},
            {"key": "description", "label": "备注", "type": "textarea", "colSpan": "full"},
        ],
    },
]


# ===== Seedream 生图能力节点（每种能力一个节点，置于「AI生成类节点」分组）=====
def _seedream_common_fields(extra=None):
    """Seedream 节点通用面板配置项。"""
    fields = [
        {"key": "model", "label": "模型", "type": "api-select", "colSpan": "half",
         "apiEndpoint": "/api/imagegen-interfaces/sdk/backend.imagegen.sdk.seedream_wrapper/models-for-node",
         "placeholder": "跟随接口默认"},
        {"key": "resolution", "label": "分辨率", "type": "api-select", "colSpan": "half",
         "apiEndpoint": "/api/imagegen-interfaces/sdk/backend.imagegen.sdk.seedream_wrapper/schema?model={model}",
         "dependsOn": "model", "placeholder": "自动"},
        {"key": "aspect_ratio", "label": "图片比例", "type": "api-select", "colSpan": "half",
         "apiEndpoint": "/api/imagegen-interfaces/sdk/backend.imagegen.sdk.seedream_wrapper/schema?model={model}",
         "dependsOn": "model", "placeholder": "1:1"},
        {"key": "num_images", "label": "生成数量", "type": "number", "min": 1, "max": 15,
         "colSpan": "half", "description": "生成 N 张图片；组图模式单次请求产出多张，其余模式逐张调用"},
        {"key": "output_format", "label": "输出格式", "type": "select", "colSpan": "half", "options": [
            {"value": "png", "label": "PNG"}, {"value": "jpg", "label": "JPG"},
            {"value": "webp", "label": "WebP"},
        ]},
        {"key": "watermark", "label": "添加水印", "type": "checkbox", "colSpan": "half"},
        {"key": "stream_output", "label": "流式输出", "type": "toggle", "colSpan": "half",
         "description": "开启后实时回传生成进度与流式消息，显示在节点进度条下方（5.0 Pro 不支持流式，会自动降级）"},
        {"key": "optimize_prompt", "label": "提示词优化", "type": "toggle", "colSpan": "half",
         "description": "开启后调用 Seedream 提示词优化，提升出图质量"},
        {"key": "custom_prompt_enabled", "label": "自定义提示词", "type": "toggle", "colSpan": "half",
         "description": "开启后使用下方自定义提示词，忽略连线文本输入"},
        {"key": "custom_prompt", "label": "自定义提示词", "type": "textarea", "colSpan": "full",
         "dependsOn": "custom_prompt_enabled", "dependsValue": True,
         "placeholder": "输入生图提示词（开启「自定义提示词」后生效）"},
    ]
    if extra:
        fields.extend(extra)
    return fields


def _seedream_node(node_id, name, description, capability,
                   need_refs=False, layer=False, ref_ports=1,
                   extra_default=None, extra_fields=None, outputs=None):
    inputs = [{"id": "text", "label": "提示词", "type": "text"}]
    if need_refs:
        if ref_ports and ref_ports > 1:
            for i in range(1, ref_ports + 1):
                inputs.append({"id": f"image{i}", "label": f"参考图{i}", "type": "image"})
        else:
            inputs.append({"id": "image", "label": "参考图", "type": "image"})
    default = {
        "model": "",  # 空 = 跟随图像生成接口（字节 Seedream）的默认模型设置
        "resolution": "auto",
        "aspect_ratio": "1:1",
        "num_images": 1,
        "output_format": "png",
        "watermark": False,
        "stream_output": True,
        "optimize_prompt": True,
        "custom_prompt_enabled": False,
        "custom_prompt": "",
    }
    if extra_default:
        default.update(extra_default)
    outputs = outputs or [
        {"id": "images", "label": "输出图片列表", "type": "json"},
        {"id": "text", "label": "第一张图片", "type": "image"},
    ]
    # 模型下拉列表镜像 AI生图 节点：按能力 mode 过滤，从后端接口动态获取（不写死）
    fields = _seedream_common_fields(extra_fields)
    for f in fields:
        if f.get("key") == "model":
            f["apiEndpoint"] = f["apiEndpoint"] + f"?mode={capability}"
    return {
        "id": node_id,
        "name": name,
        "execution_domain": "process",
        "category": "ai_gen",
        "description": description,
        "icon": "Image",
        "color": "#f472b6",
        "inputs": inputs,
        "outputs": outputs,
        "defaultConfig": default,
        "configFields": fields,
    }


_SEEDREAM_NODES = [
    _seedream_node(
        "seedream_txt2img", "Seedream文生图",
        "调用火山引擎方舟 Seedream 文生图（txt2img）：根据提示词生成单张图片。支持流式输出与提示词优化，产物保存到 cache/images。",
        "txt2img"),
    _seedream_node(
        "seedream_img2img", "Seedream图生图",
        "调用 Seedream 图生图（img2img）：以一张参考图为基础按提示词重绘生成单张图片。",
        "img2img", need_refs=True),
    _seedream_node(
        "seedream_fusion", "Seedream多图融合",
        "调用 Seedream 多图融合（fusion）：融合多张参考图生成单张图片。支持 image1~image5 共 5 个参考图输入口，按实际连接组装成输入列表。",
        "fusion", need_refs=True, ref_ports=5),
    _seedream_node(
        "seedream_grid", "Seedream组图生成",
        "调用 Seedream 文生组图（grid / sequential_image_generation）：根据提示词一次生成多张图片。",
        "grid", extra_default={"num_images": 4}),
    _seedream_node(
        "seedream_websearch", "Seedream联网搜索生图",
        "调用 Seedream 联网搜索生图（websearch / tools=[web_search]）：结合网络搜索结果按提示词生成图片，适合需要真实世界参考的场景。",
        "websearch"),
    _seedream_node(
        "seedream_layer", "Seedream图层拆分",
        "调用 Seedream 图层拆分（img2img + layer_decomposition，需 5.0 Pro）：将一张参考图拆为底图与多个图层（含 z_index/名称/bounding_box 坐标），便于二次编辑。",
        "img2img", need_refs=True, layer=True,
        outputs=[
            {"id": "base", "label": "底图", "type": "image"},
            {"id": "layers", "label": "图层列表", "type": "list"},
            {"id": "coords", "label": "坐标数据", "type": "json"},
        ]),
]
BUILTIN_NODE_TYPES.extend(_SEEDREAM_NODES)


# ─────────────────────────────────────────────────────────────────────────────
# Seedance 视频生成能力节点（即梦品牌命名，底层为火山方舟 Seedance）
# ─────────────────────────────────────────────────────────────────────────────
def _seedance_node(node_id, name, description, capability,
                   need_refs=False, ref_ports=1, outputs=None, extra_fields=None):
    inputs = [{"id": "text", "label": "提示词", "type": "text"}]
    if capability == "autovideo":
        inputs.append({"id": "image", "label": "参考图列表", "type": "list"})
        inputs.append({"id": "video", "label": "参考视频", "type": "video"})
        inputs.append({"id": "audio", "label": "参考音频", "type": "audio"})
    elif need_refs:
        if ref_ports and ref_ports > 1:
            for i in range(1, ref_ports + 1):
                inputs.append({"id": f"image{i}", "label": f"参考图{i}", "type": "image"})
        else:
            inputs.append({"id": "image", "label": "参考图", "type": "image"})
    default = {
        "model": "doubao-seedance-2-5-pro-260628",
        "resolution": "720P",
        "ratio": "16:9",
        "duration": 5,
        "num_videos": 1,
        "audio": "on",
        "output_format": "mp4",
        "watermark": False,
        "prefer_history": False,
        "custom_prompt_enabled": False,
        "custom_prompt": "",
        "extract_last_frame": False,
    }
    outputs = outputs or [
        {"id": "video", "label": "视频", "type": "video"},
        {"id": "videos", "label": "视频列表", "type": "list"},
        {"id": "last_frame", "label": "尾帧", "type": "image"},
        {"id": "params", "label": "生成参数JSON", "type": "json"},
        {"id": "task_id", "label": "任务ID", "type": "text"},
    ]
    return {
        "id": node_id,
        "name": name,
        "execution_domain": "process",
        "category": "ai_gen",
        "description": description,
        "icon": "Film",
        "color": "#a855f7",
        "inputs": inputs,
        "outputs": outputs,
        "defaultConfig": default,
        # 即梦(Seedance) 节点的参数面板由前端 SeedanceVideoNode 按所选模型能力动态渲染，
        # 不再依赖静态 configFields（模型切换时分辨率/时长/声音/各专有开关均随之调整）。
        "configFields": [],
    }


_SEEDANCE_NODES = [
    _seedance_node(
        "seedance_txt2video", "即梦-文生视频",
        "调用火山方舟 Seedance 文生视频（txt2video）：根据提示词生成视频。支持异步任务轮询、优先历史记录与查询进度。",
        "txt2video"),
    _seedance_node(
        "seedance_img2video", "即梦-图生视频",
        "调用 Seedance 图生视频-首帧（img2video）：以 1 张参考图为首帧，按提示词生成视频。",
        "img2video", need_refs=True),
    _seedance_node(
        "seedance_flf2video", "即梦-图生视频(首尾帧)",
        "调用 Seedance 图生视频-首尾帧（flf2video）：以 2 张参考图（首帧/尾帧）生成视频。",
        "flf2video", need_refs=True, ref_ports=2),
    _seedance_node(
        "seedance_autovideo", "即梦-全模态参考生视频",
        "调用 Seedance 全模态参考生视频（autovideo）：以参考图/视频/音频任意组合生成视频。",
        "autovideo", need_refs=True, ref_ports=3),
]
BUILTIN_NODE_TYPES.extend(_SEEDANCE_NODES)


# ─────────────────────────────────────────────────────────────────────────────
# AI 音乐生成能力节点（底层为 KieAI / Suno，经 backend.musicgen 工厂统一调用）
#
# 每种生成能力一个节点，统一由 backend/steps/s_musicgen.py 的 S_MusicGenBase 执行：
#   music_txt2music         文生音乐（含人声）
#   music_instrumental      纯音乐（无歌词）
#   music_lyrics            歌词生成
#   music_extend            音乐扩展（按上游 audio_id 续写）
#   music_cover             翻唱 / 风格迁移（参考音频）
#   music_add_instrumental  添加伴奏
#   music_add_vocals        添加人声
#   music_separate          人声 / 分轨分离
#   music_to_wav            转 WAV
#   music_upload_extend     上传本地音频并扩展
#
# 提示词来源兼容：所有含提示词的节点均提供 text 输入口与「使用节点内提示词」开关——
#   开关关闭 → 使用上游连线文本；开关打开且内容非空 → 使用节点内填写的提示词。
# ─────────────────────────────────────────────────────────────────────────────
MUSIC_IFACE_API = "/api/musicgen-interfaces"

_VOCAL_GENDER_OPTIONS = [
    {"value": "", "label": "不指定"},
    {"value": "male", "label": "男声"},
    {"value": "female", "label": "女声"},
    {"value": "girl", "label": "少女"},
    {"value": "boy", "label": "少年"},
    {"value": "woman", "label": "成熟女声"},
    {"value": "man", "label": "成熟男声"},
    {"value": "children", "label": "童声"},
    {"value": "young boy", "label": "年轻男声"},
    {"value": "young girl", "label": "年轻女声"},
]

_DURATION_OPTIONS = [
    {"value": "15", "label": "15 秒"},
    {"value": "30", "label": "30 秒"},
    {"value": "60", "label": "60 秒"},
    {"value": "120", "label": "120 秒"},
    {"value": "240", "label": "240 秒"},
]


def _music_common_fields(capability: str, extra=None):
    """音乐节点通用面板：接口 + 模型（模型按能力模式过滤，从接口配置动态获取）。"""
    fields = [
        {"key": "interface", "label": "音乐接口", "type": "api-select", "colSpan": "half",
         "apiEndpoint": f"{MUSIC_IFACE_API}/enabled",
         "optionLabel": "name", "optionValue": "id",
         "placeholder": "跟随全局默认接口"},
        {"key": "model", "label": "模型", "type": "api-select", "colSpan": "half",
         "apiEndpoint": f"{MUSIC_IFACE_API}/{{interface}}/models-for-node?mode={capability}",
         "dependsOn": "interface", "placeholder": "跟随接口默认模型"},
    ]
    if extra:
        fields.extend(extra)
    return fields


def _music_prompt_fields():
    """提示词双来源：上游连线文本输入 或 节点内自定义提示词。"""
    return [
        {"key": "custom_prompt_enabled", "label": "使用节点内提示词", "type": "toggle", "colSpan": "half",
         "description": "关闭时使用上游连线的文本输入；开启后优先使用下方「自定义提示词」"},
        {"key": "custom_prompt", "label": "自定义提示词", "type": "textarea", "colSpan": "full",
         "dependsOn": "custom_prompt_enabled", "dependsValue": True,
         "placeholder": "输入提示词 / 歌词 / 风格描述（开启「使用节点内提示词」后生效）"},
    ]


def _music_node(node_id, name, description, capability, icon="Music",
                inputs=None, outputs=None, extra_fields=None,
                extra_default=None, prompt=True):
    ins = list(inputs or [])
    if prompt and not any(i.get("id") == "text" for i in ins):
        ins.insert(0, {"id": "text", "label": "提示词 / 歌词", "type": "text"})

    fields = _music_common_fields(capability)
    if prompt:
        fields.extend(_music_prompt_fields())
    if extra_fields:
        fields.extend(extra_fields)
    fields.append(
        {"key": "poll_timeout", "label": "轮询超时(秒)", "type": "number",
         "min": 60, "max": 3600, "colSpan": "half",
         "description": "生成任务最长等待时间，超时视为失败"}
    )

    default = {
        "interface": "",
        "model": "",
        "custom_prompt_enabled": False,
        "custom_prompt": "",
        "poll_timeout": 600,
    }
    if extra_default:
        default.update(extra_default)

    outs = outputs or [
        {"id": "audio", "label": "音频", "type": "audio"},
        {"id": "audios", "label": "音频列表", "type": "json"},
        {"id": "params", "label": "生成参数JSON", "type": "json"},
    ]

    return {
        "id": node_id,
        "name": name,
        "execution_domain": "process",
        "category": "music_gen",
        "description": description,
        "icon": icon,
        "color": "#a78bfa",
        "inputs": ins,
        "outputs": outs,
        "defaultConfig": default,
        "configFields": fields,
    }


_MUSIC_NODES = [
    _music_node(
        "music_txt2music", "AI音乐-文生音乐",
        "根据提示词 / 歌词生成完整歌曲（含人声）。提示词可来自连线文本输入或节点内自定义；产物为音频。",
        "txt2music", icon="Music",
        extra_default={"instrumental": False, "duration": "60"},
        extra_fields=[
            {"key": "style", "label": "音乐风格", "type": "text", "colSpan": "half",
             "placeholder": "如：pop, cinematic, lo-fi"},
            {"key": "title", "label": "歌曲标题", "type": "text", "colSpan": "half"},
            {"key": "instrumental", "label": "纯音乐(无歌词)", "type": "toggle", "colSpan": "half"},
            {"key": "duration", "label": "时长", "type": "select", "colSpan": "half",
             "options": _DURATION_OPTIONS},
            {"key": "negative_tags", "label": "反向标签", "type": "text", "colSpan": "half",
             "placeholder": "逗号分隔，如：heavy metal"},
            {"key": "vocal_gender", "label": "人声性别", "type": "select", "colSpan": "half",
             "options": _VOCAL_GENDER_OPTIONS},
        ]),
    _music_node(
        "music_instrumental", "AI音乐-纯音乐",
        "根据风格描述生成无人声的纯音乐 / 伴奏。提示词可来自连线文本输入或节点内自定义。",
        "instrumental", icon="Music2",
        extra_default={"duration": "60"},
        extra_fields=[
            {"key": "style", "label": "音乐风格", "type": "text", "colSpan": "half",
             "placeholder": "如：piano, ambient, epic"},
            {"key": "title", "label": "曲目标题", "type": "text", "colSpan": "half"},
            {"key": "duration", "label": "时长", "type": "select", "colSpan": "half",
             "options": _DURATION_OPTIONS},
            {"key": "negative_tags", "label": "反向标签", "type": "text", "colSpan": "half",
             "placeholder": "逗号分隔"},
        ]),
    _music_node(
        "music_lyrics", "AI音乐-歌词生成",
        "根据主题描述生成歌词文本（不产出音频）。主题可来自连线文本输入或节点内自定义；输出歌词文本供「文生音乐」等节点使用。",
        "lyrics", icon="ListMusic",
        outputs=[
            {"id": "text", "label": "歌词文本", "type": "text"},
            {"id": "params", "label": "生成参数JSON", "type": "json"},
        ],
        extra_fields=[
            {"key": "style", "label": "音乐风格", "type": "text", "colSpan": "half",
             "placeholder": "如：pop, rock"},
            {"key": "title", "label": "歌曲标题", "type": "text", "colSpan": "half"},
        ]),
    _music_node(
        "music_extend", "AI音乐-音乐扩展",
        "对已有曲目做续写扩展：从上游音乐节点的参数 JSON 取 audio_id（也可直接填 audio_id），可指定续写起点与续写提示词。",
        "extend", icon="Repeat",
        inputs=[
            {"id": "json", "label": "上游音乐参数JSON", "type": "json"},
            {"id": "text", "label": "续写提示词", "type": "text"},
        ],
        extra_fields=[
            {"key": "audio_id", "label": "音频ID", "type": "text", "colSpan": "half",
             "description": "留空则自动从上游参数 JSON 中读取 audio_id", "placeholder": "上游传入时留空"},
            {"key": "continue_at", "label": "续写起点(秒)", "type": "number", "min": 0, "colSpan": "half",
             "description": "从原曲的第 N 秒开始续写"},
            {"key": "default_param_flag", "label": "沿用原曲参数", "type": "toggle", "colSpan": "half"},
            {"key": "style", "label": "音乐风格", "type": "text", "colSpan": "half"},
            {"key": "title", "label": "歌曲标题", "type": "text", "colSpan": "half"},
            {"key": "instrumental", "label": "纯音乐", "type": "toggle", "colSpan": "half"},
            {"key": "negative_tags", "label": "反向标签", "type": "text", "colSpan": "half"},
            {"key": "vocal_gender", "label": "人声性别", "type": "select", "colSpan": "half",
             "options": _VOCAL_GENDER_OPTIONS},
        ]),
    _music_node(
        "music_cover", "AI音乐-翻唱/风格迁移",
        "上传参考音频并按提示词 / 风格做翻唱或风格迁移。参考音频从连线 audio 输入（本地文件自动上传）。",
        "cover", icon="Disc",
        inputs=[
            {"id": "audio", "label": "参考音频", "type": "audio"},
            {"id": "text", "label": "风格/提示词", "type": "text"},
        ],
        extra_fields=[
            {"key": "style", "label": "目标风格", "type": "text", "colSpan": "half",
             "placeholder": "如：jazz, electronic"},
            {"key": "title", "label": "曲目标题", "type": "text", "colSpan": "half"},
            {"key": "custom_mode", "label": "自定义模式", "type": "toggle", "colSpan": "half",
             "description": "开启后使用节点内的风格/标题/提示词，否则由模型自动推断"},
            {"key": "instrumental", "label": "纯音乐", "type": "toggle", "colSpan": "half"},
            {"key": "negative_tags", "label": "反向标签", "type": "text", "colSpan": "half"},
            {"key": "vocal_gender", "label": "人声性别", "type": "select", "colSpan": "half",
             "options": _VOCAL_GENDER_OPTIONS},
        ]),
    _music_node(
        "music_add_instrumental", "AI音乐-添加伴奏",
        "为人声 / 干声轨道添加伴奏：上传音频后生成带伴奏的完整曲目。",
        "add_instrumental", icon="Guitar",
        inputs=[
            {"id": "audio", "label": "人声音频", "type": "audio"},
            {"id": "text", "label": "标题/标签", "type": "text"},
        ],
        extra_fields=[
            {"key": "title", "label": "曲目标题", "type": "text", "colSpan": "half",
             "description": "留空则自动取提示词前 60 字符"},
            {"key": "tags", "label": "风格标签", "type": "text", "colSpan": "half",
             "placeholder": "如：pop, energetic"},
            {"key": "negative_tags", "label": "反向标签", "type": "text", "colSpan": "half"},
            {"key": "vocal_gender", "label": "人声性别", "type": "select", "colSpan": "half",
             "options": _VOCAL_GENDER_OPTIONS},
        ]),
    _music_node(
        "music_add_vocals", "AI音乐-添加人声",
        "为伴奏 /  instrumental 轨道添加人声：上传音频并提供歌词或演唱提示词。",
        "add_vocals", icon="Mic",
        inputs=[
            {"id": "audio", "label": "伴奏音频", "type": "audio"},
            {"id": "text", "label": "歌词/演唱提示", "type": "text"},
        ],
        extra_fields=[
            {"key": "title", "label": "曲目标题", "type": "text", "colSpan": "half",
             "description": "留空则自动取提示词前 60 字符"},
            {"key": "style", "label": "音乐风格", "type": "text", "colSpan": "half"},
            {"key": "negative_tags", "label": "反向标签", "type": "text", "colSpan": "half"},
            {"key": "vocal_gender", "label": "人声性别", "type": "select", "colSpan": "half",
             "options": _VOCAL_GENDER_OPTIONS},
        ]),
    _music_node(
        "music_separate", "AI音乐-人声分离",
        "对已有曲目做分轨分离（人声 / 伴奏 / 鼓 / 贝斯等）。可接上游音频文件，也可从上游参数 JSON 取 task_id / audio_id。",
        "separate", icon="Scissors",
        inputs=[
            {"id": "audio", "label": "待分离音频", "type": "audio"},
            {"id": "json", "label": "上游音乐参数JSON", "type": "json"},
        ],
        extra_fields=[
            {"key": "stem_type", "label": "分离类型", "type": "text", "colSpan": "half",
             "placeholder": "all / vocals / instrumental / drums / bass",
             "description": "留空默认 all（分离为人声 + 伴奏）"},
        ]),
    _music_node(
        "music_to_wav", "AI音乐-转WAV",
        "把已有曲目转换为 WAV 无损格式：从上游音乐节点的参数 JSON 取 task_id / audio_id。",
        "to_wav", icon="FileAudio", prompt=False,
        inputs=[{"id": "json", "label": "上游音乐参数JSON", "type": "json"}],
        outputs=[
            {"id": "audio", "label": "WAV音频", "type": "audio"},
            {"id": "params", "label": "生成参数JSON", "type": "json"},
        ]),
    _music_node(
        "music_upload_extend", "AI音乐-上传并扩展",
        "上传本地音频并续写扩展：参考音频从连线 audio 输入，可指定续写起点与提示词。",
        "upload_extend", icon="Repeat2",
        inputs=[
            {"id": "audio", "label": "本地音频", "type": "audio"},
            {"id": "text", "label": "续写提示词", "type": "text"},
        ],
        extra_fields=[
            {"key": "continue_at", "label": "续写起点(秒)", "type": "number", "min": 0, "colSpan": "half"},
            {"key": "default_param_flag", "label": "沿用原曲参数", "type": "toggle", "colSpan": "half"},
            {"key": "style", "label": "音乐风格", "type": "text", "colSpan": "half"},
            {"key": "title", "label": "歌曲标题", "type": "text", "colSpan": "half"},
            {"key": "instrumental", "label": "纯音乐", "type": "toggle", "colSpan": "half"},
            {"key": "negative_tags", "label": "反向标签", "type": "text", "colSpan": "half"},
            {"key": "vocal_gender", "label": "人声性别", "type": "select", "colSpan": "half",
             "options": _VOCAL_GENDER_OPTIONS},
        ]),
]
BUILTIN_NODE_TYPES.extend(_MUSIC_NODES)


# ─────────────────────────────────────────────────────────────────────────────
# KIE AI 图片高清放大节点（直接调用 backend/kieai_sdk，不经生图接口）
#
# 支持 KIE market 风格放大模型（createTask 提交 + recordInfo 轮询）：
#   recraft/crisp-upscale  参数: image
#   topaz/image-upscale    参数: image_url, upscale_factor(1/2/4)
#
# API Key：读取项目密钥库中的 KIEAI_API_KEY（全局设置 → 密钥管理器），
# 缺失时回退环境变量 KIEAI_API_KEY。卡片首行提供「获取key」「用量日志」两个外链按钮。
# ─────────────────────────────────────────────────────────────────────────────
_KIE_UPSCALE_KEY_URL = "https://kie.ai?ref=1ef5b0d4df5fc43ae85034755f9bf754"
_KIE_UPSCALE_LOGS_URL = "https://kie.ai/zh-CN/logs"

_KIE_UPSCALE_NODES = [
    {
        "id": "kie_image_upscale",
        "name": "图片高清放大-kie",
        "execution_domain": "process",
        "category": "ai_gen",
        "description": (
            "调用 KIE AI 对图片做高清放大。使用前请先注册 KIE 账号并获取 API Key："
            "点击卡片上方「获取key」前往官网注册，拿到 Key 后填入【全局设置 → 密钥管理器】，"
            "密钥名称必须为 KIEAI_API_KEY（也可在系统环境变量中设置同名变量）；"
            "调用量与扣费明细可点击「用量日志」查看。"
        ),
        "icon": "ZoomIn",
        "color": "#0ea5e9",
        "inputs": [
            {"id": "image", "label": "待放大图片", "type": "image", "required": True},
        ],
        "outputs": [
            {"id": "image", "label": "放大后图片", "type": "image"},
            {"id": "images", "label": "图片列表", "type": "json"},
            {"id": "params", "label": "处理参数JSON", "type": "json"},
        ],
        "defaultConfig": {
            "model": "recraft/crisp-upscale",
            "upscale_factor": "2",
            "poll_timeout": 600,
        },
        "configFields": [
            {"key": "btn_get_key", "label": "获取key", "type": "button", "colSpan": "half",
             "url": _KIE_UPSCALE_KEY_URL,
             "description": "前往 KIE 官网注册并获取 API Key"},
            {"key": "btn_usage_logs", "label": "用量日志", "type": "button", "colSpan": "half",
             "url": _KIE_UPSCALE_LOGS_URL,
             "description": "在 KIE 控制台查看调用量与扣费明细"},
            {"key": "model", "label": "放大模型", "type": "select", "colSpan": "half",
             "options": [
                 {"value": "recraft/crisp-upscale", "label": "Recraft Crisp Upscale（锐利放大，$0.0025/张）"},
                 {"value": "topaz/image-upscale", "label": "Topaz Image Upscale（可设倍数，$0.2/张）"},
             ],
             "description": "KIE 平台提供的放大模型"},
            {"key": "upscale_factor", "label": "放大倍数", "type": "select", "colSpan": "half",
             "options": [
                 {"value": "1", "label": "1 倍"},
                 {"value": "2", "label": "2 倍"},
                 {"value": "4", "label": "4 倍"},
             ],
             "dependsOn": "model", "dependsValue": "topaz/image-upscale",
             "description": "仅 Topaz 模型支持；Recraft 为固定锐利放大"},
            {"key": "poll_timeout", "label": "轮询超时(秒)", "type": "number",
             "min": 60, "max": 3600, "colSpan": "half",
             "description": "放大任务最长等待时间，超时视为失败"},
        ],
    },
]
BUILTIN_NODE_TYPES.extend(_KIE_UPSCALE_NODES)


# ─────────────────────────────────────────────────────────────────────────────
# KIE AI 视频高清放大节点（直接调用 backend/kieai_sdk，不经视频生成接口）
#
# 支持 KIE market 风格放大模型（createTask 提交 + recordInfo 轮询）：
#   topaz/video-upscale  参数: video_url, upscale_factor(1/2/4)
#
# API Key：读取项目密钥库中的 KIEAI_API_KEY（全局设置 → 密钥管理器），
# 缺失时回退环境变量 KIEAI_API_KEY。卡片首行提供「获取key」「用量日志」两个外链按钮。
# ─────────────────────────────────────────────────────────────────────────────
_KIE_VIDEO_UPSCALE_NODES = [
    {
        "id": "kie_video_upscale",
        "name": "视频高清放大-kie",
        "execution_domain": "process",
        "category": "ai_gen",
        "description": (
            "调用 KIE AI 对视频做高清放大。使用前请先注册 KIE 账号并获取 API Key："
            "点击卡片上方「获取key」前往官网注册，拿到 Key 后填入【全局设置 → 密钥管理器】，"
            "密钥名称必须为 KIEAI_API_KEY（也可在系统环境变量中设置同名变量）；"
            "调用量与扣费明细可点击「用量日志」查看。"
        ),
        "icon": "Film",
        "color": "#0ea5e9",
        "inputs": [
            {"id": "video", "label": "待放大视频", "type": "video", "required": True},
        ],
        "outputs": [
            {"id": "video", "label": "放大后视频", "type": "video"},
            {"id": "videos", "label": "视频列表", "type": "json"},
            {"id": "params", "label": "处理参数JSON", "type": "json"},
        ],
        "defaultConfig": {
            "model": "topaz/video-upscale",
            "upscale_factor": "2",
            "poll_timeout": 900,
        },
        "configFields": [
            {"key": "btn_get_key", "label": "获取key", "type": "button", "colSpan": "half",
             "url": _KIE_UPSCALE_KEY_URL,
             "description": "前往 KIE 官网注册并获取 API Key"},
            {"key": "btn_usage_logs", "label": "用量日志", "type": "button", "colSpan": "half",
             "url": _KIE_UPSCALE_LOGS_URL,
             "description": "在 KIE 控制台查看调用量与扣费明细"},
            {"key": "model", "label": "放大模型", "type": "select", "colSpan": "half",
             "options": [
                 {"value": "topaz/video-upscale", "label": "Topaz Video Upscale（可设倍数，$0.07/次）"},
             ],
             "description": "KIE 平台提供的视频放大模型"},
            {"key": "upscale_factor", "label": "放大倍数", "type": "select", "colSpan": "half",
             "options": [
                 {"value": "1", "label": "1 倍"},
                 {"value": "2", "label": "2 倍"},
                 {"value": "4", "label": "4 倍"},
             ],
             "description": "放大倍数，留空/默认 2 倍"},
            {"key": "poll_timeout", "label": "轮询超时(秒)", "type": "number",
             "min": 60, "max": 7200, "colSpan": "half",
             "description": "视频放大耗时较长，默认 900 秒，超时视为失败"},
        ],
    },
]
BUILTIN_NODE_TYPES.extend(_KIE_VIDEO_UPSCALE_NODES)


# ─────────────────────────────────────────────────────────────────────────────
# KIE AI 视频对口型节点（直接调用 backend/kieai_sdk）
#
# 支持 KIE market 风格模型（createTask 提交 + recordInfo 轮询）：
#   volcengine/video-to-video-lip-sync
#     必填: mode(lite/basic), video_url, audio_url
#     可选: separate_vocal, open_scenedet, align_audio, align_audio_reverse,
#           templ_start_seconds
#
# API Key：读取项目密钥库中的 KIEAI_API_KEY（全局设置 → 密钥管理器），
# 缺失时回退环境变量 KIEAI_API_KEY。卡片首行提供「获取key」「用量日志」两个外链按钮。
# ─────────────────────────────────────────────────────────────────────────────
_KIE_LIP_SYNC_NODES = [
    {
        "id": "kie_lip_sync",
        "name": "视频对口型-kie",
        "execution_domain": "process",
        "category": "ai_gen",
        "description": (
            "调用 KIE AI 让视频人物口型匹配目标音频（视频 + 音频 → 对口型视频）。"
            "使用前请先注册 KIE 账号并获取 API Key：点击卡片上方「获取key」前往官网注册，"
            "拿到 Key 后填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY"
            "（也可在系统环境变量中设置同名变量）；调用量与扣费明细可点击「用量日志」查看。"
        ),
        "icon": "Mic",
        "color": "#0ea5e9",
        "inputs": [
            {"id": "video", "label": "待对口型视频", "type": "video", "required": True},
            {"id": "audio", "label": "目标音频", "type": "audio", "required": True},
        ],
        "outputs": [
            {"id": "video", "label": "对口型视频", "type": "video"},
            {"id": "videos", "label": "视频列表", "type": "json"},
            {"id": "params", "label": "处理参数JSON", "type": "json"},
        ],
        "defaultConfig": {
            "model": "volcengine/video-to-video-lip-sync",
            "mode": "basic",
            "separate_vocal": False,
            "open_scenedet": False,
            "align_audio": True,
            "align_audio_reverse": False,
            "templ_start_seconds": 0,
            "poll_timeout": 900,
        },
        "configFields": [
            {"key": "btn_get_key", "label": "获取key", "type": "button", "colSpan": "half",
             "url": _KIE_UPSCALE_KEY_URL,
             "description": "前往 KIE 官网注册并获取 API Key"},
            {"key": "btn_usage_logs", "label": "用量日志", "type": "button", "colSpan": "half",
             "url": _KIE_UPSCALE_LOGS_URL,
             "description": "在 KIE 控制台查看调用量与扣费明细"},
            {"key": "model", "label": "对口型模型", "type": "select", "colSpan": "half",
             "options": [
                 {"value": "volcengine/video-to-video-lip-sync", "label": "Volcengine Lip Sync（$0.04/次）"},
             ],
             "description": "KIE 平台提供的视频对口型模型"},
            {"key": "mode", "label": "生成模式", "type": "select", "colSpan": "half",
             "options": [
                 {"value": "basic", "label": "basic（质量优先）"},
                 {"value": "lite", "label": "lite（速度优先）"},
             ],
             "description": "必填；basic 质量更好，lite 更快"},
            {"key": "separate_vocal", "label": "人声分离", "type": "toggle", "colSpan": "half",
             "description": "对目标音频先做人声分离，再用纯人声驱动口型"},
            {"key": "open_scenedet", "label": "场景检测", "type": "toggle", "colSpan": "half",
             "description": "开启镜头/场景检测，多镜头视频效果更好"},
            {"key": "align_audio", "label": "音画对齐", "type": "toggle", "colSpan": "half",
             "description": "自动对齐音频与画面，默认开启"},
            {"key": "align_audio_reverse", "label": "反向对齐", "type": "toggle", "colSpan": "half",
             "description": "在 align_audio 基础上使用反向对齐策略"},
            {"key": "templ_start_seconds", "label": "模板起始秒", "type": "number",
             "min": 0, "max": 3600, "colSpan": "half",
             "description": "从视频第 N 秒开始作为对口型模板，默认 0"},
            {"key": "poll_timeout", "label": "轮询超时(秒)", "type": "number",
             "min": 60, "max": 7200, "colSpan": "half",
             "description": "口型合成耗时较长，默认 900 秒，超时视为失败"},
        ],
    },
]
BUILTIN_NODE_TYPES.extend(_KIE_LIP_SYNC_NODES)


# ─────────────────────────────────────────────────────────────────────────────
# KIE AI 图声生视频节点（图片 + 声音驱动视频，直接调用 backend/kieai_sdk）
#
# 支持 KIE market 风格模型（createTask 提交 + recordInfo 轮询）：
#   kling-3.0/video              image_urls(最多 5 张参考图) + 声音经 kling_elements
#   kling/ai-avatar-standard     image_url + audio_url + prompt
#   kling/ai-avatar-pro          image_url + audio_url + prompt
#   infinitalk/from-audio        image_url + audio_url + prompt (+resolution/seed)
#
# API Key：读取项目密钥库中的 KIEAI_API_KEY（全局设置 → 密钥管理器），
# 缺失时回退环境变量 KIEAI_API_KEY。卡片首行提供「获取key」「用量日志」两个外链按钮。
# ─────────────────────────────────────────────────────────────────────────────
_KIE_AV_MODEL_OPTIONS = [
    {"value": "infinitalk/from-audio", "label": "Infinitalk From Audio（图+声）"},
    {"value": "kling-3.0/video", "label": "Kling 3.0（最多 5 张参考图，$0.335/次）"},
    {"value": "kling/ai-avatar-standard", "label": "Kling AI Avatar Standard（$0.335/次）"},
    {"value": "kling/ai-avatar-pro", "label": "Kling AI Avatar Pro（$0.335/次）"},
]

_KIE_IMAGE_AUDIO_NODES = [
    {
        "id": "kie_image_audio_to_video",
        "name": "图声生视频-kie",
        "execution_domain": "process",
        "category": "ai_gen",
        "description": (
            "用图片 + 声音驱动生成视频（数字人 / 对口型 / 角色演绎）。"
            "image1 为必填主图，kling-3.0/video 额外支持 image2~image5 共 5 张参考图；"
            "audio 输入口接驱动音频；提示词可来自连线文本或节点内填写。"
            "使用前请先注册 KIE 账号并获取 API Key：点击卡片上方「获取key」前往官网注册，"
            "拿到 Key 后填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY"
            "（也可在系统环境变量中设置同名变量）；用量见「用量日志」。"
        ),
        "icon": "UserRound",
        "color": "#0ea5e9",
        "inputs": [
            {"id": "image1", "label": "主图片", "type": "image", "required": True},
            {"id": "image2", "label": "参考图2", "type": "image"},
            {"id": "image3", "label": "参考图3", "type": "image"},
            {"id": "image4", "label": "参考图4", "type": "image"},
            {"id": "image5", "label": "参考图5", "type": "image"},
            {"id": "audio", "label": "驱动音频", "type": "audio", "required": True},
            {"id": "text", "label": "提示词", "type": "text"},
        ],
        "outputs": [
            {"id": "video", "label": "生成视频", "type": "video"},
            {"id": "videos", "label": "视频列表", "type": "json"},
            {"id": "params", "label": "生成参数JSON", "type": "json"},
        ],
        "defaultConfig": {
            "model": "infinitalk/from-audio",
            "custom_prompt_enabled": False,
            "custom_prompt": "",
            "mode": "pro",
            "duration": 5,
            "aspect_ratio": "16:9",
            "sound": False,
            "resolution": "480p",
            "seed": "",
            "poll_timeout": 900,
        },
        "configFields": [
            {"key": "btn_get_key", "label": "获取key", "type": "button", "colSpan": "half",
             "url": _KIE_UPSCALE_KEY_URL,
             "description": "前往 KIE 官网注册并获取 API Key"},
            {"key": "btn_usage_logs", "label": "用量日志", "type": "button", "colSpan": "half",
             "url": _KIE_UPSCALE_LOGS_URL,
             "description": "在 KIE 控制台查看调用量与扣费明细"},
            {"key": "model", "label": "生成模型", "type": "select", "colSpan": "half",
             "options": _KIE_AV_MODEL_OPTIONS,
             "description": "图片 + 声音驱动视频的模型"},
            {"key": "custom_prompt_enabled", "label": "使用节点内提示词", "type": "toggle", "colSpan": "half",
             "description": "关闭时使用上游连线文本；开启后使用下方提示词（所有模型均需提示词）"},
            {"key": "custom_prompt", "label": "自定义提示词", "type": "textarea", "colSpan": "full",
             "dependsOn": "custom_prompt_enabled", "dependsValue": True,
             "placeholder": "描述画面内容与人物动作，开启「使用节点内提示词」后生效"},
            # Kling 3.0 专有
            {"key": "mode", "label": "画质模式", "type": "select", "colSpan": "half",
             "options": [
                 {"value": "pro", "label": "pro（1080P）"},
                 {"value": "std", "label": "std（720P）"},
                 {"value": "4K", "label": "4K（2160P）"},
             ],
             "dependsOn": "model", "dependsValue": "kling-3.0/video",
             "description": "Kling 3.0 生成模式"},
            {"key": "duration", "label": "时长(秒)", "type": "number", "min": 3, "max": 15, "colSpan": "half",
             "dependsOn": "model", "dependsValue": "kling-3.0/video",
             "description": "Kling 3.0 视频时长，3-15 秒"},
            {"key": "aspect_ratio", "label": "画面比例", "type": "select", "colSpan": "half",
             "options": [
                 {"value": "16:9", "label": "16:9"},
                 {"value": "9:16", "label": "9:16"},
                 {"value": "1:1", "label": "1:1"},
             ],
             "dependsOn": "model", "dependsValue": "kling-3.0/video",
             "description": "Kling 3.0 画面比例（提供参考图时可不填，会自动适配）"},
            {"key": "sound", "label": "生成音效", "type": "toggle", "colSpan": "half",
             "dependsOn": "model", "dependsValue": "kling-3.0/video",
             "description": "Kling 3.0 是否生成音效（与输入音频不同）"},
            # Infinitalk 专有
            {"key": "resolution", "label": "分辨率", "type": "select", "colSpan": "half",
             "options": [
                 {"value": "480p", "label": "480p"},
                 {"value": "720p", "label": "720p"},
             ],
             "dependsOn": "model", "dependsValue": "infinitalk/from-audio",
             "description": "Infinitalk 输出分辨率"},
            {"key": "seed", "label": "随机种子", "type": "number", "min": 10000, "max": 1000000, "colSpan": "half",
             "dependsOn": "model", "dependsValue": "infinitalk/from-audio",
             "description": "Infinitalk 随机种子，留空随机"},
            {"key": "poll_timeout", "label": "轮询超时(秒)", "type": "number",
             "min": 60, "max": 7200, "colSpan": "half",
             "description": "视频生成耗时较长，默认 900 秒，超时视为失败"},
        ],
    },
]
BUILTIN_NODE_TYPES.extend(_KIE_IMAGE_AUDIO_NODES)


# ─────────────────────────────────────────────────────────────────────────────
# KIE AI 图床网存节点（免费媒体暂存，直接调用 kieai_sdk 的上传接口）
#
# 使用 catalog 中的 file-upload 家族：
#   upload-file-base64   base64Data + uploadPath + fileName
#   upload-file-url      fileUrl    + uploadPath + fileName
# 返回 data.downloadUrl，可直接作为其它 KIE 生成接口的输入 URL。
#
# 说明：仅需 KIE API Key，不消耗生成额度（免费暂存）。
# API Key：读取项目密钥库 KIEAI_API_KEY（全局设置 → 密钥管理器）-> 环境变量。
# ─────────────────────────────────────────────────────────────────────────────
_KIE_MEDIA_HOST_NODES = [
    {
        "id": "kie_media_host",
        "name": "图床网存-kie",
        "execution_domain": "process",
        "category": "network_request",
        "description": (
            "把本地图片 / 视频 / 音频上传到 KIE 免费媒体暂存，返回可直接访问的外链 URL，"
            "供其它接口（生图、生视频、对口型、图声生视频等）引用。"
            "支持 image / video / audio / file 四个输入口，可同时上传多个文件（已连接的口都会上传）。"
            "注意：本节点仅做文件暂存，不消耗生成额度；使用前请先注册 KIE 账号并获取 API Key，"
            "填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY"
            "（也可在系统环境变量中设置同名变量）。"
        ),
        "icon": "Upload",
        "color": "#0ea5e9",
        "inputs": [
            {"id": "image", "label": "图片", "type": "image"},
            {"id": "video", "label": "视频", "type": "video"},
            {"id": "audio", "label": "音频", "type": "audio"},
            {"id": "file", "label": "其它文件", "type": "filepath"},
        ],
        "outputs": [
            {"id": "url", "label": "首个链接", "type": "url"},
            {"id": "urls", "label": "链接列表", "type": "json"},
            {"id": "json", "label": "上传明细", "type": "json"},
        ],
        "defaultConfig": {
            "upload_path": "auto",
            "timeout": 120,
        },
        "configFields": [
            {"key": "btn_get_key", "label": "获取key", "type": "button", "colSpan": "half",
             "url": _KIE_UPSCALE_KEY_URL,
             "description": "前往 KIE 官网注册并获取 API Key"},
            {"key": "btn_usage_logs", "label": "用量日志", "type": "button", "colSpan": "half",
             "url": _KIE_UPSCALE_LOGS_URL,
             "description": "在 KIE 控制台查看调用量与扣费明细"},
            {"key": "upload_path", "label": "存储目录", "type": "select", "colSpan": "half",
             "options": [
                 {"value": "auto", "label": "自动（按扩展名归类）"},
                 {"value": "images", "label": "images（图片）"},
                 {"value": "videos", "label": "videos（视频）"},
                 {"value": "audios", "label": "audios（音频）"},
                 {"value": "files", "label": "files（其它）"},
             ],
             "description": "上传路径 uploadPath；auto 按文件扩展名自动选择目录"},
            {"key": "timeout", "label": "超时(秒)", "type": "number", "min": 10, "max": 1200,
             "colSpan": "half", "description": "单个文件上传超时时间"},
        ],
    },
]
BUILTIN_NODE_TYPES.extend(_KIE_MEDIA_HOST_NODES)


# ─────────────────────────────────────────────────────────────────────────────
# HyperFrames 系列节点
#
# HyperFrames 用 HTML 描述合成、用 `npx hyperframes` 渲染成片。本组节点把它拆成
# 「创意 → 渲染」两步：创意节点收敛出 BRIEF.md（或加载已有 BRIEF.md 复用既有
# 工作流），渲染节点按简报构建并渲染成片；工具节点直接调用 CLI 的附属能力；
# 智能体节点是复合节点，直接驱动本项目的 piagent（小 Pi）框架跑完整条链路。
# 技能源码：backend/config/agent/skills/hyperframes/
# ─────────────────────────────────────────────────────────────────────────────
_HF_WORKFLOW_OPTIONS = [{"value": "", "label": "自动路由（由意图访谈决定）"}]
_HF_WORKFLOW_OPTIONS += [
    {"value": key, "label": f"/{key} — {label}"} for key, label in WORKFLOW_ROUTES.items()
]

_HF_ASPECT_OPTIONS = [
    {"value": "auto", "label": "按投放平台自动推断"},
    {"value": "16:9", "label": "16:9 横屏（YouTube/嵌入）"},
    {"value": "9:16", "label": "9:16 竖屏（短视频）"},
    {"value": "1:1", "label": "1:1 方形（社交信息流）"},
    {"value": "4:3", "label": "4:3"},
    {"value": "21:9", "label": "21:9 宽屏"},
]


def _hf_pi_fields(settle_default: int = 1800) -> list:
    """HyperFrames 由小 Pi 驱动的节点共用的工程/运行时设置。"""
    return [
        {
            "key": "project_dir", "label": "项目目录", "type": "text", "colSpan": "full",
            "placeholder": "留空则使用任务缓存下的 hyperframes_<节点id>",
            "description": "HyperFrames 工程目录；留空或目录为空时由节点自动初始化。上游 project_dir 端口优先于此处配置",
        },
        {"key": "update_skills", "label": "执行前刷新技能", "type": "checkbox", "colSpan": "half",
         "description": "执行前运行 npx hyperframes skills update，保证目标工作流技能已安装"},
        {"key": "skills_timeout", "label": "技能刷新超时(秒)", "type": "number", "min": 30, "max": 3600, "colSpan": "half"},
        {"key": "settle_timeout", "label": "智能体会话超时(秒)", "type": "number", "min": 60, "max": 7200, "colSpan": "half"},
        {"key": "cli_command", "label": "CLI 执行程序", "type": "text", "colSpan": "half", "placeholder": "npx"},
        {"key": "cli_package", "label": "CLI 包", "type": "text", "colSpan": "half", "placeholder": "hyperframes@latest"},
        {"key": "extra_instruction", "label": "补充要求", "type": "textarea", "colSpan": "full",
         "placeholder": "追加给智能体的要求，例如「不要用真实品牌 Logo」「控制在 45 秒内」"},
    ]


_HYPERFRAMES_NODES = [
    {
        "id": "hyperframes_creative",
        "name": "HyperFrames 创意",
        "execution_domain": "process",
        "category": "hyperframes",
        "description": (
            "两步走第一步：把 URL / 主题 / PR / 素材收敛成一份 BRIEF.md 创意简报；"
            "支持加载已有 BRIEF.md 稳定复用既有工作流，不重复做意图访谈"
        ),
        "icon": "Clapperboard",
        "color": "#f43f5e",
        "inputs": [
            {"id": "source", "label": "素材/主题", "type": "any", "required": False},
            {"id": "assets", "label": "附加素材", "type": "any", "required": False},
            {"id": "brief", "label": "已有 BRIEF.md", "type": "filepath", "required": False},
        ],
        "outputs": [
            {"id": "brief", "label": "BRIEF.md", "type": "filepath"},
            {"id": "project_dir", "label": "项目目录", "type": "filepath"},
            {"id": "summary", "label": "创意摘要", "type": "text"},
        ],
        "defaultConfig": {
            "mode": "create",
            "subject": "",
            "brief_path": "",
            "workflow": "",
            "run_mode": "collaborative",
            "style_preset": "",
            "aspect": "auto",
            "language": "",
            "project_dir": "",
            "update_skills": True,
            "skills_timeout": 600,
            "settle_timeout": 1800,
            "cli_command": "npx",
            "cli_package": "hyperframes@latest",
            "extra_instruction": "",
        },
        "configFields": [
            {
                "key": "mode", "label": "运行模式", "type": "select", "colSpan": "full",
                "options": [
                    {"value": "create", "label": "新建创意简报（走意图访谈）"},
                    {"value": "load", "label": "加载已有 BRIEF.md（复用既有工作流）"},
                ],
                "description": "加载模式不调用大模型，直接把已有简报装入项目目录并解析其中的工作流路由",
            },
            {
                "key": "brief_path", "label": "BRIEF.md 路径", "type": "file", "colSpan": "full",
                "fileFilter": ["md"], "placeholder": "选择已有的 BRIEF.md",
                "dependsOn": "mode", "dependsValue": "load",
            },
            {
                "key": "subject", "label": "创作主题", "type": "textarea", "colSpan": "full",
                "placeholder": "这段视频要讲什么？可以是一个主题、一段脚本、一个产品描述",
                "description": "留空时优先使用「素材/主题」端口传入的内联文本",
                "dependsOn": "mode", "dependsValue": "create",
            },
            {
                "key": "workflow", "label": "工作流路由", "type": "select", "colSpan": "full",
                "options": _HF_WORKFLOW_OPTIONS,
                "description": "留空则由意图访谈按输入自动路由；加载已有 BRIEF.md 时以简报里的 workflow 字段为准",
            },
            {
                "key": "run_mode", "label": "协作模式", "type": "select", "colSpan": "half",
                "options": [
                    {"value": "collaborative", "label": "协作（关键选择先确认）"},
                    {"value": "autonomous", "label": "自主（不再追问，直接产出）"},
                ],
                "dependsOn": "mode", "dependsValue": "create",
            },
            {
                "key": "aspect", "label": "画幅", "type": "select", "colSpan": "half",
                "options": _HF_ASPECT_OPTIONS,
                "dependsOn": "mode", "dependsValue": "create",
            },
            {
                "key": "style_preset", "label": "风格预设", "type": "text", "colSpan": "half",
                "placeholder": "留空由智能体按内容挑选",
                "dependsOn": "mode", "dependsValue": "create",
            },
            {
                "key": "language", "label": "旁白/字幕语言", "type": "text", "colSpan": "half",
                "placeholder": "留空跟随用户语言",
                "dependsOn": "mode", "dependsValue": "create",
            },
            *_hf_pi_fields(),
        ],
    },
    {
        "id": "hyperframes_render",
        "name": "HyperFrames 渲染",
        "execution_domain": "process",
        "category": "hyperframes",
        "description": (
            "两步走第二步：读取 BRIEF.md，按其中的工作流路由构建 HTML 合成并渲染成片；"
            "支持只构建 / 只渲染 / 只校验，可勾选渲染后 publish 出分享链接"
        ),
        "icon": "Film",
        "color": "#ef4444",
        "inputs": [
            {"id": "brief", "label": "BRIEF.md", "type": "filepath", "required": False},
            {"id": "project_dir", "label": "项目目录", "type": "filepath", "required": False},
            {"id": "assets", "label": "附加素材", "type": "any", "required": False},
        ],
        "outputs": [
            {"id": "video", "label": "成片", "type": "video"},
            {"id": "project_dir", "label": "项目目录", "type": "filepath"},
            {"id": "brief", "label": "BRIEF.md", "type": "filepath"},
            {"id": "url", "label": "发布链接", "type": "url"},
        ],
        "defaultConfig": {
            "stage": "build_and_render",
            "workflow": "",
            "brief_path": "",
            "output_name": "output.mp4",
            "output_path": "",
            "publish": False,
            "project_dir": "",
            "update_skills": True,
            "skills_timeout": 600,
            "settle_timeout": 3600,
            "cli_command": "npx",
            "cli_package": "hyperframes@latest",
            "extra_instruction": "",
        },
        "configFields": [
            {
                "key": "stage", "label": "执行阶段", "type": "select", "colSpan": "full",
                "options": [
                    {"value": "build_and_render", "label": "构建 + 渲染（默认）"},
                    {"value": "build", "label": "只构建合成，不渲染"},
                    {"value": "render", "label": "只对已有合成渲染"},
                    {"value": "validate", "label": "只校验（lint / check / validate）"},
                ],
            },
            {
                "key": "workflow", "label": "工作流路由", "type": "select", "colSpan": "full",
                "options": _HF_WORKFLOW_OPTIONS,
                "description": "留空则沿用 BRIEF.md 中记录的 workflow 字段",
            },
            {
                "key": "brief_path", "label": "BRIEF.md 路径", "type": "file", "colSpan": "full",
                "fileFilter": ["md"], "placeholder": "留空则读取项目目录或上游 brief 端口",
            },
            {"key": "output_name", "label": "成片文件名", "type": "text", "colSpan": "half", "placeholder": "output.mp4"},
            {"key": "output_path", "label": "成片查找路径", "type": "text", "colSpan": "half",
             "placeholder": "留空自动在 out/ dist/ render/ 等目录查找最新成片"},
            {"key": "publish", "label": "渲染后发布分享链接", "type": "checkbox", "colSpan": "full",
             "description": "勾选后渲染完成会执行 publish，链接从 url 端口输出"},
            *_hf_pi_fields(settle_default=3600),
        ],
    },
    {
        "id": "hyperframes_cli",
        "name": "HyperFrames 工具",
        "execution_domain": "process",
        "category": "hyperframes",
        "description": (
            "附属工具调用节点：直接在工作目录执行一条 HyperFrames CLI 命令，"
            "覆盖技能安装/体检、工程初始化、网站抓取、Registry 组件、关键帧诊断、校验、升级、预览、渲染与发布"
        ),
        "icon": "Wrench",
        "color": "#f59e0b",
        "inputs": [
            {"id": "project_dir", "label": "项目目录", "type": "filepath", "required": False},
            {"id": "input", "label": "附加输入", "type": "any", "required": False},
        ],
        "outputs": [
            {"id": "output", "label": "执行日志", "type": "filepath"},
            {"id": "stdout", "label": "输出文本", "type": "text"},
        ],
        "defaultConfig": {
            "command": "check",
            "args": "",
            "custom_args": "",
            "skill_names": "",
            "block": "",
            "url": "",
            "project_dir": "",
            "timeout": 1800,
            "cli_command": "npx",
            "cli_package": "hyperframes@latest",
        },
        "configFields": [
            {
                "key": "command", "label": "子命令", "type": "select", "colSpan": "full",
                "options": [
                    {"value": "init", "label": "init — 初始化工程"},
                    {"value": "skills_update", "label": "skills update — 安装/刷新技能"},
                    {"value": "skills_check", "label": "skills check — 技能体检"},
                    {"value": "add", "label": "add — 安装 Registry 组件"},
                    {"value": "capture", "label": "capture — 抓取网站"},
                    {"value": "keyframes", "label": "keyframes — 关键帧诊断"},
                    {"value": "lint", "label": "lint — 代码检查"},
                    {"value": "validate", "label": "validate — 结构校验"},
                    {"value": "check", "label": "check — 工程体检"},
                    {"value": "upgrade", "label": "upgrade — 升级工程 CLI 版本"},
                    {"value": "doctor", "label": "doctor — 环境诊断"},
                    {"value": "preview", "label": "preview — 启动预览"},
                    {"value": "render", "label": "render — 渲染成片"},
                    {"value": "publish", "label": "publish — 发布分享链接"},
                    {"value": "custom", "label": "custom — 自定义子命令"},
                ],
            },
            {"key": "skill_names", "label": "技能名称", "type": "text", "colSpan": "full",
             "placeholder": "空格或逗号分隔，留空只刷新核心技能集",
             "dependsOn": "command", "dependsValue": "skills_update"},
            {"key": "block", "label": "Registry 组件名", "type": "text", "colSpan": "full",
             "placeholder": "如 data-chart / device-mockup",
             "dependsOn": "command", "dependsValue": "add"},
            {"key": "url", "label": "目标网址", "type": "text", "colSpan": "full",
             "placeholder": "https://example.com",
             "dependsOn": "command", "dependsValue": "capture"},
            {"key": "custom_args", "label": "完整参数", "type": "textarea", "colSpan": "full",
             "placeholder": "直接填写子命令与参数，如：skills update pr-to-video figma",
             "dependsOn": "command", "dependsValue": "custom"},
            {"key": "args", "label": "附加参数", "type": "text", "colSpan": "full",
             "placeholder": "空格分隔，如：--json --concurrency 4",
             "dependsOn": "command", "dependsValue": ["init", "skills_update", "skills_check", "keyframes",
                                                      "lint", "validate", "check", "upgrade", "doctor",
                                                      "preview", "render", "publish"]},
            {"key": "project_dir", "label": "工作目录", "type": "text", "colSpan": "full",
             "placeholder": "留空则使用任务缓存下的 hyperframes_<节点id>",
             "description": "命令在此目录内执行；上游 project_dir 端口优先于此处配置"},
            {"key": "timeout", "label": "超时(秒)", "type": "number", "min": 30, "max": 21600, "colSpan": "half"},
            {"key": "cli_command", "label": "CLI 执行程序", "type": "text", "colSpan": "half", "placeholder": "npx"},
            {"key": "cli_package", "label": "CLI 包", "type": "text", "colSpan": "half", "placeholder": "hyperframes@latest"},
        ],
    },
    {
        "id": "hyperframes_agent",
        "name": "HyperFrames 智能体",
        "execution_domain": "process",
        "category": "hyperframes",
        "description": (
            "复合节点：直接驱动本项目的小 Pi（piagent）框架，一个节点跑完「创意 → 渲染」整条链路；"
            "检测到已有 BRIEF.md 时自动按加载模式复用既有工作流"
        ),
        "icon": "Bot",
        "color": "#a855f7",
        "inputs": [
            {"id": "source", "label": "素材/主题", "type": "any", "required": False},
            {"id": "assets", "label": "附加素材", "type": "any", "required": False},
            {"id": "brief", "label": "已有 BRIEF.md", "type": "filepath", "required": False},
        ],
        "outputs": [
            {"id": "video", "label": "成片", "type": "video"},
            {"id": "brief", "label": "BRIEF.md", "type": "filepath"},
            {"id": "project_dir", "label": "项目目录", "type": "filepath"},
            {"id": "text", "label": "执行摘要", "type": "text"},
        ],
        "defaultConfig": {
            "span": "full",
            "subject": "",
            "brief_path": "",
            "workflow": "",
            "run_mode": "collaborative",
            "style_preset": "",
            "aspect": "auto",
            "language": "",
            "stage": "build_and_render",
            "output_name": "output.mp4",
            "output_path": "",
            "publish": False,
            "project_dir": "",
            "update_skills": True,
            "skills_timeout": 600,
            "settle_timeout": 3600,
            "cli_command": "npx",
            "cli_package": "hyperframes@latest",
            "extra_instruction": "",
        },
        "configFields": [
            {
                "key": "span", "label": "执行跨度", "type": "select", "colSpan": "full",
                "options": [
                    {"value": "full", "label": "创意 + 渲染（完整链路）"},
                    {"value": "creative", "label": "只做创意"},
                    {"value": "render", "label": "只做渲染"},
                ],
            },
            {"key": "subject", "label": "创作主题", "type": "textarea", "colSpan": "full",
             "placeholder": "这段视频要讲什么？填写后即使存在旧简报也会先刷新创意",
             "dependsOn": "span", "dependsValue": ["full", "creative"]},
            {"key": "brief_path", "label": "已有 BRIEF.md 路径", "type": "file", "colSpan": "full",
             "fileFilter": ["md"], "placeholder": "选择已有的 BRIEF.md，命中即复用既有工作流",
             "description": "也可通过 brief 输入端口接入；两者任一命中就跳过意图访谈"},
            {
                "key": "workflow", "label": "工作流路由", "type": "select", "colSpan": "full",
                "options": _HF_WORKFLOW_OPTIONS,
                "description": "留空则由意图访谈自动路由，或沿用已有 BRIEF.md 里的 workflow 字段",
            },
            {
                "key": "run_mode", "label": "协作模式", "type": "select", "colSpan": "half",
                "options": [
                    {"value": "collaborative", "label": "协作（关键选择先确认）"},
                    {"value": "autonomous", "label": "自主（不再追问，直接产出）"},
                ],
                "dependsOn": "span", "dependsValue": ["full", "creative"],
            },
            {
                "key": "aspect", "label": "画幅", "type": "select", "colSpan": "half",
                "options": _HF_ASPECT_OPTIONS,
                "dependsOn": "span", "dependsValue": ["full", "creative"],
            },
            {
                "key": "style_preset", "label": "风格预设", "type": "text", "colSpan": "half",
                "placeholder": "留空由智能体按内容挑选",
                "dependsOn": "span", "dependsValue": ["full", "creative"],
            },
            {
                "key": "language", "label": "旁白/字幕语言", "type": "text", "colSpan": "half",
                "placeholder": "留空跟随用户语言",
                "dependsOn": "span", "dependsValue": ["full", "creative"],
            },
            {
                "key": "stage", "label": "渲染阶段", "type": "select", "colSpan": "full",
                "options": [
                    {"value": "build_and_render", "label": "构建 + 渲染（默认）"},
                    {"value": "build", "label": "只构建合成，不渲染"},
                    {"value": "render", "label": "只对已有合成渲染"},
                    {"value": "validate", "label": "只校验（lint / check / validate）"},
                ],
                "dependsOn": "span", "dependsValue": ["full", "render"],
            },
            {"key": "output_name", "label": "成片文件名", "type": "text", "colSpan": "half",
             "placeholder": "output.mp4",
             "dependsOn": "span", "dependsValue": ["full", "render"]},
            {"key": "output_path", "label": "成片查找路径", "type": "text", "colSpan": "half",
             "placeholder": "留空自动在 out/ dist/ render/ 等目录查找最新成片",
             "dependsOn": "span", "dependsValue": ["full", "render"]},
            {"key": "publish", "label": "渲染后发布分享链接", "type": "checkbox", "colSpan": "full",
             "dependsOn": "span", "dependsValue": ["full", "render"]},
            *_hf_pi_fields(settle_default=3600),
        ],
    },
]
BUILTIN_NODE_TYPES.extend(_HYPERFRAMES_NODES)


# ─────────────────────────────────────────────────────────────────────────────
# AIGC 流程链节点
# ─────────────────────────────────────────────────────────────────────────────
BUILTIN_NODE_TYPES.append(
    {
        "id": "image_grid_split",
        "name": "图片宫格切割",
        "execution_domain": "thread",
        "category": "aigc",
        "description": (
            "把宫格组合图按 N×N 切成单张图片：支持 4/9/16/25 宫格，"
            "可设置外框收缩与内部切缝收缩像素，输出切割后的图片路径列表"
        ),
        "icon": "Grid3x3",
        "color": "#22c55e",
        "inputs": [
            {"id": "image", "label": "图片", "type": "image", "required": True},
        ],
        "outputs": [
            {"id": "images", "label": "图片列表", "type": "list"},
        ],
        "defaultConfig": {
            "grid": "4",
            "outer_shrink": 0,
            "inner_shrink": 5,
        },
        "configFields": [
            {
                "key": "grid", "label": "宫格选择", "type": "select", "colSpan": "full",
                "options": [
                    {"value": "4", "label": "4宫格（2×2）"},
                    {"value": "9", "label": "9宫格（3×3）"},
                    {"value": "16", "label": "16宫格（4×4）"},
                    {"value": "25", "label": "25宫格（5×5）"},
                ],
            },
            {"key": "outer_shrink", "label": "外框收缩像素", "type": "number",
             "min": 0, "step": 1, "colSpan": "half", "defaultValue": 0,
             "description": "切割前整图四边向内收缩的像素，用于去掉图片外框，默认 0"},
            {"key": "inner_shrink", "label": "内部切割收缩像素", "type": "number",
             "min": 0, "step": 1, "colSpan": "half", "defaultValue": 5,
             "description": "每个内部切缝两侧各向内收缩的像素，用于去掉格间接缝；与图片外边缘重合的边不收缩，默认 5"},
        ],
    }
)

# ─────────────────────────────────────────────────────────────────────────────
# 视频处理节点
# ─────────────────────────────────────────────────────────────────────────────
BUILTIN_NODE_TYPES.append(
    {
        "id": "video_scale",
        "name": "视频缩放",
        "execution_domain": "thread",
        "category": "video",
        "description": (
            "使用 ffmpeg 将视频缩放到预置分辨率（按目标高度等比缩放）或自定义宽高，"
            "支持输出容器格式与编码质量（CRF）设置"
        ),
        "icon": "Ratio",
        "color": "#ef4444",
        "inputs": [
            {"id": "video", "label": "视频", "type": "video", "required": True},
        ],
        "outputs": [
            {"id": "video", "label": "缩放后视频", "type": "video"},
        ],
        "defaultConfig": {
            "scale_preset": "1080p",
            "custom_width": 1920,
            "custom_height": 1080,
            "output_format": "mp4",
            "video_quality": "medium",
        },
        "configFields": [
            {
                "key": "scale_preset", "label": "缩放尺寸", "type": "select", "colSpan": "full",
                "options": [
                    {"value": "original", "label": "保持原始分辨率"},
                    {"value": "2160p", "label": "4K（3840×2160）"},
                    {"value": "1440p", "label": "2K（2560×1440）"},
                    {"value": "1080p", "label": "1080P（1920×1080）"},
                    {"value": "720p", "label": "720P（1280×720）"},
                    {"value": "480p", "label": "480P（854×480）"},
                    {"value": "360p", "label": "360P（640×360）"},
                    {"value": "custom", "label": "自定义宽高"},
                ],
                "description": "预置档按目标高度等比缩放（宽度自动取偶），非 16:9 素材不变形；自定义档使用精确宽高",
            },
            {"key": "custom_width", "label": "自定义宽度(px)", "type": "number",
             "min": 16, "step": 1, "colSpan": "half", "defaultValue": 1920,
             "dependsOn": "scale_preset", "dependsValue": "custom"},
            {"key": "custom_height", "label": "自定义高度(px)", "type": "number",
             "min": 16, "step": 1, "colSpan": "half", "defaultValue": 1080,
             "dependsOn": "scale_preset", "dependsValue": "custom"},
            {
                "key": "output_format", "label": "输出格式", "type": "select", "colSpan": "half",
                "options": [
                    {"value": "mp4", "label": "MP4（H.264 + AAC）"},
                    {"value": "mkv", "label": "MKV（H.264 + AAC）"},
                    {"value": "mov", "label": "MOV（H.264 + AAC）"},
                    {"value": "flv", "label": "FLV（H.264 + AAC）"},
                    {"value": "webm", "label": "WebM（VP9 + Opus）"},
                    {"value": "avi", "label": "AVI（MPEG4 + MP3）"},
                ],
            },
            {
                "key": "video_quality", "label": "编码质量", "type": "select", "colSpan": "half",
                "options": [
                    {"value": "high", "label": "高质量（CRF 18）"},
                    {"value": "medium", "label": "中等（CRF 23）"},
                    {"value": "low", "label": "低质量（CRF 28）"},
                ],
            },
        ],
    }
)


BUILTIN_NODE_IDS = {node["id"] for node in BUILTIN_NODE_TYPES}
DELETED_BUILTIN_NODE_IDS_FILE = Path(__file__).parent / "deleted_builtin_node_ids.json"


def _deleted_builtin_node_ids() -> set[str]:
    try:
        with open(DELETED_BUILTIN_NODE_IDS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return set()
    return {node_id for node_id in data.get("node_ids", []) if node_id in BUILTIN_NODE_IDS}


def delete_builtin_node_type(node_id: str) -> bool:
    if node_id not in BUILTIN_NODE_IDS:
        return False
    deleted_ids = _deleted_builtin_node_ids()
    deleted_ids.add(node_id)
    temporary_path = DELETED_BUILTIN_NODE_IDS_FILE.with_suffix(".tmp")
    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump({"node_ids": sorted(deleted_ids)}, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary_path, DELETED_BUILTIN_NODE_IDS_FILE)
    return True


def is_builtin_node_type_deleted(node_id: str) -> bool:
    return node_id in _deleted_builtin_node_ids()


def get_builtin_node_types() -> list[dict]:
    """Return a defensive copy of built-in node definitions."""
    deleted_ids = _deleted_builtin_node_ids()
    return [deepcopy(node) for node in BUILTIN_NODE_TYPES if node["id"] not in deleted_ids]


def get_builtin_node_type(node_id: str) -> dict | None:
    """Get a built-in node definition by id."""
    if node_id in _deleted_builtin_node_ids():
        return None
    for node in BUILTIN_NODE_TYPES:
        if node["id"] == node_id:
            return deepcopy(node)
    return None

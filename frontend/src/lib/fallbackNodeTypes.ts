import type { NodeTypeDef } from './workflowTypes';

// Generated from backend/config/builtin_node_types.py as frontend fallback registry.
// Used only when backend node registry is temporarily unavailable.
export const FALLBACK_NODE_TYPES: NodeTypeDef[] = [
  {
    "id": "input",
    "name": "输入",
    "category": "input",
    "description": "导入文件或URL",
    "icon": "Upload",
    "color": "#3b82f6",
    "inputs": [],
    "outputs": [
      {
        "id": "video",
        "label": "视频",
        "type": "video"
      },
      {
        "id": "audio",
        "label": "音频",
        "type": "audio"
      },
      {
        "id": "subtitle",
        "label": "字幕",
        "type": "json"
      },
      {
        "id": "url",
        "label": "URL",
        "type": "url"
      },
      {
        "id": "filepath",
        "label": "文件路径",
        "type": "filepath"
      }
    ],
    "defaultConfig": {
      "selectedTypes": [
        "video"
      ],
      "videoPath": "",
      "audioPath": "",
      "subtitlePath": "",
      "url": "",
      "filePath": "",
      "source_language": "auto",
      "target_language": "zh",
      "copyInputs": true
    },
    "configFields": [
      {
        "key": "selectedTypes",
        "label": "输入方式",
        "type": "chips",
        "options": [
          {
            "value": "video",
            "label": "视频"
          },
          {
            "value": "audio",
            "label": "音频"
          },
          {
            "value": "subtitle",
            "label": "字幕"
          },
          {
            "value": "url",
            "label": "URL"
          },
          {
            "value": "filepath",
            "label": "文件路径"
          }
        ]
      },
      {
        "key": "videoPath",
        "label": "视频文件",
        "type": "file",
        "placeholder": "选择或输入视频文件路径",
        "dependsOn": "selectedTypes",
        "dependsAnyValues": [
          "video"
        ],
        "fileFilter": [
          "mp4",
          "avi",
          "mkv",
          "mov",
          "wmv",
          "flv",
          "webm"
        ]
      },
      {
        "key": "audioPath",
        "label": "音频文件",
        "type": "audio-selector",
        "placeholder": "选择或输入音频文件路径",
        "dependsOn": "selectedTypes",
        "dependsAnyValues": [
          "audio"
        ],
        "fileFilter": [
          "mp3",
          "wav",
          "flac",
          "aac",
          "ogg",
          "m4a"
        ]
      },
      {
        "key": "subtitlePath",
        "label": "字幕文件",
        "type": "file",
        "placeholder": "选择或输入字幕文件路径",
        "dependsOn": "selectedTypes",
        "dependsAnyValues": [
          "subtitle"
        ],
        "fileFilter": [
          "srt",
          "ass",
          "ssa",
          "sub",
          "txt"
        ]
      },
      {
        "key": "url",
        "label": "URL",
        "type": "text",
        "placeholder": "输入视频/音频URL地址",
        "dependsOn": "selectedTypes",
        "dependsAnyValues": [
          "url"
        ]
      },
      {
        "key": "filePath",
        "label": "文件路径",
        "type": "file",
        "placeholder": "选择或输入文件路径",
        "dependsOn": "selectedTypes",
        "dependsAnyValues": [
          "filepath"
        ]
      },
      {
        "key": "source_language",
        "label": "输入语言",
        "type": "language-select"
      },
      {
        "key": "target_language",
        "label": "输出语言",
        "type": "language-select"
      },
      {
        "key": "copyInputs",
        "label": "复制输入文件到任务缓存",
        "type": "checkbox"
      }
    ],
    "isBuiltIn": true
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
      {"id": "any", "label": "输入", "type": "any", "required": false}
    ],
    "outputs": [
      {"id": "text", "label": "文本", "type": "text"}
    ],
    "defaultConfig": {
      "text": ""
    },
    "configFields": [],
    "isBuiltIn": true
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
      {"id": "any", "label": "输入", "type": "any", "required": false}
    ],
    "outputs": [
      {"id": "filepath", "label": "文件路径", "type": "filepath"}
    ],
    "defaultConfig": {
      "filePath": ""
    },
    "configFields": [],
    "isBuiltIn": true
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
      {"id": "image", "label": "图片", "type": "image", "required": false}
    ],
    "outputs": [
      {"id": "image", "label": "蒙版合成图", "type": "image"},
      {"id": "mask", "label": "蒙版", "type": "image"}
    ],
    "defaultConfig": {
      "mask": {"strokes": [], "rects": [], "color": "#ff3b30", "alpha": 0.5}
    },
    "configFields": [],
    "isBuiltIn": true
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
      {"id": "prompt", "label": "提示词", "type": "text", "required": false},
      {"id": "images", "label": "图片/图片列表", "type": "image", "required": false},
      {"id": "audio", "label": "音频", "type": "audio", "required": false}
    ],
    "outputs": [
      {"id": "videos", "label": "视频", "type": "video"},
      {"id": "video", "label": "视频(首个)", "type": "video"}
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
      "optimize_prompt": true,
      "poll_timeout": 1800
    },
    "configFields": [],
    "isBuiltIn": true
  },
  {
    "id": "ai_subtitle_correct",
    "name": "AI字幕纠错",
    "execution_domain": "llm",
    "category": "ai_gen",
    "description": "读取 ASR JSON，按字数上限切分后请求 LLM（vlf-02）修复识别错误、去除空格并修正标点；专有名词可辅助识别。prompt 可在 Prompt 工程中修改。",
    "icon": "Sparkles",
    "color": "#10b981",
    "inputs": [
      {"id": "json", "label": "ASR JSON", "type": "json", "required": false, "color": "#6366f1"}
    ],
    "outputs": [
      {"id": "output", "label": "ASR JSON", "type": "json", "color": "#6366f1"},
      {"id": "text", "label": "纠错全文TXT", "type": "text", "color": "#8b5cf6"}
    ],
    "defaultConfig": {
      "maxChars": "2000",
      "properNouns": ""
    },
    "configFields": [],
    "isBuiltIn": true
  },
  {
    "id": "path_to_title",
    "name": "路径转标题",
    "category": "utility",
    "description": "从文件路径提取组件并拼装标题",
    "icon": "FileText",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "any",
        "label": "输入",
        "type": "any",
        "required": false
      }
    ],
    "outputs": [
      {
        "id": "text",
        "label": "标题",
        "type": "text"
      }
    ],
    "defaultConfig": {
      "template": "{filename}",
      "read_from_input": false,
      "update_task_name": false
    },
    "configFields": [
      {
        "key": "read_from_input",
        "label": "读取输入文件路径",
        "type": "checkbox",
        "description": "勾选后直接读取输入节点的文件路径作为解析路径",
        "colSpan": "full"
      },
      {
        "key": "template",
        "label": "标题模板",
        "type": "text",
        "placeholder": "使用 {filename} {parent} {grandparent} 占位符",
        "colSpan": "full",
        "description": "点击下方标签插入占位符到模板中"
      },
      {
        "key": "update_task_name",
        "label": "同时命名任务名",
        "type": "checkbox",
        "description": "勾选后将拼接结果写入 task.json 的 task_name 字段",
        "colSpan": "full"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "file_rename",
    "name": "文件改名",
    "category": "utility",
    "description": "给输入文件改名，支持自定义文件名、前缀、后缀方式",
    "icon": "FileEdit",
    "color": "#f97316",
    "inputs": [
      {
        "id": "any",
        "label": "输入",
        "type": "any",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "any",
        "label": "输出",
        "type": "any"
      }
    ],
    "defaultConfig": {
      "rename_mode": "suffix",
      "custom_name": "",
      "prefix": "",
      "suffix": ""
    },
    "configFields": [
      {
        "key": "rename_mode",
        "label": "改名方式",
        "type": "select",
        "options": [
          {
            "value": "custom",
            "label": "自定义文件名"
          },
          {
            "value": "prefix",
            "label": "添加前缀"
          },
          {
            "value": "suffix",
            "label": "添加后缀"
          }
        ]
      },
      {
        "key": "custom_name",
        "label": "自定义文件名",
        "type": "text",
        "placeholder": "输入新文件名（不含扩展名）",
        "dependsOn": "rename_mode",
        "dependsValue": "custom"
      },
      {
        "key": "prefix",
        "label": "前缀",
        "type": "text",
        "placeholder": "添加到文件名前面",
        "dependsOn": "rename_mode",
        "dependsValue": "prefix"
      },
      {
        "key": "suffix",
        "label": "后缀",
        "type": "text",
        "placeholder": "添加到文件名后面",
        "dependsOn": "rename_mode",
        "dependsValue": "suffix"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "platform_download",
    "name": "平台视频下载",
    "category": "process",
    "description": "使用 yt-dlp 下载平台视频",
    "icon": "Download",
    "color": "#06b6d4",
    "inputs": [
      {
        "id": "url",
        "label": "URL",
        "type": "url",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "video",
        "label": "视频",
        "type": "video"
      },
      {
        "id": "subtitle",
        "label": "字幕",
        "type": "subtitle"
      },
      {
        "id": "image",
        "label": "封面",
        "type": "image"
      }
    ],
    "defaultConfig": {
      "download_subs": false,
      "download_cover": false,
      "resolution": "best",
      "cookie_file": "",
      "use_as_task_name": false
    },
    "configFields": [
      {
        "key": "download_subs",
        "label": "下载字幕",
        "type": "checkbox"
      },
      {
        "key": "download_cover",
        "label": "下载封面",
        "type": "checkbox"
      },
      {
        "key": "use_as_task_name",
        "label": "记录为任务名称",
        "type": "checkbox",
        "colSpan": "full"
      },
      {
        "key": "resolution",
        "label": "下载分辨率",
        "type": "select",
        "options": [
          {
            "value": "best",
            "label": "最佳质量"
          },
          {
            "value": "1080p",
            "label": "1080P"
          },
          {
            "value": "720p",
            "label": "720P"
          }
        ]
      },
      {
        "key": "cookie_file",
        "label": "Cookie 文件",
        "type": "file",
        "placeholder": "选择 cookie.txt 文件（可选）",
        "fileFilter": [
          "txt"
        ]
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "extract_audio",
    "name": "音频分离",
    "category": "process",
    "description": "从视频中分离提取音频",
    "icon": "Music",
    "color": "#10b981",
    "inputs": [
      {
        "id": "video",
        "label": "视频",
        "type": "video",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "音频",
        "type": "audio"
      }
    ],
    "defaultConfig": {},
    "configFields": [],
    "isBuiltIn": true
  },
  {
    "id": "vocal_separation",
    "name": "人声分离",
    "category": "process",
    "description": "将音频中的人声和背景音乐分离",
    "icon": "Mic2",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "audio",
        "label": "音频",
        "type": "audio",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "人声",
        "type": "audio",
        "color": "#10b981"
      },
      {
        "id": "background",
        "label": "背景音乐",
        "type": "audio",
        "color": "#f59e0b"
      }
    ],
    "defaultConfig": {
      "method": "spleeter",
      "model": "",
      "format": "wav"
    },
    "configFields": [
      {
        "key": "method",
        "label": "分离接口",
        "type": "api-select",
        "apiEndpoint": "/api/separation-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id",
        "colSpan": "full"
      },
      {
        "key": "model",
        "label": "分离模型",
        "type": "api-select",
        "apiEndpoint": "/api/separation-interfaces/config-fields",
        "dependsOn": "method",
        "optionLabel": "label",
        "optionValue": "value",
        "placeholder": "留空则使用接口默认模型",
        "colSpan": "full"
      },
      {
        "key": "format",
        "label": "输出格式",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "wav",
            "label": "WAV (无损)"
          },
          {
            "value": "mp3",
            "label": "MP3"
          }
        ]
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "track_separation",
    "name": "音轨分离",
    "category": "process",
    "description": "将音频分离为6轨：人声/贝斯/鼓/吉他/钢琴/其他",
    "icon": "Music2",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "audio",
        "label": "音频",
        "type": "audio",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "vocals",
        "label": "人声",
        "type": "audio"
      },
      {
        "id": "bass",
        "label": "贝斯",
        "type": "audio"
      },
      {
        "id": "drums",
        "label": "鼓",
        "type": "audio"
      },
      {
        "id": "guitar",
        "label": "吉他",
        "type": "audio"
      },
      {
        "id": "piano",
        "label": "钢琴",
        "type": "audio"
      },
      {
        "id": "other",
        "label": "其他",
        "type": "audio"
      }
    ],
    "defaultConfig": {
      "method": "demucs",
      "model": "htdemucs_6s",
      "format": "wav"
    },
    "configFields": [
      {
        "key": "method",
        "label": "分离接口",
        "type": "api-select",
        "apiEndpoint": "/api/separation-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id",
        "colSpan": "full"
      },
      {
        "key": "model",
        "label": "分离模型",
        "type": "api-select",
        "apiEndpoint": "/api/separation-interfaces/config-fields",
        "dependsOn": "method",
        "optionLabel": "label",
        "optionValue": "value",
        "placeholder": "留空则使用接口默认模型",
        "colSpan": "full"
      },
      {
        "key": "format",
        "label": "输出格式",
        "type": "select",
        "options": [
          {
            "value": "wav",
            "label": "WAV (无损)"
          },
          {
            "value": "mp3",
            "label": "MP3"
          }
        ]
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "audio_transcode",
    "name": "音频质量转码",
    "category": "process",
    "description": "转换音频格式、采样率、位深、声道和码率",
    "icon": "AudioLines",
    "color": "#0ea5e9",
    "inputs": [
      {"id": "audio", "label": "音频", "type": "audio", "required": true}
    ],
    "outputs": [
      {"id": "audio", "label": "转码音频", "type": "audio"}
    ],
    "defaultConfig": {
      "format": "wav",
      "sample_rate": "",
      "bit_depth": "",
      "channels": "",
      "bitrate": ""
    },
    "configFields": [
      {
        "key": "format",
        "label": "输出格式",
        "type": "select",
        "options": [
          {"value": "wav", "label": "WAV (无损)"},
          {"value": "mp3", "label": "MP3"},
          {"value": "flac", "label": "FLAC (无损)"},
          {"value": "m4a", "label": "M4A"}
        ]
      },
      {
        "key": "sample_rate",
        "label": "采样率",
        "type": "select",
        "colSpan": "half",
        "options": [
          {"value": "", "label": "跟随全局设置"},
          {"value": "16000", "label": "16000 Hz ★推荐（语音识别/ASR）"},
          {"value": "44100", "label": "44100 Hz ★推荐（标准/人声分离）"},
          {"value": "48000", "label": "48000 Hz"}
        ]
      },
      {
        "key": "bit_depth",
        "label": "位深",
        "type": "select",
        "colSpan": "half",
        "options": [
          {"value": "", "label": "跟随全局设置"},
          {"value": "16", "label": "16 bit ★推荐"},
          {"value": "24", "label": "24 bit"}
        ]
      },
      {
        "key": "channels",
        "label": "声道",
        "type": "select",
        "colSpan": "half",
        "options": [
          {"value": "", "label": "跟随全局设置"},
          {"value": "1", "label": "单声道 ★推荐（语音）"},
          {"value": "2", "label": "立体声"}
        ]
      },
      {
        "key": "bitrate",
        "label": "码率 (kbps)",
        "type": "select",
        "colSpan": "half",
        "options": [
          {"value": "", "label": "跟随全局设置"},
          {"value": "128", "label": "128 kbps"},
          {"value": "192", "label": "192 kbps ★推荐"},
          {"value": "256", "label": "256 kbps"},
          {"value": "320", "label": "320 kbps"}
        ]
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "asr",
    "name": "语音识别 (ASR)",
    "category": "ai",
    "description": "从音频/视频中提取文字，支持 WhisperX / Qwen3-ASR 等引擎",
    "icon": "Mic",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "asr_audio",
        "label": "ASR音源",
        "type": "audio",
        "required": true
      },
      {
        "id": "vocal_audio",
        "label": "人声音源",
        "type": "audio",
        "required": false
      },
      {
        "id": "alignment_audio",
        "label": "时间戳对齐音频",
        "type": "audio",
        "required": false
      }
    ],
    "outputs": [
      {
        "id": "subtitle",
        "label": "ASR结果JSON",
        "type": "subtitle"
      }
    ],
    "defaultConfig": {
        "engine": "",
        "language": "auto",
        "model": "",
        "compute_type": "",
        "batch_size": 0,
        "word_timestamps": true,
        "vad_onset": 0.5,
        "vad_offset": 0.363,
        "hotwords_enabled": false,
        "hotwords": ""
      },
      "configFields": [
        {
          "key": "engine",
          "label": "ASR 引擎",
          "type": "api-select",
          "colSpan": "half",
          "apiEndpoint": "/api/asr-interfaces/enabled",
          "placeholder": "跟随全局配置"
        },
        {
          "key": "language",
          "label": "识别语言",
          "type": "select",
          "colSpan": "half",
          "placeholder": "跟随输入节点",
          "options": [
            {
              "value": "from_input",
              "label": "来自输入节点"
            },
            {
              "value": "auto",
              "label": "自动检测 (auto)"
            },
            {
              "value": "zh",
              "label": "中文 (zh)"
            },
            {
              "value": "en",
              "label": "英语 (en)"
            },
            {
              "value": "ja",
              "label": "日语 (ja)"
            },
            {
              "value": "ko",
              "label": "韩语 (ko)"
            },
            {
              "value": "fr",
              "label": "法语 (fr)"
            },
            {
              "value": "de",
              "label": "德语 (de)"
            },
            {
              "value": "es",
              "label": "西班牙语 (es)"
            },
            {
              "value": "pt",
              "label": "葡萄牙语 (pt)"
            },
            {
              "value": "ru",
              "label": "俄语 (ru)"
            }
          ]
        },
        {
          "key": "model",
          "label": "模型",
          "type": "api-select",
          "colSpan": "half",
          "apiEndpoint": "/api/asr-interfaces/models",
          "dependsOn": "engine",
          "placeholder": "默认"
        },
        {
          "key": "compute_type",
          "label": "计算精度",
          "type": "api-select",
          "colSpan": "half",
          "apiEndpoint": "/api/asr-interfaces/config-fields",
          "dependsOn": "engine",
          "placeholder": "跟随全局配置"
        },
        {
          "key": "batch_size",
          "label": "批处理大小",
          "type": "text",
          "colSpan": "half",
          "placeholder": "0=自动检测GPU显存"
        },
        {
          "key": "word_timestamps",
          "label": "启用词级时间戳对齐",
          "type": "checkbox",
          "colSpan": "half"
        },
        {
          "key": "vad_onset",
          "label": "VAD 起始阈值",
          "type": "text",
          "colSpan": "half",
          "placeholder": "0.500"
        },
        {
          "key": "vad_offset",
          "label": "VAD 结束阈值",
          "type": "text",
          "colSpan": "half",
          "placeholder": "0.363"
        },
        {
          "key": "hotwords_enabled",
          "label": "附加热词",
          "type": "checkbox",
          "colSpan": "half"
        },
        {
          "key": "hotwords",
          "label": "热词",
          "type": "hotwords",
          "colSpan": "half",
          "dependsOn": "hotwords_enabled",
          "placeholder": "多个热词用;分隔，或点击右侧按钮加载txt文件"
        }
      ],
    "isBuiltIn": true
  },
  {
    "id": "sentence_split",
    "name": "句子分割",
    "category": "ai",
    "description": "将ASR结果按标点和长度分割为独立句子，保留单词级时间戳",
    "icon": "Scissors",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "subtitle",
        "label": "ASR结果JSON",
        "type": "json",
        "required": true,
        "color": "#6366f1"
      }
    ],
    "outputs": [
      {
        "id": "subtitle",
        "label": "分割结果JSON",
        "type": "json",
        "color": "#6366f1"
      },
      {
        "id": "text",
        "label": "句子文本",
        "type": "text",
        "color": "#8b5cf6"
      }
    ],
    "defaultConfig": {
      "processing_language": "from_input",
      "max_sentence_length": 30,
      "use_llm_split": true,
      "split_sentence_ends": true,
      "split_clause_breaks": true,
      "merge_min_duration": 0.5,
      "merge_max_gap": 0.5,
      "pause_split_threshold": 1.0,
      "split_on_speaker": false,
      "merge_short_enabled": true,
      "merge_gap_enabled": true,
      "pause_split_enabled": true
    },
    "configFields": [
      {
        "key": "processing_language",
        "label": "处理语言",
        "type": "select",
        "options": [
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
          {"value": "ru", "label": "俄语 (ru)"}
        ]
      },
      {
        "key": "max_sentence_length",
        "label": "最大句子长度（以中文长度基准设置，其他语言自动按照权重调整）",
        "type": "text",
        "placeholder": "默认 30"
      },
      {
        "key": "split_sentence_ends",
        "label": "句末类标点切割",
        "type": "checkbox",
        "colSpan": "half",
        "hint": "按句末标点切割所有句子"
      },
      {
        "key": "split_clause_breaks",
        "label": "句中类标点切割",
        "type": "checkbox",
        "colSpan": "half",
        "hint": "按句中标点继续切割过长句子"
      },
      {
        "key": "split_on_speaker",
        "label": "说话人切换时切割",
        "type": "checkbox",
        "hint": "仅当 ASR 含多说话人时生效；单人视频无副作用"
      },
      {
        "key": "use_llm_split",
        "label": "AI兜底切割长句",
        "type": "checkbox"
      },
      {
        "key": "merge_min_duration",
        "label": "合并过短词句阈值(秒)",
        "type": "text",
        "placeholder": "默认 1.0",
        "colSpan": "half"
      },
      {
        "key": "merge_short_enabled",
        "label": "执行",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "merge_max_gap",
        "label": "句子间隔小于*秒合并(秒)",
        "type": "text",
        "placeholder": "默认 0.5",
        "colSpan": "half"
      },
      {
        "key": "merge_gap_enabled",
        "label": "执行",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "pause_split_threshold",
        "label": "停顿大于*秒断句(秒)",
        "type": "text",
        "placeholder": "默认 2.0",
        "colSpan": "half"
      },
      {
        "key": "pause_split_enabled",
        "label": "执行",
        "type": "checkbox",
        "colSpan": "half"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "summarize",
    "name": "内容总结",
    "category": "ai",
    "description": "总结上下文、提取术语表",
    "icon": "Brain",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "text",
        "label": "句子文本",
        "type": "text",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "subtitle",
        "label": "总结结果JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "summary_length": 3000,
      "use_custom_terminology": false,
      "custom_terminology_file": ""
    },
    "configFields": [
      {
        "key": "summary_length",
        "label": "总结文本长度",
        "type": "text",
        "placeholder": "默认 3000 字符"
      },
      {
        "key": "use_custom_terminology",
        "label": "自定义术语表",
        "type": "toggle",
        "defaultValue": false,
        "description": "勾选后加载自定义术语表JSON文件，与AI提取的术语合并"
      },
      {
        "key": "custom_terminology_file",
        "label": "术语表JSON文件",
        "type": "file",
        "placeholder": "选择术语表JSON文件",
        "fileFilter": ["*.json"]
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "translate",
    "name": "逐句翻译",
    "category": "ai",
    "description": "AI驱动的高质量翻译",
    "icon": "Languages",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "subtitle",
        "label": "切割句子JSON",
        "type": "json",
        "required": true
      },
      {
        "id": "summary",
        "label": "总结结果JSON",
        "type": "json"
      }
    ],
    "outputs": [
      {
        "id": "subtitle",
        "label": "直译结果JSON",
        "type": "subtitle",
        "color": "#3b82f6"
      },
      {
        "id": "reflect",
        "label": "反思翻译JSON",
        "type": "json",
        "color": "#10b981"
      }
    ],
    "defaultConfig": {
      "processing_language": "from_input",
      "batch_char_limit": "",
      "reflect_translate": "follow_global",
      "translation_style": ""
    },
    "configFields": [
      {
        "key": "processing_language",
        "label": "处理语言",
        "type": "select",
        "options": [
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
          {"value": "ru", "label": "俄语 (ru)"}
        ]
      },
      {
        "key": "batch_char_limit",
        "label": "单批次请求字数上限",
        "type": "text",
        "placeholder": "留空则读取全局LLM字数限制"
      },
      {
        "key": "reflect_translate",
        "label": "是否反思翻译",
        "type": "select",
        "options": [
          {
            "value": "follow_global",
            "label": "跟随全局设置"
          },
          {
            "value": "yes",
            "label": "是"
          },
          {
            "value": "no",
            "label": "否"
          }
        ]
      },
      {
        "key": "translation_style",
        "label": "翻译风格",
        "type": "text",
        "placeholder": "留空则使用全局设置"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "subtitle_gen",
    "name": "字幕生成",
    "category": "ai",
    "description": "兼容句子分割、逐句翻译、双语对齐结果并生成字幕文件",
    "icon": "FileText",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "subtitle",
        "label": "句子/翻译/对齐JSON",
        "type": "json",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "subtitle",
        "label": "译文字幕",
        "type": "subtitle"
      },
      {
        "id": "original",
        "label": "原文字幕",
        "type": "subtitle"
      },
      {
        "id": "bilingual",
        "label": "双语字幕",
        "type": "subtitle"
      }
    ],
    "defaultConfig": {
      "file_prefix": "",
      "filter_punctuation": false,
      "punctuation_replace_mode": "space"
    },
    "configFields": [
      {
        "key": "file_prefix",
        "label": "文件名前缀",
        "type": "text",
        "placeholder": "可选，如 video1_"
      },
      {
        "key": "filter_punctuation",
        "label": "是否过滤标点",
        "type": "checkbox"
      },
      {
        "key": "punctuation_replace_mode",
        "label": "标点替换模式",
        "type": "select",
        "dependsOn": "filter_punctuation",
        "options": [
          {
            "value": "space",
            "label": "空格"
          },
          {
            "value": "remove",
            "label": "去除"
          }
        ]
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "dub_task",
    "name": "生成配音任务",
    "category": "ai",
    "description": "将带时间戳的句子 JSON 包装为可编辑的 TTS 任务单",
    "icon": "Mic2",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "subtitle",
        "label": "句子时间戳JSON",
        "type": "json",
        "required": false
      },
      {
        "id": "text_file",
        "label": "文本文件",
        "type": "text",
        "required": false
      }
    ],
    "outputs": [
      {
        "id": "text",
        "label": "TTS任务单JSON",
        "type": "json"
      },
      {
        "id": "pandas",
        "label": "TTS任务表",
        "type": "pandas"
      }
    ],
    "defaultConfig": {
      "ai_read_tone": false,
      "normalize_chinese_read_text": false,
      "ai_dialect_colloquial": false,
      "dialect_name": "四川话"
    },
    "configFields": [
      {
        "key": "ai_read_tone",
        "label": "AI设计朗读语气",
        "type": "checkbox",
        "description": "启用后由 LLM 为每句补充朗读情绪语气描述"
      },
      {
        "key": "normalize_chinese_read_text",
        "label": "中文朗读文本归一化",
        "type": "checkbox",
        "description": "仅在目标朗读语言为中文时生效，将数字、单位、符号等规范化为汉字读法"
      },
      {
        "key": "ai_dialect_colloquial",
        "label": "AI方言口语化",
        "type": "checkbox",
        "description": "启用后由 LLM 按方言特色改写朗读文本"
      },
      {
        "key": "dialect_name",
        "label": "方言",
        "type": "text",
        "placeholder": "四川话",
        "dependsOn": "ai_dialect_colloquial",
        "description": "填写目标方言名称，启用方言口语化时写入任务单“方言”列"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "tts",
    "name": "语音合成 (TTS)",
    "category": "ai_gen",
    "description": "文本转语音，支持多种TTS模式",
    "icon": "Volume2",
    "color": "#10b981",
    "inputs": [
      {
        "id": "text",
        "label": "TTS任务单JSON",
        "type": "json",
        "required": true
      },
      {
        "id": "pandas",
        "label": "TTS任务表",
        "type": "pandas"
      },
      {
        "id": "source_audio",
        "label": "原始音频(切割参考)",
        "type": "audio"
      }
    ],
    "outputs": [
      {
        "id": "audio_manifest",
        "label": "配音任务清单",
        "type": "json"
      },
      {
        "id": "text",
        "label": "TTS任务单JSON",
        "type": "json"
      },
      {
        "id": "pandas",
        "label": "TTS任务表",
        "type": "pandas"
      }
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
      "speed_regenerate": true,
      "speed_rounds": 1,
      "ai_subtitle_reduction": true,
      "ai_rounds": 1,
      "overwrite_generate": false
    },
    "configFields": [
      {
        "key": "tts_mode",
        "label": "TTS 模式",
        "type": "chips",
        "singleSelect": true,
        "chipColor": "#10b981",
        "options": [
          {
            "value": "preset_voice",
            "label": "预置角色"
          },
          {
            "value": "clone",
            "label": "克隆"
          },
          {
            "value": "controllable_clone",
            "label": "指令克隆"
          },
          {
            "value": "voice_design",
            "label": "音色设计"
          }
        ]
      },
      {
        "key": "tts_engine",
        "label": "配音引擎",
        "type": "api-select",
        "dependsOn": "tts_mode",
        "apiEndpoint": "/api/tts-interfaces/by-mode/{tts_mode}",
        "placeholder": "跟随全局配置",
        "optionLabel": "name",
        "optionValue": "id"
      },
      {
        "key": "clone_source",
        "label": "克隆音频来源",
        "type": "select",
        "dependsOn": "tts_mode",
        "dependsAnyValues": ["clone", "controllable_clone"],
        "options": [
          {
            "value": "fixed",
            "label": "固定克隆音频"
          },
          {
            "value": "multi_role",
            "label": "多角色模式"
          },
          {
            "value": "per_segment",
            "label": "原文逐段参考"
          }
        ]
      },
      {
        "key": "ref_audio_path",
        "label": "参考音频路径",
        "type": "audio-selector",
        "dependsOn": "clone_source",
        "dependsValue": "fixed",
        "placeholder": "选择参考音频文件",
        "fileFilter": ["wav", "mp3", "flac", "ogg"]
      },
      {
        "key": "cc_colloquial_desc",
        "label": "口语化描述",
        "type": "text",
        "dependsOn": "tts_mode",
        "dependsAnyValues": ["controllable_clone"],
        "placeholder": "例如：用四川话说",
        "colSpan": "full",
        "description": "拼接在可控克隆指令最前面，自动补逗号分隔；留空不拼接"
      },
      {
        "key": "ref_audio_role_1",
        "label": "角色1参考音频",
        "type": "audio-selector",
        "dependsOn": "clone_source",
        "dependsValue": "multi_role",
        "placeholder": "角色1的参考音频",
        "fileFilter": ["wav", "mp3", "flac", "ogg"]
      },
      {
        "key": "ref_audio_role_2",
        "label": "角色2参考音频",
        "type": "audio-selector",
        "dependsOn": "clone_source",
        "dependsValue": "multi_role",
        "placeholder": "角色2的参考音频",
        "fileFilter": ["wav", "mp3", "flac", "ogg"]
      },
      {
        "key": "ref_audio_role_3",
        "label": "角色3参考音频",
        "type": "audio-selector",
        "dependsOn": "clone_source",
        "dependsValue": "multi_role",
        "placeholder": "角色3的参考音频",
        "fileFilter": ["wav", "mp3", "flac", "ogg"]
      },
      {
        "key": "ref_audio_role_4",
        "label": "角色4参考音频",
        "type": "audio-selector",
        "dependsOn": "clone_source",
        "dependsValue": "multi_role",
        "placeholder": "角色4的参考音频",
        "fileFilter": ["wav", "mp3", "flac", "ogg"]
      },
      {
        "key": "voice_role_1",
        "label": "朗读者1音色",
        "type": "voice-select",
        "interfaceIdKey": "tts_engine",
        "dependsOn": "tts_mode",
        "dependsAnyValues": ["preset_voice"],
        "description": "为角色1选择预置音色，点击打开音色选择面板",
      },
      {
        "key": "voice_role_2",
        "label": "朗读者2音色",
        "type": "voice-select",
        "interfaceIdKey": "tts_engine",
        "dependsOn": "tts_mode",
        "dependsAnyValues": ["preset_voice"],
        "description": "为角色2选择预置音色，点击打开音色选择面板",
      },
      {
        "key": "voice_role_3",
        "label": "朗读者3音色",
        "type": "voice-select",
        "interfaceIdKey": "tts_engine",
        "dependsOn": "tts_mode",
        "dependsAnyValues": ["preset_voice"],
        "description": "为角色3选择预置音色，点击打开音色选择面板",
      },
      {
        "key": "voice_role_4",
        "label": "朗读者4音色",
        "type": "voice-select",
        "interfaceIdKey": "tts_engine",
        "dependsOn": "tts_mode",
        "dependsAnyValues": ["preset_voice"],
        "description": "为角色4选择预置音色，点击打开音色选择面板",
      },
      {
        "key": "voice_design_role_1_desc",
        "label": "角色1音色描述",
        "type": "text",
        "dependsOn": "tts_mode",
        "dependsAnyValues": ["voice_design"],
        "placeholder": "描述角色1的音色特征"
      },
      {
        "key": "voice_design_role_2_desc",
        "label": "角色2音色描述",
        "type": "text",
        "dependsOn": "tts_mode",
        "dependsAnyValues": ["voice_design"],
        "placeholder": "描述角色2的音色特征"
      },
      {
        "key": "voice_design_role_3_desc",
        "label": "角色3音色描述",
        "type": "text",
        "dependsOn": "tts_mode",
        "dependsAnyValues": ["voice_design"],
        "placeholder": "描述角色3的音色特征"
      },
      {
        "key": "voice_design_role_4_desc",
        "label": "角色4音色描述",
        "type": "text",
        "dependsOn": "tts_mode",
        "dependsAnyValues": ["voice_design"],
        "placeholder": "描述角色4的音色特征"
      },
      {
        "key": "speed_regenerate",
        "label": "调速重生成",
        "type": "toggle",
        "defaultValue": true,
        "description": "配音后检查时长是否超出允许倍率，超出则带speed参数重新配音"
      },
      {
        "key": "speed_rounds",
        "label": "调速轮次",
        "type": "number",
        "defaultValue": 1,
        "min": 0,
        "max": 5,
        "step": 1,
        "inline": true,
        "description": "调速重生成的执行轮次，每轮都会重新检查并调整超出时间槽的配音"
      },
      {
        "key": "ai_subtitle_reduction",
        "label": "AI缩减字幕兜底",
        "type": "toggle",
        "defaultValue": true,
        "description": "调速重配后仍超时长的句子，调用LLM缩减朗读文本并重新配音"
      },
      {
        "key": "ai_rounds",
        "label": "缩减轮次",
        "type": "number",
        "defaultValue": 1,
        "min": 0,
        "max": 5,
        "step": 1,
        "inline": true,
        "description": "AI缩减字幕的执行轮次，每轮都会重新检查并缩减超出时间槽的文本"
      },
      {
        "key": "overwrite_generate",
        "label": "覆盖已有音频",
        "type": "toggle",
        "defaultValue": false,
        "description": "勾选后即使音频文件已存在也会重新生成，不勾选则跳过已存在的音频"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "merge_sub_video",
    "name": "字幕烧录",
    "category": "process",
    "description": "将字幕烧录到视频",
    "icon": "Film",
    "color": "#3b82f6",
    "inputs": [
      {
        "id": "video",
        "label": "视频",
        "type": "video",
        "required": true
      },
      {
        "id": "subtitle",
        "label": "字幕",
        "type": "subtitle",
        "required": true
      },
      {
        "id": "audio",
        "label": "背景音乐",
        "type": "audio"
      },
      {
        "id": "dub",
        "label": "配音音频",
        "type": "audio"
      }
    ],
    "outputs": [
      {
        "id": "video",
        "label": "字幕视频",
        "type": "video"
      }
    ],
    "defaultConfig": {
      "video_quality": "medium",
      "mute_original": false,
      "bgm_volume": 0.3,
      "dub_volume": 0.8,
      "fade_in": 0.5,
      "fade_out": 0.5
    },
    "configFields": [
      {
        "key": "preset_id",
        "label": "字幕样式预设",
        "type": "api-select",
        "apiUrl": "/api/subtitle-presets",
        "optionLabel": "name",
        "optionValue": "name",
        "description": "选择字幕样式预设，留空使用全局配置"
      },
      {
        "key": "mute_original",
        "label": "原视频静音",
        "type": "checkbox",
        "colSpan": "half",
        "description": "烧录字幕时是否将原视频音频静音"
      },
      {
        "key": "video_quality",
        "label": "视频质量",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "label": "原始质量(copy)",
            "value": "copy"
          },
          {
            "label": "高质量(CRF18)",
            "value": "high"
          },
          {
            "label": "中等(CRF23)",
            "value": "medium"
          },
          {
            "label": "低质量(CRF28)",
            "value": "low"
          }
        ],
        "description": "视频编码质量，copy为原始质量（有字幕时自动回退到中等）"
      },
      {
        "key": "bgm_path",
        "label": "BGM 路径",
        "type": "text",
        "description": "背景音乐文件路径，留空则不混入BGM"
      },
      {
        "key": "dub_path",
        "label": "配音路径",
        "type": "text",
        "description": "配音音频文件路径，留空则不混入配音"
      },
      {
        "key": "bgm_volume",
        "label": "BGM 音量",
        "type": "slider",
        "colSpan": "half",
        "min": 0,
        "max": 1,
        "step": 0.05,
        "description": "背景音乐音量 (0~1)"
      },
      {
        "key": "dub_volume",
        "label": "配音响度",
        "type": "slider",
        "colSpan": "half",
        "min": 0,
        "max": 1,
        "step": 0.05,
        "description": "配音音量 (0~1)"
      },
      {
        "key": "fade_in",
        "label": "淡入(秒)",
        "type": "number",
        "colSpan": "half",
        "min": 0,
        "max": 10,
        "step": 0.1,
        "description": "配音淡入时间"
      },
      {
        "key": "fade_out",
        "label": "淡出(秒)",
        "type": "number",
        "colSpan": "half",
        "min": 0,
        "max": 10,
        "step": 0.1,
        "description": "配音淡出时间"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "merge_audio",
    "name": "音视频配音对齐",
    "category": "process",
    "description": "基于原视频重新配音后，将配音片段按时间戳对齐到原视频的配音音视频对齐",
    "icon": "Merge",
    "color": "#10b981",
    "inputs": [
      {
        "id": "audio_manifest",
        "label": "配音任务清单",
        "type": "json",
        "required": true
      },
      {
        "id": "video",
        "label": "输入视频",
        "type": "video"
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "合并音频",
        "type": "audio"
      },
      {
         "id": "dub_srt",
         "label": "配音字幕",
         "type": "subtitle"
       },
      {
        "id": "dub_bilingual_srt",
        "label": "双语字幕",
        "type": "subtitle"
      },
      {
        "id": "video_adjusted",
        "label": "调速视频",
        "type": "video"
      }
    ],
    "defaultConfig": {"video_speed_adjust": false, "speed_min": "", "speed_max": "", "gap_threshold": "", "speed_limit": "", "fast_limit": "", "audio_format": "", "audio_bitrate": ""},
    "configFields": [
      {
        "key": "speed_min",
        "label": "音频最小变速倍数",
        "type": "text",
        "colSpan": "half",
        "placeholder": "留空读取全局 video.speed.min，默认 1.0",
        "description": "音频变速的最小倍数，低于此值不加速"
      },
      {
        "key": "speed_max",
        "label": "音频最大变速倍数",
        "type": "text",
        "colSpan": "half",
        "placeholder": "留空读取全局 video.speed.max，默认 1.5",
        "description": "音频变速的最大倍数，超出部分需要视频变速或截断"
      },
      {
        "key": "gap_threshold",
        "label": "说话间隙占用最大比例",
        "type": "text",
        "placeholder": "留空读取全局 video.speed.gap_threshold，默认 0.1",
        "description": "允许占用段后间隙的比例 (0~1)，用于扩展可用时长"
      },
      {
        "key": "video_speed_adjust",
        "label": "启用视频变速",
        "type": "toggle",
        "defaultValue": false,
        "description": "对缩减后仍超长的片段，对视频进行局部变速以匹配配音时长"
      },
      {
        "key": "speed_limit",
        "label": "视频变速最大倍率",
        "type": "text",
        "colSpan": "half",
        "placeholder": "留空读取全局 video.speed.limit，默认 2.0",
        "description": "视频变速的最大倍率上限"
      },
      {
        "key": "fast_limit",
        "label": "视频减速最小倍率",
        "type": "text",
        "colSpan": "half",
        "placeholder": "留空读取全局 video.speed.fast_limit，默认 2.0",
        "description": "视频局部变速的最小倍率"
      },
      {
        "key": "audio_format",
        "label": "输出音频格式",
        "type": "select",
        "colSpan": "half",
        "options": [
          {"label": "跟随全局设置", "value": ""},
          {"label": "WAV (无损)", "value": "wav"},
          {"label": "MP3", "value": "mp3"},
          {"label": "FLAC (无损压缩)", "value": "flac"}
        ],
        "description": "配音音频输出格式，留空跟随全局设置"
      },
      {
        "key": "audio_bitrate",
        "label": "音频码率(kbps)",
        "type": "text",
        "colSpan": "half",
        "placeholder": "留空读取全局 audio.bitrate，默认 320",
        "description": "MP3/FLAC 输出码率，WAV 格式忽略此项"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "merge_dub",
    "name": "配音拼接",
    "category": "process",
    "description": "适用于无时间戳要求的纯文本配音片段的合并，按顺序拼接各段配音音频并生成配音字幕",
    "icon": "Merge",
    "color": "#14b8a6",
    "inputs": [
      {
        "id": "audio",
        "label": "音频片段路径",
        "type": "audio",
        "required": false
      },
      {
        "id": "audio_manifest",
        "label": "配音任务单JSON",
        "type": "json",
        "required": false
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "合并配音音频",
        "type": "audio"
      },
      {
        "id": "dub_srt",
        "label": "配音字幕",
        "type": "subtitle"
      }
    ],
    "defaultConfig": {"audio_format": "", "audio_bitrate": "", "silence_interval": 0.5},
    "configFields": [
      {
        "key": "audio_format",
        "label": "输出音频格式",
        "type": "select",
        "colSpan": "half",
        "options": [
          {"label": "跟随全局设置", "value": ""},
          {"label": "WAV (无损)", "value": "wav"},
          {"label": "MP3", "value": "mp3"},
          {"label": "FLAC (无损压缩)", "value": "flac"}
        ],
        "description": "合并后配音音频的输出格式，留空跟随全局设置"
      },
      {
        "key": "audio_bitrate",
        "label": "音频码率(kbps)",
        "type": "text",
        "colSpan": "half",
        "placeholder": "留空读取全局 audio.bitrate，默认 320",
        "description": "MP3/FLAC 输出码率，WAV 格式忽略此项"
      },
      {
        "key": "silence_interval",
        "label": "片段间静音间隔(秒)",
        "type": "number",
        "defaultValue": 0.5,
        "min": 0,
        "max": 10,
        "step": 0.1,
        "description": "相邻配音片段之间插入的静音时长"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "merge_dub_video",
    "name": "配音视频合成",
    "category": "process",
    "description": "将配音音频合成到视频",
    "icon": "Clapperboard",
    "color": "#3b82f6",
    "inputs": [
      {
        "id": "video",
        "label": "视频",
        "type": "video",
        "required": true
      },
      {
        "id": "audio",
        "label": "配音音频",
        "type": "audio",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "video",
        "label": "配音视频",
        "type": "video"
      }
    ],
    "defaultConfig": {},
    "configFields": [],
    "isBuiltIn": true
  },
  {
    "id": "cover",
    "name": "AI封面设计",
    "category": "ai_gen",
    "description": "根据内容JSON生成封面文生图提示词，支持AI设计和自定义描述两种模式",
    "icon": "Image",
    "color": "#ec4899",
    "inputs": [
      {
        "id": "json",
        "label": "内容JSON",
        "type": "json",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "prompt",
        "label": "封面提示词",
        "type": "text"
      }
    ],
    "defaultConfig": {
      "custom_title_enabled": false,
      "custom_title": "",
      "custom_subtitle_enabled": false,
      "custom_subtitle": "",
      "design_mode": "ai_design",
      "ai_prompt": "你是一位专业的短视频封面设计师和文生图提示词专家。请根据以下视频内容信息，设计一张吸引人的短视频封面画面，并输出详细的文生图提示词。\n\n要求：\n1. 画面风格：适合短视频平台的视觉风格，色彩鲜明、对比强烈，具有视觉冲击力\n2. 标题字体：主标题使用粗体大字，醒目突出，字体风格与内容主题匹配\n3. 标题颜色：根据画面整体色调选择高对比度的颜色，确保可读性\n4. 标题位置：主标题居中或偏上，副标题在主标题下方，不遮挡画面主体\n5. 背景融合：标题与背景自然融合，可使用阴影、描边或半透明底色增强可读性\n6. 画面构图：简洁大气，留出标题空间，主体突出\n\n请直接输出文生图提示词（英文），不需要额外解释。提示词应包含画面描述、风格、色调、构图、文字排版等完整信息。",
      "custom_prompt": "A visually striking short video cover image, cinematic style, vibrant colors, bold composition. Main title \"{title}\" displayed prominently in large bold white text with dark shadow, centered upper area. Subtitle \"{subtitle}\" in smaller elegant font below the main title. Dynamic background with rich textures and depth of field, professional digital art quality, 4K resolution."
    },
    "configFields": [
      {
        "key": "custom_title_enabled",
        "label": "自定义标题",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "custom_title",
        "label": "标题文本",
        "type": "text",
        "placeholder": "输入自定义标题",
        "dependsOn": "custom_title_enabled",
        "dependsValue": true
      },
      {
        "key": "custom_subtitle_enabled",
        "label": "自定义副标题",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "custom_subtitle",
        "label": "副标题文本",
        "type": "text",
        "placeholder": "输入自定义副标题",
        "dependsOn": "custom_subtitle_enabled",
        "dependsValue": true
      },
      {
        "key": "design_mode",
        "label": "封面设计模式",
        "type": "chips",
        "singleSelect": true,
        "chipColor": "#ec4899",
        "options": [
          {
            "value": "ai_design",
            "label": "AI设计封面"
          },
          {
            "value": "custom_prompt",
            "label": "自定义描述"
          }
        ]
      },
      {
        "key": "ai_prompt",
        "label": "AI设计封面提示词",
        "type": "textarea",
        "placeholder": "留空使用默认提示词...",
        "dependsOn": "design_mode",
        "dependsValue": "ai_design"
      },
      {
        "key": "custom_prompt",
        "label": "文生图提示词",
        "type": "textarea",
        "placeholder": "输入文生图提示词，使用 {title} 和 {subtitle} 引用标题...",
        "dependsOn": "design_mode",
        "dependsValue": "custom_prompt",
        "chips": [{"value": "{title}", "label": "主标题"}, {"value": "{subtitle}", "label": "副标题"}]
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "watermark",
    "name": "水印添加",
    "category": "process",
    "description": "为视频添加水印",
    "icon": "Stamp",
    "color": "#6b7280",
    "inputs": [
      {
        "id": "video",
        "label": "视频",
        "type": "video",
        "required": true
      },
      {
        "id": "image",
        "label": "水印图片",
        "type": "image"
      }
    ],
    "outputs": [
      {
        "id": "video",
        "label": "最终视频",
        "type": "video"
      }
    ],
    "defaultConfig": {
      "enabled": false,
      "position": "bottom-right",
      "opacity": 0.5
    },
    "configFields": [
      {
        "key": "enabled",
        "label": "启用水印",
        "type": "checkbox"
      },
      {
        "key": "position",
        "label": "位置",
        "type": "select",
        "options": [
          {
            "value": "top-left",
            "label": "左上角"
          },
          {
            "value": "top-right",
            "label": "右上角"
          },
          {
            "value": "bottom-left",
            "label": "左下角"
          },
          {
            "value": "bottom-right",
            "label": "右下角"
          },
          {
            "value": "center",
            "label": "居中"
          }
        ]
      },
      {
        "key": "opacity",
        "label": "透明度",
        "type": "text",
        "placeholder": "0.5"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "output",
    "name": "输出",
    "category": "output",
    "description": "导出文件",
    "icon": "Download",
    "color": "#ef4444",
    "inputs": [
      {
        "id": "any",
        "label": "输入",
        "type": "any"
      }
    ],
    "outputs": [],
    "defaultConfig": {
      "outputDir": "",
      "fileName": "",
      "suffix": "",
      "autoIncrement": true
    },
    "configFields": [
      {
        "key": "outputDir",
        "label": "输出目录",
        "type": "file",
        "placeholder": "留空使用默认目录",
        "fileFilter": []
      },
      {
        "key": "fileName",
        "label": "自定义文件名",
        "type": "text",
        "placeholder": "留空使用原文件名"
      },
      {
        "key": "suffix",
        "label": "文件名后缀",
        "type": "text",
        "placeholder": "如 _cn、_dubbed"
      },
      {
        "key": "autoIncrement",
        "label": "同名文件自动加序号",
        "type": "checkbox"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "subtitle_align",
    "name": "译文断句和双语对齐",
    "category": "ai",
    "description": "对超长译文进行断句并与原文对齐，调整时间戳",
    "icon": "AlignLeft",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "subtitle",
        "label": "翻译结果JSON",
        "type": "subtitle",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "subtitle",
        "label": "对齐结果JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "max_subtitle_length": 30
    },
    "configFields": [
      {
        "key": "max_subtitle_length",
        "label": "译文单行最大字符数",
        "type": "text",
        "placeholder": "默认 20 字符"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "video_preview",
    "name": "视频预览器",
    "category": "preview",
    "description": "预览视频和字幕，支持标题设置、快捷调整字体大小和位置",
    "icon": "Play",
    "color": "#14b8a6",
    "inputs": [
      {
        "id": "video",
        "label": "视频",
        "type": "video"
      },
      {
        "id": "subtitle",
        "label": "译文字幕",
        "type": "subtitle"
      },
      {
        "id": "original",
        "label": "原文字幕",
        "type": "subtitle"
      },
      {
        "id": "bilingual",
        "label": "双语字幕",
        "type": "subtitle"
      }
    ],
    "outputs": [],
    "defaultConfig": {
      "title": "",
      "fontSize": 12,
      "fontFamily": "sans-serif",
      "fontColor": "#ffffff",
      "backgroundColor": "rgba(0,0,0,0.6)",
      "subtitlePosition": "bottom"
    },
    "configFields": [
      {
        "key": "mute_original",
        "label": "原视频静音",
        "type": "checkbox",
        "description": "烧录字幕时是否将原视频音频静音"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "image_preview",
    "name": "图片预览器",
    "category": "preview",
    "description": "预览图片结果",
    "icon": "Eye",
    "color": "#14b8a6",
    "inputs": [
      {
        "id": "image",
        "label": "图片",
        "type": "image"
      }
    ],
    "outputs": [],
    "defaultConfig": {
      "fit": "contain"
    },
    "configFields": [
      {
        "key": "fit",
        "label": "适应方式",
        "type": "select",
        "options": [
          {
            "value": "contain",
            "label": "包含"
          },
          {
            "value": "cover",
            "label": "覆盖"
          },
          {
            "value": "fill",
            "label": "填充"
          },
          {
            "value": "none",
            "label": "原始大小"
          }
        ]
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "llm_request",
    "name": "通用LLM请求",
    "category": "ai",
    "description": "通用 LLM 请求，支持文本/图片输入，可配置 prompt、模型、温度等",
    "icon": "Brain",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "text",
        "label": "文本输入",
        "type": "text"
      },
      {
        "id": "image",
        "label": "图片输入",
        "type": "image"
      },
      {
        "id": "json",
        "label": "JSON输入",
        "type": "json"
      }
    ],
    "outputs": [
      {
        "id": "result",
        "label": "结果文件",
        "type": "json"
      },
      {
        "id": "text",
        "label": "文本结果",
        "type": "text"
      }
    ],
    "defaultConfig": {
      "model": "",
      "system_prompt": "",
      "user_prompt": "{input_text}",
      "temperature": 0.7,
      "response_json": false,
      "log_request": false
    },
    "configFields": [
      {
        "key": "model",
        "label": "模型名称",
        "type": "text",
        "placeholder": "留空使用全局默认模型",
        "colSpan": "half"
      },
      {
        "key": "temperature",
        "label": "温度",
        "type": "slider",
        "min": 0,
        "max": 2,
        "step": 0.1,
        "colSpan": "half"
      },
      {
        "key": "system_prompt",
        "label": "System Prompt",
        "type": "textarea",
        "placeholder": "系统提示词..."
      },
      {
        "key": "user_prompt",
        "label": "User Prompt",
        "type": "textarea",
        "placeholder": "用户提示词，使用 {input_text} 引用文本输入...",
        "chips": [
          {"value": "{input_text}", "label": "输入文本"},
          {"value": "{input_json}", "label": "JSON数据"},
          {"value": "{source_language}", "label": "输入语言"},
          {"value": "{target_language}", "label": "输出语言"}
        ]
      },
      {
        "key": "response_json",
        "label": "JSON 格式输出",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "log_request",
        "label": "请求日志打印",
        "type": "checkbox",
        "colSpan": "half"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "http_request",
    "name": "网络请求",
    "category": "network_request",
    "description": "执行可配置的 HTTP 网络请求，支持请求体占位符、重试和响应保存",
    "icon": "Globe",
    "color": "#0f766e",
    "inputs": [
      {"id": "input_1", "label": "输入 1", "type": "any", "required": false},
      {"id": "input_2", "label": "输入 2", "type": "any", "required": false},
      {"id": "input_3", "label": "输入 3", "type": "any", "required": false},
      {"id": "request_data", "label": "请求 Data", "type": "json", "required": false}
    ],
    "outputs": [
      {"id": "result", "label": "结果文件", "type": "any"},
      {"id": "json", "label": "JSON 结果", "type": "json"},
      {"id": "text", "label": "文本结果", "type": "text"},
      {"id": "status", "label": "状态码", "type": "text"}
    ],
    "defaultConfig": {
      "request_client": "requests", "url": "", "method": "GET", "headers": "{}", "body_type": "json", "body": "",
      "browser_impersonation": "none", "ignore_connected_inputs": false, "retry_enabled": false, "retry_count": 3,
      "retry_interval": 1, "timeout": 30, "success_status_codes": "200-299", "output_format": "auto"
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
      {"key": "retry_count", "label": "重试次数", "type": "number", "min": 0, "max": 20, "colSpan": "half", "dependsOn": "retry_enabled", "dependsValue": true},
      {"key": "retry_interval", "label": "重试间隔（秒）", "type": "number", "min": 0, "max": 300, "colSpan": "half", "dependsOn": "retry_enabled", "dependsValue": true},
      {"key": "timeout", "label": "超时时长（秒）", "type": "number", "min": 1, "max": 1800, "colSpan": "half"},
      {"key": "success_status_codes", "label": "成功状态码", "type": "text", "placeholder": "200-299 或 200,201,2xx", "colSpan": "half"}
    ],
    "isBuiltIn": true
  },
  {
    "id": "image_gen",
    "name": "AI生图",
    "category": "ai_gen",
    "description": "AI图像生成，支持文生图和图生图模式，集成多种生图接口和模型",
    "icon": "Paintbrush",
    "color": "#f59e0b",
    "inputs": [
      {
        "id": "text",
        "label": "文本输入",
        "type": "text"
      },
      {
        "id": "image",
        "label": "图片输入",
        "type": "image"
      }
    ],
    "outputs": [
      {
        "id": "images",
        "label": "图片列表",
        "type": "json"
      },
      {
        "id": "text",
        "label": "首张图片",
        "type": "image"
      }
    ],
    "defaultConfig": {
      "mode": "txt2img",
      "interface": "",
      "model": "",
      "resolution": "1K",
      "aspect_ratio": "1:1",
      "num_images": 1,
      "custom_prompt_enabled": false,
      "custom_prompt": "",
      "output_prefix": "img"
    },
    "configFields": [
      {
        "key": "mode",
        "label": "生图模式",
        "type": "chips",
        "singleSelect": true,
        "chipColor": "#f59e0b",
        "options": [
          {"value": "txt2img", "label": "文生图"},
          {"value": "img2img", "label": "图生图"}
        ]
      },
      {
        "key": "interface",
        "label": "接口选择",
        "type": "api-select",
        "apiEndpoint": "/api/imagegen-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id"
      },
      {
        "key": "model",
        "label": "模型选择",
        "type": "api-select",
        "apiEndpoint": "/api/imagegen-interfaces/{interface}/models-for-node?mode={mode}",
        "dependsOn": "interface",
        "placeholder": "请选择模型"
      },
      {
        "key": "resolution",
        "label": "分辨率",
        "type": "select",
        "colSpan": "half",
        "options": [
          {"value": "1K", "label": "1K"},
          {"value": "2K", "label": "2K"},
          {"value": "4K", "label": "4K"}
        ]
      },
      {
        "key": "aspect_ratio",
        "label": "图片比例",
        "type": "select",
        "colSpan": "half",
        "options": [
          {"value": "1:1", "label": "1:1"},
          {"value": "16:9", "label": "16:9"},
          {"value": "9:16", "label": "9:16"},
          {"value": "4:3", "label": "4:3"},
          {"value": "3:4", "label": "3:4"},
          {"value": "3:2", "label": "3:2"},
          {"value": "2:3", "label": "2:3"},
          {"value": "21:9", "label": "21:9"}
        ]
      },
      {
        "key": "num_images",
        "label": "生成数量",
        "type": "number",
        "min": 1,
        "max": 10,
        "colSpan": "half"
      },
      {
        "key": "custom_prompt_enabled",
        "label": "自定义提示词",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "custom_prompt",
        "label": "自定义提示词",
        "type": "textarea",
        "dependsOn": "custom_prompt_enabled",
        "dependsValue": true,
        "placeholder": "输入自定义生图提示词..."
      },
      {
        "key": "output_prefix",
        "label": "输出文件名前缀",
        "type": "text",
        "colSpan": "half",
        "placeholder": "img"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "editor_agent",
    "name": "剪辑AI Agent",
    "category": "ai",
    "description": "通过自然语言读取并修改当前任务的剪辑项目和时间线",
    "icon": "Clapperboard",
    "color": "#10b981",
    "inputs": [
      {
        "id": "text",
        "label": "编辑指令",
        "type": "text"
      }
    ],
    "outputs": [
      {
        "id": "project",
        "label": "剪辑项目",
        "type": "json"
      },
      {
        "id": "artifacts",
        "label": "运行记录",
        "type": "json"
      },
      {
        "id": "result",
        "label": "执行结果",
        "type": "text"
      }
    ],
    "defaultConfig": {
      "instruction": "",
      "expert_role": "auto"
    },
    "configFields": [
      {
        "key": "instruction",
        "label": "编辑指令",
        "type": "textarea",
        "placeholder": "例如：将配音加入时间线并添加开场标题",
        "colSpan": "full"
      },
      {
        "key": "expert_role",
        "label": "专家角色",
        "type": "select",
        "options": [
          {
            "value": "auto",
            "label": "自动导演"
          },
          {
            "value": "general",
            "label": "通用剪辑"
          },
          {
            "value": "design",
            "label": "视觉设计"
          },
          {
            "value": "audio",
            "label": "音频编辑"
          },
          {
            "value": "editing",
            "label": "剪辑顾问"
          },
          {
            "value": "storytelling",
            "label": "叙事导演"
          }
        ]
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "cutia",
    "name": "Cutia 交互剪辑",
    "category": "process",
    "description": "将上游素材载入 Cutia，等待手工剪辑并导出成片后继续工作流",
    "icon": "Clapperboard",
    "color": "#14b8a6",
    "inputs": [
      {
        "id": "video",
        "label": "视频",
        "type": "video"
      },
      {
        "id": "audio",
        "label": "音频",
        "type": "audio"
      },
      {
        "id": "image",
        "label": "图片",
        "type": "image"
      },
      {
        "id": "subtitle",
        "label": "字幕",
        "type": "subtitle"
      }
    ],
    "outputs": [
      {
        "id": "video",
        "label": "剪辑成片",
        "type": "video"
      }
    ],
    "defaultConfig": {},
    "configFields": [],
    "isBuiltIn": true
  },
  {
    "id": "video_frame_extract",
    "name": "视频抽帧",
    "category": "process",
    "description": "从视频指定时间点提取帧图片，支持避开字幕",
    "icon": "Camera",
    "color": "#06b6d4",
    "inputs": [
      {
        "id": "video",
        "label": "视频",
        "type": "video"
      },
      {
        "id": "srt",
        "label": "字幕",
        "type": "subtitle"
      }
    ],
    "outputs": [
      {
        "id": "image",
        "label": "帧图片",
        "type": "image"
      }
    ],
    "defaultConfig": {
      "video_source": "input_node",
      "time_point": 1.0,
      "time_mode": "positive",
      "avoid_subtitles": false
    },
    "configFields": [
      {
        "key": "video_source",
        "label": "视频源",
        "type": "chips",
        "singleSelect": true,
        "chipColor": "#06b6d4",
        "options": [
          {"value": "input_node", "label": "来自输入节点"},
          {"value": "connection", "label": "来自节点连线"}
        ]
      },
      {
        "key": "time_point",
        "label": "截取时间点(秒)",
        "type": "text",
        "colSpan": "half",
        "placeholder": "如 5.0 或 120"
      },
      {
        "key": "time_mode",
        "label": "时间模式",
        "type": "select",
        "colSpan": "half",
        "options": [
          {"value": "positive", "label": "正数(从头)"},
          {"value": "negative", "label": "倒数(从尾)"}
        ]
      },
      {
        "key": "avoid_subtitles",
        "label": "避开字幕",
        "type": "checkbox"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "video_publish",
    "name": "视频发布",
    "category": "publish",
    "description": "将视频发布到指定社交平台，支持多平台分发、定时发布、草稿模式",
    "icon": "Share2",
    "color": "#10b981",
    "inputs": [
      {"id": "video", "label": "视频", "type": "video", "required": true},
      {"id": "cover_landscape", "label": "横屏封面", "type": "image"},
      {"id": "cover_portrait", "label": "竖屏封面", "type": "image"},
      {"id": "json", "label": "标题/描述", "type": "json"}
    ],
    "outputs": [
      {"id": "text", "label": "发布结果", "type": "text"},
      {"id": "result_file", "label": "结果文件", "type": "json"}
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
      "is_original": false,
      "publish_mode": "publish",
      "schedule_enabled": false,
      "schedule_time": ""
    },
    "configFields": [
      {
        "key": "account_ids",
        "label": "选择发布账号",
        "type": "account-select",
        "apiEndpoint": "/api/publish/accounts/all",
        "placeholder": "请选择发布账号"
      },
      {
        "key": "title",
        "label": "视频标题",
        "type": "text",
        "placeholder": "留空则从上游JSON读取"
      },
      {
        "key": "title_affix",
        "label": "标题附加文本",
        "type": "text",
        "placeholder": "输入要附加到标题的文本",
        "colSpan": "half"
      },
      {
        "key": "title_affix_mode",
        "label": "附加位置",
        "type": "select",
        "colSpan": "half",
        "options": [{"value": "prefix", "label": "前缀"}, {"value": "suffix", "label": "后缀"}]
      },
      {
        "key": "description",
        "label": "视频描述",
        "type": "textarea",
        "placeholder": "留空则从上游JSON读取"
      },
      {
        "key": "desc_affix",
        "label": "描述附加文本",
        "type": "text",
        "placeholder": "输入要附加到描述的文本",
        "colSpan": "half"
      },
      {
        "key": "desc_affix_mode",
        "label": "附加位置",
        "type": "select",
        "colSpan": "half",
        "options": [{"value": "prefix", "label": "前缀"}, {"value": "suffix", "label": "后缀"}]
      },
      {
        "key": "tags",
        "label": "标签(逗号分隔)",
        "type": "text",
        "placeholder": "标签1,标签2,标签3",
        "colSpan": "half"
      },
      {
        "key": "is_original",
        "label": "原创内容",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "publish_mode",
        "label": "发布方式",
        "type": "select",
        "options": [
          {"value": "publish", "label": "直接发布"},
          {"value": "platform_draft", "label": "存为平台草稿"},
          {"value": "local_draft", "label": "存为本地草稿"}
        ]
      },
      {
        "key": "declaration",
        "label": "内容声明",
        "type": "select",
        "options": [
          {"value": "", "label": "无需声明"},
          {"value": "ai_generated", "label": "含AI生成内容"},
          {"value": "repost", "label": "内容为转载"},
          {"value": "fictional", "label": "含虚构演绎内容"},
          {"value": "marketing", "label": "内容含营销信息"},
          {"value": "personal_opinion", "label": "个人观点，仅供参考"}
        ],
        "description": "声明视频内容属性，发布时传递给平台"
      },
      {
        "key": "schedule_enabled",
        "label": "定时发布",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "schedule_time",
        "label": "定时时间",
        "type": "datetime-local",
        "dependsOn": "schedule_enabled",
        "dependsValue": true
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "xiaopai_publish",
    "name": "小派作品发布",
    "category": "publish",
    "description": "小Pi助手作品发布节点，自动准备发布数据并调用发布服务",
    "icon": "Send",
    "color": "#06b6d4",
    "inputs": [
      {"id": "video", "label": "视频", "type": "video", "required": true},
      {"id": "cover_landscape", "label": "横屏封面", "type": "image"},
      {"id": "cover_portrait", "label": "竖屏封面", "type": "image"},
      {"id": "json", "label": "标题/描述", "type": "json"}
    ],
    "outputs": [
      {"id": "text", "label": "发布结果", "type": "text"},
      {"id": "result_file", "label": "结果文件", "type": "json"}
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
      "is_original": false,
      "publish_mode": "publish",
      "schedule_enabled": false,
      "schedule_time": ""
    },
    "configFields": [
      {
        "key": "account_ids",
        "label": "选择发布账号",
        "type": "account-select",
        "apiEndpoint": "/api/publish/accounts/all",
        "placeholder": "请选择发布账号"
      },
      {
        "key": "title",
        "label": "视频标题",
        "type": "text",
        "placeholder": "留空则从上游JSON读取"
      },
      {
        "key": "title_affix",
        "label": "标题附加文本",
        "type": "text",
        "placeholder": "输入要附加到标题的文本",
        "colSpan": "half"
      },
      {
        "key": "title_affix_mode",
        "label": "附加位置",
        "type": "select",
        "colSpan": "half",
        "options": [{"value": "prefix", "label": "前缀"}, {"value": "suffix", "label": "后缀"}]
      },
      {
        "key": "description",
        "label": "视频描述",
        "type": "textarea",
        "placeholder": "留空则从上游JSON读取"
      },
      {
        "key": "desc_affix",
        "label": "描述附加文本",
        "type": "text",
        "placeholder": "输入要附加到描述的文本",
        "colSpan": "half"
      },
      {
        "key": "desc_affix_mode",
        "label": "附加位置",
        "type": "select",
        "colSpan": "half",
        "options": [{"value": "prefix", "label": "前缀"}, {"value": "suffix", "label": "后缀"}]
      },
      {
        "key": "tags",
        "label": "标签(逗号分隔)",
        "type": "text",
        "placeholder": "标签1,标签2,标签3",
        "colSpan": "half"
      },
      {
        "key": "is_original",
        "label": "原创内容",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "publish_mode",
        "label": "发布方式",
        "type": "select",
        "options": [
          {"value": "publish", "label": "直接发布"},
          {"value": "platform_draft", "label": "存为平台草稿"},
          {"value": "local_draft", "label": "存为本地草稿"}
        ]
      },
      {
        "key": "declaration",
        "label": "内容声明",
        "type": "select",
        "options": [
          {"value": "", "label": "无需声明"},
          {"value": "ai_generated", "label": "含AI生成内容"},
          {"value": "repost", "label": "内容为转载"},
          {"value": "fictional", "label": "含虚构演绎内容"},
          {"value": "marketing", "label": "内容含营销信息"},
          {"value": "personal_opinion", "label": "个人观点，仅供参考"}
        ],
        "description": "声明视频内容属性，发布时传递给平台"
      },
      {
        "key": "schedule_enabled",
        "label": "定时发布",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "schedule_time",
        "label": "定时时间",
        "type": "datetime-local",
        "dependsOn": "schedule_enabled",
        "dependsValue": true
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "resolve_path",
    "name": "取文件路径",
    "category": "process",
    "description": "以相对路径拼接出项目文件夹内的特定文件路径",
    "icon": "FolderOpen",
    "color": "#8b5cf6",
    "inputs": [
      {"id": "input", "label": "输入", "type": "any"}
    ],
    "outputs": [
      {"id": "output", "label": "路径", "type": "any"}
    ],
    "defaultConfig": {
      "relative_path": ""
    },
    "configFields": [
      {
        "key": "relative_path",
        "label": "相对路径",
        "type": "text",
        "placeholder": "例: output/video.mp4 或 cache/subtitle.srt"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "json_to_text",
    "name": "JSON转文本",
    "category": "process",
    "description": "将JSON转换为文本文件，支持全量转文本或按key表达式取值",
    "icon": "FileText",
    "color": "#f97316",
    "inputs": [
      {"id": "json", "label": "JSON", "type": "json"}
    ],
    "outputs": [
      {"id": "text", "label": "文本文件", "type": "text"}
    ],
    "defaultConfig": {
      "mode": "full",
      "key_expr": ""
    },
    "configFields": [
      {
        "key": "mode",
        "label": "输出模式",
        "type": "select",
        "options": [
          {"value": "full", "label": "全量转文本"},
          {"value": "key", "label": "key取值"}
        ]
      },
      {
        "key": "key_expr",
        "label": "key表达式",
        "type": "text",
        "placeholder": "key0$key1$key2 (用$分隔层级)",
        "dependsOn": "mode",
        "dependsValue": "key"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "json_editor",
    "name": "JSON编辑",
    "category": "process",
    "description": "按key表达式修改JSON中指定字段的值，覆盖保存原文件",
    "icon": "Edit3",
    "color": "#f97316",
    "inputs": [
      {"id": "json", "label": "JSON", "type": "json"},
      {"id": "text", "label": "修改值", "type": "text"}
    ],
    "outputs": [
      {"id": "json", "label": "JSON", "type": "json"}
    ],
    "defaultConfig": {
      "key_expr": "",
      "value_source": "auto",
      "custom_value": ""
    },
    "configFields": [
      {
        "key": "key_expr",
        "label": "key表达式",
        "type": "text",
        "placeholder": "key0$key1$key2 (用$分隔层级)"
      },
      {
        "key": "value_source",
        "label": "修改值来源",
        "type": "select",
        "options": [
          {"value": "auto", "label": "自动（优先连线，回退自定义）"},
          {"value": "input", "label": "连线输入"},
          {"value": "custom", "label": "自定义输入"}
        ]
      },
      {
        "key": "custom_value",
        "label": "自定义输入值",
        "type": "text",
        "placeholder": "输入要设置的值"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "json_visual_editor",
    "name": "JSON可视化编辑",
    "category": "utility",
    "description": "可视化编辑 JSON，默认透传，可另存副本",
    "icon": "FileJson",
    "color": "#8b5cf6",
    "inputs": [
      {"id": "json", "label": "JSON", "type": "json", "required": true}
    ],
    "outputs": [
      {"id": "json", "label": "JSON", "type": "json"}
    ],
    "defaultConfig": {
      "enable_copy": true,
      "edited_json": ""
    },
    "configFields": [
      {
        "key": "open_editor",
        "label": "打开 JSON 编辑页",
        "type": "button",
        "description": "打开可视化 JSON 编辑弹窗，载入输入 JSON"
      },
      {
        "key": "enable_copy",
        "label": "另存副本",
        "type": "checkbox",
        "colSpan": "half",
        "description": "勾选后另存带随机后缀的副本，不覆盖原文件；取消勾选则直接覆盖原 JSON 文件"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "text_editor",
    "name": "文本编辑",
    "category": "utility",
    "description": "可视化编辑文本，支持查找删除/替换/正则，默认透传，可另存副本",
    "icon": "FileText",
    "color": "#8b5cf6",
    "inputs": [
      {"id": "text", "label": "文本", "type": "text", "required": true}
    ],
    "outputs": [
      {"id": "text", "label": "文本", "type": "text"}
    ],
    "defaultConfig": {
      "enable_copy": true,
      "edited_text": ""
    },
    "configFields": [
      {
        "key": "open_editor",
        "label": "打开文本编辑页",
        "type": "button",
        "description": "打开文本编辑弹窗，支持查找删除、查找替换、正则表达式查找替换"
      },
      {
        "key": "enable_copy",
        "label": "另存副本",
        "type": "checkbox",
        "colSpan": "half",
        "description": "勾选后另存带随机后缀的副本，不覆盖原文件；取消勾选则直接覆盖原文本文件"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "subtitle_editor",
    "name": "字幕编辑",
    "category": "utility",
    "description": "逐条编辑字幕（文本/时间/合并/拆分），带视频预览，默认透传，可另存副本",
    "icon": "Subtitles",
    "color": "#f59e0b",
    "inputs": [
      {"id": "subtitle", "label": "字幕", "type": "subtitle", "required": true}
    ],
    "outputs": [
      {"id": "subtitle", "label": "字幕", "type": "subtitle"}
    ],
    "defaultConfig": {
      "enable_copy": true,
      "edited_subtitles": ""
    },
    "configFields": [
      {
        "key": "open_editor",
        "label": "打开字幕编辑页",
        "type": "button",
        "description": "打开字幕编辑弹窗：左侧字幕列表，右侧视频预览，时间轴同步"
      },
      {
        "key": "enable_copy",
        "label": "另存副本",
        "type": "checkbox",
        "colSpan": "half",
        "description": "勾选后另存带随机后缀的副本，不覆盖原文件；取消勾选则直接覆盖原字幕文件"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "video_transcode",
    "name": "视频转码",
    "category": "video",
    "description": "使用 ffmpeg 对视频进行转码，支持容器格式、视频/音频编码、码率、分辨率、帧率、编码速度档与像素格式等参数配置",
    "icon": "Clapperboard",
    "color": "#ec4899",
    "inputs": [
      {"id": "video", "label": "视频", "type": "video", "required": true}
    ],
    "outputs": [
      {"id": "video", "label": "转码视频", "type": "video"}
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
      "audio_bitrate": "192k"
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
          {"value": "flv", "label": "FLV"}
        ],
        "description": "封装容器格式，决定输出文件扩展名"
      },
      {
        "key": "video_mode",
        "label": "视频处理模式",
        "type": "chips",
        "singleSelect": true,
        "chipColor": "#ec4899",
        "options": [
          {"value": "reencode", "label": "重新编码"},
          {"value": "copy", "label": "流复制(不重编码)"},
          {"value": "none", "label": "去除视频"}
        ],
        "description": "流复制：直接拷贝原始视频流，速度极快但无法修改画质/分辨率"
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
          {"value": "mpeg4", "label": "MPEG-4"}
        ],
        "description": "选择视频编码格式"
      },
      {
        "key": "crf",
        "label": "CRF 质量(0-51)",
        "type": "number",
        "colSpan": "half",
        "dependsOn": "video_mode",
        "dependsValue": "reencode",
        "description": "恒定质量因子，越小画质越好、体积越大。H.264/H.265 常用 18-28，VP9 常用 30-40"
      },
      {
        "key": "video_bitrate",
        "label": "视频码率",
        "type": "text",
        "colSpan": "half",
        "dependsOn": "video_mode",
        "dependsValue": "reencode",
        "placeholder": "如 2M / 4000k，留空则由 CRF 控制",
        "description": "指定固定码率；与 CRF 同时设置时以码率优先"
      },
      {
        "key": "resolution",
        "label": "分辨率(宽:高)",
        "type": "text",
        "colSpan": "half",
        "dependsOn": "video_mode",
        "dependsValue": "reencode",
        "placeholder": "如 1280:720，留空保持原分辨率",
        "description": "使用 scale 滤镜缩放，如 -2:720 表示按高度自适应宽度"
      },
      {
        "key": "fps",
        "label": "帧率",
        "type": "text",
        "colSpan": "half",
        "dependsOn": "video_mode",
        "dependsValue": "reencode",
        "placeholder": "如 30，留空保持原帧率"
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
          {"value": "veryslow", "label": "veryslow"}
        ],
        "description": "越快压缩率越低（文件越大），越慢画质/体积越优"
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
          {"value": "rgb24", "label": "rgb24"}
        ]
      },
      {
        "key": "audio_mode",
        "label": "音频处理模式",
        "type": "chips",
        "singleSelect": true,
        "chipColor": "#ec4899",
        "options": [
          {"value": "reencode", "label": "重新编码"},
          {"value": "copy", "label": "流复制(不重编码)"},
          {"value": "none", "label": "去除音频"}
        ],
        "description": "流复制：直接拷贝原始音频流"
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
          {"value": "opus", "label": "Opus (libopus)"}
        ]
      },
      {
        "key": "audio_bitrate",
        "label": "音频码率",
        "type": "text",
        "colSpan": "half",
        "dependsOn": "audio_mode",
        "dependsValue": "reencode",
        "placeholder": "如 192k / 256k"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "video_split",
    "name": "视频切割",
    "category": "process",
    "description": "将视频按数量或时长切割为多段，支持静音点切割",
    "icon": "Scissors",
    "color": "#ef4444",
    "inputs": [
      {"id": "video", "label": "视频", "type": "video", "required": true},
      {"id": "audio", "label": "音频", "type": "audio"}
    ],
    "outputs": [
      {"id": "video", "label": "切割片段", "type": "video"},
      {"id": "text", "label": "切割信息", "type": "text"}
    ],
    "defaultConfig": {
      "split_mode": "count",
      "segment_count": 2,
      "segment_duration": 60,
      "use_silence": false,
      "output_index": 1
    },
    "configFields": [
      {
        "key": "split_mode",
        "label": "切割方式",
        "type": "select",
        "options": [
          {"value": "count", "label": "按片段数量"},
          {"value": "duration", "label": "按固定时长"}
        ]
      },
      {
        "key": "segment_count",
        "label": "片段数量",
        "type": "text",
        "dependsOn": "split_mode",
        "dependsValue": "count",
        "colSpan": "half"
      },
      {
        "key": "segment_duration",
        "label": "每段时长(秒)",
        "type": "text",
        "dependsOn": "split_mode",
        "dependsValue": "duration",
        "colSpan": "half"
      },
      {
        "key": "use_silence",
        "label": "寻找静音点切割",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "output_index",
        "label": "输出片段序号",
        "type": "text",
        "placeholder": "从1开始",
        "colSpan": "half"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "translate_task_name",
    "name": "翻译项目名称",
    "category": "ai",
    "description": "将项目名称翻译为目标语言，可选择是否用译文替换任务名称",
    "icon": "Languages",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "input",
        "label": "输入",
        "type": "any"
      }
    ],
    "outputs": [
      {
        "id": "text",
        "label": "翻译结果",
        "type": "text"
      }
    ],
    "defaultConfig": {
      "replace_task_name": false
    },
    "configFields": [
      {
        "key": "replace_task_name",
        "label": "将翻译后名称替换任务名称",
        "type": "checkbox"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "timed_delay",
    "name": "定时执行",
    "category": "flow_control",
    "description": "等待指定时间后继续执行，支持时间点和倒计时两种模式",
    "icon": "Clock",
    "color": "#6366f1",
    "inputs": [
      {
        "id": "any",
        "label": "输入",
        "type": "any",
        "required": false
      }
    ],
    "outputs": [
      {
        "id": "any",
        "label": "输出",
        "type": "any"
      }
    ],
    "defaultConfig": {
      "delay_mode": "countdown",
      "target_date": "",
      "target_time": "",
      "countdown_hours": 0,
      "countdown_minutes": 0,
      "countdown_seconds": 0,
      "random_tail_enabled": false,
      "random_min": 0,
      "random_max": 0
    },
    "configFields": [
      {
        "key": "delay_mode",
        "label": "等待模式",
        "type": "select",
        "options": [
          {
            "value": "time_point",
            "label": "时间点"
          },
          {
            "value": "countdown",
            "label": "倒计时"
          }
        ]
      },
      {
        "key": "target_date",
        "label": "目标日期",
        "type": "date",
        "colSpan": "half",
        "dependsOn": "delay_mode",
        "dependsValue": "time_point"
      },
      {
        "key": "target_time",
        "label": "目标时间",
        "type": "time",
        "colSpan": "half",
        "dependsOn": "delay_mode",
        "dependsValue": "time_point"
      },
      {
        "key": "countdown_hours",
        "label": "小时",
        "type": "number",
        "min": 0,
        "max": 999,
        "colSpan": "third",
        "dependsOn": "delay_mode",
        "dependsValue": "countdown"
      },
      {
        "key": "countdown_minutes",
        "label": "分钟",
        "type": "number",
        "min": 0,
        "max": 59,
        "colSpan": "third",
        "dependsOn": "delay_mode",
        "dependsValue": "countdown"
      },
      {
        "key": "countdown_seconds",
        "label": "秒钟",
        "type": "number",
        "min": 0,
        "max": 59,
        "colSpan": "third",
        "dependsOn": "delay_mode",
        "dependsValue": "countdown"
      },
      {
        "key": "random_tail_enabled",
        "label": "随机追加尾数",
        "type": "checkbox",
        "colSpan": "full"
      },
      {
        "key": "random_min",
        "label": "最小秒数",
        "type": "number",
        "min": 0,
        "colSpan": "half",
        "dependsOn": "random_tail_enabled",
        "dependsValue": true
      },
      {
        "key": "random_max",
        "label": "最大秒数",
        "type": "number",
        "min": 0,
        "colSpan": "half",
        "dependsOn": "random_tail_enabled",
        "dependsValue": true
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "run_wait",
    "name": "运行等待",
    "category": "flow_control",
    "description": "开启后等待指定时长，超时抛出等待超时错误结束工作流；关闭则跳过并透传输入",
    "icon": "Hourglass",
    "color": "#6366f1",
    "inputs": [
      {
        "id": "input",
        "label": "输入",
        "type": "any",
        "required": false
      }
    ],
    "outputs": [
      {
        "id": "output",
        "label": "输出",
        "type": "any"
      }
    ],
    "defaultConfig": {
      "enabled": false,
      "wait_seconds": 60
    },
    "configFields": [
      {
        "key": "enabled",
        "label": "启用等待",
        "type": "toggle",
        "description": "开启后等待指定时长，超时抛出等待超时错误结束工作流；关闭则跳过并透传输入"
      },
      {
        "key": "wait_seconds",
        "label": "等待时长（秒）",
        "type": "number",
        "min": 1,
        "max": 86400,
        "colSpan": "half",
        "dependsOn": "enabled",
        "dependsValue": true,
        "placeholder": "60"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "sentence_preprocess",
    "name": "断句预处理",
    "category": "ai",
    "description": "基于全文文本（ASR JSON 或长文本 TXT）按 ASR分段/标点符号/AI 三种方法重新断句，生成更可靠的初始 segments，可选重建句子级时间戳",
    "icon": "Scissors",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "json",
        "label": "ASR结果JSON",
        "type": "json",
        "required": false
      },
      {
        "id": "text",
        "label": "长文本TXT",
        "type": "text",
        "required": false
      }
    ],
    "outputs": [
      {
        "id": "subtitle",
        "label": "断句预处理JSON",
        "type": "json",
        "color": "#6366f1"
      },
      {
        "id": "word_index",
        "label": "词级时间戳表",
        "type": "json",
        "color": "#10b981"
      }
    ],
    "defaultConfig": {
      "processing_language": "from_input",
      "method": "ai",
      "split_on_speaker": true,
      "llm_max_chars": 5000
    },
    "configFields": [
      {
        "key": "processing_language",
        "label": "处理语言",
        "type": "select",
        "options": [
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
          {"value": "ru", "label": "俄语 (ru)"}
        ]
      },
      {
        "key": "method",
        "label": "断句预处理方法",
        "type": "select",
        "options": [
          {
            "value": "asr",
            "label": "ASR分段"
          },
          {
            "value": "punct",
            "label": "标点符号断句"
          },
          {
            "value": "ai",
            "label": "AI断句"
          }
        ]
      },
      {
        "key": "split_on_speaker",
        "label": "多人会话切割",
        "type": "checkbox",
        "hint": "仅当 JSON 输入含多说话人信息时生效"
      },
      {
        "key": "llm_max_chars",
        "label": "LLM请求字数上限",
        "type": "text",
        "placeholder": "默认 5000，留空使用全局LLM字数限制"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "pi_agent",
    "name": "小pi通用智能体",
    "category": "agent",
    "description": "将小 Pi 以工作流节点方式嵌入工作流：注入任务背景与输入输出契约，发起一次 Pi 会话并执行任务，产物保存到任务 cache 目录",
    "icon": "Bot",
    "color": "#8b5cf6",
    "inputs": [
      {"id": "input_1", "label": "输入1", "type": "any", "required": false},
      {"id": "input_2", "label": "输入2", "type": "any", "required": false}
    ],
    "outputs": [
      {"id": "output_1", "label": "输出1", "type": "any"},
      {"id": "output_2", "label": "输出2", "type": "any"}
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
        {"port": "输出2", "type": "json", "desc": ""}
      ]
    },
    "configFields": [
      {"key": "inputCount", "label": "输入端口数", "type": "number", "min": 1, "max": 8},
      {"key": "outputCount", "label": "输出端口数", "type": "number", "min": 1, "max": 8},
      {"key": "skills", "label": "可调用 Skill", "type": "multiselect", "placeholder": "自行选择（不指定时由智能体自行决定）", "options": [], "description": "本次任务推荐使用的 Skill，多选；留空表示由智能体自行选择"},
      {"key": "mcps", "label": "可调用 MCP", "type": "multiselect", "placeholder": "自行选择（不指定时由智能体自行决定）", "options": [], "description": "本次任务推荐使用的 MCP，多选；留空表示由智能体自行选择"},
      {"key": "docs_path", "label": "参考技能文档", "type": "api-select", "apiEndpoint": "/api/pi/settings/docs", "optionLabel": "name", "optionValue": "path", "placeholder": "不选择", "description": "单选一份能力文档作为本任务参考；留空表示不选择"},
      {"key": "external_doc", "label": "外部参考文档", "type": "file", "fileFilter": ["md"], "placeholder": "选择外部 .md 文档", "description": "可引入外部 Markdown 文档作为本任务参考"},
      {"key": "persona", "label": "人设设定", "type": "textarea", "placeholder": "你是本项目的工作流节点执行者，执行我要求的任务，并按照需要输出产物。本次执行的任务是：", "description": "节点内人设会拼接到小 Pi 全局默认人设之后"}
    ],
    "isBuiltIn": true
  },
  {
    "id": "lcwr_watermark_removal",
    "name": "LCWR 去水印",
    "category": "process",
    "description": "调用 LCWR 本地 API 去除视频/图片中的水印与字幕。需先安装并启动 LCWR 软件（下载地址：https://qinmuzhifang.feishu.cn/wiki/IkBVwfe72iEVLTkhVQ0cW0mvnBc），右键「启动LCWR-API.bat」以管理员身份运行本地 API（默认 http://localhost:1120）",
    "icon": "Eraser",
    "color": "#0ea5e9",
    "inputs": [
      {"id": "video", "label": "视频", "type": "video", "required": false},
      {"id": "image", "label": "图片", "type": "image", "required": false}
    ],
    "outputs": [
      {"id": "video", "label": "视频", "type": "video"},
      {"id": "image", "label": "图片", "type": "image"}
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
      "fps": 25
    },
    "configFields": [
      {"key": "model", "label": "执行模型", "type": "select", "options": [
        {"value": "lama", "label": "LaMa（快速）"},
        {"value": "sttn", "label": "STTN（时空张量）"},
        {"value": "propainter", "label": "ProPainter（高质量）"},
        {"value": "diffueraser", "label": "DiffuEraser（扩散模型）"},
        {"value": "bernini", "label": "Bernini（旗舰）"},
        {"value": "online", "label": "LCWR在线模型"}
      ]},
      {"key": "lcwr_base_url", "label": "LCWR API 地址", "type": "text", "placeholder": "http://localhost:1120"},
      {"key": "aspect_ratio", "label": "视频比例（未接入视频时）", "type": "select", "options": [
        {"value": "16:9", "label": "16:9 横屏"},
        {"value": "9:16", "label": "9:16 竖屏"},
        {"value": "4:3", "label": "4:3"},
        {"value": "3:4", "label": "3:4"},
        {"value": "1:1", "label": "1:1 方形"},
        {"value": "21:9", "label": "21:9 宽屏"}
      ]},
      {"key": "skip_head_sec", "label": "片头跳过(秒)", "type": "number", "min": 0, "step": 0.5, "colSpan": "half"},
      {"key": "skip_tail_sec", "label": "片尾跳过(秒)", "type": "number", "min": 0, "step": 0.5, "colSpan": "half"},
      {"key": "skip_tail_mode", "label": "片尾计算方式", "type": "select", "options": [
        {"value": "from_end", "label": "从末尾向前数"},
        {"value": "from_head", "label": "从开头向后数"}
      ]}
    ],
    "isBuiltIn": true
  },
  {
    "id": "media_to_url",
    "name": "媒体转链接",
    "category": "process",
    "description": "上传本地视频/图片到腾讯云 VOD，返回 URL 及完整媒体详情（尺寸/时长/码率等）保存为 JSON",
    "icon": "CloudUpload",
    "color": "#06b6d4",
    "inputs": [
      {"id": "video", "label": "视频", "type": "video"},
      {"id": "image", "label": "图片", "type": "image"}
    ],
    "outputs": [
      {"id": "json", "label": "媒体详情", "type": "json"}
    ],
    "defaultConfig": {
      "timeout_sec": 300,
      "file_path": "",
      "normalize_video": false
    },
    "configFields": [
      {"key": "file_path", "label": "手动指定文件路径", "type": "file", "placeholder": "可留空，优先使用节点连线输入", "colSpan": "full", "fileFilter": ["mp4", "mkv", "webm", "avi", "mov", "wmv", "flv", "m4v", "mpg", "mpeg", "png", "jpg", "jpeg", "webp", "bmp", "gif", "tiff", "tif"]},
      {"key": "normalize_video", "label": "标准化视频", "type": "checkbox", "description": "勾选后上传前将视频用 h264 重编码为 mp4，分辨率超过 1080p 时自动等比缩小至 1080p", "colSpan": "full"},
      {"key": "timeout_sec", "label": "超时时间(秒)", "type": "number", "colSpan": "half", "placeholder": "默认 300", "description": "上传+等待URL的整体超时，超时后中断"}
    ],
    "isBuiltIn": true
  },
  {
    "id": "online_watermark_removal",
    "name": "在线去水印去字幕",
    "category": "process",
    "description": "晴沐智坊提供的在线高质量去除视频中的水印服务，使用前确保注册登录晴沐智坊账号，使用将消耗软件的通用积分，确保积分足够视频消耗，1.3分钱每秒。详情访问晴沐hub：https://www.licorxj.online/capability-hub",
    "icon": "Eraser",
    "color": "#8b5cf6",
    "inputs": [
      {"id": "url_json", "label": "媒体详情JSON", "type": "json"}
    ],
    "outputs": [
      {"id": "video", "label": "去水印视频", "type": "video"},
      {"id": "json", "label": "任务记录", "type": "json"}
    ],
    "defaultConfig": {
      "watermark_regions": [],
      "resume_request_id": "",
      "wm_mode": "normal"
    },
    "configFields": [
      {"key": "wm_mode", "label": "去水印模式", "type": "select", "colSpan": "full", "options": [
        {"value": "normal", "label": "普通模式（normal）"},
        {"value": "protect", "label": "保护模式（protect）"}
      ], "description": "普通模式：标准去水印；保护模式：更保守地处理，降低误伤风险"}
    ],
    "isBuiltIn": true
  },
  {
    "id": "qm_virtual_mailbox",
    "name": "QM虚拟邮箱",
    "category": "process",
    "description": "通过晴沐智坊虚拟邮箱发送邮件内容到转发目标。费用2分钱/条（投递计费）。详情访问：https://www.licorxj.online/mail-forwarding",
    "icon": "Mail",
    "color": "#10b981",
    "inputs": [
      {"id": "text", "label": "发送内容", "type": "text"}
    ],
    "outputs": [
      {"id": "json", "label": "发送结果", "type": "json"}
    ],
    "defaultConfig": {
      "mailbox_id": "",
      "content": ""
    },
    "configFields": [
      {"key": "content", "label": "手动设置发送内容", "type": "textarea", "colSpan": "full", "placeholder": "输入邮件正文内容（优先于连线输入）", "description": "手动输入的内容优先于连线传入的文本。留空则使用连线输入的文本或文本文件路径"}
    ],
    "isBuiltIn": true
  },
  {
    "id": "audio_cut_by_subtitle",
    "name": "按照字幕切割音频",
    "category": "audio",
    "description": "按 srt 字幕或句子 json 的时间轴切割音频，输出片段清单 json 与各音频片段",
    "icon": "Scissors",
    "color": "#22c55e",
    "inputs": [
      {"id": "audio", "label": "音频", "type": "audio", "required": true},
      {"id": "srt", "label": "SRT字幕", "type": "subtitle"},
      {"id": "json", "label": "句子JSON", "type": "json"}
    ],
    "outputs": [
      {"id": "json", "label": "切割信息", "type": "json"},
      {"id": "audio_segments", "label": "音频片段清单", "type": "audio_manifest"}
    ],
    "defaultConfig": {
      "output_format": "wav",
      "expand": 0.05
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
          {"value": "ogg", "label": "OGG (Vorbis)"}
        ],
        "description": "切割后音频片段的封装与编码格式"
      },
      {
        "key": "expand",
        "label": "切割点外扩(秒)",
        "type": "number",
        "description": "每段在首尾各外扩的秒数，避免裁掉首尾音节"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "video_cut_by_subtitle",
    "name": "按字幕切割视频",
    "category": "video",
    "description": "按 srt 字幕或句子 json 的时间轴切割视频，输出片段清单 json 与各视频片段",
    "icon": "Scissors",
    "color": "#0ea5e9",
    "inputs": [
      {"id": "video", "label": "视频", "type": "video", "required": true},
      {"id": "srt", "label": "SRT字幕", "type": "subtitle"},
      {"id": "json", "label": "句子JSON", "type": "json"}
    ],
    "outputs": [
      {"id": "json", "label": "切割信息", "type": "json"},
      {"id": "video_segments", "label": "视频片段清单", "type": "json"}
    ],
    "defaultConfig": {
      "output_format": "mp4",
      "expand": 0.05
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
          {"value": "webm", "label": "WebM (VP9/Opus)"}
        ],
        "description": "切割后视频片段的封装与编码格式"
      },
      {
        "key": "expand",
        "label": "切割点外扩(秒)",
        "type": "number",
        "description": "每段在首尾各外扩的秒数，避免裁掉首尾画面"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "output_merge_list",
    "name": "输出合并为列表",
    "category": "utility",
    "description": "将多个上游节点的输出（文本或路径）合并为列表格式 JSON，内存传递、不落盘；输入端口数量可在卡片上动态加减",
    "icon": "ListOrdered",
    "color": "#64748b",
    "dynamicPorts": true,
    "inputs": [],
    "outputs": [
      {"id": "json", "label": "列表JSON", "type": "json"}
    ],
    "defaultConfig": {
      "inputCount": 2
    },
    "configFields": [
      {
        "key": "inputCount",
        "label": "输入端口数",
        "type": "number",
        "min": 1,
        "max": 8,
        "description": "通过节点卡片上的 + / - 控制（1~8）"
      }
    ],
    "isBuiltIn": true
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
      {
        "id": "items",
        "label": "迭代对象",
        "type": "json",
        "required": false
      }
    ],
    "outputs": [
      {
        "id": "results",
        "label": "产物清单",
        "type": "json"
      },
      {
        "id": "count",
        "label": "迭代总数",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "itemsSource": "upstream",
      "inlineItems": "",
      "globPattern": "",
      "maxIterations": 0,
      "iterationConcurrency": 1,
      "onItemError": "stop",
      "itemAlias": "item",
      "indexAlias": "index"
    },
    "configFields": [
      {
        "key": "itemsSource",
        "label": "迭代对象来源",
        "type": "select",
        "options": [
          {"value": "upstream", "label": "上游连线输入"},
          {"value": "inline_json", "label": "内联 JSON 数组"},
          {"value": "directory_glob", "label": "目录文件匹配"}
        ],
        "description": "上游连线取 items 端口传入的列表；内联 JSON 直接填写数组；目录匹配按通配符扫描文件"
      },
      {
        "key": "inlineItems",
        "label": "内联 JSON 数组",
        "type": "textarea",
        "colSpan": "full",
        "dependsOn": "itemsSource",
        "dependsValue": "inline_json",
        "placeholder": "[\"a.mp4\", \"b.mp4\"] 或 [{\"path\": \"a.mp4\"}, {\"path\": \"b.mp4\"}]"
      },
      {
        "key": "globPattern",
        "label": "目录通配符",
        "type": "text",
        "colSpan": "full",
        "dependsOn": "itemsSource",
        "dependsValue": "directory_glob",
        "placeholder": "D:/videos/*.mp4"
      },
      {
        "key": "maxIterations",
        "label": "最大迭代数",
        "type": "number",
        "min": 0,
        "max": 500,
        "step": 1,
        "colSpan": "half",
        "description": "0 表示不限制（受全局上限 LOOP_MAX_ITEMS=500 约束）"
      },
      {
        "key": "iterationConcurrency",
        "label": "并发数",
        "type": "slider",
        "min": 1,
        "max": 16,
        "step": 1,
        "colSpan": "half",
        "description": "同时处理的迭代条目数；串行填 1"
      },
      {
        "key": "onItemError",
        "label": "单项失败策略",
        "type": "select",
        "colSpan": "half",
        "options": [
          {"value": "stop", "label": "立即停止"},
          {"value": "skip", "label": "跳过并继续"},
          {"value": "collect_error", "label": "记录错误后继续"}
        ]
      },
      {
        "key": "itemAlias",
        "label": "条目变量名",
        "type": "text",
        "colSpan": "half",
        "placeholder": "item",
        "description": "循环体节点配置中以 {item} 引用当前条目"
      },
      {
        "key": "indexAlias",
        "label": "序号变量名",
        "type": "text",
        "colSpan": "half",
        "placeholder": "index",
        "description": "循环体节点配置中以 {index} / {index:03d} 引用当前序号"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "image_grid_split",
    "name": "图片宫格切割",
    "category": "aigc",
    "description": "把宫格组合图按 N×N 切成单张图片：支持 4/9/16/25 宫格，可设置外框收缩与内部切缝收缩像素，输出切割后的图片路径列表",
    "icon": "Grid3x3",
    "color": "#22c55e",
    "inputs": [
      {
        "id": "image",
        "label": "图片",
        "type": "image",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "images",
        "label": "图片列表",
        "type": "list"
      }
    ],
    "defaultConfig": {
      "grid": "4",
      "outer_shrink": 0,
      "inner_shrink": 5
    },
    "configFields": [
      {
        "key": "grid",
        "label": "宫格选择",
        "type": "select",
        "colSpan": "full",
        "options": [
          { "value": "4", "label": "4宫格（2×2）" },
          { "value": "9", "label": "9宫格（3×3）" },
          { "value": "16", "label": "16宫格（4×4）" },
          { "value": "25", "label": "25宫格（5×5）" }
        ]
      },
      {
        "key": "outer_shrink",
        "label": "外框收缩像素",
        "type": "number",
        "min": 0,
        "step": 1,
        "colSpan": "half",
        "defaultValue": 0,
        "description": "切割前整图四边向内收缩的像素，用于去掉图片外框，默认 0"
      },
      {
        "key": "inner_shrink",
        "label": "内部切割收缩像素",
        "type": "number",
        "min": 0,
        "step": 1,
        "colSpan": "half",
        "defaultValue": 5,
        "description": "每个内部切缝两侧各向内收缩的像素，用于去掉格间接缝；与图片外边缘重合的边不收缩，默认 5"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "video_scale",
    "name": "视频缩放",
    "category": "video",
    "description": "使用 ffmpeg 将视频缩放到预置分辨率（按目标高度等比缩放）或自定义宽高，支持输出容器格式与编码质量（CRF）设置",
    "icon": "Ratio",
    "color": "#ef4444",
    "inputs": [
      {
        "id": "video",
        "label": "视频",
        "type": "video",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "video",
        "label": "缩放后视频",
        "type": "video"
      }
    ],
    "defaultConfig": {
      "scale_preset": "1080p",
      "custom_width": 1920,
      "custom_height": 1080,
      "output_format": "mp4",
      "video_quality": "medium"
    },
    "configFields": [
      {
        "key": "scale_preset",
        "label": "缩放尺寸",
        "type": "select",
        "colSpan": "full",
        "options": [
          { "value": "original", "label": "保持原始分辨率" },
          { "value": "2160p", "label": "4K（3840×2160）" },
          { "value": "1440p", "label": "2K（2560×1440）" },
          { "value": "1080p", "label": "1080P（1920×1080）" },
          { "value": "720p", "label": "720P（1280×720）" },
          { "value": "480p", "label": "480P（854×480）" },
          { "value": "360p", "label": "360P（640×360）" },
          { "value": "custom", "label": "自定义宽高" }
        ],
        "description": "预置档按目标高度等比缩放（宽度自动取偶），非 16:9 素材不变形；自定义档使用精确宽高"
      },
      {
        "key": "custom_width",
        "label": "自定义宽度(px)",
        "type": "number",
        "min": 16,
        "step": 1,
        "colSpan": "half",
        "defaultValue": 1920,
        "dependsOn": "scale_preset",
        "dependsValue": "custom"
      },
      {
        "key": "custom_height",
        "label": "自定义高度(px)",
        "type": "number",
        "min": 16,
        "step": 1,
        "colSpan": "half",
        "defaultValue": 1080,
        "dependsOn": "scale_preset",
        "dependsValue": "custom"
      },
      {
        "key": "output_format",
        "label": "输出格式",
        "type": "select",
        "colSpan": "half",
        "options": [
          { "value": "mp4", "label": "MP4（H.264 + AAC）" },
          { "value": "mkv", "label": "MKV（H.264 + AAC）" },
          { "value": "mov", "label": "MOV（H.264 + AAC）" },
          { "value": "flv", "label": "FLV（H.264 + AAC）" },
          { "value": "webm", "label": "WebM（VP9 + Opus）" },
          { "value": "avi", "label": "AVI（MPEG4 + MP3）" }
        ]
      },
      {
        "key": "video_quality",
        "label": "编码质量",
        "type": "select",
        "colSpan": "half",
        "options": [
          { "value": "high", "label": "高质量（CRF 18）" },
          { "value": "medium", "label": "中等（CRF 23）" },
          { "value": "low", "label": "低质量（CRF 28）" }
        ]
      }
    ],
    "isBuiltIn": true
  }
];

export const BUILTIN_NODE_TYPES = FALLBACK_NODE_TYPES;

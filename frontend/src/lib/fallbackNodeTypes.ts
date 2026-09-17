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
    "description": "给输入文件改名，支持自定义文件名、前缀、后缀，或从输入端口动态获取文件名；重名时自动追加序号",
    "icon": "FileEdit",
    "color": "#f97316",
    "inputs": [
      {
        "id": "any",
        "label": "输入",
        "type": "any",
        "required": true
      },
      {
        "id": "name",
        "label": "文件名(来自输入)",
        "type": "text",
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
          },
          {
            "value": "from_input",
            "label": "来自输入(文本端口)"
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
    "category": "network_request",
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
    "id": "batch_download",
    "name": "批量视频下载",
    "category": "network_request",
    "description": "使用 yt-dlp 的专辑/播放列表批量下载能力，一次下载整张专辑；产物统一保存到新建的专辑目录，并输出下载产物清单 JSON",
    "icon": "Download",
    "color": "#0891b2",
    "inputs": [
      {
        "id": "url",
        "label": "专辑/播放列表 URL",
        "type": "url",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "json",
        "label": "下载产物清单",
        "type": "json"
      },
      {
        "id": "folder",
        "label": "产物目录",
        "type": "text"
      },
      {
        "id": "video",
        "label": "首个视频",
        "type": "video"
      }
    ],
    "defaultConfig": {
      "download_subs": false,
      "download_cover": false,
      "resolution": "best",
      "cookie_file": "",
      "playlist_items": "",
      "max_items": 0,
      "folder_name": ""
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
        "key": "playlist_items",
        "label": "下载范围",
        "type": "text",
        "colSpan": "half",
        "placeholder": "留空=全部，如 1-10 / 1,3,5",
        "description": "yt-dlp --playlist-items 表达式，指定下载专辑中的哪些条目"
      },
      {
        "key": "max_items",
        "label": "最多下载条数",
        "type": "number",
        "colSpan": "half",
        "min": 0,
        "max": 1000,
        "step": 1,
        "defaultValue": 0,
        "description": "0 表示不限；按专辑顺序只下载前 N 条"
      },
      {
        "key": "folder_name",
        "label": "产物文件夹名",
        "type": "text",
        "colSpan": "full",
        "placeholder": "留空=自动使用专辑标题",
        "description": "产物统一保存到 output/batch_download/<名称>_<节点id>/"
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
    "category": "audio",
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
    "category": "audio",
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
        "apiEndpoint": "/api/separation-interfaces/config-fields?scope=vocal",
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
    "id": "audio_enhance",
    "name": "音频增强",
    "category": "audio",
    "description": "通过音频增强接口/模型处理音频（去混响、降噪、音质增强），输出增强后的音频",
    "icon": "Sparkles",
    "color": "#0ea5e9",
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
        "label": "增强音频",
        "type": "audio",
        "color": "#10b981"
      },
      {
        "id": "background",
        "label": "残差/副产物",
        "type": "audio",
        "color": "#f59e0b"
      },
      {
        "id": "extra",
        "label": "第三路输出",
        "type": "audio",
        "color": "#6366f1"
      }
    ],
    "defaultConfig": {
      "method": "mdx_net_onnx",
      "model": "",
      "format": "wav"
    },
    "configFields": [
      {
        "key": "method",
        "label": "增强接口",
        "type": "api-select",
        "apiEndpoint": "/api/separation-interfaces/enabled?scope=enhancement",
        "optionLabel": "name",
        "optionValue": "id",
        "colSpan": "full"
      },
      {
        "key": "model",
        "label": "增强模型",
        "type": "api-select",
        "apiEndpoint": "/api/separation-interfaces/config-fields?scope=enhancement",
        "dependsOn": "method",
        "optionLabel": "label",
        "optionValue": "value",
        "placeholder": "留空则使用接口的默认增强模型",
        "colSpan": "full"
      },
      {
        "key": "format",
        "label": "输出格式",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "",
            "label": "跟随全局设置"
          },
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
    "category": "audio",
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
    "category": "audio",
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
      "dialect_name": "四川话",
      "min_sentence_duration": 0.2,
      "speed_predict_reduce": false
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
      },
      {
        "key": "speed_predict_reduce",
        "label": "语速预测+句子缩减",
        "type": "checkbox",
        "description": "启用后预测每句 TTS 朗读时长（多语言兼容），预测时长远大于句子时间槽时由 LLM 缩减朗读文本；短句（中文<3字/英文<2词）不缩减"
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
    "category": "video",
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
    "category": "audio",
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
    "category": "audio",
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
    "category": "video",
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
    "id": "video_concat",
    "name": "视频拼接",
    "category": "video",
    "description": "将主视频/片段1~3/封面图按设定顺序与缩放方式一次性拼装为单个视频，封面图可选插入开头或结尾。",
    "icon": "Clapperboard",
    "color": "#3b82f6",
    "inputs": [
      { "id": "main", "label": "主视频", "type": "video", "required": false },
      { "id": "segment1", "label": "片段1", "type": "video", "required": false },
      { "id": "segment2", "label": "片段2", "type": "video", "required": false },
      { "id": "segment3", "label": "片段3", "type": "video", "required": false },
      { "id": "cover", "label": "封面图", "type": "image", "required": false }
    ],
    "outputs": [
      { "id": "video", "label": "拼接视频", "type": "video" }
    ],
    "defaultConfig": {
      "segment_order": ["main", "segment1", "segment2", "segment3"],
      "scale_mode": "stretch",
      "cover_position": "start",
      "cover_duration": 3,
      "output_format": "mp4"
    },
    "configFields": [
      {
        "key": "segment_order",
        "label": "片段排序",
        "type": "reorder-list",
        "options": [
          { "value": "main", "label": "主视频" },
          { "value": "segment1", "label": "片段1" },
          { "value": "segment2", "label": "片段2" },
          { "value": "segment3", "label": "片段3" }
        ],
        "description": "调整主视频与片段1/2/3 的拼接先后顺序（上下箭头排序）"
      },
      {
        "key": "scale_mode",
        "label": "片段尺寸缩放方式",
        "type": "select",
        "options": [
          { "value": "stretch", "label": "拉伸（填满，可能变形）" },
          { "value": "crop", "label": "裁切（等比覆盖，裁剪多余）" }
        ],
        "description": "各片段统一缩放到参考视频分辨率的方式"
      },
      {
        "key": "cover_position",
        "label": "封面图位置",
        "type": "select",
        "options": [
          { "value": "none", "label": "不插入" },
          { "value": "start", "label": "开头" },
          { "value": "end", "label": "结尾" }
        ]
      },
      {
        "key": "cover_duration",
        "label": "封面时长(秒)",
        "type": "number",
        "min": 0.1,
        "max": 60,
        "colSpan": "half",
        "dependsOn": "cover_position",
        "dependsValue": ["start", "end"],
        "placeholder": "3"
      },
      {
        "key": "output_format",
        "label": "输出格式",
        "type": "select",
        "colSpan": "half",
        "options": [
          { "value": "mp4", "label": "MP4" },
          { "value": "mkv", "label": "MKV" },
          { "value": "mov", "label": "MOV" },
          { "value": "webm", "label": "WebM" },
          { "value": "avi", "label": "AVI" }
        ]
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "material_storage",
    "name": "素材入库",
    "category": "asset",
    "description": "将接入的视频/图片/音频素材归档到项目公共素材库并写入数据库。后端自动识别素材类型，按前端设置的素材属性（名称/分组标签/自定义标签/描述）入库，支持视频、图片、音频三种类型。",
    "icon": "LibraryBig",
    "color": "#84cc16",
    "inputs": [
      { "id": "media", "label": "素材", "type": "any", "required": false }
    ],
    "outputs": [
      { "id": "material", "label": "素材路径", "type": "any" },
      { "id": "library_ref", "label": "素材库引用", "type": "text" },
      { "id": "asset_type", "label": "素材类型", "type": "text" },
      { "id": "asset_id", "label": "素材ID", "type": "text" }
    ],
    "defaultConfig": {
      "asset_name": "",
      "group_tags": "",
      "custom_tags": "",
      "description": ""
    },
    "configFields": [
      {
        "key": "asset_name",
        "label": "素材名称",
        "type": "text",
        "placeholder": "留空则使用文件名",
        "description": "入库后在素材库中显示的素材名称"
      },
      {
        "key": "group_tags",
        "label": "分组标签",
        "type": "text",
        "placeholder": "逗号分隔，如：宣传片,产品",
        "description": "按分组归类素材，便于素材库筛选"
      },
      {
        "key": "custom_tags",
        "label": "自定义标签",
        "type": "text",
        "placeholder": "逗号分隔，如：高清,竖屏",
        "description": "自定义检索标签（音频素材会作为素材标签写入）"
      },
      {
        "key": "description",
        "label": "素材描述",
        "type": "textarea",
        "placeholder": "对素材的补充说明",
        "description": "素材的备注信息，入库后记录在素材库"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "dub_visual_check",
    "name": "配音审听及微调",
    "category": "translation",
    "description": "读取上游配音任务 JSON，打开审听页面逐句试听与微调：可修改朗读文本/指令、更换参考音频、按语速重生单条或批量重生；本节点把上游输入 JSON 透传到输出（json），可选等待审听完成后再继续下游。",
    "icon": "ListMusic",
    "color": "#8b5cf6",
    "inputs": [
      { "id": "json", "label": "配音任务JSON", "type": "json", "required": false }
    ],
    "outputs": [
      { "id": "json", "label": "配音任务JSON", "type": "json" }
    ],
    "defaultConfig": {
      "wait_audition": false,
      "wait_seconds": 600
    },
    "configFields": [
      {
        "key": "open_check",
        "label": "打开检查页面",
        "type": "button",
        "description": "打开配音微调弹窗：分页列出每条配音，支持勾选、试听、更换参考音频、单条/批量重生与 TTS 接口设置"
      },
      {
        "key": "wait_audition",
        "label": "是否等待审听",
        "type": "checkbox",
        "description": "勾选后本节点进入等待：在检查页完成试听微调，到达等待时长后自动透传输入 JSON 到输出并继续下游"
      },
      {
        "key": "wait_seconds",
        "label": "等待时间（秒）",
        "type": "number",
        "min": 1,
        "max": 86400,
        "colSpan": "half",
        "dependsOn": "wait_audition",
        "dependsValue": true,
        "placeholder": "600",
        "description": "等待审听的最长时间（秒），到期后自动继续；仅在勾选「是否等待审听」时生效"
      }
    ],
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
    "category": "video",
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
        "id": "asr",
        "label": "asr格式json",
        "type": "json",
        "required": true
      },
      {
        "id": "subtitle",
        "label": "翻译结果JSON",
        "type": "json",
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
    "description": "接收上游剪辑项目JSON，按编辑指令对时间线二次精选，输出精选后的剪辑json",
    "icon": "Clapperboard",
    "color": "#10b981",
    "inputs": [
      {
        "id": "project",
        "label": "剪辑项目",
        "type": "json"
      },
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
      },
      {
        "key": "imagegen_iface_id",
        "label": "生图接口",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/imagegen-interfaces/enabled",
        "placeholder": "自动（按能力选择）"
      },
      {
        "key": "imagegen_model",
        "label": "生图模型",
        "type": "api-select",
        "colSpan": "half",
        "dependsOn": "imagegen_iface_id",
        "apiEndpoint": "/api/imagegen-interfaces/{imagegen_iface_id}/models-for-node?mode=txt2img",
        "placeholder": "跟随接口默认"
      },
      {
        "key": "videogen_iface_id",
        "label": "生视频接口",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/videogen-interfaces/enabled",
        "placeholder": "自动（按能力选择）"
      },
      {
        "key": "videogen_model",
        "label": "生视频模型",
        "type": "api-select",
        "colSpan": "half",
        "dependsOn": "videogen_iface_id",
        "apiEndpoint": "/api/videogen-interfaces/{videogen_iface_id}/models-for-node?mode=t2v",
        "placeholder": "跟随接口默认"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "project_init",
    "name": "剪辑项目初始化",
    "category": "cutia",
    "description": "收集上游素材并构造初始剪辑JSON（默认时间线骨架+素材清单），供「Cutia 交互剪辑」接力整理筛选",
    "icon": "Clapperboard",
    "color": "#0ea5e9",
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
        "id": "project",
        "label": "初始剪辑项目",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "arrange_tracks": true
    },
    "configFields": [
      {
        "key": "arrange_tracks",
        "label": "是否将素材加入轨道",
        "type": "checkbox",
        "colSpan": "half",
        "description": "关闭时只导入素材清单，不自动编排到时间线"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "add_media_to_library",
    "name": "添加素材到剪辑",
    "category": "video",
    "description": "将任意类型素材注册到剪辑工作台的素材库（不写入时间线轨道），供后续剪辑操作调用",
    "icon": "LibraryBig",
    "color": "#0d9488",
    "inputs": [
      {
        "id": "project",
        "label": "剪辑项目",
        "type": "json"
      },
      {
        "id": "media",
        "label": "素材",
        "type": "any"
      }
    ],
    "outputs": [
      {
        "id": "project",
        "label": "剪辑项目",
        "type": "json"
      }
    ],
    "defaultConfig": {},
    "configFields": [],
    "isBuiltIn": true
  },
  {
    "id": "add_track_media",
    "name": "添加剪辑素材到轨道",
    "category": "cutia",
    "description": "接收任意类型素材，按所选类型添加到剪辑项目轨道（可新建轨道/轨道尾部/自定义插入点），输出剪辑项目JSON",
    "icon": "Layers",
    "color": "#8b5cf6",
    "inputs": [
      {
        "id": "project",
        "label": "剪辑项目",
        "type": "json"
      },
      {
        "id": "media",
        "label": "素材",
        "type": "any"
      }
    ],
    "outputs": [
      {
        "id": "project",
        "label": "剪辑项目",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "media_type": "video",
      "new_track": false,
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
      "muted": false,
      "content": "",
      "font_size": 5,
      "font_family": "Arial",
      "color": "#ffffff",
      "background_color": "rgba(0, 0, 0, 0.7)",
      "text_align": "center",
      "font_weight": "normal"
    },
    "configFields": [
      {
        "key": "media_type",
        "label": "素材类型",
        "type": "select",
        "options": [
          { "value": "video", "label": "视频" },
          { "value": "audio", "label": "音频" },
          { "value": "image", "label": "图片" },
          { "value": "text", "label": "文字" }
        ]
      },
      {
        "key": "new_track",
        "label": "新建轨道添加",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "track_name",
        "label": "新轨道名称",
        "type": "text",
        "colSpan": "half",
        "dependsOn": "new_track",
        "placeholder": "留空自动命名"
      },
      {
        "key": "insert_mode",
        "label": "插入时间点",
        "type": "select",
        "options": [
          { "value": "end", "label": "插入到轨道尾部" },
          { "value": "custom", "label": "自定义插入点时间" }
        ]
      },
      {
        "key": "insert_time",
        "label": "插入点时间（秒）",
        "type": "number",
        "min": 0,
        "step": 0.1,
        "colSpan": "half",
        "dependsOn": "insert_mode",
        "dependsValue": "custom"
      },
      {
        "key": "static_duration",
        "label": "素材时长（秒）",
        "type": "number",
        "min": 0.1,
        "step": 0.1,
        "colSpan": "half",
        "placeholder": "仅图片/文字生效",
        "dependsOn": "media_type",
        "dependsValue": ["image", "text"]
      },
      {
        "key": "pos_x",
        "label": "X 坐标",
        "type": "number",
        "step": 1,
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": ["video", "image", "text"]
      },
      {
        "key": "pos_y",
        "label": "Y 坐标",
        "type": "number",
        "step": 1,
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": ["video", "image", "text"]
      },
      {
        "key": "scale",
        "label": "缩放",
        "type": "number",
        "min": 0.1,
        "step": 0.1,
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": ["video", "image"]
      },
      {
        "key": "rotate",
        "label": "旋转（度）",
        "type": "number",
        "step": 1,
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": ["video", "image"]
      },
      {
        "key": "opacity",
        "label": "不透明度",
        "type": "number",
        "min": 0,
        "max": 1,
        "step": 0.05,
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": ["video", "image"]
      },
      {
        "key": "volume",
        "label": "音量",
        "type": "number",
        "min": 0,
        "max": 2,
        "step": 0.1,
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": "audio"
      },
      {
        "key": "muted",
        "label": "静音",
        "type": "checkbox",
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": "audio"
      },
      {
        "key": "content",
        "label": "文字内容",
        "type": "textarea",
        "dependsOn": "media_type",
        "dependsValue": "text"
      },
      {
        "key": "font_size",
        "label": "字号",
        "type": "number",
        "min": 1,
        "step": 1,
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": "text"
      },
      {
        "key": "font_family",
        "label": "字体",
        "type": "text",
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": "text"
      },
      {
        "key": "color",
        "label": "文字颜色",
        "type": "text",
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": "text",
        "placeholder": "#ffffff"
      },
      {
        "key": "background_color",
        "label": "背景颜色",
        "type": "text",
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": "text",
        "placeholder": "rgba(0, 0, 0, 0.7)"
      },
      {
        "key": "text_align",
        "label": "对齐方式",
        "type": "select",
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": "text",
        "options": [
          { "value": "left", "label": "左对齐" },
          { "value": "center", "label": "居中" },
          { "value": "right", "label": "右对齐" }
        ]
      },
      {
        "key": "font_weight",
        "label": "字重",
        "type": "select",
        "colSpan": "half",
        "dependsOn": "media_type",
        "dependsValue": "text",
        "options": [
          { "value": "normal", "label": "常规" },
          { "value": "bold", "label": "加粗" }
        ]
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "cutia",
    "name": "推送到剪辑台",
    "category": "cutia",
    "description": "将剪辑项目JSON推送到剪辑工作台并发起系统提醒，等待剪辑后透传输出（素材编排由上游「剪辑项目初始化」完成）",
    "icon": "Clapperboard",
    "color": "#14b8a6",
    "inputs": [
      {
        "id": "project",
        "label": "剪辑项目",
        "type": "json"
      }
    ],
    "outputs": [
      {
        "id": "project",
        "label": "剪辑项目",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "wait_seconds": 600
    },
    "configFields": [
      {
        "key": "wait_seconds",
        "label": "等待剪辑时间（秒）",
        "type": "number",
        "min": 0,
        "colSpan": "half"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "cutia_render",
    "name": "剪辑渲染",
    "category": "cutia",
    "description": "接收上游精选后的剪辑项目JSON，无头加载并渲染导出成片，无需人工打开剪辑工作台",
    "icon": "Clapperboard",
    "color": "#f97316",
    "inputs": [
      {
        "id": "project",
        "label": "剪辑项目",
        "type": "json"
      }
    ],
    "outputs": [
      {
        "id": "video",
        "label": "渲染成片",
        "type": "video"
      }
    ],
    "defaultConfig": {
      "export_format": "mp4",
      "quality": "high",
      "fps": 0,
      "include_audio": true,
      "browser_channel": "",
      "timeout_minutes": 60
    },
    "configFields": [
      {
        "key": "export_format",
        "label": "导出格式",
        "type": "select",
        "options": [
          {
            "value": "mp4",
            "label": "MP4 (H.264)"
          },
          {
            "value": "webm",
            "label": "WebM (VP9)"
          }
        ]
      },
      {
        "key": "quality",
        "label": "画质",
        "type": "select",
        "options": [
          {
            "value": "low",
            "label": "低（体积最小）"
          },
          {
            "value": "medium",
            "label": "中（均衡）"
          },
          {
            "value": "high",
            "label": "高（推荐）"
          },
          {
            "value": "very_high",
            "label": "极高（体积最大）"
          }
        ]
      },
      {
        "key": "fps",
        "label": "帧率",
        "type": "number",
        "min": 0,
        "max": 60,
        "colSpan": "half",
        "placeholder": "0 表示跟随项目设置"
      },
      {
        "key": "include_audio",
        "label": "包含音频",
        "type": "checkbox",
        "colSpan": "half"
      },
      {
        "key": "browser_channel",
        "label": "浏览器通道",
        "type": "text",
        "colSpan": "half",
        "placeholder": "留空用内置 Chromium；需要 H.264 可填 chrome"
      },
      {
        "key": "timeout_minutes",
        "label": "超时（分钟）",
        "type": "number",
        "min": 1,
        "max": 720,
        "colSpan": "half"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "video_frame_extract",
    "name": "视频抽帧",
    "category": "video",
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
        "defaultValue": "suffix",
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
        "defaultValue": "suffix",
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
        "defaultValue": "suffix",
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
        "defaultValue": "suffix",
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
    "category": "file",
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
    "category": "utility",
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
    "category": "utility",
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
    "id": "json_get",
    "name": "JSON取值",
    "category": "utility",
    "description": "按key表达式从输入JSON中取值，输出端口数量可在卡片上用+号任意增加（1~8），每个端口下对应一个取值表达式；结果以any类型输出，数据不落盘（内存流转给下游，并写入任务数据库）",
    "icon": "Braces",
    "color": "#f97316",
    "dynamicPorts": true,
    "inputs": [
      {"id": "json", "label": "JSON", "type": "json"}
    ],
    "outputs": [
      {"id": "out_1", "label": "取值1", "type": "any"}
    ],
    "defaultConfig": {
      "outputCount": 1,
      "key_exprs": [""]
    },
    "configFields": [
      {
        "key": "outputCount",
        "label": "输出端口数",
        "type": "number",
        "min": 1,
        "max": 8,
        "description": "通过节点卡片上的 + / - 控制（1~8），每个端口对应一个取值表达式"
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
    "category": "video",
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
    "description": "开启后等待指定时长，超时可选择抛出错误或标记完成继续；关闭则跳过并透传输入。进入等待时会发送系统通知提醒用户。",
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
      "wait_seconds": 60,
      "timeout_action": "error"
    },
    "configFields": [
      {
        "key": "enabled",
        "label": "启用等待",
        "type": "toggle",
        "description": "开启后等待指定时长，超时按「超时操作」配置处理；关闭则跳过并透传输入"
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
      },
      {
        "key": "timeout_action",
        "label": "超时操作",
        "type": "select",
        "options": [
          { "value": "error", "label": "抛出错误（结束工作流）" },
          { "value": "complete", "label": "标记完成（继续执行下游）" }
        ],
        "colSpan": "full",
        "dependsOn": "enabled",
        "dependsValue": true
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
    "category": "video",
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
    "category": "network_request",
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
    "category": "video",
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
    "category": "network_request",
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
  },
  {
    "id": "music_txt2music",
    "name": "AI音乐-文生音乐",
    "category": "music_gen",
    "description": "根据提示词 / 歌词生成完整歌曲（含人声）。提示词可来自连线文本输入或节点内自定义；产物为音频。",
    "icon": "Music",
    "color": "#a78bfa",
    "inputs": [
      {
        "id": "text",
        "label": "提示词 / 歌词",
        "type": "text"
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "音频",
        "type": "audio"
      },
      {
        "id": "audios",
        "label": "音频列表",
        "type": "json"
      },
      {
        "id": "params",
        "label": "生成参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "interface": "",
      "model": "",
      "custom_prompt_enabled": false,
      "custom_prompt": "",
      "poll_timeout": 600,
      "instrumental": false,
      "duration": "60"
    },
    "configFields": [
      {
        "key": "interface",
        "label": "音乐接口",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id",
        "placeholder": "跟随全局默认接口"
      },
      {
        "key": "model",
        "label": "模型",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/{interface}/models-for-node?mode=txt2music",
        "dependsOn": "interface",
        "placeholder": "跟随接口默认模型"
      },
      {
        "key": "custom_prompt_enabled",
        "label": "使用节点内提示词",
        "type": "toggle",
        "colSpan": "half",
        "description": "关闭时使用上游连线的文本输入；开启后优先使用下方「自定义提示词」"
      },
      {
        "key": "custom_prompt",
        "label": "自定义提示词",
        "type": "textarea",
        "colSpan": "full",
        "dependsOn": "custom_prompt_enabled",
        "dependsValue": true,
        "placeholder": "输入提示词 / 歌词 / 风格描述（开启「使用节点内提示词」后生效）"
      },
      {
        "key": "style",
        "label": "音乐风格",
        "type": "text",
        "colSpan": "half",
        "placeholder": "如：pop, cinematic, lo-fi"
      },
      {
        "key": "title",
        "label": "歌曲标题",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "instrumental",
        "label": "纯音乐(无歌词)",
        "type": "toggle",
        "colSpan": "half"
      },
      {
        "key": "duration",
        "label": "时长",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "15",
            "label": "15 秒"
          },
          {
            "value": "30",
            "label": "30 秒"
          },
          {
            "value": "60",
            "label": "60 秒"
          },
          {
            "value": "120",
            "label": "120 秒"
          },
          {
            "value": "240",
            "label": "240 秒"
          }
        ]
      },
      {
        "key": "negative_tags",
        "label": "反向标签",
        "type": "text",
        "colSpan": "half",
        "placeholder": "逗号分隔，如：heavy metal"
      },
      {
        "key": "vocal_gender",
        "label": "人声性别",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "",
            "label": "不指定"
          },
          {
            "value": "male",
            "label": "男声"
          },
          {
            "value": "female",
            "label": "女声"
          },
          {
            "value": "girl",
            "label": "少女"
          },
          {
            "value": "boy",
            "label": "少年"
          },
          {
            "value": "woman",
            "label": "成熟女声"
          },
          {
            "value": "man",
            "label": "成熟男声"
          },
          {
            "value": "children",
            "label": "童声"
          },
          {
            "value": "young boy",
            "label": "年轻男声"
          },
          {
            "value": "young girl",
            "label": "年轻女声"
          }
        ]
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 3600,
        "colSpan": "half",
        "description": "生成任务最长等待时间，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "music_instrumental",
    "name": "AI音乐-纯音乐",
    "category": "music_gen",
    "description": "根据风格描述生成无人声的纯音乐 / 伴奏。提示词可来自连线文本输入或节点内自定义。",
    "icon": "Music2",
    "color": "#a78bfa",
    "inputs": [
      {
        "id": "text",
        "label": "提示词 / 歌词",
        "type": "text"
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "音频",
        "type": "audio"
      },
      {
        "id": "audios",
        "label": "音频列表",
        "type": "json"
      },
      {
        "id": "params",
        "label": "生成参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "interface": "",
      "model": "",
      "custom_prompt_enabled": false,
      "custom_prompt": "",
      "poll_timeout": 600,
      "duration": "60"
    },
    "configFields": [
      {
        "key": "interface",
        "label": "音乐接口",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id",
        "placeholder": "跟随全局默认接口"
      },
      {
        "key": "model",
        "label": "模型",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/{interface}/models-for-node?mode=instrumental",
        "dependsOn": "interface",
        "placeholder": "跟随接口默认模型"
      },
      {
        "key": "custom_prompt_enabled",
        "label": "使用节点内提示词",
        "type": "toggle",
        "colSpan": "half",
        "description": "关闭时使用上游连线的文本输入；开启后优先使用下方「自定义提示词」"
      },
      {
        "key": "custom_prompt",
        "label": "自定义提示词",
        "type": "textarea",
        "colSpan": "full",
        "dependsOn": "custom_prompt_enabled",
        "dependsValue": true,
        "placeholder": "输入提示词 / 歌词 / 风格描述（开启「使用节点内提示词」后生效）"
      },
      {
        "key": "style",
        "label": "音乐风格",
        "type": "text",
        "colSpan": "half",
        "placeholder": "如：piano, ambient, epic"
      },
      {
        "key": "title",
        "label": "曲目标题",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "duration",
        "label": "时长",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "15",
            "label": "15 秒"
          },
          {
            "value": "30",
            "label": "30 秒"
          },
          {
            "value": "60",
            "label": "60 秒"
          },
          {
            "value": "120",
            "label": "120 秒"
          },
          {
            "value": "240",
            "label": "240 秒"
          }
        ]
      },
      {
        "key": "negative_tags",
        "label": "反向标签",
        "type": "text",
        "colSpan": "half",
        "placeholder": "逗号分隔"
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 3600,
        "colSpan": "half",
        "description": "生成任务最长等待时间，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "music_lyrics",
    "name": "AI音乐-歌词生成",
    "category": "music_gen",
    "description": "根据主题描述生成歌词文本（不产出音频）。主题可来自连线文本输入或节点内自定义；输出歌词文本供「文生音乐」等节点使用。",
    "icon": "ListMusic",
    "color": "#a78bfa",
    "inputs": [
      {
        "id": "text",
        "label": "提示词 / 歌词",
        "type": "text"
      }
    ],
    "outputs": [
      {
        "id": "text",
        "label": "歌词文本",
        "type": "text"
      },
      {
        "id": "params",
        "label": "生成参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "interface": "",
      "model": "",
      "custom_prompt_enabled": false,
      "custom_prompt": "",
      "poll_timeout": 600
    },
    "configFields": [
      {
        "key": "interface",
        "label": "音乐接口",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id",
        "placeholder": "跟随全局默认接口"
      },
      {
        "key": "model",
        "label": "模型",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/{interface}/models-for-node?mode=lyrics",
        "dependsOn": "interface",
        "placeholder": "跟随接口默认模型"
      },
      {
        "key": "custom_prompt_enabled",
        "label": "使用节点内提示词",
        "type": "toggle",
        "colSpan": "half",
        "description": "关闭时使用上游连线的文本输入；开启后优先使用下方「自定义提示词」"
      },
      {
        "key": "custom_prompt",
        "label": "自定义提示词",
        "type": "textarea",
        "colSpan": "full",
        "dependsOn": "custom_prompt_enabled",
        "dependsValue": true,
        "placeholder": "输入提示词 / 歌词 / 风格描述（开启「使用节点内提示词」后生效）"
      },
      {
        "key": "style",
        "label": "音乐风格",
        "type": "text",
        "colSpan": "half",
        "placeholder": "如：pop, rock"
      },
      {
        "key": "title",
        "label": "歌曲标题",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 3600,
        "colSpan": "half",
        "description": "生成任务最长等待时间，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "music_extend",
    "name": "AI音乐-音乐扩展",
    "category": "music_gen",
    "description": "对已有曲目做续写扩展：从上游音乐节点的参数 JSON 取 audio_id（也可直接填 audio_id），可指定续写起点与续写提示词。",
    "icon": "Repeat",
    "color": "#a78bfa",
    "inputs": [
      {
        "id": "json",
        "label": "上游音乐参数JSON",
        "type": "json"
      },
      {
        "id": "text",
        "label": "续写提示词",
        "type": "text"
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "音频",
        "type": "audio"
      },
      {
        "id": "audios",
        "label": "音频列表",
        "type": "json"
      },
      {
        "id": "params",
        "label": "生成参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "interface": "",
      "model": "",
      "custom_prompt_enabled": false,
      "custom_prompt": "",
      "poll_timeout": 600
    },
    "configFields": [
      {
        "key": "interface",
        "label": "音乐接口",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id",
        "placeholder": "跟随全局默认接口"
      },
      {
        "key": "model",
        "label": "模型",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/{interface}/models-for-node?mode=extend",
        "dependsOn": "interface",
        "placeholder": "跟随接口默认模型"
      },
      {
        "key": "custom_prompt_enabled",
        "label": "使用节点内提示词",
        "type": "toggle",
        "colSpan": "half",
        "description": "关闭时使用上游连线的文本输入；开启后优先使用下方「自定义提示词」"
      },
      {
        "key": "custom_prompt",
        "label": "自定义提示词",
        "type": "textarea",
        "colSpan": "full",
        "dependsOn": "custom_prompt_enabled",
        "dependsValue": true,
        "placeholder": "输入提示词 / 歌词 / 风格描述（开启「使用节点内提示词」后生效）"
      },
      {
        "key": "audio_id",
        "label": "音频ID",
        "type": "text",
        "colSpan": "half",
        "description": "留空则自动从上游参数 JSON 中读取 audio_id",
        "placeholder": "上游传入时留空"
      },
      {
        "key": "continue_at",
        "label": "续写起点(秒)",
        "type": "number",
        "min": 0,
        "colSpan": "half",
        "description": "从原曲的第 N 秒开始续写"
      },
      {
        "key": "default_param_flag",
        "label": "沿用原曲参数",
        "type": "toggle",
        "colSpan": "half"
      },
      {
        "key": "style",
        "label": "音乐风格",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "title",
        "label": "歌曲标题",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "instrumental",
        "label": "纯音乐",
        "type": "toggle",
        "colSpan": "half"
      },
      {
        "key": "negative_tags",
        "label": "反向标签",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "vocal_gender",
        "label": "人声性别",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "",
            "label": "不指定"
          },
          {
            "value": "male",
            "label": "男声"
          },
          {
            "value": "female",
            "label": "女声"
          },
          {
            "value": "girl",
            "label": "少女"
          },
          {
            "value": "boy",
            "label": "少年"
          },
          {
            "value": "woman",
            "label": "成熟女声"
          },
          {
            "value": "man",
            "label": "成熟男声"
          },
          {
            "value": "children",
            "label": "童声"
          },
          {
            "value": "young boy",
            "label": "年轻男声"
          },
          {
            "value": "young girl",
            "label": "年轻女声"
          }
        ]
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 3600,
        "colSpan": "half",
        "description": "生成任务最长等待时间，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "music_cover",
    "name": "AI音乐-翻唱/风格迁移",
    "category": "music_gen",
    "description": "上传参考音频并按提示词 / 风格做翻唱或风格迁移。参考音频从连线 audio 输入（本地文件自动上传）。",
    "icon": "Disc",
    "color": "#a78bfa",
    "inputs": [
      {
        "id": "audio",
        "label": "参考音频",
        "type": "audio"
      },
      {
        "id": "text",
        "label": "风格/提示词",
        "type": "text"
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "音频",
        "type": "audio"
      },
      {
        "id": "audios",
        "label": "音频列表",
        "type": "json"
      },
      {
        "id": "params",
        "label": "生成参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "interface": "",
      "model": "",
      "custom_prompt_enabled": false,
      "custom_prompt": "",
      "poll_timeout": 600
    },
    "configFields": [
      {
        "key": "interface",
        "label": "音乐接口",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id",
        "placeholder": "跟随全局默认接口"
      },
      {
        "key": "model",
        "label": "模型",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/{interface}/models-for-node?mode=cover",
        "dependsOn": "interface",
        "placeholder": "跟随接口默认模型"
      },
      {
        "key": "custom_prompt_enabled",
        "label": "使用节点内提示词",
        "type": "toggle",
        "colSpan": "half",
        "description": "关闭时使用上游连线的文本输入；开启后优先使用下方「自定义提示词」"
      },
      {
        "key": "custom_prompt",
        "label": "自定义提示词",
        "type": "textarea",
        "colSpan": "full",
        "dependsOn": "custom_prompt_enabled",
        "dependsValue": true,
        "placeholder": "输入提示词 / 歌词 / 风格描述（开启「使用节点内提示词」后生效）"
      },
      {
        "key": "style",
        "label": "目标风格",
        "type": "text",
        "colSpan": "half",
        "placeholder": "如：jazz, electronic"
      },
      {
        "key": "title",
        "label": "曲目标题",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "custom_mode",
        "label": "自定义模式",
        "type": "toggle",
        "colSpan": "half",
        "description": "开启后使用节点内的风格/标题/提示词，否则由模型自动推断"
      },
      {
        "key": "instrumental",
        "label": "纯音乐",
        "type": "toggle",
        "colSpan": "half"
      },
      {
        "key": "negative_tags",
        "label": "反向标签",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "vocal_gender",
        "label": "人声性别",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "",
            "label": "不指定"
          },
          {
            "value": "male",
            "label": "男声"
          },
          {
            "value": "female",
            "label": "女声"
          },
          {
            "value": "girl",
            "label": "少女"
          },
          {
            "value": "boy",
            "label": "少年"
          },
          {
            "value": "woman",
            "label": "成熟女声"
          },
          {
            "value": "man",
            "label": "成熟男声"
          },
          {
            "value": "children",
            "label": "童声"
          },
          {
            "value": "young boy",
            "label": "年轻男声"
          },
          {
            "value": "young girl",
            "label": "年轻女声"
          }
        ]
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 3600,
        "colSpan": "half",
        "description": "生成任务最长等待时间，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "music_add_instrumental",
    "name": "AI音乐-添加伴奏",
    "category": "music_gen",
    "description": "为人声 / 干声轨道添加伴奏：上传音频后生成带伴奏的完整曲目。",
    "icon": "Guitar",
    "color": "#a78bfa",
    "inputs": [
      {
        "id": "audio",
        "label": "人声音频",
        "type": "audio"
      },
      {
        "id": "text",
        "label": "标题/标签",
        "type": "text"
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "音频",
        "type": "audio"
      },
      {
        "id": "audios",
        "label": "音频列表",
        "type": "json"
      },
      {
        "id": "params",
        "label": "生成参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "interface": "",
      "model": "",
      "custom_prompt_enabled": false,
      "custom_prompt": "",
      "poll_timeout": 600
    },
    "configFields": [
      {
        "key": "interface",
        "label": "音乐接口",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id",
        "placeholder": "跟随全局默认接口"
      },
      {
        "key": "model",
        "label": "模型",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/{interface}/models-for-node?mode=add_instrumental",
        "dependsOn": "interface",
        "placeholder": "跟随接口默认模型"
      },
      {
        "key": "custom_prompt_enabled",
        "label": "使用节点内提示词",
        "type": "toggle",
        "colSpan": "half",
        "description": "关闭时使用上游连线的文本输入；开启后优先使用下方「自定义提示词」"
      },
      {
        "key": "custom_prompt",
        "label": "自定义提示词",
        "type": "textarea",
        "colSpan": "full",
        "dependsOn": "custom_prompt_enabled",
        "dependsValue": true,
        "placeholder": "输入提示词 / 歌词 / 风格描述（开启「使用节点内提示词」后生效）"
      },
      {
        "key": "title",
        "label": "曲目标题",
        "type": "text",
        "colSpan": "half",
        "description": "留空则自动取提示词前 60 字符"
      },
      {
        "key": "tags",
        "label": "风格标签",
        "type": "text",
        "colSpan": "half",
        "placeholder": "如：pop, energetic"
      },
      {
        "key": "negative_tags",
        "label": "反向标签",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "vocal_gender",
        "label": "人声性别",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "",
            "label": "不指定"
          },
          {
            "value": "male",
            "label": "男声"
          },
          {
            "value": "female",
            "label": "女声"
          },
          {
            "value": "girl",
            "label": "少女"
          },
          {
            "value": "boy",
            "label": "少年"
          },
          {
            "value": "woman",
            "label": "成熟女声"
          },
          {
            "value": "man",
            "label": "成熟男声"
          },
          {
            "value": "children",
            "label": "童声"
          },
          {
            "value": "young boy",
            "label": "年轻男声"
          },
          {
            "value": "young girl",
            "label": "年轻女声"
          }
        ]
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 3600,
        "colSpan": "half",
        "description": "生成任务最长等待时间，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "music_add_vocals",
    "name": "AI音乐-添加人声",
    "category": "music_gen",
    "description": "为伴奏 /  instrumental 轨道添加人声：上传音频并提供歌词或演唱提示词。",
    "icon": "Mic",
    "color": "#a78bfa",
    "inputs": [
      {
        "id": "audio",
        "label": "伴奏音频",
        "type": "audio"
      },
      {
        "id": "text",
        "label": "歌词/演唱提示",
        "type": "text"
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "音频",
        "type": "audio"
      },
      {
        "id": "audios",
        "label": "音频列表",
        "type": "json"
      },
      {
        "id": "params",
        "label": "生成参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "interface": "",
      "model": "",
      "custom_prompt_enabled": false,
      "custom_prompt": "",
      "poll_timeout": 600
    },
    "configFields": [
      {
        "key": "interface",
        "label": "音乐接口",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id",
        "placeholder": "跟随全局默认接口"
      },
      {
        "key": "model",
        "label": "模型",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/{interface}/models-for-node?mode=add_vocals",
        "dependsOn": "interface",
        "placeholder": "跟随接口默认模型"
      },
      {
        "key": "custom_prompt_enabled",
        "label": "使用节点内提示词",
        "type": "toggle",
        "colSpan": "half",
        "description": "关闭时使用上游连线的文本输入；开启后优先使用下方「自定义提示词」"
      },
      {
        "key": "custom_prompt",
        "label": "自定义提示词",
        "type": "textarea",
        "colSpan": "full",
        "dependsOn": "custom_prompt_enabled",
        "dependsValue": true,
        "placeholder": "输入提示词 / 歌词 / 风格描述（开启「使用节点内提示词」后生效）"
      },
      {
        "key": "title",
        "label": "曲目标题",
        "type": "text",
        "colSpan": "half",
        "description": "留空则自动取提示词前 60 字符"
      },
      {
        "key": "style",
        "label": "音乐风格",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "negative_tags",
        "label": "反向标签",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "vocal_gender",
        "label": "人声性别",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "",
            "label": "不指定"
          },
          {
            "value": "male",
            "label": "男声"
          },
          {
            "value": "female",
            "label": "女声"
          },
          {
            "value": "girl",
            "label": "少女"
          },
          {
            "value": "boy",
            "label": "少年"
          },
          {
            "value": "woman",
            "label": "成熟女声"
          },
          {
            "value": "man",
            "label": "成熟男声"
          },
          {
            "value": "children",
            "label": "童声"
          },
          {
            "value": "young boy",
            "label": "年轻男声"
          },
          {
            "value": "young girl",
            "label": "年轻女声"
          }
        ]
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 3600,
        "colSpan": "half",
        "description": "生成任务最长等待时间，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "music_separate",
    "name": "AI音乐-人声分离",
    "category": "music_gen",
    "description": "对已有曲目做分轨分离（人声 / 伴奏 / 鼓 / 贝斯等）。可接上游音频文件，也可从上游参数 JSON 取 task_id / audio_id。",
    "icon": "Scissors",
    "color": "#a78bfa",
    "inputs": [
      {
        "id": "text",
        "label": "提示词 / 歌词",
        "type": "text"
      },
      {
        "id": "audio",
        "label": "待分离音频",
        "type": "audio"
      },
      {
        "id": "json",
        "label": "上游音乐参数JSON",
        "type": "json"
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "音频",
        "type": "audio"
      },
      {
        "id": "audios",
        "label": "音频列表",
        "type": "json"
      },
      {
        "id": "params",
        "label": "生成参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "interface": "",
      "model": "",
      "custom_prompt_enabled": false,
      "custom_prompt": "",
      "poll_timeout": 600
    },
    "configFields": [
      {
        "key": "interface",
        "label": "音乐接口",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id",
        "placeholder": "跟随全局默认接口"
      },
      {
        "key": "model",
        "label": "模型",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/{interface}/models-for-node?mode=separate",
        "dependsOn": "interface",
        "placeholder": "跟随接口默认模型"
      },
      {
        "key": "custom_prompt_enabled",
        "label": "使用节点内提示词",
        "type": "toggle",
        "colSpan": "half",
        "description": "关闭时使用上游连线的文本输入；开启后优先使用下方「自定义提示词」"
      },
      {
        "key": "custom_prompt",
        "label": "自定义提示词",
        "type": "textarea",
        "colSpan": "full",
        "dependsOn": "custom_prompt_enabled",
        "dependsValue": true,
        "placeholder": "输入提示词 / 歌词 / 风格描述（开启「使用节点内提示词」后生效）"
      },
      {
        "key": "stem_type",
        "label": "分离类型",
        "type": "text",
        "colSpan": "half",
        "placeholder": "all / vocals / instrumental / drums / bass",
        "description": "留空默认 all（分离为人声 + 伴奏）"
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 3600,
        "colSpan": "half",
        "description": "生成任务最长等待时间，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "music_to_wav",
    "name": "AI音乐-转WAV",
    "category": "music_gen",
    "description": "把已有曲目转换为 WAV 无损格式：从上游音乐节点的参数 JSON 取 task_id / audio_id。",
    "icon": "FileAudio",
    "color": "#a78bfa",
    "inputs": [
      {
        "id": "json",
        "label": "上游音乐参数JSON",
        "type": "json"
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "WAV音频",
        "type": "audio"
      },
      {
        "id": "params",
        "label": "生成参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "interface": "",
      "model": "",
      "custom_prompt_enabled": false,
      "custom_prompt": "",
      "poll_timeout": 600
    },
    "configFields": [
      {
        "key": "interface",
        "label": "音乐接口",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id",
        "placeholder": "跟随全局默认接口"
      },
      {
        "key": "model",
        "label": "模型",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/{interface}/models-for-node?mode=to_wav",
        "dependsOn": "interface",
        "placeholder": "跟随接口默认模型"
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 3600,
        "colSpan": "half",
        "description": "生成任务最长等待时间，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "music_upload_extend",
    "name": "AI音乐-上传并扩展",
    "category": "music_gen",
    "description": "上传本地音频并续写扩展：参考音频从连线 audio 输入，可指定续写起点与提示词。",
    "icon": "Repeat2",
    "color": "#a78bfa",
    "inputs": [
      {
        "id": "audio",
        "label": "本地音频",
        "type": "audio"
      },
      {
        "id": "text",
        "label": "续写提示词",
        "type": "text"
      }
    ],
    "outputs": [
      {
        "id": "audio",
        "label": "音频",
        "type": "audio"
      },
      {
        "id": "audios",
        "label": "音频列表",
        "type": "json"
      },
      {
        "id": "params",
        "label": "生成参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "interface": "",
      "model": "",
      "custom_prompt_enabled": false,
      "custom_prompt": "",
      "poll_timeout": 600
    },
    "configFields": [
      {
        "key": "interface",
        "label": "音乐接口",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/enabled",
        "optionLabel": "name",
        "optionValue": "id",
        "placeholder": "跟随全局默认接口"
      },
      {
        "key": "model",
        "label": "模型",
        "type": "api-select",
        "colSpan": "half",
        "apiEndpoint": "/api/musicgen-interfaces/{interface}/models-for-node?mode=upload_extend",
        "dependsOn": "interface",
        "placeholder": "跟随接口默认模型"
      },
      {
        "key": "custom_prompt_enabled",
        "label": "使用节点内提示词",
        "type": "toggle",
        "colSpan": "half",
        "description": "关闭时使用上游连线的文本输入；开启后优先使用下方「自定义提示词」"
      },
      {
        "key": "custom_prompt",
        "label": "自定义提示词",
        "type": "textarea",
        "colSpan": "full",
        "dependsOn": "custom_prompt_enabled",
        "dependsValue": true,
        "placeholder": "输入提示词 / 歌词 / 风格描述（开启「使用节点内提示词」后生效）"
      },
      {
        "key": "continue_at",
        "label": "续写起点(秒)",
        "type": "number",
        "min": 0,
        "colSpan": "half"
      },
      {
        "key": "default_param_flag",
        "label": "沿用原曲参数",
        "type": "toggle",
        "colSpan": "half"
      },
      {
        "key": "style",
        "label": "音乐风格",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "title",
        "label": "歌曲标题",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "instrumental",
        "label": "纯音乐",
        "type": "toggle",
        "colSpan": "half"
      },
      {
        "key": "negative_tags",
        "label": "反向标签",
        "type": "text",
        "colSpan": "half"
      },
      {
        "key": "vocal_gender",
        "label": "人声性别",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "",
            "label": "不指定"
          },
          {
            "value": "male",
            "label": "男声"
          },
          {
            "value": "female",
            "label": "女声"
          },
          {
            "value": "girl",
            "label": "少女"
          },
          {
            "value": "boy",
            "label": "少年"
          },
          {
            "value": "woman",
            "label": "成熟女声"
          },
          {
            "value": "man",
            "label": "成熟男声"
          },
          {
            "value": "children",
            "label": "童声"
          },
          {
            "value": "young boy",
            "label": "年轻男声"
          },
          {
            "value": "young girl",
            "label": "年轻女声"
          }
        ]
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 3600,
        "colSpan": "half",
        "description": "生成任务最长等待时间，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "kie_image_upscale",
    "name": "图片高清放大-kie",
    "category": "ai_gen",
    "description": "调用 KIE AI 对图片做高清放大。使用前请先注册 KIE 账号并获取 API Key：点击卡片上方「获取key」前往官网注册，拿到 Key 后填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY（也可在系统环境变量中设置同名变量）；调用量与扣费明细可点击「用量日志」查看。",
    "icon": "ZoomIn",
    "color": "#0ea5e9",
    "inputs": [
      {
        "id": "image",
        "label": "待放大图片",
        "type": "image",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "image",
        "label": "放大后图片",
        "type": "image"
      },
      {
        "id": "images",
        "label": "图片列表",
        "type": "json"
      },
      {
        "id": "params",
        "label": "处理参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "model": "recraft/crisp-upscale",
      "upscale_factor": "2",
      "poll_timeout": 600
    },
    "configFields": [
      {
        "key": "btn_get_key",
        "label": "获取key",
        "type": "button",
        "colSpan": "half",
        "url": "https://kie.ai?ref=1ef5b0d4df5fc43ae85034755f9bf754",
        "description": "前往 KIE 官网注册并获取 API Key"
      },
      {
        "key": "btn_usage_logs",
        "label": "用量日志",
        "type": "button",
        "colSpan": "half",
        "url": "https://kie.ai/zh-CN/logs",
        "description": "在 KIE 控制台查看调用量与扣费明细"
      },
      {
        "key": "model",
        "label": "放大模型",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "recraft/crisp-upscale",
            "label": "Recraft Crisp Upscale（锐利放大，$0.0025/张）"
          },
          {
            "value": "topaz/image-upscale",
            "label": "Topaz Image Upscale（可设倍数，$0.2/张）"
          }
        ],
        "description": "KIE 平台提供的放大模型"
      },
      {
        "key": "upscale_factor",
        "label": "放大倍数",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "1",
            "label": "1 倍"
          },
          {
            "value": "2",
            "label": "2 倍"
          },
          {
            "value": "4",
            "label": "4 倍"
          }
        ],
        "dependsOn": "model",
        "dependsValue": "topaz/image-upscale",
        "description": "仅 Topaz 模型支持；Recraft 为固定锐利放大"
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 3600,
        "colSpan": "half",
        "description": "放大任务最长等待时间，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "kie_video_upscale",
    "name": "视频高清放大-kie",
    "category": "ai_gen",
    "description": "调用 KIE AI 对视频做高清放大。使用前请先注册 KIE 账号并获取 API Key：点击卡片上方「获取key」前往官网注册，拿到 Key 后填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY（也可在系统环境变量中设置同名变量）；调用量与扣费明细可点击「用量日志」查看。",
    "icon": "Film",
    "color": "#0ea5e9",
    "inputs": [
      {
        "id": "video",
        "label": "待放大视频",
        "type": "video",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "video",
        "label": "放大后视频",
        "type": "video"
      },
      {
        "id": "videos",
        "label": "视频列表",
        "type": "json"
      },
      {
        "id": "params",
        "label": "处理参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "model": "topaz/video-upscale",
      "upscale_factor": "2",
      "poll_timeout": 900
    },
    "configFields": [
      {
        "key": "btn_get_key",
        "label": "获取key",
        "type": "button",
        "colSpan": "half",
        "url": "https://kie.ai?ref=1ef5b0d4df5fc43ae85034755f9bf754",
        "description": "前往 KIE 官网注册并获取 API Key"
      },
      {
        "key": "btn_usage_logs",
        "label": "用量日志",
        "type": "button",
        "colSpan": "half",
        "url": "https://kie.ai/zh-CN/logs",
        "description": "在 KIE 控制台查看调用量与扣费明细"
      },
      {
        "key": "model",
        "label": "放大模型",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "topaz/video-upscale",
            "label": "Topaz Video Upscale（可设倍数，$0.07/次）"
          }
        ],
        "description": "KIE 平台提供的视频放大模型"
      },
      {
        "key": "upscale_factor",
        "label": "放大倍数",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "1",
            "label": "1 倍"
          },
          {
            "value": "2",
            "label": "2 倍"
          },
          {
            "value": "4",
            "label": "4 倍"
          }
        ],
        "description": "放大倍数，留空/默认 2 倍"
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 7200,
        "colSpan": "half",
        "description": "视频放大耗时较长，默认 900 秒，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "kie_lip_sync",
    "name": "视频对口型-kie",
    "category": "ai_gen",
    "description": "调用 KIE AI 让视频人物口型匹配目标音频（视频 + 音频 → 对口型视频）。使用前请先注册 KIE 账号并获取 API Key：点击卡片上方「获取key」前往官网注册，拿到 Key 后填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY（也可在系统环境变量中设置同名变量）；调用量与扣费明细可点击「用量日志」查看。",
    "icon": "Mic",
    "color": "#0ea5e9",
    "inputs": [
      {
        "id": "video",
        "label": "待对口型视频",
        "type": "video",
        "required": true
      },
      {
        "id": "audio",
        "label": "目标音频",
        "type": "audio",
        "required": true
      }
    ],
    "outputs": [
      {
        "id": "video",
        "label": "对口型视频",
        "type": "video"
      },
      {
        "id": "videos",
        "label": "视频列表",
        "type": "json"
      },
      {
        "id": "params",
        "label": "处理参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "model": "volcengine/video-to-video-lip-sync",
      "mode": "basic",
      "separate_vocal": false,
      "open_scenedet": false,
      "align_audio": true,
      "align_audio_reverse": false,
      "templ_start_seconds": 0,
      "poll_timeout": 900
    },
    "configFields": [
      {
        "key": "btn_get_key",
        "label": "获取key",
        "type": "button",
        "colSpan": "half",
        "url": "https://kie.ai?ref=1ef5b0d4df5fc43ae85034755f9bf754",
        "description": "前往 KIE 官网注册并获取 API Key"
      },
      {
        "key": "btn_usage_logs",
        "label": "用量日志",
        "type": "button",
        "colSpan": "half",
        "url": "https://kie.ai/zh-CN/logs",
        "description": "在 KIE 控制台查看调用量与扣费明细"
      },
      {
        "key": "model",
        "label": "对口型模型",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "volcengine/video-to-video-lip-sync",
            "label": "Volcengine Lip Sync（$0.04/次）"
          }
        ],
        "description": "KIE 平台提供的视频对口型模型"
      },
      {
        "key": "mode",
        "label": "生成模式",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "basic",
            "label": "basic（质量优先）"
          },
          {
            "value": "lite",
            "label": "lite（速度优先）"
          }
        ],
        "description": "必填；basic 质量更好，lite 更快"
      },
      {
        "key": "separate_vocal",
        "label": "人声分离",
        "type": "toggle",
        "colSpan": "half",
        "description": "对目标音频先做人声分离，再用纯人声驱动口型"
      },
      {
        "key": "open_scenedet",
        "label": "场景检测",
        "type": "toggle",
        "colSpan": "half",
        "description": "开启镜头/场景检测，多镜头视频效果更好"
      },
      {
        "key": "align_audio",
        "label": "音画对齐",
        "type": "toggle",
        "colSpan": "half",
        "description": "自动对齐音频与画面，默认开启"
      },
      {
        "key": "align_audio_reverse",
        "label": "反向对齐",
        "type": "toggle",
        "colSpan": "half",
        "description": "在 align_audio 基础上使用反向对齐策略"
      },
      {
        "key": "templ_start_seconds",
        "label": "模板起始秒",
        "type": "number",
        "min": 0,
        "max": 3600,
        "colSpan": "half",
        "description": "从视频第 N 秒开始作为对口型模板，默认 0"
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 7200,
        "colSpan": "half",
        "description": "口型合成耗时较长，默认 900 秒，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "kie_image_audio_to_video",
    "name": "图声生视频-kie",
    "category": "ai_gen",
    "description": "用图片 + 声音驱动生成视频（数字人 / 对口型 / 角色演绎）。image1 为必填主图，kling-3.0/video 额外支持 image2~image5 共 5 张参考图；audio 输入口接驱动音频；提示词可来自连线文本或节点内填写。使用前请先注册 KIE 账号并获取 API Key：点击卡片上方「获取key」前往官网注册，拿到 Key 后填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY（也可在系统环境变量中设置同名变量）；用量见「用量日志」。",
    "icon": "UserRound",
    "color": "#0ea5e9",
    "inputs": [
      {
        "id": "image1",
        "label": "主图片",
        "type": "image",
        "required": true
      },
      {
        "id": "image2",
        "label": "参考图2",
        "type": "image"
      },
      {
        "id": "image3",
        "label": "参考图3",
        "type": "image"
      },
      {
        "id": "image4",
        "label": "参考图4",
        "type": "image"
      },
      {
        "id": "image5",
        "label": "参考图5",
        "type": "image"
      },
      {
        "id": "audio",
        "label": "驱动音频",
        "type": "audio",
        "required": true
      },
      {
        "id": "text",
        "label": "提示词",
        "type": "text"
      }
    ],
    "outputs": [
      {
        "id": "video",
        "label": "生成视频",
        "type": "video"
      },
      {
        "id": "videos",
        "label": "视频列表",
        "type": "json"
      },
      {
        "id": "params",
        "label": "生成参数JSON",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "model": "infinitalk/from-audio",
      "custom_prompt_enabled": false,
      "custom_prompt": "",
      "mode": "pro",
      "duration": 5,
      "aspect_ratio": "16:9",
      "sound": false,
      "resolution": "480p",
      "seed": "",
      "poll_timeout": 900
    },
    "configFields": [
      {
        "key": "btn_get_key",
        "label": "获取key",
        "type": "button",
        "colSpan": "half",
        "url": "https://kie.ai?ref=1ef5b0d4df5fc43ae85034755f9bf754",
        "description": "前往 KIE 官网注册并获取 API Key"
      },
      {
        "key": "btn_usage_logs",
        "label": "用量日志",
        "type": "button",
        "colSpan": "half",
        "url": "https://kie.ai/zh-CN/logs",
        "description": "在 KIE 控制台查看调用量与扣费明细"
      },
      {
        "key": "model",
        "label": "生成模型",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "infinitalk/from-audio",
            "label": "Infinitalk From Audio（图+声）"
          },
          {
            "value": "kling-3.0/video",
            "label": "Kling 3.0（最多 5 张参考图，$0.335/次）"
          },
          {
            "value": "kling/ai-avatar-standard",
            "label": "Kling AI Avatar Standard（$0.335/次）"
          },
          {
            "value": "kling/ai-avatar-pro",
            "label": "Kling AI Avatar Pro（$0.335/次）"
          }
        ],
        "description": "图片 + 声音驱动视频的模型"
      },
      {
        "key": "custom_prompt_enabled",
        "label": "使用节点内提示词",
        "type": "toggle",
        "colSpan": "half",
        "description": "关闭时使用上游连线文本；开启后使用下方提示词（所有模型均需提示词）"
      },
      {
        "key": "custom_prompt",
        "label": "自定义提示词",
        "type": "textarea",
        "colSpan": "full",
        "dependsOn": "custom_prompt_enabled",
        "dependsValue": true,
        "placeholder": "描述画面内容与人物动作，开启「使用节点内提示词」后生效"
      },
      {
        "key": "mode",
        "label": "画质模式",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "pro",
            "label": "pro（1080P）"
          },
          {
            "value": "std",
            "label": "std（720P）"
          },
          {
            "value": "4K",
            "label": "4K（2160P）"
          }
        ],
        "dependsOn": "model",
        "dependsValue": "kling-3.0/video",
        "description": "Kling 3.0 生成模式"
      },
      {
        "key": "duration",
        "label": "时长(秒)",
        "type": "number",
        "min": 3,
        "max": 15,
        "colSpan": "half",
        "dependsOn": "model",
        "dependsValue": "kling-3.0/video",
        "description": "Kling 3.0 视频时长，3-15 秒"
      },
      {
        "key": "aspect_ratio",
        "label": "画面比例",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "16:9",
            "label": "16:9"
          },
          {
            "value": "9:16",
            "label": "9:16"
          },
          {
            "value": "1:1",
            "label": "1:1"
          }
        ],
        "dependsOn": "model",
        "dependsValue": "kling-3.0/video",
        "description": "Kling 3.0 画面比例（提供参考图时可不填，会自动适配）"
      },
      {
        "key": "sound",
        "label": "生成音效",
        "type": "toggle",
        "colSpan": "half",
        "dependsOn": "model",
        "dependsValue": "kling-3.0/video",
        "description": "Kling 3.0 是否生成音效（与输入音频不同）"
      },
      {
        "key": "resolution",
        "label": "分辨率",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "480p",
            "label": "480p"
          },
          {
            "value": "720p",
            "label": "720p"
          }
        ],
        "dependsOn": "model",
        "dependsValue": "infinitalk/from-audio",
        "description": "Infinitalk 输出分辨率"
      },
      {
        "key": "seed",
        "label": "随机种子",
        "type": "number",
        "min": 10000,
        "max": 1000000,
        "colSpan": "half",
        "dependsOn": "model",
        "dependsValue": "infinitalk/from-audio",
        "description": "Infinitalk 随机种子，留空随机"
      },
      {
        "key": "poll_timeout",
        "label": "轮询超时(秒)",
        "type": "number",
        "min": 60,
        "max": 7200,
        "colSpan": "half",
        "description": "视频生成耗时较长，默认 900 秒，超时视为失败"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "kie_media_host",
    "name": "图床网存-kie",
    "category": "network_request",
    "description": "把本地图片 / 视频 / 音频上传到 KIE 免费媒体暂存，返回可直接访问的外链 URL，供其它接口（生图、生视频、对口型、图声生视频等）引用。支持 image / video / audio / file 四个输入口，可同时上传多个文件（已连接的口都会上传）。注意：本节点仅做文件暂存，不消耗生成额度；使用前请先注册 KIE 账号并获取 API Key，填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY（也可在系统环境变量中设置同名变量）。",
    "icon": "Upload",
    "color": "#0ea5e9",
    "inputs": [
      {
        "id": "image",
        "label": "图片",
        "type": "image"
      },
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
        "id": "file",
        "label": "其它文件",
        "type": "filepath"
      }
    ],
    "outputs": [
      {
        "id": "url",
        "label": "首个链接",
        "type": "url"
      },
      {
        "id": "urls",
        "label": "链接列表",
        "type": "json"
      },
      {
        "id": "json",
        "label": "上传明细",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "upload_path": "auto",
      "timeout": 120
    },
    "configFields": [
      {
        "key": "btn_get_key",
        "label": "获取key",
        "type": "button",
        "colSpan": "half",
        "url": "https://kie.ai?ref=1ef5b0d4df5fc43ae85034755f9bf754",
        "description": "前往 KIE 官网注册并获取 API Key"
      },
      {
        "key": "btn_usage_logs",
        "label": "用量日志",
        "type": "button",
        "colSpan": "half",
        "url": "https://kie.ai/zh-CN/logs",
        "description": "在 KIE 控制台查看调用量与扣费明细"
      },
      {
        "key": "upload_path",
        "label": "存储目录",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "auto",
            "label": "自动（按扩展名归类）"
          },
          {
            "value": "images",
            "label": "images（图片）"
          },
          {
            "value": "videos",
            "label": "videos（视频）"
          },
          {
            "value": "audios",
            "label": "audios（音频）"
          },
          {
            "value": "files",
            "label": "files（其它）"
          }
        ],
        "description": "上传路径 uploadPath；auto 按文件扩展名自动选择目录"
      },
      {
        "key": "timeout",
        "label": "超时(秒)",
        "type": "number",
        "min": 10,
        "max": 1200,
        "colSpan": "half",
        "description": "单个文件上传超时时间"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "agi_query",
    "name": "项目数据查询",
    "category": "agi_data",
    "description": "AI 漫剧·项目数据查询(只读)：按目标读取项目/章节/分镜/人物/场景/道具/素材，输出 JSON 与文本。用于把项目内的提示词、台词、设定取出来交给外部节点(LLM/生图/生视频/配音)加工，不修改任何数据",
    "icon": "Search",
    "color": "#0891b2",
    "inputs": [
      {
        "id": "creation_id",
        "label": "创作项目ID",
        "type": "text"
      },
      {
        "id": "chapter_id",
        "label": "章节ID(可选)",
        "type": "any"
      },
      {
        "id": "ids",
        "label": "记录ID(可选)",
        "type": "json"
      }
    ],
    "outputs": [
      {
        "id": "creation_id",
        "label": "创作项目ID",
        "type": "text"
      },
      {
        "id": "target",
        "label": "数据目标",
        "type": "text"
      },
      {
        "id": "count",
        "label": "记录数",
        "type": "text"
      },
      {
        "id": "ids",
        "label": "记录ID列表",
        "type": "json"
      },
      {
        "id": "items",
        "label": "数据(JSON)",
        "type": "json"
      },
      {
        "id": "text",
        "label": "数据(文本)",
        "type": "text"
      }
    ],
    "defaultConfig": {
      "creation_id": "",
      "chapter_id": "",
      "target": "shots",
      "fields": "",
      "asset_kind": "",
      "status": "",
      "limit": 0
    },
    "configFields": [
      {
        "key": "creation_id",
        "label": "创作项目",
        "type": "api-select",
        "apiEndpoint": "/api/creation/list",
        "optionLabel": "name",
        "optionValue": "id",
        "followPort": "creation_id",
        "colSpan": "full",
        "description": "数据来源项目；连线传入 creation_id 时优先"
      },
      {
        "key": "chapter_id",
        "label": "章节(可选)",
        "type": "api-select",
        "apiEndpoint": "/api/creation/{creation_id}/chapters",
        "optionLabel": "title",
        "optionValue": "id",
        "followPort": "chapter_id",
        "colSpan": "full",
        "description": "选择后只读该章；不选则跨整项目读取（分镜列表目标）"
      },
      {
        "key": "target",
        "label": "数据目标",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "creation",
            "label": "项目主数据"
          },
          {
            "value": "chapters",
            "label": "章节列表"
          },
          {
            "value": "chapter",
            "label": "单个章节(含分镜)"
          },
          {
            "value": "shots",
            "label": "分镜列表"
          },
          {
            "value": "shot",
            "label": "单个/多个分镜"
          },
          {
            "value": "characters",
            "label": "人物资产"
          },
          {
            "value": "scenes",
            "label": "场景资产"
          },
          {
            "value": "props",
            "label": "道具资产"
          },
          {
            "value": "assets",
            "label": "素材列表"
          }
        ],
        "description": "单个章节/分镜目标需连接或填写记录ID"
      },
      {
        "key": "fields",
        "label": "保留字段",
        "type": "text",
        "colSpan": "half",
        "placeholder": "如 id,index,dialogue,video_prompt",
        "description": "逗号分隔；留空返回全部字段"
      },
      {
        "key": "asset_kind",
        "label": "素材类型",
        "type": "text",
        "colSpan": "half",
        "placeholder": "如 shot_video / voiceover",
        "description": "仅「素材列表」目标生效；留空返回全部素材"
      },
      {
        "key": "status",
        "label": "状态过滤",
        "type": "text",
        "colSpan": "half",
        "placeholder": "如 pending / done",
        "description": "按记录 status 字段精确过滤；留空不过滤"
      },
      {
        "key": "limit",
        "label": "条数上限",
        "type": "number",
        "colSpan": "half",
        "min": 0,
        "max": 500,
        "description": "0 表示不限制"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "agi_write",
    "name": "项目数据写入",
    "category": "agi_data",
    "description": "AI 漫剧·项目数据写入(只写)：把外部处理结果回写到项目指定数据点。同一份补丁可批量应用到多个记录ID，也可用带 id 的数组逐条写回；字段需在该类记录的白名单内",
    "icon": "PencilLine",
    "color": "#0891b2",
    "inputs": [
      {
        "id": "creation_id",
        "label": "创作项目ID",
        "type": "text"
      },
      {
        "id": "ids",
        "label": "记录ID列表",
        "type": "json"
      },
      {
        "id": "data",
        "label": "写入数据(JSON)",
        "type": "json"
      }
    ],
    "outputs": [
      {
        "id": "creation_id",
        "label": "创作项目ID",
        "type": "text"
      },
      {
        "id": "target",
        "label": "数据目标",
        "type": "text"
      },
      {
        "id": "count",
        "label": "写入条数",
        "type": "text"
      },
      {
        "id": "ids",
        "label": "记录ID列表",
        "type": "json"
      },
      {
        "id": "updated",
        "label": "写入结果",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "creation_id": "",
      "target": "shot",
      "ids": "",
      "data": ""
    },
    "configFields": [
      {
        "key": "creation_id",
        "label": "创作项目",
        "type": "api-select",
        "apiEndpoint": "/api/creation/list",
        "optionLabel": "name",
        "optionValue": "id",
        "followPort": "creation_id",
        "colSpan": "full",
        "description": "目标项目；连线传入 creation_id 时优先"
      },
      {
        "key": "target",
        "label": "数据目标",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "creation",
            "label": "项目主数据"
          },
          {
            "value": "chapter",
            "label": "章节"
          },
          {
            "value": "shot",
            "label": "分镜"
          },
          {
            "value": "character",
            "label": "人物"
          },
          {
            "value": "scene",
            "label": "场景"
          },
          {
            "value": "prop",
            "label": "道具"
          },
          {
            "value": "asset",
            "label": "素材"
          }
        ],
        "description": "写入不存在的字段会直接报错，便于及早发现拼写问题"
      },
      {
        "key": "ids",
        "label": "记录ID(可留空)",
        "type": "text",
        "colSpan": "full",
        "placeholder": "逗号分隔多个ID",
        "description": "批量写同一份补丁时填写；已连接 ids 端口时以端口为准"
      },
      {
        "key": "data",
        "label": "写入数据",
        "type": "textarea",
        "colSpan": "full",
        "placeholder": "{\"video_prompt\": \"...\"} 或 [{\"id\": \"shot_x\", \"video_prompt\": \"...\"}]",
        "description": "JSON 对象=同一补丁批量写入 ids；JSON 数组=按每项 id 逐条写入；已连接 data 端口时以端口为准"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "agi_asset_register",
    "name": "素材登记入库",
    "category": "agi_data",
    "description": "AI 漫剧·素材登记入库(写素材)：把外部生图/生视频/配音等产物登记为项目资产，并按分镜/章节归属入库，供分镜导出与章节导出节点按分镜消费",
    "icon": "PackagePlus",
    "color": "#0891b2",
    "inputs": [
      {
        "id": "creation_id",
        "label": "创作项目ID",
        "type": "text"
      },
      {
        "id": "files",
        "label": "素材文件",
        "type": "any"
      },
      {
        "id": "shot_id",
        "label": "分镜ID(可选)",
        "type": "text"
      },
      {
        "id": "chapter_id",
        "label": "章节ID(可选)",
        "type": "any"
      }
    ],
    "outputs": [
      {
        "id": "creation_id",
        "label": "创作项目ID",
        "type": "text"
      },
      {
        "id": "count",
        "label": "登记数量",
        "type": "text"
      },
      {
        "id": "asset_ids",
        "label": "素材ID列表",
        "type": "json"
      },
      {
        "id": "assets",
        "label": "素材记录",
        "type": "json"
      },
      {
        "id": "paths",
        "label": "素材路径",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "creation_id": "",
      "shot_id": "",
      "chapter_id": "",
      "asset_kind": "auto",
      "name": "",
      "ref_id": "",
      "duration_seconds": "",
      "description": ""
    },
    "configFields": [
      {
        "key": "creation_id",
        "label": "创作项目",
        "type": "api-select",
        "apiEndpoint": "/api/creation/list",
        "optionLabel": "name",
        "optionValue": "id",
        "followPort": "creation_id",
        "colSpan": "full",
        "description": "素材归属项目；连线传入 creation_id 时优先"
      },
      {
        "key": "chapter_id",
        "label": "章节(可选)",
        "type": "api-select",
        "apiEndpoint": "/api/creation/{creation_id}/chapters",
        "optionLabel": "title",
        "optionValue": "id",
        "followPort": "chapter_id",
        "colSpan": "full",
        "description": "素材归属章节；连线传入 chapter_id 时优先"
      },
      {
        "key": "shot_id",
        "label": "分镜(可选)",
        "type": "api-select",
        "apiEndpoint": "/api/creation/{creation_id}/shots?chapter_id={chapter_id}",
        "optionLabel": "label",
        "optionValue": "id",
        "colSpan": "full",
        "description": "素材归属分镜，导出时按分镜消费；连线传入 shot_id 时优先"
      },
      {
        "key": "asset_kind",
        "label": "素材类型",
        "type": "select",
        "colSpan": "half",
        "options": [
          {
            "value": "auto",
            "label": "自动(按扩展名)"
          },
          {
            "value": "shot_video",
            "label": "分镜视频"
          },
          {
            "value": "shot_render",
            "label": "分镜图"
          },
          {
            "value": "chapter_render",
            "label": "章节成片"
          },
          {
            "value": "chapter_cover",
            "label": "章节封面"
          },
          {
            "value": "character",
            "label": "人物图"
          },
          {
            "value": "scene_image",
            "label": "场景图"
          },
          {
            "value": "prop_image",
            "label": "道具图"
          },
          {
            "value": "voiceover",
            "label": "配音"
          },
          {
            "value": "bgm",
            "label": "背景音乐"
          },
          {
            "value": "sfx",
            "label": "音效"
          }
        ],
        "description": "自动：视频→shot_video，音频→voiceover，图片→shot_render"
      },
      {
        "key": "name",
        "label": "素材名称",
        "type": "text",
        "colSpan": "half",
        "placeholder": "留空用文件名；多文件时自动加序号"
      },
      {
        "key": "ref_id",
        "label": "关联ID",
        "type": "text",
        "colSpan": "half",
        "description": "可选，关联人物/场景/道具等记录ID"
      },
      {
        "key": "duration_seconds",
        "label": "时长(秒)",
        "type": "number",
        "colSpan": "half",
        "description": "音频/视频时长，可留空"
      },
      {
        "key": "description",
        "label": "备注",
        "type": "textarea",
        "colSpan": "full"
      }
    ],
    "isBuiltIn": true
  },
  {
    "id": "agi_shot_prompt",
    "name": "组装分镜提示词",
    "category": "agi_shot",
    "description": "AI 漫剧·组装分镜提示词：把分镜用到的角色图/场景图/道具图按【image1】/【image2】顺序组装，细化为 8 个故事走向关键帧的生图提示词(JSON)，并产出有序参考图供「分镜首尾帧」图生图使用",
    "icon": "ScrollText",
    "color": "#ea580c",
    "inputs": [
      {
        "id": "shot_id",
        "label": "分镜ID(单个)",
        "type": "any"
      },
      {
        "id": "chapter_id",
        "label": "章节ID(批处理)",
        "type": "any"
      },
      {
        "id": "chapter_ids",
        "label": "多章节ID列表(可选)",
        "type": "json"
      }
    ],
    "outputs": [
      {
        "id": "shot_id",
        "label": "分镜ID",
        "type": "text"
      },
      {
        "id": "shot_ids",
        "label": "分镜ID列表",
        "type": "json"
      },
      {
        "id": "image_prompts",
        "label": "组装提示词",
        "type": "json"
      },
      {
        "id": "image_prompt_refs",
        "label": "有序参考图",
        "type": "json"
      }
    ],
    "defaultConfig": {
      "creation_id": "",
      "chapter_id": "",
      "shot_id": "",
      "llm_model": "",
      "force": false
    },
    "configFields": [
      {
        "key": "creation_id",
        "label": "创作项目",
        "type": "api-select",
        "apiEndpoint": "/api/creation/list",
        "optionLabel": "name",
        "optionValue": "id",
        "followPort": "creation_id",
        "colSpan": "full",
        "description": "项目骨架数据源；连线传入时优先"
      },
      {
        "key": "chapter_id",
        "label": "章节(批处理)",
        "type": "api-select",
        "apiEndpoint": "/api/creation/{creation_id}/chapters",
        "optionLabel": "title",
        "optionValue": "id",
        "followPort": "chapter_id",
        "colSpan": "full",
        "description": "选择后整章批处理；连线传入时优先"
      },
      {
        "key": "shot_id",
        "label": "分镜(单个)",
        "type": "api-select",
        "apiEndpoint": "/api/creation/{creation_id}/shots?chapter_id={chapter_id}",
        "optionLabel": "label",
        "optionValue": "id",
        "colSpan": "full",
        "description": "先选择创作项目与章节；连线传入时优先"
      },
      {
        "key": "llm_model",
        "label": "LLM 模型",
        "type": "api-select",
        "apiEndpoint": "/api/llm/interfaces/enabled",
        "colSpan": "half",
        "placeholder": "跟随路由默认模型"
      },
      {
        "key": "force",
        "label": "强制重组装",
        "type": "toggle",
        "colSpan": "full",
        "description": "开启后忽略已组装提示词，重新生成"
      }
    ],
    "isBuiltIn": true
  }
];

export const BUILTIN_NODE_TYPES = FALLBACK_NODE_TYPES;

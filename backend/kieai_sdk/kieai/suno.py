#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Suno 音乐 API（kie.ai 官方 ai-music-api 系列）专用客户端。

与官网 (https://kie.ai/suno-api) 完全对齐的统一调用模式：

* 所有生成/处理类操作统一 ``POST https://api.kie.ai/api/v1/jobs/createTask``，
  请求体 ``{"model": "ai-music-api/<操作>", "callBackUrl"?: ..., "input": {...}}``
  （参数一律 snake_case，与官方文档一致）。
* 提交成功返回 ``data.taskId`` —— **每个端点都会返回 taskId**，供下游节点串联
  （例如 generate → extend / persona / timestamped-lyrics / cover-generate …）。
* 统一轮询 ``GET https://api.kie.ai/api/v1/jobs/recordInfo?taskId=...``，
  结果位于 ``data.response.resultJson``（JSON 字符串），曲目在
  ``resultObject.data[]``（audio_url / stream_audio_url / image_url / id / duration）。

特殊端点：
* ``generate-persona`` 与 ``check-voice`` 为**同步**接口（不返回 taskId）：
  前者直接返回 ``persona_id``（即下游 generate/extend 的 persona_id 串联凭证），
  后者直接返回 ``isAvailable``。
* ``suno-recovery-audio`` 使用专用轮询端点
  ``GET /api/v1/suno/recovery/record-info?task_id=``（code: 201 运行中 / 200 完成 / 500 失败）。
* ``generate-midi-from-audio`` 的音符数据需再查
  ``GET /api/v1/midi/record-info?taskId=``。

官方文档: https://docs.kie.ai/suno-api/generate-music 等。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import aiohttp

from .exceptions import KieRequestError, KieTaskFailed, KieTimeout

_BASE = "https://api.kie.ai"
CREATE_TASK_URL = f"{_BASE}/api/v1/jobs/createTask"
RECORD_INFO_URL = f"{_BASE}/api/v1/jobs/recordInfo"
RECOVERY_INFO_URL = f"{_BASE}/api/v1/suno/recovery/record-info"
MIDI_INFO_URL = f"{_BASE}/api/v1/midi/record-info"

# ---------------------------------------------------------------------- #
# camelCase -> snake_case（兼容 Playground 风格的驼峰参数名）
# ---------------------------------------------------------------------- #
_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _snake(key: str) -> str:
    return _CAMEL_RE.sub("_", key).lower()


# ---------------------------------------------------------------------- #
# 官方操作规格表（与 docs.kie.ai/suno-api 一一对应）
#
# params: {name: {"req": 必填, "default": 默认, "enum": 枚举,
#                 "min"/"max": 数值范围, "max_len": 字符上限, "desc": 说明}}
# xor:    互斥必填组 [[["upload_url"], ["task_id", "audio_id"]], ...]
#         —— 每个内层组里的参数必须全部出现，且只需其中一组命中。
# ---------------------------------------------------------------------- #
_WEIGHT = {"min": 0, "max": 1, "desc": "0–1，两位小数"}
_VARIETY = {
    "min": 0, "max": 4, "default": 1,
    "desc": "多样性：0 严格同风格 / 1 正常 / 2 高 / 3 额外 / 4 最大",
}
_PERSONA_MODEL = {
    "enum": ["style_persona", "voice_persona"],
    "desc": "style_persona=Persona ID；voice_persona=Suno Voice ID（仅 V6/V6_MINI/V6_WILD）",
}
_MUSIC_MODEL = {
    "enum": ["V4", "V4_5", "V4_5PLUS", "V4_5ALL", "V5", "V5_5", "V6",
             "V6_MINI", "V6_WILD"],
    "desc": "推荐 V6 / V6_MINI / V6_WILD（其余已停用）",
}

SUNO_OPERATIONS: Dict[str, Dict[str, Any]] = {
    # ---------------- 音乐生成 ----------------
    "generate": {
        "ref": "ai-music-api/generate",
        "name": "Generate Music",
        "desc": "生成音乐（每请求多个变体曲目）",
        "params": {
            "custom_mode": {"req": True, "desc": "true=高级自定义模式"},
            "instrumental": {"req": True, "desc": "true=纯音乐无人声"},
            "model": {**_MUSIC_MODEL, "req": True},
            "prompt": {"max_len": 5000,
                       "desc": "自定义模式=歌词；非自定义=创意描述"},
            "lyrics": {"max_len": 5000, "desc": "歌词，优先级高于 prompt"},
            "style": {"max_len": 1000, "desc": "音乐风格"},
            "title": {"max_len": 80, "desc": "曲目名称（custom_mode=true 时必填）"},
            "negative_tags": {"desc": "排除的风格特征"},
            "vocal_gender": {"enum": ["m", "f"], "desc": "人声性别偏好"},
            "style_weight": _WEIGHT,
            "weirdness_constraint": _WEIGHT,
            "audio_weight": _WEIGHT,
            "variety": _VARIETY,
            "persona_id": {"desc": "Persona ID / Voice ID"},
            "persona_model": _PERSONA_MODEL,
            "duration": {"min": 10, "max": 360,
                         "desc": "目标时长（秒），仅 V6 系列有效"},
            "image_urls": {"desc": "图片参考（非自定义模式，≤5 张）"},
            "video_urls": {"desc": "视频参考（非自定义模式，≤1 个）"},
            "audio_urls": {"desc": "音频参考（非自定义模式）"},
        },
    },
    "extend": {
        "ref": "ai-music-api/extend",
        "name": "Extend Music",
        "desc": "从已有音轨扩展续写（input: task 产物的 audio_id）",
        "params": {
            "audio_id": {"req": True, "desc": "源音轨 ID"},
            "model": {**_MUSIC_MODEL, "req": True,
                      "desc": "必须与源音频模型一致"},
            "prompt": {"max_len": 5000, "desc": "扩展歌词（无 lyrics 时生效）"},
            "lyrics": {"max_len": 5000},
            "style": {"max_len": 1000},
            "title": {"max_len": 100},
            "continue_at": {"desc": "从原曲第几秒开始扩展"},
            "negative_tags": {},
            "vocal_gender": {"enum": ["m", "f"]},
            "style_weight": _WEIGHT,
            "weirdness_constraint": _WEIGHT,
            "audio_weight": _WEIGHT,
            "variety": _VARIETY,
            "persona_id": {},
            "persona_model": _PERSONA_MODEL,
            "instrumental": {"desc": "true=纯音乐，禁止传 lyrics/prompt/vocal_gender"},
        },
    },
    "upload_and_cover": {
        "ref": "ai-music-api/upload-and-cover-audio",
        "name": "Upload And Cover Audio",
        "desc": "上传音频翻唱（upload_url 或 task_id+audio_id 二选一）",
        "xor": [[["upload_url"], ["task_id", "audio_id"]]],
        "params": {
            "upload_url": {"desc": "源音频 URL（≤8 分钟）"},
            "task_id": {"desc": "KIE 已生成任务 ID"},
            "audio_id": {"desc": "要翻唱的曲目 ID"},
            "model": {**_MUSIC_MODEL, "req": True},
            "instrumental": {"req": True},
            "prompt": {"max_len": 5000},
            "lyrics": {"max_len": 5000},
            "style": {"max_len": 1000},
            "title": {"max_len": 80},
            "negative_tags": {},
            "vocal_gender": {"enum": ["m", "f"]},
            "style_weight": _WEIGHT,
            "weirdness_constraint": _WEIGHT,
            "audio_weight": _WEIGHT,
            "variety": _VARIETY,
            "persona_id": {},
            "persona_model": _PERSONA_MODEL,
            "duration": {"min": 10, "max": 360},
        },
    },
    "upload_and_extend": {
        "ref": "ai-music-api/upload-and-extend-audio",
        "name": "Upload And Extend Audio",
        "desc": "上传音频并扩展（始终 custom mode，勿传 custom_mode）",
        "params": {
            "upload_url": {"req": True, "desc": "源音频 URL（≤8 分钟）"},
            "model": {**_MUSIC_MODEL, "req": True},
            "instrumental": {},
            "prompt": {"max_len": 5000},
            "lyrics": {"max_len": 5000},
            "style": {"max_len": 1000},
            "title": {"max_len": 100},
            "continue_at": {},
            "negative_tags": {},
            "vocal_gender": {"enum": ["m", "f"]},
            "style_weight": _WEIGHT,
            "weirdness_constraint": _WEIGHT,
            "audio_weight": _WEIGHT,
            "variety": _VARIETY,
            "persona_id": {},
            "persona_model": _PERSONA_MODEL,
        },
    },
    "add_instrumental": {
        "ref": "ai-music-api/add-instrumental",
        "name": "Add Instrumental to Music",
        "desc": "为上传音频添加伴奏生成新曲",
        "params": {
            "upload_url": {"req": True},
            "title": {"req": True},
            "negative_tags": {"req": True, "max_len": 200},
            "tags": {"req": True, "max_len": 1000, "desc": "风格标签"},
            "model": {**_MUSIC_MODEL, "default": "V6"},
            "lyrics": {"max_len": 5000},
            "vocal_gender": {"enum": ["m", "f"]},
            "style_weight": _WEIGHT,
            "weirdness_constraint": _WEIGHT,
            "audio_weight": _WEIGHT,
            "variety": _VARIETY,
        },
    },
    "add_vocals": {
        "ref": "ai-music-api/add-vocals",
        "name": "Add Vocals to Music",
        "desc": "为上传音频添加人声生成新曲",
        "params": {
            "upload_url": {"req": True},
            "title": {"req": True},
            "negative_tags": {"req": True, "max_len": 200},
            "style": {"req": True, "max_len": 1000},
            "model": {**_MUSIC_MODEL, "default": "V6"},
            "prompt": {"max_len": 5000},
            "lyrics": {"max_len": 5000},
            "vocal_gender": {"enum": ["m", "f"]},
            "style_weight": _WEIGHT,
            "weirdness_constraint": _WEIGHT,
            "audio_weight": _WEIGHT,
            "variety": _VARIETY,
        },
    },
    # ---------------- Persona / Voice ----------------
    "generate_persona": {
        "ref": "ai-music-api/generate-persona",
        "name": "Generate Persona",
        "desc": "为生成的音乐创建 Persona（同步返回 persona_id，可串入 generate/extend 的 persona_id）",
        "sync": True,
        "params": {
            "task_id": {"req": True, "desc": "原音乐生成任务 ID"},
            "audio_id": {"req": True, "desc": "音轨 ID（每条只能生成一次 Persona）"},
            "name": {"req": True},
            "description": {"req": True},
            "vocal_start": {"default": 0,
                            "desc": "分析片段起点（秒），与 end 差 10–30 秒"},
            "vocal_end": {"default": 30},
            "style": {"desc": "补充风格标签"},
        },
    },
    "voice_validate": {
        "ref": "ai-music-api/validation-phrase",
        "name": "Suno Voice Generate Verification Phrase",
        "desc": "生成验证短语（Voice 链路第 1 步，免费）",
        "params": {
            "voice_url": {"req": True, "desc": "原始录音 URL"},
            "vocal_start_s": {"req": True, "desc": "人声片段起点（秒）"},
            "vocal_end_s": {"req": True, "desc": "人声片段终点（秒）"},
            "language": {"enum": ["en", "zh", "es", "fr", "pt", "de", "ja",
                                  "ko", "hi", "ru"]},
        },
    },
    "voice_create": {
        "ref": "ai-music-api/create-voice",
        "name": "Suno Voice Create Custom Voice",
        "desc": "创建自定义音色（Voice 链路第 3 步，voice_id=验证任务 taskId）",
        "params": {
            "task_id": {"req": True, "desc": "验证短语任务 ID"},
            "verify_url": {"req": True, "desc": "用户录制验证短语的音频 URL"},
            "voice_name": {},
            "description": {},
            "style": {},
            "singer_skill_level": {"enum": ["beginner", "intermediate",
                                            "advanced", "professional"],
                                   "default": "beginner"},
        },
    },
    "voice_check": {
        "ref": "ai-music-api/check-voice",
        "name": "Suno Voice Check Availability",
        "desc": "检查自定义音色是否可用（同步返回 isAvailable，免费）",
        "sync": True,
        "params": {
            "task_id": {"req": True, "desc": "Create Custom Voice 返回的 taskId"},
        },
    },
    "voice_regenerate": {
        "ref": "ai-music-api/regenerate-phrase",
        "name": "Suno Voice Regenerate Verification Phrase",
        "desc": "重新生成验证短语（结果更新在原始验证任务上，免费）",
        "params": {
            "task_id": {"req": True, "desc": "原验证任务 ID"},
        },
    },
    # ---------------- 风格 / 封面 / 片段 ----------------
    "boost_style": {
        "ref": "ai-music-api/boost-music-style",
        "name": "Boost Music Style",
        "desc": "风格增强改写（结果串回 generate 的 style）",
        "params": {
            "content": {"req": True, "desc": "风格描述，如 'Pop, Mysterious'"},
        },
    },
    "cover_generate": {
        "ref": "ai-music-api/cover-generate",
        "name": "Generate Music Cover",
        "desc": "为生成任务的音轨生成封面（2 张）",
        "params": {
            "task_id": {"req": True, "desc": "原音乐生成任务 ID"},
        },
    },
    "replace_section": {
        "ref": "ai-music-api/replace-section",
        "name": "Replace Music Section",
        "desc": "替换音乐片段（infill 时长 10 秒～全曲 50%；来源二选一）",
        "xor": [[["task_id", "audio_id"], ["upload_url", "model"]]],
        "params": {
            "task_id": {"desc": "来源 A：原任务 ID"},
            "audio_id": {"desc": "来源 A：音轨 ID"},
            "upload_url": {"desc": "来源 B：上传音频 URL"},
            "model": {**_MUSIC_MODEL, "default": "V6",
                      "desc": "来源 B 必填（默认 V6）"},
            "prompt": {"req": True},
            "tags": {"req": True},
            "title": {"req": True},
            "infill_start_s": {"req": True, "desc": "替换起点（秒）"},
            "infill_end_s": {"req": True, "desc": "替换终点（秒）"},
            "full_lyrics": {"req": True, "desc": "整首完整歌词（含修改段）"},
            "lyrics": {"max_len": 5000, "desc": "被替换片段的歌词"},
            "negative_tags": {},
            "vocal_gender": {"enum": ["m", "f"]},
            "style_weight": _WEIGHT,
            "weirdness_constraint": _WEIGHT,
            "audio_weight": _WEIGHT,
            "variety": _VARIETY,
            "persona_id": {},
            "persona_model": _PERSONA_MODEL,
        },
    },
    # ---------------- 混音 / 音效 ----------------
    "mashup": {
        "ref": "ai-music-api/mashup",
        "name": "Generate Mashup Music",
        "desc": "混音两段音频（upload_url_list 必须恰好 2 个）",
        "params": {
            "upload_url_list": {"req": True, "min_items": 2,
                                "desc": "两个可公开访问的音频 URL"},
            "model": {**_MUSIC_MODEL, "req": True},
            "style": {"req": True, "max_len": 1000},
            "title": {"req": True, "max_len": 100},
            "prompt": {"max_len": 5000},
            "lyrics": {"max_len": 5000},
            "vocal_gender": {"enum": ["m", "f"]},
            "style_weight": _WEIGHT,
            "weirdness_constraint": _WEIGHT,
            "audio_weight": _WEIGHT,
            "variety": _VARIETY,
            "persona_id": {},
            "persona_model": _PERSONA_MODEL,
            "duration": {"min": 10, "max": 360, "default": 20},
        },
    },
    "sounds": {
        "ref": "ai-music-api/sounds",
        "name": "Generate Sounds",
        "desc": "生成音效/循环环境音",
        "params": {
            "prompt": {"req": True, "max_len": 500},
            "model": {"req": True,
                      "enum": ["V5", "V5_5", "V6", "V6_WILD", "V6_MINI"]},
            "sound_loop": {"default": False, "desc": "是否无缝循环"},
            "sound_tempo": {"min": 1, "max": 300, "desc": "BPM，省略则自动"},
            "sound_key": {"enum": ["Any", "Cm", "C#m", "Dm", "D#m", "Em",
                                   "Fm", "F#m", "Gm", "G#m", "Am", "A#m",
                                   "Bm", "C", "C#", "D", "D#", "E", "F",
                                   "F#", "G", "G#", "A", "A#", "B"],
                          "default": "Any"},
            "grab_lyrics": {"default": False, "desc": "完成后抓取歌词字幕"},
        },
    },
    # ---------------- 歌词 ----------------
    "generate_lyrics": {
        "ref": "ai-music-api/generate-lyrics",
        "name": "Generate Lyrics",
        "desc": "生成歌词（返回 2–3 个变体，结果在 lyricsData[]）",
        "params": {
            "prompt": {"req": True, "max_len": 200,
                       "desc": "歌词主题/情绪/风格描述"},
        },
    },
    "timestamped_lyrics": {
        "ref": "ai-music-api/timeStamped-lyrics",
        "name": "Get Timestamped Lyrics",
        "desc": "获取逐词时间戳歌词（卡拉OK同步）",
        "params": {
            "task_id": {"req": True, "desc": "音乐生成任务 ID"},
            "audio_id": {"req": True, "desc": "音轨 ID"},
        },
    },
    # ---------------- 分离 / MIDI / 恢复 / 转码 / 视频 ----------------
    "separate_vocals": {
        "ref": "ai-music-api/separate-vocals",
        "name": "Vocal & Instrument Stem Separation",
        "desc": "人声/乐器分轨分离（来源二选一；重复提交同一音轨会重复扣费）",
        "xor": [[["task_id", "audio_id"], ["audio_url"]]],
        "params": {
            "task_id": {"desc": "来源 A：原任务 ID"},
            "audio_id": {"desc": "来源 A：音轨 ID"},
            "audio_url": {"desc": "来源 B：上传音频 URL（≤20MB）"},
            "type": {"enum": ["separate_vocal", "split_stem",
                              "split_stem_advanced"],
                     "default": "separate_vocal",
                     "desc": "separate_vocal=人声+伴奏 / split_stem=最多12轨 / "
                             "split_stem_advanced=提取指定音轨"},
            "stem_name": {"desc": "仅 split_stem_advanced 必填，如 'Lead Vocal'"},
        },
    },
    "generate_midi": {
        "ref": "ai-music-api/generate-midi-from-audio",
        "name": "Generate MIDI from Audio",
        "desc": "从分离任务的 stems 生成 MIDI（免费；音符经 /api/v1/midi/record-info 查询）",
        "poll": "midi",
        "params": {
            "task_id": {"req": True, "desc": "分离任务的 task_id"},
            "audio_id": {"desc": "指定 stem id（省略=所有 stems）"},
        },
    },
    "recovery_audio": {
        "ref": "ai-music-api/suno-recovery-audio",
        "name": "Recovery Audio",
        "desc": "恢复历史任务的音频链接（专用轮询端点）",
        "poll": "recovery",
        "params": {
            "task_id": {"req": True, "desc": "原音乐生成任务 ID"},
        },
    },
    "convert_to_wav": {
        "ref": "ai-music-api/convert-to-wav-format",
        "name": "Convert to WAV Format",
        "desc": "转换为 WAV（重复转换返回 422 + 已有结果，不重复扣费）",
        "params": {
            "task_id": {"req": True},
            "audio_id": {"req": True,
                         "desc": "音轨 ID 或分离结果的 stem id"},
        },
    },
    "create_music_video": {
        "ref": "ai-music-api/create-music-video",
        "name": "Create Music Video",
        "desc": "生成音乐可视化 MP4（结果 resultUrls[0]）",
        "params": {
            "task_id": {"req": True, "desc": "Generate/Extend 任务 ID"},
            "audio_id": {"req": True},
            "author": {"max_len": 50, "desc": "封面署名"},
            "domain_name": {"max_len": 50, "desc": "底部水印文字"},
        },
    },
}


def build_suno_entries() -> List[Dict[str, Any]]:
    """由规格表生成 catalog.json 风格的模型条目（request_style=market）。"""
    entries: List[Dict[str, Any]] = []
    for op, spec in SUNO_OPERATIONS.items():
        params = [
            {
                "name": name,
                "type": "array" if name.endswith("s") and name != "sounds"
                        else ("boolean" if meta.get("enum") == ["m", "f"]
                              or "default" in meta
                              and isinstance(meta["default"], bool) else "string"),
                "required": bool(meta.get("req")),
                "default": meta.get("default"),
                "enum": meta.get("enum"),
                "description": meta.get("desc", ""),
            }
            for name, meta in spec["params"].items()
        ]
        poll = RECORD_INFO_URL
        if spec.get("poll") == "recovery":
            poll = RECOVERY_INFO_URL
        elif spec.get("poll") == "midi":
            poll = MIDI_INFO_URL
        entries.append({
            "id": f"suno-{op.replace('_', '-')}",
            "name": f"Suno {spec['name']}",
            "platform": "suno",
            "category": "music",
            "family": "suno",
            "request_style": "market",
            "endpoint": CREATE_TASK_URL,
            "poll_endpoint": poll,
            "poll_id_param": "task_id" if spec.get("poll") == "recovery"
                             else "taskId",
            "model_ref": spec["ref"],
            "description": spec["desc"],
            "doc_url": "https://docs.kie.ai/suno-api",
            "params": params,
        })
    return entries


def apply_suno_catalog(catalog) -> None:
    """用内置规格表替换 catalog 中 family=='suno' 的全部条目（load 时调用）。"""
    from .models import ModelEntry

    new_models = [ModelEntry.from_dict(d) for d in build_suno_entries()]
    keep = [m for m in catalog.models if m.family != "suno"]
    catalog.models = keep + new_models
    catalog._by_id = {}
    catalog._by_ref = {}
    for m in catalog.models:
        catalog._by_id[m.id] = m
        if m.model_ref:
            catalog._by_ref[m.model_ref] = m


def validate_params(op: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """按规格表校验并规整 input 参数（camelCase 归一为 snake_case）。

    返回规整后的 input 字典；缺必填 / 未知参数 / 越界会抛 ValueError。
    """
    spec = SUNO_OPERATIONS.get(op)
    if spec is None:
        raise ValueError(f"Unknown suno operation: {op!r}")
    known = set(spec["params"])

    normalized: Dict[str, Any] = {}
    for k, v in params.items():
        sk = _snake(k)
        if sk not in known:
            raise ValueError(
                f"[suno/{op}] unknown param {k!r}; accepted: {sorted(known)}")
        normalized[sk] = v

    for name, meta in spec["params"].items():
        if name not in normalized or normalized[name] in (None, ""):
            if meta.get("req"):
                raise ValueError(f"[suno/{op}] missing required param {name!r}")
            if name in normalized:
                del normalized[name]
            continue
        v = normalized[name]
        if meta.get("enum") and v not in meta["enum"]:
            raise ValueError(
                f"[suno/{op}] {name}={v!r} not in {meta['enum']}")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if "min" in meta and v < meta["min"]:
                raise ValueError(f"[suno/{op}] {name}={v} < {meta['min']}")
            if "max" in meta and v > meta["max"]:
                raise ValueError(f"[suno/{op}] {name}={v} > {meta['max']}")
        if isinstance(v, str) and meta.get("max_len") and len(v) > meta["max_len"]:
            raise ValueError(
                f"[suno/{op}] {name} exceeds {meta['max_len']} chars")
        if isinstance(v, list) and meta.get("min_items") and len(v) < meta["min_items"]:
            raise ValueError(
                f"[suno/{op}] {name} needs >= {meta['min_items']} items")

    for groups in spec.get("xor", []):  # 每个互斥约束：需恰好命中一组
        hits = [g for g in groups if all(p in normalized for p in g)]
        if len(hits) == 0:
            opts = " 或 ".join("+".join(g) for g in groups)
            raise ValueError(f"[suno/{op}] 必须提供其一: {opts}")
        if len(hits) > 1:
            opts = " / ".join("+".join(g) for g in hits)
            raise ValueError(f"[suno/{op}] 互斥参数同时出现: {opts}")
    return normalized


class SunoMusicClient:
    """Suno 音乐 API 客户端：每个操作提交后返回 ``taskId`` 供下游串联。

    Example
    -------
        async with SunoMusicClient() as music:
            t = await music.generate(custom_mode=False, instrumental=False,
                                     model="V6", prompt="lofi beat")
            task_id, tracks = t["taskId"], (await music.wait(t["taskId"]))["tracks"]
            ext = await music.extend(audio_id=tracks[0]["id"], model="V6",
                                     continue_at=120)
    """

    def __init__(self, client=None, **client_kwargs):
        if client is None:
            from .client import KieClient
            client = KieClient(**client_kwargs)
        self.client = client

    async def __aenter__(self) -> "SunoMusicClient":
        if self.client._session is None:
            await self.client.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.client.__aexit__(*exc)

    # ------------------------------------------------------------------ #
    # 核心原语
    # ------------------------------------------------------------------ #
    async def submit(
        self,
        op: str,
        *,
        callback_url: Optional[str] = None,
        **params: Any,
    ) -> Dict[str, Any]:
        """提交任务，返回 ``{"taskId", "model", "input"}``（ taskId 供串联）。"""
        spec = SUNO_OPERATIONS.get(op)
        if spec is None:
            raise ValueError(f"Unknown suno operation: {op!r}")
        input_body = validate_params(op, params)
        body: Dict[str, Any] = {"model": spec["ref"], "input": input_body}
        if callback_url:
            body["callBackUrl"] = callback_url
        data = await self.client._post_json_retry(CREATE_TASK_URL, body)
        if data.get("code") not in (None, 200):
            raise KieRequestError(
                f"[suno/{op}] submit failed: {data.get('msg')}",
                body=data)
        payload = data.get("data") or {}
        task_id = payload.get("taskId") or payload.get("task_id")
        if not task_id:
            # 同步端点（persona / check-voice）直接携带最终结果
            return {"sync": True, "op": op, **payload}
        return {"taskId": str(task_id), "op": op,
                "model": spec["ref"], "input": input_body}

    async def wait(
        self,
        task_id: str,
        *,
        poll_interval: Optional[float] = None,
        max_poll: Optional[int] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """轮询 recordInfo 直到完成，返回::

            {"taskId", "successFlag", "resultUrls": [...],
             "tracks": [ {id, audio_url, stream_audio_url, image_url,
                          title, tags, duration, ...}, ... ],
             "raw": <解析后的 resultJson 全量对象>}
        """
        interval = poll_interval or self.client.poll_interval
        attempts = max_poll or self.client.max_poll
        url = f"{RECORD_INFO_URL}?taskId={task_id}"

        for _ in range(attempts):
            last = await self.client._get_json_retry(url)
            code = last.get("code")
            if code is not None and code != 200:
                raise KieTaskFailed(
                    f"Task {task_id} poll returned code={code}: {last.get('msg')}",
                    task_id=task_id, body=last)
            data = last.get("data") or {}
            flag = str(data.get("successFlag", data.get("state") or ""))
            if flag in ("2", "3"):
                raise KieTaskFailed(
                    f"Task {task_id} failed: {data.get('errorMsg') or last.get('msg')}",
                    task_id=task_id, body=last)
            result = self._parse_record(data, task_id)
            done = flag in ("1", "success", "SUCCESS", "completed")
            if done or (result["resultUrls"] and flag not in ("0", "")):
                if output_path and result["resultUrls"]:
                    await self.client._save_results(
                        {"resultUrls": result["resultUrls"]},
                        _AUDIO_ENTRY, task_id, output_path)
                return result
            await asyncio.sleep(interval)
        raise KieTimeout(
            f"Task {task_id} did not finish after {attempts} polls",
            task_id=task_id)

    async def run(self, op: str, *, callback_url: Optional[str] = None,
                  output_path: Optional[str] = None, **params: Any):
        """提交 + 等待一步到位；同步端点（persona/check-voice）直接返回结果。"""
        sub = await self.submit(op, callback_url=callback_url, **params)
        if sub.get("sync"):
            return sub
        return await self.wait(sub["taskId"], output_path=output_path)

    # ------------------------------------------------------------------ #
    # 官网各标签页对应的具名端点（每个都返回 taskId 供下个节点串联）
    # ------------------------------------------------------------------ #
    async def generate(self, **params):
        """Generate Music：生成音乐。required: custom_mode, instrumental, model"""
        return await self.submit("generate", **params)

    async def extend(self, **params):
        """Extend Music：续写扩展。required: audio_id, model"""
        return await self.submit("extend", **params)

    async def upload_and_cover(self, **params):
        """Upload And Cover Audio：上传翻唱。upload_url 或 task_id+audio_id"""
        return await self.submit("upload_and_cover", **params)

    async def upload_and_extend(self, **params):
        """Upload And Extend Audio：上传扩展。required: upload_url, model"""
        return await self.submit("upload_and_extend", **params)

    async def add_instrumental(self, **params):
        """Add Instrumental：添加伴奏。required: upload_url, title, negative_tags, tags"""
        return await self.submit("add_instrumental", **params)

    async def add_vocals(self, **params):
        """Add Vocals：添加人声。required: upload_url, title, negative_tags, style"""
        return await self.submit("add_vocals", **params)

    async def generate_persona(self, **params):
        """Generate Persona（同步）：返回 persona_id（可作 generate/extend 的 persona_id）。
        required: task_id, audio_id, name, description"""
        return await self.submit("generate_persona", **params)

    async def voice_validate(self, **params):
        """Suno Voice 验证短语（链路第 1 步，免费）。required: voice_url, vocal_start_s, vocal_end_s"""
        return await self.submit("voice_validate", **params)

    async def voice_create(self, **params):
        """Suno Voice 创建音色（链路第 3 步，voice_id = 验证任务 taskId）。
        required: task_id(验证任务), verify_url"""
        return await self.submit("voice_create", **params)

    async def voice_check(self, **params):
        """Check Voice（同步）：返回 isAvailable。required: task_id"""
        return await self.submit("voice_check", **params)

    async def voice_regenerate(self, **params):
        """重新生成验证短语（结果更新在原始验证任务上）。required: task_id"""
        return await self.submit("voice_regenerate", **params)

    async def boost_style(self, **params):
        """Boost Music Style：风格增强。required: content（结果可串回 generate 的 style）"""
        return await self.submit("boost_style", **params)

    async def cover_generate(self, **params):
        """Cover Generate：生成封面（2 张）。required: task_id"""
        return await self.submit("cover_generate", **params)

    async def replace_section(self, **params):
        """Replace Section：替换片段。task_id+audio_id 或 upload_url+model；
        required: prompt, tags, title, infill_start_s, infill_end_s, full_lyrics"""
        return await self.submit("replace_section", **params)

    async def mashup(self, **params):
        """Mashup：混音。required: upload_url_list(2 个), model, style, title"""
        return await self.submit("mashup", **params)

    async def sounds(self, **params):
        """Sounds：生成音效。required: prompt, model"""
        return await self.submit("sounds", **params)

    async def generate_lyrics(self, **params):
        """Generate Lyrics：生成歌词。required: prompt(≤200 字)"""
        return await self.submit("generate_lyrics", **params)

    async def timestamped_lyrics(self, **params):
        """Timestamped Lyrics：逐词时间戳歌词。required: task_id, audio_id"""
        return await self.submit("timestamped_lyrics", **params)

    async def separate_vocals(self, **params):
        """Separate Vocals：分轨分离。task_id+audio_id 或 audio_url；
        type: separate_vocal(默认)/split_stem/split_stem_advanced"""
        return await self.submit("separate_vocals", **params)

    async def generate_midi(self, **params):
        """Generate MIDI From Audio：required: task_id(分离任务)；用 wait_midi 取音符"""
        return await self.submit("generate_midi", **params)

    async def recovery_audio(self, **params):
        """Suno Recovery Audio：恢复音频链接。required: task_id；用 wait_recovery 轮询"""
        return await self.submit("recovery_audio", **params)

    async def convert_to_wav(self, **params):
        """Convert To Wav Format：required: task_id, audio_id"""
        return await self.submit("convert_to_wav", **params)

    async def create_music_video(self, **params):
        """Create Music Video：required: task_id, audio_id；可选 author / domain_name"""
        return await self.submit("create_music_video", **params)

    async def await_voice_ready(self, validate_task_id: str,
                                **wait_kwargs) -> Dict[str, Any]:
        """Voice 链路辅助：轮询验证任务至 success，voice_id 即 validate_task_id。"""
        return await self.wait(validate_task_id, **wait_kwargs)

    # ------------------------------------------------------------------ #
    # 特殊轮询
    # ------------------------------------------------------------------ #
    async def wait_recovery(self, task_id: str, *, poll_interval: float = 2.0,
                            max_poll: Optional[int] = None) -> List[Dict[str, Any]]:
        """恢复音频专用轮询（code: 201 运行中 / 200 完成 / 500 失败）。"""
        attempts = max_poll or self.client.max_poll
        url = f"{RECOVERY_INFO_URL}?task_id={task_id}"
        for _ in range(attempts):
            last = await self.client._get_json_retry(url)
            code = last.get("code")
            if code == 201:
                await asyncio.sleep(poll_interval)
                continue
            if code == 200:
                return last.get("data") or []
            raise KieTaskFailed(
                f"Recovery task {task_id} failed (code={code}): {last.get('msg')}",
                task_id=task_id, body=last)
        raise KieTimeout(
            f"Recovery task {task_id} did not finish after {attempts} polls",
            task_id=task_id)

    async def wait_midi(self, task_id: str, **wait_kwargs) -> Dict[str, Any]:
        """MIDI：先轮询任务完成，再拉取音符数据（pitch/start/end/velocity）。"""
        record = await self.wait(task_id, **wait_kwargs)
        last = await self.client._get_json_retry(f"{MIDI_INFO_URL}?taskId={task_id}")
        midi = (last.get("data") or {}) if last.get("code") == 200 else last
        record["midi"] = midi
        return record

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_record(data: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        parsed: Dict[str, Any] = {}
        response = data.get("response") or {}
        rj = response.get("resultJson")
        if isinstance(rj, str) and rj.strip():
            try:
                parsed = json.loads(rj)
            except (ValueError, TypeError):
                parsed = {}
        elif isinstance(rj, dict):
            parsed = rj
        if not parsed and isinstance(response, dict):
            parsed = {k: v for k, v in response.items() if k != "resultJson"}
        urls = parsed.get("resultUrls") or response.get("resultUrls") or []
        if isinstance(urls, str):
            urls = [urls]
        obj = parsed.get("resultObject") or {}
        tracks = obj.get("data") if isinstance(obj, dict) else None
        if tracks is None:
            tracks = parsed.get("data") or []
        return {
            "taskId": task_id,
            "successFlag": data.get("successFlag"),
            "result": data.get("result"),
            "resultUrls": list(urls),
            "tracks": tracks if isinstance(tracks, list) else [tracks],
            "raw": parsed,
        }


# _save_results 需要一个 category=audio 的 entry 占位
from .models import ModelEntry as _ME  # noqa: E402

_AUDIO_ENTRY = _ME(
    id="suno", name="suno", platform="suno", category="audio",
    family="suno", request_style="market", endpoint=CREATE_TASK_URL,
    poll_endpoint=RECORD_INFO_URL, poll_id_param="taskId",
)

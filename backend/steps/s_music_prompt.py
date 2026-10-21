"""音乐提示词优化节点（免费AI音乐分组）。

把用户对音乐的简单描述，按目标平台（ACE-Step / Suno）的提示词规范，
用 LLM 扩写成结构化产物：

  - prompt_zh : 中文音乐提示词（音乐描述）
  - prompt_en : 英文音乐提示词
  - lyrics    : 歌词（带 [Verse]/[Chorus] 结构标记；纯音乐为空）
  - params    : 全信息 JSON（含 BPM / 调式 / 拍号 / 时长 / 语言 / 歌者性别等）

LLM 请求 = 平台提示词指导文档 + 固定输出格式 + 前端设置 + 用户描述。
指导文档：backend/config/prompt_guide/{ACE_MUSIC,SUNO_MUSIC}_PROMPT_GUIDE.md
"""
import os
import json
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.steps.s_musicgen import _read_input_as_text
from backend.llm.llm_client import get_llm_client

_PROMPT_GUIDE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "prompt_guide")

# 优化平台 → 提示词指导文档
_PLATFORM_GUIDE = {
    "ace": "ACE_MUSIC_PROMPT_GUIDE.md",
    "suno": "SUNO_MUSIC_PROMPT_GUIDE.md",
}

# 固定输出格式（LLM 必须严格只输出这个 JSON）
_OUTPUT_FORMAT = """{
  "prompt_zh": "中文音乐提示词：一段自然语言描述，涵盖风格/流派、乐器/编排、情绪/氛围、人声，可含 BPM/调式/拍号",
  "prompt_en": "English music prompt: one paragraph covering genre, instruments/arrangement, mood, vocals, optionally BPM/key/time signature",
  "lyrics": "完整歌词文本，用 [Intro]/[Verse 1]/[Chorus]/[Bridge]/[Outro] 等结构标签并空行分段；纯音乐时此字段为 null",
  "bpm": 120,
  "key_scale": "C Major",
  "time_signature": 4,
  "duration": 240,
  "vocal_language": "zh",
  "singer_gender": "female",
  "style_tags": "genre, mood, vocal 用逗号分隔的英文风格标签"
}"""

_SINGER_GENDER_LABEL = {"male": "男声", "female": "女声", "duet": "对唱（男女对唱）"}


def _load_guide(platform: str) -> str:
    """读取平台提示词指导文档全文（读不到返回空串，不阻断流程）。"""
    name = _PLATFORM_GUIDE.get(platform)
    if not name:
        return ""
    try:
        with open(os.path.join(_PROMPT_GUIDE_DIR, name), "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


class S_MusicPromptOptimizer(BaseStep):
    step_id = "music_prompt_optimizer"
    step_name = "音乐提示词优化"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        return os.path.exists(os.path.join(
            task_dir, "cache", "musicgen", f"{node_id}_prompt_params.json"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}

        # 1. 描述：节点自定义输入直接优先于连线输入
        description = (config.get("custom_description", "") or "").strip()
        if not description:
            description = _read_input_as_text(inputs.get("text", ""), task_dir)
        if not description:
            raise ValueError("音乐描述为空：请连接 text 输入口，或在节点上填写自定义音乐描述。")

        # 2. 设置项
        platform = (config.get("platform") or "ace").strip().lower()
        instrumental = bool(config.get("instrumental"))
        vocal_language = (config.get("vocal_language") or "").strip()
        singer_gender = (config.get("singer_gender") or "").strip()
        llm_model = (config.get("llm_model") or "").strip()
        try:
            temperature = float(config["temperature"])
        except (KeyError, TypeError, ValueError):
            temperature = None

        if callback:
            callback(10, f"准备优化（平台={platform} / 纯音乐={'是' if instrumental else '否'}）...")

        # 3. 组装 LLM 请求：指导文档 + 固定输出格式 + 设置 + 用户描述
        guide = _load_guide(platform)
        settings_lines = [
            f"- 目标平台：{'Suno' if platform == 'suno' else 'ACE-Step'}"
            f"（提示词必须符合该平台的规范与写法）",
            f"- 纯音乐（无人声）：{'是——不要输出歌词，lyrics 字段为 null，描述中强调器乐/配乐' if instrumental else '否'}",
        ]
        if not instrumental:
            if vocal_language:
                settings_lines.append(f"- 歌词演唱语言：{vocal_language}")
            if singer_gender:
                settings_lines.append(
                    f"- 歌者性别：{_SINGER_GENDER_LABEL.get(singer_gender, singer_gender)}")
        settings = "\n".join(settings_lines)

        system_prompt = (
            "你是一位资深的 AI 音乐提示词工程师，精通各音乐生成平台的提示词规范。\n"
            "请严格按照下方平台提示词指导文档的规则，把用户的简单音乐描述扩写成"
            "专业、可直接用于该平台生成的完整提示词与歌词。\n\n"
            f"=== {platform.upper()} 平台提示词指导文档 ===\n{guide}\n"
            f"=== 指导文档结束 ===\n\n"
            "输出要求：严格只输出一个 JSON 对象（不要 Markdown 代码块、不要任何解释文字），"
            "字段与格式如下（值根据用户描述与设置推导；无法确定的数值字段给出合理推荐值或 null）：\n"
            f"{_OUTPUT_FORMAT}"
        )
        user_prompt = (
            f"用户设置：\n{settings}\n\n"
            f"用户的音乐描述：\n{description}"
        )

        # 4. 发起 LLM 请求（response_json=True 自动 json_repair）
        if callback:
            callback(35, "正在调用 LLM 优化提示词...")
        llm = get_llm_client()
        try:
            result = llm.chat(
                step_name=self.step_id,
                prompt=user_prompt,
                response_json=True,
                stream=False,
                system_prompt=system_prompt,
                temperature=temperature,
                model_override=llm_model or None,
            )
        except Exception as e:
            raise RuntimeError(f"音乐提示词优化失败：{e}") from e

        if isinstance(result, str):
            try:
                import json_repair
                result = json_repair.loads(result)
            except Exception:
                result = json.loads(result)
        if not isinstance(result, dict):
            raise RuntimeError(f"LLM 返回格式异常（期望 JSON 对象）：{str(result)[:300]}")

        if callback:
            callback(80, "解析优化结果...")

        # 5. 解析为各输出项
        prompt_zh = str(result.get("prompt_zh") or "").strip()
        prompt_en = str(result.get("prompt_en") or "").strip()
        lyrics = "" if instrumental else str(result.get("lyrics") or "").strip()
        if not prompt_zh and not prompt_en:
            raise RuntimeError("LLM 未返回有效的音乐提示词（prompt_zh / prompt_en 均为空）。")

        # 全信息 JSON：LLM 结果 + 本次设置，落盘供下游节点消费
        params = dict(result)
        params.update({
            "node_id": node_id,
            "platform": platform,
            "instrumental": instrumental,
            "vocal_language": vocal_language,
            "singer_gender": singer_gender,
            "description": description,
            "prompt_zh": prompt_zh,
            "prompt_en": prompt_en,
            "lyrics": lyrics,
        })
        params_dir = os.path.join(task_dir, "cache", "musicgen")
        os.makedirs(params_dir, exist_ok=True)
        params_rel = os.path.join("cache", "musicgen", f"{node_id}_prompt_params.json")
        with open(os.path.join(task_dir, params_rel), "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, "提示词优化完成")

        # 6. 输出端口（纯音乐时歌词端口在节点定义层被隐藏，这里也不输出）
        outputs = {
            "prompt_zh": prompt_zh,
            "prompt_en": prompt_en,
            "params": params_rel,
        }
        if not instrumental:
            outputs["lyrics"] = lyrics
        return {
            "artifacts": [params_rel],
            "outputs": outputs,
        }

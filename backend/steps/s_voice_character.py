# -*- coding: utf-8 -*-
"""
新建音色角色节点（Step）

流程：
  1. 读取输入（文本/JSON/文件路径，兼容解析）或使用面板设计的角色属性；
  2. 经 prompt 组装服务层装配模板，调用 LLM 服务层设计「典型朗读提示词(15~25字)」
     与「TTS 指令描述(50字内)」；
  3. 按设计模式（指令设计 voice_design / 指令克隆 controllable_clone）与 TTS 接口
     发起合成，得到角色默认片段（output_path 直落 task_dir/voice_design/）；
  4. 可选：读取配音谷情绪标签，再次经 LLM 为每个情绪设计朗读文本与语气指令，
     固定以「指令克隆」模式（默认片段为参考音频）用 5 线程池并行合成情绪片段；
  5. 组装音色数据写入 vf_voices，音频复制到 voiceforge 存储约定位置；
  6. 输出：音色ID、音色主片段音频、音色全信息JSON。
"""
import json
import os
import re
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend.steps.base_step import BaseStep

_STEP_LLM_NAME = "s_voice_character"
DESIGN_PROMPT_ID = "s_voice_character_design"
EMOTION_PROMPT_ID = "s_voice_character_emotions"

# 播音风格指令示例（装配进设计 prompt 的示例部分）
INSTRUCT_EXAMPLES = (
    "播音风格示例：热情洋溢的中年男性播音员，声音较为低沉，富有磁性与感染力，"
    "带着逐渐密集的节奏感呼喊宣讲口号；在 TTS 朗读文本中可以通过英文方括号标签，"
    "例如：[laughing] 或 [sigh]、[Uhm], [Shh]、[Question-ah], [Question-ei], "
    "[Question-en], [Question-oh]、[Surprise-wa], [Surprise-yo], "
    "[Dissatisfaction-hnn] 插入到朗读文本中起到细腻的控制。"
)

_CHARACTER_KEY_ALIASES = {
    "name": ("name", "姓名", "角色名", "角色名称"),
    "age": ("age", "年龄"),
    "personality": ("personality", "性格"),
    "dialect": ("dialect", "方言", "方言描述"),
    "occupation_background": ("occupation", "occupation_background", "职业", "职业和背景", "职业与背景", "背景"),
    "voice_description": ("voice_description", "voice", "音色", "音色描述", "音色设计", "音色设计描述"),
}


class S_VoiceCharacter(BaseStep):
    step_id = "voice_character"
    step_name = "新建音色角色"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    @property
    def name(self) -> str:
        return "新建音色角色"

    # ------------------------------------------------------------------ #
    # 角色信息读取
    @classmethod
    def _normalize_character(cls, data: dict) -> dict:
        character = {}
        for key, aliases in _CHARACTER_KEY_ALIASES.items():
            for alias in aliases:
                value = str(data.get(alias) or "").strip()
                if value:
                    character[key] = value
                    break
        return character

    @staticmethod
    def _parse_json_maybe(value: str):
        text = (value or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _read_input_payload(self, value):
        """兼容读取输入:dict / JSON字符串 / 纯文本 / 文本或JSON文件路径。"""
        if value is None:
            return None
        if isinstance(value, dict):
            return {"kind": "json", "data": value, "text": ""}
        text = str(value).strip()
        if not text:
            return None
        parsed = self._parse_json_maybe(text)
        if isinstance(parsed, dict):
            return {"kind": "json", "data": parsed, "text": ""}
        # 文件路径(文本文件 / JSON 文件)
        if os.path.isfile(text):
            raw = Path(text).read_text(encoding="utf-8", errors="replace").strip()
            parsed = self._parse_json_maybe(raw)
            if isinstance(parsed, dict):
                return {"kind": "json", "data": parsed, "text": ""}
            return {"kind": "text", "data": None, "text": raw}
        return {"kind": "text", "data": None, "text": text}

    def _gather_character(self, config: dict, step_inputs: dict) -> tuple[dict, str, str]:
        """返回 (character, source_text, design_source)。"""
        design_source = (config.get("design_source") or "input").strip()
        if design_source == "panel":
            panel = config.get("panel") or {}
            character = self._normalize_character(panel if isinstance(panel, dict) else {})
            if not character.get("name"):
                raise ValueError("面板设计模式下请填写角色姓名")
            return character, "", "panel"

        character: dict = {}
        texts: list[str] = []
        design_payload = self._read_input_payload(step_inputs.get("design_json"))
        if design_payload:
            if design_payload["kind"] == "json":
                character.update(self._normalize_character(design_payload["data"]))
            else:
                texts.append(design_payload["text"])
        description_payload = self._read_input_payload(step_inputs.get("description"))
        if description_payload:
            if description_payload["kind"] == "json":
                for key, value in self._normalize_character(description_payload["data"]).items():
                    character.setdefault(key, value)
            else:
                texts.append(description_payload["text"])
        source_text = "\n".join(part for part in texts if part).strip()
        if not character.get("name") and not source_text:
            raise ValueError("设计信息来源为「来自输入」时，请连接上游输入或填入角色描述文本/角色设计JSON")
        if not character.get("name"):
            character["name"] = ""
        return character, source_text, "input"

    @staticmethod
    def _character_info_text(character: dict, source_text: str) -> str:
        lines = []
        label_map = {"name": "姓名", "age": "年龄", "personality": "性格", "dialect": "方言描述", "occupation_background": "职业和背景", "voice_description": "音色描述"}
        for key, label in label_map.items():
            value = str(character.get(key) or "").strip()
            if value:
                lines.append(f"- {label}:{value}")
        if source_text:
            lines.append(f"- 角色描述:{source_text}")
        return "\n".join(lines) or "（未提供详细信息）"

    # ------------------------------------------------------------------ #
    # LLM
    @staticmethod
    def _parse_json_response(response) -> dict:
        if isinstance(response, dict):
            return response
        if isinstance(response, str):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.strip(), flags=re.I).strip()
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", text, re.S)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        pass
        raise ValueError(f"LLM 返回内容无法解析为 JSON：{str(response)[:160]}")

    def _llm_design(self, prompt_id: str, placeholders: dict) -> dict:
        from backend.llm.llm_client import get_llm_client
        from backend.prompts.prompt_service import PromptService

        service = PromptService()
        service.seed_voiceforge_defaults()
        assembled = service.assemble_prompt(prompt_id, placeholders)
        if not assembled.get("found"):
            raise ValueError(f"找不到 Prompt 模板 {prompt_id}，请检查 voiceforge_prompt_defaults.json")
        response = get_llm_client().chat(
            _STEP_LLM_NAME,
            assembled["user_prompt"],
            system_prompt=assembled["system_prompt"],
            response_json=True,
        )
        return self._parse_json_response(response)

    # ------------------------------------------------------------------ #
    # TTS
    @staticmethod
    def _synthesize(interface_id: str, text: str, output_path: Path, mode: str, instruct: str, ref_audio: str = ""):
        from backend.tts.tts_factory import get_tts_engine

        engine = get_tts_engine(interface_id)
        kwargs = {"mode": mode}
        if mode == "voice_design":
            kwargs["voice_design"] = instruct
        elif mode == "controllable_clone":
            kwargs["controllable_clone"] = instruct
            kwargs["ref_audio"] = ref_audio or None
        try:
            succeeded = engine.synthesize(text, str(output_path), **kwargs)
        except TypeError:
            succeeded = engine.synthesize(text, str(output_path))
        if not succeeded or not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"TTS 合成失败（接口 {interface_id}）：{text[:30]}…")

    def _validate_interface(self, interface_id: str) -> None:
        from backend.tts.tts_interface_manager import get_tts_interface_manager

        if get_tts_interface_manager().get(interface_id) is None:
            raise ValueError(f"TTS 接口「{interface_id}」不存在或未启用，请在设置的 TTS 接口中检查")

    # ------------------------------------------------------------------ #
    # 情绪
    @staticmethod
    def _load_emotion_tags() -> list[tuple[str, str]]:
        from backend.voiceforge.database import session as vf_session

        with vf_session() as conn:
            rows = conn.execute("SELECT name, description FROM vf_emotion_tags ORDER BY sort_order, created_at").fetchall()
        return [(row["name"], row["description"] or "") for row in rows]

    @staticmethod
    def _safe_emotion(name: str) -> str:
        value = "".join(char for char in (name or "") if char.isalnum() or char in "_-" or "\u4e00" <= char <= "\u9fff")[:50]
        return value or "emotion"

    # ------------------------------------------------------------------ #
    # 音色入库
    def _persist_voice(self, character: dict, tts_mode: str, interface_id: str, sample_text: str, instruct: str,
                       main_clip: Path, reference_audio: str, emotion_records: list[dict]) -> dict:
        from backend.voiceforge.database import row_to_dict, session as vf_session, storage_root
        from backend.voiceforge.voice_storage import write_voice_config

        voice_id = uuid.uuid4().hex
        root = storage_root()
        voice_dir = root / "voices" / voice_id
        emotions_dir = voice_dir / "emotions"
        emotions_dir.mkdir(parents=True, exist_ok=True)

        sample_key = f"voices/{voice_id}/design.wav"
        shutil.copy2(main_clip, root / sample_key)

        reference_key = ""
        if reference_audio and Path(reference_audio).is_file():
            ext = os.path.splitext(reference_audio)[1].lower() or ".wav"
            reference_key = f"voices/{voice_id}/reference{ext}"
            shutil.copy2(reference_audio, root / reference_key)

        emotions_json = []
        for item in emotion_records:
            target_key = f"voices/{voice_id}/emotions/{self._safe_emotion(item['emotion'])}.wav"
            shutil.copy2(item["clip"], root / target_key)
            emotions_json.append({
                "name": item["emotion"],
                "audio_path": target_key,
                "text": item["text"],
                "engine": interface_id,
                "instruct": item["instruct"],
            })

        name = character.get("name") or "音色角色"
        description_parts = [character.get("personality"), character.get("occupation_background"), character.get("dialect")]
        description = "；".join(part for part in description_parts if part)[:500]
        design_text = "；".join(part for part in (character.get("voice_description"), instruct) if part)[:500]
        params = {"voice_design": instruct, "controllable_clone": instruct}

        with vf_session() as conn:
            conn.execute(
                "INSERT INTO vf_voices (id, name, display_name, interface_id, voice_id, mode, language, tags_json, description,"
                " reference_storage_key, preview_storage_key, preview_text, params_json, gender, voice_age, voice_pitch, dialect,"
                " is_cloned, is_builtin, design_text, voice_group, sample_storage_key, emotions_json, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    voice_id, name, name, interface_id, "", tts_mode, "zh-CN",
                    json.dumps(["音色角色"], ensure_ascii=False), description,
                    reference_key, "", sample_text,
                    json.dumps(params, ensure_ascii=False),
                    character.get("gender", ""), character.get("age", ""), "", character.get("dialect", ""),
                    int(tts_mode == "controllable_clone"), 0, design_text, "", sample_key,
                    json.dumps(emotions_json, ensure_ascii=False), "ready",
                ),
            )
            row = conn.execute("SELECT * FROM vf_voices WHERE id = ?", (voice_id,)).fetchone()
        write_voice_config(voice_id)
        return row_to_dict(row)

    # ------------------------------------------------------------------ #
    def run(self, task_dir, callback=None, cancel_callback=None):
        config = getattr(self, "config", None) or getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        cancel = cancel_callback or (lambda: False)
        report = callback or (lambda *a, **k: None)

        interface_id = (config.get("interface_id") or "voxcpm").strip()
        tts_mode = config.get("tts_mode") or "voice_design"
        if tts_mode not in ("voice_design", "controllable_clone"):
            raise ValueError(f"不支持的设计模式：{tts_mode}")
        reference_audio = (config.get("reference_audio") or "").strip()
        if tts_mode == "controllable_clone":
            if not reference_audio:
                raise ValueError("指令克隆模式需要在节点卡片选择参考音频")
            if not os.path.isfile(reference_audio):
                raise ValueError(f"参考音频不存在：{reference_audio}")
        self._validate_interface(interface_id)
        generate_emotions = bool(config.get("generate_emotions"))

        report(3, "读取角色设计信息…")
        character, source_text, design_source = self._gather_character(config, step_inputs)
        character_info = self._character_info_text(character, source_text)
        character_name = character.get("name") or "未命名角色"

        # 1) LLM 设计朗读提示词与指令描述
        report(10, "LLM 正在设计音色提示词与指令描述…")
        design = self._llm_design(DESIGN_PROMPT_ID, {
            "character_name": character_name,
            "character_info": character_info,
            "instruct_examples": INSTRUCT_EXAMPLES,
        })
        sample_text = str(design.get("sample_text") or "").strip()
        instruct = str(design.get("instruct") or "").strip()
        if not sample_text or not instruct:
            raise ValueError(f"LLM 设计结果不完整：{json.dumps(design, ensure_ascii=False)[:160]}")
        if len(instruct) > 120:
            instruct = instruct[:120]
        report(20, f"设计完成：{sample_text}")

        # 2) TTS 生成默认片段
        clips_dir = Path(task_dir) / "voice_design"
        clips_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", character_name)[:60] or "voice_character"
        main_clip = clips_dir / f"{safe_name}_main.wav"
        report(30, f"TTS 合成角色默认片段（{interface_id} · {'指令设计' if tts_mode == 'voice_design' else '指令克隆'}）…")
        self._synthesize(interface_id, sample_text, main_clip, tts_mode, instruct, reference_audio)
        if cancel():
            main_clip.unlink(missing_ok=True)
            raise RuntimeError("用户已取消")

        # 3) 多情绪片段
        emotion_records: list[dict] = []
        failed_emotions: list[str] = []
        if generate_emotions:
            report(45, "读取配音谷情绪标签…")
            emotion_tags = self._load_emotion_tags()
            if not emotion_tags:
                report(50, "配音谷未配置情绪标签，已跳过多情绪片段生成")
            else:
                tag_lines = "\n".join(f"- {name}:{desc}" if desc else f"- {name}" for name, desc in emotion_tags)
                report(50, "LLM 正在设计各情绪朗读文本与语气指令…")
                emotion_design = self._llm_design(EMOTION_PROMPT_ID, {
                    "character_name": character_name,
                    "character_info": character_info,
                    "sample_text": sample_text,
                    "instruct": instruct,
                    "emotion_tags": tag_lines,
                })
                raw_emotions = emotion_design.get("emotions") or []
                if not isinstance(raw_emotions, list) or not raw_emotions:
                    raise ValueError(f"LLM 情绪设计结果为空：{json.dumps(emotion_design, ensure_ascii=False)[:160]}")
                tasks = []
                seen = set()
                for item in raw_emotions:
                    if not isinstance(item, dict):
                        continue
                    emotion = str(item.get("emotion") or "").strip()
                    text = str(item.get("text") or "").strip()
                    instruct_i = str(item.get("instruct") or "").strip()
                    if not emotion or not text or emotion in seen:
                        continue
                    seen.add(emotion)
                    tasks.append({"emotion": emotion, "text": text, "instruct": instruct_i or instruct})
                report(55, f"并行合成 {len(tasks)} 个情绪片段（指令克隆 · 5 线程）…")
                with ThreadPoolExecutor(max_workers=5) as pool:
                    futures = {}
                    for item in tasks:
                        clip = clips_dir / f"{safe_name}_{self._safe_emotion(item['emotion'])}.wav"
                        futures[pool.submit(self._synthesize, interface_id, item["text"], clip, "controllable_clone", item["instruct"], str(main_clip))] = {**item, "clip": clip}
                    for future in as_completed(futures):
                        item = futures[future]
                        try:
                            future.result()
                            emotion_records.append(item)
                        except Exception as exc:
                            failed_emotions.append(f"{item['emotion']}（{exc}）")
                emotion_records.sort(key=lambda item: item["emotion"])
                if failed_emotions:
                    report(70, f"部分情绪片段合成失败：{'；'.join(failed_emotions)}")

        # 4) 写入音色库
        report(85, "写入配音谷音色库…")
        voice = self._persist_voice(character, tts_mode, interface_id, sample_text, instruct, main_clip, reference_audio, emotion_records)
        sample_abs = str(Path(_voiceforge_root()) / "voices" / voice["id"] / "design.wav")

        info = {
            "voice": voice,
            "design": {
                "design_source": design_source,
                "character": character,
                "character_info": character_info,
                "mode": tts_mode,
                "interface_id": interface_id,
                "sample_text": sample_text,
                "instruct": instruct,
                "reference_audio": reference_audio,
                "generate_emotions": generate_emotions,
                "emotions": [
                    {
                        "emotion": item["emotion"],
                        "text": item["text"],
                        "instruct": item["instruct"],
                        "task_clip": str(item["clip"]),
                    }
                    for item in emotion_records
                ],
                "failed_emotions": failed_emotions,
            },
            "files": {
                "main_clip": str(main_clip),
                "clips_dir": str(clips_dir),
            },
        }

        artifacts = [str(main_clip)] + [str(item["clip"]) for item in emotion_records]
        report(100, f"已完成：音色「{voice.get('display_name') or name}」({voice['id'][:8]}…)")
        return {
            "artifacts": artifacts,
            "outputs": {
                "voice_id": voice["id"],
                "audio": sample_abs,
                "info": info,
            },
        }


def _voiceforge_root() -> str:
    from backend.voiceforge.database import storage_root

    return str(storage_root())

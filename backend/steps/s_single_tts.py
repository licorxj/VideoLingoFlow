"""单句配音 TTS 节点：只对一句短文本做 TTS，返回配音音频。

与「长文本TTS」节点的区别：
- 输入是**一句话**（兼容直接文本与文本文件路径），节点不做分句、不合并音频；
- 只调用一次 TTS 引擎，产出一个 wav，直接返回音频路径与时长；
- 不做时间槽调速、不做参考音频切割、不做多角色标记解析；
- 超过建议字数只告警不切分（长文请用「长文本TTS」节点）。

引擎调用、参考音频/音色解析、角色匹配与时长读取等全部复用 ``S09TTS``。
"""
import json
import os
import shutil
import time
from typing import Callable, Dict, Optional

from backend.steps.s09_tts import S09TTS
from backend.steps.io_resolve import resolve_text_input


class S_SingleSentenceTTS(S09TTS):
    step_id = "s_single_tts"
    step_name = "单句配音TTS"
    dependencies = []
    artifacts: list = []

    # ── 路径约定 ───────────────────────────────────────────────────────
    def _nid(self) -> str:
        """当前节点 id（运行时以实例属性 ``_node_id`` 注入）。"""
        return getattr(self, "_node_id", "") or "single_tts"

    def _node_dir(self, task_dir: str) -> str:
        return os.path.join(task_dir, "cache", f"single_tts_{self._nid()}")

    def _audio_path(self, task_dir: str) -> str:
        return os.path.join(self._node_dir(task_dir), "single.wav")

    def _record_path(self, task_dir: str) -> str:
        return os.path.join(task_dir, "cache", f"single_tts_record_{self._nid()}.json")

    @staticmethod
    def _rel(path: str, task_dir: str) -> str:
        return os.path.relpath(path, task_dir).replace("\\", "/")

    # ── BaseStep 接口 ──────────────────────────────────────────────────
    def check_artifact(self, task_dir: str) -> bool:
        # 勾选「覆盖已有音频」时强制重跑
        if (getattr(self, "_node_config", {}) or {}).get("overwrite_generate", False):
            return False
        audio_path = self._audio_path(task_dir)
        return os.path.isfile(audio_path) and os.path.getsize(audio_path) > 0

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        return bool(resolve_text_input(step_inputs.get("text"), task_dir).strip())

    def rollback(self, task_dir: str):
        """清理本节点的音频与记录文件。"""
        shutil.rmtree(self._node_dir(task_dir), ignore_errors=True)
        record_path = self._record_path(task_dir)
        if os.path.isfile(record_path):
            try:
                os.remove(record_path)
            except OSError:
                pass

    # ── 记录 ───────────────────────────────────────────────────────────
    @staticmethod
    def _flush_json(path: str, data: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

    # ── 主流程 ─────────────────────────────────────────────────────────
    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_cfg = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        cancel = cancel_callback or (lambda: False)

        if callback:
            callback(5, "解析输入文本...")

        # 1) 输入文本：兼容内存文本与文本文件路径；单句配音不切分
        text = str(resolve_text_input(step_inputs.get("text"), task_dir) or "").strip()
        if not text:
            raise ValueError(
                "单句配音TTS 缺少输入文本：请连接上游文本输出，或选择文本文件路径。"
            )
        warn_chars = int(node_cfg.get("max_chars") or 100)
        if warn_chars > 0 and len(text) > warn_chars:
            print(
                f"[单句配音TTS] 输入 {len(text)} 字，超过建议上限 {warn_chars} 字；"
                f"本节点不分句，仍按整句配音（长文请改用「长文本TTS」节点）"
            )
        print(f"[单句配音TTS] 待配音文本（{len(text)} 字）：{text[:60]}{'…' if len(text) > 60 else ''}")

        # 2) TTS 配置（复用 TTS 节点的解析逻辑）
        tts_config = self._parse_tts_config()

        # 3) 片段描述（沿用 TTS 任务单字段，便于复用引擎调用与角色匹配）
        node_id = self._nid()
        audio_abs = self._audio_path(task_dir)
        os.makedirs(os.path.dirname(audio_abs), exist_ok=True)
        seg: Dict = {
            "index": 0,
            "text": text,
            "read_text": text,
            "read_tone_desc": "",
            "start": 0.0,
            "end": 0.0,
            "duration": 0.0,
            "original_duration": 0.0,
            "gap_after": 0.0,
            "speed_ratio": 1.0,
            "audio_file": self._rel(audio_abs, task_dir),
            "character_id": 0,
            "read_character_id": 0,
            "character_voice_desc": "",
            "dialect": "",
            "方言": "",
        }
        self._match_characters([seg], tts_config)

        # 4) 配音（已有音频且未勾选覆盖时直接复用）
        overwrite = bool(node_cfg.get("overwrite_generate", False))
        reused = False
        if (not overwrite) and os.path.isfile(audio_abs) and os.path.getsize(audio_abs) > 0:
            reused = True
            print("[单句配音TTS] 已存在配音音频，跳过生成（勾选「覆盖已有音频」可强制重配）")
            if callback:
                callback(80, "复用已有配音音频...")
        else:
            if cancel():
                raise RuntimeError("单句配音TTS 已取消")
            if callback:
                callback(30, "调用 TTS 引擎合成单句配音...")
            ok = self._try_real_tts(seg, tts_config, audio_abs, task_dir, None)
            if not ok or not os.path.isfile(audio_abs) or os.path.getsize(audio_abs) <= 0:
                print("[单句配音TTS] 首次合成失败，1 秒后重试一次...")
                time.sleep(1)
                ok = self._try_real_tts(seg, tts_config, audio_abs, task_dir, None)
            if not ok or not os.path.isfile(audio_abs) or os.path.getsize(audio_abs) <= 0:
                raise RuntimeError(
                    "单句配音失败：TTS 引擎未产出有效音频。\n"
                    "提示：检查 TTS 模式/引擎/音色配置、参考音频是否有效，以及网络连通性后重试。"
                )

        # 5) 结果：时长 + 记录 JSON
        duration = self._get_audio_duration(audio_abs)
        record = {
            "node_id": node_id,
            "engine": tts_config.get("engine"),
            "mode": tts_config.get("mode"),
            "model": tts_config.get("model"),
            "text": text,
            "chars": len(text),
            "audio_file": self._rel(audio_abs, task_dir),
            "duration": round(float(duration or 0.0), 4),
            "generated": not reused,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        record_path = self._record_path(task_dir)
        self._flush_json(record_path, record)

        audio_rel = self._rel(audio_abs, task_dir)
        record_rel = self._rel(record_path, task_dir)
        self.artifacts = [audio_rel, record_rel]

        if callback:
            callback(100, f"配音完成：{duration:.2f} 秒" if duration else "配音完成")

        return {
            "artifacts": self.artifacts,
            "outputs": {
                "audio": audio_rel,
                "duration": round(float(duration or 0.0), 3),
                "record": record_rel,
            },
        }


StepSingleSentenceTTS = S_SingleSentenceTTS

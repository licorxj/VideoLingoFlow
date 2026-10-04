"""长文本 TTS 节点：把一整段长文本（或文本文件）分句后逐句配音。

与「语音合成 (TTS)」节点的区别：
- 输入是**原始长文本**（兼容内存文本与文本文件路径），不依赖上游任务单；
- 节点内部自行分句，逐句调用 TTS 生成音频片段（缓存目录下的 wav）；
- 每完成一句就把「输入文本 + 该句音频片段路径」**增量**写入任务目录下的
  ``cache/tts_record_<node_id>.json``，进程中断也不丢已完成记录；
- 两个输出端口：① 音频路径（合并后的完整音频文件）② 记录 JSON 路径。

引擎调用、参考音频解析、音色解析、调速与完整性校验等全部复用
``S09TTS`` 的实现，仅重写编排逻辑（run / 输入输出 / 记录）。
"""
import os
import json
import shutil
import subprocess
import time
from typing import Callable, Dict, List, Optional

from backend.steps.s09_tts import S09TTS
from backend.steps.io_resolve import resolve_text_input


class S_LongTextTTS(S09TTS):
    step_id = "s_long_text_tts"
    step_name = "长文本TTS"
    dependencies = []
    artifacts: list = []

    # ── 路径约定 ───────────────────────────────────────────────────────
    def _nid(self) -> str:
        """当前节点 id（运行时以实例属性 ``_node_id`` 注入）。"""
        return getattr(self, "_node_id", "") or "long_text_tts"

    def _node_dir(self, task_dir: str) -> str:
        return os.path.join(task_dir, "cache", f"long_tts_{self._nid()}")

    def _segment_dir(self, task_dir: str) -> str:
        return os.path.join(self._node_dir(task_dir), "segments")

    def _record_path(self, task_dir: str) -> str:
        return os.path.join(task_dir, "cache", f"tts_record_{self._nid()}.json")

    def _merged_audio_path(self, task_dir: str) -> str:
        return os.path.join(self._node_dir(task_dir), f"full_{self._nid()}.wav")

    @staticmethod
    def _rel(path: str, task_dir: str) -> str:
        return os.path.relpath(path, task_dir).replace("\\", "/")

    # ── BaseStep 接口 ──────────────────────────────────────────────────
    def check_artifact(self, task_dir: str) -> bool:
        # 勾选「覆盖已有音频」时强制重跑
        node_cfg = getattr(self, "_node_config", {}) or {}
        if node_cfg.get("overwrite_generate", False):
            return False
        record_path = self._record_path(task_dir)
        if not os.path.isfile(record_path):
            return False
        try:
            with open(record_path, "r", encoding="utf-8") as f:
                record = json.load(f)
        except Exception:
            return False
        segments = record.get("segments") or []
        if not segments:
            return False
        for seg in segments:
            audio_rel = str(seg.get("audio_file") or "")
            audio_path = audio_rel if os.path.isabs(audio_rel) else os.path.join(task_dir, audio_rel)
            if not os.path.isfile(audio_path) or os.path.getsize(audio_path) <= 0:
                return False
        return True

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        return bool(resolve_text_input(step_inputs.get("text"), task_dir).strip())

    def rollback(self, task_dir: str):
        """清理本节点的音频目录与记录文件。"""
        shutil.rmtree(self._node_dir(task_dir), ignore_errors=True)
        record_path = self._record_path(task_dir)
        if os.path.isfile(record_path):
            try:
                os.remove(record_path)
            except OSError:
                pass

    # ── 文本分句 ───────────────────────────────────────────────────────
    @staticmethod
    def _pre_split(text: str, terminals: set) -> List[str]:
        """在终止标点处切分，标点保留在前一段末尾。"""
        if not text:
            return []
        chunks: List[str] = []
        current = ""
        for ch in text:
            current += ch
            if ch in terminals:
                chunks.append(current)
                current = ""
        if current:
            chunks.append(current)
        return chunks

    @classmethod
    def _hard_split(cls, text: str, max_chars: int, compact: bool) -> List[str]:
        """无法再按标点切分时按字数硬切（英文尽量落在词边界）。"""
        if len(text) <= max_chars:
            return [text]
        if compact:
            return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
        words = text.split(" ")
        out: List[str] = []
        buf = ""
        for w in words:
            candidate = f"{buf} {w}".strip()
            if buf and len(candidate) > max_chars:
                out.append(buf)
                buf = w
            else:
                buf = candidate
        if buf:
            out.append(buf)
        # 单词本身超长时兜底硬切
        final: List[str] = []
        for piece in out:
            if len(piece) <= max_chars:
                final.append(piece)
            else:
                final.extend(piece[i:i + max_chars] for i in range(0, len(piece), max_chars))
        return final

    @classmethod
    def _split_text(cls, text: str, max_chars: int) -> List[str]:
        """把长文本切分为长度受控的句子列表。"""
        from backend.utils.sentence_split_utils import (
            load_language_puncts,
            clean_sentence_text,
            is_compact_spacing_language,
        )

        max_chars = max(10, int(max_chars or 80))
        puncts = load_language_puncts("auto") or {}
        sentence_ends = set(puncts.get("sentence_ends") or set()) | set("。！？!?…；;\n")
        clause_breaks = set(puncts.get("clause_breaks") or set()) | set("，,、：:；;")
        compact = is_compact_spacing_language("auto")

        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")

        # Step 1：先按句末标点切成原始句块
        raw = cls._pre_split(normalized, sentence_ends)

        # Step 2：合并短句块，尽量不超过 max_chars（不把一句拆散）
        merged: List[str] = []
        buf = ""
        for piece in raw:
            piece = clean_sentence_text(piece, "auto")
            if not piece:
                continue
            if not buf:
                buf = piece
                continue
            if len(buf) + len(piece) <= max_chars:
                buf += piece
            else:
                merged.append(buf)
                buf = piece
        if buf:
            merged.append(buf)

        # Step 3：对仍然超长的句子按从句标点 / 字数二次切分
        result: List[str] = []
        for sentence in merged:
            if len(sentence) <= max_chars:
                result.append(sentence)
                continue
            parts = cls._pre_split(sentence, clause_breaks)
            sub: List[str] = []
            buf2 = ""
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                if not buf2:
                    buf2 = p
                elif len(buf2) + len(p) <= max_chars:
                    buf2 += p
                else:
                    sub.append(buf2)
                    buf2 = p
            if buf2:
                sub.append(buf2)
            for p in sub:
                result.extend(cls._hard_split(p, max_chars, compact))

        return [s.strip() for s in result if s and s.strip()]

    # ── 增量记录 ───────────────────────────────────────────────────────
    @staticmethod
    def _flush_record(record_path: str, record: dict) -> None:
        os.makedirs(os.path.dirname(record_path), exist_ok=True)
        record["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tmp_path = record_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, record_path)

    # ── 音频合并 ───────────────────────────────────────────────────────
    @classmethod
    def _merge_audio(cls, audio_paths: List[str], out_path: str) -> Optional[str]:
        """把逐句音频合并为一个完整音频文件。返回合并路径（几乎总是成功）。

        合并分层（前一层失败自动落到下一层）：
          1) wave 直接拼接：参数完全一致时无损、最快；
          2) ffmpeg concat：先试无损 copy，参数不一致再重编码到统一格式；
          3) 纯 Python(numpy) 兜底：把各段重采样/统一声道后拼接，无需 ffmpeg；
          4) 终极兜底：全部失败则复制首个有效片段，保证输出端口①不为空。
        """
        valid = [p for p in audio_paths if p and os.path.isfile(p) and os.path.getsize(p) > 0]
        if not valid:
            return None
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        if len(valid) == 1:
            shutil.copyfile(valid[0], out_path)
            return out_path

        # 1) wave 直接拼接
        try:
            import wave
            params = None
            frames = []
            for p in valid:
                with wave.open(p, "rb") as w:
                    cur = (w.getnchannels(), w.getsampwidth(), w.getframerate())
                    if params is None:
                        params = cur
                    elif cur != params:
                        raise ValueError("wav 参数不一致")
                    frames.append(w.readframes(w.getnframes()))
            with wave.open(out_path, "wb") as out:
                out.setnchannels(params[0])
                out.setsampwidth(params[1])
                out.setframerate(params[2])
                for fr in frames:
                    out.writeframes(fr)
            print(f"[长文本TTS] 已用 wave 拼接 {len(valid)} 段音频 -> {out_path}")
            return out_path
        except Exception as e:
            print(f"[长文本TTS] wave 拼接失败（{e}），尝试 ffmpeg")

        # 2) ffmpeg：先无损 copy，再重编码兜底
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            try:
                list_path = out_path + ".concat.txt"
                with open(list_path, "w", encoding="utf-8") as f:
                    for p in valid:
                        safe = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
                        f.write(f"file '{safe}'\n")
                # 2a) 无损 copy
                cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                       "-f", "concat", "-safe", "0", "-i", list_path,
                       "-c", "copy", out_path]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                if proc.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                    print(f"[长文本TTS] 已用 ffmpeg(copy) 拼接 {len(valid)} 段 -> {out_path}")
                    return out_path
                # 2b) 参数不一致：重编码到统一格式（16-bit 单声道 44.1k）
                cmd2 = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "concat", "-safe", "0", "-i", list_path,
                        "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1", out_path]
                proc2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=1800)
                if proc2.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                    print(f"[长文本TTS] 已用 ffmpeg(重编码) 拼接 {len(valid)} 段 -> {out_path}")
                    return out_path
                print(f"[长文本TTS] ffmpeg 合并失败: {proc2.stderr[:300]}")
            except Exception as e:
                print(f"[长文本TTS] ffmpeg 合并异常: {e}")
            finally:
                if os.path.isfile(list_path):
                    try:
                        os.remove(list_path)
                    except OSError:
                        pass

        # 3) 纯 Python(numpy) 兜底：重采样到统一参数后拼接（无需 ffmpeg）
        try:
            return cls._numpy_merge(valid, out_path)
        except Exception as e:
            print(f"[长文本TTS] numpy 合并失败: {e}")

        # 4) 终极兜底：复制首个有效片段，保证端口①不为空
        print("[长文本TTS] 全部合并方式失败，回退到首个有效片段")
        shutil.copyfile(valid[0], out_path)
        return out_path

    @staticmethod
    def _numpy_merge(valid: List[str], out_path: str) -> Optional[str]:
        """用 numpy 把参数可能不一致的 wav 重采样/统一声道后无损级拼接。

        统一目标：采样率取各段最大值、声道数取最大值、位深统一 16-bit。
        返回合并路径；任何异常抛出交由调用方落到终极兜底。
        """
        import wave
        import numpy as np

        streams = []
        target_rate = 0
        target_ch = 0
        for p in valid:
            with wave.open(p, "rb") as w:
                ch = w.getnchannels()
                sw = w.getsampwidth()
                fr = w.getframerate()
                n = w.getnframes()
                raw = w.readframes(n)
            if sw == 1:                       # 8-bit 无符号
                arr = np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0
            elif sw == 2:                     # 16-bit 有符号
                arr = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
            elif sw == 4:                     # 32-bit 有符号
                arr = np.frombuffer(raw, dtype=np.int32).astype(np.float64) / 65536.0
            else:                             # 罕见位深（如 24-bit）按 16-bit 近似
                arr = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
            if ch > 1:
                arr = arr.reshape(-1, ch)
            else:
                arr = arr.reshape(-1, 1)
            streams.append({"data": arr, "rate": fr, "ch": ch})
            target_rate = max(target_rate, fr)
            target_ch = max(target_ch, ch)

        chunks = []
        for s in streams:
            data = s["data"]                  # (frames, ch)
            # 声道数统一到 target_ch（不足则复制首声道填充，超出则截断）
            if data.shape[1] < target_ch:
                fill = np.repeat(data[:, 0:1], target_ch - data.shape[1], axis=1)
                data = np.concatenate([data, fill], axis=1)
            elif data.shape[1] > target_ch:
                data = data[:, :target_ch]
            # 采样率统一到 target_rate（线性插值重采样）
            if s["rate"] != target_rate and data.shape[0] > 1:
                n_new = int(round(data.shape[0] * target_rate / s["rate"]))
                x_old = np.arange(data.shape[0])
                x_new = np.linspace(0.0, data.shape[0] - 1, n_new)
                data = np.stack(
                    [np.interp(x_new, x_old, data[:, c]) for c in range(target_ch)],
                    axis=1,
                )
            chunks.append(data)

        combined = np.concatenate(chunks, axis=0)
        combined = np.clip(combined, -32768.0, 32767.0).astype(np.int16)
        with wave.open(out_path, "wb") as out:
            out.setnchannels(target_ch)
            out.setsampwidth(2)
            out.setframerate(target_rate)
            out.writeframes(combined.tobytes())
        print(f"[长文本TTS] 已用 numpy 拼接 {len(valid)} 段 -> {out_path}")
        return out_path

    # ── 主流程 ─────────────────────────────────────────────────────────
    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_cfg = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        cancel = cancel_callback or (lambda: False)

        if callback:
            callback(5, "解析输入文本...")

        # 1) 解析输入文本：兼容内存文本与文本文件路径
        text = resolve_text_input(step_inputs.get("text"), task_dir)
        text = str(text or "").strip()
        if not text:
            raise ValueError(
                "长文本TTS 缺少输入文本：请连接上游文本输出，或选择文本文件路径。"
            )

        # 2) TTS 配置（复用 TTS 节点解析逻辑）
        tts_config = self._parse_tts_config()

        # 3) 分句
        max_chars = int(node_cfg.get("max_chars") or 80)
        sentences = self._split_text(text, max_chars)
        if not sentences:
            raise ValueError("输入文本分句后为空，请检查文本内容。")
        total = len(sentences)
        print(f"[长文本TTS] 输入文本 {len(text)} 字，切分为 {total} 句（单句上限 {max_chars} 字）")

        # 4) 构建片段（沿用 TTS 任务单字段，便于复用引擎与完整性校验）
        node_id = self._nid()
        seg_dir = self._segment_dir(task_dir)
        os.makedirs(seg_dir, exist_ok=True)

        segments: List[Dict] = []
        for i, sentence in enumerate(sentences):
            audio_abs = os.path.join(seg_dir, f"{i:04d}.wav")
            segments.append({
                "index": i,
                "text": sentence,
                "read_text": sentence,
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
            })

        self._match_characters(segments, tts_config)

        # 5) 初始化增量记录 JSON
        record_path = self._record_path(task_dir)
        record: Dict = {
            "node_id": node_id,
            "engine": tts_config.get("engine"),
            "mode": tts_config.get("mode"),
            "model": tts_config.get("model"),
            "max_chars": max_chars,
            "input_text": text,
            "total": total,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": "",
            "segments": [],
        }
        self._flush_record(record_path, record)
        if callback:
            callback(10, f"共 {total} 句，开始逐句配音...")

        # 6) 逐句配音 + 增量记录
        overwrite_generate = bool(node_cfg.get("overwrite_generate", False))
        success_count = 0
        fail_count = 0
        skip_count = 0

        for done, seg in enumerate(segments, start=1):
            if cancel():
                print("[长文本TTS] 收到取消请求，停止后续配音（已完成的记录已保存）")
                break

            audio_abs = os.path.join(task_dir, seg["audio_file"])
            status = "ok"
            real_dur = 0.0

            if (not overwrite_generate) and os.path.isfile(audio_abs) and os.path.getsize(audio_abs) > 0:
                status = "skip"
                skip_count += 1
            else:
                ok = self._try_real_tts(seg, tts_config, audio_abs, task_dir, None)
                if not ok:
                    time.sleep(1)
                    ok = self._try_real_tts(seg, tts_config, audio_abs, task_dir, None)
                if ok and os.path.isfile(audio_abs) and os.path.getsize(audio_abs) > 0:
                    success_count += 1
                else:
                    status = "fail"
                    fail_count += 1

            if os.path.isfile(audio_abs) and os.path.getsize(audio_abs) > 0:
                real_dur = self._get_audio_duration(audio_abs)
                if real_dur > 0:
                    seg["real_duration"] = round(real_dur, 4)

            # 增量写入记录（每句一条）
            record["segments"].append({
                "index": seg["index"],
                "text": seg["text"],
                "audio_file": seg["audio_file"],
                "duration": round(real_dur, 4),
                "status": status,
            })
            self._flush_record(record_path, record)

            if callback:
                progress = 10 + int(done / total * 80)
                callback(progress, f"配音进度: {done}/{total} 句")

        # 7) 完整性校验：缺失/静音片段补一轮，仍失败则抛错
        missing = self._collect_incomplete_segments(segments, task_dir)
        if missing:
            missing = self._regenerate_incomplete_segments(
                segments, task_dir, tts_config, {}, missing, callback
            )
            if missing:
                raise RuntimeError(
                    f"[长文本TTS] 有 {len(missing)} 句未生成有效音频"
                    f"（句子索引: {missing}），请检查 TTS 引擎配置、参考音频与网络后重试。"
                )

        # 8) 生成顺序时间戳（长文本无原始时间轴，按真实时长顺排）
        self._generate_sequential_timestamps(segments)

        # 9) 合并为一个完整音频（输出端口①）
        if callback:
            callback(92, "合并音频片段...")
        merged_path = self._merge_audio(
            [os.path.join(task_dir, s["audio_file"]) for s in segments],
            self._merged_audio_path(task_dir),
        )

        # 10) 写出标准 TTS 任务单（json + csv），供其它下游节点复用
        dub_task_path = os.path.join(self._node_dir(task_dir), f"dub_task_{node_id}.json")
        dub_data = {
            "segments": segments,
            "total_segments": len(segments),
            "source": "long_text_tts",
            "input_text": text,
        }
        with open(dub_task_path, "w", encoding="utf-8") as f:
            json.dump(dub_data, f, ensure_ascii=False, indent=2)
        csv_path = os.path.join(self._node_dir(task_dir), f"dub_task_{node_id}.csv")
        self._write_dub_task_csv(segments, csv_path)

        # 11) 回填记录：补充时间轴、合并音频与任务单路径
        by_index = {s["index"]: s for s in segments}
        for entry in record["segments"]:
            seg = by_index.get(entry["index"])
            if seg:
                entry["start"] = seg.get("start")
                entry["end"] = seg.get("end")
                entry["duration"] = seg.get("real_duration") or entry.get("duration")
                entry["real_duration"] = seg.get("real_duration")
        record["merged_audio"] = self._rel(merged_path, task_dir) if merged_path else ""
        record["dub_task_json"] = self._rel(dub_task_path, task_dir)
        record["dub_task_csv"] = self._rel(csv_path, task_dir)
        record["success"] = success_count
        record["fail"] = fail_count
        record["skip"] = skip_count
        self._flush_record(record_path, record)

        record_rel = self._rel(record_path, task_dir)
        audio_rel = self._rel(merged_path, task_dir) if merged_path else ""

        self.artifacts = [self._rel(self._node_dir(task_dir), task_dir), record_rel]

        if callback:
            callback(100, f"完成: {total} 句（成功 {success_count} / 跳过 {skip_count}）")

        return {
            "artifacts": self.artifacts,
            "outputs": {
                "audio": audio_rel,
                "record": record_rel,
            },
        }


StepLongTextTTS = S_LongTextTTS

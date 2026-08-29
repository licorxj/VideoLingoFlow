"""ASR base class: extensible interface for speech recognition."""
from abc import ABC, abstractmethod
from typing import Callable, Optional, List, Dict, Any

# ---------------------------------------------------------------------------
# 说话人字段统一
# 各 ASR 引擎对说话人标签的字段名不一致（speaker / speaker_id / spk_id 等），
# 且有的引擎只在段级标注、有的只在词级标注。这里集中把结果归一为统一的
# ``speaker`` 字段，并把段级 speaker 下放到词级，保证下游节点（按句或按词读取）
# 拿到一致的格式。
# ---------------------------------------------------------------------------
_SPEAKER_KEY = "speaker"
_SPEAKER_ID_KEYS = ("speaker_id", "speakerId", "spk_id")


def _rename_speaker_in(obj: dict):
    """把 obj 上的 speaker_id 等变体重命名为 speaker，返回最终 speaker 值。"""
    val = obj.get(_SPEAKER_KEY)
    for alt in _SPEAKER_ID_KEYS:
        if alt in obj:
            if val in (None, ""):
                val = obj[alt]
            del obj[alt]
    if val not in (None, ""):
        obj[_SPEAKER_KEY] = val
    else:
        obj.pop(_SPEAKER_KEY, None)
    return val


def normalize_speaker_format(result: dict) -> dict:
    """统一 ASR 结果中的说话人字段格式（幂等，可重复调用）。

    规则：
    1. 段 / 词上的 ``speaker_id``（以及 ``speakerId`` / ``spk_id`` / ``spk`` 变体）
       统一重命名为 ``speaker``。
    2. 当某 segment 标注了 ``speaker``、而它内部的 word 没有 ``speaker`` 时，
       把段级 speaker 下放到每个 word，避免下游按词读取时取不到说话人。
    """
    if not isinstance(result, dict):
        return result
    segments = result.get("segments")
    if not isinstance(segments, list):
        return result

    for seg in segments:
        if not isinstance(seg, dict):
            continue
        seg_speaker = _rename_speaker_in(seg)
        words = seg.get("words")
        if isinstance(words, list):
            for w in words:
                if not isinstance(w, dict):
                    continue
                w_speaker = _rename_speaker_in(w)
                if seg_speaker and not w_speaker:
                    w[_SPEAKER_KEY] = seg_speaker
    return result


class ASRBase(ABC):
    """Abstract base class for ASR engines.

    All engines must implement transcribe(). Optional kwargs allow engines
    to accept extra configuration (model, language, batch_size, etc.)
    without breaking the base contract.
    """

    @abstractmethod
    def transcribe(
        self,
        input_path: str,
        output_path: str,
        callback: Optional[Callable] = None,
        **kwargs,
    ) -> dict:
        """Transcribe audio/video file and save results to output_path.

        Parameters
        ----------
        input_path : str   Path to audio/video file.
        output_path : str  Path to write JSON result.
        callback : callable  (percent: int, message: str) progress callback.
        **kwargs : Extra engine-specific options (model, language, etc.)

        Returns
        -------
        dict  {"segments": [...], "language": "xx"}
        """
        ...

    def post_process(
        self,
        asr_result: dict,
        audio_path: str,
        language: Optional[str] = None,
        vad_engine: Optional[str] = None,
        alignment_engine: Optional[str] = None,
        diarize_engine: Optional[str] = None,
        vad_options: Optional[dict] = None,
        alignment_options: Optional[dict] = None,
        diarize_options: Optional[dict] = None,
        punctuation_engine: Optional[str] = None,
        punctuation_options: Optional[dict] = None,
        callback: Optional[Callable] = None,
        alignment_audio_path: Optional[str] = None,
    ) -> dict:
        """Post-process ASR result with VAD, alignment, speaker diarization,
        and/or punctuation restoration.

        This method allows applying VAD, word-level alignment, and speaker 
        diarization from other engines to any ASR result, enabling hybrid 
        processing pipelines.

        Parameters
        ----------
        asr_result : dict
            Original ASR result from any engine.
        audio_path : str
            Path to the original audio file (needed for VAD/diarization).
        language : str, optional
            Language code (e.g., "zh", "en"). If not provided, will try to extract from asr_result.
        vad_engine : str, optional
            VAD engine name (e.g., "silero", "fsmn", "webrtc").
        alignment_engine : str, optional
            Alignment engine name (e.g., "whisperx", "qwen3", "funasr").
        diarize_engine : str, optional
            Diarization engine name (e.g., "pyannote", "cam++", "diarize").
        punctuation_engine : str, optional
            Punctuation restoration engine name (e.g., "ct_punc").
        vad_options : dict, optional
            VAD-specific options.
        alignment_options : dict, optional
            Alignment-specific options.
        diarize_options : dict, optional
            Diarization-specific options.
        punctuation_options : dict, optional
            Punctuation restoration options.
        callback : callable, optional
            Progress callback (percent: int, message: str).
        alignment_audio_path : str, optional
            Path to audio file specifically for alignment (e.g., vocal-separated audio).
            If provided, this audio will be used for word-level alignment instead of the original audio.

        Returns
        -------
        dict
            Post-processed result with optional VAD, word timestamps, and speaker labels.
        """
        # Get language from ASR result if not provided
        if language is None:
            language = asr_result.get("language", "auto")
        
        result = asr_result.copy()
        
        # Apply VAD first to determine speech boundaries.
        # Each stage runs independently: a failure in one stage is logged and
        # skipped so it never blocks the remaining stages (alignment/diarization).
        if vad_engine:
            if callback:
                callback(30, f"Applying VAD with {vad_engine}...")
            try:
                result = self._apply_vad(result, audio_path, vad_engine, vad_options or {})
            except Exception as e:
                print(f"[PostProcess] VAD failed ({vad_engine}): {e}, continuing without VAD segmentation", flush=True)
        
        # Apply word-level alignment within VAD boundaries
        # Use alignment_audio_path if provided (e.g., vocal-separated audio for better alignment)
        if alignment_engine:
            if callback:
                callback(50, f"Applying word alignment with {alignment_engine}...")
            align_audio = alignment_audio_path or audio_path
            if alignment_audio_path:
                print(f"[PostProcess] Using alignment audio for alignment: {alignment_audio_path}", flush=True)
            try:
                result = self._apply_alignment(result, align_audio, alignment_engine, alignment_options or {}, language)
            except Exception as e:
                print(f"[PostProcess] Alignment failed ({alignment_engine}): {e}, continuing without word timestamps", flush=True)
        
        # Apply speaker diarization last
        if diarize_engine:
            if callback:
                callback(70, f"Applying speaker diarization with {diarize_engine}...")
            try:
                result = self._apply_diarization(result, audio_path, diarize_engine, diarize_options or {})
            except Exception as e:
                print(f"[PostProcess] Diarization failed ({diarize_engine}): {e}, continuing without speaker labels", flush=True)

        # Apply punctuation restoration last (smart fallback for engines without punctuation)
        if punctuation_engine:
            if callback:
                callback(85, f"Applying punctuation restoration with {punctuation_engine}...")
            try:
                result = self._apply_punctuation(result, punctuation_engine, punctuation_options or {}, language)
            except Exception as e:
                print(f"[PostProcess] Punctuation restoration failed ({punctuation_engine}): {e}, continuing without punctuation", flush=True)

        if callback:
            callback(100, "Post-processing complete")
        
        return normalize_speaker_format(result)

    def _apply_alignment(
        self,
        asr_result: dict,
        audio_path: str,
        alignment_engine: str,
        options: dict,
        language: Optional[str] = None,
    ) -> dict:
        """Apply word-level alignment to ASR result."""
        print(f"[ASRBase._apply_alignment] START engine={alignment_engine} audio={audio_path} language={language} options={options}", flush=True)
        from backend.asr.alignment_processor import (
            WhisperXAlignmentProcessor,
            Qwen3AlignmentProcessor,
            FunASRAlignmentProcessor,
            apply_alignment_to_segments
        )
        
        # Use provided language or get from result
        if language is None:
            language = asr_result.get("language", "")
        
        # Select alignment processor
        if alignment_engine == "whisperx":
            processor = WhisperXAlignmentProcessor(**options)
        elif alignment_engine == "qwen3":
            processor = Qwen3AlignmentProcessor(**options)
        elif alignment_engine == "funasr":
            processor = FunASRAlignmentProcessor(**options)
        else:
            raise ValueError(f"Unknown alignment engine: {alignment_engine}")
        
        # Run alignment
        segments = asr_result.get("segments", [])
        print(f"[ASRBase._apply_alignment] segments={len(segments)}, calling processor.align...", flush=True)
        alignment_result = processor.align(audio_path, segments, language)
        print(f"[ASRBase._apply_alignment] processor.align returned, words={len(alignment_result.words) if alignment_result.words else 0}", flush=True)
        
        # Apply alignment results to segments
        if alignment_result.words:
            asr_result["segments"] = apply_alignment_to_segments(segments, alignment_result)
        
        print(f"[ASRBase._apply_alignment] END", flush=True)
        return asr_result

    def _apply_vad(
        self,
        asr_result: dict,
        audio_path: str,
        vad_engine: str,
        options: dict,
    ) -> dict:
        """Apply VAD to ASR result segments.

        If the configured engine fails (e.g. Silero needs to download its model
        from GitHub which may be unreachable), automatically fall back to locally
        available engines: fsmn (FunASR, cached locally) -> webrtc (if installed).
        If every engine fails, the original result is returned unchanged so the
        remaining post-processing stages (alignment/diarization) still run.
        """
        print(f"[ASRBase._apply_vad] START engine={vad_engine} audio={audio_path} options={options}", flush=True)
        from backend.asr.vad_processor import (
            SileroVADProcessor, 
            FSMNVADProcessor, 
            WebRTCVADProcessor
        )
        
        # 依次尝试的VAD引擎：配置的引擎 → fsmn（本地模型）→ webrtc（如果已安装）
        candidates: list = []
        if vad_engine:
            candidates.append(vad_engine)
        for fallback in ("fsmn", "webrtc"):
            if fallback not in candidates:
                candidates.append(fallback)
        
        last_error = None
        for engine in candidates:
            try:
                if engine == "silero":
                    processor = SileroVADProcessor(**options)
                elif engine == "fsmn":
                    processor = FSMNVADProcessor(**options)
                elif engine == "webrtc":
                    processor = WebRTCVADProcessor(**options)
                else:
                    print(f"[VAD] Unknown VAD engine: {engine}, trying next", flush=True)
                    continue
                
                print(f"[VAD] Running VAD with engine: {engine}", flush=True)
                vad_segments = processor.detect(audio_path)
                
                # Merge VAD results with ASR segments
                if vad_segments and "segments" in asr_result:
                    asr_result["segments"] = self._merge_vad_segments(
                        asr_result["segments"], vad_segments
                    )
                print(f"[VAD] VAD completed with engine: {engine}, {len(vad_segments)} segment(s)", flush=True)
                return asr_result
            except Exception as e:
                last_error = e
                print(f"[VAD] VAD engine '{engine}' failed: {e}", flush=True)
        
        if last_error:
            print(f"[VAD] All VAD engines failed (last error: {last_error}); continuing without VAD segmentation", flush=True)
        return asr_result

    def _apply_diarization(
        self,
        asr_result: dict,
        audio_path: str,
        diarize_engine: str,
        options: dict,
    ) -> dict:
        """Apply speaker diarization to ASR result."""
        from backend.asr.speaker_diarization_processor import (
            PyannoteDiarizationProcessor,
            CamPlusDiarizationProcessor,
            DiarizeLibProcessor,
            merge_diarization_with_asr
        )
        
        # Select diarization processor
        if diarize_engine == "pyannote":
            processor = PyannoteDiarizationProcessor(**options)
        elif diarize_engine == "cam++":
            processor = CamPlusDiarizationProcessor(**options)
        elif diarize_engine == "diarize":
            processor = DiarizeLibProcessor(**options)
        else:
            raise ValueError(f"Unknown diarization engine: {diarize_engine}")
        
        # Run diarization
        diarization_result = processor.diarize(audio_path, **options)
        
        # Merge diarization results with ASR result
        return merge_diarization_with_asr(asr_result, diarization_result)

    def _apply_punctuation(
        self,
        asr_result: dict,
        punctuation_engine: str,
        options: dict,
        language: Optional[str] = None,
    ) -> dict:
        """Apply punctuation restoration to ASR result (final-stage fallback)."""
        print(f"[ASRBase._apply_punctuation] START engine={punctuation_engine} language={language}", flush=True)
        from backend.asr.punctuation_processor import (
            CtPuncPunctuationProcessor,
            normalize_lang_code,
        )

        if punctuation_engine == "ct_punc":
            processor = CtPuncPunctuationProcessor(**options)
        else:
            raise ValueError(f"Unknown punctuation engine: {punctuation_engine}")

        lang = language or asr_result.get("language", "")
        segments = asr_result.get("segments", []) or []
        before = [s.get("text") for s in segments]
        print(f"[ASRBase._apply_punctuation] segments={len(segments)}, calling processor.restore...", flush=True)
        processor.restore(segments, lang)
        print(f"[ASRBase._apply_punctuation] processor.restore done", flush=True)

        # 文本有变化时才重建顶层 text（zh 无分隔符、en 空格分隔）
        if any(s.get("text") != b for s, b in zip(segments, before)):
            sep = " " if normalize_lang_code(lang) == "en" else ""
            asr_result["text"] = sep.join((s.get("text") or "") for s in segments)
        print(f"[ASRBase._apply_punctuation] END", flush=True)
        return asr_result

    def _merge_vad_segments(
        self,
        asr_segments: List[dict],
        vad_segments: List[Any],
    ) -> List[dict]:
        """Merge VAD segments with ASR segments.
        
        If ASR returned few segments but VAD detected many, use VAD boundaries
        to split long ASR segments into smaller ones.
        
        Parameters
        ----------
        asr_segments : List[dict]
            Original ASR segments with text
        vad_segments : List[VADSegment]
            VAD-detected speech segments with timestamps
            
        Returns
        -------
        List[dict]
            Merged segments with VAD boundaries and ASR text
        """
        if not vad_segments:
            return asr_segments
        
        # Check if we have word-level timestamps
        has_words = any("words" in seg and seg["words"] for seg in asr_segments)
        
        if has_words:
            print(f"[VAD] Merging {len(asr_segments)} ASR segments with {len(vad_segments)} VAD segments using word timestamps", flush=True)
            all_words = []
            for seg in asr_segments:
                all_words.extend(seg.get("words", []))
            
            # Sort words by start time
            all_words.sort(key=lambda x: x.get("start", 0))
            
            merged = []
            word_idx = 0
            for i, vad_seg in enumerate(vad_segments):
                seg_words = []
                # Find words that fall into this VAD segment
                # We use a small buffer (0.1s) to include words that might start slightly before VAD
                while word_idx < len(all_words):
                    w = all_words[word_idx]
                    w_start = w.get("start", 0)
                    
                    if w_start < vad_seg.start - 0.1:
                        # Word is before this VAD segment, skip it
                        word_idx += 1
                        continue
                    if w_start < vad_seg.end:
                        # Word starts within this VAD segment
                        seg_words.append(w)
                        word_idx += 1
                    else:
                        # Word starts after this VAD segment
                        break
                
                if seg_words:
                    # Detect if it's CJK (no spaces needed)
                    is_cjk = any('\u4e00' <= c <= '\u9fff' for c in seg_words[0].get("word", ""))
                    if is_cjk:
                        seg_text = "".join(w.get("word", "") for w in seg_words)
                    else:
                        seg_text = " ".join(w.get("word", "") for w in seg_words)
                    
                    # 保留原始 ASR 文本中的标点符号：
                    # word-level 对齐（whisperx 等）返回的 word token 可能不包含标点，
                    # 直接用 words 重建 text 会丢失标点。
                    # 策略：找到这段 words 对应的原始 ASR segment，用原始 text 中
                    # 的标点版本替换重建的 text。
                    seg_text = self._restore_punctuation(seg_words, asr_segments, seg_text)
                    
                    # 保留段级说话人：取该段词中出现最多的 speaker
                    _spk_counter: dict = {}
                    for _w in seg_words:
                        _s = _w.get("speaker")
                        if _s:
                            _spk_counter[_s] = _spk_counter.get(_s, 0) + 1
                    merged.append({
                        "id": len(merged) + 1,
                        "start": round(vad_seg.start, 3),
                        "end": round(vad_seg.end, 3),
                        "text": seg_text.strip(),
                        "words": seg_words,
                        **({"speaker": max(_spk_counter, key=_spk_counter.get)} if _spk_counter else {}),
                    })
            
            # If we managed to produce merged segments, return them
            if merged:
                print(f"[VAD] Word-aware merge produced {len(merged)} segments", flush=True)
                return merged
            # Fallback if no words matched VAD segments (unlikely)
            print("[VAD] Word-aware merge failed to find matches, falling back to duration-based split", flush=True)

        # If ASR already has many segments, just filter by VAD overlap
        if len(asr_segments) > len(vad_segments) * 0.5:
            merged = []
            for asr_seg in asr_segments:
                seg_start = asr_seg.get("start", 0.0)
                seg_end = asr_seg.get("end", 0.0)
                
                # Check if this segment overlaps with any VAD segment
                for vad_seg in vad_segments:
                    if (seg_start < vad_seg.end and seg_end > vad_seg.start):
                        merged.append(asr_seg)
                        break
            
            return merged if merged else asr_segments
        
        # ASR returned few segments (e.g., 1 big segment), use VAD to split
        print(f"[VAD] Splitting {len(asr_segments)} ASR segments using {len(vad_segments)} VAD segments", flush=True)
        
        # Concatenate all ASR text（英文按空格拼接，避免单词在切分边界粘连）
        texts = [seg.get("text", "") for seg in asr_segments]
        combined = "".join(texts)
        if not combined.strip():
            return asr_segments
        is_cjk = any('\u4e00' <= c <= '\u9fff' for c in combined[:200])
        separator = "" if is_cjk else " "
        full_text = separator.join(t for t in texts if t)
        
        # Calculate total ASR duration for text distribution
        total_asr_duration = sum(
            seg.get("end", 0) - seg.get("start", 0) 
            for seg in asr_segments
        )
        
        # If ASR has no duration info, use VAD total duration
        if total_asr_duration <= 0:
            total_asr_duration = max(v.end for v in vad_segments) if vad_segments else 0
        
        # Distribute text to VAD segments based on duration proportion
        merged = []
        text_pos = 0
        total_vad_duration = sum(v.end - v.start for v in vad_segments)
        
        for i, vad_seg in enumerate(vad_segments):
            seg_duration = vad_seg.end - vad_seg.start
            
            # Calculate text proportion for this segment
            if total_vad_duration > 0:
                text_proportion = seg_duration / total_vad_duration
            else:
                text_proportion = 1.0 / len(vad_segments)
            
            # Calculate text length for this segment
            text_len = int(len(full_text) * text_proportion)
            
            # Ensure we don't exceed text length
            text_len = max(1, min(text_len, len(full_text) - text_pos))
            
            # For the last segment, use all remaining text
            if i == len(vad_segments) - 1:
                seg_text = full_text[text_pos:]
            else:
                seg_text = full_text[text_pos:text_pos + text_len]
                # Try to find a natural break point (whitespace or punctuation)
                # Avoid splitting in the middle of an English word
                if text_pos + text_len < len(full_text):
                    next_char = full_text[text_pos + text_len]
                    # If we are in the middle of a word (current char and next char are both alphanumeric)
                    if seg_text[-1].isalnum() and next_char.isalnum():
                        # Find the last space or punctuation in seg_text to break there instead
                        import re
                        match = re.search(r'[\s,.!?;:，。！？、；：][^\s,.!?;:，。！？、；：]*$', seg_text)
                        if match and match.start() > len(seg_text) // 2:
                            seg_text = seg_text[:match.start() + 1]
                            text_len = len(seg_text)
                        else:
                            # If no good break point found, try to extend to the next space
                            remaining = full_text[text_pos + text_len:]
                            space_match = re.search(r'[\s,.!?;:，。！？、；：]', remaining)
                            if space_match:
                                extra_len = space_match.start() + 1
                                seg_text = full_text[text_pos:text_pos + text_len + extra_len]
                                text_len = len(seg_text)
            
            text_pos += text_len
            
            if seg_text.strip():
                merged.append({
                    "id": len(merged) + 1,
                    "start": round(vad_seg.start, 3),
                    "end": round(vad_seg.end, 3),
                    "text": seg_text.strip(),
                })
        
        print(f"[VAD] Split into {len(merged)} segments", flush=True)
        return merged

    @staticmethod
    def _restore_punctuation(
        seg_words: List[dict],
        asr_segments: List[dict],
        rebuilt_text: str,
    ) -> str:
        """VAD 合并用 words 重建 text 后，尝试从原始 ASR segment 中恢复标点。

        word-level 对齐（whisperx wav2vec2 等）返回的 word token 通常不包含标点，
        直接用 words 重建 text 会丢失 ASR 引擎返回的标点符号。
        本方法在原始 ASR segment text 中定位这段 words 对应的文本区间，
        用原始文本（含标点）替换重建的文本。

        定位策略：去掉标点后，用 rebuilt_text 在原始 ASR segments 的拼接文本中
        做子串匹配，命中则取原始文本的对应区间（含标点）。
        """
        import re as _re
        if not rebuilt_text.strip():
            return rebuilt_text

        def _strip_punct(s: str) -> str:
            return _re.sub(r'[，。！？、；：,.!?;:\s]', '', s or '')

        rebuilt_clean = _strip_punct(rebuilt_text)
        if not rebuilt_clean:
            return rebuilt_text

        # 在原始 ASR segments 中查找包含这些 words 的 segment
        # 优先用 word 时间戳匹配：seg_words 的第一个 word 的 start 时间落在
        # 哪个原始 segment 的时间范围内
        word_start = 0.0
        for w in seg_words:
            try:
                word_start = float(w.get("start") or 0)
                break
            except (TypeError, ValueError):
                continue

        for orig_seg in asr_segments:
            orig_text = orig_seg.get("text", "")
            if not orig_text:
                continue
            orig_clean = _strip_punct(orig_text)
            # 用去掉标点后的文本做子串匹配
            if rebuilt_clean in orig_clean:
                # 找到了！从原始文本中提取含标点的对应区间
                # 逐字符扫描原始文本，跳过标点，匹配 rebuilt_clean 的字符
                result_chars: list[str] = []
                match_idx = 0
                for ch in orig_text:
                    if _strip_punct(ch):  # 非标点字符
                        if match_idx < len(rebuilt_clean):
                            if ch == rebuilt_clean[match_idx] or _strip_punct(ch) == rebuilt_clean[match_idx:match_idx+1]:
                                result_chars.append(ch)
                                match_idx += 1
                            else:
                                # 字符不匹配，重置
                                result_chars = []
                                match_idx = 0
                        else:
                            # 已经匹配完，追加剩余标点（如果紧跟在匹配区间后）
                            if ch in "，。！？、；：,.!?;:":
                                result_chars.append(ch)
                            else:
                                break
                    else:
                        # 标点字符
                        if match_idx < len(rebuilt_clean):
                            # 匹配进行中，标点可能是重建 text 中缺失的
                            result_chars.append(ch)
                        else:
                            # 匹配完成后，追加紧邻的标点
                            result_chars.append(ch)

                restored = "".join(result_chars).strip()
                # 校验：去掉标点后应该和 rebuilt_clean 一致
                if _strip_punct(restored) == rebuilt_clean:
                    return restored
        return rebuilt_text

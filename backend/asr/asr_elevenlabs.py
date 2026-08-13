"""ElevenLabs Scribe ASR engine — cloud REST API wrapper.

ElevenLabs Speech-to-Text API (Scribe v1 / v2):
  POST https://api.elevenlabs.io/v1/speech-to-text
  - model_id: "scribe_v1" | "scribe_v2"
  - file: audio file (multipart/form-data)
  - language_code: ISO-639-3 (e.g. "zho", "eng", "jpn")
  - timestamps_granularity: "word" | "character" | "none"
  - diarize: true/false (speaker detection)
  - tag_audio_events: true/false
  - num_speakers: int or null

Response:
  {
    "language_code": "eng",
    "language_probability": 0.98,
    "text": "Hello world ...",
    "words": [
      {"text": "Hello", "start": 0.0, "end": 0.5, "type": "word",
       "speaker_id": "speaker_0", "logprob": -0.1},
      ...
    ]
  }
"""

import os
import json
import time
import requests
from typing import Callable, Optional, Dict, List, Any

from backend.asr.asr_base import ASRBase

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "scribe_v2"
DEFAULT_API_BASE = "https://api.elevenlabs.io/v1/speech-to-text"

# ISO-639-1 -> ISO-639-3 mapping for ElevenLabs
_LANG_TO_ISO3 = {
    "auto": None,
    "zh": "zho",
    "yue": "yue",
    "zh-yue-hk": "yue",
    "zh-yue-gd": "yue",
    "zh-wuu": "wuu",
    "zh-min": "nan",
    "zh-anhui": "zho",
    "zh-dongbei": "zho",
    "zh-fujian": "zho",
    "zh-gansu": "zho",
    "zh-guizhou": "zho",
    "zh-hebei": "zho",
    "zh-henan": "zho",
    "zh-hubei": "zho",
    "zh-hunan": "zho",
    "zh-jiangxi": "zho",
    "zh-ningxia": "zho",
    "zh-shandoi": "zho",
    "zh-shaanxi": "zho",
    "zh-shanxi": "zho",
    "zh-sichuan": "zho",
    "zh-tianjin": "zho",
    "zh-yunnan": "zho",
    "zh-zhejiang": "zho",
    "en": "eng",
    "ja": "jpn",
    "ko": "kor",
    "fr": "fra",
    "de": "deu",
    "es": "spa",
    "pt": "por",
    "ru": "rus",
    "ar": "ara",
    "it": "ita",
    "nl": "nld",
    "pl": "pol",
    "tr": "tur",
    "vi": "vie",
    "th": "tha",
    "id": "ind",
    "hi": "hin",
    "ms": "zsm",
    "sv": "swe",
    "da": "dan",
    "fi": "fin",
    "no": "nor",
    "nb": "nor",
    "cs": "ces",
    "el": "ell",
    "he": "heb",
    "hu": "hun",
    "ro": "ron",
    "uk": "ukr",
    "bn": "ben",
    "fa": "fas",
    "tl": "fil",
    "mk": "mkd",
    "ca": "cat",
    "sk": "slk",
    "hr": "hrv",
    "bg": "bul",
    "lt": "lit",
    "lv": "lav",
    "et": "est",
    "sl": "slv",
    "sr": "srp",
}

# ISO-639-3 -> ISO-639-1 reverse mapping
_ISO3_TO_LANG = {}
for _k, _v in _LANG_TO_ISO3.items():
    if _v and _v not in _ISO3_TO_LANG:
        _ISO3_TO_LANG[_v] = _k


class ElevenLabsASRLocal(ASRBase):
    """ElevenLabs Scribe cloud ASR engine.

    Requires API key (env ELEVENLABS_API_KEY or passed via config).
    """

    def transcribe(
        self,
        input_path: str,
        output_path: str,
        callback: Optional[Callable] = None,
        *,
        model: str = DEFAULT_MODEL,
        language: Optional[str] = None,
        api_key: Optional[str] = None,
        word_timestamps: bool = True,
        diarize: bool = False,
        tag_audio_events: bool = False,
        num_speakers: Optional[int] = None,
        **kwargs,
    ) -> dict:
        """Transcribe audio/video via ElevenLabs REST API.

        Parameters
        ----------
        input_path : str   Path to audio/video file.
        output_path : str  Path to write JSON result.
        callback : callable  (percent, message) progress callback.
        model : str  "scribe_v1" or "scribe_v2".
        language : str | None  ISO-639-1 code or None for auto-detect.
        api_key : str | None  ElevenLabs API key (fallback: env ELEVENLABS_API_KEY).
        word_timestamps : bool  Include word-level timestamps.
        diarize : bool  Enable speaker diarization.
        tag_audio_events : bool  Tag non-speech audio events.
        num_speakers : int | None  Expected number of speakers.
        """
        if callback:
            callback(10, "Preparing ElevenLabs STT...")

        # Resolve API key
        key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        if not key:
            raise ValueError(
                "ElevenLabs API key required. Set ELEVENLABS_API_KEY env var "
                "or pass api_key in config."
            )

        # Map language
        lang_iso3 = self._map_language(language)

        # Build multipart form data
        if callback:
            callback(20, f"Uploading audio to ElevenLabs ({model})...")

        form_data: Dict[str, Any] = {
            "model_id": model,
            "timestamps_granularity": "word" if word_timestamps else "none",
            "diarize": str(diarize).lower(),
            "tag_audio_events": str(tag_audio_events).lower(),
        }
        if lang_iso3:
            form_data["language_code"] = lang_iso3
        if num_speakers is not None:
            form_data["num_speakers"] = str(num_speakers)

        headers = {"xi-api-key": key}

        # Determine MIME type
        mime = self._guess_mime(input_path)

        if callback:
            callback(30, "Calling ElevenLabs API...")

        start_time = time.time()
        try:
            with open(input_path, "rb") as f:
                files = {"file": (os.path.basename(input_path), f, mime)}
                resp = requests.post(
                    DEFAULT_API_BASE,
                    headers=headers,
                    data=form_data,
                    files=files,
                    timeout=600,
                )
        except requests.RequestException as e:
            raise RuntimeError(f"ElevenLabs API request failed: {e}")

        elapsed = time.time() - start_time
        if callback:
            callback(70, f"API responded in {elapsed:.1f}s (HTTP {resp.status_code})")

        if resp.status_code != 200:
            raise RuntimeError(
                f"ElevenLabs API error {resp.status_code}: {resp.text[:500]}"
            )

        result = resp.json()
        if callback:
            callback(80, "Processing results...")

        output = self._build_output(result)

        # Save
        if callback:
            callback(90, "Saving results...")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        seg_count = len(output.get("segments", []))
        if callback:
            callback(100, f"ASR done - {seg_count} segments ({elapsed:.1f}s)")
        return output

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _map_language(language: Optional[str]) -> Optional[str]:
        """Map ISO-639-1 code to ISO-639-3 for ElevenLabs API."""
        if not language or language == "auto":
            return None
        lang = language.strip().lower()
        return _LANG_TO_ISO3.get(lang, None)

    @staticmethod
    def _guess_mime(path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        mime_map = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".ogg": "audio/ogg",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".wma": "audio/x-ms-wma",
            ".mp4": "video/mp4",
            ".mkv": "video/x-matroska",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".webm": "audio/webm",
        }
        return mime_map.get(ext, "application/octet-stream")

    @staticmethod
    def _build_output(api_result: dict) -> dict:
        """Convert ElevenLabs API response to standardized output format.

        Output format:
        {
            "language": "eng",
            "text": "full text",
            "segments": [
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 2.5,
                    "text": "Hello world",
                    "speaker_id": "speaker_0",
                    "words": [
                        {"word": "Hello", "start": 0.0, "end": 0.5, "score": -0.1, "speaker_id": "speaker_0"},
                        ...
                    ]
                }
            ]
        }
        """
        detected_lang = api_result.get("language_code", "")
        full_text = api_result.get("text", "")
        words_raw = api_result.get("words", [])

        # Build word list (skip spacing/audio_event entries)
        words: List[dict] = []
        for w in words_raw:
            wtype = w.get("type", "word")
            if wtype != "word":
                continue
            word_entry: dict = {
                "word": (w.get("text") or "").strip(),
            }
            if w.get("start") is not None:
                word_entry["start"] = round(float(w["start"]), 3)
            if w.get("end") is not None:
                word_entry["end"] = round(float(w["end"]), 3)
            if w.get("logprob") is not None:
                word_entry["score"] = round(float(w["logprob"]), 4)
            if w.get("speaker_id"):
                word_entry["speaker_id"] = w["speaker_id"]
            words.append(word_entry)

        # Group words into segments by speaker change or sentence boundary
        segments: List[dict] = []
        if words:
            seg_words: List[dict] = [words[0]]
            for w in words[1:]:
                prev = seg_words[-1]
                new_seg = False
                # Speaker change
                if w.get("speaker_id") and prev.get("speaker_id") and w["speaker_id"] != prev["speaker_id"]:
                    new_seg = True
                # Long pause (>1.5s gap)
                gap = w.get("start", 0) - prev.get("end", 0)
                if gap > 1.5:
                    new_seg = True
                # Sentence-ending punctuation
                if prev.get("word", "") and prev["word"][-1] in ".!?\u3002\uff01\uff1f":
                    new_seg = True

                if new_seg:
                    segments.append(seg_words)
                    seg_words = [w]
                else:
                    seg_words.append(w)
            if seg_words:
                segments.append(seg_words)

        # Build final segments
        output_segments: List[dict] = []
        for idx, seg_words in enumerate(segments, 1):
            seg_start = seg_words[0].get("start", 0)
            seg_end = seg_words[-1].get("end", 0)
            seg_text = "".join(w.get("word", "") for w in seg_words).strip()
            seg_speaker = seg_words[0].get("speaker_id", "")
            entry: dict = {
                "id": idx,
                "start": round(float(seg_start), 3),
                "end": round(float(seg_end), 3),
                "text": seg_text,
                "words": seg_words,
            }
            if seg_speaker:
                entry["speaker_id"] = seg_speaker
            output_segments.append(entry)

        # Map ISO-639-3 back to ISO-639-1
        lang_iso1 = _ISO3_TO_LANG.get(detected_lang, detected_lang)

        return {
            "language": lang_iso1,
            "text": full_text,
            "segments": output_segments,
        }
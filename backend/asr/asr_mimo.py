"""Xiaomi MiMo ASR engine — OpenAI-compatible cloud API wrapper.

MiMo-V2.5-ASR uses the OpenAI chat completions endpoint with audio input:
  POST https://api.xiaomimimo.com/v1/chat/completions
  - model: "mimo-v2.5-asr"
  - messages: [{"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64,..."}}]}]
  - asr_options: {"language": "zh" | "en" | "auto"}

Response is standard OpenAI chat completion format:
  choices[0].message.content = transcribed text

Supported languages: zh, en, auto (auto-detect).
Supported audio: wav, mp3 (base64-encoded, max 10MB after encoding).

NOTE: MiMo ASR has a 10MB base64 size limit. This module automatically splits
large audio files at silence boundaries and merges the transcription results.
"""

import os
import json
import base64
import time
import shutil
import tempfile
import mimetypes
import subprocess
from typing import Callable, Optional, Dict, Any, List

import requests

from backend.asr.asr_base import ASRBase

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "mimo-v2.5-asr"
DEFAULT_BASE_URL = "https://api.xiaomimimo.com/v1/chat/completions"

# ISO-639-1 -> MiMo language code
_MIMO_LANG_MAP = {
    "auto": "auto",
    "zh": "zh",
    "en": "en",
}


class MiMoASRLocal(ASRBase):
    """Xiaomi MiMo-V2.5-ASR cloud engine.

    Uses OpenAI-compatible chat completions API with audio input.
    Requires API key (env MIMO_API_KEY or passed via config).
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
        base_url: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Transcribe audio/video via MiMo ASR API.

        Parameters
        ----------
        input_path : str   Path to audio/video file (wav or mp3).
        output_path : str  Path to write JSON result.
        callback : callable  (percent, message) progress callback.
        model : str  Model ID, default "mimo-v2.5-asr".
        language : str | None  "zh", "en", or "auto" (default auto).
        api_key : str | None  MiMo API key (fallback: env MIMO_API_KEY).
        base_url : str | None  API base URL override.
        """
        if callback:
            callback(5, "Preparing MiMo ASR...")

        # Resolve API key
        key = api_key or os.environ.get("MIMO_API_KEY", "")
        if not key:
            raise ValueError(
                "MiMo API key required. Set MIMO_API_KEY env var "
                "or pass api_key in config."
            )

        # Map language
        mimo_lang = self._map_language(language)
        url = base_url or DEFAULT_BASE_URL

        # Check if audio needs splitting
        if callback:
            callback(10, "Checking audio size...")

        audio_b64, mime_type = self._check_audio_size(input_path)

        if audio_b64 is not None:
            # Audio is small enough, transcribe directly
            if callback:
                callback(20, "Transcribing audio...")
            output = self._transcribe_single(
                audio_b64, mime_type, url, key, model, mimo_lang, callback
            )
        else:
            # Audio too large, split and transcribe in segments
            if callback:
                callback(15, "Audio too large, splitting into segments...")
            output = self._transcribe_with_split(
                input_path, url, key, model, mimo_lang, callback
            )

        # Save
        if callback:
            callback(90, "Saving results...")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        seg_count = len(output.get("segments", []))
        if callback:
            callback(100, f"ASR done - {seg_count} segments")
        return output

    def _check_audio_size(self, input_path: str) -> tuple:
        """Check if audio file is within MiMo's 10MB base64 limit.
        
        Returns
        -------
        tuple or None
            (base64_str, mime_type) if within limit, None if too large.
        """
        ext = os.path.splitext(input_path)[1].lower()
        mime_map = {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".mp4": "audio/mpeg",
            ".m4a": "audio/mpeg",
        }
        mime_type = mime_map.get(ext, "audio/wav")

        with open(input_path, "rb") as f:
            audio_bytes = f.read()

        b64 = base64.b64encode(audio_bytes).decode("utf-8")
        if len(b64) > 10 * 1024 * 1024:
            return None, mime_type

        return b64, mime_type

    def _transcribe_single(
        self,
        audio_b64: str,
        mime_type: str,
        url: str,
        api_key: str,
        model: str,
        language: str,
        callback: Optional[Callable] = None,
        time_offset: float = 0.0,
    ) -> dict:
        """Transcribe a single audio segment via MiMo API."""
        headers = {
            "api-key": api_key,
            "Content-Type": "application/json",
        }

        body: Dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:{mime_type};base64,{audio_b64}",
                            },
                        }
                    ],
                }
            ],
            "asr_options": {
                "language": language,
            },
        }

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=600)
        except requests.RequestException as e:
            raise RuntimeError(f"MiMo ASR API request failed: {e}")

        if resp.status_code != 200:
            raise RuntimeError(
                f"MiMo ASR API error {resp.status_code}: {resp.text[:500]}"
            )

        result = resp.json()
        output = self._build_output(result, language)

        # Apply time offset to segments
        if time_offset > 0:
            for seg in output.get("segments", []):
                seg["start"] = round(seg.get("start", 0) + time_offset, 3)
                seg["end"] = round(seg.get("end", 0) + time_offset, 3)

        return output

    def _transcribe_with_split(
        self,
        input_path: str,
        url: str,
        api_key: str,
        model: str,
        language: str,
        callback: Optional[Callable] = None,
    ) -> dict:
        """Split large audio into segments and transcribe each."""
        # Calculate target segment duration based on 10MB limit
        # WAV: ~16kHz * 2 bytes = 32KB/s, base64 ~1.33x = 42.67KB/s
        # 10MB / 42.67KB/s ≈ 240 seconds, use 200s for safety
        target_duration = 200

        # Get audio duration
        duration = self._get_audio_duration(input_path)
        if duration <= 0:
            raise RuntimeError(f"Cannot determine audio duration: {input_path}")

        if callback:
            callback(18, f"Audio duration: {duration:.1f}s, splitting...")

        # Find silence points for splitting
        silence_points = self._find_silence_points(input_path, target_duration)

        # Create segments
        segments = self._create_segments(duration, silence_points, target_duration)

        if callback:
            callback(22, f"Split into {len(segments)} segments")

        # Transcribe each segment
        tmp_dir = tempfile.mkdtemp(prefix="mimo_asr_")
        all_results = []

        try:
            for i, (seg_start, seg_end) in enumerate(segments):
                if callback:
                    pct = 25 + int(60 * i / len(segments))
                    callback(pct, f"Transcribing segment {i+1}/{len(segments)}...")

                # Extract segment audio
                seg_path = os.path.join(tmp_dir, f"seg_{i:04d}.wav")
                self._extract_segment(input_path, seg_path, seg_start, seg_end)

                # Encode and transcribe
                with open(seg_path, "rb") as f:
                    seg_bytes = f.read()
                seg_b64 = base64.b64encode(seg_bytes).decode("utf-8")

                result = self._transcribe_single(
                    seg_b64, "audio/wav", url, api_key, model, language,
                    time_offset=seg_start,
                )
                all_results.append(result)

                # Clean up segment file
                try:
                    os.remove(seg_path)
                except Exception:
                    pass
        finally:
            # Clean up temp directory
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

        # Merge results
        if callback:
            callback(85, "Merging transcription results...")

        return self._merge_results(all_results, language)

    @staticmethod
    def _get_audio_duration(audio_path: str) -> float:
        """Get audio duration in seconds using ffprobe."""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "csv=p=0",
                    audio_path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _find_silence_points(audio_path: str, target_duration: float) -> List[float]:
        """Find silence points in audio for splitting."""
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-i", audio_path,
                    "-af", f"silencedetect=noise=-30dB:d=0.5",
                    "-f", "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            
            silence_points = []
            for line in result.stderr.split("\n"):
                if "silence_end" in line:
                    try:
                        # Parse: [Parsed_silencedetect_0 ...] silence_end: 123.456 | ...
                        parts = line.split("silence_end:")
                        if len(parts) > 1:
                            end_time = float(parts[1].split("|")[0].strip())
                            silence_points.append(end_time)
                    except (ValueError, IndexError):
                        continue
            
            return sorted(silence_points)
        except Exception:
            return []

    @staticmethod
    def _create_segments(
        duration: float, 
        silence_points: List[float], 
        target_duration: float
    ) -> List[tuple]:
        """Create segment boundaries based on silence points."""
        segments = []
        seg_start = 0.0

        while seg_start < duration:
            # Target end time
            target_end = seg_start + target_duration

            if target_end >= duration:
                # Last segment
                segments.append((seg_start, duration))
                break

            # Find best silence point near target end
            best_point = None
            for sp in silence_points:
                if sp > seg_start and sp < target_end + 30:
                    best_point = sp

            if best_point and best_point > seg_start + 30:
                # Use silence point
                segments.append((seg_start, best_point))
                seg_start = best_point
            else:
                # No good silence point, split at target
                segments.append((seg_start, target_end))
                seg_start = target_end

        return segments

    @staticmethod
    def _extract_segment(input_path: str, output_path: str, start: float, end: float):
        """Extract a segment from audio file using ffmpeg."""
        duration = end - start
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i", input_path,
                "-ss", str(start),
                "-t", str(duration),
                "-ar", "16000",
                "-ac", "1",
                "-c:a", "pcm_s16le",
                output_path,
            ],
            capture_output=True,
            timeout=120,
        )

    @staticmethod
    def _merge_results(results: List[dict], language: str) -> dict:
        """Merge multiple transcription results into one."""
        all_text = []
        all_segments = []
        seg_id = 1

        for result in results:
            text = result.get("text", "")
            if text:
                all_text.append(text)

            for seg in result.get("segments", []):
                seg["id"] = seg_id
                all_segments.append(seg)
                seg_id += 1

        return {
            "language": language,
            "text": " ".join(all_text),
            "segments": all_segments,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _map_language(language: Optional[str]) -> str:
        """Map ISO-639-1 code to MiMo language code."""
        if not language or language == "auto":
            return "auto"
        lang = language.strip().lower()
        return _MIMO_LANG_MAP.get(lang, "auto")

    @staticmethod
    def _build_output(api_result: dict, language: str) -> dict:
        """Convert MiMo chat completion response to standardized output format.

        MiMo returns standard OpenAI format:
        {
            "choices": [{"message": {"content": "transcribed text ..."}}],
            "usage": {...}
        }

        Output format:
        {
            "language": "zh",
            "text": "full transcribed text",
            "segments": [
                {"id": 1, "start": 0.0, "end": 0.0, "text": "full text"}
            ]
        }

        Note: MiMo ASR does not provide word-level timestamps or segments.
        The entire transcription is returned as a single segment.
        """
        full_text = ""
        try:
            choices = api_result.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                full_text = (msg.get("content") or "").strip()
        except (KeyError, IndexError, TypeError):
            full_text = ""

        segments = []
        if full_text:
            segments.append({
                "id": 1,
                "start": 0.0,
                "end": 0.0,
                "text": full_text,
            })

        return {
            "language": language,
            "text": full_text,
            "segments": segments,
        }
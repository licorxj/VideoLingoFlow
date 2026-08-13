#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiMo TTS API Module (Online Version).

Provides API interfaces for MiMo TTS with voice cloning and voice design capabilities.
Uses OpenAI SDK for TTS synthesis.
Supports multi-threading for concurrent requests.

Supported Models:
- mimo-v2.5-tts: 使用预置精品音色进行语音合成
- mimo-v2.5-tts-voicedesign: 通过文本描述定制音色
- mimo-v2.5-tts-voiceclone: 基于音频样本复刻任意音色
"""

import base64
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# Load configuration from config.json
def _load_config():
    """Load configuration from config.json file."""
    config_path = Path(__file__).parent / "config.json"
    try:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load config.json: {e}")
    return {}

CONFIG = _load_config()

# API Configuration
DEFAULT_API_BASE = "https://api.xiaomimimo.com/v1"

# Supported models
MODEL_TTS = "mimo-v2.5-tts"                    # 预置音色
MODEL_VOICE_DESIGN = "mimo-v2.5-tts-voicedesign"  # 音色设计
MODEL_VOICE_CLONE = "mimo-v2.5-tts-voiceclone"    # 音色克隆

# Preset voices for mimo-v2.5-tts model
PRESET_VOICES = {
    "mimo_default": "mimo_default",  # 默认音色
    "冰糖": "冰糖",
    "茉莉": "茉莉",
    "苏打": "苏打",
    "白桦": "白桦",
    "Mia": "Mia",
    "Chloe": "Chloe",
    "Milo": "Milo",
    "Dean": "Dean",
}

# Supported audio formats
SUPPORTED_FORMATS = ["wav", "pcm16", "mp3"]


@dataclass
class MiMoTTSConfig:
    """Configuration for MiMo TTS API.
    
    Attributes:
        api_key: API key for authentication.
        api_base: Base URL for the API endpoint.
        timeout: Request timeout in seconds.
        max_workers: Maximum number of concurrent workers.
    """
    api_key: str = ""
    api_base: str = DEFAULT_API_BASE
    timeout: int = 120
    max_workers: int = 5


@dataclass
class TTSResult:
    """Result of TTS synthesis.
    
    Attributes:
        success: Whether the synthesis was successful.
        audio_data: Audio data as bytes (if successful).
        audio_base64: Audio data as base64 string.
        format: Audio format.
        error_message: Error message (if failed).
        metadata: Additional metadata from API response.
    """
    success: bool = False
    audio_data: Optional[bytes] = None
    audio_base64: str = ""
    format: str = "wav"
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class MiMoTTS:
    """MiMo TTS API class (Online Version).
    
    Provides voice synthesis capabilities via MiMo TTS online API.
    Supports three modes:
    1. Preset Voice (mimo-v2.5-tts): 使用预置音色
    2. Voice Design (mimo-v2.5-tts-voicedesign): 通过文本描述设计音色
    3. Voice Clone (mimo-v2.5-tts-voiceclone): 基于音频样本复刻音色
    
    Example with preset voice:
        >>> tts = MiMoTTS(api_key="your_api_key")
        >>> result = tts.synthesize_with_preset(
        ...     text="你好，这是一段测试。",
        ...     voice="冰糖"
        ... )
        >>> if result.success:
        ...     with open("output.wav", "wb") as f:
        ...         f.write(result.audio_data)
    
    Example with voice design:
        >>> tts = MiMoTTS(api_key="your_api_key")
        >>> result = tts.synthesize_with_design(
        ...     text="你好，这是一段测试。",
        ...     voice_description="一位温柔的年轻女性，声音甜美"
        ... )
    
    Example with voice clone:
        >>> tts = MiMoTTS(api_key="your_api_key")
        >>> result = tts.synthesize_with_clone(
        ...     text="你好，这是一段测试。",
        ...     reference_audio_path="reference.wav"
        ... )
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: int = 120,
        max_workers: int = 5,
        config: Optional[MiMoTTSConfig] = None,
    ):
        """Initialize MiMo TTS.
        
        Args:
            api_key: API key. If None, reads from MIMO_API_KEY environment variable.
            api_base: API base URL. If None, uses default.
            timeout: Request timeout in seconds.
            max_workers: Maximum number of concurrent workers.
            config: MiMoTTSConfig object (overrides other parameters).
        """
        # Use config if provided
        if config is not None:
            self.api_key = config.api_key or os.environ.get("MIMO_API_KEY", "")
            self.api_base = config.api_base
            self.timeout = config.timeout
        else:
            # Priority: parameter > config.json > environment variable
            self.api_key = api_key or CONFIG.get("api_key") or os.environ.get("MIMO_API_KEY", "")
            self.api_base = api_base or CONFIG.get("api_base", DEFAULT_API_BASE)
            self.timeout = timeout or CONFIG.get("timeout", 120)
        
        # Also check config.json for max_workers if not explicitly set
        if max_workers == 5 and "max_workers" in CONFIG:
            self.max_workers = CONFIG["max_workers"]
        else:
            self.max_workers = max_workers
        
        # Thread pool for concurrent requests
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        
        # OpenAI client
        self._client = None
        
        logger.info(f"MiMo TTS initialized with api_base={self.api_base}, max_workers={max_workers}")
    
    def _get_client(self):
        """Get or create OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.api_base,
                    timeout=self.timeout,
                )
            except ImportError:
                raise ImportError("openai library is required. Install with: pip install openai")
        return self._client
    
    def _encode_audio_file(self, audio_path: str) -> str:
        """Encode audio file to base64 with MIME type prefix.
        
        Args:
            audio_path: Path to audio file.
        
        Returns:
            Base64 encoded string with MIME type prefix.
        """
        # Determine MIME type
        ext = Path(audio_path).suffix.lower()
        mime_types = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
        }
        mime_type = mime_types.get(ext, "audio/mpeg")
        
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{audio_base64}"
    
    def _parse_response(self, completion) -> TTSResult:
        """Parse OpenAI completion response to TTSResult.
        
        Args:
            completion: OpenAI completion object.
        
        Returns:
            TTSResult object.
        """
        try:
            message = completion.choices[0].message
            audio = getattr(message, "audio", None)
            
            # Debug: print actual response structure
            logger.debug(f"Completion type: {type(completion)}")
            logger.debug(f"Message type: {type(message)}")
            logger.debug(f"Audio attribute: {audio}")
            logger.debug(f"Audio type: {type(audio)}")
            
            if not audio:
                return TTSResult(
                    success=False,
                    error_message=f"No audio data in response. Message: {message}",
                )
            
            # Handle audio as ChatCompletionAudio object (has .data attribute)
            audio_data_attr = getattr(audio, "data", None)
            if audio_data_attr:
                audio_data = base64.b64decode(audio_data_attr)
                audio_id = getattr(audio, "id", None)
                return TTSResult(
                    success=True,
                    audio_data=audio_data,
                    audio_base64=audio_data_attr,
                    format="wav",
                    metadata={"model": completion.model, "id": audio_id},
                )
            
            # Handle audio as dict (fallback)
            if isinstance(audio, dict) and "data" in audio:
                audio_base64 = audio["data"]
                audio_data = base64.b64decode(audio_base64)
                return TTSResult(
                    success=True,
                    audio_data=audio_data,
                    audio_base64=audio_base64,
                    format="wav",
                    metadata={"model": completion.model, "id": completion.id},
                )
            
            return TTSResult(
                success=False,
                error_message=f"No audio data in response. Audio: {audio}",
            )
            
        except Exception as e:
            return TTSResult(
                success=False,
                error_message=f"Failed to parse response: {e}",
            )
    
    def synthesize_with_preset(
        self,
        text: str,
        voice: str = "冰糖",
        style_description: Optional[str] = None,
        audio_format: str = "wav",
    ) -> TTSResult:
        """Synthesize speech using preset voice.
        
        Uses mimo-v2.5-tts model with preset voices.
        
        Args:
            text: Text to synthesize.
            voice: Preset voice name (冰糖, 茉莉, 苏打, 白桦, Mia, Chloe, Milo, Dean).
            style_description: Optional style description for natural language control.
            audio_format: Output audio format (wav, pcm16).
        
        Returns:
            TTSResult with audio data.
        """
        # Validate voice
        if voice not in PRESET_VOICES:
            logger.warning(f"Unknown voice '{voice}', using default")
            voice = "冰糖"
        
        # Build messages
        messages = []
        
        # Add user message for style control (optional)
        if style_description:
            messages.append({
                "role": "user",
                "content": style_description
            })
        
        # Add assistant message with text to synthesize
        messages.append({
            "role": "assistant",
            "content": text
        })
        
        # Audio config
        audio_config = {
            "format": audio_format,
            "voice": voice,
        }
        
        logger.info(f"Synthesizing with preset voice '{voice}': {text[:50]}...")
        
        try:
            client = self._get_client()
            completion = client.chat.completions.create(
                model=MODEL_TTS,
                messages=messages,
                audio=audio_config,
            )
            return self._parse_response(completion)
        except Exception as e:
            return TTSResult(
                success=False,
                error_message=str(e),
            )
    
    def synthesize_with_preset_async(
        self,
        text: str,
        voice: str = "冰糖",
        **kwargs,
    ):
        """Asynchronous synthesis with preset voice.
        
        Returns:
            Future object for the synthesis result.
        """
        return self._executor.submit(
            self.synthesize_with_preset,
            text,
            voice,
            **kwargs,
        )
    
    def synthesize_with_design(
        self,
        text: str,
        voice_description: str,
        audio_format: str = "wav",
    ) -> TTSResult:
        """Synthesize speech using voice design.
        
        Uses mimo-v2.5-tts-voicedesign model to generate custom voice from text description.
        
        Args:
            text: Text to synthesize.
            voice_description: Description of desired voice (e.g., "一位温柔的年轻女性，声音甜美").
            audio_format: Output audio format (wav, pcm16).
        
        Returns:
            TTSResult with audio data.
        
        Example:
            >>> result = tts.synthesize_with_design(
            ...     text="你好，这是一段测试。",
            ...     voice_description="Young female, warm and confident, speaking slowly"
            ... )
        """
        # Build messages
        messages = [
            {
                "role": "user",
                "content": voice_description
            },
            {
                "role": "assistant",
                "content": text
            }
        ]
        
        # Audio config
        audio_config = {
            "format": audio_format,
        }
        
        logger.info(f"Synthesizing with voice design: {voice_description[:50]}...")
        
        try:
            client = self._get_client()
            completion = client.chat.completions.create(
                model=MODEL_VOICE_DESIGN,
                messages=messages,
                audio=audio_config,
            )
            return self._parse_response(completion)
        except Exception as e:
            return TTSResult(
                success=False,
                error_message=str(e),
            )
    
    def synthesize_with_design_async(
        self,
        text: str,
        voice_description: str,
        **kwargs,
    ):
        """Asynchronous synthesis with voice design.
        
        Returns:
            Future object for the synthesis result.
        """
        return self._executor.submit(
            self.synthesize_with_design,
            text,
            voice_description,
            **kwargs,
        )
    
    def synthesize_with_clone(
        self,
        text: str,
        reference_audio_path: Optional[str] = None,
        reference_audio_base64: Optional[str] = None,
        style_description: Optional[str] = None,
        audio_format: str = "wav",
    ) -> TTSResult:
        """Synthesize speech using voice cloning.
        
        Uses mimo-v2.5-tts-voiceclone model to clone voice from reference audio.
        
        Args:
            text: Text to synthesize.
            reference_audio_path: Path to reference audio file.
            reference_audio_base64: Base64 encoded reference audio (alternative to path).
            style_description: Optional style description for natural language control.
            audio_format: Output audio format (wav, pcm16).
        
        Returns:
            TTSResult with audio data.
        
        Example:
            >>> result = tts.synthesize_with_clone(
            ...     text="你好，这是一段测试。",
            ...     reference_audio_path="reference.wav"
            ... )
        """
        # Validate input
        if not reference_audio_path and not reference_audio_base64:
            return TTSResult(
                success=False,
                error_message="Either reference_audio_path or reference_audio_base64 is required",
            )
        
        # Encode audio if path provided
        if reference_audio_path:
            if not os.path.exists(reference_audio_path):
                return TTSResult(
                    success=False,
                    error_message=f"Reference audio file not found: {reference_audio_path}",
                )
            voice_base64 = self._encode_audio_file(reference_audio_path)
        else:
            # Use provided base64
            if not reference_audio_base64.startswith("data:"):
                # Add prefix if not present
                voice_base64 = f"data:audio/mpeg;base64,{reference_audio_base64}"
            else:
                voice_base64 = reference_audio_base64
        
        # Build messages
        messages = []
        
        # Add user message for style control (optional)
        if style_description:
            messages.append({
                "role": "user",
                "content": style_description
            })
        else:
            # User message is required but can be empty
            messages.append({
                "role": "user",
                "content": ""
            })
        
        # Add assistant message with text to synthesize
        messages.append({
            "role": "assistant",
            "content": text
        })
        
        # Audio config with cloned voice
        audio_config = {
            "format": audio_format,
            "voice": voice_base64,
        }
        
        logger.info(f"Synthesizing with voice clone: {text[:50]}...")
        
        try:
            client = self._get_client()
            completion = client.chat.completions.create(
                model=MODEL_VOICE_CLONE,
                messages=messages,
                audio=audio_config,
            )
            return self._parse_response(completion)
        except Exception as e:
            return TTSResult(
                success=False,
                error_message=str(e),
            )
    
    def synthesize_with_clone_async(
        self,
        text: str,
        reference_audio_path: Optional[str] = None,
        **kwargs,
    ):
        """Asynchronous synthesis with voice cloning.
        
        Returns:
            Future object for the synthesis result.
        """
        return self._executor.submit(
            self.synthesize_with_clone,
            text,
            reference_audio_path,
            **kwargs,
        )
    
    def batch_synthesize(
        self,
        requests: List[Dict[str, Any]],
        max_workers: Optional[int] = None,
    ) -> List[TTSResult]:
        """Batch synthesis with multi-threading.
        
        Args:
            requests: List of request dictionaries. Each dict should have:
                - 'mode': 'preset', 'design', or 'clone'
                - 'text': Text to synthesize
                - Other mode-specific parameters
            max_workers: Override max workers for this batch.
        
        Returns:
            List of TTSResult objects in the same order as requests.
        """
        workers = max_workers or self.max_workers
        results = [None] * len(requests)
        
        def process_request(idx, req):
            mode = req.get("mode", "preset")
            text = req.get("text", "")
            
            if mode == "preset":
                return self.synthesize_with_preset(
                    text=text,
                    voice=req.get("voice", "冰糖"),
                    style_description=req.get("style_description"),
                    audio_format=req.get("audio_format", "wav"),
                )
            elif mode == "design":
                return self.synthesize_with_design(
                    text=text,
                    voice_description=req.get("voice_description", ""),
                    audio_format=req.get("audio_format", "wav"),
                )
            elif mode == "clone":
                return self.synthesize_with_clone(
                    text=text,
                    reference_audio_path=req.get("reference_audio_path"),
                    reference_audio_base64=req.get("reference_audio_base64"),
                    style_description=req.get("style_description"),
                    audio_format=req.get("audio_format", "wav"),
                )
            else:
                return TTSResult(
                    success=False,
                    error_message=f"Unknown mode: {mode}",
                )
        
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {
                executor.submit(process_request, idx, req): idx
                for idx, req in enumerate(requests)
            }
            
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    results[idx] = TTSResult(
                        success=False,
                        error_message=str(e),
                    )
        
        return results
    
    def save_audio(
        self,
        result: TTSResult,
        output_path: str,
    ) -> bool:
        """Save audio to file.
        
        Args:
            result: TTSResult object with audio data.
            output_path: Output file path.
        
        Returns:
            True if successful, False otherwise.
        """
        if not result.success or result.audio_data is None:
            logger.error("Cannot save audio: result is not successful or has no audio data")
            return False
        
        try:
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
            
            with open(output_path, "wb") as f:
                f.write(result.audio_data)
            
            logger.info(f"Audio saved to: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save audio: {e}")
            return False
    
    def get_preset_voices(self) -> Dict[str, str]:
        """Get available preset voices.
        
        Returns:
            Dictionary of voice names to voice IDs.
        """
        return PRESET_VOICES.copy()
    
    def shutdown(self):
        """Shutdown the TTS engine and release resources."""
        logger.info("Shutting down MiMo TTS")
        self._executor.shutdown(wait=True)
        self._client = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.shutdown()


class MiMoTTSAPI:
    """High-level API wrapper for MiMo TTS.
    
    Provides a simplified interface with preset configurations.
    
    Example:
        >>> api = MiMoTTSAPI(api_key="your_key")
        >>> result = api.synthesize("你好，世界！", voice="冰糖")
        >>> api.save_audio(result, "output.wav")
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        max_workers: int = 5,
        **kwargs,
    ):
        """Initialize the API.
        
        Args:
            api_key: API key for authentication.
            max_workers: Maximum concurrent workers.
            **kwargs: Additional arguments for MiMoTTS.
        """
        self.tts = MiMoTTS(api_key=api_key, max_workers=max_workers, **kwargs)
    
    def synthesize(
        self,
        text: str,
        voice: str = "冰糖",
        style: Optional[str] = None,
        **kwargs,
    ) -> TTSResult:
        """Synthesize speech with preset voice.
        
        Args:
            text: Text to synthesize.
            voice: Preset voice name.
            style: Optional style description.
            **kwargs: Additional parameters.
        
        Returns:
            TTSResult with audio data.
        """
        return self.tts.synthesize_with_preset(
            text=text,
            voice=voice,
            style_description=style,
            **kwargs,
        )
    
    def design_voice(
        self,
        text: str,
        description: str,
        **kwargs,
    ) -> TTSResult:
        """Design a voice and synthesize.
        
        Args:
            text: Text to synthesize.
            description: Voice description.
            **kwargs: Additional parameters.
        
        Returns:
            TTSResult with audio data.
        """
        return self.tts.synthesize_with_design(
            text=text,
            voice_description=description,
            **kwargs,
        )
    
    def clone_voice(
        self,
        text: str,
        reference_audio: str,
        **kwargs,
    ) -> TTSResult:
        """Clone voice and synthesize.
        
        Args:
            text: Text to synthesize.
            reference_audio: Path to reference audio.
            **kwargs: Additional parameters.
        
        Returns:
            TTSResult with audio data.
        """
        return self.tts.synthesize_with_clone(
            text=text,
            reference_audio_path=reference_audio,
            **kwargs,
        )
    
    def save_audio(self, result: TTSResult, output_path: str) -> bool:
        """Save audio to file.
        
        Args:
            result: TTSResult object.
            output_path: Output file path.
        
        Returns:
            True if successful.
        """
        return self.tts.save_audio(result, output_path)
    
    def get_voices(self) -> Dict[str, str]:
        """Get available preset voices."""
        return self.tts.get_preset_voices()
    
    def shutdown(self):
        """Shutdown the API."""
        self.tts.shutdown()


# Convenience functions
def quick_synthesize(
    text: str,
    output_path: str,
    voice: str = "冰糖",
    api_key: Optional[str] = None,
    **kwargs,
) -> bool:
    """Quick synthesis with preset voice and save.
    
    Args:
        text: Text to synthesize.
        output_path: Output audio path.
        voice: Preset voice name.
        api_key: API key.
        **kwargs: Additional parameters.
    
    Returns:
        True if successful.
    """
    with MiMoTTS(api_key=api_key) as tts:
        result = tts.synthesize_with_preset(text=text, voice=voice, **kwargs)
        return tts.save_audio(result, output_path)


def quick_design(
    text: str,
    description: str,
    output_path: str,
    api_key: Optional[str] = None,
    **kwargs,
) -> bool:
    """Quick voice design and save.
    
    Args:
        text: Text to synthesize.
        description: Voice description.
        output_path: Output audio path.
        api_key: API key.
        **kwargs: Additional parameters.
    
    Returns:
        True if successful.
    """
    with MiMoTTS(api_key=api_key) as tts:
        result = tts.synthesize_with_design(text=text, voice_description=description, **kwargs)
        return tts.save_audio(result, output_path)


def quick_clone(
    text: str,
    reference_audio: str,
    output_path: str,
    api_key: Optional[str] = None,
    **kwargs,
) -> bool:
    """Quick voice clone and save.
    
    Args:
        text: Text to synthesize.
        reference_audio: Path to reference audio.
        output_path: Output audio path.
        api_key: API key.
        **kwargs: Additional parameters.
    
    Returns:
        True if successful.
    """
    with MiMoTTS(api_key=api_key) as tts:
        result = tts.synthesize_with_clone(text=text, reference_audio_path=reference_audio, **kwargs)
        return tts.save_audio(result, output_path)


if __name__ == "__main__":
    # Example usage
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    print("MiMo TTS API Example")
    print("=" * 60)
    
    # Check for API key (from config.json or environment variable)
    api_key = CONFIG.get("api_key") or os.environ.get("MIMO_API_KEY")
    if not api_key:
        print("Error: API key not found!")
        print("Please configure API key in config.json or set MIMO_API_KEY environment variable")
        print("See README.md for configuration instructions")
        sys.exit(1)
    
    # Initialize (will use config.json automatically)
    tts = MiMoTTS()
    
    # Show available voices
    print("\nAvailable preset voices:")
    for name, voice_id in tts.get_preset_voices().items():
        print(f"  - {name}: {voice_id}")
    
    # Example 1: Preset voice
    print("\n" + "=" * 60)
    print("Example 1: Preset Voice Synthesis")
    print("=" * 60)
    
    result = tts.synthesize_with_preset(
        text="你好，欢迎使用小米MiMo语音合成系统！",
        voice="冰糖",
        style_description="用温柔亲切的语气，语速适中"
    )
    
    if result.success:
        print(f"✓ Preset voice synthesis successful")
        tts.save_audio(result, "output_preset.wav")
    else:
        print(f"✗ Preset voice synthesis failed: {result.error_message}")
    
    # Example 2: Voice design
    print("\n" + "=" * 60)
    print("Example 2: Voice Design Synthesis")
    print("=" * 60)
    
    result = tts.synthesize_with_design(
        text="你好，这是一段测试语音。",
        voice_description="一位温柔的年轻女性，声音甜美，语速稍慢"
    )
    
    if result.success:
        print(f"✓ Voice design synthesis successful")
        tts.save_audio(result, "output_design.wav")
    else:
        print(f"✗ Voice design synthesis failed: {result.error_message}")
    
    # Example 3: Voice clone (if reference audio exists)
    print("\n" + "=" * 60)
    print("Example 3: Voice Clone Synthesis")
    print("=" * 60)
    
    ref_audio = r"X:\PCTMoveData\Music\淼淼.wav"
    if os.path.exists(ref_audio):
        result = tts.synthesize_with_clone(
            text="你好，这是使用克隆声音合成的语音。",
            reference_audio_path=ref_audio
        )
        
        if result.success:
            print(f"✓ Voice clone synthesis successful")
            tts.save_audio(result, "output_clone.wav")
        else:
            print(f"✗ Voice clone synthesis failed: {result.error_message}")
    else:
        print(f"⚠ Reference audio not found: {ref_audio}")
        print("  Skipping voice clone example")
    
    # Shutdown
    tts.shutdown()
    
    print("\n" + "=" * 60)
    print("Examples completed!")
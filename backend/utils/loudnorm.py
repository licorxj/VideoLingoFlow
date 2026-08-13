"""EBU R128 loudness normalization using ffmpeg loudnorm filter.

Two-pass approach:
  Pass 1: Analyze audio to measure current loudness
  Pass 2: Apply normalization with measured values
"""

import json
import subprocess


def _analyze(audio_path: str) -> dict:
    """Run ffmpeg pass 1 to analyze loudness and return measured values."""
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    stderr = result.stderr

    # Find the last complete JSON block in stderr
    # ffmpeg loudnorm may output multiple JSON blocks for multi-channel audio
    last_close = stderr.rfind("}")
    if last_close == -1:
        raise RuntimeError(f"Failed to find JSON output in ffmpeg stderr:\n{stderr}")

    # Now find the matching opening brace
    last_open = stderr.rfind("{", 0, last_close)
    if last_open == -1:
        raise RuntimeError(f"Failed to find JSON output in ffmpeg stderr:\n{stderr}")

    json_str = stderr[last_open:last_close + 1]
    data = json.loads(json_str)

    return {
        "input_i": data["input_i"],
        "input_tp": data["input_tp"],
        "input_lra": data["input_lra"],
        "input_thresh": data["input_thresh"],
        "target_offset": data["target_offset"],
    }


def normalize_loudness(audio_path: str, target_lufs: float = -16.0, output_path: str = None) -> str:
    """Two-pass loudness normalization.

    Args:
        audio_path: Path to input audio file.
        target_lufs: Target integrated loudness in LUFS.
        output_path: Path for normalized output. Overwrites input if None.

    Returns:
        Path to the normalized audio file.
    """
    if output_path is None:
        output_path = audio_path

    # Pass 1: analyze
    measured = _analyze(audio_path)

    # Pass 2: normalize with measured values
    loudnorm_filter = (
        f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"
        f":measured_I={measured['input_i']}"
        f":measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}"
        f":measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}"
        f":linear=true"
    )

    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-af", loudnorm_filter,
        "-c:a", "pcm_s16le", output_path
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    return output_path

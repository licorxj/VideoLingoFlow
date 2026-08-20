from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


@dataclass
class VideoSpeedSegmentManifest:
    index: int
    start: float
    end: float
    speed_ratio: float
    start_frame: int
    end_frame: int
    input_frames: int
    output_frames: int
    actual_duration: float
    output_start: float = 0.0
    output_end: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class VideoSpeedManifest:
    output_path: str
    fps: float
    total_input_frames: int
    total_output_frames: int
    input_duration: float
    output_duration: float
    segments: List[VideoSpeedSegmentManifest]

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["segments"] = [item.to_dict() for item in self.segments]
        return data


def get_segment_manifest(manifest: Optional[Dict], index: int) -> Optional[Dict]:
    if not manifest:
        return None
    for item in manifest.get("segments", []):
        if int(item.get("index", -1)) == int(index):
            return item
    return None

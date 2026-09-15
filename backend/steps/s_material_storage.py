# -*- coding: utf-8 -*-
"""素材入库节点：将接入的视频 / 图片 / 音频素材归档到项目公共素材库并写入数据库。

- 后端自动识别素材类型（文件扩展名，ffprobe mime 兜底）。
- 视频 / 图片：复制到 data/libraries/{videos,images}/ 并登记到 cp_videos / cp_images。
- 音频：复制到 voiceforge 存储并按 vf_assets 登记，返回 vf:assets 引用。
前端在卡片上设置素材属性（名称 / 分组标签 / 自定义标签 / 描述），后端据此入库。
"""

import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v"}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


def _sanitize(name: str) -> str:
    value = (name or "asset").strip()
    value = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", value)
    value = value.strip(" ._")
    if not value:
        value = "asset"
    return value[:120] if len(value) > 120 else value


def _split_tags(raw) -> list:
    """把逗号 / 分号 / 换行分隔的标签字符串拆为去空白列表。"""
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        items = re.split(r"[;,\n]", str(raw))
    return [x.strip() for x in items if x and x.strip()]


class S_MaterialStorage(BaseStep):
    step_id = "material_storage"
    step_name = "素材入库"
    dependencies = []

    # ------------------------------------------------------------------ #
    def check_artifact(self, task_dir: str) -> bool:
        # 落库位置由素材类型决定，无法稳定预判，始终执行（引擎按 DB 记录判定完成）。
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_media_path(raw: object, task_dir: str) -> Optional[Path]:
        candidates: list = []
        if isinstance(raw, str):
            candidates = [raw]
        elif isinstance(raw, dict):
            for key in ("path", "file", "file_path", "url"):
                value = raw.get(key)
                if isinstance(value, str):
                    candidates.append(value)
                    break
        elif isinstance(raw, (list, tuple)):
            for item in raw:
                if isinstance(item, str):
                    candidates.append(item)
                elif isinstance(item, dict):
                    for key in ("path", "file", "file_path", "url"):
                        value = item.get(key)
                        if isinstance(value, str):
                            candidates.append(value)
                            break
        for cand in candidates:
            if not cand:
                continue
            if os.path.isabs(cand) and os.path.isfile(cand):
                return Path(cand)
            rel = os.path.join(task_dir, cand)
            if os.path.isfile(rel):
                return Path(rel)
            if os.path.isfile(cand):
                return Path(cand)
        return None

    @staticmethod
    def _detect_type(path: Path) -> Optional[str]:
        suffix = path.suffix.lower()
        if suffix in _IMAGE_SUFFIXES:
            return "image"
        if suffix in _VIDEO_SUFFIXES:
            return "video"
        if suffix in _AUDIO_SUFFIXES:
            return "audio"
        # 扩展名无法判定时，用 ffprobe 探测 mime 兜底
        import shutil
        import subprocess

        exe = shutil.which("ffprobe")
        if exe and path.is_file():
            try:
                out = subprocess.run(
                    [exe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)],
                    capture_output=True, text=True, timeout=30,
                )
                payload = json.loads(out.stdout or "{}")
                types = {s.get("codec_type") for s in payload.get("streams", [])}
                if "video" in types and "audio" not in types:
                    return "video"
                if "audio" in types:
                    return "audio"
            except Exception:
                pass
        return None

    @staticmethod
    def _probe_audio_duration(path: Path) -> Optional[float]:
        import shutil
        import subprocess

        exe = shutil.which("ffprobe")
        if not exe or not path.is_file():
            return None
        try:
            out = subprocess.run(
                [exe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                capture_output=True, text=True, timeout=30,
            )
            d = json.loads(out.stdout or "{}").get("format", {}).get("duration")
            return float(d) if d else None
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    def run(self, task_dir: str, callback: Optional[Callable] = None, cancel_callback=None) -> dict:
        config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        report = callback or (lambda *a, **k: None)

        media_path = self._resolve_media_path(step_inputs.get("media"), task_dir)
        if media_path is None:
            raise ValueError("未收到素材：请将视频 / 图片 / 音频素材连接到「素材」输入端口")

        report(10, "识别素材类型…")
        media_type = self._detect_type(media_path)
        if media_type is None:
            raise ValueError(f"无法识别素材类型（仅支持视频 / 图片 / 音频）: {media_path.name}")

        name = (config.get("asset_name") or "").strip() or media_path.stem
        safe = _sanitize(name)
        group_tags = _split_tags(config.get("group_tags"))
        custom_tags = _split_tags(config.get("custom_tags"))
        description = (config.get("description") or "").strip()
        ext = media_path.suffix.lower()

        artifact_path: Optional[str] = None
        library_ref: str = ""
        asset_id: str = ""

        if media_type in ("image", "video"):
            from backend.creation import paths
            from backend.creation.libraries import add_image, add_video

            sub = "images" if media_type == "image" else "videos"
            dest_dir = paths.DATA_ROOT / "libraries" / sub
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{uuid.uuid4().hex[:8]}_{safe}{ext}"
            shutil.copy2(media_path, dest)
            rel = paths.normalize_public_path(dest)
            report(50, f"归档素材（{media_type}），写入数据库…")
            if media_type == "image":
                rec = add_image(rel, group_tags=group_tags, custom_tags=custom_tags, description=description)
            else:
                rec = add_video(rel, group_tags=group_tags, custom_tags=custom_tags, description=description)
            asset_id = rec.get("id") or ""
            library_ref = asset_id
            artifact_path = str(dest)
        else:  # audio
            from backend.voiceforge.storage import resolve_storage_key
            from backend.creation import audio_refs

            storage_key = f"libraries/audio/{uuid.uuid4().hex[:8]}_{safe}{ext}"
            target = resolve_storage_key(storage_key)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(media_path, target)
            duration = self._probe_audio_duration(target)
            report(50, "归档音频素材，写入数据库…")
            rec = audio_refs.add_audio_asset(
                name,
                "upload",
                storage_key=storage_key,
                file_name=target.name,
                duration=duration,
                description=description,
                category="",
                tags=custom_tags,
            )
            asset_id = rec.get("id") or ""
            library_ref = rec.get("ref") or asset_id
            artifact_path = str(target)

        report(100, f"素材入库完成：{media_type}（{library_ref}）")
        return {
            "artifacts": [artifact_path] if artifact_path else [],
            "outputs": {
                "material": artifact_path or "",
                "library_ref": library_ref,
                "asset_type": media_type,
                "asset_id": asset_id,
            },
        }

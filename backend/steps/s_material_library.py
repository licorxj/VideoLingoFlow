# -*- coding: utf-8 -*-
"""
素材库节点通用实现（图片 / 视频 / 角色 / 音色）。

与音频素材库节点同一套交互约定：
  - 节点卡片记录素材ID（config.source，可从「本地素材库」弹窗选择回填）；
  - 执行时按 ID 回查素材库，取完整素材记录并落盘到任务工作目录；
  - 输出两个端口：素材路径（按节点类型分别为 image/video/filepath/audio）+ 素材全信息JSON。

各素材库：
  - 图片素材库 → cp_images（backend/creation/libraries）
  - 视频素材库 → cp_videos
  - 角色素材库 → cp_characters（素材路径 = 多视角图文件夹）
  - 音色素材库 → vf_voices（素材路径 = 设计样音 design.wav）

来源兼容：素材ID、vf:voices:<id> 引用格式、本地已存在的文件/文件夹绝对路径。
"""
import os
import re
import shutil
from pathlib import Path

from backend.steps.base_step import BaseStep


def _sanitize(name: str) -> str:
    name = (name or "asset").strip()
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name)
    name = name.strip(" ._")
    if not name:
        name = "asset"
    return name[:120] if len(name) > 120 else name


def _normalize_ref(source: str) -> str:
    """兼容 vf:voices:<id> / vf:assets:<id> 引用格式,提取纯 ID。"""
    value = (source or "").strip()
    match = re.match(r"^vf:[a-z]+:([A-Za-z0-9_-]+)$", value)
    return match.group(1) if match else value


class S_MaterialLibraryBase(BaseStep):
    """素材库节点基类:子类只需提供 library_kind 与检索/路径解析两个钩子。"""

    library_kind = ""
    output_key = "path"          # 素材路径输出口 id(与 builtin_node_types 的 outputs 对应)
    step_id = ""
    step_name = ""
    dependencies = []
    not_found_hint = "请从节点卡片的「本地素材库」选择素材,或确认素材ID有效。"

    def check_artifact(self, task_dir: str) -> bool:
        # 落盘位置由输入决定，无法稳定预判，始终执行。
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    @property
    def name(self) -> str:
        return self.step_name

    # ------------------------------------------------------------------ #
    # 子类钩子
    def _lookup(self, ref: str):
        """按素材ID检索素材库,返回完整记录(dict)或 None。"""
        raise NotImplementedError

    def _access_path(self, info: dict) -> str:
        """素材本体的可访问本地路径(文件或文件夹);拿不到返回空串。"""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    @staticmethod
    def _row_dict(row):
        from backend.creation.common import row_to_dict

        return row_to_dict(row) if row is not None else None

    def _display_name(self, info: dict) -> str:
        return (info or {}).get("name") or "asset"

    def run(self, task_dir, callback=None, cancel_callback=None):
        config = getattr(self, "config", None) or getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        report = callback or (lambda *a, **k: None)

        source = (config.get("source") or "").strip()
        if not source and step_inputs.get("any"):
            source = str(step_inputs["any"]).strip()
        if not source:
            raise ValueError("素材来源为空，请在节点卡片中从本地素材库选择素材，或填入素材ID/本地路径")

        report(5, "解析素材来源…")
        raw = source.strip()
        source_type = "local"
        asset = None
        access = ""
        if os.path.exists(raw):
            # 直接给了本地文件/文件夹路径
            access = raw
        else:
            ref = _normalize_ref(raw)
            asset = self._lookup(ref)
            if asset is None:
                raise ValueError(f"无法识别素材「{source}」。{self.not_found_hint}")
            access = self._access_path(asset)
            if not access:
                raise ValueError(f"素材「{self._display_name(asset)}」没有可用的文件本体(未上传或多视角图文件夹为空)。")

        report(30, "复制素材到工作目录…")
        task_path = Path(task_dir)
        task_path.mkdir(parents=True, exist_ok=True)
        dest = None
        if access and os.path.isdir(access):
            dest = task_path / _sanitize(self._display_name(asset) if asset else Path(access).name)
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(access, str(dest), dirs_exist_ok=True)
        elif access and os.path.isfile(access):
            ext = os.path.splitext(access)[1].lower()
            base = _sanitize(f"{self._display_name(asset) if asset else Path(access).stem}{ext}")
            dest = task_path / base
            i = 1
            while dest.exists():
                dest = task_path / f"{Path(base).stem}_{i}{Path(base).suffix}"
                i += 1
            shutil.copy2(access, str(dest))

        info = self._build_info(source, source_type, asset, access, dest)
        report(100, f"已完成:{dest.name if dest else self._display_name(asset)}")
        return {
            "artifacts": [str(dest)] if dest else [],
            "outputs": {
                self.output_key: str(dest) if dest else (access if os.path.exists(access) else ""),
                "info": info,
            },
        }

    def _build_info(self, source: str, source_type: str, asset, access: str, dest) -> dict:
        try:
            size = dest.stat().st_size if dest and dest.is_file() else None
        except OSError:
            size = None
        record = dict(asset) if asset else None
        if record is not None:
            record["absolute_path"] = access
        return {
            "source": source,
            "source_type": source_type,
            "kind": self.library_kind,
            "asset": record,
            "file": {
                "path": str(dest) if dest else "",
                "name": dest.name if dest else "",
                "size_bytes": size,
                "copied": dest is not None,
                "from": access,
            },
        }


class S_ImageAssetLibrary(S_MaterialLibraryBase):
    step_id = "image_asset_library"
    step_name = "图片素材库"
    library_kind = "image"
    output_key = "image"

    def _lookup(self, ref: str):
        from backend.control_plane.database import session_scope
        from backend.control_plane.models import ImageAsset

        with session_scope() as session:
            return self._row_dict(session.get(ImageAsset, ref))

    def _access_path(self, info: dict) -> str:
        from backend.creation import paths

        try:
            candidate = paths.resolve_public_path(info.get("path") or "")
        except ValueError:
            return ""
        return str(candidate) if candidate.is_file() else ""


class S_VideoAssetLibrary(S_MaterialLibraryBase):
    step_id = "video_asset_library"
    step_name = "视频素材库"
    library_kind = "video"
    output_key = "video"

    def _lookup(self, ref: str):
        from backend.control_plane.database import session_scope
        from backend.control_plane.models import VideoAsset

        with session_scope() as session:
            return self._row_dict(session.get(VideoAsset, ref))

    def _access_path(self, info: dict) -> str:
        from backend.creation import paths

        try:
            candidate = paths.resolve_public_path(info.get("path") or "")
        except ValueError:
            return ""
        return str(candidate) if candidate.is_file() else ""


class S_CharacterAssetLibrary(S_MaterialLibraryBase):
    step_id = "character_asset_library"
    step_name = "角色素材库"
    library_kind = "character"
    output_key = "path"
    not_found_hint = "请从节点卡片的「本地素材库」选择角色,或确认角色ID有效。"

    def _lookup(self, ref: str):
        from backend.control_plane.database import session_scope
        from backend.control_plane.models import Character

        with session_scope() as session:
            return self._row_dict(session.get(Character, ref))

    def _access_path(self, info: dict) -> str:
        from backend.creation import paths

        images_dir = info.get("images_dir") or ""
        if not images_dir:
            return ""
        try:
            candidate = paths.resolve_public_path(images_dir)
        except ValueError:
            return ""
        return str(candidate) if candidate.is_dir() else ""


class S_VoiceAssetLibrary(S_MaterialLibraryBase):
    step_id = "voice_asset_library"
    step_name = "音色素材库"
    library_kind = "voice"
    output_key = "audio"
    not_found_hint = "请从节点卡片的「本地素材库」选择音色,或确认音色ID有效(支持 vf:voices:<id> 格式)。"

    def _lookup(self, ref: str):
        from backend.voiceforge.database import session, row_to_dict

        with session() as conn:
            row = conn.execute("SELECT * FROM vf_voices WHERE id = ?", (ref,)).fetchone()
            return row_to_dict(row) if row else None

    def _access_path(self, info: dict) -> str:
        from backend.voiceforge.database import storage_root

        key = info.get("sample_storage_key") or info.get("reference_storage_key") or info.get("preview_storage_key") or ""
        if not key:
            return ""
        root = storage_root().resolve()
        candidate = (root / key).resolve()
        if candidate != root and root in candidate.parents and candidate.is_file():
            return str(candidate)
        return ""

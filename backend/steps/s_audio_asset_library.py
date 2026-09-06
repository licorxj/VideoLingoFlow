# -*- coding: utf-8 -*-
"""
音频素材库节点（Step）

作用：解析前端传入的素材来源（URL / 本地路径 / 晴沐配音谷素材库ID），
将素材下载或复制到当前工作文件夹（task_dir）并重命名。

输入：
  - 卡片配置 source：URL / 本地文件(夹)绝对路径 / 素材库素材ID（vf_assets.id）
  - 可选上游 any：作为来源的兜底值（优先使用卡片配置中的 source）
输出：
  - audio：素材路径（素材在 task_dir 中的绝对路径，type=audio，可接入音频类下游节点）
  - info ：素材全信息JSON（来源类型、素材库完整记录、落盘文件信息）
"""
import os
import re
import shutil
from pathlib import Path

from backend.steps.base_step import BaseStep


class S_AudioAssetLibrary(BaseStep):
    step_id = "audio_asset_library"
    step_name = "音频素材库"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 落盘位置由输入决定，无法稳定预判，始终执行。
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    @property
    def name(self) -> str:
        return "音频素材库"

    # ------------------------------------------------------------------ #
    @staticmethod
    def _sanitize(name: str) -> str:
        name = (name or "asset").strip()
        name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name)
        name = name.strip(" ._")
        if not name:
            name = "asset"
        return name[:120] if len(name) > 120 else name

    def _resolve(self, source: str):
        """返回 (download_or_local_url, base_name, ext_hint, vf_info)。vf_info 为素材库完整记录(dict)或 None。"""
        if re.match(r"^https?://", source, re.I):
            url = source
            if "chinaz.com" in url.lower():
                from backend.voiceforge.services import chinaz_sound_effects
                detail = chinaz_sound_effects.get_audio_detail(url)
                dl = detail.get("download_url") or detail.get("audio_url")
                if not dl:
                    raise ValueError("无法从 chinaZ 详情页解析到下载地址，请改用素材直链")
                return dl, detail.get("title") or "chinaz_asset", None, None
            return url, None, None, None
        # 无协议的 chinaZ 详情页路径
        if "chinaz.com" in source.lower():
            prefixed = "https://" + source if source.startswith("//") else "https://" + source.lstrip("/")
            return self._resolve(prefixed)
        # 本地路径
        if os.path.exists(source):
            return source, None, None, None
        # 晴沐配音谷素材库：素材ID / 文件名 / storage_key，回查 vf_assets 还原真实位置与完整信息。
        vf_info = self._lookup_voiceforge_asset(source)
        if vf_info:
            vf = self._asset_access_url(vf_info)
            if vf and (re.match(r"^https?://", vf, re.I) or os.path.exists(vf)):
                ext = os.path.splitext(vf_info.get("file_name") or vf)[1].lower() or None
                return vf, vf_info.get("name") or None, ext, vf_info
        raise ValueError(
            "无法识别该素材库ID。在线素材（如 ElevenLabs）请复制其素材「链接」(audio_url) 而非ID；"
            "chinaZ 素材的ID即详情页链接，可被直接识别；"
            "晴沐配音谷本地素材请复制卡片上的「路径」(external_path) 或素材库ID。"
        )

    @staticmethod
    def _lookup_voiceforge_asset(ref: str):
        """按素材 id / 文件名 / storage_key 在 voiceforge 素材库中检索,返回完整素材记录(dict)或 None。

        本地素材库选择后写入节点卡片的是素材 id（vf_assets.id）；兼容文件名与存储键的写法。
        """
        from backend.voiceforge.database import session, row_to_dict

        norm = (ref or "").strip()
        if not norm:
            return None
        stem = os.path.splitext(norm)[0]  # 去掉扩展名后也可匹配素材 id
        try:
            with session() as conn:
                row = conn.execute(
                    "SELECT * FROM vf_assets WHERE id = ? OR file_name = ? OR storage_key = ? "
                    "OR storage_key LIKE ? OR external_path = ? OR external_path LIKE ? LIMIT 1",
                    (norm, norm, norm, f"%/{norm}", norm, f"%/{norm}"),
                ).fetchone()
                if not row and stem:
                    row = conn.execute(
                        "SELECT * FROM vf_assets WHERE id = ? LIMIT 1", (stem,)
                    ).fetchone()
                if not row:
                    return None
                return row_to_dict(row)
        except Exception:
            # voiceforge 未初始化或查询失败时不影响其它来源解析
            return None

    @staticmethod
    def _asset_access_url(info: dict):
        """素材的可访问地址：库内文件用 storage_key 还原绝对路径;在线未下载素材回退源 URL。

        注意 external_path 可能是 http 链接,直接返回原串,不能过 Path(Path 会折叠 //)。
        """
        from backend.voiceforge.asset_service import resolve_asset_path

        external = (info.get("external_path") or "").strip()
        if re.match(r"^https?://", external, re.I):
            return external
        try:
            return str(resolve_asset_path(info))
        except Exception:
            return external

    def _asset_info(self, source: str, source_type: str, vf_info, dl_url, dest: Path) -> dict:
        """组装素材全信息 JSON:来源 + 素材库完整记录 + 落盘文件信息。"""
        try:
            size = dest.stat().st_size
        except OSError:
            size = None
        info = {
            "source": source,
            "source_type": source_type,
            "file": {
                "path": str(dest),
                "name": dest.name,
                "size_bytes": size,
                "from": dl_url,
            },
        }
        if vf_info:
            record = dict(vf_info)
            record["absolute_path"] = self._asset_access_url(vf_info)
            info["asset"] = record
        else:
            info["asset"] = None
        return info

    def _target_path(self, task_path: Path, dl_url: str, base_name, ext_hint):
        ext = None
        if ext_hint:
            ext = ext_hint
        else:
            bn = dl_url.split("?")[0].split("#")[0]
            _, e = os.path.splitext(bn)
            if e:
                ext = e.lower()
            elif base_name and os.path.splitext(base_name)[1]:
                ext = os.path.splitext(base_name)[1].lower()
        if base_name:
            raw = str(base_name)
        else:
            raw = os.path.splitext(os.path.basename(dl_url.split("?")[0]))[0] or "asset"
        if ext and not raw.lower().endswith(ext):
            raw = raw + ext
        safe = self._sanitize(raw)
        dest = task_path / safe
        if dest.exists():
            stem = Path(safe).stem
            suffix = Path(safe).suffix
            i = 1
            while dest.exists():
                dest = task_path / f"{stem}_{i}{suffix}"
                i += 1
        return dest

    def _download(self, url, dest: Path, cancel_callback, report):
        import requests

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Referer": url,
        }
        resp = requests.get(url, headers=headers, stream=True, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or 0)
        got = 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        try:
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if cancel_callback and cancel_callback():
                        raise RuntimeError("用户已取消下载")
                    if chunk:
                        f.write(chunk)
                        got += len(chunk)
                        if total:
                            pct = 40 + int(55 * got / total)
                            if report:
                                report(min(pct, 95), f"下载中 {got // 1024}KB/{total // 1024}KB")
            tmp.rename(dest)
        finally:
            if tmp.exists():
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def run(self, task_dir, callback=None, cancel_callback=None):
        config = getattr(self, "config", None) or getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        cancel = cancel_callback or (lambda: False)
        report = callback or (lambda *a, **k: None)

        source = (config.get("source") or "").strip()
        if not source and step_inputs.get("any"):
            source = str(step_inputs["any"]).strip()
        if not source:
            raise ValueError("素材来源为空，请在节点卡片中输入 URL、本地路径，或从本地素材库选择素材")

        report(5, "解析素材来源…")
        dl_url, base_name, ext_hint, vf_info = self._resolve(source)
        source_type = "voiceforge_asset" if vf_info else ("url" if re.match(r"^https?://", dl_url, re.I) else "local")

        task_path = Path(task_dir)
        dest = self._target_path(task_path, dl_url, base_name, ext_hint)

        if dl_url.startswith("http://") or dl_url.startswith("https://"):
            report(30, "开始下载素材…")
            self._download(dl_url, dest, cancel, report)
        else:
            report(30, "复制本地素材…")
            if os.path.isdir(dl_url):
                shutil.copytree(dl_url, str(dest), dirs_exist_ok=True)
            else:
                shutil.copy2(dl_url, str(dest))

        info = self._asset_info(source, source_type, vf_info, dl_url, dest)
        report(100, f"已完成：{dest.name}")
        return {
            "artifacts": [str(dest)],
            "outputs": {
                "audio": str(dest),
                "info": info,
            },
        }

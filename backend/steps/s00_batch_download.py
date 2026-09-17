# -*- coding: utf-8 -*-
"""
s00_batch_download: 批量视频下载（基于 yt-dlp 的专辑/播放列表批量下载能力）。

与 s00_platform_download（单集下载）的差异：
  - 去掉 --no-playlist，改用 --yes-playlist，启用 yt-dlp 的专辑/播放列表批量下载；
  - 支持 --playlist-items 下载范围与 --playlist-end 最大条数；
  - 启用 --ignore-errors，单集失败不中断整批；
  - 所有产物统一保存到新建的专辑目录 output/batch_download/<专辑名>_<节点id>/；
  - 输出下载产物清单 JSON（output/batch_download_manifest_<节点id>.json）。

清单 JSON 结构：
{
  "node_id": "...", "source_url": "...", "album_title": "...",
  "album_dir": "output/batch_download/xxx", "created_at": "...",
  "total": 12, "expected_total": 12, "resolution": "best",
  "items": [{"index": 1, "id": "...", "title": "...", "duration": 123.4,
             "webpage_url": "...", "file_size": 1024,
             "video": "...", "subtitle": "...", "cover": "..."}]
}
"""
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from backend.steps.base_step import BaseStep

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".m4v"}
SUB_EXTS = {".srt", ".vtt", ".ass", ".ssa", ".lrc"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _safe_name(name: str, default: str = "download", limit: int = 120) -> str:
    """把任意字符串整理为安全的目录/文件名片段。"""
    name = re.sub(r'[<>:"/\\|?*\r\n\t]', "_", str(name or ""))
    name = re.sub(r"\s+", " ", name).strip().strip(". ")
    if not name:
        name = default
    return name[:limit]


class S00BatchDownload(BaseStep):
    step_id = "s00_batch_download"
    step_name = "Batch Video Download"
    dependencies = []
    artifacts = []  # 动态产物：专辑目录 + 清单 JSON

    # ------------------------------------------------------------------ #
    # 路径与前置校验
    # ------------------------------------------------------------------ #
    def _node_key(self) -> str:
        return getattr(self, "_node_id", "") or self.step_id

    def _manifest_rel(self) -> str:
        return f"output/batch_download_manifest_{self._node_key()}.json"

    def check_artifact(self, task_dir: str) -> bool:
        """产物齐全（清单存在 + 专辑目录非空）时跳过重复下载。"""
        manifest = os.path.join(task_dir, self._manifest_rel())
        if not os.path.isfile(manifest):
            return False
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False
        album_dir = os.path.join(task_dir, str(data.get("album_dir") or ""))
        if not os.path.isdir(album_dir):
            return False
        try:
            return any(os.path.isfile(os.path.join(album_dir, n)) for n in os.listdir(album_dir))
        except OSError:
            return False

    def validate_inputs(self, task_dir: str) -> bool:
        return bool(self._resolve_url(task_dir, getattr(self, "_node_config", {}) or {}))

    # ------------------------------------------------------------------ #
    # 辅助方法
    # ------------------------------------------------------------------ #
    @staticmethod
    def _rel(path: str, task_dir: str) -> str:
        return os.path.relpath(path, task_dir).replace("\\", "/")

    @staticmethod
    def _title_from_url(url: str) -> str:
        seg = url.rstrip("/").split("/")[-1].split("?")[0]
        return seg or "batch_download"

    @staticmethod
    def _sub_lang(task_dir: str) -> str:
        task_json = os.path.join(task_dir, "task.json")
        if os.path.exists(task_json):
            try:
                with open(task_json, "r", encoding="utf-8") as f:
                    return json.load(f).get("input", {}).get("source_language", "") or "en"
            except Exception:
                pass
        return "en"

    def _load_config(self, task_dir: str) -> dict:
        """读取本节点配置：优先 workflow.json（前端卡片），回退 _node_config。"""
        node_cfg = dict(getattr(self, "_node_config", {}) or {})
        wf_path = os.path.join(task_dir, "workflow.json")
        if not os.path.exists(wf_path):
            return node_cfg
        try:
            with open(wf_path, "r", encoding="utf-8") as f:
                wf = json.load(f)
        except Exception:
            return node_cfg
        for node in wf.get("nodes") or []:
            data = node.get("data") or {}
            if data.get("nodeType") == "batch_download":
                node_cfg.update(data.get("config") or {})
                break
        return node_cfg

    def _resolve_url(self, task_dir: str, node_cfg: dict) -> str:
        """URL 优先级：上游连线 > 节点卡片 > input_url_input.txt > task.json。"""
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        url = str(step_inputs.get("url") or "").strip()
        if url:
            return url
        url = str((node_cfg or {}).get("url") or "").strip()
        if url:
            return url
        url_file = os.path.join(task_dir, "cache", "input_url_input.txt")
        if os.path.exists(url_file):
            try:
                with open(url_file, "r", encoding="utf-8") as f:
                    url = f.read().strip()
                if url:
                    return url
            except OSError:
                pass
        task_json = os.path.join(task_dir, "task.json")
        if os.path.exists(task_json):
            try:
                with open(task_json, "r", encoding="utf-8") as f:
                    return str(json.load(f).get("input", {}).get("url") or "").strip()
            except Exception:
                return ""
        return ""

    @staticmethod
    def _probe_album(url: str, cookie_file: str, js_runtime: str,
                     timeout: int = 90) -> Tuple[Optional[str], Optional[int]]:
        """轻量探测专辑/播放列表元信息（--flat-playlist，不下载）。

        返回 (专辑标题, 总集数)，探测失败时返回 (None, None)，由调用方降级处理。
        """
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--flat-playlist",
            "--no-warnings",
            "--dump-single-json",
            "--js-runtimes", js_runtime,
            "--remote-components", "ejs:github",
        ]
        if cookie_file and os.path.exists(cookie_file):
            cmd.extend(["--cookies", cookie_file])
        cmd.append(url)
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                                  encoding="utf-8", errors="replace")
            raw = (proc.stdout or "").strip()
            if not raw:
                return None, None
            data = json.loads(raw)
        except Exception as e:
            print(f"[S00B] 专辑信息探测失败（忽略，改用链接命名）: {e}")
            return None, None

        title = data.get("playlist_title") or data.get("playlist") or data.get("title") or ""
        count = None
        try:
            count = int(data.get("playlist_count") or 0) or None
        except (TypeError, ValueError):
            count = None
        if not count:
            count = len(data.get("entries") or []) or None
        return (str(title).strip() or None), count

    @staticmethod
    def _parse_vldl_lines(stdout_lines: List[str]) -> Dict[str, dict]:
        """解析 yt-dlp --print 输出，返回 {规范化绝对路径: 元数据}。

        模板：after_move:VLDL\\t<playlist_index>\\t<id>\\t<duration>\\t<webpage_url>\\t<filepath>\\t<title>
        title 放在最后，允许标题中包含制表符。
        """
        meta: Dict[str, dict] = {}
        for line in stdout_lines:
            if "VLDL\t" not in line:
                continue
            payload = line.split("after_move:", 1)[-1]
            if not payload.startswith("VLDL\t"):
                continue
            parts = payload.split("\t", 6)
            if len(parts) < 7:
                continue
            _, idx_raw, vid, dur_raw, webpage, filepath, title = parts
            fp = (filepath or "").strip()
            # yt-dlp 对不可用字段输出 NA
            if not fp or fp == "NA":
                continue
            try:
                duration = round(float(dur_raw), 3)
            except (TypeError, ValueError):
                duration = 0.0
            try:
                index = int(float(idx_raw))
            except (TypeError, ValueError):
                index = None
            meta[os.path.normcase(os.path.abspath(fp))] = {
                "index": index,
                "id": (vid or "").strip(),
                "duration": duration,
                "webpage_url": (webpage or "").strip(),
                "title": (title or "").strip(),
            }
        return meta

    # ------------------------------------------------------------------ #
    # 主流程
    # ------------------------------------------------------------------ #
    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        report = callback or (lambda *a, **k: None)
        node_id = self._node_key()
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        node_cfg = self._load_config(task_dir)
        url = self._resolve_url(task_dir, node_cfg)
        if not url:
            raise ValueError("未提供下载地址，请在节点卡片或上游连线中输入专辑/播放列表 URL")

        download_subs = bool(node_cfg.get("download_subs", False))
        download_cover = bool(node_cfg.get("download_cover", False))
        resolution = node_cfg.get("resolution", "best") or "best"
        cookie_file = str(node_cfg.get("cookie_file") or "").strip()
        playlist_items = str(node_cfg.get("playlist_items") or "").strip()
        folder_name = str(node_cfg.get("folder_name") or "").strip()
        try:
            max_items = int(node_cfg.get("max_items") or 0)
        except (TypeError, ValueError):
            max_items = 0

        sub_lang = self._sub_lang(task_dir)
        node_exe = os.environ.get("NODE_EXE")
        js_runtime = f"node:{node_exe}" if node_exe else "node"

        print(f"[S00B] URL: {url[:120]}")
        print(f"[S00B] 分辨率={resolution} 字幕={download_subs}({sub_lang}) 封面={download_cover} "
              f"范围={playlist_items or '全部'} 上限={max_items or '不限'}")
        report(3, f"准备批量下载: {url[:80]}")

        # 1) 探测专辑信息（不下载），用于命名产物目录
        report(5, "读取专辑信息...")
        album_title, album_count = self._probe_album(url, cookie_file, js_runtime)
        if album_title:
            print(f"[S00B] 专辑: {album_title}" + (f"（共 {album_count} 集）" if album_count else ""))

        # 2) 新建产物目录：output/batch_download/<专辑名>_<节点id>
        dir_seed = folder_name or album_title or self._title_from_url(url)
        album_dirname = f"{_safe_name(dir_seed, 'batch_download')}_{node_id}"
        album_dir = os.path.join(output_dir, "batch_download", album_dirname)
        os.makedirs(album_dir, exist_ok=True)
        print(f"[S00B] 产物目录: {album_dir}")
        report(8, f"产物目录: {album_dirname}")

        # 3) 更新 yt-dlp（20s 超时，失败不阻塞）
        try:
            upd = subprocess.run([sys.executable, "-m", "yt_dlp", "-U"],
                                 capture_output=True, text=True, timeout=20)
            status = "updated" if upd.returncode == 0 else "skipped"
        except Exception:
            status = "skipped"
        print(f"[S00B] yt-dlp update: {status}")

        # 4) 构建批量下载命令（关键：--yes-playlist 启用专辑/播放列表批量下载）
        name_tmpl = "%(playlist_index)03d - %(title).200B.%(ext)s"
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--yes-playlist",
            "--ignore-errors",
            "-o", os.path.join(album_dir, name_tmpl),
            "--print", "after_move:VLDL\t%(playlist_index)s\t%(id)s\t%(duration)s\t"
                       "%(webpage_url)s\t%(filepath)s\t%(title)s",
            "--js-runtimes", js_runtime,
            "--remote-components", "ejs:github",
            "--extractor-args", "youtube:player_client=web_embedded",
        ]

        if resolution == "1080p":
            cmd.extend(["-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"])
        elif resolution == "720p":
            cmd.extend(["-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best"])
        else:
            cmd.extend(["-f", "bestvideo+bestaudio/best"])
        cmd.extend(["--merge-output-format", "mp4"])

        if download_subs:
            cmd.extend([
                "--write-subs", "--write-auto-subs",
                "--sub-langs", sub_lang,
                "--convert-subs", "srt",
                "--sub-format", "srt/best",
            ])
            cmd.extend(["-o", "subtitle:" + os.path.join(album_dir, name_tmpl)])

        if download_cover:
            cmd.extend(["--write-thumbnail", "--convert-thumbnails", "jpg"])
            cmd.extend(["-o", "thumbnail:" + os.path.join(album_dir, name_tmpl)])

        if playlist_items:
            cmd.extend(["--playlist-items", playlist_items])
        if max_items and max_items > 0:
            cmd.extend(["--playlist-end", str(max_items)])
        if cookie_file and os.path.exists(cookie_file):
            cmd.extend(["--cookies", cookie_file])

        cmd.append(url)

        print(f"[S00B] 开始批量下载: {' '.join(cmd[:6])} ...")
        report(10, "开始批量下载...")

        # 5) 执行：stdout 由后台线程排空（--print 输出），主线程读 stderr 报进度
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        stdout_lines: List[str] = []
        stderr_lines: List[str] = []

        def _drain_stdout():
            try:
                for line in proc.stdout:
                    stdout_lines.append(line.rstrip("\n\r"))
            except Exception:
                pass

        drainer = threading.Thread(target=_drain_stdout, daemon=True)
        drainer.start()

        total_items = album_count or 0
        cur_item = 0
        last_pct = 10
        try:
            for line in proc.stderr:
                line = line.rstrip("\n\r")
                stderr_lines.append(line)
                print(f"[S00B] {line}")

                m_item = re.search(r"Downloading item (\d+) of (\d+)", line)
                if m_item:
                    cur_item = int(m_item.group(1))
                    total_items = int(m_item.group(2)) or total_items
                    report(min(12 + int((cur_item - 1) / max(total_items, 1) * 76), 95),
                           f"第 {cur_item}/{total_items} 集")

                m_pct = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
                if m_pct:
                    pct = float(m_pct.group(1))
                    if total_items and total_items > 0:
                        overall = (max(cur_item, 1) - 1 + pct / 100.0) / total_items
                    else:
                        overall = pct / 100.0
                    mapped = max(10, min(96, 12 + int(overall * 76)))
                    if mapped > last_pct:
                        last_pct = mapped
                        speed = re.search(r"at\s+(\S+/s)", line)
                        eta = re.search(r"ETA\s+(\S+)", line)
                        msg = f"下载 {pct:.1f}%"
                        if speed:
                            msg += f" {speed.group(1)}"
                        if eta:
                            msg += f" ETA {eta.group(1)}"
                        report(mapped, msg)

                if cancel_callback and cancel_callback():
                    proc.terminate()
                    raise RuntimeError("用户已取消批量下载")
        finally:
            drainer.join(timeout=30)
            try:
                proc.wait(timeout=7200)
            except subprocess.TimeoutExpired:
                proc.kill()

        print(f"[S00B] yt-dlp 退出码: {proc.returncode}")

        # 6) 以磁盘产物为准构建清单（--print 元数据作为补充）
        report(90, "整理下载产物...")
        meta_by_path = self._parse_vldl_lines(stdout_lines)

        videos: List[str] = []
        subs: List[str] = []
        covers: List[str] = []
        for name in sorted(os.listdir(album_dir)):
            path = os.path.join(album_dir, name)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in VIDEO_EXTS:
                videos.append(path)
            elif ext in SUB_EXTS:
                subs.append(path)
            elif ext in IMAGE_EXTS:
                covers.append(path)

        items = []
        for vp in videos:
            key = os.path.normcase(os.path.abspath(vp))
            meta = meta_by_path.get(key, {})
            stem = os.path.splitext(os.path.basename(vp))[0]
            try:
                size = os.path.getsize(vp)
            except OSError:
                size = 0
            sub = next((p for p in subs
                        if os.path.splitext(os.path.basename(p))[0].startswith(stem)), None)
            cover = next((p for p in covers
                          if os.path.splitext(os.path.basename(p))[0].startswith(stem)), None)
            items.append({
                "index": meta.get("index"),
                "id": meta.get("id") or "",
                "title": meta.get("title") or stem,
                "duration": meta.get("duration", 0.0),
                "webpage_url": meta.get("webpage_url") or "",
                "file_size": size,
                "video": self._rel(vp, task_dir),
                "subtitle": self._rel(sub, task_dir) if sub else None,
                "cover": self._rel(cover, task_dir) if cover else None,
            })
        items.sort(key=lambda it: (it["index"] is None, it["index"] or 0))

        if not items:
            diag = "\n".join(stderr_lines[-12:]) or "\n".join(stdout_lines[-8:]) or "<无输出>"
            raise RuntimeError(
                f"批量下载失败：未下载到任何视频文件（yt-dlp 退出码 {proc.returncode}）。"
                f"请检查专辑/播放列表链接、Cookie 与网络。\n{diag[:800]}"
            )

        if album_count and len(items) < album_count:
            print(f"[S00B] 警告: 预期 {album_count} 集，实际下载 {len(items)} 集（部分条目可能被跳过或下载失败）")

        # 7) 写入下载产物清单 JSON
        album_rel = self._rel(album_dir, task_dir)
        manifest = {
            "node_id": node_id,
            "source_url": url,
            "album_title": album_title or "",
            "album_dir": album_rel,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "total": len(items),
            "expected_total": album_count or len(items),
            "resolution": resolution,
            "items": items,
        }
        manifest_rel = self._manifest_rel()
        with open(os.path.join(task_dir, manifest_rel), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"[S00B] 已写入清单: {manifest_rel}（{len(items)} 条）")

        artifacts = [manifest_rel, album_rel]
        for it in items:
            for key in ("video", "subtitle", "cover"):
                if it.get(key):
                    artifacts.append(it[key])

        report(100, f"批量下载完成: {len(items)} 个视频")
        return {
            "artifacts": artifacts,
            "outputs": {
                "json": manifest_rel,
                "folder": album_rel,
                "video": items[0]["video"],
            },
        }


S00BatchDownloadStep = S00BatchDownload

"""
s00_platform_download: Download video/audio/subtitles from platforms using yt-dlp.
"""
import os
import re
import sys
import subprocess
from typing import Callable, Optional
from backend.steps.base_step import BaseStep
from backend.config.config_manager import config


def sanitize_filename(name: str) -> str:
    """Make filename safe for filesystem."""
    # Remove or replace illegal characters
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = name.strip('. ')
    if not name:
        name = "download"
    return name[:200]  # Limit length


class S00PlatformDownload(BaseStep):
    step_id = "s00_platform_download"
    step_name = "Platform Video Download"
    dependencies = []
    artifacts = []  # Dynamic based on config

    def check_artifact(self, task_dir: str) -> bool:
        cache = os.path.join(task_dir, "cache")
        return any(f.startswith("s00_platform_download_") for f in os.listdir(cache) if os.path.exists(cache))

    def validate_inputs(self, task_dir: str) -> bool:
        task_json = os.path.join(task_dir, "task.json")
        if os.path.exists(task_json):
            import json
            with open(task_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            url = data.get("input", {}).get("url", "")
            return bool(url)
        return False

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        task_json = os.path.join(task_dir, "task.json")
        cache_dir = os.path.join(task_dir, "cache")

        import json as _json
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # Priority 1: URL from upstream node via step_inputs (resolved by scheduler)
        url = step_inputs.get("url", "")

        if not url:
            with open(task_json, "r", encoding="utf-8") as f:
                task_data = _json.load(f)

            # Priority 2: Read URL from input artifact (text file passed from upstream)
            url_file = os.path.join(task_dir, "cache", "input_url_input.txt")
            if os.path.exists(url_file):
                with open(url_file, "r", encoding="utf-8") as f:
                    url = f.read().strip()

            # Priority 3: Fallback to task.json input config
            if not url:
                input_cfg = task_data.get("input", {})
                url = input_cfg.get("url", "")

        # Read node config from workflow.json
        node_cfg = {}
        wf_path = os.path.join(task_dir, "workflow.json")
        if os.path.exists(wf_path):
            with open(wf_path, "r", encoding="utf-8") as f:
                wf = _json.load(f)
            for node in wf.get("nodes", []):
                if node.get("data", {}).get("nodeType") == "platform_download":
                    node_cfg = node.get("data", {}).get("config", {})
                    break
        if not url:
            raise ValueError("No URL provided for download")

        # Config options
        download_subs = node_cfg.get("download_subs", False)
        download_cover = node_cfg.get("download_cover", False)
        resolution = node_cfg.get("resolution", "best")
        cookie_file = node_cfg.get("cookie_file", "")
        use_as_task_name = node_cfg.get("use_as_task_name", False)

        # Determine subtitle language from task input config
        sub_lang = "en"
        try:
            tj = os.path.join(task_dir, "task.json")
            if os.path.exists(tj):
                with open(tj, "r", encoding="utf-8") as f:
                    sub_lang = _json.load(f).get("input", {}).get("source_language", "") or "en"
        except Exception:
            pass

        print(f"[S00] URL: {url[:120]}")
        print(f"[S00] Resolution: {resolution}, Subs: {download_subs}, Cover: {download_cover}, Cookie: {bool(cookie_file)}")
        if callback:
            callback(5, f"Starting download from: {url[:80]}...")

        # Download into the task cache directory first, then rename after success.
        # Do not predefine the final video filename here.
        video_download_dir = cache_dir

        # Node.js runtime for yt-dlp JS challenge solving.
        # NODE_EXE is set by start.bat; fallback to PATH lookup if absent.
        node_exe = os.environ.get("NODE_EXE")
        js_runtime = f"node:{node_exe}" if node_exe else "node"

        # Build yt-dlp command (use python -m yt_dlp for Windows PATH compatibility)
        # Print the title and final filepath at after_move stage, so filepath is real
        # instead of the metadata-stage "NA".
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--no-playlist",
            "-P", video_download_dir,
            "--print", "after_move:VLDL\t%(title)s\t%(filepath)s",
            "--js-runtimes", js_runtime,
            "--remote-components", "ejs:github",
            "--extractor-args", "youtube:player_client=web_embedded",
        ]

        # Resolution/format
        if resolution == "1080p":
            cmd.extend(["-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"])
        elif resolution == "720p":
            cmd.extend(["-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best"])
        else:
            cmd.extend(["-f", "bestvideo+bestaudio/best"])
        cmd.extend(["--merge-output-format", "mp4"])

        # Subtitles
        if download_subs:
            cmd.extend([
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs", sub_lang,
                "--convert-subs", "srt",
                "--sub-format", "srt/best",
            ])
            cmd.extend(["--output", "subtitle:" + os.path.join(cache_dir, "s00_platform_download_sub.%(ext)s")])

        # Cover/thumbnail
        if download_cover:
            cmd.extend(["--write-thumbnail", "--convert-thumbnails", "jpg"])
            cmd.extend(["--output", "thumbnail:" + os.path.join(cache_dir, "s00_platform_download_cover.%(ext)s")])

        # Cookie file
        if cookie_file and os.path.exists(cookie_file):
            cmd.extend(["--cookies", cookie_file])

        cmd.append(url)

        print("[S00] Updating yt-dlp...")
        if callback:
            callback(5, "Updating yt-dlp...")

        # Update yt-dlp first (20s timeout)
        try:
            update_result = subprocess.run(
                [sys.executable, "-m", "yt_dlp", "-U"],
                capture_output=True, text=True, timeout=20
            )
            status = "updated" if update_result.returncode == 0 else "skipped"
            print(f"[S00] yt-dlp update: {status}")
            if callback:
                callback(8, f"yt-dlp {status}")
        except subprocess.TimeoutExpired:
            print("[S00] yt-dlp update timeout, continuing...")
            if callback:
                callback(8, "yt-dlp update timeout, continuing...")
        except Exception:
            pass

        print(f"[S00] Command: {' '.join(cmd[:8])}...")
        print("[S00] Downloading...")
        if callback:
            callback(10, "Downloading...")

        # Execute yt-dlp with streaming output to keep WebSocket alive
        import re as _re
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        stdout_lines = []
        stderr_lines = []
        last_progress = 10

        # Read stderr in real-time (yt-dlp writes progress to stderr)
        for line in proc.stderr:
            line = line.rstrip("\n\r")
            stderr_lines.append(line)
            print(f"[S00] {line}")

            # Parse yt-dlp progress: "[download]  45.2% of 123.45MiB ..."
            pct_match = _re.search(r'\[download\]\s+(\d+(?:\.\d+)?)%', line)
            if pct_match and callback:
                pct = float(pct_match.group(1))
                mapped = 10 + int(pct * 0.6)  # 10%~70%
                if mapped > last_progress:
                    last_progress = mapped
                    speed_match = _re.search(r'at\s+(\S+/s)', line)
                    eta_match = _re.search(r'ETA\s+(\S+)', line)
                    msg = f"Downloading {pct:.1f}%"
                    if speed_match:
                        msg += f" at {speed_match.group(1)}"
                    if eta_match:
                        msg += f" ETA {eta_match.group(1)}"
                    callback(mapped, msg)

        # Read remaining stdout
        stdout_text = proc.stdout.read() if proc.stdout else ""
        stdout_lines = stdout_text.split("\n") if stdout_text else []
        proc.wait(timeout=600)

        # Simulate result object for downstream code
        class _Result:
            pass
        result = _Result()
        result.returncode = proc.returncode
        result.stdout = stdout_text
        result.stderr = "\n".join(stderr_lines)
        stderr_text = result.stderr
        video_title, dl_filepath = self._parse_vldl_output(stdout_text)
        resolved_video_path = self._find_downloaded_video_file(cache_dir, dl_filepath)
        has_output_file = bool(resolved_video_path) and os.path.exists(resolved_video_path)

        if result.returncode != 0:
            if "has already been downloaded" in stderr_text:
                if callback:
                    callback(90, "File already downloaded")
            elif has_output_file:
                # Download succeeded despite warnings
                print(f"[S00] yt-dlp exited with code {result.returncode} (warnings only, download succeeded)")
            else:
                raise Exception(f"yt-dlp failed: {stderr_text[:300]}")

        print(f"[S00] Download exit code: {result.returncode}")
        if video_title:
            print(f"[S00] Video title: {video_title}")
        if resolved_video_path and os.path.exists(resolved_video_path):
            print(f"[S00] yt-dlp filepath: {resolved_video_path}")
        # Always print diagnostic output to help troubleshoot silent failures
        if result.stderr:
            for line in result.stderr.strip().split("\n")[-10:]:
                print(f"[S00] yt-dlp stderr: {line.strip()}")
        else:
            print(f"[S00] yt-dlp stderr: <empty>")
        if result.stdout:
            for line in result.stdout.strip().split("\n")[-8:]:
                print(f"[S00] yt-dlp stdout: {line.strip()}")
        if callback:
            callback(50, "Download complete, processing files...")

        # Resolve a sanitized title for naming the output video.
        # Priority: real title from yt-dlp > URL trailing segment > "video".
        if video_title:
            safe_title = sanitize_filename(video_title)
        else:
            safe_title = sanitize_filename(url.rstrip("/").split("/")[-1]) or "video"

        # Rename the downloaded video using the resolved real filepath first.
        produced = {}
        if resolved_video_path and os.path.isfile(resolved_video_path):
            ext = os.path.splitext(resolved_video_path)[1].lower()
            new_name = f"s00_platform_download_video_{safe_title}{ext}"
            new_path = os.path.join(cache_dir, new_name)
            if os.path.abspath(resolved_video_path) != os.path.abspath(new_path):
                os.rename(resolved_video_path, new_path)
            else:
                new_path = resolved_video_path
            produced["video"] = new_path
            if callback:
                callback(70, f"Video: {os.path.basename(new_path)}")

        # Scan cache for subtitle/cover outputs and rename with sanitized name
        if os.path.exists(cache_dir):
            for f in os.listdir(cache_dir):
                fpath = os.path.join(cache_dir, f)
                if not os.path.isfile(fpath):
                    continue

                # Determine file type
                ext = os.path.splitext(f)[1].lower()
                if f.startswith("s00_platform_download_sub"):
                    new_name = f"s00_platform_download_sub_{safe_title}{ext}"
                    new_path = os.path.join(cache_dir, new_name)
                    os.rename(fpath, new_path)
                    produced["subtitle"] = new_path
                    if callback:
                        callback(80, f"Subtitle: {new_name}")

                elif f.startswith("s00_platform_download_cover"):
                    new_name = f"s00_platform_download_cover_{safe_title}{ext}"
                    new_path = os.path.join(cache_dir, new_name)
                    os.rename(fpath, new_path)
                    produced["cover"] = new_path
                    if callback:
                        callback(85, f"Cover: {new_name}")

        # File existence validation: ensure the video was actually downloaded.
        # yt-dlp may return exit code 0 even when the media download was blocked
        # (e.g. YouTube bot detection without cookies), so we must verify the file.
        if "video" not in produced:
            diag = stderr_text.strip() or stdout_text.strip() or "<no output>"
            raise Exception(
                f"Download failed: no video file was produced. "
                f"yt-dlp exit code: {result.returncode}, title: {video_title or 'N/A'}. "
                f"output: {diag[:500]}"
            )

        # Update task_name if user checked "记录为任务名称" and we have a real title.
        if use_as_task_name and video_title and os.path.exists(task_json):
            try:
                with open(task_json, "r", encoding="utf-8") as f:
                    tdata = _json.load(f)
                tdata["task_name"] = video_title
                with open(task_json, "w", encoding="utf-8") as f:
                    _json.dump(tdata, f, ensure_ascii=False, indent=2)
                print(f"[S00] task_name set to: {video_title}")
            except Exception as e:
                print(f"[S00] WARNING: failed to update task_name: {e}")

        for ftype, fpath in produced.items():
            print(f"[S00] Output: {ftype} -> {os.path.basename(fpath)}")
        print(f"[S00] Done: {len(produced)} files produced")
        if callback:
            callback(100, f"Downloaded: {len(produced)} files")

        return {
            "artifacts": [os.path.relpath(path, task_dir) for path in produced.values()],
            "outputs": {
                ("image" if key == "cover" else key): os.path.relpath(path, task_dir)
                for key, path in produced.items()
            },
        }

    def _parse_vldl_output(self, stdout: str):
        """Parse the VLDL marker line emitted by yt-dlp --print.

        The --print template is "after_move:VLDL\\t<title>\\t<filepath>".
        Returns (title, filepath);
        filepath is None when no VLDL line is present or the field is unavailable ("NA").
        """
        for line in stdout.split("\n"):
            if line.startswith("VLDL\t") or line.startswith("after_move:VLDL\t"):
                payload = line.split("after_move:", 1)[-1]
                parts = payload.split("\t", 2)
                if len(parts) == 3:
                    title, filepath = parts[1], parts[2]
                    # yt-dlp outputs "NA" for unavailable field values
                    if filepath == "NA":
                        filepath = None
                    return title, filepath
        return None, None

    def _find_downloaded_video_file(self, cache_dir: str, reported_path: Optional[str]) -> Optional[str]:
        """Resolve the actual downloaded video file path.

        Prefer the path reported by yt-dlp after_move. If unavailable, scan the
        cache directory for the newest likely video file.
        """
        if reported_path and os.path.isfile(reported_path):
            return reported_path
        if not os.path.exists(cache_dir):
            return None

        video_exts = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".m4v"}
        candidates = []
        for name in os.listdir(cache_dir):
            path = os.path.join(cache_dir, name)
            if not os.path.isfile(path):
                continue
            if name.startswith("s00_platform_download_sub") or name.startswith("s00_platform_download_cover"):
                continue
            if os.path.splitext(name)[1].lower() not in video_exts:
                continue
            candidates.append((os.path.getmtime(path), path))

        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

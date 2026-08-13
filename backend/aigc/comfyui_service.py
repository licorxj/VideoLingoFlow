"""ComfyUI 本地/局域网节点调用服务。

从 Infinite-Canvas 的 /api/generate（ComfyUI 分支）迁移核心逻辑：
- 上传参考图到 ComfyUI 实例的 /upload/image
- POST /prompt 提交工作流（注入 prompt/seed/尺寸）
- 轮询 /history 直到完成
- 下载 outputs（图片/视频/音频/文本）

配置（来自 settings.aigc.comfyui）：
- instances: ["127.0.0.1:8188", ...]  支持多后端负载
- timeout: 1800 轮询总超时（秒）
"""
import os
import io
import json
import time
import uuid
import random
import threading
import urllib.request
import urllib.error
import urllib.parse
import base64

import requests

from backend.aigc.errors import AIGCError

COMFYUI_HISTORY_TIMEOUT = 1800


def _class_is_preview(class_type: str) -> bool:
    ct = (class_type or "").lower()
    return ct in {"previewimage", "previewvideo", "videopreview", "imagepreview"}


def _class_is_debug_text(class_type: str) -> bool:
    ct = (class_type or "").lower()
    return ct in {"showtext", "showtextany", "debug", "debugtext"}


def _output_kind(item: dict) -> str:
    """根据 ComfyUI 输出条目推断类型。"""
    if not isinstance(item, dict):
        return "file"
    if item.get("type") == "output":
        sub = item.get("subfolder") or ""
        if "video" in sub or any(k in str(item.get("filename", "")).lower() for k in (".mp4", ".webm", ".mov", ".mkv")):
            return "video"
        if any(k in str(item.get("filename", "")).lower() for k in (".wav", ".mp3", ".flac", ".ogg")):
            return "audio"
        if any(k in str(item.get("filename", "")).lower() for k in (".png", ".jpg", ".jpeg", ".webp")):
            return "image"
        return "file"
    if item.get("type") == "text":
        return "text"
    return "file"


def _collect_file_items(node_output: dict):
    items = []
    if not isinstance(node_output, dict):
        return items
    for output_key, value in node_output.items():
        if output_key in ("images", "gifs", "videos"):
            if isinstance(value, list):
                for it in value:
                    if isinstance(it, dict):
                        items.append((output_key, it))
        elif output_key == "text":
            if isinstance(value, str):
                items.append((output_key, value))
    return items


def _collect_text_values(node_output: dict):
    out = []
    if isinstance(node_output, dict):
        text = node_output.get("text")
        if isinstance(text, str) and text.strip():
            out.append((text, node_output.get("name", "text")))
    return out


class ComfyUIService:
    """本地/局域网 ComfyUI 调用。"""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.instances = [s.strip() for s in (self.config.get("instances") or []) if s.strip()]
        self.timeout = int(self.config.get("timeout") or COMFYUI_HISTORY_TIMEOUT)
        self.load_lock = threading.Lock()
        self.local_load: dict[str, int] = {addr: 0 for addr in self.instances}
        self.client_id = "videolingo-" + uuid.uuid4().hex[:8]

    # ── 内部 HTTP 工具 ────────────────────────────────────────────────
    def _get_json(self, url: str, timeout: int = 30):
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _post_json(self, url: str, payload: dict, timeout: int = 30):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _reserve_backend(self) -> str:
        if not self.instances:
            raise AIGCError("未配置 ComfyUI 实例，请在「其他能力接口」设置中填写 ComfyUI 地址")
        with self.load_lock:
            addr = min(self.instances, key=lambda a: self.local_load.get(a, 0))
            self.local_load[addr] = self.local_load.get(addr, 0) + 1
            return addr

    def _release_backend(self, addr: str):
        if not addr:
            return
        with self.load_lock:
            self.local_load[addr] = max(0, self.local_load.get(addr, 0) - 1)

    def upload_image(self, addr: str, image_path_or_bytes: bytes | str, filename: str = "") -> str | None:
        """上传图片到 ComfyUI 的 /upload/image，返回 ComfyUI 内的文件名（用于作为输入节点引用）。"""
        if isinstance(image_path_or_bytes, str):
            if not os.path.isfile(image_path_or_bytes):
                return None
            with open(image_path_or_bytes, "rb") as f:
                content = f.read()
            fname = filename or os.path.basename(image_path_or_bytes)
        else:
            content = image_path_or_bytes
            fname = filename or "input.png"
        try:
            files = {"image": (fname, content, "image/png")}
            resp = requests.post(f"http://{addr}/upload/image", files=files, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("name")
        except Exception as e:
            raise AIGCError(f"ComfyUI 上传图片失败：{e}") from e
        return None

    def upload_video(self, addr: str, video_path: str, filename: str = "") -> str | None:
        """上传参考视频到 ComfyUI 的 /upload/video，返回文件名（供 LoadVideo 类节点引用）。"""
        if not video_path or not os.path.isfile(video_path):
            return None
        fname = filename or os.path.basename(video_path)
        try:
            with open(video_path, "rb") as f:
                content = f.read()
            files = {"video": (fname, content, "video/mp4")}
            resp = requests.post(f"http://{addr}/upload/video", files=files, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("name")
        except Exception as e:
            raise AIGCError(f"ComfyUI 上传参考视频失败：{e}") from e
        return None

    def run_workflow(
        self,
        workflow: dict,
        prompt_text: str = "",
        width: int = 1024,
        height: int = 1024,
        params: dict | None = None,
        ref_images: list[str] | None = None,
        ref_video: str = "",
        callback=None,
        output_dir: str | None = None,
        num_images: int = 1,
    ) -> dict:
        """提交并等待一个 ComfyUI 工作流，产物直接下载到 output_dir（默认 tasks/aigc_output）。

        ref_images: 本地图片路径列表（首帧/图片2/图片3/图片4/尾帧组装），会上传到目标实例。
        ref_video: 本地参考视频路径，会上传到目标实例并注入 LoadVideo 类节点的 video 输入。
        output_dir: 产物落盘目录；不传则使用全局 aigc_output 目录。
        num_images: 生成数量，注入工作流中的 batch_size 类节点输入（如 EmptyLatentImage.batch_size）。
        """
        params = params or {}
        target = self._reserve_backend()
        try:
            if callback:
                callback(10, f"已选择 ComfyUI 后端 {target}")

            # 同步/上传参考图
            required_images = self._collect_required_media(params)
            if ref_images:
                for img in ref_images:
                    fname = self.upload_image(target, img)
                    if fname:
                        required_images.append(fname)

            # 上传参考视频并注入 LoadVideo 类节点
            if ref_video:
                vname = self.upload_video(target, ref_video)
                if vname:
                    for nid, nd in workflow.items():
                        if not isinstance(nd, dict):
                            continue
                        if "loadvideo" in str(nd.get("class_type") or "").lower():
                            nd.setdefault("inputs", {})["video"] = vname

            # 注入参数
            seed = random.randint(1, 4294967295)
            if prompt_text and "6" in workflow:
                try:
                    workflow["6"]["inputs"]["text"] = prompt_text
                except Exception:
                    pass
            if "144" in workflow:
                try:
                    workflow["144"]["inputs"]["width"] = width
                    workflow["144"]["inputs"]["height"] = height
                except Exception:
                    pass
            for seed_node in ("22", "158", "14", "172", "184", "146", "181"):
                if seed_node in workflow:
                    try:
                        workflow[seed_node]["inputs"]["seed"] = seed
                    except Exception:
                        pass
            for node_id, node_inputs in params.items():
                if node_id in workflow and isinstance(node_inputs, dict):
                    wi = workflow[node_id].setdefault("inputs", {})
                    for k, v in node_inputs.items():
                        if v is None:
                            wi.pop(k, None)
                        else:
                            wi[k] = v

            # 生成数量：注入 batch_size 类节点的 batch_size 输入
            if int(num_images or 1) > 1:
                for nid, nd in workflow.items():
                    if not isinstance(nd, dict):
                        continue
                    ct = str(nd.get("class_type") or "")
                    if "Latent" in ct and isinstance(nd.get("inputs"), dict) and "batch_size" in nd["inputs"]:
                        try:
                            nd["inputs"]["batch_size"] = int(num_images)
                        except Exception:
                            pass

            if callback:
                callback(30, "已提交工作流到 ComfyUI")

            payload = {"prompt": workflow, "client_id": self.client_id}
            try:
                resp = self._post_json(f"http://{target}/prompt", payload, timeout=30)
                prompt_id = resp["prompt_id"]
            except Exception as e:
                raise AIGCError(f"ComfyUI 提交失败：{e}") from e

            history = None
            for _ in range(self.timeout):
                try:
                    res = self._get_json(f"http://{target}/history", timeout=10)
                    if prompt_id in res:
                        history = res[prompt_id]
                        break
                except Exception:
                    pass
                time.sleep(1)
            if not history:
                raise AIGCError("ComfyUI 渲染超时")

            if callback:
                callback(70, "工作流完成，正在下载产物")

            return self._download_outputs(target, workflow, history, output_dir)
        finally:
            self._release_backend(target)

    def _collect_required_media(self, params: dict) -> list[str]:
        names = []
        for node_inputs in params.values():
            if isinstance(node_inputs, dict):
                for v in node_inputs.values():
                    if isinstance(v, str) and v:
                        names.append(v)
        return names

    def _download_outputs(self, addr: str, workflow: dict, history: dict, output_dir: str | None = None) -> dict:
        outputs = history.get("outputs", {})
        output_dir = output_dir or self._output_dir()
        prefix = f"comfyui_{int(time.time())}_"
        local_images, local_videos, local_audios, local_texts, local_files, local_items = [], [], [], [], [], []

        def class_type_of(nid):
            nd = workflow.get(str(nid))
            return str(nd.get("class_type") or "") if isinstance(nd, dict) else ""

        file_candidates, text_candidates = [], []
        for node_id, node_output in outputs.items():
            ct = class_type_of(node_id)
            for output_key, item in _collect_file_items(node_output):
                file_candidates.append((node_id, ct, output_key, item, _output_kind(item)))
            for text, name in _collect_text_values(node_output):
                text_candidates.append((node_id, ct, text, name))

        has_primary_image = any(
            kind == "image" and not _class_is_preview(ct) for (_nid, ct, _ok, _it, kind) in file_candidates
        )

        for node_id, ct, output_key, item, kind in file_candidates:
            if kind == "image" and has_primary_image and _class_is_preview(ct):
                continue
            local_path = self._download_one(addr, item, prefix, output_dir)
            if not local_path:
                continue
            name = os.path.basename(str(item.get("filename") or local_path).split("?")[0])
            entry = {
                "kind": kind,
                "name": name,
                "node_id": str(node_id),
                "output_key": str(output_key),
                "class_type": ct,
                "path": local_path,
            }
            if kind == "image":
                local_images.append(local_path)
            elif kind == "video":
                local_videos.append(local_path)
            elif kind == "audio":
                local_audios.append(local_path)
            elif kind == "text":
                local_texts.append(local_path)
            else:
                local_files.append(local_path)
            local_items.append(entry)

        for node_id, ct, text, name in text_candidates:
            if _class_is_debug_text(ct):
                continue
            local_path = self._save_text(text, prefix, name, output_dir)
            local_texts.append(local_path)
            local_items.append({"kind": "text", "name": name, "node_id": str(node_id), "path": local_path})

        return {
            "images": local_images,
            "videos": local_videos,
            "audios": local_audios,
            "texts": local_texts,
            "files": local_files,
            "items": local_items,
            "backend": addr,
        }

    def _download_one(self, addr: str, item: dict, prefix: str = "", output_dir: str | None = None) -> str | None:
        filename = item.get("filename")
        subfolder = item.get("subfolder", "")
        ftype = item.get("type", "output")
        if not filename:
            return None
        url = (
            f"http://{addr}/view?filename={urllib.parse.quote(filename)}"
            f"&subfolder={urllib.parse.quote(subfolder)}&type={urllib.parse.quote(ftype)}"
        )
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=60) as resp:
                content = resp.read()
            ext = os.path.splitext(filename)[1] or ".png"
            safe_name = os.path.basename(filename)
            out_name = f"{prefix}{safe_name}" if prefix else safe_name
            out_path = os.path.join(output_dir or self._output_dir(), out_name)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(content)
            return out_path
        except Exception as e:
            print(f"ComfyUI 下载产物失败 {filename}: {e}")
            return None

    def _save_text(self, text: str, prefix: str, name: str, output_dir: str | None = None) -> str:
        out_path = os.path.join(output_dir or self._output_dir(), f"{prefix}{name}.txt")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        return out_path

    def _output_dir(self) -> str:
        out = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tasks", "aigc_output")
        os.makedirs(out, exist_ok=True)
        return out

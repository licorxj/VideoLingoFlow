"""RunningHub OpenAPI 调用服务。

从 Infinite-Canvas 的 RunningHub 调用逻辑迁移核心流程：
- 上传参考素材到 /task/openapi/upload，得到 fileName
- 提交工作流 / AI 应用任务到 /task/openapi/create 或 /task/openapi/ai-app/run
- 轮询 /task/openapi/outputs 直到成功，提取图片/视频 URL
- 下载结果到本地

配置（来自 settings.aigc.runninghub）：
- base_url: "https://www.runninghub.ai"
- api_key: ""   标准模型接口 Key
- wallet_api_key: ""  账户余额 Key（标准模型接口需要）
- timeout: 1800 轮询总超时（秒）
"""
import os
import time
import asyncio

import httpx

from backend.aigc.errors import AIGCError

RUNNINGHUB_DEFAULT_BASE_URL = "https://www.runninghub.ai"
RUNNINGHUB_RUN_TIMEOUT = 1800


def _runninghub_endpoint(base_url: str, path: str) -> str:
    return (base_url.rstrip("/") + path)


def _runninghub_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _runninghub_extract_outputs(data) -> list:
    arr = []
    if isinstance(data, list):
        arr = data
    elif isinstance(data, dict):
        for key in ("outputs", "results", "files", "data"):
            value = data.get(key)
            if isinstance(value, list):
                arr = value
                break
        if not arr and (data.get("fileUrl") or data.get("url")):
            arr = [data]
    out = []
    for item in arr:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            for k in ("fileUrl", "url", "path"):
                v = item.get(k)
                if isinstance(v, str) and v:
                    out.append(v)
                    break
    return out


def _runninghub_fail_reason(raw) -> str:
    if isinstance(raw, dict):
        return raw.get("msg") or raw.get("message") or str(raw)
    return str(raw)


def _resolve_size(width: int, height: int):
    return width, height


class RunningHubService:
    """RunningHub OpenAPI 调用。"""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.base_url = self.config.get("base_url") or RUNNINGHUB_DEFAULT_BASE_URL
        self.api_key = (self.config.get("api_key") or "").strip()
        self.wallet_api_key = (self.config.get("wallet_api_key") or "").strip()
        self.timeout = int(self.config.get("timeout") or RUNNINGHUB_RUN_TIMEOUT)

    # ── 同步便捷方法（供节点/步骤调用） ──────────────────────────────
    def run(
        self,
        entry_id: str,
        kind: str = "workflow",
        prompt: str = "",
        reference_images: list[str] | None = None,
        reference_video: str = "",
        node_info_list: list | None = None,
        callback=None,
        output_dir: str | None = None,
        width: int = 1024,
        height: int = 1024,
        aspect_ratio: str = "",
        num_images: int = 1,
    ) -> dict:
        """提交一个 RunningHub 工作流 / AI 应用任务并等待结果，产物直接下载到 output_dir。"""
        return asyncio.run(
            self.run_async(
                entry_id=entry_id,
                kind=kind,
                prompt=prompt,
                reference_images=reference_images,
                reference_video=reference_video,
                node_info_list=node_info_list,
                callback=callback,
                output_dir=output_dir,
                width=width,
                height=height,
                aspect_ratio=aspect_ratio,
                num_images=num_images,
            )
        )

    async def run_async(
        self,
        entry_id: str,
        kind: str = "workflow",
        prompt: str = "",
        reference_images: list[str] | None = None,
        reference_video: str = "",
        node_info_list: list | None = None,
        callback=None,
        output_dir: str | None = None,
        width: int = 1024,
        height: int = 1024,
        aspect_ratio: str = "",
        num_images: int = 1,
    ) -> dict:
        if not self.api_key and not self.wallet_api_key:
            raise AIGCError("未配置 RunningHub API Key，请在「其他能力接口」设置中填写")

        api_key = self.wallet_api_key or self.api_key
        timeout = httpx.Timeout(connect=20.0, read=1800.0, write=240.0, pool=20.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            # 多图上传：按 首帧/图片2/图片3/图片4/尾帧 顺序，组装 nodeInfoList 的 image 字段
            uploaded = []
            for ref in (reference_images or [])[:9]:
                fname = await self._upload_asset(client, ref)
                if fname:
                    uploaded.append(fname)

            # 参考视频上传：注入 nodeInfoList 的 video 字段
            video_name = ""
            if reference_video:
                video_name = await self._upload_asset(client, reference_video) or ""

            if node_info_list is None:
                node_info_list = []
            existing_fields = {str(item.get("fieldName")) for item in node_info_list if isinstance(item, dict)}

            def _append_field(field_name, value):
                if value in (None, ""):
                    return
                if field_name not in existing_fields:
                    node_info_list.append({"nodeId": "1", "fieldName": field_name, "fieldValue": value})
                    existing_fields.add(field_name)

            # 图片列表：first_frame / image2 / image3 / image4 / last_frame
            img_field_names = ["first_frame", "image2", "image3", "image4", "last_frame"]
            for idx, fname in enumerate(uploaded):
                _append_field(img_field_names[idx] if idx < len(img_field_names) else f"image{idx + 1}", fname)
            if uploaded:
                _append_field("images", ",".join(uploaded))
            if video_name:
                _append_field("video", video_name)

            # 提示词与通用参数
            if prompt:
                _append_field("prompt", prompt)
            _append_field("width", width)
            _append_field("height", height)
            if aspect_ratio:
                _append_field("aspect_ratio", aspect_ratio)
            if int(num_images or 1) > 1:
                _append_field("num_images", int(num_images))

            headers = _runninghub_headers(api_key)
            if kind == "workflow":
                submit_url = _runninghub_endpoint(self.base_url, "/task/openapi/create")
                body = {"apiKey": api_key, "workflowId": entry_id, "addMetadata": True}
                if node_info_list:
                    body["nodeInfoList"] = node_info_list
            else:
                submit_url = _runninghub_endpoint(self.base_url, "/task/openapi/ai-app/run")
                body = {"apiKey": api_key, "webappId": entry_id, "nodeInfoList": node_info_list}

            if callback:
                callback(20, "已提交 RunningHub 任务")

            try:
                resp = await client.post(submit_url, headers=headers, json=body)
                raw = resp.json()
            except Exception as e:
                raise AIGCError(f"RunningHub 提交失败：{e}") from e

            if not (isinstance(raw, dict) and str(raw.get("code")) in ("0", "0")):
                raise AIGCError(f"RunningHub 提交失败：{_runninghub_fail_reason(raw)}")

            task_id = (raw.get("data") or {}).get("taskId") if isinstance(raw.get("data"), dict) else ""
            if not task_id:
                raise AIGCError(f"RunningHub 未返回 taskId：{raw}")

            query_url = _runninghub_endpoint(self.base_url, "/task/openapi/outputs")
            deadline = time.monotonic() + self.timeout
            last_payload = None
            while time.monotonic() < deadline:
                await asyncio.sleep(2.5)
                try:
                    q_resp = await client.post(
                        query_url, headers=headers, json={"apiKey": api_key, "taskId": task_id}
                    )
                    query_raw = q_resp.json()
                except Exception as e:
                    print(f"RunningHub 查询失败（重试）：{e}")
                    continue
                last_payload = query_raw
                code = query_raw.get("code") if isinstance(query_raw, dict) else None
                if str(code) in ("0", "0"):
                    outputs = _runninghub_extract_outputs(query_raw.get("data"))
                    urls = [u for u in outputs if str(u).startswith(("http://", "https://", "/output/", "/assets/"))]
                    if not urls:
                        raise AIGCError(f"RunningHub 任务无图片输出：{query_raw}")
                    if callback:
                        callback(80, "RunningHub 任务完成，正在下载产物")
                    local = await self._download_outputs(client, urls, output_dir)
                    return local
                if str(code) in ("805", "805"):
                    raise AIGCError(f"RunningHub 任务失败：{_runninghub_fail_reason(query_raw)}")
                # 804 运行中 / 813 排队中 / 其他状态继续轮询
            raise AIGCError(f"RunningHub 任务超时：{last_payload}")

    async def _upload_asset(self, client: httpx.AsyncClient, image_path: str) -> str | None:
        """上传本地图片到 RunningHub，返回 fileName（供 nodeInfoList 引用）。"""
        if not image_path or not os.path.isfile(image_path):
            return None
        try:
            headers = _runninghub_headers(self.api_key or self.wallet_api_key)
            with open(image_path, "rb") as f:
                files = {"file": (os.path.basename(image_path), f.read())}
            resp = await client.post(
                _runninghub_endpoint(self.base_url, "/task/openapi/upload"), headers=headers, files=files
            )
            raw = resp.json()
            if isinstance(raw, dict) and str(raw.get("code")) in ("0", "0"):
                data = raw.get("data") or {}
                return data.get("fileName") or data.get("fileUrl")
        except Exception as e:
            print(f"RunningHub 上传素材失败：{e}")
        return None

    async def _download_outputs(self, client: httpx.AsyncClient, urls: list, output_dir: str | None = None) -> dict:
        out_dir = output_dir or self._output_dir()
        os.makedirs(out_dir, exist_ok=True)
        local_images, local_videos, local_files = [], [], []
        for idx, url in enumerate(urls):
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                ext = os.path.splitext(url.split("?")[0])[1].lower() or ".png"
                path = os.path.join(out_dir, f"rh_{int(time.time())}_{idx}{ext}")
                with open(path, "wb") as f:
                    f.write(r.content)
                if ext in (".mp4", ".webm", ".mov", ".mkv"):
                    local_videos.append(path)
                elif ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                    local_images.append(path)
                else:
                    local_files.append(path)
            except Exception as e:
                print(f"RunningHub 下载结果失败 {url}: {e}")
        return {"images": local_images, "videos": local_videos, "files": local_files, "items": local_images + local_videos + local_files, "urls": urls}

    def _output_dir(self) -> str:
        out = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tasks", "aigc_output")
        os.makedirs(out, exist_ok=True)
        return out

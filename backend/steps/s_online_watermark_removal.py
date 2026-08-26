"""s_online_watermark_removal: 在线去水印去字幕节点。

调用晴沐智坊 qmhub 在线服务去除视频中的水印/字幕。

Logic:
  1. 通过 auth 组件验证用户已注册登录软件
  2. 读取上游 url_json，提取视频 URL、时长、尺寸
  3. 若配置了 resume_request_id，直接跳到轮询阶段；否则提交新任务
  4. 按「视频时长/10 和 5 秒的最大值」间隔轮询，超时为「视频时长×5 和 120 秒的最大值」
  5. 下载去水印后的视频
  6. 生成任务执行信息 JSON（即使失败/超时也兜底记录）
  7. 输出视频文件和任务记录 JSON
"""
import json
import logging
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from backend.steps.base_step import BaseStep

logger = logging.getLogger(__name__)


class S_OnlineWatermarkRemoval(BaseStep):
    step_id = "s_online_watermark_removal"
    step_name = "在线去水印去字幕"
    dependencies = []
    artifacts = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        cache_dir = os.path.join(task_dir, "cache")
        video_path = os.path.join(cache_dir, f"watermark_removed_{node_id}.mp4")
        json_path = os.path.join(cache_dir, f"watermark_removed_{node_id}.json")
        return os.path.exists(video_path) and os.path.exists(json_path)

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    # ==================== 辅助方法 ====================

    @staticmethod
    def _read_url_json(task_dir: str, step_inputs: dict, node_config: dict) -> dict:
        """从上游 json 端口读取媒体信息 JSON。"""
        json_rel = step_inputs.get("url_json", "") or step_inputs.get("json", "") or ""
        if not json_rel:
            json_rel = node_config.get("json_path", "") or ""

        if not json_rel:
            raise FileNotFoundError(
                "未收到输入 JSON。请将「媒体转链接」节点的「媒体详情」端口连接到本节点的「url_json」输入。"
            )

        json_path = json_rel if os.path.isabs(json_rel) else os.path.join(task_dir, json_rel)
        if not os.path.isfile(json_path):
            raise FileNotFoundError(f"输入 JSON 文件不存在: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        url = data.get("url", "")
        if not url:
            raise ValueError("输入 JSON 中缺少 url 字段")

        meta = data.get("meta_data") or {}
        duration = meta.get("duration") or data.get("duration") or 0
        if not duration:
            raise ValueError("输入 JSON 中缺少时长信息（meta_data.duration），无法估算积分消耗")

        # 分段视频（媒体转链接节点分段上传）：解析 segments 列表
        segments = []
        if data.get("is_segmented") or data.get("segments"):
            for idx, seg in enumerate(data.get("segments") or []):
                if not isinstance(seg, dict):
                    continue
                seg_url = seg.get("url", "")
                seg_meta = seg.get("meta_data") or {}
                seg_duration = seg_meta.get("duration") or seg.get("duration") or 0
                if not seg_url or not seg_duration:
                    continue
                segments.append({
                    "index": seg.get("index", idx + 1),
                    "url": str(seg_url),
                    "duration": float(seg_duration),
                    "width": seg_meta.get("width") or 0,
                    "height": seg_meta.get("height") or 0,
                    "start": seg.get("start") or 0,
                    "end": seg.get("end") or 0,
                })

        # 分段时 duration 返回各段总时长（顶层的 meta_data.duration 仅为第一段时长）
        if segments:
            total_duration = sum(seg["duration"] for seg in segments)
            if total_duration > 0:
                duration = total_duration
            # 仅剩 1 个有效段时（其余段因 URL/时长无效被跳过），
            # 直接用该段的 url 与时长作为单段输入，避免顶层第一段 url 与总时长不匹配导致扣费错乱
            if len(segments) == 1:
                url = segments[0]["url"]
                duration = segments[0]["duration"]

        return {
            "url": str(url),
            "duration": float(duration),
            "width": meta.get("width") or 0,
            "height": meta.get("height") or 0,
            "segments": segments,
            "raw": data,
        }

    @staticmethod
    def _check_user_auth() -> dict:
        """通过 auth 组件验证用户已注册登录软件。返回登录信息。"""
        from backend.auth.cloud_auth_service import get_cloud_auth_service

        svc = get_cloud_auth_service()
        session = svc.get_session() or {}
        token = session.get("token") or ""
        username = (session.get("user_info") or {}).get("username") or ""

        if not token:
            raise RuntimeError("节点需要注册登录软件")

        return {"token": token, "username": username}

    @staticmethod
    def _build_qmhub_client():
        """构造 qmhub 客户端（自动管理 API Key）。"""
        from backend.qmhub.auth_helper import build_qmhub_client_with_retry

        return build_qmhub_client_with_retry()

    @staticmethod
    def _convert_regions_to_absolute(
        regions: list, width: int, height: int
    ) -> list[dict[str, int]]:
        """将前端归一化比例坐标（0-1）转换为绝对像素坐标。

        前端 region 格式: { start: [x_ratio, y_ratio], end: [x_ratio, y_ratio] }
        输出格式: { x1, y1, x2, y2 }（整数像素）
        """
        result = []
        for r in regions:
            if not isinstance(r, dict):
                continue
            start = r.get("start") or [0, 0]
            end = r.get("end") or [0, 0]
            x1_ratio = float(start[0]) if len(start) > 0 else 0
            y1_ratio = float(start[1]) if len(start) > 1 else 0
            x2_ratio = float(end[0]) if len(end) > 0 else 0
            y2_ratio = float(end[1]) if len(end) > 1 else 0

            x1 = int(round(min(x1_ratio, x2_ratio) * width)) if width else 0
            y1 = int(round(min(y1_ratio, y2_ratio) * height)) if height else 0
            x2 = int(round(max(x1_ratio, x2_ratio) * width)) if width else 0
            y2 = int(round(max(y1_ratio, y2_ratio) * height)) if height else 0
            result.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
        return result

    @staticmethod
    def _compute_poll_params(duration: float) -> tuple[int, int]:
        """根据视频时长推算轮询间隔和超时。

        轮询间隔 = max(5, duration / 10)
        超时 = max(120, duration * 5)
        """
        poll_interval = max(5, int(duration / 10))
        task_timeout = max(120, int(duration * 5))
        return poll_interval, task_timeout

    # 结果 URL 提取的优先键名
    _RESULT_URL_KEYS = (
        "result_url", "output_url", "video_url", "download_url",
        "file_url", "url", "media_url", "play_url",
    )

    @classmethod
    def _extract_result_url(cls, result_data: Any) -> str:
        """在任务结果中查找第一个可用的 http(s) URL。优先匹配已知键名。"""
        url_re = re.compile(r"^https?://", re.IGNORECASE)

        def _find_url(obj, depth=0):
            if depth > 6:
                return ""
            if isinstance(obj, str):
                return obj if url_re.match(obj) else ""
            if isinstance(obj, dict):
                for k in cls._RESULT_URL_KEYS:
                    v = obj.get(k)
                    if isinstance(v, str) and url_re.match(v):
                        return v
                for v in obj.values():
                    found = _find_url(v, depth + 1)
                    if found:
                        return found
            if isinstance(obj, (list, tuple)):
                for v in obj:
                    found = _find_url(v, depth + 1)
                    if found:
                        return found
            return ""

        if isinstance(result_data, (dict, list, tuple)):
            return _find_url(result_data)
        return ""

    @staticmethod
    def _download_video(result_url: str, video_path: str) -> None:
        """流式下载视频到本地。"""
        import requests

        with requests.get(result_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(video_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)

    @staticmethod
    def _concat_videos(segment_paths: list[str], output_path: str) -> None:
        """将多个视频段拼接为单个视频（ffmpeg concat demuxer，优先 -c copy）。"""
        if len(segment_paths) < 2:
            raise RuntimeError("拼接视频至少需要 2 段")

        concat_dir = os.path.dirname(output_path)
        os.makedirs(concat_dir, exist_ok=True)
        list_path = os.path.join(concat_dir, "concat_list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in segment_paths:
                # concat 列表中的路径用单引号包裹，Windows 下转正斜杠避免反斜杠转义问题
                normalized = p.replace("\\", "/")
                f.write(f"file '{normalized}'\n")

        # 方案 1：直接流复制拼接（各段编码一致时最快）
        cmd_copy = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            output_path,
        ]
        try:
            result = subprocess.run(cmd_copy, capture_output=True, text=True, timeout=1800)
        except FileNotFoundError:
            raise RuntimeError("未找到 ffmpeg，请确保已安装并添加到 PATH")
        except subprocess.TimeoutExpired:
            raise RuntimeError("ffmpeg 拼接视频超时（1800 秒）")

        if result.returncode == 0 and os.path.exists(output_path):
            return

        # 方案 2：重编码拼接（兼容编码不一致的分段）
        cmd_reencode = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]
        try:
            result2 = subprocess.run(cmd_reencode, capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            raise RuntimeError("ffmpeg 拼接视频超时（1800 秒）")
        if result2.returncode != 0 or not os.path.exists(output_path):
            error_msg = result2.stderr[-500:] if result2.stderr else "Unknown error"
            raise RuntimeError(f"ffmpeg 拼接视频失败: {error_msg}")

    def _save_task_record(
        self,
        cache_dir: str,
        node_id: str,
        record: dict[str, Any],
    ) -> str:
        """保存任务记录 JSON，返回文件相对路径。"""
        os.makedirs(cache_dir, exist_ok=True)
        json_filename = f"watermark_removed_{node_id}.json"
        json_path = os.path.join(cache_dir, json_filename)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        return f"cache/{json_filename}"

    # ==================== 多段并行处理 ====================

    @staticmethod
    def _seg_record_path(cache_dir: str, node_id: str, index: int) -> str:
        return os.path.join(cache_dir, f"watermark_removed_{node_id}_seg_{index}.json")

    def _process_single_segment(
        self,
        seg: dict,
        cache_dir: str,
        node_id: str,
        wm_mode: str,
        abs_regions: list,
        callback: Optional[Callable],
        cancel_callback: Optional[Callable],
        resume: bool = False,
    ) -> dict:
        """处理单个视频段：提交/查询 → 轮询 → 下载。返回该段结果 dict。

        每段使用独立 qmhub client（线程安全隔离）。
        resume=True 时优先读取该段已有记录中的 request_id 继续查询。
        """
        from backend.control_plane.runtime import TaskCancelledError

        seg_index = seg["index"]
        seg_url = seg["url"]
        seg_duration = seg["duration"]
        seg_poll_interval, seg_task_timeout = self._compute_poll_params(seg_duration)

        seg_video_path = os.path.join(cache_dir, f"watermark_removed_{node_id}_seg_{seg_index}.mp4")
        seg_record_path = self._seg_record_path(cache_dir, node_id, seg_index)
        seg_record: dict[str, Any] = {
            "node_id": node_id,
            "node_name": "在线去水印去字幕（分段）",
            "segment_index": seg_index,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input": {"url": seg_url, "duration": seg_duration},
            "watermark_regions": abs_regions if abs_regions else "全屏去除",
            "wm_mode": wm_mode,
            "status": "unknown",
            "request_id": None,
            "error": None,
        }

        client = self._build_qmhub_client()

        # ---------- 提交任务（或恢复已有任务） ----------
        resume_seg_id = ""
        if resume and os.path.isfile(seg_record_path):
            try:
                with open(seg_record_path, "r", encoding="utf-8") as f:
                    prev = json.load(f)
                resume_seg_id = str(prev.get("request_id") or "").strip()
            except Exception:
                resume_seg_id = ""

        request_id = ""
        submit_result = None
        task_id_val = ""

        if resume_seg_id:
            request_id = resume_seg_id
        else:
            try:
                invoke_params = {"mode": wm_mode}
                if abs_regions:
                    x1 = min(r["x1"] for r in abs_regions)
                    y1 = min(r["y1"] for r in abs_regions)
                    x2 = max(r["x2"] for r in abs_regions)
                    y2 = max(r["y2"] for r in abs_regions)
                    invoke_params.update({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
                submit_result = client.invoke.create(
                    slug="video-watermark-removal",
                    input_url=seg_url,
                    params=invoke_params,
                    duration_seconds=seg_duration,
                )
            except Exception as e:
                seg_record["status"] = "submit_failed"
                seg_record["error"] = str(e)
                self._save_seg_record(seg_record, seg_record_path)
                return {**seg_record, "index": seg_index, "exception": e}

            if isinstance(submit_result, dict):
                raw_request_id = (
                    submit_result.get("request_id")
                    or submit_result.get("requestId")
                    or ""
                )
                request_id = raw_request_id
                task_id_val = (
                    submit_result.get("task_id")
                    or submit_result.get("taskId")
                    or ""
                )
            if not request_id:
                seg_record["status"] = "submit_no_request_id"
                seg_record["error"] = f"提交后未获取到 request_id: {submit_result}"
                seg_record["submit_result"] = submit_result
                self._save_seg_record(seg_record, seg_record_path)
                return {**seg_record, "index": seg_index,
                        "exception": RuntimeError(seg_record["error"])}

            seg_record["task_id"] = str(task_id_val) if task_id_val else None
            seg_record["request_id"] = str(request_id)
            seg_record["submit_result"] = submit_result
            self._save_seg_record(seg_record, seg_record_path)

        seg_record["request_id"] = str(request_id)

        # ---------- 轮询任务状态 ----------
        start_time = time.time()
        last_status = ""
        poll_count = 0
        result_data = None
        error_exception = None

        while True:
            if cancel_callback and cancel_callback():
                error_exception = TaskCancelledError("用户取消任务")
                break
            elapsed = time.time() - start_time
            if elapsed >= seg_task_timeout:
                error_exception = TimeoutError(
                    f"去水印任务超时（{seg_task_timeout}s），request_id: {request_id}，最后状态: {last_status}"
                )
                break
            try:
                status_result = client.invoke.task_status(request_id=request_id)
            except Exception as e:
                if callback:
                    callback(35, f"分段{seg_index} 查询状态失败（将重试）: {e}")
                time.sleep(seg_poll_interval)
                continue

            if isinstance(status_result, dict):
                current_status = status_result.get("status") or status_result.get("state") or ""
            else:
                current_status = str(status_result)

            if current_status != last_status:
                last_status = current_status
                if callback:
                    callback(35, f"分段{seg_index} 任务状态: {current_status}（已等待 {int(elapsed)}s）")

            if current_status in ("completed", "succeeded", "success", "done"):
                result_data = status_result
                break
            if current_status in ("failed", "error", "canceled", "cancelled"):
                error_msg = ""
                if isinstance(status_result, dict):
                    error_msg = status_result.get("error") or status_result.get("message") or ""
                error_exception = RuntimeError(
                    f"分段{seg_index} 去水印任务失败（状态: {current_status}）: {error_msg or '未知错误'}"
                )
                break

            poll_count += 1
            time.sleep(seg_poll_interval)

        # ---------- 下载视频 ----------
        result_url = ""
        if result_data is not None and error_exception is None:
            result_url = self._extract_result_url(result_data)
            if not result_url:
                logger.warning(
                    "[online_watermark] 分段%s 未能从任务结果中提取到视频 URL，原始结果: %s",
                    seg_index,
                    json.dumps(result_data, ensure_ascii=False)[:2000]
                    if not isinstance(result_data, str) else result_data[:2000],
                )
                error_exception = RuntimeError(
                    f"分段{seg_index} 去水印任务成功，但返回结果中未找到视频 URL"
                )
            else:
                try:
                    self._download_video(result_url, seg_video_path)
                except Exception as e:
                    error_exception = RuntimeError(f"分段{seg_index} 下载去水印视频失败: {e}")
                    result_url = ""

        # ---------- 记录该段结果 ----------
        if error_exception is None:
            status_label = "completed"
        elif isinstance(error_exception, TaskCancelledError):
            status_label = "cancelled"
        elif isinstance(error_exception, TimeoutError):
            status_label = "timeout"
        else:
            status_label = "failed"

        seg_record.update({
            "status": status_label,
            "error": str(error_exception) if error_exception else None,
            "output": {
                "result_url": result_url,
                "video_file": f"cache/watermark_removed_{node_id}_seg_{seg_index}.mp4"
                if os.path.exists(seg_video_path) else None,
            },
            "cost": {
                "duration_seconds": seg_duration,
                "rate_per_second": 0.013,
                "estimated_cost_yuan": round(seg_duration * 0.013, 2),
                "billing_seconds": (result_data.get("billing_seconds") if isinstance(result_data, dict) else None),
                "fee_points": (result_data.get("fee") if isinstance(result_data, dict) else None),
            },
            "polling": {
                "interval_seconds": seg_poll_interval,
                "task_timeout_seconds": seg_task_timeout,
                "total_polls": poll_count,
                "total_wait_seconds": round(time.time() - start_time, 1),
                "final_status": last_status,
            },
            "raw_result": result_data if isinstance(result_data, dict) else ({"raw": str(result_data)} if result_data else None),
        })
        self._save_seg_record(seg_record, seg_record_path)

        return {
            "index": seg_index,
            "request_id": str(request_id) if request_id else None,
            "status": status_label,
            "exception": error_exception,
            "result_url": result_url,
            "video_path": seg_video_path,
            "duration": seg_duration,
            "cost_yuan": round(seg_duration * 0.013, 2),
            "record": seg_record,
        }

    def _save_seg_record(self, record: dict, seg_record_path: str) -> None:
        os.makedirs(os.path.dirname(seg_record_path), exist_ok=True)
        with open(seg_record_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    @classmethod
    def _scan_seg_records(cls, cache_dir: str, node_id: str) -> list[dict]:
        """从 cache 目录扫描该节点的分段任务记录，返回按 index 排序的分段信息列表。

        用于 resume（继续查询）模式下上游 JSON 不可用时恢复各段任务。
        返回 [] 表示没有找到任何分段记录。
        """
        seg_records = []
        try:
            files = [
                fn for fn in os.listdir(cache_dir)
                if re.match(rf"^watermark_removed_{re.escape(node_id)}_seg_(\d+)\.json$", fn)
            ]
        except Exception:
            return []
        for fn in files:
            m = re.match(rf"^watermark_removed_{re.escape(node_id)}_seg_(\d+)\.json$", fn)
            if not m:
                continue
            idx = int(m.group(1))
            try:
                with open(os.path.join(cache_dir, fn), "r", encoding="utf-8") as f:
                    record = json.load(f)
            except Exception:
                continue
            req_id = str(record.get("request_id") or "").strip()
            seg_url = ((record.get("input") or {}).get("url") or "").strip()
            if not req_id:
                continue
            seg_records.append({
                "index": idx,
                "url": seg_url,
                "duration": float((record.get("input") or {}).get("duration") or 0),
                "width": 0,
                "height": 0,
                "start": 0,
                "end": 0,
                "from_record": True,
            })
        seg_records.sort(key=lambda s: s["index"])
        return seg_records

    def _run_multi_segments(
        self,
        task_dir: str,
        cache_dir: str,
        node_id: str,
        node_config: dict,
        media_info: dict,
        segments: list,
        wm_mode: str,
        abs_regions: list,
        callback: Optional[Callable],
        cancel_callback: Optional[Callable],
        resume: bool = False,
    ) -> dict:
        """多段并行提交去水印任务，全部完成后拼接为输出视频。"""
        from backend.control_plane.runtime import TaskCancelledError

        video_filename = f"watermark_removed_{node_id}.mp4"
        video_path = os.path.join(cache_dir, video_filename)

        total_duration = sum(seg["duration"] for seg in segments)
        cost_yuan = round(total_duration * 0.013, 2)
        if callback:
            callback(15, f"检测到 {len(segments)} 段视频，总时长 {total_duration:.1f}s，并行提交去水印任务...")

        max_workers = min(len(segments), 3)
        seg_results = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    self._process_single_segment,
                    seg, cache_dir, node_id, wm_mode, abs_regions,
                    callback, cancel_callback, resume,
                ): seg
                for seg in segments
            }
            done_count = 0
            for future in as_completed(futures):
                try:
                    seg_results.append(future.result())
                except Exception as e:
                    seg_results.append({
                        "index": futures[future]["index"],
                        "status": "failed",
                        "exception": e,
                        "record": {},
                    })
                done_count += 1
                if callback:
                    callback(30 + int(50 * done_count / len(segments)),
                             f"分段处理进度: {done_count}/{len(segments)}")

        seg_results.sort(key=lambda r: r.get("index", 0))

        # ---------- 检查是否全部成功 ----------
        failed = [r for r in seg_results if r.get("status") != "completed"]
        if failed:
            first_err = failed[0].get("exception")
            err_msg = (
                f"分段 {', '.join(str(r['index']) for r in failed)} 处理失败: "
                f"{first_err}"
            )
            raise RuntimeError(err_msg) from (first_err if isinstance(first_err, BaseException) else None)

        # ---------- 拼接视频 ----------
        if callback:
            callback(85, "全部段落处理完成，开始拼接视频...")
        segment_videos = [r["video_path"] for r in seg_results]
        try:
            self._concat_videos(segment_videos, video_path)
        except Exception as e:
            raise RuntimeError(f"拼接分段视频失败: {e}") from e

        if callback:
            callback(92, f"拼接完成，输出视频: {video_filename}")

        # ---------- 生成任务记录 JSON ----------
        status_label = "completed"
        task_record: dict[str, Any] = {
            "node_id": node_id,
            "node_name": "在线去水印去字幕",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status_label,
            "error": None,
            "is_segmented": True,
            "segment_count": len(seg_results),
            "input": {
                "source_url": media_info.get("url", ""),
                "duration": total_duration,
                "width": media_info.get("width") or 0,
                "height": media_info.get("height") or 0,
            },
            "watermark_regions": abs_regions if abs_regions else "全屏去除",
            "wm_mode": wm_mode,
            "cost": {
                "duration_seconds": total_duration,
                "rate_per_second": 0.013,
                "estimated_cost_yuan": cost_yuan,
            },
            "output": {
                "result_url": None,
                "video_file": f"cache/{video_filename}",
            },
            "segments": [],
        }
        for r in seg_results:
            task_record["segments"].append({
                "index": r.get("index"),
                "request_id": r.get("request_id"),
                "status": r.get("status"),
                "result_url": r.get("result_url"),
                "video_file": r.get("video_path"),
                "duration": r.get("duration"),
                "cost_yuan": r.get("cost_yuan"),
            })

        json_rel = self._save_task_record(cache_dir, node_id, task_record)

        if callback:
            callback(100, "去水印任务完成（多段拼接）")

        return {
            "artifacts": [f"cache/{video_filename}", json_rel],
            "outputs": {
                "video": f"cache/{video_filename}",
                "json": json_rel,
            },
        }

    # ==================== 主流程 ====================

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        from backend.control_plane.runtime import TaskCancelledError

        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        video_filename = f"watermark_removed_{node_id}.mp4"
        video_path = os.path.join(cache_dir, video_filename)

        # 兜底记录的公共字段
        base_record: dict[str, Any] = {
            "node_id": node_id,
            "node_name": "在线去水印去字幕",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": None,
            "status": "unknown",
            "error": None,
        }

        # ========== 阶段 1：验证用户登录 ==========
        if callback:
            callback(2, "验证用户注册登录状态...")
        auth_info = self._check_user_auth()
        if callback:
            callback(5, f"用户已登录: {auth_info['username'] or '已认证'}")

        # 是否为「继续查询上次任务」模式（提前读取，便于后续阶段容错）
        # 支持两种值：
        #   - 实际 request_id 字符串（如 "12345"）：直接使用
        #   - "auto"：从上次任务的 cache JSON 中自动提取 request_id
        resume_request_id = node_config.get("resume_request_id", "")
        resume_request_id = str(resume_request_id).strip() if resume_request_id else ""

        if resume_request_id == "auto":
            json_path = os.path.join(cache_dir, f"watermark_removed_{node_id}.json")
            if os.path.isfile(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as _f:
                        _prev = json.load(_f)
                    _sr = _prev.get("submit_result") or {}
                    # 仅取 request_id（整数），不回退到 task_id（哈希字符串，
                    # qmhub task_status 接口要求路径段为整数）。
                    _raw_id = (
                        _sr.get("request_id")
                        or _sr.get("requestId")
                        or _prev.get("request_id")
                        or ""
                    )
                    # 校验为有效整数
                    try:
                        int(_raw_id)
                        resume_request_id = str(_raw_id).strip()
                    except (ValueError, TypeError):
                        resume_request_id = ""
                    if resume_request_id and callback:
                        callback(6, f"自动读取上次 request_id: {resume_request_id}")
                except Exception:
                    resume_request_id = ""
            else:
                resume_request_id = ""

        # ========== 阶段 2：读取输入 JSON ==========
        if callback:
            callback(8, "读取输入媒体信息...")
        media_info = None
        try:
            media_info = self._read_url_json(task_dir, step_inputs, node_config)
            url = media_info["url"]
            duration = media_info["duration"]
            width = media_info["width"]
            height = media_info["height"]
        except Exception:
            # resume 模式下上游 url_json 可能不存在/不可用，仅用于记录与费用预估，
            # 读取失败时回退到保守默认值，不阻断「继续查询 + 下载」流程。
            if resume_request_id:
                if callback:
                    callback(9, "resume 模式：未读取到上游媒体信息，使用默认值继续查询")
                url, duration, width, height = "", 30, 0, 0
            else:
                raise

        # resume 模式下若上游 JSON 不可用，尝试从分段任务记录恢复各段
        if media_info is None and resume_request_id:
            seg_records = self._scan_seg_records(cache_dir, node_id)
            if seg_records:
                if callback:
                    callback(10, f"从分段任务记录恢复 {len(seg_records)} 段任务...")
                media_info = {
                    "url": "",
                    "duration": sum(s["duration"] for s in seg_records),
                    "width": 0,
                    "height": 0,
                    "segments": seg_records,
                    "raw": {},
                }
                duration = media_info["duration"]

        cost_yuan = round(duration * 0.013, 2)
        if callback:
            callback(12, f"视频时长 {duration:.1f}s，预估消耗约 {cost_yuan} 元（1.3分/秒，不足10秒按10秒计）")

        # 推算轮询参数
        poll_interval, task_timeout = self._compute_poll_params(duration)
        if callback:
            callback(15, f"轮询间隔 {poll_interval}s，超时 {task_timeout}s")

        # 读取水印区域配置
        raw_regions = node_config.get("watermark_regions", [])
        if not isinstance(raw_regions, list):
            raw_regions = []
        abs_regions = self._convert_regions_to_absolute(raw_regions, width, height) if raw_regions else []

        # 读取去水印模式（normal: 普通模式 / protect: 保护模式）
        wm_mode = node_config.get("wm_mode", "normal")
        if wm_mode not in ("normal", "protect"):
            wm_mode = "normal"

        # ========== 多段模式：并行提交 + 全部完成后拼接 ==========
        segments = (media_info or {}).get("segments") or []
        if len(segments) > 1:
            if callback:
                callback(14, f"上游视频已分段（{len(segments)} 段），进入多段并行处理")
            return self._run_multi_segments(
                task_dir, cache_dir, node_id, node_config,
                media_info, segments, wm_mode, abs_regions,
                callback, cancel_callback,
                resume=bool(resume_request_id),
            )

        base_record["input"] = {
            "source_url": url,
            "duration": duration,
            "width": width,
            "height": height,
        }
        base_record["watermark_regions"] = abs_regions if abs_regions else "全屏去除"
        base_record["wm_mode"] = wm_mode

        # ========== 阶段 3：提交任务 或 继续查询 ==========
        request_id = None
        submit_result = None
        client = self._build_qmhub_client()

        if resume_request_id:
            if callback:
                callback(20, f"继续查询上次任务，request_id: {resume_request_id}")
            request_id = resume_request_id
        else:
            if callback:
                if abs_regions:
                    callback(20, f"提交去水印任务（指定 {len(abs_regions)} 个水印区域）...")
                else:
                    callback(20, "提交去水印任务（全屏去除模式）...")

            try:
                invoke_params = {"mode": wm_mode}
                if abs_regions:
                    x1 = min(r["x1"] for r in abs_regions)
                    y1 = min(r["y1"] for r in abs_regions)
                    x2 = max(r["x2"] for r in abs_regions)
                    y2 = max(r["y2"] for r in abs_regions)
                    invoke_params.update({"x1": x1, "y1": y1, "x2": x2, "y2": y2})

                submit_result = client.invoke.create(
                    slug="video-watermark-removal",
                    input_url=url,
                    params=invoke_params,
                    duration_seconds=duration,
                )
            except Exception as e:
                base_record["status"] = "submit_failed"
                base_record["error"] = str(e)
                base_record["submit_exception"] = str(e)
                self._save_task_record(cache_dir, node_id, base_record)
                raise RuntimeError(f"提交去水印任务失败: {e}") from e

            if isinstance(submit_result, dict):
                # qmhub 的 task_status 接口路径为 /api/capability/tasks/{request_id}，
                # 路径段是整数 request_id（服务端 pydantic 校验为 int）；
                # task_id 是任务哈希字符串，不能直接用于该路径，否则会触发
                # "path -> request_id: Input should be a valid integer"。
                # 因此 task_status 查询/轮询必须用 request_id，task_id 仅作记录。
                raw_request_id = (
                    submit_result.get("request_id")
                    or submit_result.get("requestId")
                    or ""
                )
                request_id = raw_request_id
                task_id_val = (
                    submit_result.get("task_id")
                    or submit_result.get("taskId")
                    or ""
                )
            else:
                task_id_val = ""
                raw_request_id = ""
            if not request_id:
                base_record["status"] = "submit_no_request_id"
                base_record["error"] = f"提交后未获取到 task_id: {submit_result}"
                base_record["submit_result"] = submit_result
                self._save_task_record(cache_dir, node_id, base_record)
                raise RuntimeError(base_record["error"])

            base_record["task_id"] = str(task_id_val) if task_id_val else None
            base_record["request_id"] = str(raw_request_id) if raw_request_id else None
            base_record["submit_result"] = submit_result
            if callback:
                callback(25, f"任务已提交，request_id: {request_id}")

        # ========== 阶段 4：轮询任务状态 ==========
        if callback:
            callback(30, f"等待任务完成，每 {poll_interval}s 查询一次...")

        start_time = time.time()
        last_status = ""
        poll_count = 0
        result_data = None
        error_exception = None

        while True:
            if cancel_callback and cancel_callback():
                error_exception = TaskCancelledError("用户取消任务")
                break

            elapsed = time.time() - start_time
            if elapsed >= task_timeout:
                error_exception = TimeoutError(
                    f"去水印任务超时（{task_timeout}s），request_id: {request_id}，最后状态: {last_status}"
                )
                break

            try:
                status_result = client.invoke.task_status(request_id=request_id)
            except Exception as e:
                if callback:
                    callback(35, f"查询状态失败（将重试）: {e}")
                time.sleep(poll_interval)
                continue

            if isinstance(status_result, dict):
                current_status = status_result.get("status") or status_result.get("state") or ""
            else:
                current_status = str(status_result)

            if current_status != last_status:
                last_status = current_status
                progress = min(85, 30 + poll_count * 2)
                if callback:
                    callback(progress, f"任务状态: {current_status}（已等待 {int(elapsed)}s）")

            # 完成
            if current_status in ("completed", "succeeded", "success", "done"):
                result_data = status_result
                break

            # 失败
            if current_status in ("failed", "error", "canceled", "cancelled"):
                error_msg = ""
                if isinstance(status_result, dict):
                    error_msg = status_result.get("error") or status_result.get("message") or ""
                error_exception = RuntimeError(
                    f"去水印任务失败（状态: {current_status}）: {error_msg or '未知错误'}"
                )
                break

            poll_count += 1
            time.sleep(poll_interval)

        # ========== 阶段 5：下载视频（仅在成功时） ==========
        result_url = ""
        if result_data is not None and error_exception is None:
            result_url = self._extract_result_url(result_data)

            if not result_url:
                logger.warning(
                    "[online_watermark] 未能从任务结果中提取到视频 URL，"
                    "原始结果: %s", json.dumps(result_data, ensure_ascii=False)[:2000]
                    if not isinstance(result_data, str) else result_data[:2000]
                )
                error_exception = RuntimeError(
                    "去水印任务成功，但返回结果中未找到视频 URL，请查看任务记录 JSON 的 raw_result 字段"
                )
            else:
                if callback:
                    callback(88, "去水印完成，开始下载视频...")

            try:
                self._download_video(result_url, video_path)
            except Exception as e:
                error_exception = RuntimeError(f"下载去水印视频失败: {e}")
                result_url = ""

        # ========== 阶段 6：生成任务记录 JSON（兜底：即使失败也记录） ==========
        if error_exception is None:
            status_label = "completed"
        elif isinstance(error_exception, TaskCancelledError):
            status_label = "cancelled"
        elif isinstance(error_exception, TimeoutError):
            status_label = "timeout"
        else:
            status_label = "failed"

        task_record = {
            **base_record,
            "status": status_label,
            "request_id": str(request_id) if request_id else None,
            "error": str(error_exception) if error_exception else None,
            "input": {
                "source_url": url,
                "duration": duration,
                "width": width,
                "height": height,
            },
            "watermark_regions": abs_regions if abs_regions else "全屏去除",
            "output": {
                "result_url": result_url,
                "video_file": f"cache/{video_filename}" if os.path.exists(video_path) else None,
            },
            "cost": {
                "duration_seconds": duration,
                "rate_per_second": 0.013,
                "estimated_cost_yuan": cost_yuan,
                # 以下为云端返回的实际计费信息（仅成功时有值，扣费由云端处理）
                "billing_seconds": (result_data.get("billing_seconds") if isinstance(result_data, dict) else None),
                "fee_points": (result_data.get("fee") if isinstance(result_data, dict) else None),
                "actual_cost_yuan": (
                    round(result_data.get("fee", 0) / 100, 2)
                    if isinstance(result_data, dict) and result_data.get("fee") is not None
                    else None
                ),
            },
            "polling": {
                "interval_seconds": poll_interval,
                "task_timeout_seconds": task_timeout,
                "total_polls": poll_count,
                "total_wait_seconds": round(time.time() - start_time, 1),
                "final_status": last_status,
            },
            "submit_result": submit_result,
            "raw_result": result_data if isinstance(result_data, dict) else ({"raw": str(result_data)} if result_data else None),
        }

        json_rel = self._save_task_record(cache_dir, node_id, task_record)

        # 如果有异常，在记录保存后抛出
        if error_exception is not None:
            raise error_exception

        if callback:
            callback(95, "视频下载完成，任务记录已保存")
            callback(100, "去水印任务完成")

        return {
            "artifacts": [f"cache/{video_filename}", json_rel],
            "outputs": {
                "video": f"cache/{video_filename}",
                "json": json_rel,
            },
        }


StepOnlineWatermarkRemoval = S_OnlineWatermarkRemoval

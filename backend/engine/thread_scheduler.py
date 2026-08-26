"""Thread scheduler: manages async multi-task execution via ThreadPoolExecutor.
Each task gets an isolated environment folder with standardized artifacts.
"""
import os
import json
import time
import uuid
import shutil
import threading
import traceback
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Optional

from backend.config.builtin_node_types import get_builtin_node_types, is_builtin_node_type_deleted


TASKS_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tasks"
)
os.makedirs(TASKS_ROOT, exist_ok=True)

NODE_TYPES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "node_types",
)

BUILTIN_STEP_REGISTRY = {
    "platform_download": ("backend.steps.s00_platform_download", "S00PlatformDownload"),
    "asr": ("backend.steps.s02_asr", "S02ASR"),
    "sentence_split": ("backend.steps.s03_sentence_split", "S03SentenceSplit"),
    "sentence_preprocess": ("backend.steps.s_sentence_preprocess", "S_SentencePreprocess"),
    "summarize": ("backend.steps.s04_summarize", "S04Summarize"),
    "translate": ("backend.steps.s05_translate", "S05Translate"),
    "subtitle_gen": ("backend.steps.s06_subtitle_gen", "S06SubtitleGen"),
    "merge_sub_video": ("backend.steps.s07_merge_sub_video", "S07MergeSubVideo"),
    "dub_task": ("backend.steps.s08_dub_task", "S08DubTask"),
    "tts": ("backend.steps.s09_tts", "S09TTS"),
    "merge_audio": ("backend.steps.s10_merge_audio", "S10MergeAudio"),
    "merge_dub": ("backend.steps.s_merge_dub", "S_MergeDub"),
    "merge_dub_video": ("backend.steps.s11_merge_dub_video", "S11MergeDubVideo"),
    "cover": ("backend.steps.s12_cover", "S12Cover"),
    "watermark": ("backend.steps.s13_watermark", "S13Watermark"),
    "output": ("backend.steps.s14_output", "StepOutput"),
    "extract_audio": ("backend.steps.s15_extract_audio", "StepExtractAudio"),
    "audio_transcode": ("backend.steps.s18_audio_transcode", "StepAudioTranscode"),
    "audio_denoise": ("backend.steps.s_audio_denoise", "StepAudioDenoise"),
    "vocal_separation": ("backend.steps.s16_vocal_separation", "StepVocalSeparation"),
    "subtitle_align": ("backend.steps.s07_subtitle_align", "S07SubtitleAlign"),
    "llm_request": ("backend.steps.s_llm_request", "S_LLMRequest"),
    "http_request": ("backend.steps.s_http_request", "S_HttpRequest"),
    "pi_agent": ("backend.steps.s_pi_agent", "S_PiAgent"),
    "image_gen": ("backend.steps.s_imagegen", "S_ImageGen"),
    "video_frame_extract": ("backend.steps.s_video_frame_extract", "S_VideoFrameExtract"),
    "subtitle_position_search": ("backend.steps.s_subtitle_position_search", "S_SubtitlePositionSearch"),
    "subtitle_recognition": ("backend.steps.s_subtitle_recognition", "S_SubtitleRecognition"),
    "video_publish": ("backend.steps.s_video_publish", "S_VideoPublish"),
    "resolve_path": ("backend.steps.s_resolve_path", "S_ResolvePath"),
    "translate_task_name": ("backend.steps.s_translate_task_name", "S_TranslateTaskName"),
    "json_to_text": ("backend.steps.s_json_to_text", "S_JsonToText"),
    "json_editor": ("backend.steps.s_json_editor", "S_JsonEditor"),
    "json_visual_editor": ("backend.steps.s_json_visual_editor", "S_JsonVisualEditor"),
    "text_editor": ("backend.steps.s_text_editor", "S_TextEditor"),
    "subtitle_editor": ("backend.steps.s_subtitle_editor", "S_SubtitleEditor"),
    "video_split": ("backend.steps.s_video_split", "S_VideoSplit"),
    "path_to_title": ("backend.steps.s_path_to_title", "S_PathToTitle"),
    "track_separation": ("backend.steps.s17_track_separation", "S17TrackSeparation"),
    "file_rename": ("backend.steps.s_file_rename", "S_FileRename"),
    "timed_delay": ("backend.steps.s_timed_delay", "S_TimedDelay"),
    "run_wait": ("backend.steps.s_run_wait", "S_RunWait"),
    "editor_agent": ("backend.steps.s_editor_agent", "S_EditorAgent"),
    "cutia": ("backend.steps.s_cutia", "S_Cutia"),
    "aigc_comfyui": ("backend.steps.s_aigc_comfyui", "S_AIGC_ComfyUI"),
    "aigc_runninghub": ("backend.steps.s_aigc_runninghub", "S_AIGC_RunningHub"),
    "aigc_jimeng": ("backend.steps.s_aigc_jimeng", "S_AIGC_Jimeng"),
    "media_to_url": ("backend.steps.s_media_to_url", "S_MediaToUrl"),
    "online_watermark_removal": ("backend.steps.s_online_watermark_removal", "S_OnlineWatermarkRemoval"),
    "qm_virtual_mailbox": ("backend.steps.s_qm_virtual_mailbox", "S_QmVirtualMailbox"),
}

FRONTEND_ONLY_NODE_TYPES = {"video_preview", "image_preview"}

# 需要在独立子进程中执行的重型节点。
# 这些步骤会加载大模型并做长时间推理（whisperx 对齐、pyannote 说话人识别、
# funasr VAD、demucs 分离等），在同一进程内会长时间占用 GIL，
# 饿死单进程 uvicorn 的事件循环线程，导致前端无法与后端通信。
PROCESS_ISOLATED_NODE_TYPES = {"asr", "vocal_separation", "track_separation", "http_request"}
BUILTIN_NODE_OUTPUT_IDS = {
    node["id"]: [output.get("id") for output in node.get("outputs", []) if output.get("id")]
    for node in get_builtin_node_types()
}


class TaskCancelledError(Exception):
    """Raised when a running task is cancelled by user request."""


class WorkflowWaitingError(Exception):
    def __init__(self, message, workbench_url):
        self.workbench_url = workbench_url
        super().__init__(message)


class ThreadScheduler:
    def __init__(self, max_workers: int = 3):
        self._max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._running = {}
        self._cancel_flags = {}
        self._active_processes = {}
        self._lock = threading.Lock()

    def submit(self, task_id, fn, *args, **kwargs):
        future = self.executor.submit(fn, *args, **kwargs)
        with self._lock:
            self._running[task_id] = future
        def _cleanup(f):
            with self._lock:
                self._running.pop(task_id, None)
        future.add_done_callback(_cleanup)
        return future

    def reset_executor(self, max_workers=None):
        """Replace the ThreadPoolExecutor with a fresh one.
        
        Old stuck workers are abandoned (they'll finish naturally or be GC'd).
        Running tasks tracked in _running that belong to the old pool are cleaned up.
        """
        new_max = max_workers or self._max_workers
        with self._lock:
            old = self.executor
            self.executor = ThreadPoolExecutor(max_workers=new_max)
            self._max_workers = new_max
            # Clear references to futures from the old pool
            stuck_count = sum(1 for f in self._running.values() if not f.done())
            self._running.clear()
        print(f"[Scheduler] Thread pool reset: {new_max} workers (cleared {stuck_count} stale future(s))")

    def get_pool_status(self):
        """Return pool health info for diagnostics."""
        with self._lock:
            total = len(self._running)
            running = sum(1 for f in self._running.values() if not f.done())
            max_w = self._max_workers
        return {
            "max_workers": max_w,
            "tracked_tasks": total,
            "active_tasks": running,
            "available_workers": max(0, max_w - running),
        }

    def is_running(self, task_id):
        with self._lock:
            f = self._running.get(task_id)
            return f is not None and not f.done()

    def request_cancel(self, task_id):
        with self._lock:
            flag = self._cancel_flags.setdefault(task_id, threading.Event())
            flag.set()
            proc = self._active_processes.get(task_id)
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
        return True

    def _is_cancel_requested(self, task_id):
        with self._lock:
            flag = self._cancel_flags.get(task_id)
            return bool(flag and flag.is_set())

    def _clear_cancel_request(self, task_id):
        with self._lock:
            flag = self._cancel_flags.get(task_id)
            if flag:
                flag.clear()

    def _register_process(self, task_id, process):
        with self._lock:
            self._active_processes[task_id] = process

    def _unregister_process(self, task_id, process=None):
        with self._lock:
            current = self._active_processes.get(task_id)
            if process is None or current is process:
                self._active_processes.pop(task_id, None)

    def _raise_if_cancelled(self, task_id):
        if self._is_cancel_requested(task_id):
            raise TaskCancelledError("Cancelled by user")

    def _mark_task_cancelled(self, task_json_path, message="Cancelled by user", step_id=None):
        try:
            with open(task_json_path, "r", encoding="utf-8") as f:
                task_info = json.load(f)
        except Exception:
            return

        changed_nodes = []
        for nid, node_info in task_info.get("nodes", {}).items():
            current_status = node_info.get("status", "")
            if current_status == "completed":
                continue  # Keep completed nodes as-is
            if current_status in ("running", "streaming") or nid == step_id:
                # Running/streaming nodes → cancelled
                # Current-step pending node → cancelled (user specifically stopped this step)
                node_info["status"] = "cancelled"
                node_info["message"] = "Cancelled by user"
                node_info["error"] = "Cancelled"
                node_info["progress"] = -1
                changed_nodes.append(nid)
            # Other pending nodes remain unchanged

        task_info["status"] = "cancelled"
        task_info["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._write_json(task_json_path, task_info)

        for nid in changed_nodes:
            ns = task_info["nodes"][nid]
            self._log(task_info.get("id", ""), nid, ns.get("progress", 0), ns.get("message", ""), {"status": ns["status"]})
        self._log(task_info.get("id", ""), "__task__", -1, message, {"status": "cancelled"})

    def _build_node_state(self, node):
        return {
            "nodeType": node.get("data", {}).get("nodeType", ""),
            "label": node.get("data", {}).get("label", ""),
            "status": "pending",
            "progress": 0,
            "message": "",
            "inputs": {},
            "outputs": {},
            "error": "",
        }

    def _copy_input_files(self, task_dir, input_config):
        cache_dir = os.path.join(task_dir, "cache")
        for key in ["video", "audio", "subtitle"]:
            fp = input_config.get(key + "Path", "")
            if fp and os.path.exists(fp):
                ext = os.path.splitext(fp)[1]
                shutil.copy2(fp, os.path.join(cache_dir, "input_" + key + ext))

    def _reset_task_workspace(self, task_dir, input_config):
        cache_dir = os.path.join(task_dir, "cache")
        output_dir = os.path.join(task_dir, "output")
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(cache_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        self._copy_input_files(task_dir, input_config)

    def _collect_downstream_nodes(self, edges, start_node_id):
        downstream = set()
        queue = [start_node_id]
        while queue:
            current = queue.pop(0)
            if current in downstream:
                continue
            downstream.add(current)
            for edge in edges:
                if edge.get("source") == current:
                    target = edge.get("target", "")
                    if target and target not in downstream:
                        queue.append(target)
        return downstream

    def create_task_env(self, workflow, input_config, task_id=None, task_name=None, batch_id=None):
        task_id = task_id or uuid.uuid4().hex[:12]
        task_dir = os.path.join(TASKS_ROOT, task_id)
        os.makedirs(os.path.join(task_dir, "cache"), exist_ok=True)
        os.makedirs(os.path.join(task_dir, "output"), exist_ok=True)

        # Update input node's source_language/target_language from input_config
        # so that downstream steps reading workflow.json directly get the right values.
        for node in workflow.get("nodes", []):
            if node.get("data", {}).get("nodeType") == "input":
                cfg = node.setdefault("data", {}).setdefault("config", {})
                if "source_language" in input_config:
                    cfg["source_language"] = input_config["source_language"]
                if "target_language" in input_config:
                    cfg["target_language"] = input_config["target_language"]
                break

        with open(os.path.join(task_dir, "workflow.json"), "w", encoding="utf-8") as f:
            json.dump(workflow, f, ensure_ascii=False, indent=2)

        nodes_status = {}
        for node in workflow.get("nodes", []):
            nid = node.get("id", "")
            nodes_status[nid] = self._build_node_state(node)

        task_info = {
            "id": task_id,
            "task_name": task_name or task_id,
            "workflow_id": workflow.get("id", ""),
            "batch_id": batch_id or "",
            "status": "created",
            "input": input_config,
            "nodes": nodes_status, "edges": workflow.get("edges", []),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "started_at": None, "finished_at": None,
        }
        with open(os.path.join(task_dir, "task.json"), "w", encoding="utf-8") as f:
            json.dump(task_info, f, ensure_ascii=False, indent=2)

        self._copy_input_files(task_dir, input_config)

        return task_id

    def resume_task(self, task_id, workflow, resume_from_node=None, custom_dir=None, input_config=None):
        """Resume a task: keep completed nodes, reset all non-completed nodes to pending.
        Input nodes are always skipped (not executed)."""
        task_dir = custom_dir or os.path.join(TASKS_ROOT, task_id)
        task_json_path = os.path.join(task_dir, "task.json")

        try:
            with open(task_json_path, "r", encoding="utf-8") as f:
                task_info = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError(f"Task {task_id} has corrupted task.json, cannot resume")
        except FileNotFoundError:
            raise FileNotFoundError(f"Task {task_id} not found at {task_dir}")

        # Update input config from frontend (merge with existing to preserve workflow-level keys)
        if input_config:
            old_input = task_info.get("input", {})
            merged_input = {**old_input, **input_config}
            for key in ("copyInputs", "var1", "var2", "var1Required", "var2Required"):
                if key in old_input and key not in input_config:
                    merged_input[key] = old_input[key]
            task_info["input"] = merged_input

        # Sync input node config from task.json into workflow before writing
        # This ensures the cleaned workflow (with empty input paths) gets the
        # correct paths from task.json, so _exec_input_node won't clear them.
        ic = task_info.get("input", {})
        for node in workflow.get("nodes", []):
            if node.get("data", {}).get("nodeType") == "input":
                cfg = node.setdefault("data", {}).setdefault("config", {})
                # Sync file paths
                for key in ("videoPath", "audioPath", "subtitlePath", "url",
                            "source_language", "target_language"):
                    if ic.get(key):
                        cfg[key] = ic[key]
                break

        # Update workflow.json with potentially new workflow
        with open(os.path.join(task_dir, "workflow.json"), "w", encoding="utf-8") as f:
            json.dump(workflow, f, ensure_ascii=False, indent=2)

        reset_nodes = self._collect_downstream_nodes(workflow.get("edges", []), resume_from_node) if resume_from_node else set()

        # Keep completed nodes as-is, reset all others to pending
        nodes = workflow.get("nodes", [])
        for node in nodes:
            nid = node.get("id", "")
            if nid not in task_info.get("nodes", {}):
                # New node not in previous task
                task_info["nodes"][nid] = self._build_node_state(node)
            elif nid in reset_nodes or task_info["nodes"][nid].get("status") != "completed":
                # Non-completed node or explicit resume target/downstream: reset to pending
                task_info["nodes"][nid]["status"] = "pending"
                task_info["nodes"][nid]["progress"] = 0
                task_info["nodes"][nid]["message"] = ""
                task_info["nodes"][nid]["outputs"] = {}
                task_info["nodes"][nid]["error"] = ""
            # else: completed node stays completed

        task_info["edges"] = workflow.get("edges", [])
        task_info["workflow_id"] = workflow.get("id", task_info.get("workflow_id", ""))
        task_info["status"] = "created"
        task_info["started_at"] = None
        task_info["finished_at"] = None
        self._write_json(task_json_path, task_info)

        completed = sum(1 for n in task_info["nodes"].values() if n.get("status") == "completed")
        total = len(task_info["nodes"])
        print(f"[Scheduler] Resumed task {task_id}: {completed}/{total} completed")

        return task_id


    def restart_task(self, task_id, workflow, custom_dir=None, input_config=None):
        """Restart a task: reset all nodes to pending, update input from latest config."""
        task_dir = custom_dir or os.path.join(TASKS_ROOT, task_id)
        task_json_path = os.path.join(task_dir, "task.json")

        try:
            with open(task_json_path, "r", encoding="utf-8") as f:
                task_info = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError(f"Task {task_id} has corrupted task.json, cannot restart")
        except FileNotFoundError:
            raise FileNotFoundError(f"Task {task_id} not found at {task_dir}")

        # Update input config from frontend (preserve workflow-level settings like copyInputs)
        if input_config:
            old_input = task_info.get("input", {})
            # Merge: new values override old, but keep workflow-level keys from old input
            merged_input = {**old_input, **input_config}
            # Preserve workflow-level settings from old input if not provided in new
            for key in ("copyInputs", "var1", "var2", "var1Required", "var2Required"):
                if key in old_input and key not in input_config:
                    merged_input[key] = old_input[key]
            task_info["input"] = merged_input
            print(f"[Scheduler] Updated input config for task {task_id}")

        # Sync input node config from task.json into workflow before writing
        # This ensures the cleaned workflow (with empty input paths) gets the
        # correct paths from task.json, so _exec_input_node won't clear them.
        ic = task_info.get("input", {})
        for node in workflow.get("nodes", []):
            if node.get("data", {}).get("nodeType") == "input":
                cfg = node.setdefault("data", {}).setdefault("config", {})
                # Sync file paths
                for key in ("videoPath", "audioPath", "subtitlePath", "url",
                            "source_language", "target_language"):
                    if ic.get(key):
                        cfg[key] = ic[key]
                break

        with open(os.path.join(task_dir, "workflow.json"), "w", encoding="utf-8") as f:
            json.dump(workflow, f, ensure_ascii=False, indent=2)

        self._reset_task_workspace(task_dir, task_info.get("input", {}))

        nodes = workflow.get("nodes", [])
        for node in nodes:
            nid = node.get("id", "")
            task_info["nodes"][nid] = self._build_node_state(node)

        task_info["edges"] = workflow.get("edges", [])
        task_info["workflow_id"] = workflow.get("id", task_info.get("workflow_id", ""))
        task_info["status"] = "created"
        task_info["started_at"] = None
        task_info["finished_at"] = None
        self._write_json(task_json_path, task_info)

        print(f"[Scheduler] Restarted task {task_id}")
        return task_id

    def restart_task_custom_dir(self, task_id, workflow, task_dir):
        """Restart a task in a custom directory (for batch subdirectories)."""
        return self.restart_task(task_id, workflow, custom_dir=task_dir)

    def resume_task_custom_dir(self, task_id, workflow, task_dir):
        """Resume a task in a custom directory (for batch subdirectories)."""
        return self.resume_task(task_id, workflow, custom_dir=task_dir)

    def execute_workflow(self, task_id, custom_dir=None):
        """Execute a workflow: resume if needed, then run steps in topological order."""
        task_dir = custom_dir or os.path.join(TASKS_ROOT, task_id)
        task_json = os.path.join(task_dir, "task.json")
        self._clear_cancel_request(task_id)

        def _run():
            current_step_id = None
            try:
                print(f"[Scheduler] START task {task_id}")
                task_dir = custom_dir or os.path.join(TASKS_ROOT, task_id)
                task_json = os.path.join(task_dir, "task.json")
                cache_dir = os.path.join(task_dir, "cache")

                with open(task_json, "r", encoding="utf-8") as f:
                    task_info = json.load(f)
                with open(os.path.join(task_dir, "workflow.json"), "r", encoding="utf-8") as f:
                    workflow = json.load(f)

                nodes = workflow.get("nodes", [])
                edges = workflow.get("edges", [])
                input_config = task_info.get("input", {})

                # 清理孤儿边：移除引用了不存在节点的边
                node_ids = {n["id"] for n in nodes}
                valid_edges = []
                for e in edges:
                    src = e.get("source", "")
                    tgt = e.get("target", "")
                    if src in node_ids and tgt in node_ids:
                        valid_edges.append(e)
                    else:
                        print(f"[Scheduler] Removing orphan edge: {e.get('id','')} (source={src}, target={tgt})")
                if len(valid_edges) != len(edges):
                    print(f"[Scheduler] Cleaned {len(edges) - len(valid_edges)} orphan edge(s)")
                    edges = valid_edges
                    workflow["edges"] = edges
                    with open(os.path.join(task_dir, "workflow.json"), "w", encoding="utf-8") as f:
                        json.dump(workflow, f, ensure_ascii=False, indent=2)

                task_info["status"] = "running"
                task_info["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                task_info["finished_at"] = None
                self._write_json(task_json, task_info)

                exec_order = self._topo_sort(nodes, edges)
                if len(exec_order) != len(nodes):
                    raise ValueError("Workflow contains a cycle or disconnected invalid edges")
                print(f"[Scheduler] Order: {exec_order}")

                for nid in exec_order:
                    self._raise_if_cancelled(task_id)
                    node = next((n for n in nodes if n["id"] == nid), None)
                    if not node:
                        continue

                    # Skip already-completed nodes (for resume mode)
                    if task_info["nodes"][nid].get("status") == "completed":
                        print(f"[Scheduler] Skipping completed node {nid}")
                        continue

                    node_type = node.get("data", {}).get("nodeType", "")
                    node_config = node.get("data", {}).get("config", {})
                    current_step_id = nid

                    task_info["nodes"][nid]["status"] = "running"
                    task_info["nodes"][nid]["progress"] = 0
                    task_info["nodes"][nid]["message"] = f"Starting {node_type}"
                    task_info["nodes"][nid]["outputs"] = {}
                    task_info["nodes"][nid]["error"] = ""
                    self._write_json(task_json, task_info)
                    self._log(task_id, nid, 0, f"Starting {node_type}")

                    step_inputs = self._resolve_inputs(
                        nid, node_type, node_config, input_config,
                        task_dir, cache_dir, edges, nodes
                    )
                    print(f"[Scheduler] Step {nid} ({node_type}), inputs: {list(step_inputs.keys())}")

                    self._raise_if_cancelled(task_id)
                    result = self._exec_step(task_id, nid, node_type, node_config, step_inputs, task_dir, cache_dir, input_config)
                    self._raise_if_cancelled(task_id)
                    ok = result[0] if isinstance(result, tuple) else result
                    err_detail = result[1] if isinstance(result, tuple) and len(result) > 1 else None
                    step_result = result[2] if isinstance(result, tuple) and len(result) > 2 else {}

                    if ok:
                        # If input node was executed successfully, sync task_info from file
                        if node_type == "input":
                            try:
                                with open(task_json, "r", encoding="utf-8") as f:
                                    updated_task = json.load(f)
                                if "input" in updated_task:
                                    task_info["input"] = updated_task["input"]
                                if "task_name" in updated_task:
                                    task_info["task_name"] = updated_task["task_name"]
                                    print(f"[Input] Synced task_info['task_name']: {updated_task['task_name']}")
                            except Exception as e:
                                print(f"[Input] Warning: Failed to sync task_info: {e}")
                        
                        # For any node that may modify task_name (like path_to_title, translate_task_name, platform_download)
                        # Sync task_name from file to prevent it being overwritten by stale task_info
                        if node_type in ("path_to_title", "translate_task_name", "platform_download"):
                            try:
                                with open(task_json, "r", encoding="utf-8") as f:
                                    updated_task = json.load(f)
                                if "task_name" in updated_task:
                                    task_info["task_name"] = updated_task["task_name"]
                                    print(f"[Scheduler] Synced task_info['task_name']: {updated_task['task_name']}")
                            except Exception as e:
                                print(f"[Scheduler] Warning: Failed to sync task_name: {e}")

                        # Use step's returned artifact paths when available
                        step_artifacts = {}
                        if isinstance(step_result, dict):
                            step_artifacts = self._normalize_output_paths(
                                task_dir,
                                step_result.get("outputs", {}),
                            )
                            for art in step_result.get("artifacts", []):
                                art_path = os.path.join(task_dir, art) if not os.path.isabs(art) else art
                                if os.path.exists(art_path):
                                    key = os.path.splitext(os.path.basename(art))[0]
                                    step_artifacts.setdefault(key, art_path)
                        # Fallback: scan cache/ for node_id prefix
                        if not step_artifacts:
                            step_artifacts = self._scan_artifacts(cache_dir, nid)
                        step_artifacts = self._filter_outputs_for_node(node_type, step_artifacts)
                        task_info["nodes"][nid]["outputs"] = step_artifacts
                        task_info["nodes"][nid]["status"] = "completed"
                        task_info["nodes"][nid]["progress"] = 100
                        task_info["nodes"][nid]["message"] = "Completed"
                        task_info["nodes"][nid]["error"] = ""
                        # Write file BEFORE WebSocket notification
                        self._write_json(task_json, task_info)
                        self._log(task_id, nid, 100, "Completed", {"status": "completed", "outputs": step_artifacts})
                    else:
                        task_info["nodes"][nid]["status"] = "failed"
                        task_info["nodes"][nid]["message"] = err_detail or "Failed"
                        task_info["nodes"][nid]["error"] = err_detail or "Failed"
                        # Write file BEFORE WebSocket notification and break
                        self._write_json(task_json, task_info)
                        self._log(task_id, nid, -1, f"ERROR: {err_detail or 'Failed'}", {"status": "failed", "error": err_detail or "Failed"})
                        break
                    current_step_id = None

                done = all(n.get("status") == "completed" for n in task_info["nodes"].values())
                task_info["status"] = "completed" if done else "failed"
                task_info["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                self._write_json(task_json, task_info)
                self._log(task_id, "__task__", 100 if done else -1, "Done" if done else "Failed", {"status": task_info["status"]})
                print(f"[Scheduler] FINISH task {task_id}: {task_info['status']}")

            except WorkflowWaitingError as e:
                with open(task_json, "r", encoding="utf-8") as f:
                    task_info = json.load(f)
                if current_step_id and current_step_id in task_info.get("nodes", {}):
                    node_info = task_info["nodes"][current_step_id]
                    node_info["status"] = "waiting"
                    node_info["progress"] = 50
                    node_info["message"] = str(e)
                    node_info["workbench_url"] = e.workbench_url
                    node_info["error"] = ""
                task_info["status"] = "paused"
                task_info["finished_at"] = None
                self._write_json(task_json, task_info)
                self._log(task_id, current_step_id or "__task__", 50, str(e), {"status": "waiting", "workbench_url": e.workbench_url})
                self._log(task_id, "__task__", 50, "Waiting for Cutia export", {"status": "paused"})
            except TaskCancelledError as e:
                print(f"[Scheduler] CANCEL task {task_id}: {e}")
                self._mark_task_cancelled(task_json, str(e), current_step_id)
            except Exception as e:
                print(f"[Scheduler] ERROR task {task_id}: {e}")
                traceback.print_exc()
                # Ensure task is marked failed and frontend is notified
                try:
                    with open(task_json, "r", encoding="utf-8") as f:
                        ti = json.load(f)
                    ti["status"] = "failed"
                    ti["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    if current_step_id and current_step_id in ti.get("nodes", {}):
                        ti["nodes"][current_step_id]["status"] = "failed"
                        ti["nodes"][current_step_id]["error"] = str(e)[:500]
                    self._write_json(task_json, ti)
                    self._log(task_id, "__task__", -1, "Failed", {"status": "failed"})
                except Exception as e2:
                    print(f"[Scheduler] CRITICAL: Failed to write error state for task {task_id}: {e2}", flush=True)
                    traceback.print_exc()

        self.submit(task_id, _run)

    def resume_waiting_cutia_task(self, task_id):
        task_dir = os.path.join(TASKS_ROOT, task_id)
        task_json_path = os.path.join(task_dir, "task.json")
        workflow_path = os.path.join(task_dir, "workflow.json")
        try:
            with open(task_json_path, "r", encoding="utf-8") as f:
                task_info = json.load(f)
            with open(workflow_path, "r", encoding="utf-8") as f:
                workflow = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return False
        waiting_nodes = [
            node_id for node_id, node in task_info.get("nodes", {}).items()
            if node.get("nodeType") == "cutia" and node.get("status") == "waiting"
        ]
        if not waiting_nodes:
            return False
        self.resume_task(task_id, workflow)
        self.execute_workflow(task_id)
        return True

    def execute_single_node(self, task_id, target_node_id, custom_dir=None):
        """Execute only a single node (after checking/updating task state)."""
        self._clear_cancel_request(task_id)

        def _run():
            task_dir = custom_dir or os.path.join(TASKS_ROOT, task_id)
            task_json_path = os.path.join(task_dir, "task.json")
            cache_dir = os.path.join(task_dir, "cache")

            try:
                with open(task_json_path, "r", encoding="utf-8") as f:
                    task_info = json.load(f)
                with open(os.path.join(task_dir, "workflow.json"), "r", encoding="utf-8") as f:
                    workflow = json.load(f)

                nodes = workflow.get("nodes", [])
                edges = workflow.get("edges", [])
                input_config = task_info.get("input", {})

                # 清理孤儿边
                node_ids = {n["id"] for n in nodes}
                valid_edges = [e for e in edges if e.get("source", "") in node_ids and e.get("target", "") in node_ids]
                if len(valid_edges) != len(edges):
                    print(f"[Scheduler] Cleaned {len(edges) - len(valid_edges)} orphan edge(s)")
                    edges = valid_edges
                    workflow["edges"] = edges

                task_info["status"] = "running"
                task_info["started_at"] = task_info.get("started_at") or time.strftime("%Y-%m-%dT%H:%M:%S")
                task_info["finished_at"] = None

                node = next((n for n in nodes if n["id"] == target_node_id), None)
                if not node:
                    print(f"[Scheduler] Node {target_node_id} not found in workflow.json")
                    return

                node_type = node.get("data", {}).get("nodeType", "")
                node_config = node.get("data", {}).get("config", {})
                node_label = node.get("data", {}).get("label", node_type)
                
                # Ensure the node exists in task_info["nodes"]
                if target_node_id not in task_info.get("nodes", {}):
                    print(f"[Scheduler] Node {target_node_id} not in task.json, adding it now")
                    if "nodes" not in task_info:
                        task_info["nodes"] = {}
                    task_info["nodes"][target_node_id] = {
                        "nodeType": node_type,
                        "label": node_label,
                        "status": "pending",
                        "progress": 0,
                        "message": "",
                        "inputs": {},
                        "outputs": {},
                        "error": ""
                    }
                
                self._raise_if_cancelled(task_id)

                # Set this node to running
                task_info["nodes"][target_node_id]["status"] = "running"
                task_info["nodes"][target_node_id]["progress"] = 0
                task_info["nodes"][target_node_id]["message"] = f"Starting {node_type}"
                task_info["nodes"][target_node_id]["outputs"] = {}
                task_info["nodes"][target_node_id]["error"] = ""
                self._write_json(task_json_path, task_info)
                self._log(task_id, target_node_id, 0, f"Starting {node_type}")

                # Resolve inputs from upstream outputs
                # Validate upstream node status
                for e in edges:
                    if e.get("target") == target_node_id:
                        src_id = e.get("source", "")
                        src_info = task_info["nodes"].get(src_id, {})
                        src_label = src_info.get("label") or src_info.get("nodeType") or src_id
                        if src_info.get("status") != "completed":
                            err_msg = f"上游节点「{src_label}」未完成，请先执行上游节点"
                            print(f"[Scheduler] {err_msg}")
                            self._log(task_id, target_node_id, -1, f"ERROR: {err_msg}")
                            self._update_node_error(task_json_path, target_node_id, err_msg)
                            with open(task_json_path, "r", encoding="utf-8") as f:
                                ti = json.load(f)
                            ti["nodes"][target_node_id]["status"] = "failed"
                            ti["nodes"][target_node_id]["message"] = err_msg
                            ti["nodes"][target_node_id]["error"] = err_msg
                            ti["status"] = "failed"
                            ti["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                            self._write_json(task_json_path, ti)
                            self._log(task_id, "__task__", -1, "Failed", {"status": "failed"})
                            return
                step_inputs = self._resolve_inputs(
                    target_node_id, node_type, node_config, input_config,
                    task_dir, cache_dir, edges, nodes
                )

                self._raise_if_cancelled(task_id)
                result = self._exec_step(task_id, target_node_id, node_type, node_config, step_inputs, task_dir, cache_dir, input_config)
                self._raise_if_cancelled(task_id)
                ok = result[0] if isinstance(result, tuple) else result
                err_detail = result[1] if isinstance(result, tuple) and len(result) > 1 else None
                step_result = result[2] if isinstance(result, tuple) and len(result) > 2 else {}

                if ok:
                    # If input node was executed successfully, sync task_info from file
                    if node_type == "input":
                        try:
                            with open(task_json_path, "r", encoding="utf-8") as f:
                                updated_task = json.load(f)
                            if "input" in updated_task:
                                task_info["input"] = updated_task["input"]
                            if "task_name" in updated_task:
                                task_info["task_name"] = updated_task["task_name"]
                                print(f"[Input] Synced task_info['task_name']: {updated_task['task_name']}")
                        except Exception as e:
                            print(f"[Input] Warning: Failed to sync task_info: {e}")
                    
                    # For any node that may modify task_name (like path_to_title, translate_task_name, platform_download)
                    # Sync task_name from file to prevent it being overwritten by stale task_info
                    if node_type in ("path_to_title", "translate_task_name", "platform_download"):
                        try:
                            with open(task_json_path, "r", encoding="utf-8") as f:
                                updated_task = json.load(f)
                            if "task_name" in updated_task:
                                task_info["task_name"] = updated_task["task_name"]
                                print(f"[Scheduler] Synced task_info['task_name']: {updated_task['task_name']}")
                        except Exception as e:
                            print(f"[Scheduler] Warning: Failed to sync task_name: {e}")

                    step_artifacts = {}
                    if isinstance(step_result, dict):
                        step_artifacts = self._normalize_output_paths(
                            task_dir,
                            step_result.get("outputs", {}),
                        )
                        for art in step_result.get("artifacts", []):
                            art_path = os.path.join(task_dir, art) if not os.path.isabs(art) else art
                            if os.path.exists(art_path):
                                key = os.path.splitext(os.path.basename(art))[0]
                                step_artifacts.setdefault(key, art_path)
                    if not step_artifacts:
                        step_artifacts = self._scan_artifacts(cache_dir, target_node_id)
                    step_artifacts = self._filter_outputs_for_node(node_type, step_artifacts)
                    task_info["nodes"][target_node_id]["outputs"] = step_artifacts
                    task_info["nodes"][target_node_id]["status"] = "completed"
                    task_info["nodes"][target_node_id]["progress"] = 100
                    task_info["nodes"][target_node_id]["message"] = "Completed"
                    task_info["nodes"][target_node_id]["error"] = ""
                    task_info["status"] = "completed"
                    task_info["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                else:
                    task_info["nodes"][target_node_id]["status"] = "failed"
                    task_info["nodes"][target_node_id]["message"] = err_detail or "Failed"
                    task_info["nodes"][target_node_id]["error"] = err_detail or "Failed"
                    task_info["status"] = "failed"
                    task_info["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

                # Write file BEFORE any WebSocket notification so fetchTaskState reads up-to-date data
                self._write_json(task_json_path, task_info)
                if ok:
                    self._log(task_id, target_node_id, 100, "Completed", {"status": "completed", "outputs": step_artifacts})
                else:
                    self._log(task_id, target_node_id, -1, f"ERROR: {err_detail or 'Failed'}", {"status": "failed", "error": err_detail or "Failed"})
                self._log(
                    task_id,
                    "__task__",
                    100 if task_info["status"] == "completed" else -1,
                    "Done" if task_info["status"] == "completed" else "Failed",
                    {"status": task_info["status"]},
                )
            except TaskCancelledError as e:
                print(f"[Scheduler] CANCEL single node {task_id}: {e}")
                self._mark_task_cancelled(task_json_path, str(e), target_node_id)
                self._broadcast_direct(task_id, target_node_id, 0, "Cancelled", {"status": "cancelled"})
            except Exception as e:
                import traceback
                print(f"[Scheduler] ERROR single node {task_id}/{target_node_id}: {e}")
                traceback.print_exc()
                # Ensure task is marked failed and frontend is notified
                err_msg = str(e)[:500]
                try:
                    with open(task_json_path, "r", encoding="utf-8") as f:
                        ti = json.load(f)
                    ti["status"] = "failed"
                    ti["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    if target_node_id in ti.get("nodes", {}):
                        ti["nodes"][target_node_id]["status"] = "failed"
                        ti["nodes"][target_node_id]["error"] = err_msg
                    self._write_json(task_json_path, ti)
                    self._log(task_id, "__task__", -1, "Failed", {"status": "failed"})
                    self._broadcast_direct(task_id, target_node_id, -1, f"ERROR: {err_msg}", {"status": "failed", "error": err_msg})
                except Exception as e2:
                    print(f"[Scheduler] CRITICAL: Failed to write error state for single node {task_id}/{target_node_id}: {e2}", flush=True)
                    traceback.print_exc()

        self.submit(task_id, _run)

    def _topo_sort(self, nodes, edges):
        """Topological sort of nodes based on edges."""
        ids = [n["id"] for n in nodes]
        indeg = {i: 0 for i in ids}
        adj = {i: [] for i in ids}
        for e in edges:
            s, t = e.get("source", ""), e.get("target", "")
            if s in adj and t in indeg:
                adj[s].append(t)
                indeg[t] += 1
        from collections import deque
        q = deque([i for i in ids if indeg[i] == 0])
        order = []
        while q:
            n = q.popleft()
            order.append(n)
            for nb in adj[n]:
                indeg[nb] -= 1
                if indeg[nb] == 0:
                    q.append(nb)
        return order

    def _resolve_inputs(self, nid, node_type, node_config, input_config, task_dir, cache_dir, edges, nodes):
        """Resolve step inputs from upstream node outputs and input config."""
        step_inputs = {}
        incoming = [e for e in edges if e.get("target") == nid]
        print(f"[Resolve] Node {nid} ({node_type}): {len(incoming)} incoming edge(s)")
        for edge in incoming:
            src = edge.get("source", "")
            src_node = next((n for n in nodes if n["id"] == src), None)
            if not src_node:
                print(f"[Resolve]   edge from {src}: source node not found in nodes list")
                continue
            src_type = src_node.get("data", {}).get("nodeType", "")
            # Get source node outputs from task.json
            src_outputs = {}
            task_json = os.path.join(task_dir, "task.json")
            if os.path.exists(task_json):
                with open(task_json, "r", encoding="utf-8") as f:
                    ti = json.load(f)
                src_outputs = ti.get("nodes", {}).get(src, {}).get("outputs", {})
            target_port = (edge.get("targetHandle", "") or "").replace("in-", "")
            source_port = (edge.get("sourceHandle", "") or "").replace("out-", "")
            print(f"[Resolve]   edge from {src} ({src_type}): sourceHandle={edge.get('sourceHandle','')} -> {source_port}, targetHandle={edge.get('targetHandle','')} -> {target_port}, src_outputs={src_outputs}")
            if src_type == "input":
                # Prefer actual node outputs (set by _exec_input_node), fall back to input_config
                output_val = src_outputs.get(source_port, "")
                if output_val:
                    step_inputs[target_port or source_port] = output_val
                else:
                    input_key_map = {
                        "video": "videoPath",
                        "audio": "audioPath",
                        "subtitle": "subtitlePath",
                        "url": "url",
                        "filepath": "filePath",
                    }
                    config_key = input_key_map.get(source_port, source_port)
                    if config_key and config_key in input_config:
                        step_inputs[target_port or source_port or config_key] = input_config[config_key]
            elif src_outputs:
                # Non-input node: use its cached outputs
                if source_port:
                    step_inputs[target_port or source_port] = src_outputs.get(source_port, "")
                else:
                    step_inputs.update(src_outputs)
        # Pass config values for specific node types
        if node_type in ["translate", "summarize"]:
            step_inputs.setdefault("language", node_config.get("language", ""))
        if node_type == "translate":
            step_inputs.setdefault("prompt_template", node_config.get("prompt_template", ""))
        if node_type == "llm_request":
            step_inputs.setdefault("source_language", input_config.get("source_language", ""))
            step_inputs.setdefault("target_language", input_config.get("target_language", ""))
        # Pass input node variables to all downstream nodes
        for vk in ("var1", "var2"):
            val = input_config.get(vk, "")
            if val:
                step_inputs.setdefault(vk, val)
        # Validate resolved input files exist
        missing_files = []
        for ik, iv in list(step_inputs.items()):
            if not isinstance(iv, str):
                continue
            iv_str = iv.strip()
            if not iv_str or iv_str.startswith(("http://", "https://")):
                continue
            # 解析相对路径为绝对路径后再检查
            iv_abs = iv_str if os.path.isabs(iv_str) else os.path.join(task_dir, iv_str)
            if not os.path.exists(iv_abs):
                missing_files.append(f"{ik}: {iv_str}")
                print(f"[Resolve] WARNING: input file not found: {ik} = {iv_abs}")
        if missing_files:
            print(f"[Resolve] {len(missing_files)} missing input file(s) for node")
        return step_inputs

    def _scan_artifacts(self, cache_dir, nid):
        """Scan cache directory for artifacts matching a node ID."""
        artifacts = {}
        if not os.path.exists(cache_dir):
            return artifacts
        for fn in os.listdir(cache_dir):
            if fn.startswith(nid + "_") or fn.startswith(nid + "."):
                key = fn[len(nid)+1:] if fn.startswith(nid + "_") else fn
                artifacts[os.path.splitext(key)[0]] = os.path.join(cache_dir, fn)
        return artifacts

    def _normalize_output_paths(self, task_dir, output_map):
        """Normalize a step outputs map to absolute file paths."""
        normalized = {}
        for key, value in (output_map or {}).items():
            if not value:
                continue
            value_str = str(value)
            # URLs and non-file values: pass through as-is
            if value_str.startswith(("http://", "https://")):
                normalized[key] = value_str
                continue
            if isinstance(value, list):
                paths = []
                for item in value:
                    item_path = item if os.path.isabs(str(item)) else os.path.join(task_dir, str(item))
                    if os.path.exists(item_path):
                        paths.append(item_path)
                if paths:
                    normalized[key] = paths
                continue
            value_path = value if os.path.isabs(value_str) else os.path.join(task_dir, value_str)
            if os.path.exists(value_path):
                normalized[key] = value_path
        return normalized

    def _get_declared_output_ids(self, node_type):
        """Get declared output port ids for built-in or custom node definitions."""
        builtin_output_ids = BUILTIN_NODE_OUTPUT_IDS.get(node_type)
        if builtin_output_ids is not None:
            return builtin_output_ids

        node_def_path = os.path.join(NODE_TYPES_DIR, f"{node_type}.json")
        if not os.path.exists(node_def_path):
            return []
        try:
            with open(node_def_path, "r", encoding="utf-8") as f:
                node_def = json.load(f)
            return [output.get("id") for output in node_def.get("outputs", []) if output.get("id")]
        except Exception:
            return []

    def _filter_outputs_for_node(self, node_type, output_map):
        """Keep only declared output ids and deduplicate identical file paths."""
        declared_output_ids = set(self._get_declared_output_ids(node_type))
        filtered = {}
        seen_paths = set()
        for key, value in (output_map or {}).items():
            if declared_output_ids and key not in declared_output_ids:
                continue
            dedupe_key = tuple(value) if isinstance(value, list) else value
            if dedupe_key in seen_paths:
                continue
            seen_paths.add(dedupe_key)
            filtered[key] = value
        return filtered

    def _exec_custom_node(self, task_id, nid, node_type, node_config, step_inputs, task_dir, cache_dir):
        """Execute a custom node from the node_types registry."""
        node_def_path = os.path.join(NODE_TYPES_DIR, f"{node_type}.json")
        if not os.path.exists(node_def_path):
            return None
        with open(node_def_path, "r", encoding="utf-8") as f:
            node_def = json.load(f)
        exec_type = (node_def.get("execType") or node_def.get("language") or "python").lower()
        exec_code = node_def.get("execCode") or node_def.get("code") or ""
        exec_file = node_def.get("execFile") or ""
        exec_timeout = int(node_def.get("execTimeout") or 300)
        code_dir = node_def.get("codeDir") or ""

        if exec_file and not os.path.isabs(exec_file):
            exec_file = os.path.join(code_dir, exec_file) if code_dir else exec_file

        if exec_file and exec_type == "python":
            return self._run_python_file(task_id, nid, exec_file, node_config, step_inputs, task_dir, cache_dir, timeout=exec_timeout)
        if exec_type == "python" and exec_code:
            return self._run_inline_python(task_id, nid, exec_code, node_config, step_inputs, task_dir, cache_dir)
        if exec_type in ("shell", "bash", "sh"):
            command = exec_code or exec_file
            if not command:
                return False, "Custom shell node missing execCode/execFile"
            return self._run_shell_command(task_id, nid, command, node_config, step_inputs, task_dir, cache_dir, timeout=exec_timeout)
        if exec_type == "llm" and exec_code:
            return self._run_llm_node(task_id, nid, exec_code, node_config, step_inputs, task_dir, cache_dir)
        return None

    def _run_python_file(self, task_id, nid, script_path, node_config, step_inputs, task_dir, cache_dir, timeout=300):
        """Run an external Python file for a custom node."""
        import subprocess
        import sys

        if not os.path.exists(script_path):
            return False, f"Python script not found: {script_path}"

        env = os.environ.copy()
        env["TASK_DIR"] = task_dir
        env["CACHE_DIR"] = cache_dir
        env["NODE_ID"] = nid
        outputs_json_path = os.path.join(cache_dir, f"{nid}_outputs.json")
        env["OUTPUTS_JSON_PATH"] = outputs_json_path
        for k, v in step_inputs.items():
            env[f"INPUT_{k.upper()}"] = str(v)
        for k, v in node_config.items():
            env[f"CONFIG_{k.upper()}"] = str(v)
        for k, v in node_config.items():
            env[f"CONFIG_{k.upper()}"] = str(v)

        try:
            process = subprocess.Popen(
                [sys.executable, script_path],
                cwd=task_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._register_process(task_id, process)
            start_time = time.time()
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if self._is_cancel_requested(task_id):
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        raise TaskCancelledError("Cancelled by user")
                    if time.time() - start_time > timeout:
                        process.kill()
                        raise subprocess.TimeoutExpired([sys.executable, script_path], timeout)
            result = type("Result", (), {"returncode": process.returncode, "stdout": stdout, "stderr": stderr})()
            if result.returncode != 0:
                return False, result.stderr[:500] or result.stdout[:500] or "Python script failed"
            self._log(task_id, nid, 100, result.stdout[:500] if result.stdout else "OK")
            artifacts = []
            outputs = {}
            if os.path.exists(outputs_json_path):
                try:
                    with open(outputs_json_path, "r", encoding="utf-8") as f:
                        outputs = json.load(f)
                except Exception:
                    outputs = {}
            for fn in os.listdir(cache_dir):
                if fn.startswith(nid):
                    artifacts.append(os.path.join(cache_dir, fn))
            return True, None, {"artifacts": artifacts, "outputs": outputs}
        except subprocess.TimeoutExpired:
            return False, f"Python script timed out after {timeout}s"
        except TaskCancelledError:
            raise
        except Exception as e:
            return False, str(e)
        finally:
            self._unregister_process(task_id)

    def _run_inline_python(self, task_id, nid, code, node_config, step_inputs, task_dir, cache_dir):
        """Run inline Python code for a custom node."""
        import io
        from contextlib import redirect_stdout, redirect_stderr
        old_dir = os.getcwd()
        try:
            os.chdir(task_dir)
            produced = {}
            env = {
                "task_dir": task_dir,
                "cache_dir": cache_dir,
                "node_id": nid,
                "config": node_config,
                "inputs": step_inputs,
                "node_config": node_config,
                "step_inputs": step_inputs,
                "produced": produced,
            }
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, {"__builtins__": __builtins__, **env})
            self._log(task_id, nid, 100, stdout_buf.getvalue()[:500] if stdout_buf.getvalue() else "OK")
            artifacts = []
            for path in produced.values():
                if path and os.path.exists(path):
                    artifacts.append(path)
            for fn in os.listdir(cache_dir):
                if fn.startswith(nid):
                    artifacts.append(os.path.join(cache_dir, fn))
            artifacts = list(dict.fromkeys(artifacts))
            return True, None, {"artifacts": artifacts, "outputs": produced}
        except Exception as e:
            return False, str(e)
        finally:
            os.chdir(old_dir)

    def _run_shell_command(self, task_id, nid, command, node_config, step_inputs, task_dir, cache_dir, timeout=300):
        """Run a shell command for a custom node."""
        import subprocess
        env = os.environ.copy()
        env["TASK_DIR"] = task_dir
        env["CACHE_DIR"] = cache_dir
        env["NODE_ID"] = nid
        outputs_json_path = os.path.join(cache_dir, f"{nid}_outputs.json")
        env["OUTPUTS_JSON_PATH"] = outputs_json_path
        for k, v in step_inputs.items():
            env[f"INPUT_{k.upper()}"] = str(v)
        for k, v in node_config.items():
            env[f"CONFIG_{k.upper()}"] = str(v)
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=task_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._register_process(task_id, process)
            start_time = time.time()
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if self._is_cancel_requested(task_id):
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        raise TaskCancelledError("Cancelled by user")
                    if time.time() - start_time > timeout:
                        process.kill()
                        raise subprocess.TimeoutExpired(command, timeout)
            result = type("Result", (), {"returncode": process.returncode, "stdout": stdout, "stderr": stderr})()
            if result.returncode != 0:
                return False, result.stderr[:500] or "Shell command failed"
            self._log(task_id, nid, 100, result.stdout[:500] if result.stdout else "OK")
            artifacts = []
            outputs = {}
            if os.path.exists(outputs_json_path):
                try:
                    with open(outputs_json_path, "r", encoding="utf-8") as f:
                        outputs = json.load(f)
                except Exception:
                    outputs = {}
            for fn in os.listdir(cache_dir):
                if fn.startswith(nid):
                    artifacts.append(os.path.join(cache_dir, fn))
            return True, None, {"artifacts": artifacts, "outputs": outputs}
        except subprocess.TimeoutExpired:
            return False, f"Command timed out after {timeout}s"
        except TaskCancelledError:
            raise
        except Exception as e:
            return False, str(e)
        finally:
            self._unregister_process(task_id)

    def _run_llm_node(self, task_id, nid, prompt_template, node_config, step_inputs, task_dir, cache_dir):
        """Run an LLM-powered custom node using OpenAI API."""
        from backend.config import settings
        prompt = prompt_template
        for k, v in step_inputs.items():
            prompt = prompt.replace("{" + k + "}", str(v))
        for k, v in node_config.items():
            prompt = prompt.replace("{" + k + "}", str(v))
        try:
            from openai import OpenAI
            import httpx
            # 忽略系统代理（VPN 全局代理），直接连接上游
            client = OpenAI(
                api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_API_BASE,
                http_client=httpx.Client(timeout=120, trust_env=False),
            )
            response = client.chat.completions.create(
                model=node_config.get("model", settings.SMALL_MODEL),
                messages=[{"role": "user", "content": prompt}],
                temperature=node_config.get("temperature", 0.7),
            )
            out_path = os.path.join(cache_dir, f"{nid}_llm_output.txt")
            response = response.choices[0].message.content
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(response)
            print(f"[Custom:{nid}] LLM output saved")
            return True, None, {"artifacts": [out_path], "outputs": {"text": out_path}}
        except Exception as e:
            return False, f"LLM error: {e}"

    def _exec_input_node(self, nid, node_config, task_dir, cache_dir, input_config=None):
        """Execute the input node: copy files if requested, record outputs and variables.

        First, read input node parameters from workflow.json and update task.json.
        Then, merge per-task input_config (from task.json) with workflow node_config.
        For batch tasks, workflow config has empty paths; the real input is in task.json's input field.
        """
        # 1. Read workflow.json and update task.json with input node parameters
        synced_input = None
        try:
            workflow_path = os.path.join(task_dir, "workflow.json")
            task_path = os.path.join(task_dir, "task.json")
            
            print(f"[Input] Starting sync: workflow={workflow_path}, task={task_path}")
            print(f"[Input] workflow.json exists: {os.path.exists(workflow_path)}")
            print(f"[Input] task.json exists: {os.path.exists(task_path)}")
            
            if os.path.exists(workflow_path) and os.path.exists(task_path):
                with open(workflow_path, "r", encoding="utf-8") as f:
                    workflow = json.load(f)
                
                # Find the input node in workflow
                input_node = None
                for node in workflow.get("nodes", []):
                    if node.get("data", {}).get("nodeType") == "input":
                        input_node = node
                        break
                
                print(f"[Input] Found input node in workflow: {input_node is not None}")
                
                if input_node:
                    # Read task.json
                    with open(task_path, "r", encoding="utf-8") as f:
                        task = json.load(f)
                    
                    # Get input node config from workflow
                    wf_input_config = input_node.get("data", {}).get("config", {})
                    print(f"[Input] Workflow config: {wf_input_config}")
                    
                    # Update task.json's input field with workflow's input node config
                    if "input" not in task:
                        task["input"] = {}
                    
                    # Merge workflow input config into task input field
                    # Only update with non-empty values to preserve task-level input paths
                    for k in ("videoPath", "audioPath", "subtitlePath", "url",
                              "source_language", "target_language"):
                        wf_val = wf_input_config.get(k, "")
                        if wf_val:
                            task["input"][k] = wf_val
                    
                    # Extract task_name from input file path
                    input_path = (task["input"].get("videoPath") or 
                                  task["input"].get("audioPath") or 
                                  task["input"].get("subtitlePath") or "")
                    if input_path:
                        # Get filename without extension
                        filename = os.path.basename(input_path)
                        task_name = os.path.splitext(filename)[0]
                    else:
                        task_name = ""
                    task["task_name"] = task_name
                    print(f"[Input] Set task_name: {task_name}")
                    
                    # Save updated task.json
                    with open(task_path, "w", encoding="utf-8") as f:
                        json.dump(task, f, ensure_ascii=False, indent=2)
                    
                    # Verify write was successful
                    with open(task_path, "r", encoding="utf-8") as f:
                        verify_task = json.load(f)
                    verify_video = verify_task.get("input", {}).get("videoPath", "")
                    print(f"[Input] Verify - task.json videoPath after write: {verify_video}")
                    
                    # Store synced input for use in step 3
                    synced_input = task["input"]
                    
                    print(f"[Input] Updated task.json with workflow input parameters")
                    print(f"[Input] New task input: {synced_input}")
                else:
                    print(f"[Input] Warning: No input node found in workflow")
            else:
                print(f"[Input] Warning: workflow.json or task.json not found")
        except Exception as e:
            import traceback
            print(f"[Input] Warning: Failed to sync workflow input to task.json: {e}")
            print(f"[Input] Traceback: {traceback.format_exc()}")

        # 2. Delete old input node artifacts and cache/input.* files
        try:
            # Delete old input artifacts
            output_dir = os.path.join(task_dir, "output")
            if os.path.exists(output_dir):
                for filename in os.listdir(output_dir):
                    if filename.startswith("input"):
                        file_path = os.path.join(output_dir, filename)
                        try:
                            if os.path.isfile(file_path):
                                os.remove(file_path)
                                print(f"[Input] Deleted old artifact: {filename}")
                        except Exception as e:
                            print(f"[Input] Warning: Failed to delete {filename}: {e}")
            
            # Delete cache/input.* files
            if os.path.exists(cache_dir):
                for filename in os.listdir(cache_dir):
                    if filename.startswith("input"):
                        file_path = os.path.join(cache_dir, filename)
                        try:
                            if os.path.isfile(file_path):
                                os.remove(file_path)
                                print(f"[Input] Deleted old cache file: {filename}")
                        except Exception as e:
                            print(f"[Input] Warning: Failed to delete {filename}: {e}")
        except Exception as e:
            print(f"[Input] Warning: Failed to clean up old files: {e}")

        # 3. Execute input node operations
        # Use synced input from task.json if available, otherwise fall back to passed input_config
        outputs: dict[str, str] = {}
        artifacts: list[str] = []
        ic = synced_input or input_config or {}

        # URL: prefer task-level input_config, fall back to node_config
        url = ic.get("url", "") or node_config.get("url", "")
        if url:
            outputs["url"] = url

        # File paths: prefer task-level input_config, fall back to node_config
        for key in ("videoPath", "audioPath", "subtitlePath"):
            fp = ic.get(key, "") or node_config.get(key, "")
            if fp and os.path.isfile(fp):
                port = key.replace("Path", "")
                outputs[port] = fp

        # 文件路径：无需任何路径处理，有输入直接作为输出项透传
        fp = ic.get("filePath", "") or node_config.get("filePath", "")
        if fp:
            outputs["filepath"] = fp

        # copyInputs and source/target language: from node_config (workflow definition)
        copy_inputs = node_config.get("copyInputs", False)
        if copy_inputs:
            for key in ("videoPath", "audioPath", "subtitlePath"):
                fp = ic.get(key, "") or node_config.get(key, "")
                if fp and os.path.isfile(fp):
                    ext = os.path.splitext(fp)[1]
                    dst = os.path.join(cache_dir, "input" + ext)
                    shutil.copy2(fp, dst)
                    artifacts.append(dst)
                    port = key.replace("Path", "")
                    outputs[port] = dst  # Override with cached path
                    print(f"[Input] Copied {fp} -> {dst}")

        # Record source/target language for downstream nodes
        for lang_key in ("source_language", "target_language"):
            val = ic.get(lang_key, "") or node_config.get(lang_key, "")
            if val:
                outputs[lang_key] = val

        # Record variables for downstream nodes
        for vk in ("var1", "var2"):
            val = node_config.get(vk, "")
            if val:
                outputs[vk] = val

        print(f"[Input] Node executed: outputs={list(outputs.keys())}")
        return True, None, {"artifacts": artifacts, "outputs": outputs}

    def _exec_step_subprocess(self, task_id, nid, node_type, node_config, step_inputs, task_dir, cache_dir):
        """Execute a heavy step in a separate process.

        模型加载/推理放在子进程中执行，避免长时间占用 GIL 阻塞 API 事件循环。
        进度通过子进程 stdout 的 `PROGRESS <json>` 行中继回主进程并广播。
        取消通过 request_cancel 直接终止子进程，同时写入取消标记文件让子进程优雅退出。
        """
        mod_path, cls_name = BUILTIN_STEP_REGISTRY[node_type]
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        ctx_path = os.path.join(cache_dir, f"{nid}_subproc_ctx.json")
        out_path = os.path.join(cache_dir, f"{nid}_subproc_result.json")
        cancel_file = os.path.join(cache_dir, f"{nid}.cancel")
        for p in (out_path, cancel_file):
            try:
                os.remove(p)
            except OSError:
                pass

        ctx = {
            "task_dir": task_dir,
            "nid": nid,
            "node_type": node_type,
            "module": mod_path,
            "class": cls_name,
            "node_config": node_config,
            "step_inputs": step_inputs,
            "output_file": out_path,
            "cancel_file": cancel_file,
        }
        try:
            with open(ctx_path, "w", encoding="utf-8") as f:
                json.dump(ctx, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return False, f"Failed to write step context: {e}"

        self._raise_if_cancelled(task_id)
        cmd = [sys.executable, "-m", "backend.engine.step_runner", ctx_path]
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        try:
            process = subprocess.Popen(
                cmd,
                cwd=project_root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            return False, f"Failed to start step subprocess: {e}"
        self._register_process(task_id, process)

        stderr_lines = []

        def _read_stdout():
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("PROGRESS "):
                    try:
                        data = json.loads(line[len("PROGRESS "):])
                        self._log(task_id, nid, int(data.get("p", 0)), data.get("m", ""))
                    except Exception:
                        pass
                else:
                    try:
                        print(f"[{nid}] {line}", flush=True)
                    except Exception:
                        pass

        def _read_stderr():
            for line in process.stderr:
                stderr_lines.append(line)

        threading.Thread(target=_read_stdout, daemon=True).start()
        threading.Thread(target=_read_stderr, daemon=True).start()

        rc = None
        try:
            while True:
                try:
                    rc = process.wait(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    if self._is_cancel_requested(task_id):
                        try:
                            with open(cancel_file, "w", encoding="utf-8") as f:
                                f.write("1")
                        except Exception:
                            pass
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=3)
                        rc = process.returncode
                        break
        finally:
            self._unregister_process(task_id)

        result = None
        if os.path.exists(out_path):
            try:
                with open(out_path, "r", encoding="utf-8") as f:
                    result = json.load(f)
            except Exception:
                result = None

        if result is not None and result.get("ok"):
            return True, None, result.get("result", {})
        err = result.get("error") if isinstance(result, dict) else None
        if not err:
            stderr_tail = "".join(stderr_lines)[-1500:]
            err = stderr_tail or f"Step subprocess exited with code {rc}"
        return False, err[:500]

    def _exec_step(self, task_id, nid, node_type, node_config, step_inputs, task_dir, cache_dir, input_config=None):
        """Execute a single workflow step by its node type."""
        task_json = os.path.join(task_dir, "task.json")
        try:
            self._raise_if_cancelled(task_id)
            if is_builtin_node_type_deleted(node_type):
                msg = f"Deleted built-in node type: {node_type}"
                self._update_node_error(task_json, nid, msg)
                return False, msg
            if node_type == "input":
                return self._exec_input_node(nid, node_config, task_dir, cache_dir, input_config)
            if node_type in FRONTEND_ONLY_NODE_TYPES:
                return True
            if node_type not in BUILTIN_STEP_REGISTRY:
                # Try to execute as custom node
                custom_result = self._exec_custom_node(task_id, nid, node_type, node_config, step_inputs, task_dir, cache_dir)
                if custom_result is not None:
                    return custom_result
                msg = f"Unknown node type: {node_type}"
                print(f"[Scheduler] {msg}")
                self._update_node_error(task_json, nid, msg)
                return False, msg

            mod_path, cls_name = BUILTIN_STEP_REGISTRY[node_type]
            # 重型节点（模型加载/推理）放到独立子进程执行，避免 GIL 阻塞 API 事件循环
            if node_type in PROCESS_ISOLATED_NODE_TYPES:
                return self._exec_step_subprocess(task_id, nid, node_type, node_config, step_inputs, task_dir, cache_dir)
            import importlib
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            step = cls()
            step._node_id = nid
            step._node_config = node_config
            step._step_inputs = step_inputs
            def progress_callback(progress, message):
                self._raise_if_cancelled(task_id)
                self._log(task_id, nid, progress, message)
            # Pass cancel_callback only if the step accepts it
            import inspect
            sig = inspect.signature(step.run)
            run_kwargs = {"callback": progress_callback}
            if "cancel_callback" in sig.parameters:
                run_kwargs["cancel_callback"] = lambda: self._is_cancel_requested(task_id)
            step_result = step.run(task_dir, **run_kwargs)
            if isinstance(step_result, dict):
                return True, None, step_result
            return True, None

        except WorkflowWaitingError:
            raise
        except Exception as e:
            err_msg = f"{type(e).__name__}: {str(e)[:500]}"
            print(f"[Scheduler] Step {nid} ({node_type}) FAILED: {err_msg}")
            traceback.print_exc()
            self._update_node_error(task_json, nid, err_msg)
            return False, err_msg

    def _update_node_error(self, task_json, nid, error_msg):
        """Update a node's error status and broadcast via WebSocket."""
        try:
            with open(task_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            if nid in data.get("nodes", {}):
                data["nodes"][nid]["status"] = "failed"
                data["nodes"][nid]["message"] = error_msg
                data["nodes"][nid]["error"] = error_msg
            with open(task_json, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        # Broadcast error to WebSocket via queue
        try:
            task_id = json.loads(open(task_json, "r", encoding="utf-8").read()).get("id", "")
            from backend.api.ws_queue import get_ws_callback
            cb = get_ws_callback()
            cb(task_id, nid, -1, f"ERROR: {error_msg}")
        except Exception:
            pass

    def _broadcast_direct(self, task_id, step_id, progress, message, extra=None):
        """Direct broadcast via asyncio to ensure frontend receives the signal
        regardless of queue drainer state."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                from backend.api.ws import broadcast_progress
                asyncio.run_coroutine_threadsafe(
                    broadcast_progress(task_id, step_id, progress, message, extra or {}),
                    loop
                )
        except Exception:
            pass

    def _log(self, task_id, step_id, progress, message, extra=None):
        """Log a step progress message and broadcast via WebSocket."""
        if progress == -1 or "ERROR" in message:
            print(f"[ERROR][{step_id}] {message}", flush=True)
        else:
            print(f"[{step_id}] {message} ({progress}%)", flush=True)

        # Thread-safe broadcast via message queue
        try:
            from backend.api.ws_queue import get_ws_callback
            cb = get_ws_callback()
            cb(task_id, step_id, progress, message, extra or {})
        except Exception:
            pass

        # On node/task completion/failure, also do a direct broadcast for reliability
        if progress in (100, -1):
            self._broadcast_direct(task_id, step_id, progress, message, extra)

    def _write_json(self, path, data):
        """Write JSON data to a file atomically (tmp + rename)."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)


_scheduler = None


def get_scheduler(max_workers=3):
    """Get or create the global scheduler singleton.
    
    If the scheduler already exists and max_workers is larger than the current
    pool size, the executor is automatically expanded to accommodate more
    concurrent tasks.
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = ThreadScheduler(max_workers=max_workers)
    elif max_workers > _scheduler._max_workers:
        _scheduler.reset_executor(max_workers=max_workers)
    return _scheduler

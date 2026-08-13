"""
s14_output: Copy/move upstream files to output directory with filename rules.
"""
import os
import re
import shutil
from typing import Callable, Optional


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = name.strip('. ')
    if not name:
        name = "output"
    return name[:200]


class StepOutput:
    step_id = "s14_output"
    step_name = "Output"

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        import json
        node_id = getattr(self, "_node_id", "")
        task_json = os.path.join(task_dir, "task.json")
        with open(task_json, "r", encoding="utf-8") as f:
            task_data = json.load(f)

        # Read node config from workflow.json
        node_cfg = {}
        wf_path = os.path.join(task_dir, "workflow.json")
        with open(wf_path, "r", encoding="utf-8") as f:
            wf = json.load(f)
        for node in wf.get("nodes", []):
            if node.get("id") == node_id:
                node_cfg = node.get("data", {}).get("config", {})
                break

        cache_dir = os.path.join(task_dir, "cache")
        output_dir = node_cfg.get("outputDir", "")
        file_name = node_cfg.get("fileName", "")
        suffix = node_cfg.get("suffix", "")
        auto_increment = node_cfg.get("autoIncrement", True)

        # Default output dir: task folder / output
        if not output_dir:
            output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        print(f"[S14] Output directory: {output_dir}")
        print(f"[S14] File name: {file_name or '(original)'}, Suffix: {suffix or '(none)'}, Auto-increment: {auto_increment}")
        if callback:
            callback(10, f"Output directory: {output_dir}")

        # Collect upstream files - only files actually connected to this node
        # Read workflow edges to find what's connected to output node
        upstream_files = {}
        edges = wf.get("edges", [])
        output_nid = node_id
        
        # File type to extension mapping
        TYPE_EXTS = {
            "video": ('.mp4', '.mkv', '.webm', '.avi', '.mov'),
            "audio": ('.wav', '.mp3', '.flac', '.m4a', '.ogg'),
            "subtitle": ('.srt', '.ass', '.vtt', '.sub'),
            "image": ('.jpg', '.jpeg', '.png', '.webp'),
        }

        if output_nid:
            for edge in edges:
                if edge.get("target") == output_nid:
                    src_nid = edge.get("source", "")
                    # Determine port type from sourceHandle (e.g. "out-video" -> "video")
                    src_handle = edge.get("sourceHandle", "")
                    port_type = src_handle.replace("out-", "") if src_handle.startswith("out-") else ""

                    # Use task.json outputs to get actual file paths from upstream node
                    src_outputs = task_data.get("nodes", {}).get(src_nid, {}).get("outputs", {})

                    if port_type and port_type in src_outputs:
                        upstream_files[port_type] = src_outputs[port_type]
                    elif port_type == "image" and "cover" in src_outputs:
                        upstream_files["image"] = src_outputs["cover"]
                    elif port_type == "any" or not port_type:
                        # "any" port: accept all media outputs from upstream
                        for ftype in ("video", "audio", "audio_manifest", "subtitle", "image", "cover", "background", "text"):
                            if ftype in src_outputs:
                                key = "image" if ftype == "cover" else ftype
                                upstream_files.setdefault(key, src_outputs[ftype])
        


        print(f"[S14] Found {len(upstream_files)} upstream files: {list(upstream_files.keys())}")
        for ftype, fpath in upstream_files.items():
            print(f"[S14]   {ftype}: {os.path.basename(fpath)}")
        if not upstream_files:
            print("[S14] WARNING: No files to output")
            if callback:
                callback(100, "No files to output")
            return {"outputs": {}}

        produced = {}
        total = len(upstream_files)
        for i, (file_type, src_path) in enumerate(upstream_files.items()):
            ext = os.path.splitext(src_path)[1]

            # Build output filename
            if file_name:
                base_name = sanitize_filename(file_name)
            else:
                base_name = sanitize_filename(os.path.splitext(os.path.basename(src_path))[0])

            if suffix:
                base_name = base_name + suffix

            out_name = base_name + ext
            out_path = os.path.join(output_dir, out_name)

            # Auto-increment if file exists
            if auto_increment and os.path.exists(out_path):
                counter = 1
                while os.path.exists(out_path):
                    out_name = f"{base_name}_{counter}{ext}"
                    out_path = os.path.join(output_dir, out_name)
                    counter += 1

            print(f"[S14] Copying: {os.path.basename(src_path)} -> {out_path}")
            shutil.copy2(src_path, out_path)
            produced[file_type] = out_path
            print(f"[S14] OK: {out_name} ({os.path.getsize(out_path)} bytes)")

            progress = int(10 + (i + 1) / total * 90)
            if callback:
                callback(progress, f"Output: {out_name}")

        print(f"[S14] Output complete: {len(produced)} files")
        if callback:
            callback(100, f"Output complete: {len(produced)} files")

        return {
            "artifacts": [os.path.relpath(path, task_dir) for path in produced.values()],
            "outputs": produced,
        }

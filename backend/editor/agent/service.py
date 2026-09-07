from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

import httpx

from backend.editor.agent.prompts import (
    DEFAULT_EXPERT_ROLE,
    EXPERT_ROLE_IDS,
    EXPERT_ROLE_LABELS,
    FONT_SIZE_HINT,
    SELECTABLE_ROLE_IDS,
    build_system_prompt,
    describe_role_options,
    total_duration,
)
from backend.editor.agent.media_tools import (
    generate_image,
    generate_video,
    synthesize_speech,
    transcribe_media,
)
from backend.editor.repository import EditorProjectRepository, RevisionConflictError
from backend.llm.llm_client import get_llm_client

# 移植 cutia runAgentLoop 的轮次上限（原实现为 8 轮，复杂编排任务不够用）
MAX_TOOL_ROUNDS = 20

SWITCH_ROLE_TOOL_NAME = "switch_expert_role"

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_project_info",
            "description": "Get the current project state including canvas size, FPS, duration, track summary, and available media assets.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_media_assets",
            "description": "List all media assets available in the current project (images, videos, audio) with their properties.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_timeline_state",
            "description": "Get the current timeline state including all tracks and their elements with timing information.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_video_to_timeline",
            "description": "Add a video or image media asset to the timeline. Use list_media_assets to find available media IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mediaId": {"type": "string", "description": "The ID of the media asset to add"},
                    "startTime": {"type": "number", "description": "Start time in seconds on the timeline (default: 0)"},
                    "duration": {"type": "number", "description": "Duration in seconds. Defaults to the media's original duration; images default to 5s."},
                },
                "required": ["mediaId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_audio_to_timeline",
            "description": "Add an audio media asset to the timeline. The audio must already exist in the project's media library.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mediaId": {"type": "string", "description": "The ID of the audio media asset to add"},
                    "startTime": {"type": "number", "description": "Start time in seconds on the timeline (default: 0)"},
                    "duration": {"type": "number", "description": "Duration in seconds (defaults to the audio's original duration)"},
                },
                "required": ["mediaId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_text_to_timeline",
            "description": "Add a text overlay element to the timeline with customizable content and styling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The text content to display"},
                    "startTime": {"type": "number", "description": "Start time in seconds (default: 0)"},
                    "duration": {"type": "number", "description": "Duration in seconds (default: 5)"},
                    "fontSize": {"type": "number", "minimum": 1, "maximum": 38, "description": "Font size. " + FONT_SIZE_HINT + " Default: 15."},
                    "fontFamily": {"type": "string", "description": "Font family name, e.g. 'Arial', 'Inter' (default: 'Arial')"},
                    "fontWeight": {"type": "string", "enum": ["normal", "bold"], "description": "Font weight (default: 'normal')"},
                    "fontStyle": {"type": "string", "enum": ["normal", "italic"], "description": "Font style (default: 'normal')"},
                    "color": {"type": "string", "description": "Text color as hex string (default: '#ffffff')"},
                    "backgroundColor": {"type": "string", "description": "Background color as hex string (default: transparent)"},
                    "textAlign": {"type": "string", "enum": ["left", "center", "right"], "description": "Text alignment (default: 'center')"},
                    "positionX": {"type": "number", "description": "Horizontal pixel offset from canvas center. 0 = center, positive = right."},
                    "positionY": {"type": "number", "description": "Vertical pixel offset from canvas center. 0 = center, positive = down."},
                    "scale": {"type": "number", "description": "Transform scale factor (default: 1)"},
                    "rotate": {"type": "number", "description": "Rotation angle in degrees (default: 0, positive = clockwise)"},
                    "opacity": {"type": "number", "minimum": 0, "maximum": 1, "description": "Element opacity (default: 1)"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_element",
            "description": "Update properties of an existing timeline element (transform, opacity, text content, styling, timing).",
            "parameters": {
                "type": "object",
                "properties": {
                    "trackId": {"type": "string", "description": "The track ID containing the element"},
                    "elementId": {"type": "string", "description": "The element ID to update"},
                    "content": {"type": "string", "description": "New text content (text elements only)"},
                    "startTime": {"type": "number", "description": "New start time in seconds"},
                    "duration": {"type": "number", "description": "New duration in seconds"},
                    "fontSize": {"type": "number", "minimum": 1, "maximum": 38, "description": "Font size (text elements only). " + FONT_SIZE_HINT},
                    "fontFamily": {"type": "string", "description": "Font family name (text elements only)"},
                    "fontWeight": {"type": "string", "enum": ["normal", "bold"], "description": "Font weight (text elements only)"},
                    "fontStyle": {"type": "string", "enum": ["normal", "italic"], "description": "Font style (text elements only)"},
                    "color": {"type": "string", "description": "Text color as hex string (text elements only)"},
                    "backgroundColor": {"type": "string", "description": "Background color as hex string (text elements only)"},
                    "textAlign": {"type": "string", "enum": ["left", "center", "right"], "description": "Text alignment (text elements only)"},
                    "opacity": {"type": "number", "minimum": 0, "maximum": 1, "description": "Element opacity from 0 to 1"},
                    "scale": {"type": "number", "description": "Transform scale factor"},
                    "positionX": {"type": "number", "description": "Horizontal pixel offset from canvas center"},
                    "positionY": {"type": "number", "description": "Vertical pixel offset from canvas center"},
                    "rotate": {"type": "number", "description": "Rotation angle in degrees"},
                },
                "required": ["trackId", "elementId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_element",
            "description": "Move an element to a different time position, optionally to a different track.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sourceTrackId": {"type": "string", "description": "Current track ID of the element"},
                    "elementId": {"type": "string", "description": "Element ID to move"},
                    "newStartTime": {"type": "number", "description": "New start time in seconds"},
                    "targetTrackId": {"type": "string", "description": "Target track ID (defaults to the same track)"},
                },
                "required": ["sourceTrackId", "elementId", "newStartTime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_element",
            "description": "Delete one or more elements from the timeline. Pass an `elements` array, or a single trackId/elementId pair.",
            "parameters": {
                "type": "object",
                "properties": {
                    "elements": {
                        "type": "array",
                        "description": "Array of elements to delete",
                        "items": {
                            "type": "object",
                            "properties": {
                                "trackId": {"type": "string", "description": "Track ID"},
                                "elementId": {"type": "string", "description": "Element ID"},
                            },
                            "required": ["trackId", "elementId"],
                        },
                    },
                    "trackId": {"type": "string", "description": "Track ID (single-element form)"},
                    "elementId": {"type": "string", "description": "Element ID (single-element form)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_project_settings",
            "description": "Update project settings such as canvas size (width/height), FPS, or background color.",
            "parameters": {
                "type": "object",
                "properties": {
                    "width": {"type": "integer", "minimum": 320, "maximum": 7680, "description": "Canvas width in pixels"},
                    "height": {"type": "integer", "minimum": 320, "maximum": 7680, "description": "Canvas height in pixels"},
                    "fps": {"type": "integer", "minimum": 1, "maximum": 120, "description": "Frames per second (e.g. 24, 30, 60)"},
                    "backgroundColor": {"type": "string", "description": "Background color as hex string (e.g. '#000000')"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_speech",
            "description": "Generate speech audio from text using the configured TTS interface. The audio is added to the media library; use the returned mediaId with add_audio_to_timeline. This may take several seconds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to speak"},
                    "voice": {"type": "string", "description": "Optional voice name (uses the interface default when omitted)"},
                    "engineId": {"type": "string", "description": "Optional TTS interface id (uses the first enabled interface when omitted)"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transcribe_media",
            "description": "Transcribe speech in a media asset into timestamped subtitle segments using the configured ASR interface. Use it to read narration text before writing captions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mediaId": {"type": "string", "description": "The media asset id (video or audio) to transcribe"},
                    "language": {"type": "string", "description": "Optional language code, e.g. 'zh', 'en'"},
                    "engineId": {"type": "string", "description": "Optional ASR interface id (uses the first enabled interface when omitted)"},
                },
                "required": ["mediaId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an image with AI using the configured image generation interface. The image is added to the media library; use the returned mediaId with add_video_to_timeline (images are supported there).",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Description of the image to generate"},
                    "aspectRatio": {"type": "string", "description": "Aspect ratio such as '16:9', '1:1', '9:16' (default: '16:9')"},
                    "numImages": {"type": "integer", "minimum": 1, "maximum": 4, "description": "How many images to generate (default: 1)"},
                    "refMediaId": {"type": "string", "description": "Optional existing image asset id to use as a visual reference"},
                    "ifaceId": {"type": "string", "description": "Optional image-generation interface id. Omit to let the agent auto-pick an enabled interface; if the chosen one fails it falls back to another capable interface."},
                    "model": {"type": "string", "description": "Optional model name to override the interface default (e.g. 'seedream-3.0')."},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_video",
            "description": "Generate a video clip with AI using the configured video generation interface. This is a long-running operation (often minutes). The clip is added to the media library; use the returned mediaId with add_video_to_timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Description of the video to generate"},
                    "duration": {"type": "integer", "minimum": 1, "maximum": 30, "description": "Clip duration in seconds (default: 5)"},
                    "ratio": {"type": "string", "description": "Aspect ratio such as '16:9', '9:16' (default: '16:9')"},
                    "resolution": {"type": "string", "description": "Resolution tier: 480P / 720P / 1080P (default: '720P')"},
                    "refMediaId": {"type": "string", "description": "Optional image asset id to use as the first frame reference"},
                    "ifaceId": {"type": "string", "description": "Optional video-generation interface id. Omit to let the agent auto-pick an enabled interface; if the chosen one fails it falls back to another capable interface."},
                    "model": {"type": "string", "description": "Optional model name to override the interface default."},
                },
                "required": ["prompt"],
            },
        },
    },
]

SWITCH_ROLE_SCHEMA = {
    "type": "function",
    "function": {
        "name": SWITCH_ROLE_TOOL_NAME,
        "description": (
            "Switch your active expert role to leverage specialized knowledge for the current phase. "
            f"Only available in Director (auto) mode. Options: {describe_role_options()}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": list(SELECTABLE_ROLE_IDS),
                    "description": "The expert role to switch to",
                },
            },
            "required": ["role"],
        },
    },
}


class EditorAgentService:
    def __init__(self, repository: EditorProjectRepository | None = None):
        self.repository = repository or EditorProjectRepository()
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _run_path(self, task_id: str, run_id: str) -> Path:
        path = self.repository.editor_dir(task_id) / "runs"
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{run_id}.json"

    def _save_run(self, task_id: str, run: dict[str, Any]) -> None:
        path = self._run_path(task_id, run["id"])
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        with self._lock:
            self._runs[run["id"]] = run

    def get_run(self, task_id: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
        if run:
            return run
        path = self._run_path(task_id, run_id)
        if not path.exists():
            raise ValueError("Agent run not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def _client(self, manual_config: dict[str, str] | None) -> tuple[OpenAI, str]:
        if manual_config:
            base_url = manual_config.get("base_url", "").rstrip("/")
            api_key = manual_config.get("api_key", "")
            model = manual_config.get("model", "")
            if not base_url or not api_key or not model:
                raise ValueError("Manual OpenAI-compatible configuration is incomplete")
            return OpenAI(
                base_url=base_url, api_key=api_key, timeout=120, max_retries=0,
                # 忽略系统代理（VPN 全局代理），直接连接上游
                http_client=httpx.Client(timeout=120, trust_env=False),
            ), model
        llm = get_llm_client()
        config = llm._get_api_config("editor_agent")
        if not config["base_url"] or not config["api_key"]:
            raise ValueError("LLM router is not configured")
        return llm._make_client(config), config["model"]

    def _new_track(self, project: dict[str, Any], track_type: str) -> dict[str, Any]:
        scene = next((scene for scene in project.get("scenes", []) if scene.get("id") == project.get("currentSceneId")), project.get("scenes", [])[0])
        track = {"id": f"track_{uuid.uuid4().hex[:12]}", "type": track_type, "name": track_type.title(), "isMain": False, "elements": []}
        if track_type == "video":
            track["transitions"] = []
        scene.setdefault("tracks", []).append(track)
        return track

    def _find_track(self, project: dict[str, Any], track_id: str) -> dict[str, Any]:
        for scene in project.get("scenes", []):
            for track in scene.get("tracks", []):
                if track.get("id") == track_id:
                    return track
        raise ValueError("Timeline track not found")

    def _find_element(self, project: dict[str, Any], track_id: str, element_id: str):
        track = self._find_track(project, track_id)
        for element in track.get("elements", []):
            if element.get("id") == element_id:
                return track, element
        raise ValueError("Timeline element not found")

    def _apply_transform(self, element: dict[str, Any], arguments: dict[str, Any]) -> bool:
        """合并 transform 增量更新，返回是否发生变化。"""
        if not any(key in arguments for key in ("scale", "positionX", "positionY", "rotate")):
            return False
        current = element.get("transform") or {"scale": 1, "position": {"x": 0, "y": 0}, "rotate": 0}
        position = current.get("position") or {"x": 0, "y": 0}
        element["transform"] = {
            "scale": arguments.get("scale", current.get("scale", 1)),
            "position": {
                "x": arguments.get("positionX", position.get("x", 0)),
                "y": arguments.get("positionY", position.get("y", 0)),
            },
            "rotate": arguments.get("rotate", current.get("rotate", 0)),
        }
        return True

    def _execute_tool(self, task_id: str, tool_name: str, arguments: dict[str, Any], expected_revision: int, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        snapshot = self.repository.snapshot(task_id)
        if expected_revision != snapshot["revision"]:
            raise RevisionConflictError(snapshot["revision"])
        project = snapshot["project"]
        assets = {asset["id"]: asset for asset in snapshot["assets"]}

        if tool_name == "get_project_info":
            return {"success": True, "message": "Project state loaded", "data": snapshot}
        if tool_name == "list_media_assets":
            listing = [
                {key: asset.get(key) for key in ("id", "name", "type", "duration", "width", "height")}
                for asset in snapshot["assets"]
            ]
            return {
                "success": True,
                "message": f"Found {len(listing)} media asset(s)",
                "data": {"assets": listing},
            }
        if tool_name == "get_timeline_state":
            tracks = []
            for scene in project.get("scenes", []):
                for track in scene.get("tracks", []):
                    tracks.append({
                        "id": track.get("id"),
                        "type": track.get("type"),
                        "name": track.get("name"),
                        "isMain": bool(track.get("isMain")),
                        "elements": [
                            {
                                "id": element.get("id"),
                                "type": element.get("type"),
                                "name": element.get("name"),
                                "startTime": element.get("startTime"),
                                "duration": element.get("duration"),
                                "content": element.get("content"),
                                "mediaId": element.get("mediaId"),
                            }
                            for element in track.get("elements", [])
                        ],
                    })
            return {
                "success": True,
                "message": f"Timeline has {len(tracks)} track(s), total duration: {total_duration(project):.2f}s",
                "data": {"tracks": tracks, "totalDuration": total_duration(project)},
            }

        if tool_name == "generate_speech":
            asset = synthesize_speech(
                task_id,
                str(arguments.get("text") or ""),
                arguments.get("voice"),
                arguments.get("engineId"),
            )
            return {"success": True, "message": f"Speech generated: {asset['name']}", "data": {"asset": asset, "mediaId": asset["id"]}}
        if tool_name == "transcribe_media":
            result = transcribe_media(
                task_id,
                str(arguments.get("mediaId") or ""),
                arguments.get("language"),
                arguments.get("engineId"),
            )
            return {"success": True, "message": f"Transcribed {result['segmentCount']} segment(s)", "data": result}
        if tool_name == "generate_image":
            asset = generate_image(
                task_id,
                str(arguments.get("prompt") or ""),
                arguments.get("aspectRatio") or "16:9",
                arguments.get("numImages") or 1,
                arguments.get("refMediaId"),
                arguments.get("ifaceId") or (defaults or {}).get("imagegen_iface_id"),
                arguments.get("model") or (defaults or {}).get("imagegen_model"),
            )
            return {"success": True, "message": f"Image generated: {asset['name']}", "data": {"asset": asset, "mediaId": asset["id"]}}
        if tool_name == "generate_video":
            asset = generate_video(
                task_id,
                str(arguments.get("prompt") or ""),
                arguments.get("duration") or 5,
                arguments.get("ratio") or "16:9",
                arguments.get("resolution") or "720P",
                arguments.get("refMediaId"),
                arguments.get("ifaceId") or (defaults or {}).get("videogen_iface_id"),
                arguments.get("model") or (defaults or {}).get("videogen_model"),
            )
            return {"success": True, "message": f"Video generated: {asset['name']}", "data": {"asset": asset, "mediaId": asset["id"]}}

        if tool_name in {"add_video_to_timeline", "add_audio_to_timeline"}:
            asset = assets.get(arguments["mediaId"])
            required_type = "audio" if tool_name == "add_audio_to_timeline" else None
            if not asset or (required_type and asset.get("type") != required_type) or (not required_type and asset.get("type") not in {"video", "image"}):
                raise ValueError("Selected media asset is unavailable for this operation")
            track_type = "audio" if required_type else "video"
            track = next((track for scene in project.get("scenes", []) for track in scene.get("tracks", []) if track.get("type") == track_type), None)
            if not track:
                track = self._new_track(project, track_type)
            duration = float(arguments.get("duration") or asset.get("duration") or 5)
            element = {"id": f"element_{uuid.uuid4().hex[:12]}", "type": asset["type"], "mediaId": asset["id"], "startTime": float(arguments.get("startTime") or 0), "duration": duration, "trimStart": 0, "trimEnd": 0, "opacity": 1, "transform": {"position": {"x": 0, "y": 0}, "scale": 1, "rotate": 0}}
            track.setdefault("elements", []).append(element)
            message = f"Added {asset['name']} to the {track_type} timeline"
        elif tool_name == "add_text_to_timeline":
            track = next((track for scene in project.get("scenes", []) for track in scene.get("tracks", []) if track.get("type") == "text"), None)
            if not track:
                track = self._new_track(project, "text")
            element = {
                "id": f"element_{uuid.uuid4().hex[:12]}",
                "type": "text",
                "content": arguments["content"],
                "startTime": float(arguments.get("startTime") or 0),
                "duration": float(arguments.get("duration") or 5),
                "fontSize": arguments.get("fontSize", 15),
                "fontFamily": arguments.get("fontFamily", "Arial"),
                "fontWeight": arguments.get("fontWeight", "normal"),
                "fontStyle": arguments.get("fontStyle", "normal"),
                "color": arguments.get("color", "#ffffff"),
                "textAlign": arguments.get("textAlign", "center"),
                "opacity": arguments.get("opacity", 1),
                "transform": {
                    "scale": arguments.get("scale", 1),
                    "position": {"x": arguments.get("positionX", 0), "y": arguments.get("positionY", 0)},
                    "rotate": arguments.get("rotate", 0),
                },
            }
            if arguments.get("backgroundColor"):
                element["backgroundColor"] = arguments["backgroundColor"]
            track.setdefault("elements", []).append(element)
            message = "Added text to the timeline"
        elif tool_name == "update_element":
            _track, element = self._find_element(project, arguments["trackId"], arguments["elementId"])
            for field in ("content", "startTime", "duration", "color", "fontSize", "fontFamily", "fontWeight", "fontStyle", "textAlign", "opacity"):
                if field in arguments:
                    element[field] = arguments[field]
            if "backgroundColor" in arguments:
                element["backgroundColor"] = arguments["backgroundColor"]
            self._apply_transform(element, arguments)
            message = "Updated timeline element"
        elif tool_name == "move_element":
            source_track, element = self._find_element(project, arguments["sourceTrackId"], arguments["elementId"])
            element["startTime"] = float(arguments.get("newStartTime") or 0)
            target_track_id = arguments.get("targetTrackId")
            if target_track_id and target_track_id != arguments["sourceTrackId"]:
                target_track = self._find_track(project, target_track_id)
                source_track["elements"] = [item for item in source_track.get("elements", []) if item.get("id") != arguments["elementId"]]
                target_track.setdefault("elements", []).append(element)
            message = f"Moved element to {element['startTime']}s"
        elif tool_name == "delete_element":
            targets = arguments.get("elements") or []
            if not targets and arguments.get("trackId") and arguments.get("elementId"):
                targets = [{"trackId": arguments["trackId"], "elementId": arguments["elementId"]}]
            if not targets:
                raise ValueError("No elements specified")
            deleted = 0
            for target in targets:
                track = self._find_track(project, target.get("trackId"))
                before = len(track.get("elements", []))
                track["elements"] = [item for item in track.get("elements", []) if item.get("id") != target.get("elementId")]
                deleted += before - len(track["elements"])
            if deleted == 0:
                raise ValueError("Timeline element not found")
            message = f"Deleted {deleted} element(s)"
        elif tool_name == "update_project_settings":
            settings = project.setdefault("settings", {})
            canvas = settings.setdefault("canvasSize", {"width": 1920, "height": 1080})
            if "width" in arguments:
                canvas["width"] = arguments["width"]
            if "height" in arguments:
                canvas["height"] = arguments["height"]
            if "fps" in arguments:
                settings["fps"] = arguments["fps"]
            if "backgroundColor" in arguments:
                settings["background"] = {"type": "color", "color": arguments["backgroundColor"]}
            message = "Updated project settings"
        else:
            raise ValueError(f"Unsupported tool: {tool_name}")
        updated = self.repository.save_project(task_id, project, expected_revision, "agent")
        return {"success": True, "message": message, "data": {"revision": updated["revision"]}}

    def _switch_role(self, arguments: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        """处理专家角色切换，返回（工具结果，新角色或 None）。"""
        role = str(arguments.get("role") or "").strip()
        if role not in SELECTABLE_ROLE_IDS:
            return {
                "success": False,
                "message": f"Invalid role: {role}. Available roles: {', '.join(SELECTABLE_ROLE_IDS)}",
            }, None
        label = EXPERT_ROLE_LABELS.get(role, role)
        return {
            "success": True,
            "message": f"Switched to {label} role. Your next actions should leverage this expert's specialized knowledge.",
        }, role

    def execute(self, task_id: str, content: str, role: str = "auto", expected_revision: int | None = None, manual_config: dict[str, str] | None = None, imagegen_iface_id: str | None = None, imagegen_model: str | None = None, videogen_iface_id: str | None = None, videogen_model: str | None = None) -> dict[str, Any]:
        snapshot = self.repository.snapshot(task_id)
        revision = expected_revision if expected_revision is not None else snapshot["revision"]
        active_role = role if role in EXPERT_ROLE_IDS else DEFAULT_EXPERT_ROLE
        is_director = active_role == "auto"

        run = {"id": uuid.uuid4().hex, "task_id": task_id, "status": "running", "createdAt": self._now(), "events": [], "toolCalls": [], "input_revision": revision, "role": active_role}
        self._save_run(task_id, run)
        try:
            defaults = {
                key: value
                for key, value in (
                    ("imagegen_iface_id", imagegen_iface_id),
                    ("imagegen_model", imagegen_model),
                    ("videogen_iface_id", videogen_iface_id),
                    ("videogen_model", videogen_model),
                )
                if value
            }
            client, model = self._client(manual_config)
            schemas = list(TOOL_SCHEMAS) + ([SWITCH_ROLE_SCHEMA] if is_director else [])
            messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
            final_content = ""

            for _ in range(MAX_TOOL_ROUNDS):
                # 每轮重建系统提示：项目状态与专家角色都可能是最新的
                snapshot = self.repository.snapshot(task_id)
                system_prompt = build_system_prompt(snapshot["project"], snapshot["assets"], active_role)
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system_prompt}, *messages],
                    tools=schemas,
                    tool_choice="auto",
                )
                message = response.choices[0].message
                if message.content:
                    final_content += message.content
                    run["events"].append({"type": "content", "content": message.content})
                messages.append(message.model_dump(exclude_none=True))
                if not message.tool_calls:
                    break

                for call in message.tool_calls:
                    arguments = json.loads(call.function.arguments or "{}")
                    if is_director and call.function.name == SWITCH_ROLE_TOOL_NAME:
                        result, new_role = self._switch_role(arguments)
                        if new_role:
                            active_role = new_role
                            run["events"].append({"type": "role.switched", "role": new_role})
                    else:
                        result = self._execute_tool(task_id, call.function.name, arguments, revision, defaults=defaults)
                        revision = result.get("data", {}).get("revision", revision)
                    record = {"id": call.id, "name": call.function.name, "arguments": arguments, "result": result}
                    run["toolCalls"].append(record)
                    run["events"].append({"type": "tool.completed", **record})
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})

            run["status"] = "completed"
            run["content"] = final_content or "已完成项目分析和编辑。"
            run["output_revision"] = revision
            run["final_role"] = active_role
        except Exception as exc:
            run["status"] = "failed"
            run["error"] = str(exc)
        run["completedAt"] = self._now()
        self._save_run(task_id, run)
        return run

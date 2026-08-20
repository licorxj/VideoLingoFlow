# VideoLingoFlow Capability and Skill Index

All paths are relative to `PROJECT_ROOT`.

## Workflow Node Implementations

- Platform/media download: `backend/steps/s00_platform_download.py`, `backend/steps/s01_download.py`.
- Speech recognition and preprocessing: `backend/steps/s02_asr.py`, `backend/steps/s_sentence_preprocess.py`.
- Sentence splitting, summary, and translation: `backend/steps/s03_sentence_split.py`, `backend/steps/s04_summarize.py`, `backend/steps/s05_translate.py`.
- Subtitle processing and rendering: `backend/steps/s06_subtitle_gen.py`, `backend/steps/s07_subtitle_align.py`, `backend/steps/s07_merge_sub_video.py`.
- Dubbing and audio/video composition: `backend/steps/s08_dub_task.py`, `backend/steps/s09_tts.py`, `backend/steps/s10_merge_audio.py`, `backend/steps/s11_merge_dub_video.py`.
- Image/video finishing: `backend/steps/s12_cover.py`, `backend/steps/s13_watermark.py`, `backend/steps/s14_output.py`.
- Audio extraction and separation: `backend/steps/s15_extract_audio.py`, `backend/steps/s16_vocal_separation.py`, `backend/steps/s17_track_separation.py`.
- AI generation: `backend/steps/s_aigc_comfyui.py`, `backend/steps/s_aigc_jimeng.py`, `backend/steps/s_aigc_runninghub.py`, `backend/steps/s_imagegen.py`.
- Utility and integration nodes: `backend/steps/s_http_request.py`, `backend/steps/s_llm_request.py`, `backend/steps/s_json_editor.py`, `backend/steps/s_json_to_text.py`, `backend/steps/s_file_rename.py`, `backend/steps/s_video_publish.py`.
- Editing and workflow-agent nodes: `backend/steps/s_cutia.py`, `backend/steps/s_editor_agent.py`.

## Skill Documentation Locations

- Built-in agent knowledge documents: `backend/config/agent/*.md`.
- Project-specific installed skills: `backend/config/agent/skills/`.
- User-installed skills are scanned from: `%USERPROFILE%/.claude/skills`, `%USERPROFILE%/.codex/skills`, `%USERPROFILE%/.trae/skills`, `%USERPROFILE%/.agents/skills`, `%USERPROFILE%/.agent/skills`.
- Project-specific MCP definitions: `backend/config/agent/mcp/`.
- User-installed MCP definitions are scanned from: `%USERPROFILE%/.claude/mcps`, `%USERPROFILE%/.trae/mcps`, `%USERPROFILE%/.agents/mcps`, `%USERPROFILE%/.agent/mcps`.

In the workflow node configuration, Skill/MCP are picked through a picker dialog (searchable, checkbox selection, description preview, manual rescan button); only items explicitly enabled in 小π Agent settings are eligible for authorization. Availability in a directory does not itself grant execution permission.

## Primary Configuration Sources

- Main backend configuration: `backend/config/config.yaml`.
- Local runtime environment: `.runtime/local_env.bat`.
- Node definitions and schema helpers: `backend/config/builtin_node_types.py`, `backend/config/node_schema.py`.
- Custom node runtime: `backend/control_plane/custom_node_runtime.py`; workflow normalization and group expansion: `backend/workflow_validation.py`.
- Optional GPU scheduling: `backend/gpu_service/`.
- Workflow definitions: `backend/config/workflows/`.
- Subtitle presets: `backend/config/subtitle_presets/`.
- Pi runtime model configuration: `data/workspace/pi-agent-config/models.json`.

## Working Method

For a request involving a workflow capability, first locate the relevant API router, node schema, workflow definition, and step implementation. Do not invent node fields or execution contracts when the repository already defines them.

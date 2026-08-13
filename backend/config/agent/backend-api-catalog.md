# Backend API Catalog

This catalog lists supported project APIs by mounted route group. Paths are relative to the main FastAPI backend at `http://127.0.0.1:11001` in the default local runtime. Endpoint implementation lives under `backend/api/`.

Authentication, registration, subscription, licensing, account, entitlement, and payment-related APIs are intentionally excluded. Do not inspect or call those APIs for account-control work.

## Operations and Workflows

- `/api/tasks`: task metadata, task CRUD, workflow payloads, execution, pause, cancellation, rollback, artifacts, and output opening.
- `/api/batch`: batch configuration, creation, execution, stop/resume, retry, task membership, cleanup, and worker-pool status.
- `/api/workflows`: workflow and workflow-group CRUD, validation/debug work, whole-workflow execution, node execution, task spawning, global save, and status.
- `/api/history`: completed and failed task history.
- `/api/node-types`: node definitions, schemas, validation, CRUD, import/export, backup, and restore.

## AI and Media Interfaces

- `/api/llm`: LLM configuration, presets, provider testing, chat, streaming chat, and batch inference.
- `/api/asr-interfaces`: ASR provider configuration, enabled engines, capabilities, testing, and reload.
- `/api/tts-interfaces` and `/api/tts-voices`: TTS provider/interface and voice configuration, testing, capabilities, refresh, and cleanup.
- `/api/imagegen-interfaces`: image generation interface CRUD, toggle/reload, balance, models, parameter schemas, and model management.
- `/api/separation-interfaces`: vocal/track separation interface CRUD, testing, models, and defaults.
- `/api/aigc`: AIGC capability configuration/status plus ComfyUI, RunningHub, and Jimeng checks.
- `/api/prompts`: prompt template listing, preview, editing, validation, and assembly.
- `/api/subtitle-presets` and `/api/subtitle-preview`: subtitle style presets and preview generation.

## Files, Editing, and Voice Production

- `/api/files`: project file browsing, upload/read/stream, native file dialogs, language data, audio scanning, and trim operations.
- `/api/editor`: editor project assets, project/character data, saving, streaming, and rendered export upload.
- `/api/editor/tasks/{task_id}/agent/*`: editor-agent execution, monitoring, approval, cancellation, and events.
- `/api/cutia/update`: embedded Cutia editor update.
- `/api/voiceforge`: VoiceForge projects, chapters, characters, sentences, text processing, synthesis, exports, cloning, emotion generation, and asset library management.

## Publishing, Community, and Pi

- `/api/publish`: social publishing platforms/accounts, tags, media inspection/upload, drafts, publish queues/tasks, history, service settings, and health.
- `/api/community`: workflow/node package publishing, analysis, import, and local package listing.
- `/api/pi`: Pi Agent runtime status, settings, extensions, sessions, history, prompt execution, session control, and SSE events.

## Control, Settings, and Diagnostics

- `/api/settings`: YAML-backed application configuration read/write.
- `/api/public-info`: public application metadata.
- `/api/control`: non-account Control Plane operations including presence, trusted LAN/remote mode, project/workflow versioning, audit, workspace files, assets, and checkpoints.
- `/api/health`, `/api/health/live`, `/api/health/ready`: service health and readiness.
- `/api/metrics`: metrics endpoint.
- `/api/restart`: manager-mediated restart response.

## WebSocket Groups

- `/ws/tasks/{task_id}`: task updates.
- `/ws/collaboration`: collaboration presence and events.
- `/ws/logs`: runtime logs.
- `/ws/voiceforge/projects/{project_id}/progress`: VoiceForge project progress.
- `/ws/voiceforge/voices/{voice_id}/progress`: voice-generation progress.

## API Use Rules

Confirm method, payload schema, and side effects in the owning router before invoking an endpoint. Prefer existing frontend clients under `frontend/src/api/` when changing UI behavior. Do not infer credentials or bypass normal project access controls.

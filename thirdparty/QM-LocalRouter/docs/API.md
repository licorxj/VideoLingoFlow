# API Reference

Base URL: http://127.0.0.1:8800

Interactive docs: http://127.0.0.1:8800/docs

---

## Proxy API

### Chat Completions

    POST /v1/chat/completions

OpenAI-compatible. model = strategy name.
### Text Completions

    POST /v1/completions

Legacy text completions. Converts to chat format internally.

### List Models

    GET /v1/models

Returns all active strategy names.

---

## Management API

### Providers

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/providers | List all providers |
| POST | /api/providers | Create provider |
| PUT | /api/providers/{id} | Update provider |
| DELETE | /api/providers/{id} | Delete provider |
| GET | /api/providers/hot-providers | Hot provider templates |

### API Keys

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/providers/{id}/keys | List keys |
| POST | /api/api-keys | Create key |
| PUT | /api/api-keys/{id} | Update key |
| DELETE | /api/api-keys/{id} | Delete key |
| POST | /api/api-keys/{id}/test | Test key |
| POST | /api/providers/{id}/keys/test-all | Batch test |
| DELETE | /api/providers/{id}/keys/invalid | Delete invalid |

### Models

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/providers/{id}/models | List models |
| POST | /api/models | Create model |
| PUT | /api/models/{id} | Update model |
| DELETE | /api/models/{id} | Delete model |
| POST | /api/models/sync/{id} | Sync from upstream |

### Strategies

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/strategies | List all strategies |
| POST | /api/strategies | Create strategy |
| PUT | /api/strategies/{id} | Update strategy |
| DELETE | /api/strategies/{id} | Delete strategy |
| POST | /api/strategies/{id}/test | Test strategy |

### Request Logs

    GET /api/logs?page=1&page_size=20

### Dashboard

    GET /api/dashboard/stats

---

## Settings API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/settings | Get settings |
| PUT | /api/settings | Update settings |

Output Protocol: openai, claude, gemini

---

## Icons API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/icons/search | Search Baidu Images |
| POST | /api/icons/save | Save icon locally |
| GET | /api/icons/file/{name} | Serve icon file |

---

## Backup & Restore API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/backup/config | Get backup config |
| PUT | /api/backup/config | Update backup config |
| POST | /api/backup/create | Create backup |
| GET | /api/backup/list | List backups |
| POST | /api/backup/restore-local?filename=xxx | Restore local |
| POST | /api/backup/restore | Upload and restore |
| GET | /api/backup/download/{name} | Download backup |
| DELETE | /api/backup/{name} | Delete backup |

---

## Health Check

    GET /api/health

Returns: status ok, version

# API Reference

Base URL: http://127.0.0.1:8800

Interactive docs: http://127.0.0.1:8800/docs

---

## Proxy API

One gateway, four client formats. The format is decided by the **endpoint**,
not by a global setting: the backend converts each inbound request to the
upstream protocol and converts the response back. When the client format and
the upstream protocol are identical the request is forwarded untouched
(no double conversion, no added latency).

| Client format | Endpoint | SDK setup |
|---------------|----------|-----------|
| OpenAI Chat Completions | `POST /v1/chat/completions` | base_url = `.../v1` |
| OpenAI Responses | `POST /v1/responses` | base_url = `.../v1` |
| Anthropic Messages | `POST /v1/messages` | base_url = `.../v1` |
| Gemini GenerateContent | `POST /v1beta/models/{model}:{action}` | base_url = `.../v1beta` |

Every endpoint uses the same routing (`model` = strategy name), load
balancing, key rotation, logging and token accounting.

### Model names: strategy or direct

`model` accepts either form:

| Form | Example | Behaviour |
|------|---------|-----------|
| Strategy name | `my-strategy` | Strategy routing: rules, LB method, retries and the strategy's **key policy** |
| `platform_id/model_id` | `33/opencode/ling-3.1-flash-free` | Direct call: skips the strategy, uses that platform's own **multi-key policy** |
| `platform_name/model_id` | `DeepSeek/deepseek-v4-flash` | Same as above (platform names containing `/` must use the id form) |

`model_id` may itself contain `/` (only the first `/` separates the platform
part). Strategy names are resolved first, so existing clients are unaffected.
In the platform page the copy button next to a model id copies the ready-to-use
`platform_id/model_id` string.

### Chat Completions

    POST /v1/chat/completions

OpenAI-compatible. model = strategy name.

### Responses API

    POST /v1/responses

OpenAI Responses API (Codex / Cline compatible). model = strategy name.

Request (subset):

    {
      "model": "my-strategy",
      "instructions": "You are concise.",
      "input": "hello",
      "max_output_tokens": 256,
      "stream": false
    }

`input` accepts a plain string or an array of items (`message` / `function_call` /
`function_call_output`). Internally the request is translated to
`/v1/chat/completions` and the result is converted back to a Response object
(`object: "response"`, `output[].content[].output_text`).

Streaming (`stream: true`) emits Responses SSE events in OpenAI order:
`response.created` -> `response.in_progress` -> `response.output_item.added` ->
`response.content_part.added` -> `response.output_text.delta`* ->
`response.output_text.done` -> `response.content_part.done` ->
`response.output_item.done` -> `response.completed` (no `data: [DONE]`).

Notes:
- Stateless: `store` is always reported as `false` and `previous_response_id`
  is ignored — send the full conversation history on every call.
- Errors are returned as `event: error` + `event: response.failed`
  (non-streaming: HTTP status + `{"error": {...}}`).
- Built-in tools (`web_search_preview`, `file_search`, ...) are dropped; only
  `function` tools are forwarded.

Key-in-path alias: `POST /k/{client_key}/v1/responses`.

### Anthropic Messages API

    POST /v1/messages

Anthropic-compatible (`system`, `messages`, `max_tokens`, `tools`,
`tool_choice`). Point the Claude SDK base URL at `/v1`; the strategy name goes
in `model`. Responses come back in Messages format (`type: "message"`,
`content[].text`, `stop_reason`, `usage.input_tokens/output_tokens`).

Streaming emits Anthropic events (`content_block_delta`, `message_stop`).

Alias: `POST /k/{client_key}/v1/messages`.

### Gemini GenerateContent

    POST /v1beta/models/{model}:generateContent
    POST /v1beta/models/{model}:streamGenerateContent
    GET  /v1beta/models

Gemini-compatible. Point the Gemini SDK base URL at `/v1beta`; the model
segment of the path is the strategy name. `contents`, `systemInstruction`,
`generationConfig`, `tools` are all accepted. `{model}` may contain `/`.

Streaming returns newline-delimited GenerateContent JSON objects.

Alias: `POST /k/{client_key}/v1beta/models/{model}:generateContent`,
`GET /k/{client_key}/v1beta/models`.

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

Provider records now carry the direct-mode key policy
(`key_strategy`, `key_switch_mode`, `key_rpm_threshold`,
`key_count_threshold`), settable via `PUT /api/providers/{id}` or the
"多key调用策略" button on the platform page.

Output Protocol: openai, responses, claude, gemini (legacy global override —
the per-endpoint format above takes precedence for /v1/responses, /v1/messages
and /v1beta/models/*)

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

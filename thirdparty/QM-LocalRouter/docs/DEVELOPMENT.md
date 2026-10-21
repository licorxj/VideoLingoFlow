# Developer Guide | 开发者文档

This document is for developers contributing to or extending the LocalRouter project.

---

## Table of Contents

1. [Development Environment Setup](#development-environment-setup)
2. [Project Architecture](#project-architecture)
3. [Backend Development](#backend-development)
4. [Frontend Development](#frontend-development)
5. [Internationalization (i18n)](#internationalization)
6. [Database Migration](#database-migration)
7. [Protocol Adapter Layer](#protocol-adapter-layer)
8. [Load Balancing Engine](#load-balancing-engine)
9. [Output Protocol Conversion](#output-protocol-conversion)
10. [Testing](#testing)
11. [Build & Deploy](#build--deploy)
12. [Contributing](#contributing)

---

## Development Environment Setup

### Prerequisites

- **Python** 3.10+ (3.12 recommended)
- **Node.js** 18+ (20 LTS recommended)
- **Git**, **pip**, **npm**

### Backend

`ash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
`

### Frontend

`ash
cd frontend
npm install
`

### Start Dev Servers

**Terminal 1 (Backend):**
`ash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8800 --reload
`

**Terminal 2 (Frontend):**
`ash
cd frontend
npm run dev
`

The Vite dev server proxies /api/* and /v1/* to http://127.0.0.1:8800.

---

## Project Architecture

### Request Forwarding Flow

`
Client -> POST /v1/chat/completions (model="strategy-name")
         or POST /v1/responses (model="strategy-name")
  -> proxy.py: resolve strategy
  -> balancer.py: select rule + key
  -> forwarder.py: protocol adapt + send to upstream
  -> Receive response (streaming/non-streaming)
  -> Output protocol conversion (if needed)
  -> Log request
  -> Return to client
`

### Directory Structure

#### Backend (ackend/)

| Path | Description |
|------|-------------|
| pp/main.py | FastAPI entry, router registration, middleware, lifespan |
| pp/config.py | pydantic-settings config, .env support |
| pp/database.py | Async SQLAlchemy engine, session factory, table init |
| pp/models/ | SQLAlchemy ORM models (Provider, ApiKey, Model, Strategy, StrategyRule, RequestLog) |
| pp/schemas/schemas.py | Pydantic request/response models |
| pp/routers/ | API route handlers |
| pp/routers/proxy.py | Core proxy endpoints (/v1/chat/completions, /v1/responses, /v1/models) |
| pp/routers/settings.py | App settings (output protocol, etc.) |
| pp/routers/icons.py | Icon search (Baidu) + local storage |
| pp/routers/backup.py | Backup/restore with auto-backup |
| pp/services/balancer.py | Load balancing engine (5 strategies) |
| pp/services/forwarder.py | HTTP request forwarding with retry |
| pp/services/stream_handler.py | SSE stream processing |
| pp/utils/protocol_adapter.py | Claude/Gemini <-> OpenAI format conversion, Responses <-> chat conversion |
| pp/utils/crypto.py | Fernet symmetric encryption for API keys |

#### Frontend (rontend/)

| Path | Description |
|------|-------------|
| src/pages/ | Page components (Dashboard, Providers, Strategies, Logs, Settings) |
| src/components/ui/ | shadcn/ui base components |
| src/components/layout/ | Layout components (Sidebar) |
| src/services/api.ts | Axios instance + all API call functions |
| src/stores/ | Zustand state management (toast notifications) |
| src/i18n/ | Internationalization (en-US.json, zh-CN.json) |
| src/lib/utils.ts | Utility functions (cn class name merge, etc.) |

---

## Backend Development

### Adding a New API Route

1. Create/edit route file in ackend/app/routers/:

`python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

router = APIRouter(prefix="/api/my-endpoint", tags=["my-tag"])

@router.get("")
async def my_handler(db: AsyncSession = Depends(get_db)):
    return {"message": "hello"}
`

2. Register in pp/main.py:

`python
from app.routers import my_module
app.include_router(my_module.router)
`

### Adding a New Data Model

1. Create model in ackend/app/models/:

`python
from sqlalchemy import Column, Integer, String
from app.database import Base

class MyModel(Base):
    __tablename__ = "my_table"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
`

2. Add Pydantic schema in pp/schemas/schemas.py:

`python
class MyModelCreate(BaseModel):
    name: str = Field(..., max_length=100)

class MyModelOut(BaseModel):
    id: int
    name: str
    class Config:
        from_attributes = True
`

3. Tables auto-created by pp/database.py init_db().

### Environment Variables

In ackend/.env:

`env
HOST=127.0.0.1
PORT=8800
LOG_RETENTION_DAYS=30
DEFAULT_TIMEOUT=120
DEFAULT_RETRY_COUNT=2
`

---

## Frontend Development

### Page Development

Pages are in src/pages/, use React Router for navigation:

`	sx
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getMyData, createMyData } from "../services/api";
import { useI18n } from "../i18n";

export default function MyPage() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const { data = [] } = useQuery({
    queryKey: ["my-data"],
    queryFn: () => getMyData().then(r => r.data),
  });

  return <div>{t('myPage.title')}</div>;
}
`

### Adding API Calls

In src/services/api.ts:

`	ypescript
export const getMyData = () => api.get("/api/my-endpoint");
export const createMyData = (data: any) => api.post("/api/my-endpoint", data);
`

### UI Components

Use shadcn/ui components from src/components/ui/:

`	sx
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Dialog, DialogContent } from "../components/ui/dialog";
`

---

## Internationalization

### How It Works

- Translation files: src/i18n/en-US.json and src/i18n/zh-CN.json
- Hook: const { t, locale, setLocale } = useI18n();
- Usage: 	('providers.title') resolves to "Upstream Providers" or "上游平台"

### Adding New Translations

1. Add key to both en-US.json and zh-CN.json:

`json
{
  "mySection": {
    "title": "My Section",
    "description": "Description text"
  }
}
`

2. Use in component:

`	sx
<h1>{t('mySection.title')}</h1>
<p>{t('mySection.description')}</p>
`

### Guidelines

- Use flat dot-notation keys: section.subsection.key
- Always update both language files
- Keep translations concise
- For dynamic content, use template patterns: 	('key') + variable

---

## Database Migration

SQLite is used. New columns are added via _add_missing_columns() in database.py:

`python
# In database.py _add_missing_columns()
("my_table", "new_column", "VARCHAR(100) DEFAULT ''"),
`

---

## Protocol Adapter Layer

### OpenAI Protocol
Input and output are OpenAI Chat Completions format, no conversion needed.

### Claude (Anthropic) Protocol
- **Request**: OpenAI messages -> Anthropic Messages API (system param, messages array, model, 	emperature, max_tokens)
- **Response**: Anthropic response -> OpenAI format (content[0].text -> choices[0].message.content)

### Gemini (Google) Protocol
- **Request**: OpenAI messages -> Gemini GenerateContent (contents + 
ole mapping, generationConfig)
- **Response**: Gemini response -> OpenAI format (candidates[0].content.parts[0].text -> choices[0].message.content)

### Responses Protocol
Used in both directions, all in `app/utils/protocol_adapter.py`:

- **Inbound** (`POST /v1/responses`): Responses request -> chat body
  (`responses_request_to_chat`: `instructions` -> leading system message,
  `input` string/array -> `messages`, `max_output_tokens` -> `max_tokens`,
  function tools -> chat tools). Chat results are converted back with
  `chat_completion_to_response` (usage renamed to
  `input_tokens`/`output_tokens`/`total_tokens`, `finish_reason` mapped to
  `status` + `incomplete_details`, `tool_calls` -> `function_call` items).
- **Streaming**: `ResponsesStreamWriter` accumulates `chat.completion.chunk`
  deltas and emits the official event sequence
  (`response.created` ... `response.output_text.delta`* ... `response.completed`),
  with monotonic `sequence_number` and no `data: [DONE]` terminator. Failures
  become `event: error` + `event: response.failed`.
- **Outbound** (Codex OAuth upstream, `upstream_style == "responses"`):
  `chat_to_responses_request` / `responses_to_chat` /
  `responses_stream_chunk_to_chat`.

The inbound endpoint is stateless: `store` is always `false` and
`previous_response_id` is ignored.

### Anthropic / Gemini client formats
`POST /v1/messages` and `POST /v1beta/models/{rest:path}` translate the inbound
request with `claude_request_to_chat` / `gemini_request_to_chat`
(`system`/`systemInstruction` -> system message, content blocks/parts ->
OpenAI content blocks, `generationConfig` -> temperature/top_p/max_tokens,
tools -> chat tools) and convert results back with `openai_to_claude_response` /
`openai_to_gemini_response` plus the streaming variants
`convert_openai_stream_to_claude_chunks` /
`convert_openai_stream_to_gemini_chunks`. Chunks that cannot be represented in
the target format (e.g. `reasoning_content`) are dropped instead of leaked, and
the OpenAI `data: [DONE]` terminator is not forwarded.

The format is chosen per endpoint (`out_format` in `proxy.py`); the global
`output_protocol` setting only remains as a legacy override for
`/v1/chat/completions`.

### Direct model names (`platform_id/model_id`)
`proxy._resolve_direct_model` splits on the **first** `/` (model ids may contain
`/`), resolves the platform by numeric id or by unique name, then the model by
`model_id` or `display_name`. `_dispatch_by_model` resolves strategy names first
and only falls back to direct mode, so existing clients are unaffected;
`_forward_direct` builds a pseudo strategy whose `key_*` fields come from the
new provider columns (`key_strategy`, `key_switch_mode`, `key_rpm_threshold`,
`key_count_threshold`, added in `database._add_missing_columns`), so
`Balancer.select_key` applies the platform multi-key policy — strategy routing
keeps using the strategy's own policy. Auth (401/403) and 429 failures mark the
key like `_try_forward` does.

### Passthrough (same format)
`Forwarder._passthrough_plan` forwards the request byte-for-byte when the client
format equals the upstream protocol (`custom` counts as OpenAI): same URL
(`/messages`, `:generateContent`, `chat_path`), same auth headers, no
messages<->protocol conversion in either direction. Skipped for CLI profiles
(opencode/cline/workbuddy), `upstream_style == "responses"` and non-bearer
upstream auth. `_handle_non_stream` / `_handle_stream` detect the same condition
via `_raw_body` + `_client_format` and return the upstream body/frames verbatim,
extracting tokens from `usage`, `message_start`/`message_delta` or
`usageMetadata` for logging.

### OpenCode upstream retry events
When the OpenCode upstream fails (e.g. `Upstream request failed: Model is
unavailable.`), `opencode serve` does **not** emit `message.updated.error`
immediately: it first sends `session.status{type:"retry", attempt, message}` and
retries on its own (4 attempts, 5s/10s/20s/40s backoff). No text delta arrives
during that window, so a collector that only checks `message.updated.error` is cut
off by the 45s idle timeout and returns HTTP 200 with `content: null`, losing the
real error. `OpenCodeClient._collect` therefore records the retry message and
treats it as activity; a collect that ends on idle/first-delta timeout returns the
recorded message as an error, which the caller turns into HTTP 502. The full list
of SSE pitfalls is documented at the top of `services/opencode.py`.

---

## Load Balancing Engine

### Model-level Strategies

| Strategy | Description |
|----------|-------------|
| 
ound_robin | Sequential rotation |
| weighted | Weight-proportional distribution |
| 
andom | Random selection |
| ailover | Priority-based, switch on failure |
| priority | Always highest priority |

### Key-level Strategies

| Strategy | Description |
|----------|-------------|
| 
ound_robin | Round-robin across keys |
| 
andom | Random key selection |
| ailover | Use first key, switch on failure |

### Key Switch Triggers

| Mode | Description |
|------|-------------|
| 
one | No automatic switching |
| 
pm_threshold | Switch when requests/min exceeds threshold |
| count_threshold | Switch when total requests exceed threshold |

---

## Output Protocol Conversion

The system supports converting the response format before returning to clients:

- **openai** (default): Standard OpenAI format
- **responses**: Converts to the OpenAI Responses API format (same objects the
  `/v1/responses` endpoint returns; non-streaming `object: "response"`,
  streaming `response.*` SSE events). Only function tools survive the round trip.
- **claude**: Converts to Anthropic Messages API format
- **gemini**: Converts to Gemini GenerateContent format

Configurable via Settings page or GET/PUT /api/settings.

---

## Build & Deploy

### Frontend Build

`ash
cd frontend
npm run build
`

Output: rontend/dist/

### Backend Deploy

`ash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8800 --workers 4
`

---

## Contributing

1. Fork the project
2. Create feature branch (git checkout -b feature/amazing-feature)
3. Commit changes (git commit -m 'Add amazing feature')
4. Push to branch (git push origin feature/amazing-feature)
5. Create Pull Request

### Code Standards

- Backend: PEP 8
- Frontend: TypeScript strict mode
- All files: UTF-8 without BOM
- Commit messages: English, concise

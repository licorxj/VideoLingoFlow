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
| pp/routers/proxy.py | Core proxy endpoints (/v1/chat/completions, /v1/models) |
| pp/routers/settings.py | App settings (output protocol, etc.) |
| pp/routers/icons.py | Icon search (Baidu) + local storage |
| pp/routers/backup.py | Backup/restore with auto-backup |
| pp/services/balancer.py | Load balancing engine (5 strategies) |
| pp/services/forwarder.py | HTTP request forwarding with retry |
| pp/services/stream_handler.py | SSE stream processing |
| pp/utils/protocol_adapter.py | Claude/Gemini <-> OpenAI format conversion |
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

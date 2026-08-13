# LocalRouter

> **Your Local LLM API Routing Manager** | 你的本地 API 路由管家

> **English** | [中文](README_ZH.md)

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

<p align="center">
  <img src="docs/images/%E4%B8%BB%E9%A1%B5.png" alt="LocalRouter Dashboard Preview" width="800">
</p>

---

## Highlights

- **⚡ Local One-Stop Management** — Centrally manage all your upstream AI providers (OpenAI, Anthropic, Google Gemini, DeepSeek, and 50+ more) in one local dashboard
- **🔄 Multi-Strategy Intelligent Routing** — 5 load-balancing strategies (Round Robin, Weighted, Random, Failover, Priority) with automatic failover
- **🔑 Multi-Key Load Balancing** — Distribute requests across multiple API keys per provider with RPM/count threshold switching
- **🤖 Multi-Model Auto Scheduling** — Automatically route to the best available model based on strategy rules
- **🛡️ Protocol Auto-Conversion** — Seamless conversion between OpenAI, Claude, and Gemini formats — use any SDK to call any model
- **🔒 Zero Public Exposure** — Runs entirely on your local machine; no data leaves your network
- **🌐 LAN Sharing** — Once deployed, all devices on your local network can share API keys and strategies through a single access point

---

## Why LocalRouter?

Managing multiple LLM providers is painful. Each has its own API format, billing, and rate limits. You need multiple API keys, multiple SDKs, and manual failover handling.

**LocalRouter solves this** by providing a single OpenAI-compatible endpoint that handles:

| Problem | Solution |
|---------|----------|
| Multiple provider SDKs | Single OpenAI-compatible API |
| API key sprawl | Centralized key management with encryption |
| Provider outages | Automatic failover between providers |
| Rate limiting | Multi-key rotation with intelligent switching |
| Format differences | Auto-convert between OpenAI/Claude/Gemini |
| Model discoverability | One-click sync from upstream + built-in model database |

---

## 🌐 LAN Network Advantages

LocalRouter is designed for **local area network (LAN)** deployment from day one. Once you enable LAN access in Settings, every device on your network benefits:

| Advantage | Description |
|-----------|-------------|
| **💰 Cost Sharing** | One API key subscription serves your entire team — no per-device licensing |
| **🔑 Centralized Key Management** | Add/rotate API keys in one place, all LAN devices use them automatically |
| **📋 Unified Strategy Control** | Define routing rules once, all team members share the same intelligent routing |
| **⚡ Zero Latency Overhead** | Local network forwarding adds <1ms — no cloud relay delays |
| **🔒 Data Privacy** | All API requests stay within your LAN; no data passes through external gateways |
| **🖥️ Cross-Platform** | Windows, macOS, Linux, iOS, Android — any device with an HTTP client works |
| **🔌 Plug-and-Play** | Compatible with all OpenAI SDK clients — Cursor, ChatBox, CherryStudio, Open WebUI |

**Typical use cases:**
- Team shares one set of API keys across all workstations
- Mobile devices access LLM APIs without installing SDKs
- IoT devices integrate AI capabilities through a local endpoint
- CI/CD pipelines use the same routing strategy as development

---

## Features

### Provider Management
- Structured management of upstream providers (name, protocol, base URL, icon)
- One-click icon search via image search engines
- 65+ hot provider templates for instant setup
- Enable/disable providers individually

### API Key Management
- Per-provider API key grouping with aliases
- Key health detection (active/inactive/untested) via automatic testing
- Batch test all keys, batch delete invalid keys
- Weighted distribution for load balancing
- **Encrypted storage** — keys encrypted at rest using Fernet symmetric encryption

### Model Management
- Per-provider model management with detailed attributes
- One-click sync from upstream API with intelligent parameter detection
- **Sync dialog** with select-all/invert/batch-add support
- Built-in **known models database** with 100+ pre-configured models
- Automatic model type detection (text/image/video/TTS/embedding)

### Routing Strategies
| Strategy | Description |
|----------|-------------|
| **Round Robin** | Sequential rule rotation |
| **Weighted** | Weight-proportional distribution |
| **Random** | Random rule selection |
| **Failover** | Priority-based, switch on failure |
| **Priority** | Always use highest priority |

### Key Strategies
| Strategy | Description |
|----------|-------------|
| **Round Robin** | Sequential key rotation |
| **Random** | Random key selection |
| **Failover** | Use first key, switch on failure |
| **RPM Threshold** | Auto-switch when requests/min exceeds threshold |
| **Count Threshold** | Auto-switch when total requests exceed threshold |

### Protocol Support
- **OpenAI** — Native compatibility (GPT, o1, o3 series, DALL-E, TTS, Whisper)
- **Anthropic Claude** — Automatic format conversion from OpenAI format
- **Google Gemini** — Automatic format conversion from OpenAI format
- **Custom** — Any OpenAI-compatible endpoint

### Observability
- **Dashboard** — Today's request stats, success rate, latency, token usage
- **Request Logs** — Full searchable request history with filters by strategy/provider/status
- **Strategy Testing** — Test routing chains before production use

### Settings
- Dark/Light theme
- **Bilingual UI** — Chinese and English
- **Output Protocol** — Return responses in OpenAI, Claude, or Gemini format
- **Backup & Restore** — Manual/auto backup with configurable scheduling

---

## Architecture

```
Client (OpenAI SDK / Third-party App)
  |
  | POST /v1/chat/completions (model="strategy-name")
  v
[proxy.py] -- Resolve strategy by model name
  |
  v
[balancer.py] -- Select routing rule + API key
  |                (5 LB strategies / 3 key strategies)
  v
[forwarder.py] -- Protocol adaptation + upstream request
  |                (OpenAI / Claude / Gemini)
  v
[protocol_adapter.py] -- Optional output format conversion
  |
  v
[stream_handler.py] -- SSE streaming handling
  |
  v
Client <--- Standard OpenAI format response
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+

### 1. Clone & Initialize

```bash
git clone https://github.com/licorxj/QM-LocalRouter.git
cd QM-LocalRouter

# Initialize database (creates venv, installs deps, creates database)
cd scripts
python init_db.py        # cross-platform Python script
# or: ./init_db.sh       # Linux/macOS
# or: init_db.bat        # Windows
cd ..
```

### 2. Start Services

**Option A: Using management scripts (recommended)**

```bash
# Linux/macOS
chmod +x scripts/manage.sh
./scripts/manage.sh start

# Windows
scripts\manage.bat start
```

**Option B: Manual start**

```bash
# Terminal 1 - Backend
cd backend
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS
uvicorn app.main:app --host 0.0.0.0 --port 12002

# Terminal 2 - Frontend
cd frontend
npm install
npm run dev
```

### 3. Use

1. Open **http://localhost:12001** in your browser
2. Go to **Providers** page, click **+** to add a provider (or use **Hot Providers**)
3. Add an API key under the provider
4. Add models — either manually, via **Sync**, or use the **Sync Provider Models** dialog
5. Go to **Strategies**, create a strategy with routing rules
6. In your client, set `base_url` to `http://localhost:12002/v1` and `model` to your strategy name

---

## Tech Stack

| Layer | Technology | Description |
|-------|-----------|-------------|
| Frontend | React 18 + TypeScript + Vite 5 | SPA with fast HMR |
| UI | shadcn/ui + Tailwind CSS 3 | Modern accessible components |
| State | Zustand + TanStack Query 5 | Lightweight state + server cache |
| i18n | Custom React Context | Chinese / English |
| Backend | Python 3.10+ + FastAPI + uvicorn | Async high-performance API |
| Database | SQLite + SQLAlchemy 2.0 (async) | Zero-config local storage |
| Encryption | cryptography (Fernet) | AES-128 API key encryption |
| HTTP | httpx (async) | Upstream API forwarding |

---

## API Overview

All proxy endpoints are at `/v1/` and are fully compatible with the OpenAI SDK.

| Endpoint | Description |
|----------|-------------|
| `POST /v1/chat/completions` | Chat completions (streaming + non-streaming) |
| `POST /v1/completions` | Text completions |
| `POST /v1/embeddings` | Embeddings proxy |
| `POST /v1/images/generations` | Image generation proxy |
| `POST /v1/audio/speech` | Text-to-speech proxy |
| `POST /v1/videos` | Video generation proxy |
| `GET /v1/models` | List active strategies |

Management API at `/api/` (Swagger UI: `http://localhost:12002/docs`)

Full API reference: [docs/API.md](docs/API.md)

---

## Client Configuration

| Client | Configuration |
|--------|--------------|
| **OpenAI SDK** | `base_url="http://localhost:12002/v1"`, `api_key="any-value"` |
| **ChatBox** | Settings > Custom API > Base URL: `http://localhost:12002/v1` |
| **CherryStudio** | Settings > Add Custom API > Base URL: `http://localhost:12002/v1` |
| **LobeChat** | Settings > Add Custom Model > API URL: `http://localhost:12002/v1` |
| **Open WebUI** | `OPENAI_API_BASE_URL=http://localhost:12002/v1` |
| **Cursor** | Settings > Models > Base URL: `http://localhost:12002/v1` |
| **curl** | See below |

```bash
curl http://localhost:12002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"my-strategy","messages":[{"role":"user","content":"Hello!"}]}'
```

> **Note**: You can use any value for `api_key`. The `model` field must be your strategy name.

---

## Documentation

| Document | Description |
|----------|-------------|
| [README_ZH.md](README_ZH.md) | 中文文档 |
| [docs/USAGE.md](docs/USAGE.md) | Complete user guide |
| [docs/USAGE_ZH.md](docs/USAGE_ZH.md) | 中文使用教程 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Deployment guide (Docker, VPS, Windows, Linux) |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Developer guide |
| [docs/API.md](docs/API.md) | API reference |
| [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) | Dependency list |

---

## Contact & Support

If you find this project helpful, feel free to reach out or support it:

<div align="center">
  <table>
    <tr>
      <td align="center">
        <strong>Contact (WeChat)</strong><br>
        <img src="docs/images/contact-qr.jpg" width="200" alt="Contact QR Code"><br>
        <em>Scan to add me as a friend</em>
      </td>
      <td align="center">
        <strong>Support (WeChat Pay)</strong><br>
        <img src="docs/images/donate-qr.png" width="200" alt="Donation QR Code"><br>
        <em>Scan to support the project</em>
      </td>
    </tr>
  </table>
</div>

---

## License

MIT License

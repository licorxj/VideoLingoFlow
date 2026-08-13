﻿# LocalRouter - User Guide

> **English** | [中文](USAGE_ZH.md)

---

## Table of Contents

1. [Installation & Startup](#installation--startup)
2. [Adding Providers](#adding-providers)
3. [Managing API Keys](#managing-api-keys)
4. [Managing Models](#managing-models)
5. [Sync Provider Models Dialog](#sync-provider-models-dialog)
6. [Creating Routing Strategies](#creating-routing-strategies)
7. [Sending Requests](#sending-requests)
8. [Viewing Request Logs](#viewing-request-logs)
9. [Dashboard](#dashboard)
10. [Settings](#settings)
11. [Data Backup & Restore](#data-backup--restore)
12. [FAQ](#faq)

---

## Installation & Startup

### Quick Start (Recommended)

```bash
# 1. Initialize database
cd scripts
python init_db.py          # Cross-platform
# ./init_db.sh             # Linux/macOS
# init_db.bat              # Windows
cd ..

# 2. Start all services
# Linux/macOS
chmod +x scripts/manage.sh
./scripts/manage.sh start

# Windows
scripts\manage.bat start
```

### Manual Start

```bash
# Terminal 1 - Backend
cd backend
venv\Scripts\activate                # Windows
# source venv/bin/activate            # Linux/macOS
uvicorn app.main:app --host 0.0.0.0 --port 12002

# Terminal 2 - Frontend
cd frontend
npm install
npm run dev
```

Open http://localhost:12001 in your browser.

---

## Adding Providers

The **Providers** page combines provider, API key, and model management in one interface.

### Manual Add

1. Click the **"+"** (Plus) button in the top-right
2. Fill in:
   - **Name** 鈥?e.g., OpenAI, DeepSeek
   - **Protocol** 鈥?openai / gemini / claude / custom
   - **Base URL** 鈥?With auto-complete, just enter the domain (e.g., `https://api.openai.com`). With it off, enter the full API path
   - **Homepage** 鈥?Optional, the provider's website URL
   - **Description** 鈥?Optional notes
3. Click **Save**

### Hot Provider Quick-Add

1. Click **"Hot Providers"** button
2. Browse or search providers (fuzzy search matches name, protocol, and description)
3. Click a provider to auto-fill name, protocol, base URL, icon, and homepage
4. Confirm and save

### Provider Icon

- Click **"Search Icon"** in the add/edit dialog
- Enter keywords to search (e.g., "openai")
- Select from the 3脳3 image grid
- Supports Baidu, Bing, and Sogou image search engines

### Protocol Reference

| Protocol | Description | Base URL Example |
|----------|-------------|-----------------|
| **openai** | OpenAI compatible API | `https://api.openai.com/v1` |
| **gemini** | Google Gemini API | `https://generativelanguage.googleapis.com/v1beta` |
| **claude** | Anthropic Claude API | `https://api.anthropic.com/v1` |
| **custom** | Custom OpenAI-compatible | Any URL |

---

## Managing API Keys

After selecting a provider, the right panel shows its API keys in the top section.

### Add Key

1. Click **"Add Key"**
2. Paste the API key value
3. Set an alias (e.g., "Primary", "Backup")
4. Set weight (default 1, for weighted load balancing)
5. Save

### Key Status

| Status | Color | Description |
|--------|-------|-------------|
| **Active** | Green | Tested and working |
| **Invalid** | Red | Tested but not working |
| **Untested** | Gray | Not yet tested |

### Batch Operations

- **Test All** 鈥?Check all keys at once against the upstream API
- **Delete Invalid** 鈥?Remove all keys with "Invalid" status

### Copy Key

Click the **Copy** icon next to any key to copy its **real (decrypted) value** to clipboard.

### Key Encryption

All API keys are encrypted at rest using Fernet symmetric encryption (AES-128). The encryption key is auto-generated and stored in `backend/data/.encryption_key`.

---

## Managing Models

The right panel's bottom section shows models for the selected provider.

### Add Model Manually

1. Click **"Add Model"**
2. Fill in:
   - **Model ID** 鈥?Upstream model name (e.g., `gpt-4o`, `claude-3-opus`)
   - **Display Name** 鈥?Optional friendly name
   - **Model Type** 鈥?Text / Image / Video / TTS / Embedding
   - **Multimodal** 鈥?Toggle if model supports image/audio/video input
   - **Context Window** 鈥?Max tokens (preset options: 4K/8K/16K/32K/64K/128K/200K/1M)
   - **Temperature** 鈥?Default temperature (0鈥?)
   - **Input Price** 鈥?Price per million input tokens
   - **Output Price** 鈥?Price per million output tokens
3. Save

### Sync from Upstream

Click **"Sync Provider Models"** to fetch available models from the upstream API. This opens a dialog that:
- Shows all models from the upstream provider
- Automatically detects model parameters (type, context window, pricing)
- Marks already-added models as "Added"
- Supports selecting models to add

**See next section for details.**

---

## Sync Provider Models Dialog

The Sync dialog provides a powerful interface for browsing and adding upstream models.

### Opening the Dialog

Click the **"Sync Provider Models"** button in the Models section toolbar.

### Dialog Features

- **Model List** 鈥?Displays each model with:
  - Checkbox for selection
  - Model ID (with copy button)
  - Display name
  - Model type (with color-coded badge)
  - Multimodal indicator
  - Context window
  - Input/Output pricing
  - Individual **Add** button
- **Already Added** 鈥?Models already in your database are shown with 50% opacity and an "Added" badge
- **Select All** 鈥?Selects all addable models at once
- **Invert** 鈥?Inverts the current selection
- **Batch Add** 鈥?Adds all selected models with one click
- **Selection Count** 鈥?Shows how many models are currently selected

### Adding Models

**Individual Add:**
Click the **Add** button on any model's row to add it immediately.

**Batch Add:**
1. Select models using checkboxes (or use Select All/Invert)
2. Click **Batch Add (N)** button in the toolbar
3. Result shows "Added X, failed Y" after completion

---

## Creating Routing Strategies

Routing strategies define how requests are forwarded to upstream providers.

### Create a Strategy

1. Go to the **Strategies** page
2. Click **"Create Strategy"**
3. Fill in:

**Basic Info:**
- **Strategy Name** 鈥?Used as the `model` field in client requests
- **Load Balancing** 鈥?Choose the balancing method
- **Description** 鈥?Optional notes

**Key Strategy:**
- **Key Selection** 鈥?How to choose API keys (Round Robin / Random / Failover)
- **Key Switch Trigger** 鈥?None / RPM threshold / Count threshold

**Advanced:**
- **Timeout** 鈥?Request timeout in seconds (default 120)
- **Retry Count** 鈥?Number of retries on failure (default 2)
- **Enable** 鈥?Toggle strategy on/off

4. **Add Routing Rules**: Select provider + model, set priority and weight, click "Add"
5. Click **"Create"**

### Load Balancing Strategies

| Strategy | Description |
|----------|-------------|
| **Round Robin** | Use rules in order, cycling through sequentially |
| **Weighted** | Distribute by weight ratio (e.g., 3:1 = 75%:25%) |
| **Random** | Randomly select a rule each time |
| **Failover** | Use highest priority; switch to next on failure |
| **Priority** | Always use the highest priority rule |

### Key Strategies

| Strategy | Description |
|----------|-------------|
| **Round Robin** | Cycle through keys sequentially |
| **Random** | Randomly select a key |
| **Failover** | Use the first key; switch to next on failure |

### Key Switch Triggers

| Mode | Description |
|------|-------------|
| **None** | No automatic switching |
| **RPM** | Switch when requests/minute exceeds the threshold |
| **Count** | Switch when total requests exceed the threshold |

### Strategy Test

Click **"Test"** on a strategy card to send a test request and verify the routing chain works.

---

## Sending Requests

### Request Format

```
POST http://localhost:12002/v1/chat/completions
```

```json
{
  "model": "your-strategy-name",
  "messages": [{"role": "user", "content": "Hello!"}],
  "stream": false
}
```

- **model**: Your strategy name (NOT the upstream model name)
- **messages**: Standard OpenAI chat messages format
- **stream**: Set to `true` for SSE streaming

### curl Example

```bash
curl http://localhost:12002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"my-strategy","messages":[{"role":"user","content":"Write a poem"}],"stream":true}'
```

### OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:12002/v1",
    api_key="any-value",  # Can be any string
)

response = client.chat.completions.create(
    model="my-strategy",  # Strategy name
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### Third-party Client Setup

| Client | Instructions |
|--------|-------------|
| **ChatBox** | Settings > Custom API > Base URL: `http://localhost:12002/v1` |
| **CherryStudio** | Settings > Add Custom API > Base URL: `http://localhost:12002/v1` |
| **LobeChat** | Settings > Add Custom Model > API URL: `http://localhost:12002/v1` |
| **Open WebUI** | `OPENAI_API_BASE_URL=http://localhost:12002/v1` |
| **Cursor** | Settings > Models > Base URL: `http://localhost:12002/v1` |
| **Continue (VS Code)** | Add model + OpenAI-compatible provider, set Base URL accordingly |

> **Note**: You can use any value for `api_key`. The `model` field must be your strategy name.

---

## Viewing Request Logs

The **Request Logs** page shows all proxied requests.

| Column | Description |
|--------|-------------|
| **Time** | When the request was made |
| **Strategy** | Routing strategy used |
| **Provider** | Upstream provider used |
| **Model** | Actual upstream model name |
| **Key** | API key used (alias) |
| **Status** | HTTP status code |
| **Latency** | Response time in milliseconds |
| **Tokens** | Prompt / Completion / Total |
| **Stream** | Whether streaming was used |
| **Error** | Error message (if any) |

### Filtering

Filter the log list by:
- **Strategy** 鈥?Show only specific strategy
- **Provider** 鈥?Filter by upstream provider
- **Status** 鈥?Status code filter
- **Time Range** 鈥?Custom date/time range

---

## Dashboard

The **Dashboard** provides a global overview:

- **Today's Requests** 鈥?Total count, success rate, average latency
- **Token Usage** 鈥?Prompt tokens, completion tokens, total tokens
- **Active Resources** 鈥?Strategies, providers, and keys in use
- **Service Status** 鈥?Backend service running indicator

---

## Settings

The **Settings** page (gear icon in sidebar) provides:

### Network Access
- **Enable LAN Access** 鈥?Toggle to allow other devices on the same local network to access LocalRouter
- When enabled, the actual LAN IP address is auto-detected and displayed
- Use the displayed LAN address (e.g., `http://192.168.1.100:12002/v1`) from other devices on your network
- The proxy address and curl example in the Proxy Configuration section update automatically based on this setting

### Appearance
- **Theme** 鈥?Dark / Light mode
- **Language** 鈥?Chinese / English

### Proxy Configuration
- Displays the proxy address to configure in your client
- Shows a curl example for quick testing

### Output Protocol
| Mode | Description |
|------|-------------|
| **OpenAI Format** | Default 鈥?compatible with most clients |
| **Claude Format** | Anthropic Messages API format |
| **Gemini Format** | Gemini GenerateContent format |

### Route Management
- **Default Model** 鈥?Default model for router management (leave empty for strategy-based routing)

### Backup & Restore

**Auto Backup:**
1. Set backup folder (default: `backend/data/backups/`)
2. Enable auto-backup and set interval (hours)
3. System auto-backs up on startup and at configured intervals

**Manual Backup:**
Click **"Create Backup Now"** to create an immediate backup.

**Restore:**
- **From list**: Click "Restore" on any backup entry
- **Upload file**: Click "Upload & Restore" and select a `.db` file

> **Warning**: Restore replaces all current data. It's recommended to create a backup first.

---

## FAQ

### Q: Can't connect to LocalRouter?
- Is the backend running on port 12002?
- Is the frontend running on port 12001?
- Is your client Base URL set to `http://localhost:12002/v1`?

### Q: "Strategy not found" error?
- Is the strategy created and enabled?
- Is the `model` field set to the strategy name (not the upstream model name)?

### Q: Request timeout?
- Increase timeout in the strategy settings
- Check your network connectivity to the upstream provider
- Check your upstream API key balance/quota

### Q: How to see which key was used?
- Check the **Request Logs** page
- Each log entry shows the strategy, provider, and key used

### Q: Are API keys secure?
- Keys are encrypted with Fernet symmetric encryption (AES-128)
- Stored in a local SQLite database
- The system runs locally only 鈥?no public exposure

### Q: How to backup my data?
- Use the **Settings > Backup & Restore** page
- Enable auto-backup for scheduled backups
- Or copy the `backend/data/app.db` file manually

### Q: Can I use LocalRouter in production?
- Yes. For production, use the management script (`scripts/manage.sh`) or Docker deployment
- Set up nginx reverse proxy with HTTPS for public access
- Use a process manager (systemd, supervisor) for auto-restart

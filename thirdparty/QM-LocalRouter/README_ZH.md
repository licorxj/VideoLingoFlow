# LocalRouter

> **你的本地 API 路由管家** | Your Local LLM API Routing Manager

> [English](README.md) | **中文**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

<p align="center">
  <img src="docs/images/%E4%B8%BB%E9%A1%B5.png" alt="LocalRouter 界面预览" width="800">
</p>

---

## 核心亮点

- **⚡ 本地一站式管理** — 集中管理所有上游 AI 平台（OpenAI、Anthropic、Google Gemini、DeepSeek 等 65+ 平台），所有配置和数据存储本地，无需公网暴露
- **🔄 多策略智能路由** — 5 种负载均衡策略（轮询、加权、随机、故障转移、优先级）+ 自动故障切换
- **🔑 多 Key 负载均衡** — 每个平台可配置多个 API Key，支持 RPM 阈值和计数阈值自动切换
- **🤖 多 Model 自动调度** — 根据策略规则自动选择最优模型，支持模型级别自动降级
- **🛡️ 协议自动转换** — OpenAI / Claude / Gemini 三种协议自动互转，任意 SDK 调用任意模型
- **🔒 数据安全** — 纯本地运行，API Key 使用 Fernet 加密存储，零数据外泄
- **🌐 局域网共享** — 部署后局域网内所有设备共享 API Key 和路由策略，只需一个接入点

---

## 为什么选择 LocalRouter？

管理多个 LLM 平台非常痛苦。每个平台都有不同的 API 格式、计费方式和速率限制。你需要维护多套 API Key、多个 SDK、手动处理故障转移。

**LocalRouter 通过一个统一的 OpenAI 兼容端点解决了这些问题：**

| 问题 | 解决方案 |
|------|----------|
| 多个平台 SDK 不统一 | 单一 OpenAI 兼容 API |
| API Key 管理混乱 | 集中密钥管理 + 加密存储 |
| 平台故障 | 自动故障转移到备用平台/Key |
| 速率限制 | 多 Key 轮换 + RPM 智能切换 |
| 协议不兼容 | 自动转换 OpenAI/Claude/Gemini 格式 |
| 模型发现困难 | 一键从上游同步 + 内置 100+ 已知模型库 |

---

## 局域网统一管理优势

LocalRouter 从设计之初就为**局域网（LAN）部署**而优化。开启局域网访问后，网内所有设备共享一个接入点：

| 优势 | 说明 |
|------|------|
| **成本共享** | 一份 API Key 订阅服务整个团队，无需为每台设备单独购买 |
| **集中密钥管理** | 一处添加/轮换 API Key，所有局域网设备自动生效 |
| **统一策略管控** | 路由规则一次定义，团队成员共享相同的智能路由策略 |
| **零延迟开销** | 局域网转发延迟 <1ms，无需经过云端中转 |
| **数据隐私** | 所有 API 请求在局域网内完成，不经过外部网关 |
| **跨平台支持** | Windows、macOS、Linux、iOS、Android -- 任何支持 HTTP 的设备都能用 |
| **即插即用** | 兼容所有 OpenAI SDK 客户端 -- Cursor、ChatBox、CherryStudio、Open WebUI |

**典型使用场景：**
- 团队工作站共享一套 API Key，统一管理
- 移动设备无需安装 SDK，直接调用 LLM API
- IoT 设备通过局域网端点集成 AI 能力
- CI/CD 流水线使用与开发环境相同的路由策略

---

## 功能特性

### 平台管理
- 结构化管理上游平台（名称、协议、地址、图标）
- 一键搜索图标（百度/必应/搜狗图片）
- 65+ 热门平台模板 -- 一键快速添加
- 启用/禁用单个平台

### API Key 管理
- 按平台分组管理 API Key，支持别名
- 密钥健康检测（有效/无效/未测试）
- 批量测试全部 Key、批量删除无效 Key
- 权重设置（用于加权负载均衡）
- **加密存储** -- Fernet 对称加密，密钥文件自动生成

### 模型管理
- 每个平台独立的模型管理，支持详细属性
- **一键从上游同步** -- 智能参数检测和填充
- **同步弹窗交互** -- 支持全选、反选、逐条添加、批量添加
- **内置已知模型数据库** -- 100+ 预配置模型参数
- 自动模型类型检测（文本/图像/视频/TTS/嵌入）

### 路由策略

| 策略 | 说明 |
|------|------|
| **轮询 (Round Robin)** | 按顺序依次轮换规则 |
| **加权 (Weighted)** | 按权重比例分配流量 |
| **随机 (Random)** | 随机选择规则 |
| **故障转移 (Failover)** | 按优先级，失败时自动切换 |
| **优先级 (Priority)** | 始终使用最高优先级 |

### Key 策略

| 策略 | 说明 |
|------|------|
| **轮询** | 按顺序轮换使用 Key |
| **随机** | 随机选择 Key |
| **故障转移** | 使用第一个 Key，失败则切换 |
| **RPM 阈值** | 每分钟请求数超阈值时自动切换 |
| **计数阈值** | 总请求数超阈值时自动切换 |

### 协议支持
- **OpenAI** -- 原生兼容（GPT 系列、o1/o3、DALL-E、TTS、Whisper）
- **Anthropic Claude** -- 自动格式转换（从 OpenAI 格式）
- **Google Gemini** -- 自动格式转换（从 OpenAI 格式）
- **自定义** -- 任何 OpenAI 兼容端点

### 可观测性
- **仪表盘** -- 今日请求量、成功率、平均延迟、Token 用量
- **请求日志** -- 完整的搜索筛选请求历史（按策略/平台/状态/时间）
- **策略测试** -- 上线前测试路由链路

### 系统设置
- 暗色/亮色主题切换
- **中英文双语界面**
- **输出协议转换** -- 返回 OpenAI / Claude / Gemini 格式
- **备份与恢复** -- 手动/自动备份，支持定时和上传恢复

---

## 系统架构

```
客户端 (OpenAI SDK / 第三方应用)
  |
  | POST /v1/chat/completions (model="策略名称")
  v
[proxy.py] -- 根据模型名解析策略
  |
  v
[balancer.py] -- 选择路由规则 + API Key
  |                (5 种负载均衡策略 / 3 种 Key 策略)
  v
[forwarder.py] -- 协议适配 + 发送上游请求
  |                (OpenAI / Claude / Gemini)
  v
[protocol_adapter.py] -- 可选输出格式转换
  |
  v
[stream_handler.py] -- SSE 流式处理
  |
  v
客户端 <--- 标准 OpenAI 格式响应
```

---

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+

### 1. 克隆与初始化

```bash
git clone https://github.com/licorxj/QM-LocalRouter.git
cd QM-LocalRouter

# 初始化数据库（自动创建虚环境、安装依赖、创建数据库）
cd scripts
python init_db.py        # 跨平台 Python 脚本
# 或: ./init_db.sh       # Linux/macOS
# 或: init_db.bat        # Windows
cd ..
```

### 2. 启动服务

**方式 A：使用管理脚本（推荐）**

```bash
# Linux/macOS
chmod +x scripts/manage.sh
./scripts/manage.sh start

# Windows
scripts\manage.bat start
```

**方式 B：手动启动**

```bash
# 终端 1 - 后端
cd backend
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS
uvicorn app.main:app --host 0.0.0.0 --port 12002

# 终端 2 - 前端
cd frontend
npm install
npm run dev
```

### 3. 使用

1. 浏览器打开 **http://localhost:12001**
2. 进入 **平台管理** 页面，点击 **+** 添加平台（或使用 **热门平台** 一键添加）
3. 在平台下添加 API Key
4. 添加模型 -- 可手动、一键同步、或使用"同步平台模型"弹窗
5. 进入 **路由策略**，创建策略并添加路由规则
6. 客户端中设置 `base_url` 为 `http://localhost:12002/v1`，`model` 为策略名称

---

## 技术栈

| 层 | 技术 | 说明 |
|-------|-----------|------|
| 前端 | React 18 + TypeScript + Vite 5 | 单页应用，快速热更新 |
| UI | shadcn/ui + Tailwind CSS 3 | 现代无障碍组件库 |
| 状态管理 | Zustand + TanStack Query 5 | 轻量状态 + 服务端缓存 |
| 国际化 | 自定义 React Context | 中文 / 英文 |
| 后端 | Python 3.10+ + FastAPI + uvicorn | 异步高性能 API |
| 数据库 | SQLite + SQLAlchemy 2.0 (异步) | 零配置本地存储 |
| 加密 | cryptography (Fernet) | API Key AES-128 加密 |
| HTTP | httpx (异步) | 上游 API 请求转发 |

---

## API 概览

所有代理端点位于 `/v1/`，与 OpenAI SDK 完全兼容。

| 端点 | 说明 |
|------|------|
| `POST /v1/chat/completions` | 聊天补全（流式 + 非流式） |
| `POST /v1/completions` | 文本补全 |
| `POST /v1/embeddings` | 向量嵌入 |
| `POST /v1/images/generations` | 图像生成 |
| `POST /v1/audio/speech` | 语音合成 |
| `POST /v1/videos` | 视频生成 |
| `GET /v1/models` | 列出活跃策略 |

管理 API 在 `/api/` 下（Swagger：`http://localhost:12002/docs`）

---

## 客户端配置

| 客户端 | 配置方式 |
|--------|----------|
| **OpenAI SDK** | `base_url="http://localhost:12002/v1"`, `api_key="任意值"` |
| **ChatBox** | 设置 > 自定义 API > Base URL: `http://localhost:12002/v1` |
| **CherryStudio** | 设置 > 添加自定义 API > Base URL: `http://localhost:12002/v1` |
| **LobeChat** | 设置 > 添加自定义模型 > API URL: `http://localhost:12002/v1` |
| **Open WebUI** | `OPENAI_API_BASE_URL=http://localhost:12002/v1` |
| **Cursor** | 设置 > 模型 > Base URL: `http://localhost:12002/v1` |
| **curl** | 见下方示例 |

```bash
curl http://localhost:12002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"my-strategy","messages":[{"role":"user","content":"你好！"}]}'
```

> **注意**: `api_key` 可填任意值。`model` 字段必须填策略名称。

---

## 文档

| 文档 | 说明 |
|------|------|
| [README.md](README.md) | English documentation |
| [docs/USAGE.md](docs/USAGE.md) | English user guide |
| [docs/USAGE_ZH.md](docs/USAGE_ZH.md) | 中文使用教程 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 部署指南（Docker、VPS、Windows、Linux） |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 开发者文档 |
| [docs/API.md](docs/API.md) | API 参考 |
| [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) | 依赖清单 |

---

## 联系与支持

如果这个项目对你有帮助，欢迎联系和交流：

<div align="center">
  <table>
    <tr>
      <td align="center">
        <strong>添加好友 (微信)</strong><br>
        <img src="docs/images/contact-qr.jpg" width="200" alt="联系二维码"><br>
        <em>扫码添加好友</em>
      </td>
      <td align="center">
        <strong>打赏支持 (微信支付)</strong><br>
        <img src="docs/images/donate-qr.png" width="200" alt="打赏二维码"><br>
        <em>扫码支持项目</em>
      </td>
    </tr>
  </table>
</div>

---

## 许可证

MIT License

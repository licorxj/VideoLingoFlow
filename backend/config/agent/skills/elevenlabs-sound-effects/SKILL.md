---
name: elevenlabs-sound-effects
description: "封装 ElevenLabs 音效库「搜索接口」的爬虫与下载工具。能从接口响应中提取营销片段（sound-effects 文档）的详细信息与 URL，并下载音效音频。**搜索词必须使用英文**（ElevenLabs 检索为英文检索）。脚本仍内置中文→英文 LLM 自动翻译（CJK 自动触发，依赖项目 backend.llm）作为后备，可用 --no-translate 关闭。音效经 eleven-public-cdn 直连下载。当用户要：搜索/抓取 ElevenLabs 音效、按英文关键词找音效片段、或下载某个音效 mp3/wav 时使用。"
metadata: { "tags": "elevenlabs, 音效, 爬虫, 搜索, 下载, sound-effects, 营销片段" }
---

# ElevenLabs 音效库爬虫与下载（Skill）

本 Skill 封装一个 Python 爬虫脚本，对接 ElevenLabs 音效库搜索接口，抓取「营销片段」详情与 URL，并可下载音效音频。

## 1. 脚本位置

| 组件 | 位置（相对 PROJECT_ROOT） |
|---|---|
| 爬虫脚本（以本副本为准） | `backend/config/agent/skills/elevenlabs-sound-effects/elevenlabs_sound_effects.py` |
| 请求信息文件（含 cookie / next-action 等） | 脚本同目录下的 `elevenlabs_request.json`（精简 JSON 格式） |

> 脚本最初也保留在 `backend/crawlers/elevenlabs_sound_effects.py`；以本 Skill 目录内 bundled 副本为准。

## 2. 接口与原理

- 接口：`POST https://elevenlabs.io/zh/sound-effects`
- 请求体：React Flight 格式编码的搜索词，即 JSON 数组字符串 `["<query>"]`。
- 关键请求头 `next-action` / `x-deployment-id` / `cookie` 从请求信息文件 `elevenlabs_request.json`（浏览器开发者工具导出的请求信息，存为精简 JSON）自动解析；Cookie 含登录态、会过期，失效后需重新导出该文件。
- 该接口有 Cloudflare TLS 指纹校验，普通 `urllib/requests` 直连会被 403，因此**检索走 Playwright（真实浏览器 TLS）**。
- 音效音频托管在 `eleven-public-cdn.elevenlabs.io`，**可直接用 `requests` 下载**（无需浏览器 TLS），支持代理与重试。
- 响应为 Next.js RSC(flight) 流，脚本解析其中 `{"docs":[...]}` 得到营销片段列表。
- **搜索词必须使用英文**：ElevenLabs 音效搜索基于英文检索。`--query` 传入中文时会被自动调用项目 LLM 翻译成英文后再检索（CJK 自动触发），但建议直接传英文关键词；若用 `--no-translate` 关闭自动翻译，中文原词检索很可能得到 0 结果。

## 3. 依赖

```powershell
pip install playwright requests
playwright install chromium
```

- 中文→英文翻译依赖项目 LLM 服务层（`backend.llm.llm_client`），需项目 LLM 已配置（默认走 `localhost:8800` 路由）。未配置时：翻译回退为原查询（中文则可能 0 结果）。
- 代理通过 `--proxy` 或环境变量 `HTTP_PROXY` / `HTTPS_PROXY` 传入（例如 `http://127.0.0.1:7892`）。

## 4. 用法

```powershell
# 1) 英文关键词搜索，输出 JSON（推荐）
python backend/config/agent/skills/elevenlabs-sound-effects/elevenlabs_sound_effects.py `
  --query explosion --output result.json

# 2) 中文关键词（会自动经 LLM 翻译成英文后检索；建议直接传英文）
python backend/config/agent/skills/elevenlabs-sound-effects/elevenlabs_sound_effects.py `
  --query "码头船只归来的鸣笛" --output result.json

# 3) 爬取并下载音效（按营销片段分子目录）
python backend/config/agent/skills/elevenlabs-sound-effects/elevenlabs_sound_effects.py `
  --query ferry --download --download-dir downloads

# 4) 直接按音频 URL 下载（独立于爬取流程，可多次 --download-url）
python backend/config/agent/skills/elevenlabs-sound-effects/elevenlabs_sound_effects.py `
  --download-url "https://eleven-public-cdn.elevenlabs.io/payloadcms/xxxx.mp3"

# 5) 离线解析已保存的响应文件（调试用，跳过网络）
python backend/config/agent/skills/elevenlabs-sound-effects/elevenlabs_sound_effects.py `
  --parse-file saved_response.txt --output out.json
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--query` | 搜索关键词（**必须为英文**；传中文会自动经 LLM 翻译，建议直接传英文） |
| `--request-file` | 浏览器导出的请求信息文件（默认尝试脚本同目录下的 `elevenlabs_request.json`，精简 JSON 格式） |
| `--cookie` / `--next-action` / `--x-deployment-id` | 覆盖对应请求头 |
| `--no-translate` | 关闭中文→英文 LLM 自动翻译（仅用英文原词检索；关闭后中文可能 0 结果） |
| `--download` | 爬取完成后下载各片段音效 |
| `--download-dir` | 下载目录（默认 `./downloads`） |
| `--flatten` | 所有音频平铺到下载目录，不按片段分子目录 |
| `--download-url` | 直接下载给定音频 URL（可多次指定） |
| `--parse-file` | 直接解析已保存的响应文件 |
| `--proxy` | HTTP/HTTPS 代理 |
| `--output` / `-o` | 输出 JSON 文件路径（默认 `elevenlabs_sound_effects.json`） |

## 5. 输出 JSON 结构

```json
{
  "query_original": "explosion",
  "query": "explosion",
  "query_keywords": ["explosion"],
  "translated": false,
  "count": 20,
  "source": "https://elevenlabs.io/zh/sound-effects",
  "items": [
    {
      "title": "Ship Horn",
      "slug": "ship-horn",
      "page_url": "https://elevenlabs.io/zh/sound-effects/ship-horn",
      "hero_cover_url": "https://eleven-public-cdn.../cover.png",
      "question": "...",
      "meta": { "...": "..." },
      "generation_suggestions": ["..."],
      "sounds": [
        {
          "name": "Transit",
          "short_description": "...",
          "audio_url": "https://eleven-public-cdn.elevenlabs.io/payloadcms/xxx.mp3",
          "id": "...",
          "labels": ["..."]
        }
      ]
    }
  ],
  "downloaded": {
    "dir": "...", "total": 22, "ok": 22, "failed": 0,
    "records": [ { "title": "Transit", "url": "...", "path": "...", "ok": true, "error": null } ]
  }
}
```

## 6. 注意事项

- **Cookie 过期**：出现「未能从响应中解析出 docs 数据」时，多半是 `elevenlabs_request.json` 中的 cookie 失效，重新用浏览器开发者工具导出请求信息覆盖该文件即可。
- **请求信息文件格式**：精简 JSON，形如 `{"cookie": "...", "next_action": "...", "x_deployment_id": "..."}`（键名也接受带连字符的 `next-action` / `x-deployment-id`）；放在脚本同目录、命名为 `elevenlabs_request.json` 时会被自动读取。
- **搜索词必须为英文**：ElevenLabs 检索基于英文，建议 `--query` 直接传英文；传中文会触发内置 LLM 翻译（CJK 自动识别），但翻译服务不可用时中文将得到 0 结果，`--no-translate` 可彻底关闭自动翻译。
- **下载并发**：`--query` 翻译后若含多个逗号分隔关键词，会分别检索并去重合并（最多取前 3 个关键词），每个片段下音效可能较多，注意下载量。

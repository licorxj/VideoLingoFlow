---
name: chinaz-sound-effects
description: "封装站长之家音效库（sc.chinaz.com/yinxiao）的爬虫与下载工具。纯 requests 抓取（GBK 编码、无 WAF/浏览器依赖），支持按筛选标签或关键词批量获取音效结构化列表，并按音频编号下载高码率原文件（wav）。内置容错：网络重试、Windows 中文参数乱码修复、标签名模糊匹配、下载文件名安全。当用户要：抓取站长之家音效、按标签/关键词批量列音效、下载音效原文件（高码率）、或需要国内音效素材时使用。"
metadata: { "tags": "chinaz, 站长之家, 音效, 爬虫, 下载, 素材, 音效库" }
---

# 站长之家音效库爬虫与下载（Skill）

本 Skill 封装一个纯 `requests` Python 爬虫，对接站长之家音效库，抓取音效列表与详情，并可按编号下载高码率音频。

## 1. 脚本位置

| 组件 | 位置（相对 PROJECT_ROOT） |
|---|---|
| 爬虫脚本（以本副本为准） | `backend/config/agent/skills/chinaz-sound-effects/chinaz_sound_effects.py` |
| 筛选标签缓存（自动生成） | `backend/config/agent/skills/chinaz-sound-effects/chinaz_categories.json` |

> 脚本最初也保留在 `backend/crawlers/chinaz_sound_effects.py`；以本 Skill 目录内 bundled 副本为准。

## 2. 接口与原理

- 站点：`https://sc.chinaz.com/yinxiao/`（筛选标签在 `#Screen`，音频列表容器为 `#AudioList`）。
- 页面为 **GBK** 编码；**无 WAF、无需浏览器/指纹**，普通 `requests` 直连即可（检索不需要 Playwright）。
- 筛选标签首次运行自动抓取并持久化到 `chinaz_categories.json`（~895 个），`--refresh-categories` 可刷新。
- 音频列表分页规律：第 N 页为 `xxx_N.html`（N≥2）。
- 搜索接口：`https://aspx.sc.chinaz.com/query.aspx?classid=14&keyword=<kw>`。
- 详情页含高码率下载地址 `download_url`（`.wav`）与低码率预览 `preview_url`（`.mp3`）；注意**服务器文件名（如 `xm4154`）与详情页编号（如 `260415541901`）无直接映射**，高码率 URL 只能从详情页解析得到，无法纯靠编号拼。

## 3. 依赖

```powershell
pip install requests lxml
```

仅标准库 + `requests` + `lxml`，无其他外部服务依赖。

## 4. 用法

```powershell
# 1) 列出全部筛选标签
python backend/config/agent/skills/chinaz-sound-effects/chinaz_sound_effects.py --list-categories

# 2) 按标签名（容错匹配）抓取列表，输出 JSON
python backend/config/agent/skills/chinaz-sound-effects/chinaz_sound_effects.py `
  --category 战争音效 --max-pages 3 --output result.json

# 3) 或直接给标签子 url
python backend/config/agent/skills/chinaz-sound-effects/chinaz_sound_effects.py `
  --category-url https://sc.chinaz.com/yinxiao/zhanzhengyinxiao.html --output result.json

# 4) 按关键词搜索
python backend/config/agent/skills/chinaz-sound-effects/chinaz_sound_effects.py `
  --search 打雷 --output search.json

# 5) 抓取并下载高码率原文件（按编号命名）
python backend/config/agent/skills/chinaz-sound-effects/chinaz_sound_effects.py `
  --category 战争音效 --download --save-dir out

# 6) 单条详情页下载高码率
python backend/config/agent/skills/chinaz-sound-effects/chinaz_sound_effects.py `
  --detail https://sc.chinaz.com/yinxiao/260415541901.htm --download
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--list-categories` | 列出全部筛选标签 |
| `--refresh-categories` | 强制刷新筛选标签缓存 |
| `--category` | 按标签名称匹配（精确→包含，容错）抓取列表 |
| `--category-url` | 直接给定标签子 url 抓取列表 |
| `--search` | 按关键词搜索 |
| `--detail` | 给定音频详情页 url，获取高码率下载地址与标签 |
| `--max-pages` | 音频列表最多抓取页数（默认 1） |
| `--download` | 同时下载音频（按编号取高码率原文件，失败回退低码率预览） |
| `--save-dir` | 下载保存目录（默认 `chinaz_audio`） |
| `--output` | 结果输出到 JSON 文件（默认打印终端） |

## 5. 输出 JSON 结构

列表（`get_audio_list`）：

```json
[
  {
    "name": "鼠标不停地点击音效",
    "detail_url": "https://sc.chinaz.com/yinxiao/260415541901.htm",
    "preview_url": "https://downsc.chinaz.net/Files/DownLoad/sound1/202603/xm4154.mp3",
    "tags": [ { "name": "鼠标", "url": "https://sc.chinaz.com/tag_yinxiao/shubiao.html" } ],
    "local_path": "out/260415541901.wav"
  }
]
```

详情（`get_audio_detail`）：

```json
{
  "download_url": "https://downsc.chinaz.net/Files/DownLoad/sound1/202603/xm4154.wav",
  "tags": ["鼠标", "点击鼠标"],
  "local_path": "out/260415541901.wav"
}
```

搜索（`search`）：`[{ "name": "...", "detail_url": "..." }]`。

## 6. 容错与注意事项

- **网络重试**：对网络异常 / 5xx 自动退避重试（默认 3 次），4xx 不重试。
- **中文参数乱码**：Windows 下用 Wide API（`GetCommandLineW`+`CommandLineToArgvW`）重新解析命令行，在 UTF-8 终端（或 `chcp 65001` 后）`--category 战争音效` 可正确匹配；若终端仍以 GBK 代码页把 UTF-8 当 GBK 读导致乱码，改用 `--category-url` 直接传 url。
- **标签名模糊匹配**：精确（忽略大小写/空白）→ 包含匹配；命中多个会列出候选并取第一个；无命中给出提示。
- **下载文件名安全**：自动清洗非法字符、超长截断、同名校验加序号避免覆盖。
- **预览 vs 下载**：列表输出中的 `preview_url` 为低码率预览；`--download` 时按 `detail_url` 编号拉详情页取**高码率** `download_url`（`.wav`）下载并以编号命名，高码率不可用时回退低码率预览（并告警）。
- **筛选标签缓存**：`chinaz_categories.json` 持久化在脚本同目录，首次自动生成。

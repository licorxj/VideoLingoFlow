# kieai — kie.ai 异步 Python SDK

封装 kie.ai 的全部 **图片 / 视频 / 音乐 / 文件上传** API。所有生成类接口统一采用
**异步提交 + 轮询** 模式（不使用 `callBackUrl` 回调）。

- 数据驱动：模型清单由 `catalog.json` 描述，SDK 按清单路由到正确的端点与轮询地址。
- 异步：基于 `aiohttp` + `asyncio`。
- 统一接口：`submit`（提交）/`wait`（轮询）/`generate`（一步到位）。

## 目录结构

```
kieai_sdk/
├── build_catalog.py        # 从 docs 的 OpenAPI YAML 重新生成 catalog.json
├── catalog.json            # 模型目录（180 个接口，按分类/平台/参数组织）
├── requirements.txt        # aiohttp
├── kieai/                  # SDK 包
│   ├── __init__.py
│   ├── client.py           # KieClient（submit/wait/generate/upload）
│   ├── models.py           # Catalog / ModelEntry / Param
│   └── exceptions.py
└── examples/basic_usage.py
```

## 安装

```bash
cd kieai_sdk
pip install -r requirements.txt
# 将 kieai 包加入路径（或 pip install -e .）
```

## 快速开始

```python
import asyncio
from kieai import KieClient

async def main():
    # api_key 可省略：依次回退到 secret://KIEAI_API_KEY、环境变量 KIEAI_API_KEY
    async with KieClient() as client:
        # 图片（Market 统一端点）
        img = await client.generate(
            "bytedance/seedream-v4-text-to-image",
            prompt="a calm lake at dawn", image_size="landscape_16_9")
        # 视频（Veo 3.1）
        vid = await client.generate(
            "generate-veo3-1-video", model="veo3_fast", prompt="a dog playing")
        # 音乐（Suno）—— 串联/多端点建议用 SunoMusicClient（见下文专章）
        song = await client.generate(
            "suno-generate", custom_mode=False, instrumental=False,
            model="V6", prompt="lofi beat")
        # 文件上传（同步返回 URL）
        up = await client.upload(method="url", fileUrl="https://x/y.jpg")

asyncio.run(main())
```

## API Key 获取（三级回退）

`KieClient(api_key=...)` 中的 `api_key` 是可选的。未显式传入时，SDK 按以下优先级解析真实密钥：

1. **调用者传入**：构造时传入的 `api_key`（也支持传入 `secret://NAME` 引用，会经密钥管理员解析）。
2. **项目密钥管理员**：查询 `secret://KIEAI_API_KEY`（对应 `backend/config/credential_store` 中的凭据）；每次请求都会重新解析，因此支持密钥管理页的轮询/轮换策略。
3. **系统环境变量**：`KIEAI_API_KEY`。

三者皆无时，首次发起请求会抛出 `KieRequestError`。在独立（非 backend）环境使用 SDK 时，第 2 步自动跳过（模块不可导入），直接回退到第 3 步或显式传入的 key。

```python
# 完全省略 key（依赖项目密钥管理员或环境变量）
client = KieClient()
# 自定义引用名 / 环境变量名
client = KieClient(secret_name="KIEAI_API_KEY")
```

## 音乐（Suno / ai-music-api）—— 与官网对齐

Suno 全家桶已按官方新规范（https://docs.kie.ai/suno-api）统一：
所有操作 `POST https://api.kie.ai/api/v1/jobs/createTask`，请求体
`{"model": "ai-music-api/<操作>", "input": {...snake_case 参数}}`；
统一轮询 `GET /api/v1/jobs/recordInfo?taskId=`，曲目在
`resultObject.data[]`（`audio_url / stream_audio_url / image_url / id / duration`）。

**每个提交类端点完成后都返回 `taskId`，供下游节点串联**（generate →
extend / persona / timestamped-lyrics / cover-generate / convert-to-wav …）。

### 用法：SunoMusicClient

```python
import asyncio
from kieai import SunoMusicClient

async def main():
    async with SunoMusicClient() as music:
        # 提交（立即返回 taskId）
        sub = await music.generate(custom_mode=False, instrumental=False,
                                   model="V6", prompt="lofi beat")
        task_id = sub["taskId"]

        # 轮询（返回 taskId / resultUrls / tracks / raw）
        done = await music.wait(task_id)
        audio_id = done["tracks"][0]["id"]     # 下游串联凭证

        # 用 audio_id 续写（再次返回新 taskId）
        ext = await music.extend(audio_id=audio_id, model="V6", continue_at=60)

        # 提交+等待一步到位
        ly = await music.run("generate_lyrics", prompt="a nostalgic song")
asyncio.run(main())
```

- 参数名与官网 Playground 一致（snake_case），也兼容 camelCase（自动归一）。
- 提交前按规格表校验：缺必填 / 未知参数 / 互斥组冲突 / 枚举越界会抛 `ValueError`。
- `callback_url=` 可选传入 `callBackUrl`；默认仍为轮询模式。

### 端点清单（与官网标签页一一对应）

| 官网标签 | 方法 | model（createTask 的 model 字段） | 串联输入 → 输出 |
|---|---|---|---|
| Generate | `generate` | `ai-music-api/generate` | prompt/style → **taskId** → tracks[].id |
| Extend | `extend` | `ai-music-api/extend` | audio_id → **taskId** |
| Upload And Cover Audio | `upload_and_cover` | `ai-music-api/upload-and-cover-audio` | upload_url 或 task_id+audio_id → **taskId** |
| Upload And Extend Audio | `upload_and_extend` | `ai-music-api/upload-and-extend-audio` | upload_url → **taskId** |
| Add Instrumental | `add_instrumental` | `ai-music-api/add-instrumental` | upload_url → **taskId** |
| Add Vocals | `add_vocals` | `ai-music-api/add-vocals` | upload_url → **taskId** |
| Generate Persona | `generate_persona` | `ai-music-api/generate-persona` | task_id+audio_id → **persona_id**（同步） |
| Generate Voice（验证短语） | `voice_validate` | `ai-music-api/validation-phrase` | voice_url → **taskId**（=voice_id） |
| Create Voice | `voice_create` | `ai-music-api/create-voice` | 验证 taskId+verify_url → **taskId** |
| Check Voice | `voice_check` | `ai-music-api/check-voice` | create-voice taskId → **isAvailable**（同步） |
| 重新生成验证短语 | `voice_regenerate` | `ai-music-api/regenerate-phrase` | 验证 taskId → 受理 **taskId** |
| Boost Music Style | `boost_style` | `ai-music-api/boost-music-style` | content → **taskId**（结果串回 style） |
| Cover Generate | `cover_generate` | `ai-music-api/cover-generate` | task_id → **taskId**（2 张封面） |
| Replace Section | `replace_section` | `ai-music-api/replace-section` | task_id+audio_id 或 upload_url+model → **taskId** |
| Mashup | `mashup` | `ai-music-api/mashup` | upload_url_list×2 → **taskId** |
| Sounds | `sounds` | `ai-music-api/sounds` | prompt → **taskId** |
| Generate Lyrics | `generate_lyrics` | `ai-music-api/generate-lyrics` | prompt → **taskId**（lyricsData[]） |
| Timestamped Lyrics | `timestamped_lyrics` | `ai-music-api/timeStamped-lyrics` | task_id+audio_id → **taskId**（alignedWords） |
| Separate Vocals | `separate_vocals` | `ai-music-api/separate-vocals` | task_id+audio_id 或 audio_url → **taskId**（stems） |
| Generate MIDI From Audio | `generate_midi` | `ai-music-api/generate-midi-from-audio` | 分离 task_id → **taskId**（`wait_midi` 取音符） |
| Suno Recovery Audio | `recovery_audio` | `ai-music-api/suno-recovery-audio` | task_id → **taskId**（`wait_recovery` 专用轮询） |
| Convert To Wav Format | `convert_to_wav` | `ai-music-api/convert-to-wav-format` | task_id+audio_id → **taskId**（resultUrls[0]=.wav） |
| Create Music Video | `create_music_video` | `ai-music-api/create-music-video` | task_id+audio_id → **taskId**（resultUrls[0]=.mp4） |

通用等待：`music.wait(task_id)`；MIDI 用 `wait_midi`；恢复音频用
`wait_recovery`（code 201 运行中 / 200 完成 / 500 失败）。Persona 与
Check Voice 为同步端点，`submit` 返回值带 `sync: True` 且无 taskId。

串联完整示例见 `examples/music_chains.py`。catalog.json 中的 suno 条目
（id 形如 `suno-generate`…，`model_ref` 形如 `ai-music-api/generate`）
由 `kieai/suno.py` 的内置规格表在加载时自动覆盖，与官网保持一致。

## 产物落盘（output_path）

`generate` / `generate_image` / `generate_video` / `generate_music` 以及底层的
`wait` 在任务完成后会自动把结果 URL 下载到本地，并把保存路径写入返回字典的
`local_paths` 字段（即使不传 `output_path` 也会落盘）：

```python
# 不传 output_path -> 默认保存到 <cwd>/output/<category>/<taskId>_<时间戳>.<ext>
res = await client.generate("nano-banana-2", prompt="a cat", resolution="1K")
print(res["local_paths"])          # ['output/image/xxxx_20260907_...jpeg']

# 传文件路径 -> 作为基础名；多个产物自动追加 _1 / _2 …
res = await client.generate("nano-banana-2", prompt="a cat",
                            output_path="out/cat.png")
# -> ['out/cat.png'] 或 ['out/cat_1.png', 'out/cat_2.png', ...]

# 传目录 -> 写入该目录，文件名用 <taskId>_<时间戳>
res = await client.generate("nano-banana-2", prompt="a cat",
                            output_path="out/nb/")
```

- 分类子目录由模型 `category` 决定：`image` / `video` / `audio`（其余归为 `file`）。
- 默认根目录为 `<cwd>/output`，可在构造 `KieClient(output_base="...")` 时修改。
- 扩展名优先从结果 URL 推断，推断不出时按分类回退（图片 `.png`、视频 `.mp4`、音频 `.mp3`）。
- 返回字典除 `local_paths` 外仍保留原始远程 URL 字段（如 `resultUrls`）。

## 模型查找

`catalog.json` 中每个模型可用以下任一键定位：

- `id`：如 `bytedance/seedream-v4-text-to-image`（Market 模型）、`generate-music`（Suno 方法）。
- `model_ref`：Market 模型的 `model` 枚举值。
- 名称（大小写不敏感，支持包含匹配）。

```python
from kieai import Catalog
cat = Catalog.load()
cat.search(category="video", family="veo3")   # 按分类/家族筛选
cat.get("generate-veo3-1-video")              # 精确查找
```

分类口径（`category`）：`image` / `video` / `music`(Suno) / `audio`(TTS/语音) /
`file-upload` / `other`(Chat 模型，未纳入本次封装)。

## 请求与轮询机制

1. `POST` 任务 → 从响应中提取 `taskId`（兼容 `taskId/task_id/id`）。
2. `GET` 状态端点（各家族不同，见 `catalog.json` 的 `poll_endpoint`）轮询：
   - 状态 `1` / `SUCCESS` / 出现结果 URL → 成功，返回 `data`。
   - 状态 `2` / `3` / `FAILED` → 抛出 `KieTaskFailed`。
   - 超过 `max_poll` 次 → 抛出 `KieTimeout`。
3. 文件上传为**同步**，直接返回结果，无轮询。

`KieClient` 构造参数：`timeout`、`poll_interval`（默认 3s）、`max_poll`（默认 120）。

## 价格获取接口（`kieai/pricing.py`）

价格来自 kie.ai 内部接口 `POST https://api.kie.ai/client/v1/model-pricing/page`
（非公开文档；`pricing.txt` 中记录了请求头与载荷格式）。该接口按
`interfaceType`（Image/Video/Music/Audio）分页返回每条模型的：

- `falPrice` → **官方价格**（`official_price`）
- `usdPrice` → **kie 实际价**（`kie_price`，折扣由 `discountRate` 体现）
- `creditPrice` / `creditUnit` / `provider` / `anchor`

### 接口用法

```python
import asyncio
from kieai import KiePricing

async def main():
    client = KiePricing(
        authorization="<你的 authorization>",
        a_dkmt="<a-dkmt 会话令牌>",
        uniqueid="<uniqueid>",
    )
    records = await client.fetch_all()          # 拉取全部 393 条价格
    for r in records:
        print(r.model_id, r.official_price, r.kie_price)

asyncio.run(main())
```

- `fetch_page(interface_type, page_num, page_size)`：单页。
- `fetch_all(...)`：跨所有 interfaceType 翻页汇总（默认 Image/Video/Music/Audio）。
- `build_index(records)`：按归一化模型 id 建索引，便于查找。
- 也可用便捷协程 `fetch_prices(authorization, a_dkmt, uniqueid)`。

**磁盘缓存**：`KiePricing` 默认把结果写入 `prices_cache.json`（构造函数
`cache_path` 可改，传 `None` 关闭），下次 `fetch_all()` 直接读缓存、不再打接口；
`ttl`（秒）控制有效期，`None` 表示永不过期。缓存绕过方式：
`fetch_all(force=True)` 或 `fetch_prices(..., force=True)`。

```python
client = KiePricing(auth, dkmt, uid, cache_path="prices_cache.json", ttl=86400)
records = await client.fetch_all()        # 首次走接口并写缓存
records = await client.fetch_all()        # 之后读缓存（ttl 内）
records = await client.fetch_all(force=True)  # 强制刷新
```

> ⚠️ `a-dkmt` / `uniqueid` 是浏览器会话令牌，可能过期，需从浏览器开发者工具刷新。
> 缓存未过期时即使令牌失效也能拿到上次结果。

### 回填到 catalog.json

`enrich_catalog.py` 拉取价格并按模型匹配写回 `catalog.json`（同时生成
独立的 `prices.json` 供人工查阅）：

```bash
python enrich_catalog.py            # 优先读缓存，缓存缺失/过期才请求接口
python enrich_catalog.py --force    # 强制刷新价格（忽略缓存）
```

令牌读取顺序：`pricing_config.json`（已生成，含你的会话令牌，**已被 .gitignore 忽略**）
→ 环境变量 `KIE_PRICING_AUTH` / `KIE_PRICING_DKMT` / `KIE_PRICING_UID`。
缓存文件 `prices_cache.json` 同样已被 `.gitignore` 忽略。

匹配策略：
- Tier-1（精确）：Market 模型靠 `model_ref`（如 `bytedance/seedream-...`）、
  去厂商前缀/能力后缀后的 `model_ref`、id、name 做归一化匹配。
- Tier-2（近似，`pricing.approx=true`）：专属家族（Veo3 / Runway / Flux / 4o）
  按平台自然词 + 分类词在原始描述中匹配，结果标记为近似。

当前回填结果：180 个模型中 **161 个命中价格**（34 个为近似匹配）；
未命中主要为 Chat 模型（`other`）与文件上传（无价格）。

## 重新生成 catalog.json

文档如有更新，用脚本重新解析（需已下载的 Markdown 文档）：

```bash
python build_catalog.py "路径/to/kieai文档" catalog.json
```

## 已知限制 / 待补全

- **价格与日期**：`kie.ai/pricing` 在本环境被地域限制拦截（返回 block 页），
  故 `model_date` / `official_price` / `kie_price` 均为 `"N/A"`，
  `other_info_url` 固定指向 https://kie.ai/pricing 供人工核查。
- **`kling-3-0`**：其官方文档的 OpenAPI 块导出时缺失 `requestBody`，
  该条目 `params` 为空（其余 Kling 版本正常）。可改用其他 Kling 版本或手动补全参数。
- 轮询状态判定采用各家族通用的 `0/1/2/3` 数字约定；若某接口返回结构特殊，
  可在 `kieai/client.py` 的 `_SUCCESS_VALUES` / `_FAILURE_VALUES` 中扩展。

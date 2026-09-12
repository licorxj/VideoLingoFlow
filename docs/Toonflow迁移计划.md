# Toonflow 迁移计划（创作画布）v2 — 已确认关键决策

> 目标：把开源 AI 短剧系统 Toonflow（`_backup/Toonflow-app-master`，v1.1.8，Apache-2.0）的
> **创作流程、Agent/Skill/提示词/画风资产**迁移进本项目：前端**自建**「创作画布」（agent 侧边栏 +
> 无限画布主区），后端迁移到 `backend/toonflow/`，AI 接入层完全适配本项目 LLM/TTS/生图/生视频/
> 音乐接口（**不使用沙箱**）。剪辑/轨道部分**不迁移**（本项目已有成片链）。
>
> 已确认决策：①前端自建（React Flow 无限画布 + agent 侧边栏）；②无沙箱、纯适配层；
> ③Agent **纯后端化**（已核实可行）；④只迁创作流程；⑤skills/提示词/画风模板原样保留。

---

## 1. 源系统调研结论

- **后端**：Express 5 + socket.io + SQLite(knex)，169 条路由，无任务队列（HTTP 内异步 + 前端轮询）。
- **Agent 定性**：**Vercel AI SDK 通用工具循环（`generateText + tools + stepCountIs`）之上的
  自建三层编排**：决策 Agent → 子 Agent(每个是一个 tool) → 监督 QC Agent。
  非 LangGraph 类图框架。**已核实可纯后端化**：
  - `add_deriveAsset` / `del_deriveAsset`：工具内直接写库，与前端无关；
  - `get_flowData`：socket 回调只是为了拿前端缓存的工作区数据 → 后端直接读库；
  - `generateDeriveAsset` / `generateStoryboard` 等：emit 给前端是为刷新 UI + 触发生成，
    而生成最终调的是服务端 HTTP 路由 → 后端直接调服务端函数即可。
  - ⇒ socket 只保留**单向推送**（消息/进度/思考过程），去掉回调等待与 800ms socketQueue。
- **AI 接入层**：vendor = 11 份 TS 模板 + vm2 沙盒 → **不迁移**，替换为本项目引擎适配层。
- **资产（重点保留）**：
  - `data/skills/*.md`：18 个主技能（script/production 的 decision/supervision/execution）+
    `art_skills/`（12 画风，各含 prefix.md/art_prompt/driector_skills）+
    `story_skills/`（12 题材）+ `production_skills/`（分镜技法 25KB）；
  - `initDB.ts`（76KB）内 `o_prompt` 种子（音频绑定等）、vendor 配置、画风列表；
  - `data/modelPrompt/video/*.md`：Seedance/universal 首尾帧等视频参数模板。
- **剪辑/轨道**：源系统本无合成代码（无 ffmpeg），轨道仅数据管理 → **不迁移**。

## 2. 总体架构

```
前端（自建，复用 @xyflow/react 12 —— 项目已有依赖）
├── 素材库 →「创作画布」标签页（MaterialLibrary.tsx KIND_META 加 canvas）
├── 主区：React Flow 无限画布
│    · 自定义节点：剧本/事件/角色·场景·道具资产卡/分镜卡/图片/视频/音频
│    · 节点操作：预览、删除、重生（重新生成该节点）、审查状态
│    · 数据源：/api/tf/canvas/{projectId} 全量快照 + 增量推送
└── 侧边栏：Agent 会话（socket.io 推送消息/思考/工具调用过程）

backend/toonflow/                     # 迁移代码根（新建）
├── api/                              # 自定义 API（/api/tf/*，无历史包袱）
│   ├── projects.py  canvas.py  pipeline.py  agents.py  assets.py  settings.py
├── core/
│   ├── models.py                     # tf_ 表（对齐源 o_* 精简版，alembic 管理）
│   ├── seed.py                       # initDB.ts 种子移植（o_prompt/画风/题材清单）
│   ├── flowdata.py                   # 工作区(FlowData)读写，替代前端缓存
│   └── paths.py                      # oss 存储 + 缩略图(Pillow)
├── engines/                          # ★ AI 适配层（无沙箱，直连本项目工厂）
│   ├── text.py                       # → backend.llm.llm_client（补流式/工具循环封装）
│   ├── image.py                      # → imagegen_factory（txt2img/img2img/ref/分辨率档位）
│   ├── video.py                      # → videogen_factory（txt2video/flf2video/autovideo/audio）
│   ├── audio.py                      # → tts_factory（preset/clone/voice_design）
│   ├── music.py                      # → musicgen 统一封装（不足则增强本地接口）
│   └── imaging.py                    # sharp→Pillow（zipImage/mergeImages/缩略图）
├── agents/
│   ├── loop.py                       # 自建轻量 tool-loop（function calling + 步数上限）
│   ├── script_agent/                 # 决策→骨架/改编/生成 子Agent→监督QC
│   ├── production_agent/             # 决策→衍生资产/导演计划/分镜表/分镜面板/出图→监制
│   ├── tools.py                      # 服务端工具（写库+调 pipeline，socket 只推送）
│   ├── skills_tools.py               # frontmatter 解析 + activate_skill（照抄源实现）
│   └── memory.py                     # 压缩记忆 + 向量检索（P4，sentence-transformers）
├── skills/                           # data/skills/*.md 原样拷贝（文案零改动）
└── prompts_seed/                     # o_prompt 种子 + modelPrompt/video/*.md
```

## 3. 引擎适配矩阵

| 源能力 | 本项目接口 | 对齐度 | 动作 |
|---|---|---|---|
| `textRequest`（流式/工具循环/think） | `llm_client` | 部分 | 适配层补**流式**与**tool-loop**封装 |
| `imageRequest`：size 1K/2K/4K、aspectRatio、referenceList、底图 | `imagegen_factory`（txt2img/img2img/ref_images/init/分辨率/比例） | 高 | 参数映射；分辨率档位对齐 |
| `videoRequest`：duration/resolution/ratio/referenceList/audio/首尾帧 | `videogen_factory`（txt2video/flf2video/autovideo/audio/ref_audios） | **高** | 纯映射 + 能力裁剪 |
| `ttsRequest` | `tts_factory`（preset/clone/voice_design） | 高 | 映射；音色复用配音谷 `vf:voices` |
| 音乐（MiniMax vendor） | `musicgen_interfaces` | 中 | 补统一 musicgen 引擎封装（增强本地接口） |
| `pollTask` 轮询 | 各 engine 内部轮询/落盘 | 高 | 适配层暴露同语义工具 |
| sharp 图像处理 | 无统一 | 中 | `imaging.py` Pillow 重写对齐 |

## 4. 分期实施计划

| 期 | 范围 | 产出/验收 |
|---|---|---|
| **P0 骨架与资产搬运（1~1.5 天）** | `backend/toonflow` 包 + main.py 挂载（`/api/tf/*`）；tf_ 核心表模型 + 迁移；`skills/`、`prompts_seed/` 原样搬运 + 加载器；前端「创作画布」tab + React Flow 空画布 + agent 侧边栏 UI 骨架 | 画布页面可打开，技能 md 可被后端加载解析 |
| **P1 引擎适配层（2~3 天）** | `engines/*` 五适配器 + imaging；`/api/tf/settings`（模型映射配置） | 服务端单测：文/图/视频/TTS/音乐各跑通一次 |
| **P2 核心创作链（3~4 天）** | pipeline 服务层：小说导入→事件提取→剧本生成→资产提取与出图→分镜表/分镜面板→分镜图→视频提示词→视频生成→角色配音绑定；canvas 快照 API；画布节点展示 + 手动删除/重生 | **同一本小说在画布内手动跑通到分镜视频/配音**（Agent 不启用） |
| **P3 Agent 后端化（3~4 天）** | `loop.py` tool-loop；scriptAgent / productionAgent 三层编排；tools 全部服务端实现；socket 单向推送接侧边栏会话；监督 QC 出审核意见并在画布标红 | Agent 对话驱动：小说→剧本→分镜→出图全链，侧边栏可见思考/工具过程 |
| **P4 打磨（2 天+）** | 记忆系统（sentence-transformers）、音乐接入画布、审查态联动重生、并发与性能、画风/题材选择器 | 与 Node 原版对照抽查产物质量 |

> 合计预估 **2~3 周**。P2 结束即有可用价值（手动全流程），P3 结束达成"强壮流程 + AgentSkill +
> 质检监督"目标。相比 v1 方案：去掉了契约复刻、API 冲突审计、黑盒前端三大风险。

## 5. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | Agent 决策/监督提示词与 XML 工作区格式（`<storyboardTable>` 等）是隐式契约 | skills md 原文零改动；解析器照抄源清洗逻辑（stripThink/XML 标签提取） |
| 2 | 自建 tool-loop 与 ai-sdk 行为差异（多步工具调用、终止条件） | 步数上限对齐（工具数×50）；工具结果文本化格式对齐；用源系统同提示词做 A/B 抽查 |
| 3 | 事件提取等 prompt 依赖特定输出格式（`|` 分隔 7 字段） | 移植时连同解析函数一起搬运并加单元测试 |
| 4 | 前端画布工作量大 | P2 先只读展示 + 单节点操作；编辑/连线交互后置 |
| 5 | 双数据体系（cp_creations_* 与 tf_*） | 第一阶段互不侵犯；后续桥接（Toonflow 项目 ↔ 创作项目）另行立项 |
| 6 | 中文状态字面量/魔法数字 | 迁移时集中为枚举常量，不改语义 |

## 6. 许可证合规

Apache-2.0：保留 `LICENSE`/`NOTICES.txt` 副本至 `backend/toonflow/`；在关于文档注明
"创作流程与 Agent 技能基于 Toonflow (Apache-2.0) 迁移"；skills md 保留来源注释头。

## 7. P0 任务清单（立即可启动）

1. `backend/toonflow/` 包骨架 + `main.py` 挂载 `/api/tf` + alembic tf_ 核心表迁移。
2. `data/skills` → `backend/toonflow/skills/` 拷贝 + `skills_tools.py`（frontmatter/activate_skill）+ 单测。
3. `initDB.ts` 中 o_prompt/画风/题材种子 → `core/seed.py`。
4. 前端：`MaterialLibrary.tsx` 加「创作画布」tab；新建 `frontend/src/pages/creation-canvas/`
   （React Flow 画布 + agent 侧边栏布局骨架 + `/api/tf` client 封装）。

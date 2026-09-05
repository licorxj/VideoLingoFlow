# HyperFrames 视频创作能力

HyperFrames 用 **HTML 描述合成、用 `npx hyperframes` 渲染成片**。本项目把它的能力包装成
「HyperFrames 节点」分组下的一组工作流节点，核心是**创意 → 渲染**两步走。

## 节点清单（分组：hyperframes）

| 节点 id | 名称 | 作用 |
| --- | --- | --- |
| `hyperframes_creative` | HyperFrames 创意 | 第一步：把 URL / 主题 / PR / 素材收敛成 `BRIEF.md`。支持 `mode=load` 直接加载已有 `BRIEF.md`，稳定复用既有工作流，不调用大模型 |
| `hyperframes_render` | HyperFrames 渲染 | 第二步：读取 `BRIEF.md`，按其中的工作流路由构建合成并渲染成片；可只构建 / 只渲染 / 只校验，可勾选渲染后 publish |
| `hyperframes_cli` | HyperFrames 工具 | 附属工具调用：直接执行一条 CLI 子命令（技能安装/体检、init、capture、add、keyframes、lint、validate、check、upgrade、doctor、preview、render、publish、自定义） |
| `hyperframes_agent` | HyperFrames 智能体 | 复合节点：直接驱动本项目的小 Pi（piagent）框架，一个节点跑完「创意 → 渲染」整条链路；检测到已有 `BRIEF.md` 自动按加载模式复用 |

实现位置：`backend/steps/s_hyperframes_base.py`（公共基类）、
`backend/steps/s_hyperframes_{creative,render,cli,agent}.py`、
公共支撑 `backend/utils/hyperframes.py`。

## 技能源码

`backend/config/agent/skills/hyperframes/`：

- `SKILL.md`：入口与意图路由（capability map + workflow cheat-sheet）
- `references/routes/<workflow>.md`：每个工作流的输入/输出/触发契约
- `references/intent-interview.md`、`capability-menu.md`、`skill-lifecycle.md`、
  `route-briefs.md`、`workflow-catalog.md`、`pitch-round.md`：访谈、能力、生命周期等细则

工作流路由（`BRIEF.md` 的 `workflow` 字段取值）：
`product-launch-video`、`faceless-explainer`、`pr-to-video`、`embedded-captions`、
`talking-head-recut`、`motion-graphics`、`music-to-video`、`slideshow`、
`general-video`、`remotion-to-hyperframes`。留空表示由意图访谈自动路由。

## 标准编排

1. `输入节点` → `HyperFrames 创意`（subject 填主题）
2. `HyperFrames 创意.brief` → `HyperFrames 渲染.brief`
3. `HyperFrames 渲染.video` → 下游（发布 / 归档 / 合成）

想一步到位时用一个 `HyperFrames 智能体` 节点代替第 1、2 步。

## 复用既有工程

三种等价方式，命中其一即跳过意图访谈：

- 创意节点 `brief_path` 配置指向已有 `BRIEF.md`
- 上游把 `BRIEF.md` 接到创意节点的 `brief` 输入端口
- 项目目录（`project_dir`）下已存在 `BRIEF.md`

渲染节点独立使用时同理：它优先读取 `brief` 端口，其次 `brief_path` 配置，
最后在项目目录里找 `BRIEF.md`。

## 产物约定

- 创意节点：`cache/hyperframes_brief_<node_id>.json`（结果摘要）+ 项目目录内 `BRIEF.md`
- 渲染节点：`cache/hyperframes_render_<node_id>.<ext>`（成片副本）+ `cache/hyperframes_render_<node_id>.json`
- 工具节点：`cache/hyperframes_cli_<node_id>.log`
- 项目目录默认落在 `cache/hyperframes_<node_id>/`，可在节点设置里改为任意目录（支持已有工程）

## 环境要求

- Node.js 可执行（`npx` 在 PATH 中）。节点设置里的 `cli_command` / `cli_package` 可改成其它调用方式
- 小 Pi 运行时尚可用（创意 / 渲染 / 智能体节点都通过 `backend/pi_rpc` 发起一次性会话）
- 首次执行会自动 `npx hyperframes skills update`，需要网络

## 排错

- `未找到 CLI 执行程序 'npx'`：安装 Node.js 并在节点设置里指定 `cli_command` 绝对路径
- `未返回约定的结束标识 [HF_DONE]`：小 Pi 未按要求收尾，重跑或把 `settle_timeout` 调大
- `未找到 BRIEF.md`：确认项目目录可写，或改用 `brief_path` 显式指定
- `渲染阶段结束但未找到成片`：先用 `HyperFrames 工具` 跑 `check` / `lint` 排查，再设置 `output_path`

# 能力文档目录（Capability Index）

> 本目录合集供 **通用任务助手（general）** 使用，也供各专项助手交叉参考。
> 使用方式：根据用户需求在下方清单中定位对应能力文档，用 `read` 工具按需读取该文档正文后再执行；
> **不要一次性通读所有能力文档**，以免浪费上下文。

所有路径均为相对 `PROJECT_ROOT` 的路径（PROJECT_ROOT 即本机 VideoLingoFlow 安装根目录，如 `Y:\VideoLingoLc`）。
读取文档时请使用绝对路径：`PROJECT_ROOT + "/backend/config/agent/docs/" + 文件名`。

## 能力文档清单

| 文档 | 路径 | 适用场景 |
|---|---|---|
| 节点创建能力 | `backend/config/agent/docs/node-creation.md` | 新建/注册/导入自定义节点；设计节点输入输出端口；规范存放节点文件；配置接口 |
| 工作流编排能力 | `backend/config/agent/docs/workflow-orchestration.md` | 按需求编排工作流 DAG；书写/校验工作流 JSON；规划节点顺序、连线与端口匹配 |
| 任务执行能力 | `backend/config/agent/docs/task-execution.md` | 理解任务执行流程；定位执行失败/卡住的原因；查看任务目录与产物；批量任务管理 |
| GPU 服务能力 | `backend/config/agent/docs/gpu-service.md` | 配置或排查可选 GPU lane 服务、显存和 ASR/分离调度 |
| 文件整理能力 | `backend/config/agent/docs/file-management.md` | 梳理项目目录结构；整理素材/字幕/音频/导出产物；规划目录与命名规范 |
| 作品发布能力 | `backend/config/agent/docs/publishing.md` | 准备多平台作品发布；标题/简介/封面检查；发布前素材与合规检查 |
| 技能安装能力 | `backend/config/agent/docs/skill-mcp-install.md` | 安装 Skill/MCP 扩展包；询问项目专用或系统级别；说明授权与放行方式 |

## 基础知识文档（跨助手通用）

| 文档 | 路径 | 内容 |
|---|---|---|
| 项目架构 | `backend/config/agent/project-architecture.md` | 仓库结构、技术栈、本地服务与端口 |
| 后端 API 目录 | `backend/config/agent/backend-api-catalog.md` | 非认证/非收费的后端 API 分组 |
| 技能与实现索引 | `backend/config/agent/skills-index.md` | 工作流步骤实现路径、Skill/MCP 位置 |

## 选择指引

- 用户要"建一个节点/接口" → `node-creation.md`
- 用户要"编排/规划工作流、画流程" → `workflow-orchestration.md`
- 用户要"解释任务为什么失败/怎么跑起来" → `task-execution.md`
- 用户要"整理文件/目录规划" → `file-management.md`
- 用户要"发布作品/多平台发布" → `publishing.md`
- 用户要"了解项目本身/技术栈" → `project-architecture.md`、`backend-api-catalog.md`

读取对应文档后，如文档中引用了代码或配置文件，应继续用 `read`/`grep` 按需核实，不要凭记忆编造实现细节。

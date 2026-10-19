"""s_expert_agent: 召唤专家工作流节点。

与「小pi通用智能体」(s_pi_agent) 同构，复用其一次性 Pi 会话、动态输入输出端口、
``[PI_TASK_DONE]`` 验收与产物收拢逻辑（cache/agent_{node_id}_{i}{ext}）。

差异在于能力来源：
- 不提供 Skill / MCP 选择器，改为「专家选择」：选定已安装的专家团（pack）
- 只注入该专家团自己的指导文件 ``~/.claude/skills/<pack_key>/skill.md``，
  不再串联全部成员技能正文，避免挤爆上下文（成员技能仅列出名字供按需取用）
- 不单独提供「任务」字段：角色与任务一并在「人设设定」里说明
- 提供「输入项说明」（每个输入端口一条说明），协助智能体快速理解上游传入的数据
"""
import json
from pathlib import Path
from typing import Any, Callable, Optional

from backend.pi_rpc import get_pi_manager
from backend.steps.s_pi_agent import S_PiAgent

# 专家团指导文件的注入上限。会话系统提示最终会被截断到 32000 字符，
# 故指导文件留出上限，保证背景、契约与回报规则不被截断。
PACK_GUIDE_LIMIT = 20000


class S_ExpertAgent(S_PiAgent):
    """召唤专家：以选定专家团的指导文件为能力底座执行工作流环节。"""

    step_id = "expert_agent"
    step_name = "召唤专家"
    dependencies = []

    # 本次执行的专家团上下文（由 _collect_recommended_tools 组装，供提示词拼装使用）
    _expert_context: dict[str, Any] = {}

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        config = getattr(self, "_node_config", {}) or {}
        if not str(config.get("persona", "")).strip():
            raise ValueError("召唤专家需要人设设定")
        if not str(config.get("pack_id", "") or "").strip():
            raise ValueError("召唤专家需要选择专家团")
        return super().run(task_dir, callback, cancel_callback)

    def validate_inputs(self, task_dir: str) -> bool:
        config = getattr(self, "_node_config", {}) or {}
        if not str(config.get("persona", "")).strip():
            return False
        return bool(str(config.get("pack_id", "") or "").strip())

    # ---------- 专家团解析 ----------

    def _pack_info(self, pack_id: str) -> dict[str, Any]:
        """按 pack_id 从 SkillHUB 安装记录（skills_store_lock.json）中取出专家团。"""
        for pack in get_pi_manager().packs():
            if str(pack.get("pack_id")) == pack_id:
                return pack
        raise ValueError(
            f"未找到专家团「{pack_id}」，它可能已被卸载。"
            "请到「Agent 设置 → 专家团」确认，或用「组建专家团」助手重新安装后再执行本节点。"
        )

    @staticmethod
    def _pack_guide(pack_key: str) -> tuple[str, str]:
        """读取专家团自带的指导文件 ~/.claude/skills/<pack_key>/skill.md（大小写兼容）。"""
        root = Path(__file__).resolve().parents[2]
        bases = [
            Path.home() / ".claude" / "skills" / pack_key,
            Path.home() / ".agent" / "skills" / pack_key,
            root / "backend" / "config" / "agent" / "skills" / pack_key,
        ]
        for base in bases:
            if not base.is_dir():
                continue
            for name in ("skill.md", "SKILL.md", "README.md"):
                target = base / name
                if target.is_file():
                    return str(target), target.read_text(encoding="utf-8", errors="replace")
        return "", ""

    @staticmethod
    def _normalize_input_items(raw_items: Any) -> list[dict[str, Any]]:
        """规范化输入项说明，保证与输入端口一一对应。"""
        if not isinstance(raw_items, list):
            return []
        items: list[dict[str, Any]] = []
        for i, item in enumerate(raw_items[:8], start=1):
            if not isinstance(item, dict):
                item = {}
            items.append({
                "index": i,
                "port": str(item.get("port") or f"输入{i}"),
                "desc": str(item.get("desc") or ""),
            })
        return items

    # ---------- 组装逻辑 ----------

    def _collect_recommended_tools(self, config: dict[str, Any]) -> dict[str, Any]:
        """收集专家团摘要、指导文件正文与输入项说明（替代 pi_agent 的 Skill/MCP 推荐）。"""
        pack_id = str(config.get("pack_id", "") or "").strip()
        pack = self._pack_info(pack_id)
        guide_path, guide = self._pack_guide(str(pack.get("pack_id") or pack_id))
        if len(guide) > PACK_GUIDE_LIMIT:
            guide = guide[:PACK_GUIDE_LIMIT] + "\n...(已截断)"
        members = [
            str(item.get("slug") or "").strip()
            for item in (pack.get("skills") or [])
            if str(item.get("slug") or "").strip()
        ]
        self._expert_context = {
            "pack": {
                "pack_id": str(pack.get("pack_id") or ""),
                "display_name": str(pack.get("display_name") or ""),
                "skills": members,
            },
            "guide": {"path": guide_path, "text": guide},
            "input_items": self._normalize_input_items(config.get("input_items", [])),
        }
        return self._expert_context["pack"]

    def _build_system_prompt(
        self,
        persona: str,
        background: dict[str, Any],
        recommended: dict[str, Any],
        input_ports: dict[str, Any],
        output_items: list[dict[str, Any]],
    ) -> str:
        context = getattr(self, "_expert_context", {}) or {}
        pack = context.get("pack") or recommended or {}
        guide = context.get("guide") or {}
        input_items = context.get("input_items") or []

        if input_items:
            input_section = json.dumps(
                [
                    {
                        "port": item["port"],
                        "说明": item["desc"],
                        "值": input_ports.get(f"input_{item['index']}", ""),
                    }
                    for item in input_items
                ],
                ensure_ascii=False,
                indent=2,
            )
        else:
            input_section = json.dumps(input_ports, ensure_ascii=False, indent=2)

        parts = [
            persona,
            "你是当前 VideoLingoFlow 工作流中的一个节点执行器，本次由「召唤专家」节点唤起。"
            "你的能力底座来自用户选定的专家团：请先阅读下方专家团指导文件，严格按其方法、规范与流程完成任务；"
            "指导文件中列出的成员技能只在确实需要时再按名取用，不要一次性全部展开。"
            "任务完成后必须以约定的结束标识回报验收结果。",
            f"## 任务背景\n{json.dumps(background, ensure_ascii=False, indent=2)}",
            f"## 召唤的专家团\n{json.dumps(pack, ensure_ascii=False, indent=2)}",
        ]
        if guide.get("text"):
            parts.append(f"## 专家团指导文件（{guide.get('path')}）\n{guide['text']}")
        elif guide.get("path") == "":
            parts.append("## 专家团指导文件\n（未找到该专家团的 skill.md，请确认专家团已完整安装）")
        parts.extend([
            f"## 本节点输入端口（含说明）\n{input_section}",
            f"## 本节点要求输出的产物\n{json.dumps(output_items, ensure_ascii=False, indent=2)}",
            (
                "## 执行与回报规则\n"
                "1. 输入端口的值可能为字符串或文件路径（相对任务目录），请按需读取后再处理。\n"
                "2. 按要求完成本次任务并生成产物。每个需要落盘的产物请保存到任务目录下（推荐 cache/ 目录），并记录其相对路径。\n"
                "3. 任务完成后，在最终回复的最后单独输出一行结束标识：\n"
                "   [PI_TASK_DONE]\n"
                "   并在其后输出验收 JSON（不要用代码块包裹）：\n"
                '   {"status": "success" | "failed", "message": "简要说明", "outputs": {"1": "相对路径或文本值", "2": "..."}}\n'
                "   其中 outputs 的键为输出序号（1 开始），值可以是相对任务目录的文件路径，或字符串类型产物的直接文本值。\n"
                "4. 若执行失败，同样输出结束标识并置 status 为 failed。"
            ),
        ])
        return "\n\n".join(parts)

    def _build_task_instruction(self, input_ports: dict[str, Any], output_items: list[dict[str, Any]]) -> str:
        context = getattr(self, "_expert_context", {}) or {}
        pack = context.get("pack") or {}
        return (
            "请开始执行本次工作流节点任务（角色与任务见系统提示中的人设设定）。\n"
            f"召唤的专家团：{pack.get('display_name') or pack.get('pack_id') or '（未指定）'}"
            f"（成员技能：{', '.join(pack.get('skills') or []) or '无'}，按需取用）\n"
            f"输入端口数据：{json.dumps(input_ports, ensure_ascii=False)}\n"
            f"输出要求：{json.dumps(output_items, ensure_ascii=False)}\n"
            "完成后按系统提示中的约定输出 [PI_TASK_DONE] 结束标识与验收 JSON。"
        )

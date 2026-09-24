import type { NodeTypeDef } from "./workflowTypes";

// 节点「历史默认名」表。
//
// 背景：添加节点时会把当时的节点名写进 node.data.label，而画布渲染是
// `label || nodeType.name`（label 优先）。因此节点改名后，老工作流里已保存
// 的 label 会一直显示旧名，即使后端节点定义已经更新。
//
// 这里做一次显示层兜底：仅当 label 恰好等于某个历史默认名时改用当前节点名；
// 用户自己改过名的节点不受影响。
const LEGACY_DEFAULT_LABELS: Record<string, string[]> = {
  opencode_agent: ["OpenCode 智能体"],
};

/** 解析节点显示名：把历史默认名替换为当前节点名，兼容用户自定义名。 */
export function resolveNodeLabel(
  nodeType: Pick<NodeTypeDef, "id" | "name">,
  label?: string,
): string {
  const raw = String(label ?? "").trim();
  if (!raw) return nodeType.name;
  const legacy = LEGACY_DEFAULT_LABELS[nodeType.id];
  if (legacy && legacy.includes(raw)) return nodeType.name;
  return raw;
}

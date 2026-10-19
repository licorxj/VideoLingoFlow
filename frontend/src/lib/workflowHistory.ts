/**
 * 工作流画布「撤销 / 重做」的纯逻辑部分（快照 + 指纹 + 运行态保护）。
 *
 * 设计要点：
 * 1. 快照式历史：不 patch ReactFlow 内部状态，撤销/重做时整份 nodes/edges 还原，
 *    这样组合/循环容器内部结构也能整体回退。
 * 2. 指纹只覆盖「结构 + 配置」：忽略选中态（点选节点不该产生一步）与
 *    ReactFlow 的内部测量字段（width/height/measured/dragging）。
 * 3. 忽略运行态字段：任务轮询与 WS 订阅每秒刷新 status/outputs，
 *    若纳入指纹会在执行期间把历史栈冲垮。
 * 4. 恢复时保留当前运行态：历史条目里的 status/outputs 是「当时」的，
 *    直接覆盖会把正在跑的实时状态弄乱。
 */

/** 画布快照 */
export interface CanvasSnapshot {
  nodes: any[];
  edges: any[];
}

export interface HistoryEntry extends CanvasSnapshot {
  /** 剔除运行态与选中态后的指纹，用于判断这一步是否真的改了画布 */
  fingerprint: string;
}

/** 运行态字段：任务轮询 / WS 订阅持续刷新，不算作用户的一步编辑 */
export const RUNTIME_KEYS = [
  "status", "progress", "message", "outputs", "error", "duration", "workbench_url", "loopProgress",
] as const;

function stripRuntime(data: any) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const out: Record<string, any> = {};
  for (const key of Object.keys(data)) {
    if ((RUNTIME_KEYS as readonly string[]).includes(key)) continue;
    out[key] = data[key];
  }
  return out;
}

/** 结构 + 配置指纹：刻意不含 selected / width / height / measured / dragging */
export function snapshotFingerprint(snap: CanvasSnapshot): string {
  const nodes = snap.nodes.map((n: any) => [
    n?.id ?? null,
    n?.type ?? "workflow",
    n?.position?.x ?? null,
    n?.position?.y ?? null,
    n?.parentId ?? null,
    n?.hidden ? 1 : 0,
    stripRuntime(n?.data),
  ]);
  const edges = snap.edges.map((e: any) => [
    e?.id ?? null,
    e?.source ?? null,
    e?.target ?? null,
    e?.sourceHandle ?? null,
    e?.targetHandle ?? null,
    e?.type ?? null,
  ]);
  return JSON.stringify([nodes, edges]);
}

export function cloneSnapshot(snap: CanvasSnapshot): CanvasSnapshot {
  return {
    nodes: JSON.parse(JSON.stringify(snap?.nodes || [])),
    edges: JSON.parse(JSON.stringify(snap?.edges || [])),
  };
}

/**
 * 恢复快照时，用「当前画布」里同 id 节点的运行态字段覆盖历史值，
 * 避免撤销把正在运行的任务的实时输出回退掉。
 */
export function preserveRuntimeFields(restored: any[], current: any[]): any[] {
  const currentMap = new Map<string, any>();
  for (const n of current || []) {
    if (n?.id) currentMap.set(n.id, n);
  }
  return (restored || []).map((n: any) => {
    const cur = n?.id ? currentMap.get(n.id) : undefined;
    if (!cur?.data) return { ...n, dragging: false };
    const data: Record<string, any> = { ...n.data };
    for (const key of RUNTIME_KEYS) {
      if (cur.data[key] !== undefined) data[key] = cur.data[key];
    }
    return { ...n, dragging: false, data };
  });
}
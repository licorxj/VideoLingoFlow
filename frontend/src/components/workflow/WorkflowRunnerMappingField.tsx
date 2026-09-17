import { useEffect, useMemo, useState } from "react";
import client from "@/api/client";
import { Plus, Trash2 } from "lucide-react";

/** 「工作流执行器」节点的输入输出映射编辑器。

内部端口不依赖节点类型元数据，而是**从子工作流定义自身的 edges 反推**
（targetHandle 去 in- 前缀即输入端口，sourceHandle 去 out- 前缀即输出端口），
这样拿到的端口一定是该子图真实在用的，比读节点类型定义更可靠。
端口同时允许手填（input + datalist），覆盖未被连线暴露的端口。
*/
interface MappingRow {
  exposedPortId?: string;
  targetNodeId?: string;
  targetPortId?: string;
  internalNodeId?: string;
  internalPortId?: string;
}

interface Props {
  field?: { key: string };
  config: Record<string, any>;
  onConfigChange: (key: string, value: any) => void;
}

const INPUT_PORTS = ["in_1", "in_2", "in_3", "in_4"];
const OUTPUT_PORTS = ["out_1", "out_2", "out_3", "out_4"];
const INPUT_NODE_PORTS = ["video", "audio", "subtitle", "url"];

function stripPrefix(handle: unknown, prefix: string): string {
  const raw = String(handle || "");
  return raw.startsWith(prefix) ? raw.slice(prefix.length) : raw;
}

export default function WorkflowRunnerMappingField({ config, onConfigChange }: Props) {
  const wfId = String(config.targetWorkflowId || "");
  const refMode = String(config.refMode || "snapshot");
  const [wf, setWf] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const inputMappings: MappingRow[] = Array.isArray(config.inputMappings) ? config.inputMappings : [];
  const outputMappings: MappingRow[] = Array.isArray(config.outputMappings) ? config.outputMappings : [];

  // 拉取目标工作流定义：用于列出内部节点 / 端口，并在快照模式下写入 config 供后端执行
  useEffect(() => {
    if (!wfId) {
      setWf(null);
      setError("");
      return;
    }
    let alive = true;
    setLoading(true);
    client
      .get(`/api/workflows/${wfId}`)
      .then((res) => {
        if (!alive) return;
        const data = res.data || {};
        setWf(data);
        setError("");
        if (refMode === "snapshot") {
          const snap = { nodes: data.nodes || [], edges: data.edges || [] };
          if (JSON.stringify(config.workflowSnapshot || {}) !== JSON.stringify(snap)) {
            onConfigChange("workflowSnapshot", snap);
          }
        }
      })
      .catch(() => {
        if (!alive) return;
        setError("读取工作流失败，请检查目标工作流是否存在");
        setWf(null);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wfId, refMode]);

  const nodes = useMemo(
    () => (wf?.nodes || []).filter((n: any) => n && n.id),
    [wf]
  );

  const nodeOptions = useMemo<{ id: string; label: string; nodeType: string }[]>(
    () =>
      nodes.map((n: any) => {
        const d = n.data || {};
        const type = String(d.nodeType || "");
        const label = String(d.label || type || n.id);
        return { id: String(n.id), label: `${label} · ${n.id}`, nodeType: type };
      }),
    [nodes]
  );

  /** 从 edges 反推每个内部节点实际使用的输入 / 输出端口 */
  const portsByNode = useMemo(() => {
    const map: Record<string, { inputs: string[]; outputs: string[] }> = {};
    for (const n of nodes) map[String(n.id)] = { inputs: [], outputs: [] };
    for (const e of wf?.edges || []) {
      const s = String(e.source || "");
      const t = String(e.target || "");
      if (map[t] && e.targetHandle) {
        const p = stripPrefix(e.targetHandle, "in-");
        if (p && !map[t].inputs.includes(p)) map[t].inputs.push(p);
      }
      if (map[s] && e.sourceHandle) {
        const p = stripPrefix(e.sourceHandle, "out-");
        if (p && !map[s].outputs.includes(p)) map[s].outputs.push(p);
      }
    }
    for (const n of nodes) {
      const d = n.data || {};
      if (String(d.nodeType || "") === "input") {
        const list = map[String(n.id)].outputs;
        for (const p of INPUT_NODE_PORTS) if (!list.includes(p)) list.push(p);
      }
    }
    return map;
  }, [nodes, wf]);

  const setInputMappings = (rows: MappingRow[]) => onConfigChange("inputMappings", rows);
  const setOutputMappings = (rows: MappingRow[]) => onConfigChange("outputMappings", rows);

  const updateInput = (index: number, patch: MappingRow) => {
    const next = inputMappings.map((row, i) => (i === index ? { ...row, ...patch } : row));
    setInputMappings(next);
  };
  const updateOutput = (index: number, patch: MappingRow) => {
    const next = outputMappings.map((row, i) => (i === index ? { ...row, ...patch } : row));
    setOutputMappings(next);
  };

  const cellClass =
    "w-full rounded border border-border bg-background px-1.5 py-1 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary";

  const renderNodeSelect = (value: string, onChange: (v: string) => void) => (
    <select className={cellClass} value={value || ""} onChange={(e) => onChange(e.target.value)}>
      <option value="">选择节点</option>
      {nodeOptions.map((opt) => (
        <option key={opt.id} value={opt.id}>
          {opt.label}
        </option>
      ))}
    </select>
  );

  const renderPortInput = (
    value: string,
    candidates: string[],
    listId: string,
    onChange: (v: string) => void
  ) => (
    <>
      <input
        className={cellClass}
        list={listId}
        value={value || ""}
        placeholder="端口 id"
        onChange={(e) => onChange(e.target.value)}
      />
      <datalist id={listId}>
        {candidates.map((p) => (
          <option key={p} value={p} />
        ))}
      </datalist>
    </>
  );

  const renderSection = (
    title: string,
    hint: string,
    rows: MappingRow[],
    exposedPorts: string[],
    direction: "in" | "out",
    onAdd: () => void,
    onRemove: (i: number) => void,
    onUpdate: (i: number, patch: MappingRow) => void
  ) => (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-medium text-foreground">{title}</div>
        <button
          type="button"
          onClick={onAdd}
          className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground hover:border-primary"
        >
          <Plus className="h-3 w-3" />
          添加
        </button>
      </div>
      <div className="text-[10px] leading-tight text-muted-foreground">{hint}</div>
      {rows.length === 0 ? (
        <div className="text-[10px] text-muted-foreground/70">未配置映射</div>
      ) : (
        <div className="space-y-1">
          {rows.map((row, index) => {
            const nodeId = String(
              (direction === "in" ? row.targetNodeId : row.internalNodeId) || ""
            );
            const candidates = portsByNode[nodeId]
              ? direction === "in"
                ? portsByNode[nodeId].inputs
                : portsByNode[nodeId].outputs
              : [];
            const portValue = String(
              (direction === "in" ? row.targetPortId : row.internalPortId) || ""
            );
            return (
              <div key={index} className="grid grid-cols-[80px_1fr_1fr_20px] gap-1 items-center">
                <select
                  className={cellClass}
                  value={String(row.exposedPortId || "")}
                  onChange={(e) => onUpdate(index, { exposedPortId: e.target.value } as MappingRow)}
                >
                  <option value="">端口</option>
                  {exposedPorts.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
                {renderNodeSelect(nodeId, (v) =>
                  onUpdate(
                    index,
                    (direction === "in" ? { targetNodeId: v } : { internalNodeId: v }) as MappingRow
                  )
                )}
                {renderPortInput(
                  portValue,
                  candidates,
                  `wf-port-${direction}-${index}`,
                  (v) =>
                    onUpdate(
                      index,
                      (direction === "in"
                        ? { targetPortId: v }
                        : { internalPortId: v }) as MappingRow
                    )
                )}
                <button
                  type="button"
                  onClick={() => onRemove(index)}
                  className="text-muted-foreground hover:text-destructive"
                  title="删除"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );

  if (!wfId) {
    return (
      <div className="rounded-md border border-dashed border-border px-2 py-2 text-[10px] text-muted-foreground">
        请先在上方选择「目标工作流」，之后即可在此配置输入输出映射
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-md border border-border bg-background/40 p-2">
      <div className="text-[10px] text-muted-foreground">
        {loading ? "正在读取工作流定义…" : error ? error : `已加载 ${nodeOptions.length} 个内部节点`}
      </div>
      {renderSection(
        "输入映射（本节点 → 子工作流）",
        "把本节点的 in_1~in_4 端口值，注入到子工作流某个节点的输入端口",
        inputMappings,
        INPUT_PORTS,
        "in",
        () => setInputMappings([...inputMappings, { exposedPortId: "", targetNodeId: "", targetPortId: "" }]),
        (i) => setInputMappings(inputMappings.filter((_, idx) => idx !== i)),
        updateInput
      )}
      {renderSection(
        "输出映射（子工作流 → 本节点）",
        "把子工作流某个节点的输出端口，映射为本节点的 out_1~out_4 端口；留空则按「输出取值」策略自动推断",
        outputMappings,
        OUTPUT_PORTS,
        "out",
        () => setOutputMappings([...outputMappings, { exposedPortId: "", internalNodeId: "", internalPortId: "" }]),
        (i) => setOutputMappings(outputMappings.filter((_, idx) => idx !== i)),
        updateOutput
      )}
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import client from "@/api/client";
import { getNodeTypeDef, isConfigFieldVisible, type ConfigField } from "@/lib/workflowTypes";
import { LANGUAGE_OPTIONS } from "@/lib/languages";
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
const INPUT_NODE_PORTS = ["video", "audio", "subtitle", "url", "text"];

/** 子工作流 input 节点的数据类字段：由上方「输入映射」负责传入，不在设置项里重复填写 */
const INPUT_DATA_FIELD_KEYS = [
  "selectedTypes",
  "videoPath",
  "audioPath",
  "subtitlePath",
  "url",
  "filePath",
  "text",
];

/** 端口候选项：id 写入映射，label 用于下拉展示 */
interface PortOption {
  id: string;
  label: string;
}

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
        // GET /api/workflows/{id} 返回 { workflow: {...}, removed_edges: [...] }，需取内层 workflow
        const payload = res.data || {};
        const data = payload.workflow || payload;
        setWf(data);
        if (!(data.nodes || []).length) {
          setError("该工作流没有任何节点，无法建立映射");
          return;
        }
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
        const id = String(n.id);
        // 节点 id 形如 node_1_1780590163157，完整展示会撑爆下拉；保留尾部 6 位以便区分同类节点
        const short = id.length > 10 ? `…${id.slice(-6)}` : id;
        return { id, label: `${label} · ${short}`, nodeType: type };
      }),
    [nodes]
  );

  /** 汇总每个内部节点可用的输入 / 输出端口，供下拉选择：
   *  1) 节点类型定义里的全部端口（label 友好，且覆盖未被连线暴露的端口）
   *  2) edges 反推到的端口（补上类型定义里没有的历史端口）
   *  3) input 节点的隐含输出端口
   */
  const portsByNode = useMemo(() => {
    const map: Record<string, { inputs: PortOption[]; outputs: PortOption[] }> = {};
    const push = (list: PortOption[], id: string, label?: string) => {
      if (!id) return;
      const exist = list.find((p) => p.id === id);
      if (exist) {
        if (label && exist.label === exist.id) exist.label = label;
        return;
      }
      list.push({ id, label: label || id });
    };

    for (const n of nodes) {
      const key = String(n.id);
      map[key] = { inputs: [], outputs: [] };
      const def = getNodeTypeDef(String((n.data || {}).nodeType || ""));
      for (const p of (def?.inputs || []) as any[]) push(map[key].inputs, String(p?.id || ""), p?.label);
      for (const p of (def?.outputs || []) as any[]) {
        const pid = String(p?.id || "");
        if (pid === "no_input") continue; // 「不需要输入」不是数据端口，不作为映射目标
        push(map[key].outputs, pid, p?.label);
      }
    }

    for (const e of wf?.edges || []) {
      const s = String(e.source || "");
      const t = String(e.target || "");
      if (map[t] && e.targetHandle) push(map[t].inputs, stripPrefix(e.targetHandle, "in-"));
      if (map[s] && e.sourceHandle) push(map[s].outputs, stripPrefix(e.sourceHandle, "out-"));
    }

    for (const n of nodes) {
      const key = String(n.id);
      if (String((n.data || {}).nodeType || "") === "input") {
        for (const p of INPUT_NODE_PORTS) push(map[key].outputs, p);
      }
    }
    return map;
  }, [nodes, wf]);

  const setInputMappings = (rows: MappingRow[]) => onConfigChange("inputMappings", rows);
  const setOutputMappings = (rows: MappingRow[]) => onConfigChange("outputMappings", rows);

  /** 子工作流的「输入」节点：既是输入映射的唯一目标，也承载可覆盖的设置项 */
  const innerInputNodes = useMemo<{ id: string; label: string; config: Record<string, any> }[]>(
    () =>
      nodes
        .filter((n: any) => String((n.data || {}).nodeType || "") === "input")
        .map((n: any) => {
          const id = String(n.id);
          return {
            id,
            label: `${String((n.data || {}).label || "输入")} · ${id.length > 10 ? `…${id.slice(-6)}` : id}`,
            config: ((n.data || {}).config || {}) as Record<string, any>,
          };
        }),
    [nodes]
  );

  /** 输入桥接的目标固定为子工作流的输入节点（取第一个），不允许改选其他节点 */
  const defaultInputNodeId = innerInputNodes.length ? innerInputNodes[0].id : "";

  // 强制收敛：把所有输入映射行的目标统一为输入节点，顺带纠正历史配置里指向其他节点的值
  useEffect(() => {
    if (!defaultInputNodeId || inputMappings.length === 0) return;
    if (inputMappings.every((row) => row.targetNodeId === defaultInputNodeId)) return;
    setInputMappings(
      inputMappings.map((row) =>
        row.targetNodeId === defaultInputNodeId ? row : { ...row, targetNodeId: defaultInputNodeId }
      )
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultInputNodeId, inputMappings]);

  const updateInput = (index: number, patch: MappingRow) => {
    const next = inputMappings.map((row, i) => (i === index ? { ...row, ...patch } : row));
    setInputMappings(next);
  };
  const updateOutput = (index: number, patch: MappingRow) => {
    const next = outputMappings.map((row, i) => (i === index ? { ...row, ...patch } : row));
    setOutputMappings(next);
  };

  // ── 输入节点设置项：覆盖子工作流 input 节点的 config（语言 / 变量 / 默认输入等） ──
  const inputConfigs: Record<string, Record<string, any>> =
    config.inputConfigs && typeof config.inputConfigs === "object" ? config.inputConfigs : {};

  const setInputConfigValue = (nodeId: string, key: string, value: any) => {
    onConfigChange("inputConfigs", {
      ...inputConfigs,
      [nodeId]: { ...(inputConfigs[nodeId] || {}), [key]: value },
    });
  };

  const renderInputFieldControl = (
    field: ConfigField,
    value: any,
    onChange: (v: any) => void
  ) => {
    if (field.type === "chips") {
      const selected: string[] = Array.isArray(value) ? value : [];
      return (
        <div className="flex flex-wrap gap-1">
          {(field.options || []).map((opt) => {
            const on = selected.includes(opt.value);
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() =>
                  onChange(on ? selected.filter((v) => v !== opt.value) : [...selected, opt.value])
                }
                className={
                  "rounded-full border px-2 py-0.5 text-[10px] transition-colors " +
                  (on
                    ? "border-primary bg-primary/15 text-foreground"
                    : "border-border text-muted-foreground hover:text-foreground")
                }
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      );
    }
    if (field.type === "checkbox" || field.type === "toggle") {
      return (
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          className="h-3.5 w-3.5 rounded border-border accent-primary"
        />
      );
    }
    if (field.type === "select" || field.type === "language-select" || field.type === "multiselect") {
      const options = field.type === "language-select" ? LANGUAGE_OPTIONS : field.options || [];
      return (
        <select
          className={cellClass}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">沿用子工作流原设置</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      );
    }
    if (field.type === "number" || field.type === "slider") {
      return (
        <input
          type="number"
          className={cellClass}
          value={value ?? ""}
          min={field.min}
          max={field.max}
          step={field.step}
          onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
        />
      );
    }
    return (
      <input
        type="text"
        className={cellClass}
        value={value ?? ""}
        placeholder={field.placeholder || ""}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  };

  const cellClass =
    "w-full rounded border border-border bg-background px-1.5 py-1 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary";

  const renderNodeSelect = (
    value: string,
    options: { id: string; label: string }[],
    placeholder: string,
    onChange: (v: string) => void
  ) => (
    <select className={cellClass} value={value || ""} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {options.map((opt) => (
        <option key={opt.id} value={opt.id}>
          {opt.label}
        </option>
      ))}
    </select>
  );

  const renderPortSelect = (
    value: string,
    candidates: PortOption[],
    emptyHint: string,
    onChange: (v: string) => void
  ) => {
    if (!candidates.length) {
      return (
        <select className={cellClass} value="" disabled title={emptyHint}>
          <option value="">{emptyHint}</option>
        </select>
      );
    }
    // 历史配置里的端口若不在候选中，保留为「当前值」项，避免静默丢失
    const known = candidates.some((c) => c.id === value);
    return (
      <select className={cellClass} value={value || ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">选择端口</option>
        {!known && value ? <option value={value}>{value}（当前值）</option> : null}
        {candidates.map((c) => (
          <option key={c.id} value={c.id}>
            {c.label === c.id ? c.id : `${c.label} · ${c.id}`}
          </option>
        ))}
      </select>
    );
  };

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
            // 输入映射的目标固定为输入节点，直接用固定值，不依赖行内数据
            const nodeId = String(
              (direction === "in" ? defaultInputNodeId : row.internalNodeId) || ""
            );
            // 两种映射取的都是该节点的 outputs：
            // 输入映射注入的是 input 节点的产出端口（video/audio/subtitle/url…），
            // 输出映射取的是内部节点的产出端口
            const candidates = portsByNode[nodeId]?.outputs ?? [];
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
                {direction === "in" ? (
                  <div
                    className="truncate rounded border border-dashed border-border px-1.5 py-1 text-[11px] text-muted-foreground"
                    title={nodeId}
                  >
                    {innerInputNodes[0]?.label || "该工作流无输入节点"}
                  </div>
                ) : (
                  renderNodeSelect(nodeId, nodeOptions, "选择节点", (v) =>
                    onUpdate(index, { internalNodeId: v } as MappingRow)
                  )
                )}
                {renderPortSelect(
                  portValue,
                  candidates,
                  nodeId ? "该节点无可用端口" : "请先选择节点",
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
        "把本节点的 in_1~in_4 端口值，注入到子工作流「输入」节点对应的输入项（目标固定为输入节点，不可改选）",
        inputMappings,
        INPUT_PORTS,
        "in",
        () => {
          if (!defaultInputNodeId) return;
          setInputMappings([
            ...inputMappings,
            { exposedPortId: "", targetNodeId: defaultInputNodeId, targetPortId: "" },
          ]);
        },
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
      {innerInputNodes.length > 0
        ? innerInputNodes.map((node) => {
            const fields = (getNodeTypeDef("input")?.configFields || []) as ConfigField[];
            const override = inputConfigs[node.id] || {};
            const merged = { ...node.config, ...override };
            return (
              <div key={node.id} className="space-y-1.5">
                <div className="text-[11px] font-medium text-foreground">
                  输入节点设置（{node.label}）
                </div>
                <div className="text-[10px] leading-tight text-muted-foreground">
                  「输入方式 / 各输入文件」由上方「输入映射」负责传入，此处不再重复设置；本区只覆盖输入语言 / 输出语言 / 变量等设置项，留空表示沿用子工作流原设置
                </div>
                <div className="grid grid-cols-2 gap-x-2 gap-y-2 rounded-md border border-border bg-background/40 p-2">
                  {fields
                    .filter(
                      (f) =>
                        !INPUT_DATA_FIELD_KEYS.includes(f.key) && isConfigFieldVisible(f, merged)
                    )
                    .map((field) => {
                      const inline = field.type === "checkbox" || field.type === "toggle";
                      const raw = override[field.key];
                      const value =
                        raw !== undefined
                          ? raw
                          : node.config[field.key] ?? field.defaultValue ?? "";
                      const control = renderInputFieldControl(field, value, (v) =>
                        setInputConfigValue(node.id, field.key, v)
                      );
                      return (
                        <div
                          key={field.key}
                          className={field.colSpan === "full" ? "col-span-2" : ""}
                        >
                          {inline ? (
                            <label className="flex items-center gap-1.5 text-[11px] text-foreground">
                              {control}
                              {field.label}
                            </label>
                          ) : (
                            <>
                              <div className="mb-0.5 text-[10px] text-muted-foreground">
                                {field.label}
                              </div>
                              {control}
                            </>
                          )}
                        </div>
                      );
                    })}
                </div>
              </div>
            );
          })
        : null}
    </div>
  );
}

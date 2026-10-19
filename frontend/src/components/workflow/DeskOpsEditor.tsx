/**
 * AI剪辑链「剪辑编排」节点的 ops 可视化编辑器
 *
 * 把原先需要手写 JSON 的 ops 数组改成「逐条选择工具 + 按 schema 填参数」的表单：
 *   - 工具下拉：来自 GET /api/openchatcut/tools（headless 工具 + 参数 schema）
 *   - 参数控件：按 schema 的 type/enum 生成 input / number / checkbox / select / textarea
 *   - 引用上游：参数值支持 {{input.xxx}}（本节点输入端口）与 {{prev.xxx}}（上一个工具结果）
 *   - 序列化结果仍是标准 ops JSON：[{"tool":..., "args":{...}}]，后端零改动
 */
import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, GripVertical, Plus, Trash2, Variable } from "lucide-react";
import { cn } from "@/lib/utils";
import client from "@/api/client";

export interface DeskOp {
  tool: string;
  args: Record<string, any>;
}

export interface DeskToolParam {
  name: string;
  label?: string;
  type: string;
  enum?: string[] | null;
  description: string;
  required: boolean;
}

export interface DeskTool {
  name: string;
  label?: string;
  description: string;
  params: DeskToolParam[];
}

interface Props {
  value: any;
  onChange: (value: DeskOp[]) => void;
  /** 可引用的上游输入端口名（来自节点 inputs，如 asset_ids / clip_ids / project） */
  inputPorts?: string[];
  className?: string;
}

function parseOps(value: any): DeskOp[] {
  if (Array.isArray(value)) return value as DeskOp[];
  if (typeof value === "string" && value.trim()) {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed as DeskOp[];
    } catch {
      /* 非法 JSON 时按空处理，避免编辑器崩 */
    }
  }
  return [];
}

function ParamRow({
  param,
  value,
  onChange,
  inputPorts,
  opIndex,
}: {
  param: DeskToolParam;
  value: any;
  onChange: (value: any) => void;
  inputPorts: string[];
  opIndex: number;
}) {
  const isRef = typeof value === "string" && value.startsWith("{{");
  const [refMenu, setRefMenu] = useState(false);

  const setRef = (ref: string) => {
    onChange(ref);
    setRefMenu(false);
  };

  const baseCls =
    "w-full text-xs px-2 py-1.5 rounded-md border border-border/50 bg-background outline-none transition-all focus:border-primary/50";
  const label = (
    <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
      <span className="font-medium text-foreground/80">{param.label || param.name}</span>
      {param.required && <span className="text-destructive">*</span>}
      {param.description && (
        <span className="truncate text-muted-foreground/60" title={param.description}>
          {param.description}
        </span>
      )}
    </label>
  );

  const refButton = (
    <div className="relative">
      <button
        type="button"
        title="引用上游输入或上一个工具的结果"
        onClick={() => setRefMenu((v) => !v)}
        className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-md border transition-colors",
          isRef
            ? "border-ai/50 bg-ai/10 text-ai"
            : "border-border/50 text-muted-foreground hover:bg-accent hover:text-foreground",
        )}
      >
        <Variable className="h-3.5 w-3.5" />
      </button>
      {refMenu && (
        <div className="absolute right-0 top-8 z-30 w-52 rounded-lg border border-border bg-popover p-1 shadow-lg">
          <p className="px-2 py-1 text-[10px] font-semibold text-muted-foreground">引用上游输入</p>
          {inputPorts.length === 0 && (
            <p className="px-2 py-1 text-[10px] text-muted-foreground/70">本节点无输入端口</p>
          )}
          {inputPorts.map((port) => (
            <button
              key={port}
              type="button"
              className="block w-full rounded px-2 py-1 text-left font-mono text-[11px] hover:bg-accent"
              onClick={() => setRef(`{{input.${port}}}`)}
            >
              {`{{input.${port}}}`}
            </button>
          ))}
          <p className="mt-1 px-2 py-1 text-[10px] font-semibold text-muted-foreground">引用上一个工具结果</p>
          <button
            type="button"
            className="block w-full rounded px-2 py-1 text-left font-mono text-[11px] hover:bg-accent"
            onClick={() => setRef("{{prev}}")}
          >
            {`{{prev}}`}
          </button>
          <p className="px-2 py-1 text-[10px] leading-snug text-muted-foreground/70">
            也可手写 <code className="font-mono">{"{{prev.xxx}}"}</code> 取上个工具返回里的字段
          </p>
        </div>
      )}
    </div>
  );

  return (
    <div className="space-y-1">
      {label}
      <div className="flex items-center gap-1.5">
        {param.enum && param.enum.length > 0 ? (
          <select
            className={cn(baseCls, "flex-1")}
            value={typeof value === "string" ? value : ""}
            onChange={(e) => onChange(e.target.value)}
          >
            <option value="">（不填）</option>
            {param.enum.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        ) : param.type === "boolean" ? (
          <label className="flex flex-1 items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={!!value}
              onChange={(e) => onChange(e.target.checked)}
              className="h-3.5 w-3.5"
            />
            <span className="text-muted-foreground">开启</span>
          </label>
        ) : param.type === "number" || param.type === "integer" ? (
          <input
            type="number"
            className={cn(baseCls, "flex-1")}
            value={value ?? ""}
            onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
          />
        ) : param.type === "array" || param.type === "object" ? (
          <textarea
            className={cn(baseCls, "flex-1 font-mono")}
            rows={2}
            placeholder={param.type === "array" ? '["a","b"] 或每行一项' : '{"k":"v"}'}
            value={typeof value === "string" ? value : value == null ? "" : JSON.stringify(value)}
            onChange={(e) => {
              const text = e.target.value.trim();
              if (!text) return onChange(undefined);
              try {
                onChange(JSON.parse(text));
              } catch {
                onChange(text); // 暂时保留原文，序列化时再容错
              }
            }}
          />
        ) : (
          <input
            className={cn(baseCls, "flex-1", isRef && "font-mono text-ai")}
            value={value ?? ""}
            placeholder={param.type === "string" ? "文本值" : ""}
            onChange={(e) => onChange(e.target.value || undefined)}
          />
        )}
        {refButton}
      </div>
      {isRef && (
        <p className="text-[10px] text-ai/80">
          第 {opIndex + 1} 步 · 运行时会替换为实际值
        </p>
      )}
    </div>
  );
}

function OpCard({
  op,
  index,
  total,
  tool,
  inputPorts,
  onPatch,
  onRemove,
  onMove,
}: {
  op: DeskOp;
  index: number;
  total: number;
  tool?: DeskTool;
  inputPorts: string[];
  onPatch: (patch: Partial<DeskOp>) => void;
  onRemove: () => void;
  onMove: (direction: -1 | 1) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const filled = Object.values(op.args || {}).filter((v) => v !== undefined && v !== "").length;

  return (
    <div className="rounded-lg border border-border/60 bg-muted/20 p-2.5">
      <div className="flex items-center gap-1.5">
        <GripVertical className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50" />
        <span className="shrink-0 rounded bg-ai/10 px-1.5 py-0.5 text-[10px] font-semibold text-ai">
          {index + 1}
        </span>
        <span className="shrink-0 text-[10px] font-medium text-foreground/80">
          {tool?.label || "未选择工具"}
        </span>
        {tool?.label && tool.label !== tool.name && (
          <span className="shrink-0 font-mono text-[9px] text-muted-foreground/50">{tool.name}</span>
        )}
        {tool && filled > 0 && (
          <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {filled} 个参数
          </span>
        )}
        <div className="ml-auto flex items-center gap-0.5">
          <button
            type="button"
            title="上移"
            disabled={index === 0}
            className="rounded p-1 text-muted-foreground hover:bg-accent disabled:opacity-30"
            onClick={() => onMove(-1)}
          >
            <ChevronUp className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="下移"
            disabled={index === total - 1}
            className="rounded p-1 text-muted-foreground hover:bg-accent disabled:opacity-30"
            onClick={() => onMove(1)}
          >
            <ChevronDown className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title={collapsed ? "展开参数" : "收起参数"}
            className="rounded p-1 text-muted-foreground hover:bg-accent"
            onClick={() => setCollapsed((v) => !v)}
          >
            {collapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
          </button>
          <button
            type="button"
            title="删除这一步"
            className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            onClick={onRemove}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {tool?.description && (
        <p className="mt-1.5 line-clamp-2 text-[10px] leading-snug text-muted-foreground/80" title={tool.description}>
          {tool.description}
        </p>
      )}

      {!collapsed && (
        <div className="mt-2 space-y-2">
          {tool && tool.params.length > 0 ? (
            tool.params.map((param) => (
              <ParamRow
                key={param.name}
                param={param}
                opIndex={index}
                inputPorts={inputPorts}
                value={(op.args || {})[param.name]}
                onChange={(v) => {
                  const args = { ...(op.args || {}) };
                  if (v === undefined || v === "") delete args[param.name];
                  else args[param.name] = v;
                  onPatch({ args });
                }}
              />
            ))
          ) : (
            <p className="text-[10px] text-muted-foreground/70">
              {tool ? "该工具无需参数" : "请先在上方选择工具"}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default function DeskOpsEditor({ value, onChange, inputPorts = [], className }: Props) {
  const ops = useMemo(() => parseOps(value), [value]);
  const [tools, setTools] = useState<DeskTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    client
      .get("/api/openchatcut/tools")
      .then((res) => {
        if (!alive) return;
        const data = res.data || {};
        if (data.available === false) {
          setError(data.reason || "工具清单不可用");
          setTools([]);
        } else {
          setTools(Array.isArray(data.tools) ? data.tools : []);
          setError("");
        }
      })
      .catch(() => alive && setError("无法读取剪辑台工具清单"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const toolByName = useMemo(() => {
    const map: Record<string, DeskTool> = {};
    tools.forEach((t) => (map[t.name] = t));
    return map;
  }, [tools]);

  const commit = (next: DeskOp[]) => onChange(next);

  const addOp = () => commit([...ops, { tool: "", args: {} }]);

  const patchOp = (index: number, patch: Partial<DeskOp>) => {
    const next = ops.map((op, i) => (i === index ? { ...op, ...patch } : op));
    commit(next);
  };

  const removeOp = (index: number) => commit(ops.filter((_, i) => i !== index));

  const moveOp = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= ops.length) return;
    const next = [...ops];
    [next[index], next[target]] = [next[target], next[index]];
    commit(next);
  };

  return (
    <div className={cn("space-y-2", className)} onWheel={(e) => e.stopPropagation()}>
      {loading && <p className="text-[11px] text-muted-foreground">正在加载剪辑台工具清单…</p>}
      {!loading && error && (
        <p className="rounded-md border border-warning/30 bg-warning/10 px-2 py-1.5 text-[10px] text-warning">
          {error}
        </p>
      )}

      {ops.map((op, index) => (
        <div key={index} className="space-y-1.5">
          <select
            className="w-full rounded-md border border-border/50 bg-background px-2 py-1.5 text-xs outline-none transition-all focus:border-primary/50"
            value={op.tool || ""}
            onChange={(e) => patchOp(index, { tool: e.target.value, args: {} })}
          >
            <option value="">选择剪辑台工具…</option>
            {tools.map((tool) => (
              <option key={tool.name} value={tool.name}>
                {tool.label || tool.name}
                {tool.params.some((p) => p.required) ? " *" : ""}
              </option>
            ))}
          </select>
          <OpCard
            op={op}
            index={index}
            total={ops.length}
            tool={toolByName[op.tool]}
            inputPorts={inputPorts}
            onPatch={(patch) => patchOp(index, patch)}
            onRemove={() => removeOp(index)}
            onMove={(direction) => moveOp(index, direction)}
          />
        </div>
      ))}

      <button
        type="button"
        onClick={addOp}
        disabled={loading || !!error}
        className="flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-border/60 py-1.5 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-50"
      >
        <Plus className="h-3.5 w-3.5" />
        添加工具调用
      </button>

      {ops.length > 0 && (
        <p className="text-[10px] leading-relaxed text-muted-foreground/70">
          将按顺序执行 {ops.length} 个工具调用；任一步失败即中止。
          {inputPorts.length > 0 && <> 可引用上游：{inputPorts.map((p) => `{{input.${p}}}`).join("、")}</>}
        </p>
      )}
    </div>
  );
}

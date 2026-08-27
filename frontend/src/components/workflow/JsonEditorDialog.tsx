import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ChevronRight, FileJson, Maximize2, Minimize2, Plus, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";

type JsonValue = any;

interface Props {
  open: boolean;
  initialJson?: JsonValue;
  onClose: () => void;
  onSave: (data: JsonValue) => void;
  // 保存后直接触发节点运行（写回文件），可选
  onRun?: () => void;
}

const TYPE_COLORS: Record<string, string> = {
  object: "text-amber-600 dark:text-amber-400",
  array: "text-sky-600 dark:text-sky-400",
  string: "text-emerald-600 dark:text-emerald-400",
  number: "text-violet-600 dark:text-violet-400",
  boolean: "text-rose-600 dark:text-rose-400",
  null: "text-muted-foreground",
};

function typeOf(v: JsonValue): string {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  return typeof v;
}

/** 深拷贝 */
function clone<T>(v: T): T {
  return v === undefined ? v : JSON.parse(JSON.stringify(v));
}

function ScalarEditor({ value, type, onChange }: { value: JsonValue; type: string; onChange: (v: JsonValue) => void }) {
  if (type === "boolean") {
    return (
      <select
        value={value === true ? "true" : "false"}
        onChange={(e) => onChange(e.target.value === "true")}
        className="text-xs px-1.5 py-0.5 rounded border border-border/50 bg-background outline-none"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }
  if (type === "null") {
    return <span className="text-xs text-muted-foreground italic">null</span>;
  }
  if (type === "number") {
    return (
      <input
        type="number"
        value={value as number}
        onChange={(e) => {
          const n = e.target.value === "" ? 0 : Number(e.target.value);
          onChange(Number.isFinite(n) ? n : 0);
        }}
        className="w-32 text-xs px-1.5 py-0.5 rounded border border-border/50 bg-background outline-none"
        onPointerDown={(e) => e.stopPropagation()}
      />
    );
  }
  return (
    <input
      type="text"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      className="w-48 text-xs px-1.5 py-0.5 rounded border border-border/50 bg-background outline-none"
      onPointerDown={(e) => e.stopPropagation()}
    />
  );
}

function JsonTreeNode({ nodeKey, value, depth, onUpdate, onRemove }: {
  nodeKey: string | number;
  value: JsonValue;
  depth: number;
  onUpdate: (newValue: JsonValue) => void;
  onRemove: () => void;
}) {
  const [expanded, setExpanded] = useState(depth < 2);
  const t = typeOf(value);
  const isContainer = t === "object" || t === "array";

  const changeType = (newType: string) => {
    let next: JsonValue;
    if (newType === "object") next = {};
    else if (newType === "array") next = [];
    else if (newType === "boolean") next = false;
    else if (newType === "null") next = null;
    else next = "";
    onUpdate(next);
  };

  const label = String(nodeKey === "" ? '""' : nodeKey);

  return (
    <div className="ml-3 border-l border-border/30 pl-2">
      <div className="flex items-center gap-1 py-0.5 group">
        {isContainer ? (
          <button
            type="button"
            onClick={() => setExpanded((p) => !p)}
            className="p-0.5 rounded text-muted-foreground hover:text-foreground"
            onPointerDown={(e) => e.stopPropagation()}
          >
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </button>
        ) : (
          <span className="w-4" />
        )}
        <span className="text-xs font-medium text-foreground/80">{label}:</span>
        {isContainer ? (
          <span className={`text-[10px] ${TYPE_COLORS[t]}`}>
            {t === "array" ? `[${value.length}]` : `{${Object.keys(value).length}}`}
          </span>
        ) : (
          <ScalarEditor value={value} type={t} onChange={onUpdate} />
        )}
        {!isContainer && (
          <select
            value={t}
            onChange={(e) => changeType(e.target.value)}
            className="text-[10px] px-1 py-0.5 rounded border border-border/40 bg-background text-muted-foreground outline-none"
            onPointerDown={(e) => e.stopPropagation()}
          >
            <option value="string">string</option>
            <option value="number">number</option>
            <option value="boolean">boolean</option>
            <option value="null">null</option>
            <option value="object">object</option>
            <option value="array">array</option>
          </select>
        )}
        {isContainer && (
          <button
            type="button"
            onClick={() => onUpdate(addChild(value))}
            className="p-0.5 rounded text-muted-foreground/50 hover:text-primary opacity-0 group-hover:opacity-100"
            title="添加成员"
            onPointerDown={(e) => e.stopPropagation()}
          >
            <Plus className="w-3 h-3" />
          </button>
        )}
        <button
          type="button"
          onClick={onRemove}
          className="p-0.5 rounded text-muted-foreground/50 hover:text-red-500 opacity-0 group-hover:opacity-100"
          title="删除"
          onPointerDown={(e) => e.stopPropagation()}
        >
          <Trash2 className="w-3 h-3" />
        </button>
      </div>
      {isContainer && expanded && (
        <div className="ml-2">
          {Object.entries(value).map(([k, v]) => (
            <JsonTreeNode
              key={Array.isArray(value) ? k : k || "empty"}
              nodeKey={Array.isArray(value) ? `[${k}]` : k}
              value={v}
              depth={depth + 1}
              onUpdate={(nv) => onUpdateChild(value, k, nv)}
              onRemove={() => onUpdate(removeChild(value, k))}
            />
          ))}
        </div>
      )}
    </div>
  );

  function addChild(target: JsonValue): JsonValue {
    const copy = clone(target);
    if (Array.isArray(copy)) copy.push(null);
    else copy[""] = null;
    return copy;
  }
  function onUpdateChild(target: JsonValue, k: string, nv: JsonValue): JsonValue {
    const copy = clone(target);
    if (Array.isArray(copy)) copy[Number(k)] = nv;
    else copy[k] = nv;
    return copy;
  }
  function removeChild(target: JsonValue, k: string): JsonValue {
    const copy = clone(target);
    if (Array.isArray(copy)) copy.splice(Number(k), 1);
    else delete copy[k];
    return copy;
  }
}

export default function JsonEditorDialog({ open, initialJson, onClose, onSave, onRun }: Props) {
  const [text, setText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [data, setData] = useState<JsonValue>({});
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    if (!open) return;
    const initial = initialJson === undefined || initialJson === null ? {} : initialJson;
    setData(clone(initial));
    setText(JSON.stringify(initial, null, 2));
    setParseError(null);
  }, [open, initialJson]);

  const handleTextChange = useCallback((raw: string) => {
    setText(raw);
    try {
      const parsed = JSON.parse(raw);
      setData(parsed);
      setParseError(null);
    } catch (e: any) {
      setParseError(e?.message || "JSON 解析失败");
    }
  }, []);

  const syncTextFromData = useCallback((nextData: JsonValue) => {
    setData(nextData);
    setText(JSON.stringify(nextData, null, 2));
    setParseError(null);
  }, []);

  const formatted = useMemo(() => {
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return text;
    }
  }, [text]);

  if (!open) return null;

  const handleSave = () => {
    try {
      onSave(JSON.parse(text));
      onClose();
      // 保存后立即触发节点运行，将编辑结果写回文件
      onRun?.();
    } catch {
      setParseError("JSON 内容无效，无法保存");
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm" onPointerDown={(e) => e.stopPropagation()}>
      <div className={cn(
        "w-[864px] max-w-[92vw] h-[720px] max-h-[85vh] flex flex-col rounded-2xl border border-border/60 bg-card text-card-foreground shadow-2xl",
        maximized && "w-[96vw] max-w-[96vw] h-[94vh] max-h-[94vh]"
      )}>
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
          <div className="flex items-center gap-2">
            <FileJson className="w-4 h-4 text-violet-500" />
            <span className="text-sm font-bold">JSON 可视化编辑</span>
            {parseError ? (
              <span className="text-[11px] text-red-500">格式错误</span>
            ) : (
              <span className="text-[11px] text-emerald-500">格式正确</span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setMaximized((p) => !p)}
              className="p-1.5 rounded-md text-muted-foreground/70 hover:text-foreground hover:bg-foreground/10"
              title={maximized ? "还原窗口" : "最大化"}
            >
              {maximized ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-muted-foreground/70 hover:text-foreground hover:bg-foreground/10"
              title="关闭"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 flex flex-col min-h-0">
          {/* 原始文本编辑区 */}
          <div className="px-4 pt-3">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] font-medium text-muted-foreground">原始 JSON 文本</span>
              <button
                type="button"
                onClick={() => setText(formatted)}
                className="text-[11px] px-2 py-0.5 rounded border border-border/50 text-muted-foreground hover:text-primary hover:border-primary/40"
              >
                格式化
              </button>
            </div>
            <textarea
              value={text}
              onChange={(e) => handleTextChange(e.target.value)}
              rows={4}
              spellCheck={false}
              className="w-full text-xs font-mono px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none resize-none"
              onPointerDown={(e) => e.stopPropagation()}
            />
            {parseError && <div className="text-[11px] text-red-500 mt-0.5">{parseError}</div>}
          </div>

          {/* 结构化树视图 */}
          <div className="flex-1 px-4 py-3 min-h-0 flex flex-col">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] font-medium text-muted-foreground">结构化视图（可折叠/编辑值/增删成员）</span>
              <button
                type="button"
                onClick={() => { try { syncTextFromData(JSON.parse(text)); } catch { /* ignore */ } }}
                className="text-[11px] px-2 py-0.5 rounded border border-border/50 text-muted-foreground hover:text-primary hover:border-primary/40"
              >
                同步结构到文本
              </button>
            </div>
            <div className="flex-1 overflow-auto rounded-md border border-border/40 bg-background p-2 min-h-0">
              {parseError ? (
                <div className="text-xs text-muted-foreground py-2">请先修正 JSON 文本格式，结构化视图将自动更新</div>
              ) : (
                <JsonTreeNode
                  nodeKey="root"
                  value={data}
                  depth={0}
                  onUpdate={syncTextFromData}
                  onRemove={() => syncTextFromData({})}
                />
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-border/50">
          <span className="text-[11px] text-muted-foreground pr-3 leading-snug">
            默认不修改输入，保存后输出编辑结果；勾选「另存副本」输出带随机后缀的副本，否则覆盖原文件。本节点需人工编辑，可与「运行等待」节点配合使用。
          </span>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-xs rounded-md border border-border/50 text-muted-foreground hover:text-foreground"
            >
              取消
            </button>
            <button
              onClick={handleSave}
              className="px-3 py-1.5 text-xs rounded-md bg-primary text-primary-foreground hover:opacity-90"
            >
              保存到节点
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

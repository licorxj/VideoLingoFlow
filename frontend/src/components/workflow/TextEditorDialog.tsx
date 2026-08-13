import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { FileText, Maximize2, Minimize2, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  initialText?: string;
  onClose: () => void;
  onSave: (text: string) => void;
}

/** 构造正则（带 g 标志）；非法时返回 null */
function buildRegex(pattern: string): RegExp | null {
  try {
    return new RegExp(pattern, "g");
  } catch {
    return null;
  }
}

export default function TextEditorDialog({ open, initialText, onClose, onSave }: Props) {
  const [text, setText] = useState("");
  const [findText, setFindText] = useState("");
  const [replaceText, setReplaceText] = useState("");
  const [useRegex, setUseRegex] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    if (!open) return;
    setText(initialText === undefined ? "" : String(initialText));
    setFindText("");
    setReplaceText("");
    setUseRegex(false);
    setError(null);
    setFlash(null);
  }, [open, initialText]);

  // 正则合法性校验（避免在渲染期间 setState）
  useEffect(() => {
    if (useRegex && findText) {
      const re = buildRegex(findText);
      setError(re ? null : "正则表达式无效");
    } else {
      setError(null);
    }
  }, [findText, useRegex]);

  // 查找匹配数量
  const matchCount = useMemo(() => {
    if (!findText) return 0;
    if (useRegex) {
      const re = buildRegex(findText);
      if (!re) return 0;
      return (text.match(re) || []).length;
    }
    return text.split(findText).length - 1;
  }, [text, findText, useRegex]);

  // 替换（正则或普通文本），并返回是否成功
  const doReplace = useCallback((replacement: string) => {
    if (!findText) return;
    try {
      let next: string;
      if (useRegex) {
        const re = buildRegex(findText);
        if (!re) {
          setError("正则表达式无效");
          return;
        }
        next = text.replace(re, replacement);
      } else {
        next = text.split(findText).join(replacement);
      }
      setText(next);
      setFlash(`已替换 ${text.split(findText).length - 1} 处`);
    } catch (e: any) {
      setError(e?.message || "替换失败");
    }
  }, [text, findText, useRegex]);

  // 查找删除：删除所有匹配
  const doDelete = useCallback(() => {
    doReplace("");
    setFlash(`已删除 ${matchCount} 处匹配`);
  }, [doReplace, matchCount]);

  // 查找替换：替换所有匹配
  const doReplaceAll = useCallback(() => {
    doReplace(replaceText);
    setFlash(`已替换 ${matchCount} 处匹配`);
  }, [doReplace, replaceText, matchCount]);

  if (!open) return null;

  const inputCls = "w-full text-xs px-2 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none";

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm" onPointerDown={(e) => e.stopPropagation()}>
      <div className={cn(
        "w-[912px] max-w-[92vw] h-[768px] max-h-[85vh] flex flex-col rounded-2xl border border-border/60 bg-card text-card-foreground shadow-2xl",
        maximized && "w-[96vw] max-w-[96vw] h-[94vh] max-h-[94vh]"
      )}>
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-violet-500" />
            <span className="text-sm font-bold">文本编辑</span>
            {flash && <span className="text-[11px] text-emerald-500">{flash}</span>}
            {error && <span className="text-[11px] text-red-500">{error}</span>}
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
        <div className="flex-1 flex flex-col min-h-0 px-4 py-3 gap-3">
          {/* 查找 / 替换 工具栏 */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 flex-1">
                <Search className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
                <input
                  value={findText}
                  onChange={(e) => setFindText(e.target.value)}
                  placeholder="查找内容"
                  className={inputCls}
                  onPointerDown={(e) => e.stopPropagation()}
                />
              </div>
              <span className="text-[11px] text-muted-foreground flex-shrink-0 w-16 text-right">共 {matchCount} 处</span>
              <label className="flex items-center gap-1 text-[11px] text-muted-foreground flex-shrink-0 cursor-pointer">
                <input
                  type="checkbox"
                  checked={useRegex}
                  onChange={(e) => setUseRegex(e.target.checked)}
                  className="accent-primary"
                  onPointerDown={(e) => e.stopPropagation()}
                />
                正则表达式
              </label>
            </div>
            <div className="flex items-center gap-2">
              <input
                value={replaceText}
                onChange={(e) => setReplaceText(e.target.value)}
                placeholder="替换为（正则模式下可用 $1 引用捕获组）"
                className={inputCls}
                onPointerDown={(e) => e.stopPropagation()}
              />
              <button
                type="button"
                onClick={doReplaceAll}
                disabled={!findText || matchCount === 0}
                className="flex-shrink-0 px-3 py-1.5 text-xs font-medium rounded-md bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 disabled:opacity-40 disabled:cursor-not-allowed"
                title="查找替换（全部匹配）"
              >
                查找替换
              </button>
              <button
                type="button"
                onClick={doDelete}
                disabled={!findText || matchCount === 0}
                className="flex-shrink-0 px-3 py-1.5 text-xs font-medium rounded-md bg-red-500/10 text-red-600 border border-red-500/30 hover:bg-red-500/20 disabled:opacity-40 disabled:cursor-not-allowed"
                title="删除全部匹配"
              >
                查找删除
              </button>
            </div>
            {error && <div className="text-[11px] text-red-500">{error}</div>}
          </div>

          {/* 文本编辑区 */}
          <div className="flex-1 flex flex-col min-h-0">
            <span className="text-[11px] font-medium text-muted-foreground mb-1">文本内容（可自由编辑）</span>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              spellCheck={false}
              className="flex-1 w-full min-h-0 text-xs font-mono px-2.5 py-2 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none resize-none"
              onPointerDown={(e) => e.stopPropagation()}
              placeholder="在此输入或编辑文本内容"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-border/50">
          <span className="text-[11px] text-muted-foreground pr-3 leading-snug">
            查找删除/查找替换/正则表达式查找替换（正则模式可用 $1 引用捕获组）；默认不修改输入，保存后输出编辑结果；勾选「另存副本」输出带随机后缀的副本，否则覆盖原文件。需人工编辑，可与「运行等待」节点配合。
          </span>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-xs rounded-md border border-border/50 text-muted-foreground hover:text-foreground"
            >
              取消
            </button>
            <button
              onClick={() => { onSave(text); onClose(); }}
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

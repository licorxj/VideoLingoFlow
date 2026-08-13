import { cn } from "@/lib/utils";
import { Play, RotateCcw, FilePlus2, ArrowRight, X } from "lucide-react";

export type ExecutionMode = "resume" | "restart" | "new";

interface Props {
  isOpen: boolean;
  onConfirm: (mode: ExecutionMode) => void;
  onCancel: () => void;
  hasCompletedSteps?: boolean;
  isBatchTask?: boolean;
}

export default function ExecutionModeModal({ isOpen, onConfirm, onCancel, hasCompletedSteps, isBatchTask }: Props) {
  if (!isOpen) return null;

  const modes = [
    {
      id: "resume" as ExecutionMode,
      icon: ArrowRight,
      title: "断点续执行",
      desc: "跳过已完成的节点，从上次中断的节点继续执行",
      color: "text-blue-500",
      bg: "hover:border-blue-500/40 hover:bg-blue-500/5",
      disabled: !hasCompletedSteps,
      disabledHint: "没有已完成的节点",
    },
    {
      id: "restart" as ExecutionMode,
      icon: RotateCcw,
      title: "从头执行",
      desc: "清空所有输出产物，从第一个节点重新开始执行",
      color: "text-amber-500",
      bg: "hover:border-amber-500/40 hover:bg-amber-500/5",
    },
    {
      id: "new" as ExecutionMode,
      icon: FilePlus2,
      title: "新建任务执行",
      desc: "创建全新任务独立执行当前工作流",
      color: "text-emerald-500",
      bg: "hover:border-emerald-500/40 hover:bg-emerald-500/5",
      disabled: isBatchTask,
      disabledHint: isBatchTask ? "批量任务不支持新建任务" : undefined,
    },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in" onClick={onCancel}>
      <div className="bg-background border border-border/60 rounded-2xl shadow-2xl w-[min(480px,90vw)] animate-scale-in" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 pt-5 pb-2">
          <div>
            <h3 className="text-lg font-bold">选择执行模式</h3>
            <p className="text-xs text-muted-foreground mt-1">请选择如何执行当前工作流</p>
          </div>
          <button onClick={onCancel} className="p-1.5 rounded-lg hover:bg-secondary transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-2.5">
          {modes.map((mode) => {
            const Icon = mode.icon;
            return (
              <button
                key={mode.id}
                onClick={() => !mode.disabled && onConfirm(mode.id)}
                disabled={mode.disabled}
                className={cn(
                  "w-full flex items-start gap-3.5 p-4 rounded-xl border border-border/40 text-left transition-all duration-200",
                  mode.disabled
                    ? "opacity-40 cursor-not-allowed"
                    : cn("cursor-pointer", mode.bg)
                )}
              >
                <div className={cn("mt-0.5 p-2 rounded-lg bg-muted/50", mode.color)}>
                  <Icon className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">{mode.title}</span>
                    {mode.disabled && mode.disabledHint && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">{mode.disabledHint}</span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{mode.desc}</p>
                </div>
                {!mode.disabled && (
                  <Play className="w-3.5 h-3.5 mt-1 text-muted-foreground/40 flex-shrink-0" />
                )}
              </button>
            );
          })}
        </div>

        <div className="px-6 pb-5 flex justify-end">
          <button onClick={onCancel} className="px-4 py-2 text-sm font-medium border border-border/60 rounded-xl hover:bg-secondary/70 transition-all active:scale-[0.97]">取消</button>
        </div>
      </div>
    </div>
  );
}

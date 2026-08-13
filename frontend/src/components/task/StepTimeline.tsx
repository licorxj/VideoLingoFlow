import { cn } from "@/lib/utils";
import {
  CheckCircle2,
  Circle,
  Loader2,
  XCircle,
} from "lucide-react";

const statusConfig: Record<
  string,
  { icon: any; color: string; bg: string; label: string }
> = {
  pending: {
    icon: Circle,
    color: "text-muted-foreground/40",
    bg: "bg-transparent",
    label: "待执行",
  },
  running: {
    icon: Loader2,
    color: "text-blue-500",
    bg: "bg-blue-500/10",
    label: "执行中",
  },
  completed: {
    icon: CheckCircle2,
    color: "text-emerald-500",
    bg: "bg-emerald-500/10",
    label: "已完成",
  },
  failed: {
    icon: XCircle,
    color: "text-red-500",
    bg: "bg-red-500/10",
    label: "失败",
  },
};

interface StepTimelineProps {
  steps: Record<string, any>;
  onStepClick?: (stepId: string) => void;
}

export default function StepTimeline({
  steps,
  onStepClick,
}: StepTimelineProps) {
  const entries = Object.entries(steps);

  return (
    <div className="relative">
      <div className="absolute left-[15px] top-3 bottom-3 w-px bg-border/40" />

      <div className="space-y-1">
        {entries.map(([stepId, info]: [string, any], index) => {
          const status = info.status || "pending";
          const cfg = statusConfig[status] || statusConfig.pending;
          const Icon = cfg.icon;

          return (
            <div
              key={stepId}
              onClick={() => onStepClick?.(stepId)}
              className={cn(
                "relative flex items-start gap-3 p-3 rounded-xl transition-all duration-200 group",
                onStepClick && "cursor-pointer hover:bg-accent/40"
              )}
              style={{
                animationDelay: `${index * 60}ms`,
              }}
            >
              <div
                className={cn(
                  "relative z-10 w-[30px] h-[30px] rounded-lg flex items-center justify-center flex-shrink-0 transition-colors duration-200",
                  cfg.bg
                )}
              >
                <Icon
                  className={cn(
                    "w-4 h-4",
                    cfg.color,
                    status === "running" && "animate-spin"
                  )}
                  strokeWidth={2}
                />
              </div>

              <div className="flex-1 min-w-0 pt-0.5">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium group-hover:text-foreground transition-colors">
                    {info.name || stepId}
                  </span>
                  <span
                    className={cn(
                      "text-[11px] font-medium px-2 py-0.5 rounded-md",
                      cfg.bg,
                      cfg.color
                    )}
                  >
                    {cfg.label}
                  </span>
                </div>

                {status === "running" && info.progress != null && (
                  <div className="mt-2.5">
                    <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-primary to-primary/70 rounded-full transition-all duration-500 ease-out"
                        style={{ width: `${info.progress}%` }}
                      />
                    </div>
                    {info.message && (
                      <p className="text-xs text-muted-foreground mt-1.5">
                        {info.message}
                      </p>
                    )}
                  </div>
                )}

                {status === "failed" && info.message && (
                  <p className="text-xs text-red-500/80 mt-1.5">
                    {info.message}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

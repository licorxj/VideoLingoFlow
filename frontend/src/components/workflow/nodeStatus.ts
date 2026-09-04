import { AlertTriangle, CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";

/** 画布节点状态样式表（组合节点卡片、循环容器卡片、普通节点卡片共用）。 */
export const STATUS_CONFIG: Record<
  string,
  { icon: any; color: string; bg: string; border: string; glow: string; label: string; badgeBg: string; badgeText: string }
> = {
  pending: {
    icon: Clock, color: "text-muted-foreground", bg: "bg-muted/30",
    border: "", glow: "",
    label: "等待中",
    badgeBg: "bg-muted/60", badgeText: "text-muted-foreground",
  },
  running: {
    icon: Loader2, color: "text-blue-500", bg: "bg-blue-500/5",
    border: "border-blue-400 shadow-[0_0_12px_rgba(59,130,246,0.25)]",
    glow: "ring-2 ring-blue-400/30",
    label: "执行中",
    badgeBg: "bg-blue-500/15", badgeText: "text-blue-600",
  },
  waiting: {
    icon: Clock, color: "text-amber-600", bg: "bg-amber-500/5",
    border: "border-amber-400 shadow-[0_0_12px_rgba(245,158,11,0.2)]",
    glow: "",
    label: "等待剪辑",
    badgeBg: "bg-amber-500/15", badgeText: "text-amber-700",
  },
  completed: {
    icon: CheckCircle2, color: "text-emerald-500", bg: "bg-emerald-500/5",
    border: "!border-[4px] border-emerald-400 shadow-[0_0_14px_rgba(16,185,129,0.3)]",
    glow: "",
    label: "已完成",
    badgeBg: "bg-emerald-500/15", badgeText: "text-emerald-600",
  },
  failed: {
    icon: XCircle, color: "text-red-500", bg: "bg-red-500/5",
    border: "border-red-400 shadow-[0_0_12px_rgba(239,68,68,0.25)]",
    glow: "",
    label: "失败",
    badgeBg: "bg-red-500/15", badgeText: "text-red-600",
  },
  skipped: {
    icon: Clock, color: "text-yellow-500", bg: "bg-yellow-500/5",
    border: "border-yellow-400",
    glow: "",
    label: "已跳过",
    badgeBg: "bg-yellow-500/15", badgeText: "text-yellow-600",
  },
  cancelled: {
    icon: AlertTriangle, color: "text-orange-500", bg: "bg-orange-500/5",
    border: "border-orange-400 shadow-[0_0_10px_rgba(249,115,22,0.2)]",
    glow: "",
    label: "已取消",
    badgeBg: "bg-orange-500/15", badgeText: "text-orange-600",
  },
};

/** 节点头部顶栏：只有在该元素上按下鼠标才允许拖动节点，避免正文内框选/拖动误触移动节点 */
export const NODE_DRAG_HANDLE_CLASS = "wf-node-drag-handle";

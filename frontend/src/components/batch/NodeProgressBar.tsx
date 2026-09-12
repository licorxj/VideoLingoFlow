import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

interface NodeStatus {
  nodeType?: string;
  label?: string;
  status?: string;
  progress?: number;
  message?: string;
  error?: string;
}

interface Props {
  nodes: Record<string, NodeStatus>;
  workflowNodes: { id: string; nodeType: string; label: string }[];
}

/** 进度条分段配色 */
const BAR_COLORS: Record<string, string> = {
  completed: "bg-emerald-500",
  running: "bg-blue-500 animate-pulse",
  failed: "bg-red-500",
  cancelled: "bg-amber-500",
  pending: "bg-muted-foreground/20 dark:bg-muted-foreground/15",
};

/** 状态展示元数据：中文名 + 配色（点 / 文本 / 徽标 / 行底色） */
const STATUS_META: Record<
  string,
  { label: string; dot: string; text: string; chip: string; row: string }
> = {
  completed: {
    label: "已完成",
    dot: "bg-emerald-500",
    text: "text-emerald-600 dark:text-emerald-400",
    chip: "border-emerald-500/25 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    row: "",
  },
  running: {
    label: "执行中",
    dot: "bg-blue-500 animate-pulse",
    text: "text-blue-600 dark:text-blue-400",
    chip: "border-blue-500/25 bg-blue-500/10 text-blue-600 dark:text-blue-400",
    row: "bg-blue-500/5",
  },
  failed: {
    label: "失败",
    dot: "bg-red-500",
    text: "text-red-600 dark:text-red-400",
    chip: "border-red-500/25 bg-red-500/10 text-red-600 dark:text-red-400",
    row: "bg-red-500/5",
  },
  cancelled: {
    label: "已中止",
    dot: "bg-amber-500",
    text: "text-amber-600 dark:text-amber-400",
    chip: "border-amber-500/25 bg-amber-500/10 text-amber-600 dark:text-amber-400",
    row: "",
  },
  pending: {
    label: "等待中",
    dot: "bg-muted-foreground/40",
    text: "text-muted-foreground",
    chip: "border-border bg-muted text-muted-foreground",
    row: "",
  },
};

function statusMeta(status?: string) {
  return STATUS_META[status || "pending"] || STATUS_META.pending;
}

/** 浮层相对光标的偏移与视口留白 */
const CURSOR_OFFSET = 16;
const VIEWPORT_PADDING = 8;
/** 离开进度条后允许移动到浮层上的宽限时间 */
const HIDE_DELAY = 160;
/** 悬停多久才弹出浮层，避免快速划过任务行时不断闪现 */
const SHOW_DELAY = 1000;

export default function NodeProgressBar({ nodes, workflowNodes }: Props) {
  const [visible, setVisible] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [scrollable, setScrollable] = useState(false);
  const layerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLDivElement | null>(null);
  const mouseRef = useRef({ x: 0, y: 0 });
  const rafRef = useRef<number | null>(null);
  const hideTimerRef = useRef<number | null>(null);
  const showTimerRef = useRef<number | null>(null);

  const total = workflowNodes.length;

  const cancelHide = useCallback(() => {
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }, []);

  const cancelShow = useCallback(() => {
    if (showTimerRef.current !== null) {
      window.clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
  }, []);

  /** 悬停满 SHOW_DELAY 才显示；重复进入只保留最后一次计时。 */
  const scheduleShow = useCallback(() => {
    cancelShow();
    showTimerRef.current = window.setTimeout(() => {
      showTimerRef.current = null;
      setVisible(true);
    }, SHOW_DELAY);
  }, [cancelShow]);

  const scheduleHide = useCallback(() => {
    cancelHide();
    hideTimerRef.current = window.setTimeout(() => {
      hideTimerRef.current = null;
      setVisible(false);
      setPinned(false);
      setScrollable(false);
    }, HIDE_DELAY);
  }, [cancelHide]);

  /** 把浮层移动到光标附近；靠近视口右/下边缘时自动翻转到左侧/上方。 */
  const positionLayer = useCallback(() => {
    const el = layerRef.current;
    if (!el) return;
    let { x, y } = mouseRef.current;
    if (!x && !y) {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (rect) {
        x = rect.left + rect.width / 2;
        y = rect.top;
      }
    }
    const width = el.offsetWidth;
    const height = el.offsetHeight;
    let left = x + CURSOR_OFFSET;
    let top = y + CURSOR_OFFSET;
    if (left + width > window.innerWidth - VIEWPORT_PADDING) {
      left = Math.max(VIEWPORT_PADDING, x - CURSOR_OFFSET - width);
    }
    if (top + height > window.innerHeight - VIEWPORT_PADDING) {
      top = Math.max(VIEWPORT_PADDING, y - CURSOR_OFFSET - height);
    }
    el.style.transform = `translate3d(${Math.round(left)}px, ${Math.round(top)}px, 0)`;
  }, []);

  /** 用 rAF 节流光标移动，避免高频布局抖动。 */
  const schedulePosition = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = window.requestAnimationFrame(() => {
      rafRef.current = null;
      positionLayer();
    });
  }, [positionLayer]);

  useLayoutEffect(() => {
    if (!visible) return;
    positionLayer();
    const el = layerRef.current;
    if (el) setScrollable(el.scrollHeight - el.clientHeight > 1);
  }, [visible, positionLayer]);

  useEffect(
    () => () => {
      if (rafRef.current !== null) window.cancelAnimationFrame(rafRef.current);
      if (hideTimerRef.current !== null) window.clearTimeout(hideTimerRef.current);
      if (showTimerRef.current !== null) window.clearTimeout(showTimerRef.current);
    },
    []
  );

  // ── 进度条（触发区）──
  const handleTriggerEnter = (event: ReactMouseEvent<HTMLDivElement>) => {
    cancelHide();
    mouseRef.current = { x: event.clientX, y: event.clientY };
    setPinned(false);
    // 已经显示时立刻恢复跟随，不再走延迟
    if (visible) return;
    scheduleShow();
  };

  const handleTriggerMove = (event: ReactMouseEvent<HTMLDivElement>) => {
    mouseRef.current = { x: event.clientX, y: event.clientY };
    // 已固定（鼠标在浮层内）时不再跟随，便于在浮层里滚动浏览
    if (visible && !pinned) schedulePosition();
  };

  // ── 浮层 ──
  const handleLayerEnter = () => {
    cancelHide();
    setPinned(true);
    const el = layerRef.current;
    if (el) setScrollable(el.scrollHeight - el.clientHeight > 1);
  };

  /** 鼠标在浮层内向右移动 → 列表按比例向下滚动（左端=顶部，右端=底部）。 */
  const handleLayerMove = (event: ReactMouseEvent<HTMLDivElement>) => {
    cancelHide();
    const el = layerRef.current;
    if (!el) return;
    const maxScroll = el.scrollHeight - el.clientHeight;
    if (maxScroll <= 1) {
      setScrollable(false);
      return;
    }
    setScrollable(true);
    const rect = el.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / Math.max(1, rect.width)));
    el.scrollTop = ratio * maxScroll;
  };

  if (!total) return null;

  const statuses = workflowNodes.map((node) => nodes[node.id]?.status || "pending");
  const completedCount = statuses.filter((status) => status === "completed").length;
  const runningCount = statuses.filter((status) => status === "running").length;
  const failedCount = statuses.filter((status) => status === "failed").length;

  return (
    <>
      <div
        ref={triggerRef}
        onMouseEnter={handleTriggerEnter}
        onMouseMove={handleTriggerMove}
        onMouseLeave={() => {
          cancelShow();
          scheduleHide();
        }}
        className="flex w-full -my-1.5 cursor-default items-center gap-0.5 py-1.5"
      >
        {workflowNodes.map((wn) => {
          const status = nodes[wn.id]?.status || "pending";
          return (
            <div
              key={wn.id}
              className={cn(
                "h-[8px] min-w-[4px] flex-1 rounded-sm transition-colors duration-300",
                BAR_COLORS[status] || BAR_COLORS.pending
              )}
              style={{ flex: `1 1 ${100 / total}%` }}
            />
          );
        })}
      </div>
      {visible &&
        createPortal(
          <div
            ref={layerRef}
            onMouseEnter={handleLayerEnter}
            onMouseMove={handleLayerMove}
            onMouseLeave={scheduleHide}
            style={{ transform: "translate3d(-9999px, -9999px, 0)" }}
            className={cn(
              "fixed left-0 top-0 z-[100]",
              "w-[min(460px,90vw)] max-h-[calc(100vh-16px)] overflow-y-auto overscroll-contain",
              "rounded-2xl border border-cyan-400/30 bg-popover/75 text-popover-foreground",
              "backdrop-blur-xl backdrop-saturate-150",
              "ring-1 ring-cyan-400/20",
              "shadow-[0_0_0_1px_rgba(34,211,238,0.16),0_0_28px_-2px_rgba(34,211,238,0.35),0_24px_60px_-20px_rgba(2,6,23,0.6)]"
            )}
          >
            <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-cyan-400/20 bg-popover/80 px-3 py-2 backdrop-blur-xl">
              <span className="text-xs font-semibold">节点执行状态</span>
              <span className="flex items-center gap-2.5 text-[11px] text-muted-foreground">
                {scrollable && (
                  <span className="shrink-0 rounded-md border border-cyan-400/30 bg-cyan-400/10 px-1.5 py-px text-[10px] font-medium text-cyan-600 dark:text-cyan-300">
                    右移滚动
                  </span>
                )}
                <span className="inline-flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  {completedCount}/{total} 完成
                </span>
                {runningCount > 0 && (
                  <span className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400">
                    <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
                    {runningCount} 执行中
                  </span>
                )}
                {failedCount > 0 && (
                  <span className="inline-flex items-center gap-1 text-red-600 dark:text-red-400">
                    <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
                    {failedCount} 失败
                  </span>
                )}
              </span>
            </div>
            <ul className="p-1.5">
              {workflowNodes.map((wn, index) => {
                const ns = nodes[wn.id];
                const meta = statusMeta(ns?.status);
                const detail = ns?.error || ns?.message || "";
                const isError = Boolean(ns?.error);
                const percent =
                  typeof ns?.progress === "number" && ns.status === "running"
                    ? Math.max(0, Math.min(100, Math.round(ns.progress)))
                    : null;
                return (
                  <li
                    key={wn.id}
                    className={cn("flex items-start gap-2 rounded-lg px-1.5 py-1.5", meta.row)}
                  >
                    <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", meta.dot)} />
                    <span className="w-4 shrink-0 pt-px text-right text-[10px] tabular-nums text-muted-foreground/70">
                      {index + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className="truncate text-xs font-medium text-foreground"
                          title={wn.label || wn.nodeType}
                        >
                          {wn.label || wn.nodeType}
                        </span>
                        <span
                          className={cn(
                            "shrink-0 rounded-md border px-1.5 py-px text-[10px] font-semibold",
                            meta.chip
                          )}
                        >
                          {meta.label}
                        </span>
                        {percent !== null && (
                          <span className={cn("shrink-0 text-[10px] font-semibold tabular-nums", meta.text)}>
                            {percent}%
                          </span>
                        )}
                      </div>
                      {detail && (
                        <div
                          className={cn(
                            "mt-0.5 line-clamp-2 break-all text-[11px]",
                            isError ? "text-red-500" : "text-muted-foreground"
                          )}
                          title={detail}
                        >
                          {isError ? "错误：" : ""}
                          {detail}
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>,
          document.body
        )}
    </>
  );
}

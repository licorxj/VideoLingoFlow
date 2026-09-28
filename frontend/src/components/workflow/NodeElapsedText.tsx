import { cn } from "@/lib/utils";

/** 节点执行耗时文案：保留一位小数、单位秒（画布节点卡片完成状态下方展示）。 */
export function formatNodeElapsed(seconds?: number | null): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "";
  return `${seconds.toFixed(1)} 秒`;
}

/** 节点卡片状态徽标下方的耗时文字；无耗时数据时不渲染（不影响卡片布局）。 */
export function NodeElapsedText({ seconds, className }: { seconds?: number | null; className?: string }) {
  const text = formatNodeElapsed(seconds);
  if (!text) return null;
  return (
    <span
      className={cn(
        "whitespace-nowrap text-[10px] font-medium leading-none tabular-nums text-emerald-600/80 dark:text-emerald-400/80",
        className,
      )}
      title="节点执行耗时"
    >
      {text}
    </span>
  );
}

export default NodeElapsedText;

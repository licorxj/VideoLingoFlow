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

const STATUS_COLORS: Record<string, string> = {
  completed: "bg-emerald-500",
  running: "bg-blue-500 animate-pulse",
  failed: "bg-red-500",
  cancelled: "bg-amber-500",
  pending: "bg-muted-foreground/20 dark:bg-muted-foreground/15",
};

export default function NodeProgressBar({ nodes, workflowNodes }: Props) {
  const total = workflowNodes.length;

  return (
    <div className="flex items-center gap-0.5 w-full" title={workflowNodes.map((n) => {
      const ns = nodes[n.id];
      return `${n.label || n.nodeType}: ${ns?.status || "pending"}`;
    }).join("\n")}>
      {workflowNodes.map((wn) => {
        const ns = nodes[wn.id];
        const status = ns?.status || "pending";
        return (
          <div
            key={wn.id}
            className={cn(
              "flex-1 h-[8px] rounded-sm transition-colors duration-300 min-w-[4px]",
              STATUS_COLORS[status] || STATUS_COLORS.pending
            )}
            style={{ flex: `1 1 ${100 / total}%` }}
          />
        );
      })}
    </div>
  );
}
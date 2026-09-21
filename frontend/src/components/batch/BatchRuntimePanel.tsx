import { useState } from "react";
import { Activity, ChevronDown, ChevronUp, Cpu, Eraser, Gauge, HardDrive, Layers3, ServerCog } from "lucide-react";
import { batchApi, RuntimeStatus } from "@/api/batch";
import { useAlert } from "@/components/ui/AlertProvider";
import { cn } from "@/lib/utils";

interface Props {
  runtime: RuntimeStatus | null;
  loading?: boolean;
  onRefresh?: () => void;
}

function StatCard({
  icon: Icon,
  label,
  value,
  hint,
  accent = "text-primary",
}: {
  icon: any;
  label: string;
  value: string | number;
  hint?: string;
  accent?: string;
}) {
  return (
    <div className="rounded-xl border border-border/60 bg-card/50 px-3 py-2.5">
      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
        <Icon className={cn("h-3.5 w-3.5", accent)} />
        <span>{label}</span>
      </div>
      <div className="mt-1 text-lg font-semibold leading-none">{value}</div>
      {hint ? <div className="mt-1 text-[11px] text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

export default function BatchRuntimePanel({ runtime, loading = false, onRefresh }: Props) {
  const [expanded, setExpanded] = useState(true);
  const [releasing, setReleasing] = useState(false);
  const { alert: showAlert, confirm: showConfirm } = useAlert();
  const batch = runtime?.batch;
  const control = runtime?.control_plane;
  const gpu = runtime?.gpu_service;
  const tokens = control?.resources?.tokens;

  const tokenHoldersSummary = Object.entries(tokens || {})
    .filter(([, info]) => (info?.in_use ?? 0) > 0 && (info?.holders?.length ?? 0) > 0)
    .map(([key, info]) => `${key}=${info.holders.slice(0, 2).join("、")}`)
    .join(" · ");

  const handleReleaseTokens = async () => {
    if (
      !(await showConfirm(
        "释放资源令牌只清理残留占用。若确有资源型节点正在执行，可能造成短时并发超限（显存/CPU 压力上升）。确定继续？"
      ))
    ) {
      return;
    }
    setReleasing(true);
    try {
      const res: any = await batchApi.releaseResourceTokens();
      const released = Object.keys(res?.released || {}).join("、") || "全部";
      showAlert(`已释放资源令牌（${released}），等待中的节点可重新获取。`, "success");
      onRefresh?.();
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || e?.message || "释放失败");
    } finally {
      setReleasing(false);
    }
  };

  const workerCount = Object.keys(control?.workers?.stats || {}).length;
  const queueSummary = Object.entries(control?.queues || {})
    .map(([key, item]) => `${key}:${item.depth}`)
    .join(" / ");

  const gpuHint = gpu?.enabled
    ? gpu?.available
      ? `${gpu.vram?.name || "GPU"} · 空闲 ${gpu.vram?.free_gb ?? "-"}GB${gpu.vram_pressure ? " · 显存紧张，加速回收空闲 lane" : ""}`
      : "GPU 服务未就绪"
    : "GPU 服务未启用";

  return (
    <div className="rounded-2xl border border-border/60 bg-card/40 p-3.5">
      <div className={cn("flex items-center justify-between gap-2", expanded && "mb-3")}>
        <div className="flex min-w-0 items-center gap-2">
          <ServerCog className="h-4 w-4 shrink-0 text-primary" />
          <div className="min-w-0">
            <div className="text-sm font-semibold">系统运行态</div>
            <div className="text-[11px] text-muted-foreground">
              批次投递、Worker、资源容量与 GPU 服务实时状态
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border/60 bg-background/60 px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
          title={expanded ? "折叠系统运行态" : "展开系统运行态"}
          aria-expanded={expanded}
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {expanded ? "折叠" : "展开"}
        </button>
      </div>

      {expanded && !runtime && (
        <div className="mb-3 rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-700">
          {loading ? "正在获取系统运行态..." : "系统运行态暂未返回，请确认后端已重启并可访问 /api/control/runtime/status"}
        </div>
      )}
      {expanded && !!runtime?.control_plane?.error && (
        <div className="mb-3 rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-700">
          {runtime.control_plane.error}
        </div>
      )}

      <div className={cn("grid gap-2.5 md:grid-cols-2 xl:grid-cols-4", !expanded && "hidden")}>
        <StatCard
          icon={Layers3}
          label="批次队列任务数"
          value={batch?.inflight_tasks ?? "-"}
          hint={`含执行中+排队中；运行批次 ${batch?.running_batches ?? "-"} / 等待继续 ${batch?.paused_batches ?? "-"}`}
          accent="text-blue-500"
        />
        <StatCard
          icon={Activity}
          label="控制面任务状态"
          value={`${control?.tasks?.running ?? 0} 执行中 / ${control?.tasks?.queued ?? 0} 排队`}
          hint={`暂停 ${control?.tasks?.paused ?? 0} / 停止中 ${control?.tasks?.stopping ?? 0}`}
          accent="text-emerald-500"
        />
        <StatCard
          icon={Cpu}
          label="Worker 消费者"
          value={control?.workers?.available ? workerCount : "不可用"}
          hint={control?.workers?.available ? `已发现 ${workerCount} 个 worker` : "Celery inspect 不可达"}
          accent="text-violet-500"
        />
        <StatCard
          icon={HardDrive}
          label="GPU 服务"
          value={
            gpu?.enabled
              ? gpu?.available
                ? `${gpu.busy_lanes ?? 0}/${gpu.configured?.max_lanes ?? gpu.active_lanes ?? 0}`
                : "未就绪"
              : "未启用"
          }
          hint={gpuHint}
          accent="text-orange-500"
        />
      </div>

      <div className={cn("mt-3 grid gap-2.5 xl:grid-cols-[1.4fr_1fr]", !expanded && "hidden")}>
        <div className="rounded-xl border border-border/50 bg-background/40 px-3 py-2.5">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <Gauge className="h-3.5 w-3.5 text-sky-500" />
            <span>队列与投递配置</span>
          </div>
          <div className="mt-1 text-xs text-foreground/90">
            最大同时执行任务数（Worker 并发）：<span className="font-semibold">{control?.resources?.batch_max_inflight_tasks ?? "-"}</span>
            {"  "} 启动间隔：<span className="font-semibold">{control?.resources?.batch_task_start_interval ?? "-"}</span>s
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground break-all">
            {queueSummary || "暂无队列数据"}
          </div>
        </div>

        <div className="rounded-xl border border-border/50 bg-background/40 px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <Cpu className="h-3.5 w-3.5 text-rose-500" />
              <span>资源令牌占用（使用中/容量）</span>
            </div>
            <button
              type="button"
              onClick={handleReleaseTokens}
              disabled={releasing}
              className="inline-flex items-center gap-1 rounded-lg border border-border/60 bg-background/60 px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-rose-400/50 hover:text-rose-500 disabled:opacity-50"
              title="持有者进程被强杀后令牌可能残留，导致节点一直「等待 XX 资源」假死。点击清理残留占用。"
            >
              <Eraser className="h-3 w-3" />
              {releasing ? "释放中…" : "释放僵尸令牌"}
            </button>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-foreground/90">
            {Object.entries(control?.resources?.capacity || {}).map(([key, capacity]) => {
              const info = tokens?.[key];
              const used = info?.in_use ?? 0;
              const exhausted = (info?.available ?? capacity - used) === 0;
              return (
                <span
                  key={key}
                  className="inline-block"
                  title={
                    info?.holders?.length
                      ? `${key} 持有者：${info.holders.join("，")}`
                      : `${key} 当前无持有者`
                  }
                >
                  {key}:{" "}
                  <span className={cn("font-semibold", exhausted ? "text-rose-500" : "text-foreground")}>
                    {used}/{capacity}
                  </span>
                </span>
              );
            })}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground break-all">
            {tokenHoldersSummary
              ? `持有者：${tokenHoldersSummary}`
              : `当前无持有者 · GPU 主控：${control?.resources?.gpu_service_enabled ? "服务层" : "worker 资源令牌"}`}
          </div>
        </div>
      </div>
    </div>
  );
}

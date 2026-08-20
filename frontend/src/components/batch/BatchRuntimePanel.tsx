import { Activity, Cpu, Gauge, HardDrive, Layers3, ServerCog } from "lucide-react";
import { RuntimeStatus } from "@/api/batch";
import { cn } from "@/lib/utils";

interface Props {
  runtime: RuntimeStatus | null;
  loading?: boolean;
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

export default function BatchRuntimePanel({ runtime, loading = false }: Props) {
  const batch = runtime?.batch;
  const control = runtime?.control_plane;
  const gpu = runtime?.gpu_service;

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
      <div className="mb-3 flex items-center gap-2">
        <ServerCog className="h-4 w-4 text-primary" />
        <div>
          <div className="text-sm font-semibold">系统运行态</div>
          <div className="text-[11px] text-muted-foreground">
            批次投递、Worker、资源容量与 GPU 服务实时状态
          </div>
        </div>
      </div>

      {!runtime && (
        <div className="mb-3 rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-700">
          {loading ? "正在获取系统运行态..." : "系统运行态暂未返回，请确认后端已重启并可访问 /api/control/runtime/status"}
        </div>
      )}
      {!!runtime?.control_plane?.error && (
        <div className="mb-3 rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-700">
          {runtime.control_plane.error}
        </div>
      )}

      <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={Layers3}
          label="批次在途任务数"
          value={batch?.inflight_tasks ?? "-"}
          hint={`运行批次 ${batch?.running_batches ?? "-"} / 等待继续 ${batch?.paused_batches ?? "-"}`}
          accent="text-blue-500"
        />
        <StatCard
          icon={Activity}
          label="控制面任务状态"
          value={`${control?.tasks?.running ?? 0} 运行 / ${control?.tasks?.queued ?? 0} 排队`}
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

      <div className="mt-3 grid gap-2.5 xl:grid-cols-[1.4fr_1fr]">
        <div className="rounded-xl border border-border/50 bg-background/40 px-3 py-2.5">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <Gauge className="h-3.5 w-3.5 text-sky-500" />
            <span>队列与投递配置</span>
          </div>
          <div className="mt-1 text-xs text-foreground/90">
            最大同时在途任务数：<span className="font-semibold">{control?.resources?.batch_max_inflight_tasks ?? "-"}</span>
            {"  "} 启动间隔：<span className="font-semibold">{control?.resources?.batch_task_start_interval ?? "-"}</span>s
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground break-all">
            {queueSummary || "暂无队列数据"}
          </div>
        </div>

        <div className="rounded-xl border border-border/50 bg-background/40 px-3 py-2.5">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <Cpu className="h-3.5 w-3.5 text-rose-500" />
            <span>资源容量</span>
          </div>
          <div className="mt-1 text-[11px] text-foreground/90">
            {Object.entries(control?.resources?.capacity || {}).map(([key, value]) => (
              <span key={key} className="mr-3 inline-block">
                {key}: <span className="font-semibold">{value}</span>
              </span>
            ))}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">
            GPU 主控：{control?.resources?.gpu_service_enabled ? "服务层" : "worker 资源令牌"}
          </div>
        </div>
      </div>
    </div>
  );
}

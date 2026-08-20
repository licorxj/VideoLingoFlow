import { useState, useEffect, useCallback } from "react";
import { Layers, Plus, RefreshCw, Play, Inbox, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { batchApi, BatchDetail, RuntimeStatus } from "@/api/batch";
import CreateBatchDialog from "@/components/batch/CreateBatchDialog";
import BatchGroupCard from "@/components/batch/BatchGroupCard";
import BatchRuntimePanel from "@/components/batch/BatchRuntimePanel";
import { useAlert } from "@/components/ui/AlertProvider";
import { getSubscriptionError, isDeviceLimitError, isSubscriptionBlocked, getQuotaExhaustedMessage } from "@/api/subscription";
import { useSubscriptionStore } from "@/stores/subscriptionStore";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/shared/PageHeader";
import { PageBackground } from "@/components/shared/PageBackground";
import { EmptyState } from "@/components/shared/EmptyState";
import { LoadingState } from "@/components/shared/LoadingState";

function buildRuntimeFallback(batches: BatchDetail[], maxConcurrent: number, taskStartInterval: number): RuntimeStatus {
  const tasks = batches.flatMap((batch) => batch.tasks || []);
  const runningTasks = tasks.filter((task) => task.status === "running").length;
  const queuedTasks = tasks.filter((task) => task.status === "created").length;
  const pausedTasks = tasks.filter((task) => task.status === "paused" || task.status === "interrupted").length;
  const stoppingTasks = 0;
  const inflightTasks = tasks.filter((task) => task.status === "running" || task.status === "created").length;
  const runningBatches = batches.filter((batch) => batch.status === "running").length;
  const pausedBatches = batches.filter((batch) => batch.status === "paused" || batch.status === "interrupted").length;

  return {
    batch: {
      inflight_tasks: inflightTasks,
      running_batches: runningBatches,
      paused_batches: pausedBatches,
    },
    control_plane: {
      tasks: {
        running: runningTasks,
        queued: queuedTasks,
        paused: pausedTasks,
        stopping: stoppingTasks,
      },
      queues: {},
      workers: {
        available: false,
        stats: {},
        active: {},
        reserved: {},
      },
      resources: {
        capacity: {},
        gpu_service_enabled: false,
        batch_max_inflight_tasks: maxConcurrent,
        batch_task_start_interval: taskStartInterval,
      },
      error: "当前显示为批量页本地统计，后端运行态接口暂不可用",
    },
    gpu_service: {
      enabled: false,
      available: false,
    },
    system: {
      available: false,
      cpu_percent: null,
      ram_percent: null,
      gpu_percent: null,
      vram_percent: null,
    },
  };
}

export default function BatchWorkshop() {
  const { alert: showAlert, confirm: showConfirm } = useAlert();
  const [batches, setBatches] = useState<BatchDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [maxConcurrent, setMaxConcurrent] = useState(3);
  const [taskStartInterval, setTaskStartInterval] = useState(0);
  const [configLoading, setConfigLoading] = useState(false);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null);

  const loadBatches = useCallback(async () => {
    setLoading(true);
    try {
      const result = await batchApi.listPage();
      setBatches(result.batches);
    } catch {
      setBatches([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadConfig = useCallback(async () => {
    try {
      const cfg = await batchApi.getConfig();
      setMaxConcurrent(cfg.max_concurrent_tasks || 3);
      setTaskStartInterval(cfg.task_start_interval || 0);
    } catch {}
  }, []);

  const loadRuntimeStatus = useCallback(async () => {
    try {
      const result = await batchApi.getRuntimeStatus();
      setRuntimeStatus(result);
    } catch {
      setRuntimeStatus(null);
    }
  }, []);

  useEffect(() => {
    loadBatches();
    loadConfig();
    loadRuntimeStatus();
  }, [loadBatches, loadConfig, loadRuntimeStatus]);

  // Auto-refresh every 5 seconds when there are running tasks
  useEffect(() => {
    const hasRunning = batches.some((b) => b.status === "running");
    const hasInterrupted = batches.some((b) => b.status === "interrupted");
    if (!hasRunning && !hasInterrupted) return;
    const timer = setInterval(() => {
      loadBatches();
      loadRuntimeStatus();
    }, 5000);
    return () => clearInterval(timer);
  }, [batches, loadBatches, loadRuntimeStatus]);

  const handleUpdateConfig = async (val: number) => {
    setConfigLoading(true);
    try {
      await batchApi.updateConfig(val, taskStartInterval);
      setMaxConcurrent(val);
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || "更新配置失败");
    } finally {
      setConfigLoading(false);
    }
  };

  const handleUpdateInterval = async (val: number) => {
    setConfigLoading(true);
    try {
      await batchApi.updateConfig(maxConcurrent, val);
      setTaskStartInterval(val);
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || "更新配置失败");
    } finally {
      setConfigLoading(false);
    }
  };

  const handleStopAll = async () => {
    if (!(await showConfirm("确定要停止所有批次的全部任务吗？"))) return;
    setLoading(true);
    try {
      await batchApi.stopAll();
      await loadBatches();
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || "操作失败");
    } finally {
      setLoading(false);
    }
  };

  const handleSubscriptionError = (e: any) => {
    if (!isSubscriptionBlocked(e)) return false;
    if (isDeviceLimitError(e)) {
      showAlert(`${getSubscriptionError(e)}\n请前往“用户和订阅”页面查看当前已绑定设备数。`, "warning");
      return true;
    }
    const status = useSubscriptionStore.getState().status;
    showAlert(getQuotaExhaustedMessage(status), "warning");
    return true;
  };

  const handleOpenCreateDialog = async () => {
    const status = await useSubscriptionStore.getState().fetchStatus();
    if (status && !status.can_create_task) {
      showAlert(getQuotaExhaustedMessage(status), "warning");
      return;
    }
    setShowCreateDialog(true);
  };

  const handleResumeUnfinished = async () => {
    setLoading(true);
    try {
      const status = await useSubscriptionStore.getState().fetchStatus();
      if (status && !status.can_create_task) {
        showAlert(getQuotaExhaustedMessage(status), "warning");
        return;
      }
      await batchApi.resumeAllUnfinished();
      await loadBatches();
    } catch (e: any) {
      if (handleSubscriptionError(e)) return;
      showAlert(e?.response?.data?.detail || "操作失败");
    } finally {
      setLoading(false);
    }
  };

  const effectiveRuntimeStatus = runtimeStatus
    ? {
        ...buildRuntimeFallback(batches, maxConcurrent, taskStartInterval),
        ...runtimeStatus,
        batch: {
          ...buildRuntimeFallback(batches, maxConcurrent, taskStartInterval).batch,
          ...(runtimeStatus.batch || {}),
        },
        control_plane: {
          ...buildRuntimeFallback(batches, maxConcurrent, taskStartInterval).control_plane,
          ...(runtimeStatus.control_plane || {}),
          tasks: {
            ...buildRuntimeFallback(batches, maxConcurrent, taskStartInterval).control_plane.tasks,
            ...(runtimeStatus.control_plane?.tasks || {}),
          },
          resources: {
            ...buildRuntimeFallback(batches, maxConcurrent, taskStartInterval).control_plane.resources,
            ...(runtimeStatus.control_plane?.resources || {}),
          },
        },
      }
    : buildRuntimeFallback(batches, maxConcurrent, taskStartInterval);

  return (
    <PageBackground tone="batch" className="max-w-7xl mx-auto space-y-5 p-1">
      <PageHeader
        icon={Layers}
        title="批量工作台"
        detail="批量创建、投递和恢复视频处理任务"
        actions={
          <>
            <Button variant="destructive" size="sm" onClick={handleStopAll} disabled={loading}>
              <Square className="mr-1.5 h-4 w-4" />
              全部停止
            </Button>
            <Button variant="success-soft" size="sm" onClick={handleResumeUnfinished} disabled={loading}>
              <Play className="mr-1.5 h-4 w-4" />
              全局继续中断任务
            </Button>
            <Button size="sm" onClick={handleOpenCreateDialog}>
              <Plus className="mr-1.5 h-4 w-4" />
              新建批量任务
            </Button>
            <Button variant="outline" size="sm" onClick={() => { loadBatches(); loadRuntimeStatus(); }} disabled={loading}>
              <RefreshCw className={cn("mr-1.5 h-4 w-4", loading && "animate-spin")} />
              刷新
            </Button>
          </>
        }
      />

      {/* Toolbar: config (parallel / interval) */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border/60 bg-card p-3">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted/40">
          <span className="text-xs font-semibold text-muted-foreground">最大同时在途任务数</span>
          <select
            className="text-xs font-semibold bg-transparent border-none outline-none cursor-pointer"
            value={maxConcurrent}
            onChange={(e) => handleUpdateConfig(Number(e.target.value))}
            disabled={configLoading}
          >
            {[1, 2, 3, 4, 5, 6, 8].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted/40">
          <span className="text-xs font-semibold text-muted-foreground">启动间隔</span>
          <input
            type="number"
            min={0}
            max={60}
            step={0.5}
            value={taskStartInterval}
            onChange={(e) => handleUpdateInterval(Number(e.target.value))}
            className="w-14 text-xs font-semibold bg-transparent border-none outline-none text-center"
            disabled={configLoading}
          />
          <span className="text-xs text-muted-foreground">秒</span>
        </div>
      </div>

      <BatchRuntimePanel runtime={effectiveRuntimeStatus} loading={loading && !runtimeStatus} />

      {/* Batch list */}
      {loading && batches.length === 0 ? (
        <LoadingState label="正在加载批量任务…" />
      ) : batches.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title="暂无批量任务"
          detail='点击"新建批量任务"创建你的第一个批量任务'
          action={
            <Button onClick={handleOpenCreateDialog}>
              <Plus className="mr-1.5 h-4 w-4" />
              新建批量任务
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {batches.map((batch) => (
            <BatchGroupCard
              key={batch.batch_id}
              batch={batch}
              loading={loading}
              onRefresh={() => {
                loadBatches();
                loadRuntimeStatus();
              }}
            />
          ))}
        </div>
      )}

      {/* Create dialog */}
      {showCreateDialog && (
        <CreateBatchDialog
          onClose={() => setShowCreateDialog(false)}
          onCreated={loadBatches}
        />
      )}
    </PageBackground>
  );
}

import { useState, useEffect, useCallback } from "react";
import { Layers, Plus, RefreshCw, Play, Inbox, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { batchApi, BatchDetail } from "@/api/batch";
import CreateBatchDialog from "@/components/batch/CreateBatchDialog";
import BatchGroupCard from "@/components/batch/BatchGroupCard";
import { useAlert } from "@/components/ui/AlertProvider";
import { getSubscriptionError, isDeviceLimitError, isSubscriptionBlocked, getQuotaExhaustedMessage } from "@/api/subscription";
import { useSubscriptionStore } from "@/stores/subscriptionStore";

export default function BatchWorkshop() {
  const { alert: showAlert, confirm: showConfirm } = useAlert();
  const [batches, setBatches] = useState<BatchDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [maxConcurrent, setMaxConcurrent] = useState(3);
  const [taskStartInterval, setTaskStartInterval] = useState(0);
  const [configLoading, setConfigLoading] = useState(false);

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

  useEffect(() => {
    loadBatches();
    loadConfig();
  }, [loadBatches, loadConfig]);

  // Auto-refresh every 5 seconds when there are running tasks
  useEffect(() => {
    const hasRunning = batches.some((b) => b.status === "running");
    if (!hasRunning) return;
    const timer = setInterval(loadBatches, 5000);
    return () => clearInterval(timer);
  }, [batches, loadBatches]);

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

  return (
    <div className="max-w-7xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-extrabold tracking-tight flex items-center gap-2.5">
            <Layers className="w-6 h-6 text-primary" />
            批量工作台
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            批量创建和管理视频处理任务
          </p>
        </div>
      </div>

      {/* Toolbar: config + actions */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Parallel count */}
        <div className="flex items-center gap-2 px-3 py-2 border border-border/60 rounded-xl bg-card/50">
          <span className="text-xs font-semibold text-muted-foreground">并行数量</span>
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

        {/* Task start interval */}
        <div className="flex items-center gap-2 px-3 py-2 border border-border/60 rounded-xl bg-card/50">
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

        <span className="w-px h-6 bg-border/40" />

        {/* Stop all */}
        <button
          onClick={handleStopAll}
          disabled={loading}
          className="flex items-center gap-1.5 px-3.5 py-2 border border-red-500/40 rounded-xl text-xs font-semibold text-red-600 hover:bg-red-500/10 transition-all duration-200 active:scale-95 disabled:opacity-50"
        >
          <Square className="w-3.5 h-3.5" />
          全部停止
        </button>

        {/* Resume unfinished */}
        <button
          onClick={handleResumeUnfinished}
          disabled={loading}
          className="flex items-center gap-1.5 px-3.5 py-2 border border-border/60 rounded-xl text-xs font-semibold hover:bg-accent/60 transition-all duration-200 active:scale-95 disabled:opacity-50"
        >
          <Play className="w-3.5 h-3.5 text-emerald-500" />
          继续未完成任务
        </button>

        {/* New batch */}
        <button
          onClick={handleOpenCreateDialog}
          className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 transition-all duration-200 active:scale-95 shadow-sm shadow-primary/20"
        >
          <Plus className="w-3.5 h-3.5" />
          新建批量任务
        </button>

        {/* Refresh */}
        <button
          onClick={loadBatches}
          disabled={loading}
          className="flex items-center gap-1.5 px-3.5 py-2 border border-border/60 rounded-xl text-xs font-semibold hover:bg-accent/60 transition-all duration-200 active:scale-95 disabled:opacity-50 ml-auto"
        >
          <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
          刷新
        </button>
      </div>

      {/* Batch list */}
      {loading && batches.length === 0 ? (
        <div className="flex items-center justify-center py-16">
          <RefreshCw className="w-6 h-6 animate-spin text-muted-foreground" />
        </div>
      ) : batches.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 rounded-2xl bg-muted/50 flex items-center justify-center mb-4">
            <Inbox className="w-8 h-8 text-muted-foreground/40" />
          </div>
          <p className="text-sm font-medium text-muted-foreground">暂无批量任务</p>
          <p className="text-xs text-muted-foreground/60 mt-1">
            点击"新建批量任务"创建你的第一个批量任务
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {batches.map((batch) => (
            <BatchGroupCard
              key={batch.batch_id}
              batch={batch}
              loading={loading}
              onRefresh={loadBatches}
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
    </div>
  );
}

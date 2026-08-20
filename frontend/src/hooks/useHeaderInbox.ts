import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import client from "@/api/client";
import { batchApi, type BatchDetail } from "@/api/batch";

export type HeaderAnnouncement = {
  id: string;
  title: string;
  content: string;
  createdAt: string;
};

export type RuntimeNotificationKind = "dispatch" | "success" | "error";

export type RuntimeNotification = {
  id: string;
  kind: RuntimeNotificationKind;
  title: string;
  description: string;
  createdAt: number;
  read: boolean;
  batchId?: string;
  taskId?: string;
};

type AnnouncementResponse = {
  announcements?: Record<string, unknown>[];
  error?: string | null;
};

type TaskSnapshot = {
  batchId: string;
  batchName: string;
  taskId: string;
  taskName: string;
  status: string;
  error: string;
};

function pickValue(source: Record<string, unknown> | null | undefined, keys: string[]) {
  if (!source) return "";
  for (const key of keys) {
    const value = source[key];
    if (value !== undefined && value !== null && value !== "") return String(value);
  }
  return "";
}

export function formatAnnouncementTime(iso: string) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function parseAnnouncements(items: Record<string, unknown>[] | undefined): HeaderAnnouncement[] {
  return (items || []).map((item, index) => {
    const title = pickValue(item, ["title", "name"]) || "项目公告";
    const content = pickValue(item, ["content", "description", "body"]) || "暂无内容";
    const createdAtRaw = pickValue(item, ["created_at", "publish_at"]);
    const id = pickValue(item, ["id", "announcement_id"]) || `${createdAtRaw}-${title}-${index}`;
    return { id, title, content, createdAt: formatAnnouncementTime(createdAtRaw) };
  });
}

function createSnapshotMap(batches: BatchDetail[]): Map<string, TaskSnapshot> {
  const snapshot = new Map<string, TaskSnapshot>();
  for (const batch of batches) {
    for (const task of batch.tasks || []) {
      snapshot.set(task.task_id, {
        batchId: batch.batch_id,
        batchName: batch.name || batch.batch_id,
        taskId: task.task_id,
        taskName: task.task_name || task.task_id.slice(0, 8),
        status: task.status,
        error:
          task.error ||
          Object.values(task.nodes || {}).find((node) => node.error)?.error ||
          "",
      });
    }
  }
  return snapshot;
}

function createDispatchNotification(task: TaskSnapshot, started = false): RuntimeNotification {
  return {
    id: `${task.taskId}:${started ? "started" : "dispatch"}:${Date.now()}`,
    kind: "dispatch",
    title: started ? "任务开始执行" : "任务已分发",
    description: `批次「${task.batchName}」中的任务「${task.taskName}」${started ? "开始执行" : "已进入待执行队列"}`,
    createdAt: Date.now(),
    read: false,
    batchId: task.batchId,
    taskId: task.taskId,
  };
}

function createSuccessNotification(task: TaskSnapshot): RuntimeNotification {
  return {
    id: `${task.taskId}:completed:${Date.now()}`,
    kind: "success",
    title: "任务执行完成",
    description: `批次「${task.batchName}」中的任务「${task.taskName}」已完成`,
    createdAt: Date.now(),
    read: false,
    batchId: task.batchId,
    taskId: task.taskId,
  };
}

function createErrorNotification(task: TaskSnapshot): RuntimeNotification {
  return {
    id: `${task.taskId}:error:${Date.now()}`,
    kind: "error",
    title: task.status === "cancelled" ? "任务已中止" : "任务异常退出",
    description:
      `批次「${task.batchName}」中的任务「${task.taskName}」` +
      (task.error ? `：${task.error}` : task.status === "cancelled" ? "已取消" : "执行失败"),
    createdAt: Date.now(),
    read: false,
    batchId: task.batchId,
    taskId: task.taskId,
  };
}

export function useHeaderInbox() {
  const [announcements, setAnnouncements] = useState<HeaderAnnouncement[]>([]);
  const [announcementLoading, setAnnouncementLoading] = useState(false);
  const [announcementError, setAnnouncementError] = useState("");
  const [notifications, setNotifications] = useState<RuntimeNotification[]>([]);
  const [toastQueue, setToastQueue] = useState<RuntimeNotification[]>([]);
  const baselineReadyRef = useRef(false);
  const snapshotRef = useRef<Map<string, TaskSnapshot>>(new Map());
  const pollTimerRef = useRef<number | null>(null);
  const toastTimersRef = useRef<Record<string, number>>({});

  const dismissToast = useCallback((id: string) => {
    const timer = toastTimersRef.current[id];
    if (timer) {
      window.clearTimeout(timer);
      delete toastTimersRef.current[id];
    }
    setToastQueue((current) => current.filter((item) => item.id !== id));
  }, []);

  const pushNotification = useCallback((notification: RuntimeNotification) => {
    setNotifications((current) => [notification, ...current].slice(0, 80));
    setToastQueue((current) => [notification, ...current.filter((item) => item.taskId !== notification.taskId || item.kind !== notification.kind)].slice(0, 3));
    toastTimersRef.current[notification.id] = window.setTimeout(() => dismissToast(notification.id), 5000);
  }, [dismissToast]);

  const refreshAnnouncements = useCallback(async () => {
    setAnnouncementLoading(true);
    try {
      const response = await client.get("/api/public-info/announcements");
      const data = response.data as AnnouncementResponse;
      setAnnouncements(parseAnnouncements(data.announcements));
      setAnnouncementError(data.error || "");
    } catch (error) {
      setAnnouncementError(error instanceof Error ? error.message : "公告获取失败");
    } finally {
      setAnnouncementLoading(false);
    }
  }, []);

  const syncTaskNotifications = useCallback(async () => {
    try {
      const result = await batchApi.listPage(1, 100);
      const nextSnapshot = createSnapshotMap(result.batches || []);
      if (!baselineReadyRef.current) {
        snapshotRef.current = nextSnapshot;
        baselineReadyRef.current = true;
        return;
      }

      nextSnapshot.forEach((task, taskId) => {
        const previous = snapshotRef.current.get(taskId);
        if (!previous) {
          if (task.status === "created") pushNotification(createDispatchNotification(task));
          else if (task.status === "running") pushNotification(createDispatchNotification(task, true));
          return;
        }
        if (previous.status === task.status) return;
        if (task.status === "created" && previous.status !== "created") {
          pushNotification(createDispatchNotification(task));
          return;
        }
        if (task.status === "running" && previous.status !== "running") {
          pushNotification(createDispatchNotification(task, true));
          return;
        }
        if (task.status === "completed" && previous.status !== "completed") {
          pushNotification(createSuccessNotification(task));
          return;
        }
        if ((task.status === "failed" || task.status === "cancelled") && previous.status !== task.status) {
          pushNotification(createErrorNotification(task));
        }
      });

      snapshotRef.current = nextSnapshot;
    } catch {
      // 头部通知不阻塞主界面；接口偶发失败时下个轮询周期继续
    }
  }, [pushNotification]);

  const markNotificationsRead = useCallback(() => {
    setNotifications((current) => current.map((item) => ({ ...item, read: true })));
  }, []);

  const clearNotifications = useCallback(() => {
    Object.values(toastTimersRef.current).forEach((timer) => window.clearTimeout(timer));
    toastTimersRef.current = {};
    setNotifications([]);
    setToastQueue([]);
    snapshotRef.current = new Map();
    baselineReadyRef.current = false;
  }, []);

  useEffect(() => {
    clearNotifications();
    refreshAnnouncements();
    syncTaskNotifications();
    pollTimerRef.current = window.setInterval(syncTaskNotifications, 5000);
    return () => {
      if (pollTimerRef.current) window.clearInterval(pollTimerRef.current);
      Object.values(toastTimersRef.current).forEach((timer) => window.clearTimeout(timer));
    };
  }, [clearNotifications, refreshAnnouncements, syncTaskNotifications]);

  const unreadNotificationCount = useMemo(
    () => notifications.filter((item) => !item.read).length,
    [notifications]
  );

  return {
    announcements,
    announcementLoading,
    announcementError,
    notifications,
    toastQueue,
    unreadNotificationCount,
    refreshAnnouncements,
    markNotificationsRead,
    dismissToast,
  };
}

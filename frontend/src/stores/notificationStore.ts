import { create } from "zustand";

export type NotificationKind = "info" | "success" | "warning" | "error";

export type NotificationItem = {
  id: string;
  kind: NotificationKind;
  title: string;
  description: string;
  createdAt: number;
  read: boolean;
  /** 来源标记（可选），用于区分推送方 */
  source?: string;
};

type PushInput = Omit<NotificationItem, "id" | "createdAt" | "read">;

type NotificationState = {
  notifications: NotificationItem[];
  unreadCount: number;
  pushNotification: (item: PushInput) => string;
  markAllRead: () => void;
  dismiss: (id: string) => void;
  clear: () => void;
};

/** 列表上限，防止长时间运行后无界增长 */
const MAX_ITEMS = 100;

function recount(items: NotificationItem[]): number {
  return items.reduce((acc, n) => acc + (n.read ? 0 : 1), 0);
}

function makeId(input: PushInput): string {
  return `${input.source ?? "app"}:${input.kind}:${Date.now()}:${Math.random().toString(36).slice(2, 7)}`;
}

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  unreadCount: 0,
  pushNotification: (item) => {
    const id = makeId(item);
    const next: NotificationItem = {
      id,
      createdAt: Date.now(),
      read: false,
      ...item,
    };
    set((state) => {
      const notifications = [next, ...state.notifications].slice(0, MAX_ITEMS);
      return { notifications, unreadCount: recount(notifications) };
    });
    return id;
  },
  markAllRead: () => {
    set((state) => ({
      notifications: state.notifications.map((n) => (n.read ? n : { ...n, read: true })),
      unreadCount: 0,
    }));
  },
  dismiss: (id) => {
    set((state) => {
      const notifications = state.notifications.filter((n) => n.id !== id);
      return { notifications, unreadCount: recount(notifications) };
    });
  },
  clear: () => {
    set({ notifications: [], unreadCount: 0 });
  },
}));
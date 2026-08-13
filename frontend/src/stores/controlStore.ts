import { create } from "zustand";
import { getControlSession, logoutControlSession, type ControlUser } from "@/api/controlPlane";
import { getPresence, type EditingState, type PresenceMember } from "@/api/collaboration";
import { getWebSocketUrl } from "@/api/baseUrl";

export type WsStatus = "idle" | "connecting" | "online" | "offline";

export interface ProgressEvent {
  task_id?: string;
  step_id?: string;
  progress?: number;
  message?: string;
  event_type?: string;
  status?: string;
  ts: number;
}

interface ControlState {
  user: ControlUser | null;
  roles: string[];
  presence: PresenceMember[];
  editing: EditingState | null;
  wsStatus: WsStatus;
  progressEvents: ProgressEvent[];
  setUser: (user: ControlUser | null) => void;
  setPresence: (members: PresenceMember[]) => void;
  setEditing: (editing: EditingState | null, broadcast?: boolean) => void;
  addProgressEvent: (event: ProgressEvent) => void;
  clearProgressEvents: () => void;
  refreshPresence: () => Promise<void>;
  refreshSession: () => Promise<ControlUser | null>;
  connectWS: () => void;
  disconnectWS: () => void;
  logout: () => Promise<void>;
}

let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let heartbeatTimer: number | null = null;
let reconnectAttempts = 0;
let manualClose = false;

function getSessionTokenFromCookie(): string {
  const match = document.cookie.match(/(?:^|;\s*)cp_session=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function scheduleReconnect() {
  if (manualClose) return;
  reconnectAttempts += 1;
  const delay = Math.min(30000, 1000 * Math.pow(2, reconnectAttempts));
  reconnectTimer = setTimeout(() => useControlStore.getState().connectWS(), delay);
}

export const useControlStore = create<ControlState>((set, get) => ({
  user: null,
  roles: [],
  presence: [],
  editing: null,
  wsStatus: "idle",
  progressEvents: [],

  setUser: (user) => {
    set({ user, roles: user?.roles ?? [] });
  },

  setPresence: (presence) => set({ presence }),

  setEditing: (editing, broadcast = true) => {
    set({ editing });
    if (broadcast && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "editing", editing }));
    }
  },

  addProgressEvent: (event) => {
    set((state) => ({ progressEvents: [{ ...event, ts: Date.now() }, ...state.progressEvents].slice(0, 200) }));
  },

  clearProgressEvents: () => set({ progressEvents: [] }),

  refreshPresence: async () => {
    try {
      const data = await getPresence();
      set({ presence: data.members });
    } catch {
      /* WS 与 REST 均不可用时保持现状 */
    }
  },

  refreshSession: async () => {
    try {
      const user = await getControlSession();
      if (user) {
        set({ user, roles: user.roles ?? [] });
        get().refreshPresence();
        get().connectWS();
        return user;
      }
      set({ user: null, roles: [], presence: [] });
      return null;
    } catch {
      set({ user: null, roles: [], presence: [] });
      return null;
    }
  },

  connectWS: () => {
    manualClose = false;
    const { user } = get();
    if (!user || socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) return;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    set({ wsStatus: "connecting" });
    const token = getSessionTokenFromCookie();
    const baseUrl = getWebSocketUrl("/ws/collaboration");
    const url = token ? `${baseUrl}?token=${encodeURIComponent(token)}` : baseUrl;
    try {
      socket = new WebSocket(url);
    } catch {
      set({ wsStatus: "offline" });
      scheduleReconnect();
      return;
    }
    socket.onopen = () => {
      reconnectAttempts = 0;
      set({ wsStatus: "online" });
      heartbeatTimer = window.setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ping" }));
      }, 25000);
    };
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === "presence") {
          set({ presence: message.members ?? [] });
        } else if (message.type === "presence_join" || message.type === "presence_leave") {
          get().refreshPresence();
        } else if (message.type === "editing") {
          set((state) => ({
            presence: state.presence.map((m) => (m.user_id === message.user_id ? { ...m, editing: message.editing ?? null } : m)),
          }));
        } else if (message.type === "progress") {
          get().addProgressEvent(message);
        }
      } catch {
        /* 忽略无法解析的帧 */
      }
    };
    socket.onclose = () => {
      socket = null;
      if (heartbeatTimer) {
        clearInterval(heartbeatTimer);
        heartbeatTimer = null;
      }
      set({ wsStatus: "offline" });
      scheduleReconnect();
    };
    socket.onerror = () => {
      /* onclose 统一处理重连 */
    };
  },

  disconnectWS: () => {
    manualClose = true;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
    if (socket) {
      socket.onclose = null;
      socket.close();
      socket = null;
    }
    set({ wsStatus: "idle" });
  },

  logout: async () => {
    try {
      await logoutControlSession();
    } catch {
      /* 忽略登出接口异常 */
    }
    get().disconnectWS();
    set({ user: null, roles: [], presence: [], editing: null });
  },
}));

import { createWebSocket } from "./ws";

export type TaskMonitorOptions<T> = {
  taskId: string;
  fetchTask: (taskId: string, signal: AbortSignal) => Promise<T | null | undefined>;
  isTerminal: (task: T) => boolean;
  onTask: (task: T) => void;
  onEvent?: (event: Record<string, unknown>) => void;
  onError?: (error: unknown) => void;
  pollIntervalMs?: number;
  maxPollAttempts?: number;
  reconnectLimit?: number;
};

export class TaskMonitor<T> {
  private readonly controller = new AbortController();
  private readonly options: Required<Pick<TaskMonitorOptions<T>, "pollIntervalMs" | "maxPollAttempts" | "reconnectLimit">> & TaskMonitorOptions<T>;
  private socket: WebSocket | null = null;
  private reconnectTimer: number | null = null;
  private pollTimer: number | null = null;
  private pollAttempts = 0;
  private reconnectAttempts = 0;
  private stopped = false;

  constructor(options: TaskMonitorOptions<T>) {
    this.options = {
      ...options,
      pollIntervalMs: options.pollIntervalMs ?? 2000,
      maxPollAttempts: options.maxPollAttempts ?? 900,
      reconnectLimit: options.reconnectLimit ?? 8,
    };
  }

  start() {
    if (this.stopped) return;
    this.poll();
    this.connect();
  }

  stop() {
    if (this.stopped) return;
    this.stopped = true;
    this.controller.abort();
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    if (this.pollTimer !== null) window.clearTimeout(this.pollTimer);
    this.reconnectTimer = null;
    this.pollTimer = null;
    this.socket?.close();
    this.socket = null;
  }

  private connect() {
    if (this.stopped || this.reconnectAttempts >= this.options.reconnectLimit) return;
    const socket = createWebSocket(this.options.taskId, (event) => this.options.onEvent?.(event as Record<string, unknown>));
    this.socket = socket;
    socket.onopen = () => {
      this.reconnectAttempts = 0;
    };
    socket.onerror = () => socket.close();
    socket.onclose = () => {
      if (this.stopped || this.socket !== socket) return;
      this.socket = null;
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect() {
    if (this.reconnectAttempts >= this.options.reconnectLimit) return;
    const delay = Math.min(30000, 1000 * 2 ** this.reconnectAttempts);
    this.reconnectAttempts += 1;
    this.reconnectTimer = window.setTimeout(() => this.connect(), delay);
  }

  private async poll() {
    if (this.stopped || this.pollAttempts >= this.options.maxPollAttempts) return;
    this.pollAttempts += 1;
    try {
      const task = await this.options.fetchTask(this.options.taskId, this.controller.signal);
      if (task) {
        this.options.onTask(task);
        if (this.options.isTerminal(task)) {
          this.stop();
          return;
        }
      }
    } catch (error) {
      if (!this.controller.signal.aborted) this.options.onError?.(error);
    }
    if (!this.stopped) this.pollTimer = window.setTimeout(() => this.poll(), this.options.pollIntervalMs);
  }
}

import { getWebSocketUrl } from "./baseUrl";

export { getWebSocketUrl };

export function createWebSocket(taskId: string, onMessage: (data: unknown) => void): WebSocket {
  const ws = new WebSocket(getWebSocketUrl(`/ws/tasks/${encodeURIComponent(taskId)}`));
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch {
      return;
    }
  };
  return ws;
}

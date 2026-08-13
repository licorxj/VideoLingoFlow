import { useEffect, useRef } from "react";
import { createWebSocket } from "@/api/ws";

export function useWebSocket(taskId: string | null, onMessage: (data: any) => void) {
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!taskId) return;
    wsRef.current = createWebSocket(taskId, onMessage);
    return () => {
      wsRef.current?.close();
    };
  }, [taskId]);

  return wsRef.current;
}

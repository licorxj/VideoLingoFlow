import client from "./client";
import { getApiUrl } from "./baseUrl";

export interface PiSession {
  session_id: string;
  project_id: string;
  model: string;
  tools: string[];
  streaming: boolean;
  message_count: number;
  last_error?: string | null;
  closed: boolean;
  seq?: number;
  messages?: PiChatMessage[];
}

export interface PiChatMessage {
  role: "user" | "assistant";
  text: string;
  thinking?: string;
}

export interface PiEvent {
  type: string;
  seq?: number;
  message?: { role?: string; content?: unknown };
  assistantMessageEvent?: {
    type?: string;
    delta?: string;
    content?: string;
    kind?: string;
    thinking?: string;
  };
  toolName?: string;
  isError?: boolean;
  error?: string;
}

export interface PiHistorySession {
  id: number;
  session_id: string;
  created_at: number;
  closed_at: number;
  message_count: number;
  messages: PiChatMessage[];
  cwd?: string;
  session_dir?: string;
}

export interface PiIntegration {
  kind: "skill" | "mcp";
  item_id: string;
  name: string;
  path: string;
  enabled: boolean;
}
export interface PiAgentSettings {
  model_mode: "router" | "custom";
  custom_base_url: string;
  custom_api_key: string;
  custom_model: string;
  base_docs_paths: string[];
  read_blacklist: string[];
  write_blacklist: string[];
  tools_enabled: string[];
  skills: PiIntegration[];
  mcps: PiIntegration[];
  assistants: Record<
    string,
    {
      persona?: string;
      docs_path?: string;
      read_blacklist?: string[];
      write_blacklist?: string[];
    }
  >;
}

export const piRpcApi = {
  createSession: (projectId: string, systemPrompt?: string) =>
    client.post<PiSession>("/api/pi/sessions", {
      project_id: projectId,
      system_prompt: systemPrompt,
    }),
  getSession: (sessionId: string) =>
    client.get<PiSession>(`/api/pi/sessions/${encodeURIComponent(sessionId)}`),
  prompt: (
    sessionId: string,
    message: string,
    streamingBehavior?: "steer" | "followUp",
    attachments?: string[],
  ) =>
    client.post(`/api/pi/sessions/${encodeURIComponent(sessionId)}/prompt`, {
      message,
      streaming_behavior: streamingBehavior,
      attachments,
    }),
  abort: (sessionId: string) =>
    client.post(`/api/pi/sessions/${encodeURIComponent(sessionId)}/abort`),
  close: (sessionId: string) =>
    client.delete(`/api/pi/sessions/${encodeURIComponent(sessionId)}`),
  clear: (sessionId: string) =>
    client.post<PiSession>(
      `/api/pi/sessions/${encodeURIComponent(sessionId)}/clear`,
    ),
  newSession: (sessionId: string, systemPrompt?: string) =>
    client.post<PiSession>(
      `/api/pi/sessions/${encodeURIComponent(sessionId)}/new`,
      { system_prompt: systemPrompt },
    ),
  history: (sessionId: string) =>
    client.get<PiHistorySession[]>(
      `/api/pi/sessions/${encodeURIComponent(sessionId)}/history`,
    ),
  restoreHistory: (sessionId: string, historyId: number) =>
    client.post<PiSession>(
      `/api/pi/sessions/${encodeURIComponent(sessionId)}/history/${historyId}/restore`,
    ),
  deleteHistory: (sessionId: string, historyId: number) =>
    client.delete<{ success: boolean }>(
      `/api/pi/sessions/${encodeURIComponent(sessionId)}/history/${historyId}`,
    ),
  getSettings: () => client.get<PiAgentSettings>("/api/pi/settings"),
  updateSettings: (values: Partial<PiAgentSettings>) =>
    client.put<PiAgentSettings>("/api/pi/settings", { values }),
  updateAssistant: (assistantId: string, values: Record<string, unknown>) =>
    client.put(`/api/pi/settings/assistants/${assistantId}`, { values }),
  scan: (kind: "docs" | "skill" | "mcp") =>
    client.post(
      kind === "docs"
        ? "/api/pi/settings/scan/docs"
        : `/api/pi/settings/scan/${kind}`,
    ),
  toggleIntegration: (
    kind: "skill" | "mcp",
    itemId: string,
    enabled: boolean,
  ) =>
    client.put(`/api/pi/settings/${kind}/${encodeURIComponent(itemId)}`, {
      enabled,
    }),
  staging: () =>
    client.get<{ name: string; path: string }[]>("/api/pi/settings/staging"),
  clearCache: (category: "sessions" | "models" | "staging" | "all") =>
    client.post<{ sessions: number; models: number; staging: number }>(
      "/api/pi/cache/clear",
      { category },
    ),
  models: () =>
    client.get<
      {
        id: string;
        name: string;
        api: string;
        provider: string;
        baseUrl: string;
        reasoning: boolean;
        contextWindow: number;
        maxTokens: number;
      }[]
    >("/api/pi/settings/models"),
  install: (
    kind: "skill" | "mcp",
    name: string,
    level: "project" | "system",
    sourceDir: string,
  ) =>
    client.post<{
      kind: string;
      name: string;
      level: string;
      target: string;
      enabled: boolean;
    }>("/api/pi/settings/install", { kind, name, level, source_dir: sourceDir }),
  eventsUrl: (sessionId: string) =>
    getApiUrl(`/api/pi/sessions/${encodeURIComponent(sessionId)}/events`),
  getRuntime: () => client.get<PiRuntimeInfo>("/api/pi/runtime"),
  getDiagnostics: () => client.get<PiRuntimeInfo>("/api/pi/diagnostics"),
};

export interface PiRuntimeInfo {
  enabled: boolean;
  status:
    | "disabled"
    | "missing_runtime"
    | "incompatible_runtime"
    | "missing_dependencies"
    | "launch_failed"
    | "available";
  message?: string;
  node_version?: string;
  node_path?: string;
  cli_path?: string;
  launch_error?: string;
  checks?: Record<string, boolean>;
  session_count?: number;
}

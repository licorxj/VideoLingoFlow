import client from "./client";

export type EditorAssetType = "video" | "audio" | "image" | "subtitle";

export interface EditorTask {
  id: string;
  task_name: string;
  status: string;
  created_at?: string;
  finished_at?: string;
  has_project: boolean;
}

export interface EditorAsset {
  id: string;
  name: string;
  type: EditorAssetType;
  relative_path: string;
  source: string;
  size: number;
  mime_type?: string;
  duration?: number;
  width?: number;
  height?: number;
  recommended?: boolean;
  selected?: boolean;
  category?: "video" | "audio" | "subtitle" | "cover" | "other";
}

export interface EditorSnapshot {
  project: Record<string, any>;
  assets: EditorAsset[];
  characters: Record<string, any>[];
  revision: number;
}

export interface EditorImportSelection {
  candidate_ids: string[];
  use_dub_segments: boolean;
}

export interface AgentRun {
  id: string;
  status: "completed" | "failed" | "running" | "cancelled";
  content?: string;
  error?: string;
  output_revision?: number;
  toolCalls: Array<{ id: string; name: string; arguments: Record<string, any>; result: { success: boolean; message: string } }>;
}

export interface CutiaUpdateResult {
  success: boolean;
  updated: boolean;
  message: string;
  previous_revision?: string;
  current_revision?: string;
  backup_branch?: string;
}

export const editorApi = {
  listTasks: () => client.get<{ tasks: EditorTask[] }>("/api/editor/tasks"),
  getCandidates: (taskId: string) => client.get<{ candidates: EditorAsset[] }>(`/api/editor/tasks/${taskId}/import-candidates`),
  importAssets: (taskId: string, selection: EditorImportSelection) => client.post<EditorSnapshot>(`/api/editor/tasks/${taskId}/import`, selection),
  getProject: (taskId: string) => client.get<EditorSnapshot>(`/api/editor/tasks/${taskId}/project`),
  saveProject: (taskId: string, project: Record<string, any>, revision: number) => client.put<EditorSnapshot>(`/api/editor/tasks/${taskId}/project`, { project, expected_revision: revision }),
  assetUrl: (taskId: string, assetId: string) => `${client.defaults.baseURL}/api/editor/tasks/${encodeURIComponent(taskId)}/assets/${encodeURIComponent(assetId)}/stream`,
  runAgent: (taskId: string, payload: { content: string; expert_role: string; expected_revision: number }) => client.post<AgentRun>(`/api/editor/tasks/${taskId}/agent/runs`, payload),
  updateCutia: () => client.post<CutiaUpdateResult>("/api/cutia/update", undefined, { timeout: 150000 }),
};

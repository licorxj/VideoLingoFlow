import client from "./client";

export type VideoDubWorkspaceSummary = {
  id: string;
  name: string;
  video_name: string;
  duration: number;
  subtitle_count: number;
  version: number;
  updated_at: string | null;
};

export type VideoDubWorkspaceDetail = {
  id: string;
  name: string;
  video_name: string;
  video_key: string;
  duration: number;
  state: Record<string, unknown>;
  version: number;
  updated_at: string | null;
};

export const videodubApi = {
  create: (file: File | null, name: string) => {
    const form = new FormData();
    if (file) form.append("file", file);
    form.append("name", name);
    return client.post("/api/videodub", form);
  },
  list: () => client.get("/api/videodub"),
  detail: (id: string) => client.get(`/api/videodub/${id}`),
  saveState: (id: string, state: unknown, name?: string, duration?: number) =>
    client.put(`/api/videodub/${id}/state`, { state, name, duration }),
  uploadAudio: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return client.post(`/api/videodub/${id}/audio`, form);
  },
  mediaUrl: (id: string, key: string) => `/api/videodub/${id}/media?key=${encodeURIComponent(key)}`,
  remove: (id: string) => client.delete(`/api/videodub/${id}`),
  /** vlf 任务工作区内的配音任务表与视频文件列表。 */
  vlfFiles: (taskId: string) => client.get("/api/videodub/vlf-files", { params: { task_id: taskId } }),
  vlfImport: (data: { task_id: string; dub_table: string; video_path?: string }) => client.post("/api/videodub/vlf-import", data),
  /** 把 vlf 任务里的音频文件复制进 voiceforge 存储，返回 storage_key 供克隆模式作参考音频。 */
  referenceFromTask: (data: { taskId: string; path: string }) => client.post("/api/videodub/reference-from-task", { task_id: data.taskId, path: data.path }),
  /** vlf 任务媒体（视频/配音/原文片段）走现成的带 Range 文件流。 */
  vlfMediaUrl: (taskId: string, path: string) => `/api/files/stream?path=${encodeURIComponent(path)}&task_id=${encodeURIComponent(taskId)}`,
};

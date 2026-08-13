import client from "./client";

export interface CreateTaskRequest {
  task_type: string;
  input_files: Record<string, string>;
  name?: string;
  options?: Record<string, any>;
}

export const tasksApi = {
  list: (status?: string) => client.get("/api/tasks", { params: { status } }),
  get: (id: string, signal?: AbortSignal) => client.get(`/api/tasks/${id}`, { signal }),
  create: (data: CreateTaskRequest) => client.post("/api/tasks", data),
  execute: (id: string, fromStep?: string) => client.post(`/api/tasks/${id}/execute`, { from_step: fromStep }),
  rollback: (id: string, stepId: string) => client.post(`/api/tasks/${id}/rollback/${stepId}`),
  delete: (id: string) => client.delete(`/api/tasks/${id}`),
  getMeta: () => client.get("/api/tasks/meta/types"),
};

import client from "./client";

export interface BatchSummary {
  id: string;
  name: string;
  workflow_id: string;
  workflow_name: string;
  created_at: string;
  task_count: number;
  task_ids: string[];
  status: string;  // created | running | paused | completed | partial | failed
}

export interface BatchTaskDetail {
  task_id: string;
  task_name?: string;
  index: number;
  status: string;
  nodes: Record<string, {
    nodeType: string;
    label: string;
    status: string;
    progress: number;
    message: string;
    error: string;
  }>;
  started_at: string;
  finished_at: string;
  error: string;
}

export interface BatchDetail {
  batch_id: string;
  name: string;
  workflow_id: string;
  workflow_name: string;
  workflow: {
    id?: string;
    name?: string;
    nodes?: any[];
    edges?: any[];
  };
  tasks: BatchTaskDetail[];
  workflow_nodes: { id: string; nodeType: string; label: string }[];
  status: string;
  created_at: string;
}

export interface BatchPage {
  batches: BatchDetail[];
  total: number;
  page: number;
  page_size: number;
}

export interface BatchCreateRequest {
  workflow_id: string;
  batch_name?: string;
  tasks: Record<string, string>[];
  common_config: Record<string, any>;
}

export const batchApi = {
  list: () => client.get("/api/batch").then((r) => r.data.batches as BatchSummary[]),

  listPage: (page = 1, pageSize = 20) =>
    client.get("/api/batch/summary", { params: { page, page_size: pageSize } }).then((r) => r.data as BatchPage),

  getDetail: (batchId: string) =>
    client.get(`/api/batch/${batchId}`).then((r) => r.data as BatchDetail),

  create: (data: BatchCreateRequest) =>
    client.post("/api/batch/create", data).then((r) => r.data),

  start: (batchId: string) =>
    client.post(`/api/batch/${batchId}/start`).then((r) => r.data),

  stop: (batchId: string) =>
    client.post(`/api/batch/${batchId}/stop`).then((r) => r.data),

  syncWorkflow: (batchId: string, workflowId: string) =>
    client.post(`/api/batch/${batchId}/sync-workflow`, null, {
      params: { workflow_id: workflowId },
    }).then((r) => r.data),

  resume: (batchId: string) =>
    client.post(`/api/batch/${batchId}/resume`).then((r) => r.data),

  cancelTask: (batchId: string, taskId: string) =>
    client.post(`/api/batch/${batchId}/${taskId}/cancel`).then((r) => r.data),

  retryTask: (batchId: string, taskId: string) =>
    client.post(`/api/batch/${batchId}/${taskId}/retry`).then((r) => r.data),

  resumeTask: (batchId: string, taskId: string) =>
    client.post(`/api/batch/${batchId}/${taskId}/resume`).then((r) => r.data),

  deleteBatch: (batchId: string) =>
    client.delete(`/api/batch/${batchId}`).then((r) => r.data),

  addTasks: (batchId: string, tasks: Record<string, string>[], commonConfig?: Record<string, any>) =>
    client.post(`/api/batch/${batchId}/add`, { tasks, common_config: commonConfig || {} }).then((r) => r.data),

  deleteTasks: (batchId: string, taskIds: string[]) =>
    client.delete(`/api/batch/${batchId}/tasks`, { data: { task_ids: taskIds } }).then((r) => r.data),

  stopAll: () => client.post("/api/batch/stop-all").then((r) => r.data),

  resumeAllUnfinished: () =>
    client.post("/api/batch/resume-unfinished").then((r) => r.data),

  getConfig: () =>
    client.get("/api/batch/config").then((r) => r.data),

  updateConfig: (maxConcurrent: number, taskStartInterval?: number) =>
    client.put("/api/batch/config", {
      max_concurrent_tasks: maxConcurrent,
      task_start_interval: taskStartInterval ?? 0,
    }).then((r) => r.data),
};

import client from "./client";

export interface ArchivedTask {
  task_id: string;
  task_name: string;
  workflow_name: string;
  archive_path: string;
  archived_at: string | null;
  exists: boolean;
}

export interface RestoreArchivedResult {
  restored: { task_id: string; dir: string; archive_path: string }[];
  failed: { task_id: string; error: string }[];
}

export const historyApi = {
  list: (status?: string) => client.get("/api/history", { params: { status } }),
  listArchived: () => client.get<{ tasks: ArchivedTask[] }>("/api/history/archived"),
  restore: (taskIds: string[]) =>
    client.post<RestoreArchivedResult>("/api/history/restore", { task_ids: taskIds }),
};

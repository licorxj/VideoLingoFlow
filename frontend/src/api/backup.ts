import client from "./client";

export type RestoreMode = "overwrite" | "incremental";

export interface BackupOption {
  id: string;
  label: string;
  description: string;
  currentCount: number;
}

export interface BackupInfo {
  path: string;
  name: string;
  createdAt: string;
  options: string[];
  itemCount: number;
}

export interface BackupCreateResult {
  success: boolean;
  backupPath: string;
  createdAt: string;
  options: string[];
  itemCount: number;
}

export interface RestoreItemResult {
  category: string;
  restored: number;
  label: string;
}

export interface BackupRestoreResult {
  success: boolean;
  mode: RestoreMode;
  restored: RestoreItemResult[];
}

export const backupApi = {
  options: () => client.get<{ options: BackupOption[] }>("/api/backup/options"),
  list: (dir: string) =>
    client.get<{ backups: BackupInfo[] }>("/api/backup/list", { params: { dir } }),
  create: (backupDir: string, options: string[]) =>
    client.post<BackupCreateResult>("/api/backup/create", { backupDir, options }),
  restore: (backupPath: string, options: string[], mode: RestoreMode) =>
    client.post<BackupRestoreResult>("/api/backup/restore", {
      backupPath,
      options,
      mode,
    }),
};

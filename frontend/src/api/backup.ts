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

export interface BackupSettings {
  backupDir: string;
  settingsPath?: string;
}

export interface BackupSettingsSaveResult {
  success: boolean;
  backupDir: string;
  settingsPath: string;
}

export const backupApi = {
  options: () => client.get<{ options: BackupOption[] }>("/api/backup/options"),
  /** 读取备份设置（后端存于用户目录 ~/.lcsoftware，文件不存在时返回空值） */
  getSettings: () => client.get<BackupSettings>("/api/backup/settings"),
  /** 保存备份目录设置（后端会自动初始化 ~/.lcsoftware 目录） */
  saveSettings: (backupDir: string) =>
    client.put<BackupSettingsSaveResult>("/api/backup/settings", { backupDir }),
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

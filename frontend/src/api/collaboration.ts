import client from "./client";
import { getApiUrl } from "./baseUrl";

export type ControlRole = "admin" | "editor" | "viewer";

export interface EditingState {
  project_id?: string;
  workflow_key?: string;
  node_id?: string;
}

export interface PresenceMember {
  user_id: string;
  username: string;
  display_name: string;
  roles: string[];
  online: boolean;
  last_seen_at: string | null;
  editing: EditingState | null;
}

export interface JoinApplicationItem {
  id: string;
  username: string;
  display_name: string;
  reason: string;
  status: "pending" | "approved" | "rejected";
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  review_note: string | null;
}

export interface ControlUserFull {
  id: string;
  username: string;
  display_name: string;
  roles: string[];
  is_active: boolean;
}

export interface ControlAsset {
  id: string;
  project_id: string | null;
  task_id: string | null;
  kind: string;
  object_key: string;
  content_sha256: string;
  size_bytes: number;
  content_type: string;
  metadata: Record<string, any>;
  expires_at: string | null;
}

export interface WorkspaceFileEntry {
  name: string;
  path: string;
  size_bytes: number;
  modified_at: number;
  is_dir: boolean;
}

// ---- 注册申请与审批 ----
export function bootstrapAdmin(payload: { username: string; password: string; display_name?: string }) {
  return client.post("/api/control/auth/bootstrap", payload).then((r) => r.data);
}

export function applyJoin(payload: { username: string; password: string; display_name?: string; reason?: string }) {
  return client.post("/api/control/auth/apply", payload).then((r) => r.data as { application_id: string; status: string });
}

export function getApplyStatus(applicationId: string) {
  return client.get(`/api/control/auth/apply/${applicationId}`).then((r) => r.data as { application_id: string; status: string; created_at: string });
}

export function listApplications(status?: string) {
  return client.get("/api/control/admin/applications", { params: status ? { status } : {} }).then((r) => r.data.applications as JoinApplicationItem[]);
}

export function approveApplication(applicationId: string) {
  return client.post(`/api/control/admin/applications/${applicationId}/approve`).then((r) => r.data);
}

export function rejectApplication(applicationId: string, note: string) {
  return client.post(`/api/control/admin/applications/${applicationId}/reject`, { note }).then((r) => r.data);
}

// ---- 成员/角色/在线状态 ----
export function getPresence() {
  return client.get("/api/control/presence").then((r) => r.data as { members: PresenceMember[] });
}

export function listControlUsers() {
  return client.get("/api/control/users").then((r) => r.data.users as ControlUserFull[]);
}

export function listProjectTasks(projectId: string) {
  return client.get(`/api/control/projects/${projectId}/tasks`).then((r) => r.data.tasks as { id: string; status: string; created_at: string; name: string }[]);
}

export function assignControlUserRole(userId: string, role: string) {
  return client.put(`/api/control/users/${userId}/roles`, { role }).then((r) => r.data);
}

// ---- 系统配置与账号 ----
export function getLanMode() {
  return client.get("/api/control/lan-mode").then((r) => r.data as { enabled: boolean; restart_required: boolean });
}

export function setLanMode(enabled: boolean) {
  return client.post("/api/control/lan-mode", { enabled }).then((r) => r.data as { ok: boolean; enabled: boolean; restart_required: boolean });
}

export function getRemoteMode() {
  return client.get("/api/control/remote-mode").then((r) => r.data as { enabled: boolean; restart_required: boolean });
}

export interface CloudflaredStatus {
  installed: boolean;
  running: boolean;
  action: "none" | "started" | "failed" | "install";
  message: string;
}

export function setRemoteMode(enabled: boolean) {
  return client.post("/api/control/remote-mode", { enabled }).then((r) => r.data as {
    ok: boolean;
    enabled: boolean;
    restart_required: boolean;
    cloudflared?: CloudflaredStatus;
  });
}

export function setUserActive(userId: string, isActive: boolean) {
  return client.post(`/api/control/users/${userId}/active`, { is_active: isActive }).then((r) => r.data);
}

export function changeOwnCredentials(payload: { current_password: string; new_username?: string; new_password?: string }) {
  return client.post("/api/control/users/me/credentials", payload).then((r) => r.data);
}

// ---- 项目资产 ----
export function listAssets(projectId: string, kind?: string) {
  return client.get(`/api/control/projects/${projectId}/assets`, { params: kind ? { kind } : {} }).then((r) => r.data.assets as ControlAsset[]);
}

export function assetDownloadUrl(assetId: string) {
  return getApiUrl(`/api/control/assets/${assetId}/download`);
}

export function deleteAsset(assetId: string) {
  return client.delete(`/api/control/assets/${assetId}`).then((r) => r.data);
}

async function sha256Hex(buffer: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function uploadAsset(projectId: string, kind: string, name: string, file: File): Promise<ControlAsset> {
  const buffer = await file.arrayBuffer();
  const digest = await sha256Hex(buffer);
  const form = new FormData();
  form.append("file", new File([buffer], file.name));
  const response = await client.post(`/api/control/projects/${projectId}/assets`, form, {
    params: { kind, name },
    headers: { "X-Content-Sha256": digest, "X-Content-Length": String(file.size) },
  });
  return response.data.asset as ControlAsset;
}

// ---- 任务工作区文件 ----
export function listTaskFiles(projectId: string, taskId: string, path = "") {
  return client.get(`/api/control/projects/${projectId}/tasks/${taskId}/files`, { params: path ? { path } : {} }).then((r) => r.data as { path: string; entries: WorkspaceFileEntry[] });
}

export function taskFileDownloadUrl(projectId: string, taskId: string, path: string) {
  return getApiUrl(`/api/control/projects/${projectId}/tasks/${taskId}/files/download?path=${encodeURIComponent(path)}`);
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

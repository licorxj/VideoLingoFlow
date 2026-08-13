import client from "./client";

/* ---------------------------------------------------------------- */
/* 类型                                                               */
/* ---------------------------------------------------------------- */
export interface CommunityResource {
  id: string;
  type: "node" | "workflow";
  name: string;
  description: string;
  author: string;
  category: string;
  tags: string[];
  version: string;
  sourceId?: string;
  downloads: number;
  likeCount: number;
  liked: boolean;
  /** 云端安全扫描告警（可疑代码模式），空数组表示未发现。 */
  scanWarnings?: string[];
  previewUrl: string;
  createdAt: string;
  updatedAt: string;
  fileNames?: string[];
}

export interface ResourceListResult {
  items: CommunityResource[];
  total: number;
  page: number;
  pageSize: number;
}

export interface PackResult {
  resourceId: string;
  folder: string;
  files: string[];
}

export interface CommunityPackage {
  resourceId: string;
  folder: string;
  name: string;
  type: string;
  createdAt: string;
  files: string[];
}

export interface PublishResult {
  id: string;
  folderKey: string;
  previewUrl: string;
  url: string;
}

/* ---------------------------------------------------------------- */
/* 本地后端                                                           */
/* ---------------------------------------------------------------- */
/**
 * 社区 Worker 地址：构建时通过 VITE_COMMUNITY_API_URL 注入，
 * 分发给用户后无需任何配置（公开 URL，非敏感信息）。
 */
export function getCommunityBaseUrl(): string {
  return (import.meta.env.VITE_COMMUNITY_API_URL || "").trim().replace(/\/+$/, "");
}

export async function packNode(form: FormData): Promise<PackResult> {
  const res = await client.post("/api/community/pack-node", form);
  return res.data;
}

export async function packWorkflow(form: FormData): Promise<PackResult> {
  const res = await client.post("/api/community/pack-workflow", form);
  return res.data;
}

export async function publishPackage(folder: string): Promise<PublishResult> {
  const form = new FormData();
  form.append("folder", folder);
  form.append("baseUrl", getCommunityBaseUrl());
  const res = await client.post("/api/community/publish", form);
  return res.data;
}

/** 列出本地已打包的文件夹（share/community 下）。 */
export async function listPackages(): Promise<CommunityPackage[]> {
  const res = await client.get("/api/community/packages");
  return res.data.packages || [];
}

/* ---------------------------------------------------------------- */
/* 工作流导入（分析 + 安装捆绑节点）                                    */
/* ---------------------------------------------------------------- */
export interface WorkflowNodeAnalysis {
  nodeId: string;
  name: string;
  version: string;
  /** new | upgrade | downgrade | same | different */
  status: string;
  localVersion: string;
  exists: boolean;
  message: string;
}

export interface WorkflowAnalysis {
  workflow: { id: string; name: string; nodeCount: number };
  nodes: WorkflowNodeAnalysis[];
}

export type NodeImportAction = "install" | "rename" | "skip";

export interface WorkflowImportResult {
  workflow: { id: string; name: string };
  installed: { nodeId: string; action: string; newId?: string | null; backupPath?: string | null }[];
  failed: { nodeId: string; error: string }[];
}

/** 预检工作流包：工作流摘要 + 捆绑节点与本地版本对比。 */
export async function analyzeWorkflowPackage(file: File): Promise<WorkflowAnalysis> {
  const form = new FormData();
  form.append("file", file);
  const res = await client.post("/api/community/analyze-workflow-package", form, { timeout: 60000 });
  return res.data;
}

/** 导入工作流：按 decisions 安装捆绑节点并保存为新的全局工作流。 */
export async function importWorkflowPackage(
  file: File,
  name: string,
  decisions: Record<string, { action: NodeImportAction; renameTo?: string }>
): Promise<WorkflowImportResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("name", name);
  form.append("decisions", JSON.stringify(decisions));
  const res = await client.post("/api/community/import-workflow", form, { timeout: 120000 });
  return res.data;
}

/* ---------------------------------------------------------------- */
/* Cloudflare Worker（前端直连）                                       */
/* ---------------------------------------------------------------- */
function workerUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

export interface ResourceListParams {
  type?: string;
  category?: string;
  q?: string;
  page?: number;
  pageSize?: number;
  sort?: "new" | "likes" | "downloads";
  deviceId?: string;
}

export async function listResources(baseUrl: string, params: ResourceListParams): Promise<ResourceListResult> {
  const query = new URLSearchParams();
  if (params.type) query.set("type", params.type);
  if (params.category) query.set("category", params.category);
  if (params.q) query.set("q", params.q);
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("pageSize", String(params.pageSize));
  if (params.sort) query.set("sort", params.sort);
  if (params.deviceId) query.set("deviceId", params.deviceId);
  const res = await fetch(workerUrl(baseUrl, "/api/resources?" + query.toString()));
  if (!res.ok) throw new Error(`社区列表请求失败 (${res.status})`);
  return res.json();
}

export async function getResourceDetail(baseUrl: string, id: string, deviceId: string): Promise<CommunityResource> {
  const res = await fetch(workerUrl(baseUrl, `/api/resources/${id}?deviceId=${encodeURIComponent(deviceId)}`));
  if (!res.ok) throw new Error(`资源详情请求失败 (${res.status})`);
  return res.json();
}

export async function likeResource(baseUrl: string, id: string, deviceId: string): Promise<{ likeCount: number; liked: boolean }> {
  const res = await fetch(workerUrl(baseUrl, `/api/resources/${id}/like`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ deviceId }),
  });
  if (!res.ok) throw new Error(`点赞失败 (${res.status})`);
  return res.json();
}

export async function unlikeResource(baseUrl: string, id: string, deviceId: string): Promise<{ likeCount: number; liked: boolean }> {
  const res = await fetch(workerUrl(baseUrl, `/api/resources/${id}/like`), {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ deviceId }),
  });
  if (!res.ok) throw new Error(`取消点赞失败 (${res.status})`);
  return res.json();
}

/** 下载资源：节点 → ZIP 包；工作流 → ZIP 整包（workflow.json + 捆绑节点）。返回 Blob。 */
export async function downloadResource(baseUrl: string, id: string): Promise<Blob> {
  const res = await fetch(workerUrl(baseUrl, `/api/resources/${id}/download`));
  if (!res.ok) throw new Error(`下载失败 (${res.status})`);
  return res.blob();
}

/* ---------------------------------------------------------------- */
/* 社区用户身份（设置身份注册）+ 管理员登录 + 删除                        */
/* ---------------------------------------------------------------- */
export interface CommunityUser {
  id: string;
  name: string;
  email: string;
  isAdmin: boolean;
  createdAt: string;
}

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const j = await res.json();
    if (j && j.error) return String(j.error);
  } catch {
    /* 忽略 */
  }
  return fallback;
}

/** 注册社区身份：仅做名称重复验证，无重复即注册通过。 */
export async function registerUser(baseUrl: string, name: string, email: string): Promise<CommunityUser> {
  const res = await fetch(workerUrl(baseUrl, "/api/users/register"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email }),
  });
  if (!res.ok) throw new Error(await readError(res, `注册失败 (${res.status})`));
  const j = await res.json();
  return j.user as CommunityUser;
}

/** 管理员登录：校验管理密钥（ADMIN_TOKEN），成功后可执行资源删除。 */
export async function adminLogin(baseUrl: string, adminKey: string): Promise<void> {
  const res = await fetch(workerUrl(baseUrl, "/api/users/admin-login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ adminKey }),
  });
  if (!res.ok) throw new Error(await readError(res, `管理员登录失败 (${res.status})`));
}

/** 管理员删除资源（需 Bearer 管理密钥）。 */
export async function deleteCommunityResource(baseUrl: string, id: string, adminToken: string): Promise<void> {
  const res = await fetch(workerUrl(baseUrl, `/api/admin/resources/${id}`), {
    method: "DELETE",
    headers: { Authorization: `Bearer ${adminToken}` },
  });
  if (!res.ok) throw new Error(await readError(res, `删除失败 (${res.status})`));
}

export function workerPreviewUrl(baseUrl: string, resource: Pick<CommunityResource, "previewUrl">): string {
  return workerUrl(baseUrl, resource.previewUrl);
}

/** 将下载的 Blob 转为 File（供导入流程使用）。 */
export function blobToFile(blob: Blob, filename: string): File {
  return new File([blob], filename, { type: blob.type || "application/octet-stream" });
}

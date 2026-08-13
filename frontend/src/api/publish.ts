/**
 * Publish service API client.
 *
 * Proxies requests to the social-auto-upload backend (port 5409)
 * through our FastAPI backend (/api/publish/*).
 */
import client from "./client";

const BASE = "/api/publish";

// ═══════════════════════════════════════════
// Platforms
// ═══════════════════════════════════════════

export async function listPlatforms() {
  const res = await client.get(`${BASE}/platforms`);
  return res.data;
}

// ═══════════════════════════════════════════
// Accounts
// ═══════════════════════════════════════════

export async function listAccounts(type?: string) {
  const res = await client.get(`${BASE}/accounts`, { params: type ? { type } : {} });
  return res.data;
}

export async function listAllAccounts() {
  const res = await client.get(`${BASE}/accounts/all`);
  return res.data;
}

export async function listValidAccounts() {
  const res = await client.get(`${BASE}/accounts/valid`);
  return res.data;
}

export async function checkAccount(accountId: string) {
  const res = await client.get(`${BASE}/accounts/${accountId}/check`);
  return res.data;
}

export async function deleteAccount(accountId: string) {
  const res = await client.get(`${BASE}/accounts/${accountId}/delete`);
  return res.data;
}

export async function syncProfile(accountId: string) {
  const res = await client.post(`${BASE}/accounts/${accountId}/sync`);
  return res.data;
}

// ═══════════════════════════════════════════
// Tags
// ═══════════════════════════════════════════

export async function listTags() {
  const res = await client.get(`${BASE}/tags`);
  return res.data;
}

export async function createTag(name: string, color?: string) {
  const res = await client.post(`${BASE}/tags`, { name, color });
  return res.data;
}

export async function deleteTag(tagId: number) {
  const res = await client.delete(`${BASE}/tags/${tagId}`);
  return res.data;
}

export async function getAccountTags(accountId: number) {
  const res = await client.get(`${BASE}/accounts/${accountId}/tags`);
  return res.data;
}

export async function setAccountTags(accountId: number, tagIds: number[]) {
  const res = await client.put(`${BASE}/accounts/${accountId}/tags`, { tag_ids: tagIds });
  return res.data;
}

export async function batchSetAccountTags(accountIds: number[], tagIds: number[]) {
  const res = await client.put(`${BASE}/accounts/batch/tags`, {
    account_ids: accountIds,
    tag_ids: tagIds,
  });
  return res.data;
}

// ═══════════════════════════════════════════
// Video Publishing
// ═══════════════════════════════════════════

export interface PublishVideoParams {
  type: number;
  title: string;
  file_paths: string[];
  account_id?: string;
  account_list?: string[];
  description?: string;
  tags?: string[];
  thumbnail?: string;
  thumbnail_landscape?: string;
  thumbnail_portrait?: string;
  is_draft?: boolean;
  schedule_time?: string;
  is_original?: boolean;
  audience?: string;
  ai_content?: string;
  hotspot?: string;
  mix_id?: string;
}

export async function publishVideo(params: PublishVideoParams) {
  const res = await client.post(`${BASE}/video`, params);
  return res.data;
}

// ═══════════════════════════════════════════
// Materials
// ═══════════════════════════════════════════

export async function uploadMaterial(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await client.post(`${BASE}/materials/upload`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 300000,
  });
  return res.data;
}

export async function listMaterials(params?: {
  type?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}) {
  const res = await client.get(`${BASE}/materials`, { params });
  return res.data;
}

export async function getMaterial(materialId: string) {
  const res = await client.get(`${BASE}/materials/${materialId}`);
  return res.data;
}

export async function deleteMaterial(materialId: string) {
  const res = await client.delete(`${BASE}/materials/${materialId}`);
  return res.data;
}

export async function probeMaterial(materialId: string) {
  const res = await client.post(`${BASE}/materials/${materialId}/probe`);
  return res.data;
}

// ═══════════════════════════════════════════
// Drafts
// ═══════════════════════════════════════════

export async function listDrafts(type: string = "video") {
  const res = await client.get(`${BASE}/drafts`, { params: { type } });
  return res.data;
}

export async function createDraft(type: string = "video", draftData: Record<string, any> = {}) {
  const res = await client.post(`${BASE}/draft`, { type, draft_data: draftData });
  return res.data;
}

export async function getDraft(draftId: string) {
  const res = await client.get(`${BASE}/drafts/${draftId}`);
  return res.data;
}

export async function updateDraft(draftId: string, draftData: Record<string, any>) {
  const res = await client.put(`${BASE}/drafts/${draftId}`, { draft_data: draftData });
  return res.data;
}

export async function deleteDraft(draftId: string) {
  const res = await client.delete(`${BASE}/drafts/${draftId}`);
  return res.data;
}

export async function batchPublishDrafts(draftIds: number[]) {
  const res = await client.post(`${BASE}/drafts/batch-publish`, { draft_ids: draftIds });
  return res.data;
}

export async function batchDeleteDrafts(draftIds: number[]) {
  const res = await client.delete(`${BASE}/drafts/batch`, { data: { draft_ids: draftIds } });
  return res.data;
}

// ═══════════════════════════════════════════
// Tasks
// ═══════════════════════════════════════════

export async function listTasks(params?: {
  status?: string;
  page?: number;
  page_size?: number;
}) {
  const res = await client.get(`${BASE}/tasks`, { params });
  return res.data;
}

export async function getTaskStatus(taskId: string) {
  const res = await client.get(`${BASE}/tasks/${taskId}`);
  return res.data;
}

export async function cancelTask(taskId: string) {
  const res = await client.post(`${BASE}/tasks/${taskId}/cancel`);
  return res.data;
}

export async function retryTask(taskId: string) {
  const res = await client.post(`${BASE}/tasks/${taskId}/retry`);
  return res.data;
}

// ═══════════════════════════════════════════
// History & Stats
// ═══════════════════════════════════════════

export async function getPublishStats() {
  const res = await client.get(`${BASE}/stats`);
  return res.data;
}

export async function getQueueStatus() {
  const res = await client.get(`${BASE}/queue`);
  return res.data;
}

export async function getPublishHistory(params?: {
  platform?: string;
  status?: string;
  time_range?: string;
  page?: number;
  page_size?: number;
}) {
  const res = await client.get(`${BASE}/history`, { params });
  return res.data;
}

export async function getHistoryDetail(batchId: string) {
  const res = await client.get(`${BASE}/history/${batchId}`);
  return res.data;
}

export async function deleteHistory(batchId: string) {
  const res = await client.delete(`${BASE}/history/${batchId}`);
  return res.data;
}

export async function batchDeleteHistory(batchIds: string[]) {
  const res = await client.delete(`${BASE}/history/batch`, { data: { batch_ids: batchIds } });
  return res.data;
}

// ═══════════════════════════════════════════
// Settings
// ═══════════════════════════════════════════

export async function getSettings() {
  const res = await client.get(`${BASE}/settings`);
  return res.data;
}

export async function updateSettings(settings: Record<string, any>) {
  const res = await client.put(`${BASE}/settings`, settings);
  return res.data;
}

// ═══════════════════════════════════════════
// Templates
// ═══════════════════════════════════════════

export async function getPublishTemplates(type: string = "video") {
  const res = await client.get(`${BASE}/templates`, { params: { type } });
  return res.data;
}

// ═══════════════════════════════════════════
// Health & System
// ═══════════════════════════════════════════

export async function checkHealth() {
  const res = await client.get(`${BASE}/health`);
  return res.data;
}

export async function getSystemInfo() {
  const res = await client.get(`${BASE}/system-info`);
  return res.data;
}

export async function clearCache() {
  const res = await client.post(`${BASE}/cache/clear`);
  return res.data;
}

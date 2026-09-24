import client from "./client";

export type FileTransitItem = {
  id: string;
  name: string;
  file_type: string;
  file_type_label: string;
  task_name: string;
  path: string;
  task_id: string;
  seq: number;
  created_at: string;
};

export type FileTransitQuery = {
  file_type?: string;
  keyword?: string;
  order?: string;
  limit?: number;
  offset?: number;
};

export const FILE_TRANSIT_TYPES = [
  { value: "all", label: "全部类型" },
  { value: "video", label: "视频" },
  { value: "audio", label: "音频" },
  { value: "image", label: "图片" },
  { value: "text", label: "文本" },
  { value: "other", label: "其它" },
];

export const FILE_TRANSIT_ORDERS = [
  { value: "latest", label: "最新入库" },
  { value: "oldest", label: "最旧入库" },
  { value: "index", label: "排序序号" },
  { value: "name", label: "文件名称" },
];

/** 中转站文件预览/下游取用地址：相对路径需带 task_id 才能按任务工作区解析。 */
export function transitFileUrl(path: string, taskId?: string): string {
  const params = new URLSearchParams({ path });
  if (taskId) params.set("task_id", taskId);
  return `/api/files/stream?${params.toString()}`;
}

export const fileTransitApi = {
  items: (params: FileTransitQuery = {}) =>
    client.get<{ items: FileTransitItem[]; total: number }>("/api/file-transit/items", { params }),

  /** 按规则预演取件结果（供卡片显示「将取到」） */
  pick: (params: { file_type?: string; keyword?: string; order?: string; index?: number; path?: string } = {}) =>
    client.get<{ item: FileTransitItem | null }>("/api/file-transit/pick", { params }),

  /** 移除登记（只删记录，不动磁盘文件） */
  remove: (id: string) => client.delete(`/api/file-transit/items/${id}`),
};

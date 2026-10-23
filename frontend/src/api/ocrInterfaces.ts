import client from "./client";

/**
 * 各引擎字段不同（RapidOCR 用 engine_type/ocr_version/...，Indra OCR 用
 * model_dir/threads/dpi/...），故统一用松散字典承载，key 说明见 backend/config/ocr_interfaces.json。
 */
export type OCRInterfaceConfig = Record<string, any>;

export interface OCRInterface {
  id: string;
  name: string;
  type: "sdk";
  builtin: boolean;
  enabled: boolean;
  description: string;
  config: OCRInterfaceConfig;
}

export interface OCRTestResult {
  success: boolean;
  txts: string[];
  scores: number[];
  elapse: number;
  box_count: number;
}

export interface OCRDeps {
  rapidocr: boolean;
  indra_ocr: boolean;
  onnxruntime: boolean;
  torch: boolean;
  paddle: boolean;
}

export interface OCRConfigFields {
  engine_options: Array<{ value: string; label: string; description: string }>;
  sizes_by_version: Record<string, string[]>;
  lang_options: Array<{ value: string; label: string }>;
  indra_mode_options?: Array<{ value: string; label: string }>;
}

export const ocrInterfacesApi = {
  list: () => client.get("/api/ocr-interfaces"),
  getEnabled: () => client.get("/api/ocr-interfaces/enabled"),
  get: (id: string) => client.get(`/api/ocr-interfaces/${id}`),
  create: (data: Partial<OCRInterface>) =>
    client.post("/api/ocr-interfaces", data),
  update: (id: string, data: Partial<OCRInterface>) =>
    client.put(`/api/ocr-interfaces/${id}`, data),
  delete: (id: string) => client.delete(`/api/ocr-interfaces/${id}`),
  toggle: (id: string, enabled: boolean) =>
    client.post(`/api/ocr-interfaces/${id}/toggle?enabled=${enabled}`),
  reload: () => client.post("/api/ocr-interfaces/reload"),
  checkDeps: () => client.get("/api/ocr-interfaces/check-deps"),
  configFields: () => client.get("/api/ocr-interfaces/config-fields"),
  uploadImage: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return client.post("/api/ocr-interfaces/upload-image", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  test: (id: string, data: { image_path: string }) =>
    client.post(`/api/ocr-interfaces/${id}/test`, data),
};

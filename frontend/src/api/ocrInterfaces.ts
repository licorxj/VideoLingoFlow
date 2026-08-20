import client from "./client";

export interface OCRInterfaceConfig {
  sdk_module?: string;
  sdk_class?: string;
  engine_type: string;
  ocr_version: string;
  model_type: string;
  custom_model_name: string;
  lang_type: string;
  use_cuda: boolean;
  device_id: number;
  use_det: boolean;
  use_cls: boolean;
  use_rec: boolean;
  text_score: number;
  box_thresh: number;
  unclip_ratio: number;
  limit_side_len: number;
  threads: number;
  return_word_box: boolean;
  max_workers: number;
  timeout: number;
}

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
  onnxruntime: boolean;
  torch: boolean;
  paddle: boolean;
}

export interface OCRConfigFields {
  engine_options: Array<{ value: string; label: string; description: string }>;
  sizes_by_version: Record<string, string[]>;
  lang_options: Array<{ value: string; label: string }>;
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

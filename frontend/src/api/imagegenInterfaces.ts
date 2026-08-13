import client from "./client";

export interface ImageGenModeConfig {
  enabled: boolean;
  endpoint: string;
}

export interface ImageGenModesMap {
  txt2img?: ImageGenModeConfig;
  img2img?: ImageGenModeConfig;
}

export interface ImageGenModelMeta {
  modes?: string[];           // e.g. ["t2i", "i2i"]
  price?: string;             // e.g. "¥0.04/张"
  resolutions?: string[];     // e.g. ["1K", "2K", "4K"]
  aspect_ratios?: string[];   // e.g. ["16:9", "9:16", "4:3", "3:4", "1:1"]
}

export interface ImageGenInterfaceConfig {
  api_url?: string;
  api_key?: string;
  sdk_package?: string;
  sdk_module?: string;
  sdk_function?: string;
  sdk_api_key?: string;
  sdk_extra_args?: Record<string, string>;
  default_model?: string;
  model_options?: string[];
  model_metadata?: Record<string, ImageGenModelMeta>;
  model_list_url?: string;
  model_list_key?: string;
  balance_endpoint?: string;
  modes?: ImageGenModesMap;
  max_concurrent?: number;
  timeout?: number;
  custom_params?: Array<{ key: string; default: string; description: string }>;
}

export interface ImageGenInterface {
  id: string;
  name: string;
  type: "sdk" | "openai_compatible";
  builtin: boolean;
  enabled: boolean;
  description: string;
  api_source_url?: string;
  model_docs_url?: string;
  balance?: number | string | null;
  config: ImageGenInterfaceConfig;
}

export interface ImageGenTestResult {
  success: boolean;
  images?: string[];
  output_dir?: string;
  count?: number;
}

export const imagegenInterfacesApi = {
  list: () => client.get("/api/imagegen-interfaces/"),
  getEnabled: () => client.get("/api/imagegen-interfaces/enabled"),
  get: (id: string) => client.get(`/api/imagegen-interfaces/${id}`),
  create: (data: Partial<ImageGenInterface>) =>
    client.post("/api/imagegen-interfaces/", data),
  update: (id: string, data: Partial<ImageGenInterface>) =>
    client.put(`/api/imagegen-interfaces/${id}`, data),
  delete: (id: string) => client.delete(`/api/imagegen-interfaces/${id}`),
  toggle: (id: string, enabled: boolean) =>
    client.post(`/api/imagegen-interfaces/${id}/toggle`, { enabled }),
  reload: () => client.post("/api/imagegen-interfaces/reload"),
  test: (id: string, data: {
    prompt?: string;
    negative_prompt?: string;
    resolution?: string;
    aspect_ratio?: string;
    num_images?: number;
    ref_images?: string[];
    model?: string;
    mode?: string;
  }) => client.post(`/api/imagegen-interfaces/${id}/test`, data),
  getModels: (id: string) =>
    client.get(`/api/imagegen-interfaces/${id}/models`),
  addModel: (id: string, model_name: string, modes?: string[], price?: string, resolutions?: string[], aspect_ratios?: string[]) =>
    client.post(`/api/imagegen-interfaces/${id}/models`, { model_name, modes: modes || ["t2i", "i2i"], price: price || "", resolutions: resolutions || [], aspect_ratios: aspect_ratios || [] }),
  removeModel: (id: string, model_name: string) =>
    client.delete(`/api/imagegen-interfaces/${id}/models/${model_name}`),
  fetchModels: (id: string) =>
    client.post(`/api/imagegen-interfaces/${id}/fetch-models`),
  refreshBalance: (id: string) =>
    client.post(`/api/imagegen-interfaces/${id}/refresh-balance`),
};

import client from "./client";

export interface OpenChatCutLlmConfig {
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
}

export interface OpenChatCutImageConfig {
  base_url: string;
  api_key: string;
  /** 旧的单模型字段，仅作兼容回退 */
  model: string;
  /** 无参考图（文生图）时使用的模型 */
  txt2img_model: string;
  /** 有参考图（图生图）时使用的模型 */
  img2img_model: string;
  interface_id: string;
}

export interface OpenChatCutTtsConfig {
  base_url: string;
  api_key: string;
  model: string;
  interface_id: string;
}

export interface OpenChatCutVideoConfig {
  base_url: string;
  api_key: string;
  model: string;
}

export interface OpenChatCutConfig {
  enabled: boolean;
  host: string;
  port: number;
  llm: OpenChatCutLlmConfig;
  image: OpenChatCutImageConfig;
  tts: OpenChatCutTtsConfig;
  video: OpenChatCutVideoConfig;
  mcp: { token: string };
  agent_import_roots: string;
  media_dir: string;
}

export interface OpenChatCutImageOption {
  id: string;
  name: string;
  txt2img_models: string[];
  img2img_models: string[];
}

export interface OpenChatCutTtsOption {
  id: string;
  name: string;
  models: string[];
  voices: string[];
  modes: string[];
}

export interface OpenChatCutStatus {
  repo: boolean;
  deps: boolean;
  /** 前端构建产物（dist/index.html）已就绪：启动时走生产模式，否则回退 dev server */
  build?: boolean;
  /** 本机 Node.js 检测：剪辑台依赖 Node 24.x，缺失时前端提醒安装 */
  node_ok?: boolean;
  /** Node 版本字符串（如 v24.12.0），探测失败为 null */
  node_version?: string | null;
  /** 后台依赖安装进行中 */
  installing?: boolean;
  env_file: boolean;
  env_mtime: number;
  port: number;
  running: boolean;
  editor_url: string;
  direct_url: string;
  mcp_url: string;
}

export interface OpenChatCutInstallStatus {
  running: boolean;
  success: boolean | null;
  exit_code: number | null;
  started_at: number | null;
  finished_at: number | null;
  log: string[];
}

export interface OpenChatCutProjectInfo {
  name: string;
  upstream: string;
  website: string;
  license: string;
  version_hint: string;
  notice: string;
  disclaimer: string;
}

export const openchatcutApi = {
  getConfig: () => client.get<{ config: OpenChatCutConfig }>("/api/openchatcut/config"),
  updateConfig: (values: Record<string, unknown>) =>
    client.put<{ config: OpenChatCutConfig; env_keys: string[] }>("/api/openchatcut/config", values),
  applyEnv: () => client.post<{ env_keys: string[] }>("/api/openchatcut/apply-env"),
  envPreview: () =>
    client.get<{ env: Record<string, string>; env_file: string; env_exists: boolean }>("/api/openchatcut/env-preview"),
  status: () => client.get<OpenChatCutStatus>("/api/openchatcut/status"),
  install: (force = false) =>
    client.post<{ started: boolean; already_running?: boolean; error?: string; message?: string }>(
      "/api/openchatcut/install",
      { force },
    ),
  installStatus: () => client.get<OpenChatCutInstallStatus>("/api/openchatcut/install-status"),
  imageOptions: () =>
    client.get<{ interfaces: OpenChatCutImageOption[] }>("/api/openchatcut/options/image"),
  ttsOptions: () =>
    client.get<{ interfaces: OpenChatCutTtsOption[] }>("/api/openchatcut/options/tts"),
  editorUrl: () => client.get<{ url: string; direct_url: string; running: boolean }>("/api/openchatcut/editor-url"),
  projectInfo: () => client.get<OpenChatCutProjectInfo>("/api/openchatcut/project-info"),
};

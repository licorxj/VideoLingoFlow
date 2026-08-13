interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  /** 共享社区 Worker 地址（构建时注入，分发给用户后无需再配置）。 */
  readonly VITE_COMMUNITY_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

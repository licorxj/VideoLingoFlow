import client from "./client";

export interface LocalVersion {
  version: string;
  api_version?: string;
  software_id?: string;
}

export const publicInfoApi = {
  /** 本地版本（不访问云端，页面启动时可无感调用） */
  getVersion: () => client.get("/api/public-info/version").then((r) => r.data as LocalVersion),
};

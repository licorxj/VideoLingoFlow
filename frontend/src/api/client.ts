import axios, { AxiosError } from "axios";
import { apiBaseUrl } from "./baseUrl";

export type ApiError = Error & {
  status?: number;
  code?: string;
  details?: unknown;
};

export function normalizeApiError(error: unknown): ApiError {
  if (!axios.isAxiosError(error)) {
    const message = error instanceof Error ? error.message : "请求失败";
    return Object.assign(new Error(message), { details: error });
  }

  const response = error.response;
  const detail = response?.data?.detail;
  const payload = detail && typeof detail === "object" ? detail as Record<string, unknown> : response?.data;
  const message = typeof detail === "string"
    ? detail
    : typeof payload?.message === "string"
      ? payload.message
      : response ? "请求失败" : "网络连接失败";

  return Object.assign(new Error(message), {
    status: response?.status,
    code: typeof payload?.code === "string" ? payload.code : undefined,
    details: detail,
  });
}

const client = axios.create({
  baseURL: apiBaseUrl || "/",
  timeout: 30000,
  withCredentials: true,
});

client.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => Promise.reject(normalizeApiError(error)),
);

export default client;

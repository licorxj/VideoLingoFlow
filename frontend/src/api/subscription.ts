import client from "./client";

export type UserType = "guest" | "registered" | "subscribed";

export interface UserInfo {
  id?: string | number;
  user_id?: string | number;
  username?: string;
  email?: string;
  phone?: string;
  nickname?: string;
  is_active?: boolean;
  created_at?: string;
  last_login?: string;
  [key: string]: any;
}

export interface Entitlement {
  id?: string | number;
  software_id?: string;
  softwareId?: string;
  software_code?: string;
  softwareCode?: string;
  status?: string;
  state?: string;
  valid_until?: string;
  validUntil?: string;
  expire_at?: string;
  expires_at?: string;
  device_limit?: number;
  bound_device_count?: number;
  boundDeviceCount?: number;
  remaining_points?: number;
  points?: number;
  total_points?: number;
  quota_remaining?: number;
  balance?: number;
  last_granted_at?: string;
  [key: string]: any;
}

export interface SubscriptionLinks {
  products: string;
  home: string;
  versions: string;
}

export interface SubscriptionStatus {
  software_id: string;
  is_logged_in: boolean;
  user_type: UserType;
  user_info: UserInfo | null;
  entitlements: Entitlement[];
  active_entitlement: Entitlement | null;
  daily_usage: number;
  daily_limit: number | null;
  remaining_today: number | null;
  can_create_task: boolean;
  daily_node_usage?: number;
  daily_node_limit?: number | null;
  remaining_nodes_today?: number | null;
  can_execute_node?: boolean;
  links: SubscriptionLinks;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface RegisterPayload {
  username: string;
  password: string;
  email: string;
  phone?: string;
  verification_code?: string;
}

export interface ResetPasswordPayload {
  email: string;
  code: string;
  new_password: string;
}

export function getSubscriptionError(error: any) {
  return error?.response?.data?.detail || error?.response?.data?.message || error?.message || "操作失败";
}

export function isDeviceLimitError(error: any) {
  const text = String(getSubscriptionError(error) || "");
  return text.includes("1205") || text.includes("设备数量已超过限制") || text.includes("设备超限");
}

export function isSubscriptionBlocked(error: any) {
  const status = error?.status ?? error?.response?.status;
  return status === 402 || status === 403;
}

export function getQuotaExhaustedMessage(status: SubscriptionStatus | null) {
  if (!status) return "额度不足，请前往“用户和订阅”页面查看详情。";
  if (status.user_type === "guest") {
    return "游客你好，你的每日免费额度已经用完，请注册获取更多免费额度，或者明日再来！感谢您的使用和支持！";
  }
  return "尊敬的注册用户你好，温馨提示您的免费额度或订阅时长已用完，请订阅已获得更多使用时长。";
}

export const subscriptionApi = {
  getStatus: () => client.get("/api/subscription/status").then((r) => r.data as SubscriptionStatus),
  refresh: () => client.post("/api/subscription/refresh").then((r) => r.data as SubscriptionStatus),
  login: (data: LoginPayload) => client.post("/api/subscription/login", data).then((r) => r.data as SubscriptionStatus),
  logout: () => client.post("/api/subscription/logout").then((r) => r.data),
  unbindDevice: () => client.post("/api/subscription/unbind-device").then((r) => r.data as SubscriptionStatus),
  register: (data: RegisterPayload) => client.post("/api/subscription/register", data).then((r) => r.data),
  sendCode: (email: string) => client.post("/api/subscription/send-code", { email }).then((r) => r.data),
  sendResetCode: (email: string) => client.post("/api/subscription/reset-password/send-code", { email }).then((r) => r.data),
  resetPassword: (data: ResetPasswordPayload) => client.post("/api/subscription/reset-password/confirm", data).then((r) => r.data),
  verifyCard: (card_code: string) => client.post("/api/subscription/verify-card", { card_code }).then((r) => r.data as SubscriptionStatus),
  getLinks: () => client.get("/api/subscription/links").then((r) => r.data as SubscriptionLinks),
};

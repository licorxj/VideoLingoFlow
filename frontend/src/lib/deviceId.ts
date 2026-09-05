/** 社区点赞身份：设备 UUID（localStorage 持久化，一次生成）。 */
const KEY = "vl_community_device_id";

export function getDeviceId(): string {
  try {
    let id = localStorage.getItem(KEY);
    if (!id) {
      id =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : "dev-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
      localStorage.setItem(KEY, id);
    }
    return id;
  } catch {
    return "unknown-device";
  }
}

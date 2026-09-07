const MANAGER_BASE = "http://localhost:18001";

export const managerApi = {
  restartControlPlaneWorker: () =>
    fetch(`${MANAGER_BASE}/manager/restart-control-plane-worker`, { method: "POST" }).then(
      async (res) => {
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || data.message || `重启请求失败 (${res.status})`);
        }
        return res.json();
      },
    ),
};

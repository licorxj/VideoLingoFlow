import client from "./client";

export const aigcApi = {
  // 读取完整配置（含默认值合并）
  getConfig: () => client.get("/api/aigc/config"),
  // 更新某个 provider 的子配置
  updateConfig: (provider: string, values: Record<string, any>) =>
    client.put("/api/aigc/config", { provider, values }),
  // 探测三项能力的可用性状态
  status: () => client.get("/api/aigc/status"),
  // 测试 ComfyUI 连通性
  testComfyui: () => client.post("/api/aigc/comfyui/test", {}),
  // 测试 RunningHub 配置
  testRunninghub: () => client.post("/api/aigc/runninghub/test", {}),
  // 查询即梦 CLI 版本
  jimengVersion: () => client.post("/api/aigc/jimeng/version", {}),
};

# GPU 服务能力

> 本文档描述可选的本地 GPU lane 服务。它只处理当前已接入的 ASR 与人声/音轨分离任务，不是通用 GPU 执行器。

## 启用与配置

- Manager 仅在 `GPU_SERVICE_ENABLED` 为真值时启动 `backend.gpu_service.manager`。
- Windows 本地配置入口为 `.runtime/local_env.bat`。安装器可按 NVIDIA 显存写入建议值；设置 `GPU_SERVICE_AUTO_CONFIG=0` 后保留人工配置。
- 关键变量：`GPU_SERVICE_REDIS_URL`、`GPU_SERVICE_MAX_LANES`、`GPU_SERVICE_LANE_IDLE_TIMEOUT`、`GPU_SERVICE_VRAM_HEADROOM_GB`、`GPU_SERVICE_JOB_TIMEOUT`。

## 调度边界

- 服务通过 Redis 队列和 lane 子进程复用已加载模型；达到 lane 上限或剩余显存低于预留值时任务继续等待。
- lane 空闲超过 `GPU_SERVICE_LANE_IDLE_TIMEOUT` 后退出以释放显存。
- `GET /api/gpu-service/status` 用于检查启用状态、Redis、lane 和显存信息。
- Redis 或服务不可用时，ASR 与分离节点会回退原有执行路径；排障时不要只根据 GPU 服务未启动断定任务必然失败。

# 本地运行时覆盖目录

此目录只保存当前机器的运行时覆盖配置，不进入发布包的数据内容。

- `local_env.bat`：从 `local_env.bat.template` 复制生成；默认 `VIDEOLINGO_LAN_MODE=0`，API 和 Manager 仅监听 `127.0.0.1`。
- 开启局域网共享时将 `VIDEOLINGO_LAN_MODE=1`，重启 Manager 后 API 与 Manager 监听 `0.0.0.0`。
- LAN 模式没有认证、TLS、项目隔离或下载授权，只能用于可信局域网。
- 可选 `VITE_API_BASE_URL=http://<主机IP>:11001` 用于前端与 API 不同源的部署；未设置时前端使用当前页面的同源 API 和 WebSocket 地址。

实际运行数据应保持在 `data/`、`_model_cache/` 和 `logs/`，不要写入本目录。

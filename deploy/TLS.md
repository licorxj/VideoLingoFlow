# TLS 部署策略

生产和局域网部署均由 `proxy` 终止 TLS。仅允许 TLS 1.2 和 TLS 1.3；Compose 不发布 API、PostgreSQL、Redis 或 MinIO 端口到宿主机。

将受信任的服务器证书链放在 `deploy/tls/fullchain.pem`，私钥放在 `deploy/tls/privkey.pem`，两者只读装载到 Nginx。证书和私钥不得提交到版本库；使用企业内部 CA 时，将 CA 签发的服务证书链装载到同一证书路径，并把 CA 根证书分发到客户端信任库。

复制 `deploy/.env.example` 为 `.env` 后替换所有密码、证书路径和镜像标识。密码通过部署平台的 secret 注入；不得写入 Compose 文件、日志或镜像层。

代理没有 HTTP 监听，也没有明文回退。缺少证书、私钥或任一依赖健康状态时，`proxy` 不会启动，API readiness 也不会通过。

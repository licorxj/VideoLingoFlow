# 集群基线

1. 复制 `deploy/.env.example` 为 `.env` 并填写随机密码。
2. 准备 `deploy/tls/fullchain.pem` 和 `deploy/tls/privkey.pem`，具体策略见 `deploy/TLS.md`。
3. 构建应用镜像：`docker compose -f deploy/docker-compose.yml --env-file .env build api`。
4. 启动控制平面依赖：`docker compose -f deploy/docker-compose.yml --env-file .env up -d postgres redis minio`。
5. 执行版本化迁移：`docker compose -f deploy/docker-compose.yml --env-file .env run --rm --no-deps api alembic upgrade head`。
6. 启动 API、worker 和反向代理：`docker compose -f deploy/docker-compose.yml --env-file .env up -d api worker proxy`。
7. 通过 `https://<host>/api/health/live` 检查进程存活，通过 `https://<host>/api/health/ready` 检查 PostgreSQL schema、Redis、MinIO 和 worker 就绪状态。

数据库 schema 的唯一初始化和升级入口为 `docker compose -f deploy/docker-compose.yml --env-file .env run --rm --no-deps api alembic upgrade head`。该命令仅迁移控制平面 PostgreSQL schema；API 启动时保留 VoiceForge 本地兼容数据库初始化。

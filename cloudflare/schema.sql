-- 共享社区 D1 数据库 Schema
-- 初始化：npx wrangler d1 execute videolingo-community-db --file schema.sql --remote

CREATE TABLE IF NOT EXISTS resources (
  id          TEXT PRIMARY KEY,              -- 资源唯一 ID
  type        TEXT NOT NULL,                 -- 'node' | 'workflow'
  name        TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  author      TEXT NOT NULL DEFAULT '',
  category    TEXT NOT NULL DEFAULT '',
  tags        TEXT NOT NULL DEFAULT '[]',    -- JSON 数组字符串
  version     TEXT NOT NULL DEFAULT '1.0.0',
  source_id   TEXT NOT NULL DEFAULT '',      -- 节点 id 或工作流 id
  folder_key  TEXT NOT NULL,                 -- nodes/{id} 或 workflows/{id}
  downloads   INTEGER NOT NULL DEFAULT 0,
  scan_flags  TEXT NOT NULL DEFAULT '[]',    -- 云端安全扫描告警（JSON 数组字符串）
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resources_list ON resources(type, category, created_at DESC);

CREATE TABLE IF NOT EXISTS likes (
  resource_id TEXT NOT NULL,
  user_key    TEXT NOT NULL,                 -- 前端设备 UUID
  created_at  TEXT NOT NULL,
  PRIMARY KEY (resource_id, user_key)
);

-- 社区用户（设置身份注册）：名称唯一，仅做名称重复验证
CREATE TABLE IF NOT EXISTS users (
  id         TEXT PRIMARY KEY,               -- 用户唯一 ID
  name       TEXT NOT NULL UNIQUE,           -- 名称（唯一）
  email      TEXT NOT NULL DEFAULT '',       -- 邮箱
  is_admin   INTEGER NOT NULL DEFAULT 0,     -- 是否管理员（保留字段）
  created_at TEXT NOT NULL
);

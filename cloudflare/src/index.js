/**
 * VideoLingo 共享社区 Worker
 *
 * 依赖绑定：
 *   - COMMUNITY_BUCKET (R2) : 存储资源文件夹（nodes/{id}/... 或 workflows/{id}/...）
 *   - DB (D1)              : resources / likes 表
 *   - ADMIN_TOKEN (Secret) : 治理删除接口（DELETE /api/admin/resources/:id）的 Bearer 令牌，
 *                            通过 `npx wrangler secret put ADMIN_TOKEN` 设置，不写入代码/配置。
 *
 * 接口说明：
 *   - 浏览 / 点赞 / 下载 / 公开发布（POST /api/resources）为公开接口，软件分发无需任何配置
 *   - 发布接口内置大小限制与按 IP 限频，防止滥用
 *
 * 部署：
 *   cd cloudflare && npm install
 *   npx wrangler d1 execute videolingo-community-db --file schema.sql --remote
 *   npx wrangler deploy
 *   npx wrangler secret put ADMIN_TOKEN   # 可选：仅治理删除需要
 */
import { zipSync, strToU8 } from "fflate";

const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,DELETE,PUT,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Access-Control-Max-Age": "86400",
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS_HEADERS, ...JSON_HEADERS },
  });
}

function fail(status, code, message) {
  return json({ error: message, code }, status);
}

function unauthorized() {
  return fail(401, "unauthorized", "Invalid or missing admin token");
}

function notFound() {
  return fail(404, "not_found", "Resource not found");
}

function previewUrl(type, id) {
  return `/preview/${type}/${id}/preview.png`;
}

function safeParseTags(raw) {
  try {
    const v = JSON.parse(raw || "[]");
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

async function countLikes(env, id) {
  const res = await env.DB.prepare(
    "SELECT COUNT(*) AS c FROM likes WHERE resource_id = ?"
  ).bind(id).first();
  return res ? res.c : 0;
}

async function getResource(env, id) {
  return await env.DB.prepare("SELECT * FROM resources WHERE id = ?").bind(id).first();
}

async function rowToItem(env, row, deviceId = "") {
  const likeCount = row.like_count != null ? row.like_count : await countLikes(env, row.id);
  let liked = false;
  if (deviceId) {
    const res = await env.DB.prepare(
      "SELECT 1 AS x FROM likes WHERE resource_id = ? AND user_key = ?"
    ).bind(row.id, deviceId).first();
    liked = !!res;
  }
  return {
    id: row.id,
    type: row.type,
    name: row.name,
    description: row.description,
    author: row.author,
    category: row.category,
    tags: safeParseTags(row.tags),
    version: row.version,
    sourceId: row.source_id,
    downloads: row.downloads,
    likeCount,
    liked,
    scanWarnings: safeParseTags(row.scan_flags),
    previewUrl: previewUrl(row.type, row.id),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

/* ---------------------------------------------------------------- */
/* 列表                                                               */
/* ---------------------------------------------------------------- */
async function handleList(env, url) {
  const type = (url.searchParams.get("type") || "").trim();
  const category = (url.searchParams.get("category") || "").trim();
  const q = (url.searchParams.get("q") || "").trim();
  const deviceId = (url.searchParams.get("deviceId") || "").trim();
  const sort = (url.searchParams.get("sort") || "new").trim();
  const page = Math.max(1, parseInt(url.searchParams.get("page") || "1", 10) || 1);
  const pageSize = Math.min(50, Math.max(1, parseInt(url.searchParams.get("pageSize") || "12", 10) || 12));
  const offset = (page - 1) * pageSize;

  const where = [];
  const binds = [];
  if (type === "node" || type === "workflow") {
    where.push("r.type = ?");
    binds.push(type);
  }
  if (category) {
    where.push("r.category = ?");
    binds.push(category);
  }
  if (q) {
    where.push("(r.name LIKE ? OR r.description LIKE ? OR r.author LIKE ?)");
    binds.push(`%${q}%`, `%${q}%`, `%${q}%`);
  }
  const whereSql = where.length ? "WHERE " + where.join(" AND ") : "";

  let order = "r.created_at DESC";
  if (sort === "likes") order = "like_count DESC, r.created_at DESC";
  else if (sort === "downloads") order = "r.downloads DESC, r.created_at DESC";

  const countRow = await env.DB.prepare(
    `SELECT COUNT(*) AS c FROM resources r ${whereSql}`
  ).bind(...binds).first();
  const total = countRow ? countRow.c : 0;

  const rows = await env.DB.prepare(
    `SELECT r.*,
            (SELECT COUNT(*) FROM likes l WHERE l.resource_id = r.id) AS like_count,
            (CASE WHEN ? = '' THEN 0
                  ELSE (SELECT COUNT(*) FROM likes l2
                        WHERE l2.resource_id = r.id AND l2.user_key = ?)
             END) AS liked
     FROM resources r ${whereSql}
     ORDER BY ${order} LIMIT ? OFFSET ?`
  ).bind(deviceId, deviceId, ...binds, pageSize, offset).all();

  const items = [];
  for (const row of rows.results) {
    items.push(await rowToItem(env, row, deviceId));
  }
  return json({ items, total, page, pageSize });
}

/* ---------------------------------------------------------------- */
/* 详情                                                               */
/* ---------------------------------------------------------------- */
async function handleDetail(env, id, deviceId) {
  const row = await getResource(env, id);
  if (!row) return notFound();
  const item = await rowToItem(env, row, deviceId);
  try {
    const list = await env.COMMUNITY_BUCKET.list({ prefix: row.folder_key + "/" });
    item.fileNames = list.objects
      .map((o) => o.key.slice(row.folder_key.length + 1))
      .filter((k) => k && !k.endsWith("/"));
  } catch {
    item.fileNames = [];
  }
  return json(item);
}

/* ---------------------------------------------------------------- */
/* 下载                                                               */
/* ---------------------------------------------------------------- */
async function handleDownload(env, id) {
  const row = await getResource(env, id);
  if (!row) return notFound();

  try {
    await env.DB.prepare("UPDATE resources SET downloads = downloads + 1 WHERE id = ?").bind(id).run();
  } catch {
    /* 计数尽力而为 */
  }

  const prefix = row.folder_key + "/";
  const list = await env.COMMUNITY_BUCKET.list({ prefix });

  if (row.type === "node") {
    // 现场打包为与本地导出一致的 ZIP（node_config.json + share_meta.json + 代码文件）
    const files = {};
    for (const obj of list.objects) {
      if (obj.key.endsWith("/")) continue;
      const rel = obj.key.slice(prefix.length);
      const r2obj = await env.COMMUNITY_BUCKET.get(obj.key);
      if (!r2obj) continue;
      files[rel] = new Uint8Array(await r2obj.arrayBuffer());
    }
    if (!files["node_config.json"]) {
      return fail(404, "missing_node_config", "Node package missing node_config.json");
    }
    const shareMeta = {
      shareName: row.name,
      description: row.description,
      nodeId: row.source_id,
      version: row.version,
      schemaVersion: "1.0",
      author: row.author,
      sourceUrl: "",
      tags: safeParseTags(row.tags),
      exportedAt: row.created_at,
    };
    files["share_meta.json"] = strToU8(JSON.stringify(shareMeta, null, 2));
    const zipped = zipSync(files);
    const safeName = (row.name || "node").replace(/[^\w\u4e00-\u9fa5-]+/g, "_");
    return new Response(new Blob([zipped], { type: "application/zip" }), {
      status: 200,
      headers: {
        ...CORS_HEADERS,
        "Content-Type": "application/zip",
        "Content-Disposition": `attachment; filename="node_${safeName}_${row.source_id || row.id}.zip"`,
      },
    });
  }

  // workflow：打包 workflow.json + 捆绑的自定义节点（nodes/**），便于下载方一键补齐
  const wfFiles = {};
  for (const obj of list.objects) {
    if (obj.key.endsWith("/")) continue;
    const rel = obj.key.slice(prefix.length);
    if (rel === "resource.json" || rel === "preview.png") continue;
    const r2obj = await env.COMMUNITY_BUCKET.get(obj.key);
    if (!r2obj) continue;
    wfFiles[rel] = new Uint8Array(await r2obj.arrayBuffer());
  }
  if (!wfFiles["workflow.json"]) {
    return fail(404, "missing_workflow", "Workflow file missing");
  }
  const wfZip = zipSync(wfFiles);
  const wfSafeName = (row.name || "workflow").replace(/[^\w\u4e00-\u9fa5-]+/g, "_");
  return new Response(new Blob([wfZip], { type: "application/zip" }), {
    status: 200,
    headers: {
      ...CORS_HEADERS,
      "Content-Type": "application/zip",
      "Content-Disposition": `attachment; filename="workflow_${wfSafeName}.zip"`,
    },
  });
}

/* ---------------------------------------------------------------- */
/* 点赞 / 取消点赞                                                     */
/* ---------------------------------------------------------------- */
async function handleLike(env, id, request, method) {
  const row = await getResource(env, id);
  if (!row) return notFound();

  let deviceId = "";
  try {
    const body = await request.json();
    deviceId = String((body && body.deviceId) || "").trim();
  } catch {
    /* 忽略 */
  }
  if (!deviceId) return fail(400, "bad_request", "deviceId required");

  const now = new Date().toISOString();
  if (method === "POST") {
    await env.DB.prepare(
      "INSERT OR IGNORE INTO likes (resource_id, user_key, created_at) VALUES (?, ?, ?)"
    ).bind(id, deviceId, now).run();
    return json({ likeCount: await countLikes(env, id), liked: true });
  }
  await env.DB.prepare(
    "DELETE FROM likes WHERE resource_id = ? AND user_key = ?"
  ).bind(id, deviceId).run();
  return json({ likeCount: await countLikes(env, id), liked: false });
}

/* ---------------------------------------------------------------- */
/* 安全扫描：上传内容结构校验 + 恶意特征检测                            */
/* ---------------------------------------------------------------- */
// 硬性恶意特征：命中直接拒绝上传（正常代码几乎不会出现）
const HARD_BLOCK_PATTERNS = [
  [/__import__\s*\(\s*['"](?:os|sys|subprocess)['"]/, "动态导入执行"],
  [/eval\s*\(\s*compile\s*\(/, "eval(compile) 代码混淆"],
  [/(?:b64decode|decodebytes)\s*\([^)]*\)[\s\S]{0,80}?(?:exec|eval|system|Popen|subprocess)/, "Base64 混淆执行"],
  [/socket\s*\.\s*socket\s*\([\s\S]{0,200}?\.(?:connect|connect_ex|bind)\s*\(/, "反向连接/远程控制"],
  [/\b(?:xmrig|minergate|cryptonight|coinhive|nicehash)\b/, "挖矿程序"],
  [/\b(?:curl|wget)\b[^\n]*\|\s*(?:sudo\s+)?(?:bash|sh|\/bin\/sh)\b/, "curl|sh 管道执行"],
  [/\b(powershell|pwsh)\b[^\n]*\b(?:iex|Invoke-Expression|EncodedCommand|-enc)\b/i, "PowerShell 混淆执行"],
  [/\bpty\.spawn\s*\(/, "伪终端反弹 Shell"],
];

// 可疑特征：正常代码也可能出现，仅标记警告（导入前客户端提示）
const SOFT_WARNING_PATTERNS = [
  [/\b(?:os\.system|os\.popen|os\.exec[lv]?|os\.spawn)\b/, "系统命令执行"],
  [/\bsubprocess\b/, "子进程调用"],
  [/\beval\s*\(/, "eval 动态执行"],
  [/\bexec\s*\(/, "exec 动态执行"],
  [/\bsocket\b/, "网络套接字"],
  [/\b(?:requests|urllib)\./, "网络请求"],
  [/\bpickle\.(?:loads|load)\b/, "反序列化"],
  [/\b(?:shutil\.rmtree|os\.(?:remove|unlink|rmdir|removedirs))\b/, "删除文件/目录"],
];

// 二进制文件不扫描文本特征
const BINARY_EXTS = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp",
  ".zip", ".gz", ".tar", ".rar", ".7z",
  ".mp4", ".mp3", ".wav", ".flac", ".ogg", ".webm",
  ".pdf", ".exe", ".dll", ".so", ".bin", ".db", ".sqlite", ".woff", ".woff2", ".ttf", ".otf",
]);

function isTextFile(name) {
  const idx = name.lastIndexOf(".");
  const ext = idx >= 0 ? name.slice(idx).toLowerCase() : "";
  return !BINARY_EXTS.has(ext);
}

function scanText(text, filename, result) {
  for (const [re, label] of HARD_BLOCK_PATTERNS) {
    if (re.test(text)) result.blocked.push(`${label}（${filename}）`);
  }
  for (const [re, label] of SOFT_WARNING_PATTERNS) {
    if (re.test(text)) result.warnings.push(`${label}（${filename}）`);
  }
}

function scanBuffer(buf, filename, result) {
  if (!isTextFile(filename)) return;
  const slice = buf.slice(0, 512 * 1024);
  const text = new TextDecoder("utf-8", { fatal: false }).decode(slice);
  scanText(text, filename, result);
}

const MAX_WORKFLOW_NODES = 200;

function validateWorkflowStructure(text) {
  let wf;
  try {
    wf = JSON.parse(text);
  } catch {
    return "workflow.json 不是有效的 JSON";
  }
  if (!wf || typeof wf !== "object") return "workflow.json 结构无效";
  const nodes = Array.isArray(wf.nodes) ? wf.nodes : [];
  const edges = Array.isArray(wf.edges) ? wf.edges : [];
  if (nodes.length > MAX_WORKFLOW_NODES) return `工作流节点数超过上限（${MAX_WORKFLOW_NODES}）`;
  for (const n of nodes) {
    if (!n || typeof n.id !== "string" || !(n.data && typeof n.data.nodeType === "string")) {
      return "工作流包含无效节点（缺少 id 或 nodeType）";
    }
  }
  for (const e of edges) {
    if (!e || typeof e.source !== "string" || typeof e.target !== "string") {
      return "工作流包含无效连线";
    }
  }
  return "";
}

const ALLOWED_EXEC_TYPES = new Set(["", "python", "shell", "llm"]);

function validateNodeStructure(text) {
  let cfg;
  try {
    cfg = JSON.parse(text);
  } catch {
    return "node_config.json 不是有效的 JSON";
  }
  if (!cfg || typeof cfg !== "object") return "node_config.json 结构无效";
  if (!cfg.id || typeof cfg.id !== "string") return "节点缺少 id";
  if (!cfg.name || typeof cfg.name !== "string") return "节点缺少 name";
  const execType = String(cfg.execType ?? "");
  if (!ALLOWED_EXEC_TYPES.has(execType)) return `非法的执行类型: ${execType}`;
  return "";
}

/* ---------------------------------------------------------------- */
/* 管理：上传（公开发布，内置防滥用 + 安全检查）                         */
/* ---------------------------------------------------------------- */
// 防滥用：大小限制 + 尽力而为的按 IP 限频（多个 isolate 间不共享，仅作威慑）
const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20MB
const MAX_BODY_SIZE = 50 * 1024 * 1024; // 50MB
const MAX_FILES = 200;
const UPLOAD_LIMIT = 10;
const UPLOAD_WINDOW_MS = 10 * 60 * 1000;
const uploadAttempts = new Map();

function rateLimited(ip) {
  if (!ip) return false;
  const now = Date.now();
  const arr = (uploadAttempts.get(ip) || []).filter((t) => now - t < UPLOAD_WINDOW_MS);
  if (arr.length >= UPLOAD_LIMIT) {
    uploadAttempts.set(ip, arr);
    return true;
  }
  arr.push(now);
  uploadAttempts.set(ip, arr);
  return false;
}

async function handleUpload(env, request) {
  const ip = request.headers.get("CF-Connecting-IP") || "";
  if (rateLimited(ip)) {
    return fail(429, "rate_limited", "上传过于频繁，请稍后再试");
  }

  const clen = Number(request.headers.get("Content-Length") || 0);
  if (clen > MAX_BODY_SIZE) {
    return fail(413, "too_large", "上传内容过大（超过 50MB）");
  }

  let form;
  try {
    form = await request.formData();
  } catch {
    return fail(400, "bad_request", "Expected multipart form data");
  }

  const type = String(form.get("type") || "").trim();
  if (type !== "node" && type !== "workflow") {
    return fail(400, "bad_request", "type must be 'node' or 'workflow'");
  }
  const name = String(form.get("name") || "").trim();
  if (!name) return fail(400, "bad_request", "name required");
  const description = String(form.get("description") || "").trim();
  const author = String(form.get("author") || "").trim();
  const category = String(form.get("category") || "").trim();
  const version = String(form.get("version") || "1.0.0").trim();
  const sourceId = String(form.get("sourceId") || "").trim();
  let tags = [];
  try {
    const v = JSON.parse(String(form.get("tags") || "[]"));
    tags = Array.isArray(v) ? v.map(String) : [];
  } catch {
    tags = [];
  }

  const preview = form.get("preview");
  const files = form.getAll("files").filter((f) => f && typeof f !== "string");

  if (files.length > MAX_FILES) {
    return fail(413, "too_large", "文件数量过多（超过 50 个）");
  }
  for (const f of files) {
    if (f.size > MAX_FILE_SIZE) {
      return fail(413, "too_large", `单个文件过大（超过 20MB）: ${f.name}`);
    }
  }

  const id = crypto.randomUUID();
  const folderKey = `${type}/${id}`;
  const now = new Date().toISOString();

  // 读取所有内容文件到内存（受 MAX_BODY_SIZE 50MB 约束），随后统一扫描
  const entries = [];
  for (const f of files) {
    const fname = String(f.name || "").replace(/\\/g, "/");
    if (!fname || fname.startsWith("/") || fname.split("/").includes("..")) continue;
    entries.push({ name: fname, type: f.type || "application/octet-stream", buf: await f.arrayBuffer() });
  }

  // 安全检查：结构校验 + 恶意特征扫描
  const scan = { blocked: [], warnings: [] };
  if (type === "workflow") {
    const wfEntry = entries.find((e) => e.name === "workflow.json");
    if (!wfEntry) return fail(400, "bad_request", "工作流包缺少 workflow.json");
    const err = validateWorkflowStructure(new TextDecoder().decode(wfEntry.buf));
    if (err) return fail(400, "scan_blocked", err);
    // 捆绑的自定义节点（nodes/{id}/node_config.json）同样做结构校验
    for (const e of entries) {
      const m = e.name.match(/^nodes\/[^/]+\/node_config\.json$/);
      if (!m) continue;
      const nerr = validateNodeStructure(new TextDecoder().decode(e.buf));
      if (nerr) return fail(400, "scan_blocked", nerr);
    }
  } else {
    const cfgEntry = entries.find((e) => e.name === "node_config.json");
    if (!cfgEntry) return fail(400, "bad_request", "节点包缺少 node_config.json");
    const err = validateNodeStructure(new TextDecoder().decode(cfgEntry.buf));
    if (err) return fail(400, "scan_blocked", err);
  }
  for (const e of entries) scanBuffer(e.buf, e.name, scan);
  if (scan.blocked.length > 0) {
    return fail(400, "scan_blocked", "检测到恶意代码特征，已拒绝上传：" + scan.blocked.join("；"));
  }

  // 写入内容文件
  for (const e of entries) {
    await env.COMMUNITY_BUCKET.put(`${folderKey}/${e.name}`, e.buf, {
      httpMetadata: { contentType: e.type },
    });
  }

  // 预览图
  if (preview && typeof preview !== "string") {
    await env.COMMUNITY_BUCKET.put(`${folderKey}/preview.png`, preview.stream(), {
      httpMetadata: { contentType: preview.type || "image/png" },
    });
  }

  // 介绍文件（含扫描告警，供客户端导入前提示）
  const resource = {
    type, name, description, author, category, tags,
    version, sourceId, resourceId: id,
    scanWarnings: scan.warnings,
    createdAt: now, updatedAt: now,
  };
  await env.COMMUNITY_BUCKET.put(`${folderKey}/resource.json`, JSON.stringify(resource, null, 2), {
    httpMetadata: { contentType: "application/json" },
  });

  await env.DB.prepare(
    `INSERT INTO resources
       (id, type, name, description, author, category, tags, version, source_id, folder_key, downloads, scan_flags, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)`
  ).bind(
    id, type, name, description, author, category,
    JSON.stringify(tags), version, sourceId, folderKey,
    JSON.stringify(scan.warnings), now, now,
  ).run();

  return json({ id, folderKey, previewUrl: previewUrl(type, id), scanWarnings: scan.warnings }, 201);
}

/* ---------------------------------------------------------------- */
/* 管理：删除                                                          */
/* ---------------------------------------------------------------- */
async function handleAdminDelete(env, id, request) {
  if ((request.headers.get("Authorization") || "").trim() !== `Bearer ${env.ADMIN_TOKEN}`) {
    return unauthorized();
  }
  const row = await getResource(env, id);
  if (!row) return notFound();

  await env.DB.prepare("DELETE FROM likes WHERE resource_id = ?").bind(id).run();
  await env.DB.prepare("DELETE FROM resources WHERE id = ?").bind(id).run();

  try {
    const list = await env.COMMUNITY_BUCKET.list({ prefix: row.folder_key + "/" });
    await Promise.all(list.objects.map((o) => env.COMMUNITY_BUCKET.delete(o.key)));
  } catch {
    /* 忽略清理错误 */
  }
  return json({ ok: true });
}

/* ---------------------------------------------------------------- */
/* 用户：注册身份（名称唯一，仅做名称重复验证）                           */
/* ---------------------------------------------------------------- */
async function handleRegister(env, request) {
  const ip = request.headers.get("CF-Connecting-IP") || "";
  if (rateLimited(ip)) {
    return fail(429, "rate_limited", "操作过于频繁，请稍后再试");
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return fail(400, "bad_request", "Invalid JSON body");
  }
  const name = String((body && body.name) || "").trim();
  const email = String((body && body.email) || "").trim();

  if (!name) return fail(400, "bad_request", "名称不能为空");
  if (name.length > 32) return fail(400, "bad_request", "名称过长（最多 32 个字符）");
  if (email.length > 64) return fail(400, "bad_request", "邮箱过长（最多 64 个字符）");
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return fail(400, "bad_request", "邮箱格式不正确");
  }

  // 仅做名称重复验证：重名则拒绝，无重复即注册通过
  const dup = await env.DB.prepare("SELECT 1 AS x FROM users WHERE name = ?").bind(name).first();
  if (dup) {
    return fail(409, "name_taken", `名称「${name}」已被注册，请更换后再试`);
  }

  const id = crypto.randomUUID();
  const now = new Date().toISOString();
  try {
    await env.DB.prepare(
      "INSERT INTO users (id, name, email, is_admin, created_at) VALUES (?, ?, ?, 0, ?)"
    ).bind(id, name, email, now).run();
  } catch (e) {
    // UNIQUE 冲突兜底（并发注册同名）
    return fail(409, "name_taken", `名称「${name}」已被注册，请更换后再试`);
  }
  return json({ user: { id, name, email, isAdmin: false, createdAt: now } }, 201);
}

/* ---------------------------------------------------------------- */
/* 管理员登录：校验 ADMIN_TOKEN（wrangler secret 设置），仅本人可用        */
/* ---------------------------------------------------------------- */
async function handleAdminLogin(env, request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return fail(400, "bad_request", "Invalid JSON body");
  }
  const adminKey = String((body && body.adminKey) || "").trim();
  if (!adminKey) return fail(400, "bad_request", "管理密钥不能为空");
  if (adminKey !== (env.ADMIN_TOKEN || "")) return unauthorized();
  return json({ admin: true, message: "管理员登录成功" });
}

/* ---------------------------------------------------------------- */
/* 预览图                                                             */
/* ---------------------------------------------------------------- */
async function handlePreview(env, type, id) {
  if (type !== "node" && type !== "workflow") return notFound();
  const obj = await env.COMMUNITY_BUCKET.get(`${type}/${id}/preview.png`);
  if (!obj) return notFound();
  const headers = new Headers(CORS_HEADERS);
  headers.set("Content-Type", "image/png");
  headers.set("Cache-Control", "public, max-age=3600");
  return new Response(obj.body, { headers });
}

/* ---------------------------------------------------------------- */
/* 入口                                                               */
/* ---------------------------------------------------------------- */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    if (method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    if (method === "GET" && path === "/api/health") {
      return json({ ok: true, service: "videolingo-community" });
    }

    if (method === "GET" && path === "/api/resources") {
      return handleList(env, url);
    }

    // /api/resources/:id/like  (POST/DELETE)
    let m = path.match(/^\/api\/resources\/([^/]+)\/like$/);
    if (m && (method === "POST" || method === "DELETE")) {
      return handleLike(env, m[1], request, method);
    }

    // /api/resources/:id/download
    m = path.match(/^\/api\/resources\/([^/]+)\/download$/);
    if (m && method === "GET") {
      return handleDownload(env, m[1]);
    }

    // /api/resources/:id
    m = path.match(/^\/api\/resources\/([^/]+)$/);
    if (m && method === "GET") {
      return handleDetail(env, m[1], url.searchParams.get("deviceId") || "");
    }

    // /api/resources（公开发布，内置大小限制与限频防滥用）
    if (path === "/api/resources" && method === "POST") {
      return handleUpload(env, request);
    }

    // /api/users/register（设置身份：名称唯一，无重复即通过）
    if (path === "/api/users/register" && method === "POST") {
      return handleRegister(env, request);
    }

    // /api/users/admin-login（管理员登录：校验 ADMIN_TOKEN）
    if (path === "/api/users/admin-login" && method === "POST") {
      return handleAdminLogin(env, request);
    }

    // /api/admin/resources/:id（治理删除，需 ADMIN_TOKEN，通过 wrangler secret 设置）
    m = path.match(/^\/api\/admin\/resources\/([^/]+)$/);
    if (m && method === "DELETE") {
      return handleAdminDelete(env, m[1], request);
    }

    // /preview/:type/:id/preview.png
    m = path.match(/^\/preview\/(node|workflow)\/([^/]+)\/preview\.png$/);
    if (m && method === "GET") {
      return handlePreview(env, m[1], m[2]);
    }

    return fail(404, "not_found", "Not found");
  },
};

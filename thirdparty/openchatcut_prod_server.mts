/**
 * OpenChatCut 生产模式启动器（主项目进程管理器调用；不修改上游源码）
 *
 * 复用上游官方的 Electron 内嵌生产服务 desktop/embedded-server.ts：
 *   node:http + serverPlugins（/api、/llm、MCP 等全部服务端能力）
 *   + dist/ 静态产物（构建产物直接对外服务，不再走 vite dev server）
 *
 * 用法:
 *   tsx openchatcut_prod_server.mts <openchatcut 目录绝对路径>
 * 例:
 *   tsx thirdparty/openchatcut_prod_server.mts y:/VideoLingoLc/thirdparty/openchatcut
 */

import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const argDir = process.argv[2];
const occDir = resolve(argDir || new URL('./openchatcut', import.meta.url).pathname);

// 上游内部多处按 process.cwd() 解析 .env.local / data dir，须先切到项目目录
process.chdir(occDir);

const distDir = resolve(occDir, 'dist');
const mod = await import(pathToFileURL(resolve(occDir, 'desktop/embedded-server.ts')).href);
const server = await mod.startEmbeddedServer(distDir);
const port = server?.port ?? 5199;
console.log(`[openchatcut-prod] ready: http://127.0.0.1:${port} (dist=${distDir})`);

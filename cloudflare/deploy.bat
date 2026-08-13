@echo off
chcp 65001 >nul
REM ============================================================
REM  VideoLingo 共享社区 Worker 一键部署脚本
REM  前置条件：
REM    1. 已安装 Node.js 18+ 与 npm
REM    2. 已在 Cloudflare 控制台创建 R2 桶 videolingo-community
REM       与 D1 数据库 videolingo-community-db
REM    3. 已把 wrangler.toml 中的 database_id 填写完整
REM    4. 已执行 npx wrangler login 完成认证
REM
REM  敏感信息说明（软件分发场景）：
REM    管理令牌 ADMIN_TOKEN 通过 Cloudflare Secret 加密存储，
REM    不写入 wrangler.toml / 不随软件分发，仅用于治理删除，可选设置。
REM ============================================================
cd /d "%~dp0"

echo [1/3] 安装依赖 (npm install) ...
call npm install || goto :fail

echo [2/3] 初始化 D1 表结构 ...
call npx wrangler d1 execute videolingo-community-db --file schema.sql --remote || goto :fail

echo [3/3] 部署 Worker ...
call npx wrangler deploy || goto :fail

echo.
echo 可选：设置治理删除令牌（加密保存在 Cloudflare，不写入任何文件）
set /p SET_SECRET="是否设置 ADMIN_TOKEN？(y/n) "
if /i "%SET_SECRET%"=="y" (
  call npx wrangler secret put ADMIN_TOKEN || goto :fail
)

echo.
echo 部署完成！最后在构建前端时注入社区地址：
echo   在 frontend\.env 中写入： VITE_COMMUNITY_API_URL=https://videolingo-community.<你的子域>.workers.dev
echo   然后重新构建 frontend（npm run build），分发给用户即可直接使用，无需任何配置。
pause
exit /b 0

:fail
echo.
echo [错误] 部署失败，请检查上方输出。
pause
exit /b 1

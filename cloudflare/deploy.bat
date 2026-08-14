@echo off
REM ============================================================
REM  VideoLingo Community Worker deploy script
REM  Prerequisites:
REM    1. Node.js 18+ and npm installed
REM    2. R2 bucket "videolingo-community" created on Cloudflare dashboard
REM    3. D1 database "videolingo-community-db" created
REM    4. database_id filled in wrangler.toml
REM    5. Run "npx wrangler login" for authentication
REM
REM  Sensitive info (distribution note):
REM    ADMIN_TOKEN is stored encrypted via Cloudflare Secrets,
REM    never written to wrangler.toml or shipped with the software.
REM    It is optional, only used for moderation/deletion.
REM ============================================================
cd /d "%~dp0"

echo [1/3] Installing dependencies (npm install) ...
call npm install || goto :fail

echo [2/3] Initializing D1 schema ...
call npx wrangler d1 execute videolingo-community-db --file schema.sql --remote || goto :fail

echo [3/3] Deploying Worker ...
call npx wrangler deploy || goto :fail

echo.
echo Optional: set moderation deletion token (stored encrypted in Cloudflare, not written to any file)
set /p SET_SECRET="Set ADMIN_TOKEN? (y/n) "
if /i "%SET_SECRET%"=="y" (
  call npx wrangler secret put ADMIN_TOKEN || goto :fail
)

echo.
echo Deployment done! Finally, inject the community URL when building the frontend:
echo   In frontend\.env write: VITE_COMMUNITY_API_URL=https://videolingo-community.<your-subdomain>.workers.dev
echo   Then rebuild frontend (npm run build) and distribute - users can use it directly.
pause
exit /b 0

:fail
echo.
echo [ERROR] Deploy failed, please check the output above.
pause
exit /b 1

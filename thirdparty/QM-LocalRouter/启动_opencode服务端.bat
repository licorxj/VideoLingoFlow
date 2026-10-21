@echo off
chcp 65001 >nul
title OpenCode Serve (port 4096)
echo ================================================
echo  启动 OpenCode 本地服务端  http://127.0.0.1:4096
echo  （10001 端口常被小米电脑管家等软件占用，故用 4096）
echo ================================================
start "opencode-serve" /min cmd /c "opencode serve --port 4096 --hostname 127.0.0.1"
echo 等待服务端就绪...
powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 20;$i++){ Start-Sleep 1; try{ $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:4096/global/health -TimeoutSec 2; if($r.Content -match 'healthy'){ echo $r.Content; $ok=$true; break } }catch{} }; if(-not $ok){ echo '服务端未就绪，请检查 opencode 是否已安装' }"
echo.
echo 启动完成，本窗口可关闭（opencode-serve 窗口请保持运行）。
pause

@echo off
REM RapidOCR 桌面 exe 一键启动（无界面后台服务）
cd /d "%~dp0dist\RapidOCR桌面工具"
if not exist "RapidOCR桌面工具.exe" (
  echo [ERROR] 未找到 exe，请先执行 build_exe.bat 重新打包。
  pause
  exit /b 1
)

echo 正在启动 RapidOCR 桌面服务（无界面，属正常现象）...
start "" "RapidOCR桌面工具.exe"

echo.
echo 稍候 2~5 秒，浏览器会自动打开：http://127.0.0.1:8003/
echo 若未自动打开，请手动在浏览器访问：http://127.0.0.1:8003/
echo.
echo 验证是否在运行：浏览器访问 http://127.0.0.1:8003/api/healthz ，返回 200 即正常。
echo 停止服务请用「停止exe.bat」，或任务管理器结束 RapidOCR桌面工具.exe。
echo.
echo 注意：点 X 关掉浏览器【不会】停止服务，服务仍在后台运行并占用 8003 端口。
pause

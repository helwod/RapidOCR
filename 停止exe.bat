@echo off
REM RapidOCR 桌面 exe 一键停止
echo 正在停止 RapidOCR 桌面服务（RapidOCR桌面工具.exe）...
taskkill /f /im "RapidOCR桌面工具.exe" >nul 2>&1
if errorlevel 1 (
  echo 未发现运行中的 RapidOCR 服务（可能本来就没启动）。
) else (
  echo 已停止，服务已关闭，8003 端口已释放。
)
echo.
echo 提示：停止后再次双击 exe 即可重新启动；请务必先停止旧实例，
echo       否则新实例会因 8003 端口被占用而自动改用 8004、8005…端口。
pause

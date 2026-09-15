@echo off
REM 打包 RapidOCR 工作台为 Windows 单目录桌面应用
REM 产物：dist\RapidOCR桌面工具\RapidOCR桌面工具.exe（含 185MB 模型）
REM 首次构建较慢（2-5 分钟），之后增量构建更快

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] 未找到 .venv\Scripts\python.exe
  pause & exit /b 1
)

echo [1/2] 清理旧构建...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [2/2] PyInstaller 构建中（请耐心等待）...
.venv\Scripts\python.exe -m PyInstaller RapidOCR.spec --noconfirm
if errorlevel 1 (
  echo.
  echo [ERROR] 构建失败，查看上方报错
  pause & exit /b 1
)

echo.
echo ============================================================
echo  构建完成！
echo  产物目录：%CD%\dist\RapidOCR桌面工具\
echo  启动程序：%CD%\dist\RapidOCR桌面工具\RapidOCR桌面工具.exe
echo  双击 exe 即可启动（自动开浏览器，错误在同目录 rapidocr_app.log）
echo ============================================================
pause
endlocal

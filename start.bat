@echo off
REM RapidOCR 可视化校对工作台 —— Windows 一键启动
REM 启动后会自动打开浏览器（设 RAPIDOCR_NO_BROWSER=1 可关闭）

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] 未找到 .venv\Scripts\python.exe，请先创建虚拟环境并安装依赖：
  echo         py -3.13 -m venv .venv
  echo         .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

REM 启动服务（app.py 会在 1.5 秒后自动打开默认浏览器）
.venv\Scripts\python.exe app.py
if errorlevel 1 (
  echo.
  echo [ERROR] 服务异常退出，查看上方报错。
  pause
)
endlocal

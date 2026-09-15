# -*- coding: utf-8 -*-
"""启动已打包的 RapidOCR 桌面 exe（无界面后台服务，自动开浏览器）。

等价原 启动exe.bat：启动 dist/RapidOCR桌面工具/RapidOCR桌面工具.exe，
并脱离本脚本独立运行（关掉本窗口不影响服务）。
用法：
    .venv/Scripts/python.exe launch_exe.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
EXE_DIR = os.path.join(ROOT, "dist", "RapidOCR桌面工具")
EXE = os.path.join(EXE_DIR, "RapidOCR桌面工具.exe")


def main() -> int:
    if not os.path.isfile(EXE):
        print("[ERROR] 未找到 exe，请先执行 build_exe.py 重新打包。")
        return 1

    print("正在启动 RapidOCR 桌面服务（无界面，属正常现象）...")
    # DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP：脱离父进程，本脚本退出后服务仍在后台运行
    subprocess.Popen(
        [EXE],
        cwd=EXE_DIR,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        | getattr(subprocess, "DETACHED_PROCESS", 0),
    )

    print("\n稍候 2~5 秒，浏览器会自动打开：http://127.0.0.1:8003/")
    print("若未自动打开，请手动在浏览器访问：http://127.0.0.1:8003/")
    print("验证：访问 http://127.0.0.1:8003/api/healthz ，返回 200 即正常。")
    print("停止服务请用 stop_exe.py，或任务管理器结束 RapidOCR桌面工具.exe。")
    print("注意：点 X 关掉浏览器【不会】停止服务，服务仍在后台运行并占用 8003 端口。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

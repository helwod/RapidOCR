# -*- coding: utf-8 -*-
"""停止正在运行的 RapidOCR 桌面 exe。

等价原 停止exe.bat：结束 RapidOCR桌面工具.exe 进程，释放 8003 端口。
用法：
    .venv/Scripts/python.exe stop_exe.py
"""
import subprocess
import sys

EXE_NAME = "RapidOCR桌面工具.exe"


def main() -> int:
    rc = subprocess.call(
        ["taskkill", "/f", "/im", EXE_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if rc != 0:
        print("未发现运行中的 RapidOCR 服务（可能本来就没启动）。")
    else:
        print("已停止，服务已关闭，8003 端口已释放。")
    print("提示：停止后再次双击 exe 即可重新启动；请务必先停止旧实例，")
    print("      否则新实例会因 8003 端口被占用而自动改用 8004、8005…端口。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

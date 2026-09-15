# -*- coding: utf-8 -*-
"""把 RapidOCR 工作台打包为 Windows 单目录桌面应用。

等价原 build_exe.bat：调用 PyInstaller 走 RapidOCR.spec。
用法（在仓库根目录执行）：
    .venv/Scripts/python.exe build_exe.py
产物：dist/RapidOCR桌面工具/RapidOCR桌面工具.exe
"""
import os
import sys
import shutil
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")


def _pause_if_interactive():
    # 双击运行时给个停顿，避免窗口一闪而过；管道/CI 下不阻塞。
    if sys.stdin.isatty():
        try:
            input("\n按回车退出...")
        except Exception:
            pass


def main() -> int:
    if not os.path.isfile(VENV_PY):
        print("[ERROR] 未找到 .venv/Scripts/python.exe，请先按 README 创建虚拟环境并安装依赖。")
        _pause_if_interactive()
        return 1

    print("[1/2] 清理旧构建...")
    for d in ("build", "dist"):
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            shutil.rmtree(p)

    print("[2/2] PyInstaller 构建中（请耐心等待，首次 2-5 分钟）...")
    rc = subprocess.call([VENV_PY, "-m", "PyInstaller", "RapidOCR.spec", "--noconfirm"], cwd=ROOT)
    if rc != 0:
        print("\n[ERROR] 构建失败，查看上方报错。")
        _pause_if_interactive()
        return rc

    exe = os.path.join(ROOT, "dist", "RapidOCR桌面工具", "RapidOCR桌面工具.exe")
    print("\n============================================================")
    print("  构建完成！")
    print("  产物目录：%s" % os.path.join(ROOT, "dist", "RapidOCR桌面工具"))
    print("  启动程序：%s" % exe)
    print("  双击 exe 即可启动（自动开浏览器，错误在同目录 rapidocr_app.log）")
    print("============================================================")
    _pause_if_interactive()
    return 0


if __name__ == "__main__":
    sys.exit(main())

# PyInstaller 运行时钩子：在任意用户代码（含 app.py 的 import）执行之前安装全局异常钩子，
# 把未捕获异常写入 exe 同目录的 crash.log，并弹出对话框，
# 避免"窗口一闪而过 / 毫无提示"式的静默启动失败，便于排查。
import os
import sys
import traceback
from datetime import datetime


def _show_box(msg: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "RapidOCR 启动错误", 0x10)
    except Exception:
        pass


def _hook(exc_type, exc, tb) -> None:
    # SystemExit / KeyboardInterrupt 不弹窗（正常退出 / 手动中断）
    if exc_type in (SystemExit, KeyboardInterrupt):
        return
    try:
        base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
        path = os.path.join(base, "crash.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n=== crash @ %s ===\n" % datetime.now().isoformat(timespec="seconds"))
            traceback.print_exception(exc_type, exc, tb, file=f)
        _show_box(
            "RapidOCR 启动失败，错误信息已写入：\n%s\n\n"
            "请查看该文件，或联系技术支持。" % path
        )
    except Exception:
        pass


sys.excepthook = _hook

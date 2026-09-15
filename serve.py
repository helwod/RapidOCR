# -*- coding: utf-8 -*-
"""从源码启动 RapidOCR 工作台（开发 / 二次开发用）。

等价原 start.bat：用本项目 .venv 里的 Python 运行 app.py。
用法：
    .venv/Scripts/python.exe serve.py            # 默认 127.0.0.1:8003 并自动开浏览器
    .venv/Scripts/python.exe serve.py --server   # 无界面后台服务模式
    .venv/Scripts/python.exe serve.py --host 0.0.0.0 --port 8130
其余参数会原样透传给 app.py。
"""
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
APP = os.path.join(ROOT, "app.py")


def main() -> int:
    if not os.path.isfile(VENV_PY):
        print("[ERROR] 未找到 .venv/Scripts/python.exe，请先按 README 创建虚拟环境并安装依赖。")
        return 1
    args = [VENV_PY, APP] + sys.argv[1:]
    return subprocess.call(args, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())

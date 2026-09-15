# -*- coding: utf-8 -*-
"""把 dist/RapidOCR桌面工具 打包成可分发的 zip（用于 GitHub Release）。

排除运行期残留：日志、store.json、settings.json、static/cache/*
保留 models/*.onnx —— 使压缩包解压即用，无需联网下载 OCR 模型。
"""
import os
import sys
import zipfile

SRC_DIR = os.path.join("dist", "RapidOCR桌面工具")
DST = os.path.join("release", "RapidOCR-Desktop-v1.0.0-win64.zip")

EXCLUDE_FILES = {"rapidocr_app.log", ".exe_stdout.log", "crash.log",
                 "store.json", "settings.json"}
EXCLUDE_DIRS = {"cache"}

if not os.path.isdir(SRC_DIR):
    sys.exit("未找到打包目录：%s" % SRC_DIR)

os.makedirs(os.path.dirname(DST), exist_ok=True)

parent = os.path.dirname(SRC_DIR)  # dist
n_files = 0
total_in = 0

with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for root, dirs, files in os.walk(SRC_DIR):
        # 目录过滤（原地修改 dirs 以剪枝）
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f in EXCLUDE_FILES or f.endswith((".log", ".pyc")):
                continue
            fp = os.path.join(root, f)
            arc = os.path.relpath(fp, parent).replace("\\", "/")
            try:
                z.write(fp, arc)
                n_files += 1
                total_in += os.path.getsize(fp)
            except Exception as e:  # 被占用等
                print("skip %s (%s)" % (arc, e))

size_out = os.path.getsize(DST)
print("ZIP OK")
print("  output : %s" % os.path.abspath(DST))
print("  files  : %d" % n_files)
print("  raw    : %.1f MB" % (total_in / 1024 / 1024))
print("  zipped : %.1f MB" % (size_out / 1024 / 1024))

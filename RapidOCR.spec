# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 RapidOCR 工作台打包为单目录桌面应用。

产物：dist/RapidOCR桌面工具/RapidOCR桌面工具.exe（不含 onnx 模型，启动后自动下载）
"""
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# 控制台窗口模式用标准库 tkinter（已在 excludes 中移除 tkinter 以保留打包）。
# 不在 WebView2/pywebview 内嵌页面（实测 WebView2 读不到配置信息），改用外部浏览器打开工作台。

block_cipher = None

# 不打包 onnx 模型：启动后由程序自动下载到运行期 models/ 目录
_ro_datas = collect_data_files('rapidocr')
_ro_datas = [(s, d) for (s, d) in _ro_datas if not s.endswith('.onnx')]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('static', 'static'),
    ] + _ro_datas + collect_data_files('onnxruntime'),
    hiddenimports=[
        'field_understanding',
    ] + collect_submodules('field_understanding'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['crash_handler.py'],
    excludes=[
        'test', 'unittest', 'pydoc', 'doctest',
        'matplotlib', 'pytest', 'IPython', 'notebook', 'jedi',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx',
        'scipy', 'pandas', 'sklearn', 'torch', 'tensorflow',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RapidOCR桌面工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                # 窗口模式；错误日志在 ROOT/rapidocr_app.log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RapidOCR桌面工具',
)

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：将 PageWhisper 封装为单文件可执行程序。

用法：
    pip install pyinstaller
    pyinstaller pagewhisper.spec
生成的可执行文件位于 dist/PageWhisper(.exe)，双击即可启动本地服务。
"""
datas = [('static', 'static')]

hiddenimports = [
    'fitz', 'requests', 'deep_translator', 'reportlab',
    'reportlab.lib.pagesizes', 'reportlab.lib.units', 'reportlab.lib.colors',
    'reportlab.lib.styles', 'reportlab.platypus', 'reportlab.pdfbase',
    'reportlab.pdfbase.cidfonts', 'PIL', 'fastapi', 'uvicorn',
    'pdf_extract', 'smart_extract', 'translate_paper', 'translator',
    'html_builder',
]

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['playwright'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PageWhisper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

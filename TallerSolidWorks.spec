# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files, get_module_file_attribute
import os

datas = [('plantilla_macro.swp', '.'), ('biblioteca_sw.bas', '.'), ('ejemplos', 'ejemplos')]
binaries = []
hiddenimports = [
    # pywin32 and COM
    'pythoncom', 'pywin32', 'win32', 'win32api', 'win32con', 'win32com', 'win32com.client',
    'win32com.client.dynamic', 'win32com.server', 'win32gui', 'win32process', 'pywintypes',
    # custom modules
    'customtkinter', 'darkdetect',
    'pdfcotas', 'pdfgeo', 'pdf2vba', 'tareas', 'sw', 'swp_escribir', 'stl_vba', 'stl_a_macro', 'gemini_plano',
    'plano_a_macro', 'planos_gemini', 'PIL', 'PIL.Image',
    'olefile', 'pdfplumber', 'pypdf', 'shapely', 'oletools',
]

# customtkinter with data files
ctk_path = get_module_file_attribute('customtkinter')
if ctk_path:
    ctk_root = os.path.dirname(ctk_path)
    datas.append((os.path.join(ctk_root, 'assets'), 'customtkinter/assets'))

tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('oletools')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pypdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pymupdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('shapely')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('google.genai')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['taller_solidworks.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TallerSolidWorks',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

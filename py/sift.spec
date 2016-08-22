# -*- mode: python -*-

import sys
from PyInstaller.compat import is_win, is_darwin
from PyInstaller.utils.hooks import collect_submodules
import vispy.glsl
import vispy.io

block_cipher = None
exe_name = "SIFT"
main_script_pathname = os.path.join("cspov", "__main__.py")
_script_base = os.path.dirname(os.path.realpath(sys.argv[0]))

data_files = [
    (os.path.dirname(vispy.glsl.__file__), os.path.join("vispy", "glsl")),
    (os.path.join(os.path.dirname(vispy.io.__file__), "_data"), os.path.join("vispy", "io", "_data")),
]

if is_win:
    from llvmlite.binding.ffi import _lib_dir, _lib_name
    data_files += [
        (os.path.join(_lib_dir, _lib_name), '.'),
        (os.path.join(_lib_dir, "MSVCP120.dll"), '.'),
        (os.path.join(_lib_dir, "MSVCR120.dll"), '.'),
    ]

for shape_dir in ["ne_50m_admin_0_countries", "ne_110m_admin_0_countries"]:
    data_files.append((os.path.join("cspov", "data", shape_dir), os.path.join("cspov", "data", shape_dir)))

hidden_imports = [
    "vispy.ext._bundled.six",
    "vispy.app.backends._pyqt4",
] + collect_submodules("rasterio")

binaries = []
if is_darwin:
    lib_dir = sys.executable.replace(os.path.join("bin", "python"), "lib")
    binaries += [(os.path.join(lib_dir, 'libgeos_c.dylib'), '')]
    binaries += [(os.path.join(lib_dir, 'libgeos.dylib'), '')]

a = Analysis([main_script_pathname],
             pathex=[_script_base],
             binaries=binaries,
             datas=data_files,
             hiddenimports=hidden_imports,
             hookspath=[],
             runtime_hooks=[],
             excludes=["tkinter"],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
# FIXME: Remove the console when all diagnostics are properly shown in the GUI

exe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          name=exe_name,
          debug=False,
          strip=False,
          upx=True,
          console=True )

coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=None,
               upx=True,
               name=exe_name)

if is_darwin:
    app = BUNDLE(coll,
                 name=exe_name + '.app',
                 icon=None,
                 bundle_identifier=None)

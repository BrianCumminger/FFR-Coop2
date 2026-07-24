# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os

# Check environment variables for build configuration
# Options: 'both_onedir' (default), 'gui_onefile', 'cli_onefile'
BUILD_TYPE = os.environ.get('BUILD_TYPE', 'both_onedir').lower()

datas, binaries, hiddenimports = collect_all('customtkinter')

# Add our custom resources
datas += [('resources', 'resources'), ('LICENSE', '.')]

if BUILD_TYPE == 'both_onedir':
    # -------------------------------------------------------------------------
    # CONFIGURATION 1: The current setup (Folder containing both GUI & CLI)
    # -------------------------------------------------------------------------
    # GUI Analysis
    a_gui = Analysis(
        ['gui.py'],
        pathex=[],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=['numpy', 'pandas', 'matplotlib', 'scipy', 'PyQt5', 'PySide6', 'IPython', 'notebook'],
        noarchive=False,
    )

    # CLI Analysis
    a_cli = Analysis(
        ['main.py'],
        pathex=[],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=['numpy', 'pandas', 'matplotlib', 'scipy', 'PyQt5', 'PySide6', 'IPython', 'notebook'],
        noarchive=False,
    )

    pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data)
    pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data)

    exe_gui = EXE(
        pyz_gui,
        a_gui.scripts,
        [],
        exclude_binaries=True,
        name='FFR-Coop-GUI',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False, # Hides the console
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon='resources\\ffrcoop2.ico',
    )

    exe_cli = EXE(
        pyz_cli,
        a_cli.scripts,
        [],
        exclude_binaries=True,
        name='FFR-Coop-CLI',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=True, # Keeps the console
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon='resources\\ffrcoop2.ico',
    )

    # Collect both into a single directory
    coll = COLLECT(
        exe_gui,
        a_gui.binaries,
        a_gui.zipfiles,
        a_gui.datas,
        exe_cli,
        a_cli.binaries,
        a_cli.zipfiles,
        a_cli.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='FFR-Coop',
    )

elif BUILD_TYPE == 'gui_onefile':
    # -------------------------------------------------------------------------
    # CONFIGURATION 2: Single standalone EXE for just the GUI
    # -------------------------------------------------------------------------
    a = Analysis(
        ['gui.py'],
        pathex=[],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=['numpy', 'pandas', 'matplotlib', 'scipy', 'PyQt5', 'PySide6', 'IPython', 'notebook'],
        noarchive=False,
    )

    pyz = PYZ(a.pure, a.zipped_data)

    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='FFR-Coop-GUI-Standalone',
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
        icon='resources\\ffrcoop2.ico',
    )

elif BUILD_TYPE == 'cli_onefile':
    # -------------------------------------------------------------------------
    # CONFIGURATION 3: Single standalone EXE for just the CLI
    # -------------------------------------------------------------------------
    a = Analysis(
        ['main.py'],
        pathex=[],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=['numpy', 'pandas', 'matplotlib', 'scipy', 'PyQt5', 'PySide6', 'IPython', 'notebook'],
        noarchive=False,
    )

    pyz = PYZ(a.pure, a.zipped_data)

    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='FFR-Coop-CLI-Standalone',
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
        icon='resources\\ffrcoop2.ico',
    )

# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for WIMI
Build with: pyinstaller wimi.spec
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# Project paths
project_root = Path(SPECPATH)
src_dir = project_root / 'src'

# Collect all web assets (HTML, CSS, JS, libraries, data)
web_datas = [
    (str(src_dir / 'web' / 'html'), 'web/html'),
    (str(src_dir / 'web' / 'css'), 'web/css'),
    (str(src_dir / 'web' / 'js'), 'web/js'),
    (str(src_dir / 'web' / 'lib'), 'web/lib'),      # Quill, KaTeX, and other libraries
    (str(src_dir / 'web' / 'data'), 'web/data'),    # Exam templates JSON
]

# Collect database schema files
schema_datas = [
    (str(src_dir / 'database' / 'schema'), 'database/schema'),
    (str(src_dir / 'database' / 'migrations'), 'database/migrations'),
]

# Combine all data files
datas = web_datas + schema_datas

# Hidden imports for PyQt6 WebEngine and MCP server
hiddenimports = [
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebChannel',
    'PyQt6.QtCore',
    'PyQt6.QtWidgets',
    'PyQt6.QtGui',
    'PyQt6.sip',
    'sqlite3',
    'json',
    'dataclasses',
    'pathlib',
    'PIL',
    'PIL.Image',
    # MCP server (embedded, activated via --mcp-server flag and SSE from Settings)
    'mcp',
    'mcp.server',
    'mcp.server.fastmcp',
    'mcp_server',
    'anyio',
    'anyio._backends',
    'anyio._backends._asyncio',
    'pydantic',
    'pydantic_settings',
    'httpx',
    'httpx_sse',
    'uvicorn',
    'uvicorn.config',
    'uvicorn.main',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'starlette',
    'starlette.applications',
    'starlette.routing',
    'starlette.responses',
    'starlette.requests',
    'starlette.middleware',
    'sse_starlette',
    'sse_starlette.sse',
    'jsonschema',
    'python_multipart',
    'typing_extensions',
    'typing_inspection',
]

a = Analysis(
    [str(src_dir / 'app' / 'main.py')],
    pathex=[str(src_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude dev/test dependencies
        'pytest',
        'pytest_cov',
        'pytest_mock',
        'pytest_qt',
        'pytest_timeout',
        'coverage',
        'sphinx',
        'black',
        'flake8',
        'pylint',
        'mypy',
        'isort',
        'app_data_test',
        'app_data_test_diag',
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
    name='WIMI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Set to False for release builds
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon path here: 'assets/wimi.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WIMI',
)

# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for WIMI - macOS
Build with: pyinstaller wimi_macos.spec --noconfirm
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# Project paths
project_root = Path(SPECPATH)
src_dir = project_root / 'src'

# ---------------------------------------------------------------- build variant
# Release or test (#144). Decided at BUILD time and baked into the bundle:
# the test variant adds one runtime hook that marks the bundle as a test
# build, which is the only thing that lets a frozen WIMI accept --test-mode
# (see src/app/cli.py). A release bundle has no hook, so nothing at runtime
# can turn test mode on. Everything else is identical, on purpose -- the
# binary the suite drives should differ from the one users get by as
# little as possible. build_windows.bat / build_macos.sh set this; `test`
# as their first argument selects the test variant.
import os
BUILD_VARIANT = os.environ.get('WIMI_BUILD_VARIANT', 'release')
if BUILD_VARIANT not in ('release', 'test'):
    raise SystemExit(f"WIMI_BUILD_VARIANT must be 'release' or 'test', not {BUILD_VARIANT!r}")
TEST_BUILD = BUILD_VARIANT == 'test'

# ------------------------------------------------- relation-extraction runtime
# A SECOND, ORTHOGONAL flag (#60, owner's decision 2026-10-04): WIMI ships two
# artifacts per platform, one carrying the relation-extraction runtime
# (torch / transformers / gliner2) and one without. The user chooses at
# download time, because bundling it for everyone roughly doubles the
# installer -- PyQt6 + Qt + Chromium is 504 MB in the venv and this adds 1.2 GB
# of site-packages, 769 MB of it torch (measured) -- for a feature many users
# will not enable.
#
# WHY A SEPARATE FLAG AND NOT A THIRD VALUE OF WIMI_BUILD_VARIANT. The two
# questions are independent: "does this bundle accept --test-mode" and "does
# this bundle carry torch". A single enum would need release / test /
# relations / test-relations, i.e. the product of the two spelled out by hand,
# and a fifth concern later would make it eight names. Orthogonal flags
# compose, and so does the folder name below. #144's instruction -- "Both
# variants come from one spec and differ by that hook alone -- keep it that
# way; a second spec would let them drift" -- is the reason this is here at all
# rather than in a wimi_relations.spec.
RELATIONS_FLAG = os.environ.get('WIMI_BUILD_RELATIONS', '0')
if RELATIONS_FLAG not in ('0', '1'):
    raise SystemExit(
        f"WIMI_BUILD_RELATIONS must be '0' or '1', not {RELATIONS_FLAG!r}"
    )
RELATIONS_BUILD = RELATIONS_FLAG == '1'

# The top-level distributions the relations artifact adds. Kept in step with
# RELATIONS_RUNTIME_PACKAGES in scripts/check_relations_runtime_imports.py,
# which is the gate that keeps them off the startup path; this list is what
# keeps them out of the default BUNDLE (see `excludes` below).
RELATIONS_RUNTIME_PACKAGES = [
    'torch',
    'torchvision',
    'torchaudio',
    'transformers',
    'gliner2',
    'gliner',
    'tokenizers',
    'safetensors',
    'huggingface_hub',
    'accelerate',
    'sentencepiece',
]

runtime_hooks = []
if TEST_BUILD:
    runtime_hooks.append(str(project_root / 'packaging' / 'rthook_test_build.py'))
if RELATIONS_BUILD:
    runtime_hooks.append(str(project_root / 'packaging' / 'rthook_relations_build.py'))
# The folder name is what tells them apart on disk, and it composes exactly as
# the flags do -- which is the point of keeping them orthogonal:
#
#   dist/WIMI                 default
#   dist/WIMI-test            test
#   dist/WIMI-relations       relations
#   dist/WIMI-test-relations  test + relations
#
# One line per flag. If this ever becomes a four-way conditional, the flag
# design has drifted back into an enum.
DIST_NAME = 'WIMI' + ('-test' if TEST_BUILD else '') + ('-relations' if RELATIONS_BUILD else '')

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

# Third-party executables and shared libraries WIMI carries but does not link
# against. Empty until the speech-to-text block below.
binaries = []

# ------------------------------------------------------------- speech-to-text
# The vendored whisper.cpp CLI and its shared libraries (#59), COMPILED into
# vendor/whisper/macos-arm64/ by build_macos.sh. There is nothing to fetch:
# whisper.cpp publishes no macOS binary and never has -- its one macos-latest
# release job builds an iOS xcframework (plan section 3.2), which is why
# scripts/fetch_whisper.py answers --platform macos-arm64 with a source-build
# recipe instead of a download. Model weights are deliberately NOT here: owner
# decision D2 downloads them on first run into app_data/models/, so nothing in
# this file may reference them (plan section 3.8).
#
# binaries=, NOT datas=. Stated identically in wimi.spec and wimi_macos.spec,
# because those two files are clones with no shared helper and a change made
# in one of them is a bug that only shows on the other platform.
#
#   The two lists produce the SAME bundle here, and that is the reason for the
#   choice rather than an argument against caring. PyInstaller 6 reclassifies
#   every collected file by inspecting its contents before it acts on any of
#   them -- "Automatic binary vs. data reclassification" in
#   building/build_main.py, via bindepend.classify_binary_vs_data(), which
#   reads the PE MZ header on Windows and opens the file with macholib on
#   macOS. whisper-cli and its libraries come out BINARY whichever list they
#   were declared in, and LICENSE comes out DATA. So the declaration is not a
#   switch; it is a statement about what the files are, and it should be the
#   true one.
#
#   It stops being cosmetic in exactly one case: classification returns None
#   when it cannot answer (file missing, pefile/macholib unavailable, an
#   unexpected parse error), and then the DECLARED typecode stands. Declared
#   BINARY, a whisper-cli that failed classification still gets dependency
#   analysis, still gets its macOS load paths rewritten and re-signed, and
#   still lands in Contents/Frameworks. Declared DATA it silently would not,
#   and the result is a bundle that is wrong in a way nothing reports.
#
#   The directory is mixed and does not need splitting: the reclassification
#   pass runs before dependency analysis and before any binary processing, so
#   LICENSE is DATA again by the time anything would have tried to read it as
#   an executable. That keeps the file list where the build step owns it,
#   instead of copied into two spec files to drift.
#
#   feature/ai-capture declares its llama-server tree as datas. It is not a
#   counter-example and does not need changing: the same reclassification pass
#   lands it in the same place.
#
# #158 -- the MSVC runtime -- is a Windows-only concern and has no macOS half.
# It is recorded in wimi.spec, not repeated here, so this clone does not grow a
# paragraph about a platform it cannot reach.
#
# FROZEN PATH. One answer, and it is not the one app_data uses:
#
#     Path(sys._MEIPASS) / 'whisper' / '<platform>'
#
#   Windows onedir:  dist/WIMI/_internal/whisper/windows/whisper-cli.exe
#   macOS .app:      WIMI.app/Contents/Frameworks/whisper/macos-arm64/whisper-cli
#                    (cross-linked from Contents/Resources; the Frameworks copy
#                    is the real file, because these are BINARY entries)
#
#   Path(sys.executable).parent / '_internal' is the OTHER frozen base path in
#   this codebase (main_window.py:12-26, migrations/_helpers.py:41). It names
#   the same directory on Windows and DOES NOT EXIST inside a macOS .app,
#   where sys.executable is Contents/MacOS/WIMI. sys._MEIPASS is the one that
#   is right on both: PyInstaller points it at _internal on Windows and at
#   Contents/Frameworks in an .app (fake-modules/_pyi_rth_utils/__init__.py
#   keys on exactly that suffix).
#
#   The platform key must stay free of dots. PyInstaller rewrites any
#   directory name containing one under Contents/Frameworks to satisfy
#   codesign, and leaves a symlink behind -- so 'macos-arm64' is collected
#   verbatim and 'macos.arm64' would not have been.
#
# build_macos.sh owns the file list; it is deliberately not repeated here,
# because a second copy of it would drift. This check catches only the one
# failure a silent build would otherwise ship: the build step never ran.
WHISPER_PLATFORM = 'macos-arm64'
WHISPER_BINARY = 'whisper-cli'
whisper_src = project_root / 'vendor' / 'whisper' / WHISPER_PLATFORM
whisper_dest = 'whisper/' + WHISPER_PLATFORM
if not (whisper_src / WHISPER_BINARY).is_file():
    raise SystemExit(
        'vendor/' + whisper_dest + '/' + WHISPER_BINARY + ' is missing -- '
        'build it with ./build_macos.sh, which compiles whisper.cpp from '
        'source (Xcode Command Line Tools and CMake required)'
    )
binaries += [(str(whisper_src), whisper_dest)]

# Never UPX the vendored tree. UPX on a third-party native binary is a known
# way to produce something that will not execute, and on macOS it invalidates
# the signature as well. This is load-bearing, not decoration: the files above
# are BINARY entries, EXE, COLLECT and the BUNDLE that inherits COLLECT's
# settings all set upx=True, and PyInstaller would compress them without this.
#
# Matched against the SOURCE path by pathlib.PurePath.match -- right to left,
# '*' but no '**', case sensitivity per the OS (building/utils.py,
# process_collected_binary). So the pattern carries the two trailing
# directories on purpose: a bare '*.dylib' would also match every Qt library.
whisper_upx_exclude = [whisper_dest + '/*']

# Hidden imports for PyQt6 WebEngine and MCP server
#
# PyQt6.QtMultimedia is deliberately absent (#59). PyInstaller 6.19 ships
# hook-PyQt6.QtMultimedia.py and collects the Qt multimedia plugins itself as
# soon as anything in the analysed graph imports the module, which src/app/stt
# does. Measured by T2. Listing it here would add an entry that reads as
# load-bearing and is not, and hand-rolling a plugin-collection step beside it
# would be worse.
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

# ------------------------------------------- relations runtime, when asked for
# UNVERIFIED ON A REAL BUILD. Written on Linux, where WIMI does not ship, so
# nothing below has been through PyInstaller on Windows or macOS. A torch
# bundle is well known for hidden-import and DLL/dylib-collection surprises,
# and the first real build on each platform should be expected to need
# additions here. Say so rather than letting a later maintainer read this as
# tested (#60).
#
# torch and transformers are left to pyinstaller-hooks-contrib, which carries
# maintained hooks for both. That package is already pinned in
# requirements-prod.txt (2026.7) for precisely this class of reason: it is a
# build-time code generator that decides what ends up in the bundle, and an
# unpinned transitive is how #135 shipped a Chromium nobody had tested.
# Re-implementing its torch hook here would mean maintaining a copy that
# drifts from it.
#
# gliner2 gets collect_all because it almost certainly has no contributed hook
# and ships package data (model and schema configuration) that a pure import
# scan does not see.
#
# Model WEIGHTS are not here and must never be: they download on first use
# into app_data/models/ (owner's decision, #59's D2). Only the runtime ships.
if RELATIONS_BUILD:
    from PyInstaller.utils.hooks import collect_all

    hiddenimports = hiddenimports + ['torch', 'transformers', 'gliner2']

    try:
        _g_datas, _g_binaries, _g_hidden = collect_all('gliner2')
    except Exception as exc:
        raise SystemExit(
            "WIMI_BUILD_RELATIONS=1 but gliner2 could not be collected: "
            f"{exc!r}.\n"
            "Install the runtime from the CPU index first:\n"
            "    pip install -r requirements-relations.txt "
            "--index-url https://download.pytorch.org/whl/cpu "
            "--extra-index-url https://pypi.org/simple\n"
            "scripts/check_build_env.py --relations checks this before the "
            "build reaches here."
        )
    datas = datas + _g_datas
    binaries = binaries + _g_binaries
    hiddenimports = hiddenimports + _g_hidden

a = Analysis(
    [str(src_dir / 'app' / 'main.py')],
    pathex=[str(src_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
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
        # The relation-extraction runtime, unless this is the relations build
        # (#60). Excluding it is not belt-and-braces -- it is what makes the
        # DEFAULT artifact deterministic. PyInstaller's analysis is static and
        # ignores import scope and try/except guards, so a developer building
        # the default artifact on a machine that has the relations venv
        # installed would otherwise collect gigabytes of torch into it from a
        # function-level import. scripts/check_relations_runtime_imports.py
        # stops a module-scope import reaching the startup path; this stops
        # either kind reaching the default BUNDLE.
        *([] if RELATIONS_BUILD else RELATIONS_RUNTIME_PACKAGES),
    ],
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
    console=False,  # macOS .app bundles must not be console apps
    disable_windowed_traceback=False,
    argv_emulation=False,
    # Apple Silicon only (#59). WIMI no longer builds for Intel Macs, and
    # 'universal2' cost roughly 2x the download to carry a slice nobody
    # runs. It also screened out every arm64-only wheel -- which is most
    # ML tooling, including what a local speech-to-text model needs.
    #
    # Stated as 'arm64' rather than None on purpose: None means "whatever
    # this build host happens to be", so building on an Intel Mac would
    # quietly produce an x86_64 app that looks fine and is not what we
    # ship. 'arm64' fails loudly there instead.
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file='entitlements.plist',
    icon=None,  # Future: 'assets/wimi.icns'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=whisper_upx_exclude,
    name=DIST_NAME,
)

app = BUNDLE(
    coll,
    name=DIST_NAME + '.app',
    icon=None,  # Future: 'assets/wimi.icns'
    bundle_identifier='com.wimi.app.test' if TEST_BUILD else 'com.wimi.app',
    info_plist={
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleDisplayName': 'WIMI',
        # Required before anything in this bundle touches the microphone
        # (#59). macOS does not hand a process without this key an error
        # -- it KILLS it, so the absence would surface as an unexplained
        # crash rather than a denied permission. It costs nothing while
        # the feature does not exist yet: the string is only ever shown
        # in the system prompt, which is raised on first use.
        #
        # This is also why speech capture is Qt's and not the web page's:
        # getUserMedia would open the device from the nested
        # QtWebEngineProcess.app, whose Info.plist is Qt's, not ours.
        'NSMicrophoneUsageDescription':
            'WIMI uses the microphone only when you press record, so you '
            'can speak an explanation instead of typing it. The audio is '
            'transcribed on this Mac and never leaves it.',
    },
)

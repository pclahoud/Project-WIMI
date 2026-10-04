#!/bin/bash
# ============================================
# WIMI macOS Build Script
# ============================================

echo ""
echo "========================================"
echo "   WIMI Build Script for macOS"
echo "========================================"
echo ""

# Build variant (#144). No argument makes the RELEASE build, which refuses
# --test-mode. "./build_macos.sh test" makes the TEST build: identical except
# for one runtime hook, and the only build that accepts --test-mode (a
# Chromium remote debugger). Point WIMI_TEST_BINARY at a test build. Never
# distribute one.
#
# "relations" is a SECOND, ORTHOGONAL flag (#60): it bundles the
# relation-extraction runtime (torch / transformers / gliner2), which WIMI
# ships as its own artifact rather than in everyone's download. The two
# compose, in any order and in either combination:
#
#   ./build_macos.sh                   -> dist/WIMI
#   ./build_macos.sh test              -> dist/WIMI-test
#   ./build_macos.sh relations         -> dist/WIMI-relations
#   ./build_macos.sh test relations    -> dist/WIMI-test-relations
#
# A loop rather than a four-way case, deliberately: the names compose because
# the flags do, and a case over the combinations is the enum this design
# rejected (see wimi_macos.spec's variant block).
VARIANT="release"
RELATIONS="0"
for arg in "$@"; do
    case "$arg" in
        test) VARIANT="test" ;;
        relations) RELATIONS="1" ;;
        *)
            echo "[ERROR] Unknown argument '$arg'."
            echo "        No argument makes a release build without the"
            echo "        relation-extraction runtime. 'test' makes a test build;"
            echo "        'relations' bundles that runtime. Both may be given."
            exit 1
            ;;
    esac
done
# One line per flag, so the composition is diffable by eye against
# build_windows.bat's three equivalent lines.
DIST_NAME="WIMI"
[ "$VARIANT" = "test" ] && DIST_NAME="${DIST_NAME}-test"
[ "$RELATIONS" = "1" ] && DIST_NAME="${DIST_NAME}-relations"
export WIMI_BUILD_VARIANT="$VARIANT"
# Exported BEFORE check_build_env.py runs: the gate reads it to decide whether
# to verify requirements-relations.txt and that torch is the CPU build, so the
# call below needs no extra argument (#60).
export WIMI_BUILD_RELATIONS="$RELATIONS"
# PyInstaller's workpath needs the relations flag too, or a relations build
# and a default build share build/release -- so each would wipe the other's
# intermediate work, which is what the clean step below says it does NOT do.
# The existing build/release and build/test paths are unchanged.
BUILD_TAG="$VARIANT"
[ "$RELATIONS" = "1" ] && BUILD_TAG="${BUILD_TAG}-relations"
echo "Variant: $VARIANT  relations: $RELATIONS  (output: dist/$DIST_NAME/)"
echo ""

# Check if virtual environment exists.
# NOTE: this only proves the file is THERE. It does not prove activation
# works -- a renamed or moved venv leaves an activate script that exists,
# runs, and silently leaves the system Python on PATH (#183). The real
# check is check_build_env.py's check_interpreter, which compares
# sys.prefix against this checkout's .venv and refuses on a mismatch.
if [ ! -f ".venv/bin/activate" ]; then
    echo "[ERROR] Virtual environment not found!"
    echo "Please run: python3 -m venv .venv"
    echo "Then: source .venv/bin/activate"
    echo "Then: pip install -r requirements-prod.txt"
    exit 1
fi

# A C++ toolchain is a REAL prerequisite of the macOS build since #59, and it
# is not one docs/BUILD_MACOS.md used to ask for. whisper.cpp publishes no
# macOS binary and never has -- its one macos-latest release job builds an iOS
# xcframework -- so this script compiles the engine instead of downloading it
# (plan section 3.2). llama.cpp does publish macOS assets; that is the one
# place the two vendored engines stop being the same shape.
#
# Checked up front, before anything is cleaned or built, because a CMake error
# three minutes into a PyInstaller run is a worse experience than a one-line
# refusal at the start. Checked unconditionally even when vendor/whisper is
# already present: a conditional check is a second code path that only runs on
# the branch nobody exercises.
if ! xcode-select -p > /dev/null 2>&1; then
    echo "[ERROR] Xcode Command Line Tools not found!"
    echo "        The macOS build compiles whisper.cpp from source (#59)."
    echo "Please run: xcode-select --install"
    exit 1
fi

if ! command -v cmake > /dev/null 2>&1; then
    echo "[ERROR] CMake not found!"
    echo "        The macOS build compiles whisper.cpp from source (#59)."
    echo "Please run: brew install cmake"
    echo "        (or install it from https://cmake.org/download/ and put it on PATH)"
    exit 1
fi

if ! command -v git > /dev/null 2>&1; then
    echo "[ERROR] git not found!"
    echo "        It is needed to fetch the pinned whisper.cpp source."
    echo "Please run: xcode-select --install"
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Check if PyInstaller is installed
if ! pip show pyinstaller > /dev/null 2>&1; then
    echo "[INFO] Installing PyInstaller..."
    pip install pyinstaller
fi

# Verify the environment matches requirements-prod.txt before building.
# The Windows machine once drifted to PyQt6 6.10.1 while the pin said 6.9.1,
# and the drifted Qt shipped inside the bundle -- so the binary ran a browser
# engine no test had ever exercised (#135, and #134/#136 for what that broke).
# A pin nobody checks is a comment.
echo ""
echo "[1/7] Checking build environment..."
if ! python scripts/check_build_env.py; then
    echo ""
    echo "[ERROR] Build environment does not match requirements-prod.txt."
    echo "        Fix it with: pip install -r requirements-prod.txt"
    echo "        Do NOT ship a build made from a mismatched environment."
    exit 1
fi

# ---------------------------------------------------------------------------
# Build the vendored whisper.cpp engine from source (#59).
#
# This is where the macOS build stops matching build_windows.bat, which fetches
# a pinned release asset. Everything below produces the same
# vendor/whisper/<platform>/ layout that scripts/fetch_whisper.py documents, so
# wimi_macos.spec collects it the same way.
#
# The BINARY only. Model weights download on first run into app_data/models/
# (owner decision D2) and must never enter the installer.
#
# Both variants need it: a test build must be the release build plus one
# runtime hook (#144), and a test build missing the engine would be evidence
# about a binary nobody ships.
echo ""
echo "[2/7] Building whisper.cpp engine from source..."

# The pin lives in scripts/fetch_whisper.py and nowhere else. Reading it here
# rather than repeating it is the difference between one pin and two that
# drift: bumping the release tag there has to move this build with it.
WHISPER_TAG="$(python -c 'import sys; sys.path.insert(0, "scripts"); import fetch_whisper; print(fetch_whisper.RELEASE_TAG)')"
if [ -z "$WHISPER_TAG" ]; then
    echo "[ERROR] Could not read RELEASE_TAG from scripts/fetch_whisper.py."
    exit 1
fi

WHISPER_DEST="vendor/whisper/macos-arm64"
WHISPER_SRC="build/whisper.cpp-$WHISPER_TAG"
WHISPER_STAMP="$WHISPER_DEST/build_manifest.json"

# Rebuild only when the pin moved or the tree is gone. The stamp records the
# tag actually built, so bumping the pin rebuilds and an ordinary build does
# not pay for a compile it does not need.
NEED_WHISPER=1
if [ -x "$WHISPER_DEST/whisper-cli" ] && [ -f "$WHISPER_STAMP" ]; then
    if grep -q "\"release_tag\": \"$WHISPER_TAG\"" "$WHISPER_STAMP"; then
        NEED_WHISPER=0
        echo "      Already built at $WHISPER_TAG (delete $WHISPER_DEST to force)."
    else
        echo "      Pin moved to $WHISPER_TAG; rebuilding."
    fi
fi

if [ "$NEED_WHISPER" = "1" ]; then
    if [ ! -d "$WHISPER_SRC" ]; then
        echo "      Cloning whisper.cpp at $WHISPER_TAG..."
        if ! git clone --depth 1 --branch "$WHISPER_TAG" \
                https://github.com/ggml-org/whisper.cpp "$WHISPER_SRC"; then
            echo ""
            echo "[ERROR] Could not fetch whisper.cpp at $WHISPER_TAG."
            echo "        Check the tag in scripts/fetch_whisper.py and the network."
            exit 1
        fi
    fi

    # GGML_METAL_EMBED_LIBRARY=ON embeds the Metal shaders into the binary, so
    # there is no .metallib to locate at runtime or carry through PyInstaller.
    # Observed on upstream's iOS job and INFERRED for desktop -- T19 confirms.
    #
    # The two rpath flags are what stop this shipping a binary that works only
    # on the machine that built it. CMake's default build-tree rpath points at
    # build/src, which still exists here and does not exist on a student's Mac,
    # so a smoke test on the build host would pass and the student's would
    # fail. '@loader_path' makes whisper-cli look beside itself, which is
    # exactly the flat layout the fetcher documents. A no-op if upstream links
    # these statically.
    # GGML_NATIVE=OFF is the difference between an artifact that runs on
    # Apple Silicon and one that runs on THIS Apple Silicon (#178).
    #
    # ggml defaults it ON, which compiles with -mcpu=native. T19's build log
    # on a Mac mini M4:
    #
    #   ARM -march/-mcpu not found, -mcpu=native will be used
    #   -mcpu=native+dotprod+i8mm+nosve+sme
    #
    # -mcpu=native there resolves to apple-m4, emitting +bf16 +i8mm +sme
    # +sme2. SME exists only on M4; i8mm and bf16 are absent on M1. So a
    # release cut on an M4 can emit instructions an M1, M2 or M3 cannot
    # execute -- and it would pass every test on the machine that built it.
    #
    # This is the same mistake wimi_macos.spec already refuses one level up,
    # where target_arch is stated as 'arm64' rather than None precisely
    # because "None means whatever this build host happens to be". Here it
    # is the CPU feature set rather than the architecture.
    #
    # OFF and nothing else: no explicit -mcpu baseline is named, so the
    # compiler's own default for arm64-apple-macos applies, which Apple
    # guarantees across the Macs it supports. Naming a baseline (apple-m1)
    # would be a further optimisation and a further thing to get wrong on a
    # toolchain nobody here can test against.
    #
    # NOT the best available fix. GGML_CPU_ALL_VARIANTS builds several CPU
    # backends and selects at runtime, which is what the Windows build
    # already does -- ggml.dll LoadLibrary's the right ggml-cpu-*.dll, and
    # T18/T19 measured two different variants loading on two machines
    # (cascadelake, haswell). On ARM that also needs GGML_BACKEND_DL, and it
    # interacts with the dylib collection and rpath rewriting this script
    # and #181 are already arguing about. It is the right destination and it
    # needs a Mac to reach; this flag removes the defect today without one.
    echo "      Configuring..."
    if ! cmake -S "$WHISPER_SRC" -B "$WHISPER_SRC/build" \
            -DCMAKE_BUILD_TYPE=Release \
            -DGGML_NATIVE=OFF \
            -DGGML_METAL_EMBED_LIBRARY=ON \
            -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
            -DCMAKE_INSTALL_RPATH='@loader_path'; then
        echo ""
        echo "[ERROR] CMake configuration failed."
        exit 1
    fi

    echo "      Compiling (this takes a few minutes)..."
    if ! cmake --build "$WHISPER_SRC/build" -j --config Release; then
        echo ""
        echo "[ERROR] whisper.cpp build failed."
        exit 1
    fi

    if [ ! -f "$WHISPER_SRC/build/bin/whisper-cli" ]; then
        echo ""
        echo "[ERROR] The build produced no whisper-cli."
        echo "        Looked in $WHISPER_SRC/build/bin/."
        echo "        Upstream may have moved it; see scripts/fetch_whisper.py."
        exit 1
    fi

    rm -rf "$WHISPER_DEST"
    mkdir -p "$WHISPER_DEST"
    cp "$WHISPER_SRC/build/bin/whisper-cli" "$WHISPER_DEST/"
    cp "$WHISPER_SRC/LICENSE" "$WHISPER_DEST/"

    # Copy whatever shared libraries the build produced, flat, beside the
    # binary. The set is NOT pinned here: nobody has run this build yet, and
    # scripts/fetch_whisper.py says so where it refuses --platform macos-arm64.
    # T19 measures it and pins it. A static build produces none, which is why
    # finding none is not an error -- the smoke test below is what decides.
    WHISPER_DYLIBS=0
    while IFS= read -r dylib; do
        cp "$dylib" "$WHISPER_DEST/"
        WHISPER_DYLIBS=$((WHISPER_DYLIBS + 1))
    done < <(find "$WHISPER_SRC/build" \
                  \( -name 'libwhisper*.dylib' -o -name 'libggml*.dylib' \) -print)
    echo "      Collected whisper-cli, LICENSE and $WHISPER_DYLIBS shared libraries."

    # Does it load? This is the one thing a build host can check that a student
    # would otherwise discover instead. It deliberately tests the LINKER and
    # not the exit status: whisper-cli's convention for --help is not something
    # this script should assert (T19 can), but a dyld failure is unambiguous
    # and is the failure the rpath flags above exist to prevent.
    WHISPER_SMOKE="$("$WHISPER_DEST/whisper-cli" --help 2>&1 || true)"
    case "$WHISPER_SMOKE" in
        *"Library not loaded"*|*"image not found"*|*"dyld"*)
            echo ""
            echo "[ERROR] The built whisper-cli cannot load its libraries:"
            echo "$WHISPER_SMOKE" | head -5
            echo ""
            echo "        This is the failure that would otherwise reach a student."
            echo "        Check the rpath flags in this script and what landed in"
            echo "        $WHISPER_DEST."
            exit 1
            ;;
    esac

    # Mirrors the shape of the fetcher's fetch_manifest.json: what was
    # installed, and from which pin, so the next run can tell.
    {
        echo "{"
        echo "  \"release_tag\": \"$WHISPER_TAG\","
        echo "  \"platform\": \"macos-arm64\","
        echo "  \"source\": \"compiled from source; whisper.cpp publishes no macOS asset\","
        echo "  \"cmake_flags\": \"-DGGML_NATIVE=OFF -DGGML_METAL_EMBED_LIBRARY=ON -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON -DCMAKE_INSTALL_RPATH=@loader_path\","
        echo "  \"built_at\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\""
        echo "}"
    } > "$WHISPER_STAMP"
fi

# Clean the previous build of THIS variant only, so a test build does not
# wipe a release build sitting beside it (or the other way round).
echo ""
echo "[3/7] Cleaning previous $BUILD_TAG build..."
rm -rf "build/$BUILD_TAG" "dist/$DIST_NAME" "dist/$DIST_NAME.app"

# Run PyInstaller
echo ""
echo "[4/7] Building with PyInstaller..."
echo "      This may take several minutes..."
echo ""
pyinstaller wimi_macos.spec --noconfirm --workpath "build/$BUILD_TAG"

if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] Build failed!"
    exit 1
fi

# PyInstaller produces:
#   dist/WIMI/      <- COLLECT output (binary + _internal/, redundant once .app exists)
#   dist/WIMI.app   <- BUNDLE output (the actual app)
# We want dist/WIMI/WIMI.app with app_data/ and logs/ as siblings, so
# wipe the redundant COLLECT folder, recreate it as a container, and
# move the .app inside.
echo ""
echo "[5/7] Setting up distribution..."
rm -rf "dist/$DIST_NAME"
mkdir -p "dist/$DIST_NAME"
mv "dist/$DIST_NAME.app" "dist/$DIST_NAME/WIMI.app"
mkdir -p "dist/$DIST_NAME/app_data"
mkdir -p "dist/$DIST_NAME/logs"

# Licence texts and the corresponding-source notice (#272). GPL-3.0 s4 requires
# the licence to be conveyed WITH the program and s6 requires the source to be
# obtainable from a stated place; Settings -> About names the licences but
# naming is not conveying, and until this the bundle carried no copyleft text at
# all. Identical line in build_windows.bat -- the logic is in the Python so the
# two scripts cannot drift the way CLAUDE.md records the two .spec files can.
python scripts/stage_license_files.py "dist/$DIST_NAME"

# Generate First Launch.command: a build-host convenience, NOT a no-Terminal
# path, and not the route a recipient is given.
#
# Double-clicking it is refused exactly as the app is, because the .command file
# carries com.apple.quarantine too -- measured on a quarantined copy, and
# Control-click -> Open in Finder gave the same dialog (#179, T19 2026-09-24).
# So the helper cannot bootstrap itself out of the problem it exists to solve,
# and it must never be advertised as a click-only route.
#
# Nothing in the script below depends on being launched by Finder, but running
# it from Terminal has NOT been tested in that form, and it clears ALL extended
# attributes (xattr -cr) where what was measured end-to-end is the narrower
# xattr -dr com.apple.quarantine. So the recipient instruction below is the two
# commands, not this file. It is kept as a convenience on the build host, where
# nothing is quarantined.
echo ""
echo "[6/7] Generating First Launch.command..."
cat > "dist/$DIST_NAME/First Launch.command" <<'LAUNCHER'
#!/bin/bash
cd "$(dirname "$0")"
echo "Preparing WIMI for first launch..."
xattr -cr WIMI.app
echo "Done. Launching WIMI."
open WIMI.app
LAUNCHER
chmod +x "dist/$DIST_NAME/First Launch.command"

# Finalize
echo ""
echo "[7/7] Finalizing..."

echo ""
echo "========================================"
echo "   BUILD COMPLETE!"
echo "========================================"
echo ""
echo "Output location: dist/$DIST_NAME/"
echo "Application:     dist/$DIST_NAME/WIMI.app"
echo "First-run helper: dist/$DIST_NAME/First Launch.command"
echo "                  (build-host convenience only -- do not distribute it"
echo "                   as the first-launch route; see below)"
echo ""
echo "To run locally (your machine):"
echo "  open dist/$DIST_NAME/WIMI.app"
echo "  (a copy you just built is not quarantined, so this opens normally)"
echo ""
if [ "$VARIANT" = "test" ]; then
    echo "This is a TEST build: it accepts --test-mode, which starts a remote"
    echo "debugger. Use it for WIMI_TEST_BINARY. Do NOT distribute it."
    echo ""
    exit 0
fi
echo "To distribute:"
if [ "$RELATIONS" = "1" ]; then
    # Asset naming follows the existing WIMI_mac_v0.1.0-beta.zip shape (#60).
    # Provisional but committed: the owner has approved this shape and will
    # write the release-page copy that explains what the larger download buys.
    echo "  cd dist && zip -r WIMI_mac_relations_v<version>.zip $DIST_NAME"
    echo ""
    echo "This is the RELATIONS artifact: it carries the relation-extraction"
    echo "runtime and is roughly twice the size of the default one. It is a"
    echo "SEPARATE download, not a replacement -- publish both, and do not let"
    echo "this one take the default artifact's name."
else
    echo "  cd dist && zip -r WIMI_mac_v<version>.zip $DIST_NAME"
fi
echo ""
echo "THIS BUILD NEEDS ONE TERMINAL STEP BEFORE SOMEBODY ELSE CAN OPEN IT."
echo "It is adhoc-signed and NOT notarized, so macOS refuses a downloaded"
echo "copy and offers only [Move to Trash] and [Done]. There is no Open"
echo "button to click, and a right-click or Control-click Open in Finder"
echo "raises the identical refusal -- measured, so do not pass that on."
echo ""
echo "The supported first launch (#179). Recipients unzip, open Terminal,"
echo "and run -- one time per copy, not once per launch:"
echo "    xattr -dr com.apple.quarantine /path/to/WIMI.app"
echo "    open /path/to/WIMI.app"
echo ""
echo "Nobody has to know how to type a path: type the command with a"
echo "trailing space, then DRAG WIMI.app from Finder into the Terminal"
echo "window and Terminal fills the path in. Pass that on with the"
echo "command -- it is the difference between an instruction a student"
echo "can follow and one they cannot."
echo ""
echo "Measured 2026-10-02 on one Mac mini M4, macOS 26.2, MDM-managed,"
echo "non-admin account. NO ADMIN RIGHTS ARE NEEDED, and the app is not"
echo "translocated, so app_data/ and logs/ land beside the .app. One host,"
echo "though -- an unmanaged Mac has not been tried. System Settings"
echo "'Open Anyway' is UNTESTED, may not appear at all on a managed Mac,"
echo "and is not an alternative to offer."
echo ""
echo "Tell them what the command does and why. It clears the flag macOS"
echo "sets on anything downloaded; it does not make WIMI signed, notarized"
echo "or verified, and 'spctl' still reports 'rejected' afterwards because"
echo "assessment only gates quarantined launches. Launching is the test."
echo "The step goes away when the build is signed and notarized (#274,"
echo "blocked on a paid Apple Developer account)."
echo ""
echo "Do NOT hand over 'First Launch.command' as the route. Double-clicking"
echo "it is refused the same way the app is (it is quarantined too), and"
echo "running it from Terminal has not been tested in that form -- it also"
echo "clears ALL extended attributes, not just the quarantine flag. Give"
echo "them the two commands above. See docs/BUILD_MACOS.md and #179."
echo ""

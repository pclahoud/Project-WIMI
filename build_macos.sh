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
    # fail. '@loader_path' makes whisper-cli look beside itself -- true in
    # vendor/, which is where the smoke test below runs it, and NOT what
    # happens in the bundle (#181). There PyInstaller's dependency analysis
    # copies the six libraries to the top of Contents/Frameworks/ and rewrites
    # whisper-cli's rpath to @loader_path/../.., so DYLD_PRINT_LIBRARIES shows
    # every one loading from there and none from the copies beside it in
    # Frameworks/whisper/macos-arm64/. Both are measured; they differ. Those
    # copies are therefore removed from the bundle after PyInstaller (#388).
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

    # Copy each shared library ONCE, flat, beside the binary, under its
    # INSTALL NAME (#181). CMake writes one real file per library plus two
    # version symlinks (libX.dylib, libX.<major>.dylib); without -type f the
    # find matched all three and cp dereferenced each, so every library
    # landed three times -- "18 shared libraries" was 6 x 3. The install name
    # (`otool -D`, e.g. @rpath/libwhisper.1.dylib) is the one name dyld asks
    # for, so it is the only copy whisper-cli can use.
    #
    # The set is pinned as MACOS_DYLIBS in scripts/fetch_whisper.py, read from
    # there like the release tag so there is one list, not two that drift. A
    # build producing a different set is refused rather than shipped: a new
    # backend upstream would otherwise arrive unnoticed, and a missing one
    # would fail only on a student's Mac.
    WHISPER_DYLIBS=0
    while IFS= read -r dylib; do
        install_name="$(otool -D "$dylib" | sed -n 2p)"
        if [ -z "$install_name" ]; then
            echo ""
            echo "[ERROR] $dylib has no install name (otool -D printed none)."
            exit 1
        fi
        cp "$dylib" "$WHISPER_DEST/$(basename "$install_name")"
        WHISPER_DYLIBS=$((WHISPER_DYLIBS + 1))
    done < <(find "$WHISPER_SRC/build" -type f \
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

# The library set is checked on EVERY build, not only after a compile (#181).
# A vendor/ tree built before the fix holds all 18 copies under a stamp that
# still matches the pin, so the "already built" shortcut above would ship it.
WHISPER_EXPECTED="$(python -c 'import sys; sys.path.insert(0, "scripts"); import fetch_whisper; print("\n".join(sorted(fetch_whisper.MACOS_DYLIBS)))')"
WHISPER_GOT="$(cd "$WHISPER_DEST" && ls -1 lib*.dylib 2>/dev/null | sort)"
if [ "$WHISPER_GOT" != "$WHISPER_EXPECTED" ]; then
    echo ""
    echo "[ERROR] $WHISPER_DEST holds a different set of libraries than"
    echo "        MACOS_DYLIBS in scripts/fetch_whisper.py pins (#181)."
    echo "        Expected:"; echo "$WHISPER_EXPECTED" | sed 's/^/          /'
    echo "        Got:";      echo "$WHISPER_GOT"      | sed 's/^/          /'
    echo "        A tree built before #181 holds three copies of each: delete"
    echo "        $WHISPER_DEST and build again. If upstream changed the set,"
    echo "        measure the new one and update the pin."
    exit 1
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

# Drop the six whisper dylibs nothing loads, then re-seal (#388, owner's
# decision 2026-10-06: delete after the build, so this script stays the one
# owner of the file list and wimi_macos.spec is untouched).
#
# They are dead weight, measured: PyInstaller's dependency analysis copies the
# six to the TOP of Contents/Frameworks/ and rewrites whisper-cli's rpath to
# @loader_path/../.., and DYLD_PRINT_LIBRARIES shows every one loading from
# there (#181, on an M4, an M1 and a MacBook Air). The copies beside whisper-cli
# in Frameworks/whisper/macos-arm64/ are 5.0 MB that nothing opens. whisper-cli
# itself, its LICENSE and build_manifest.json stay.
#
# TWO places, not one. PyInstaller also writes a SYMLINK to each of them under
# Contents/Resources/whisper/macos-arm64/, so deleting only the files leaves six
# dangling links and the signature check fails with "No such file or
# directory".
#
# And the bundle MUST be re-sealed. PyInstaller signs it (adhoc) with all six
# listed in _CodeSignature/CodeResources, so removing them invalidates the
# signature until it is re-signed. --preserve-metadata keeps the entitlements
# entitlements.plist put there (JIT, unsigned executable memory, library
# validation, audio input). Without them Chromium and the microphone break.
# Only the outer bundle is re-signed: nested code keeps its own signatures,
# which is why this is not --deep. The verify below is --deep and --strict.
# Measured on a MacBook Air: it passes afterwards with the same four
# entitlements, and whisper-cli still resolves all six libraries.
#
# STANDING CONSTRAINT: this re-seal is the last thing that may touch WIMI.app.
# Any later step that writes into the bundle has to go ABOVE it. Nothing
# enforces that, and the symptom of breaking it is an app that fails its
# signature check on a recipient's Mac. Licence staging and First-Launch.command
# below write BESIDE the bundle, not into it.
WHISPER_BUNDLED="dist/$DIST_NAME/WIMI.app/Contents/Frameworks/whisper/macos-arm64"
WHISPER_LINKS="dist/$DIST_NAME/WIMI.app/Contents/Resources/whisper/macos-arm64"
for name in $WHISPER_EXPECTED; do
    if [ ! -e "dist/$DIST_NAME/WIMI.app/Contents/Frameworks/$name" ]; then
        # The copies at the top are the ones that load. If PyInstaller ever
        # stops putting one there, the copy here may be the live one.
        echo "[ERROR] Contents/Frameworks/$name is missing, so the copy in"
        echo "        Frameworks/whisper/macos-arm64/ may be the one whisper-cli"
        echo "        loads. Not deleting anything; re-measure #388 first."
        exit 1
    fi
    rm -f "$WHISPER_BUNDLED/$name" "$WHISPER_LINKS/$name"
done
codesign --force --sign - \
    --preserve-metadata=entitlements,requirements,flags,runtime \
    "dist/$DIST_NAME/WIMI.app" || { echo "[ERROR] Re-signing failed."; exit 1; }
if ! codesign --verify --deep --strict "dist/$DIST_NAME/WIMI.app"; then
    echo "[ERROR] WIMI.app does not verify after the whisper dylibs were removed."
    exit 1
fi
if ! "$WHISPER_BUNDLED/whisper-cli" --help > /dev/null 2>&1; then
    echo "[ERROR] The bundled whisper-cli no longer starts."
    exit 1
fi
echo "Removed 6 unused whisper dylibs from the bundle; signature re-sealed and verified."

# Licence texts and the corresponding-source notice (#272). GPL-3.0 s4 requires
# the licence to be conveyed WITH the program and s6 requires the source to be
# obtainable from a stated place; Settings -> About names the licences but
# naming is not conveying, and until this the bundle carried no copyleft text at
# all. Identical line in build_windows.bat -- the logic is in the Python so the
# two scripts cannot drift the way CLAUDE.md records the two .spec files can.
python scripts/stage_license_files.py "dist/$DIST_NAME"

# Generate First-Launch.command. NOT a click-only route -- but it does work
# when invoked as `bash First-Launch.command`, which is measured (#276).
#
# THE NAME HAS NO SPACE ON PURPOSE (#276). It was "First Launch.command" until
# 2026-10-02, and the space was a trap: dragging the file into Terminal inserts
# a backslash-escaped path, and inside double quotes neither bash nor zsh reads
# `\ ` as an escape -- so a recipient who typed a quote and then dragged got
# `No such file or directory` naming a file with a backslash in it. Measured in
# bash 3.2 AND zsh 5.9, and zsh is the default shell on any Mac set up since
# Catalina, so that was the recipient's shell. With no space there is nothing to
# escape, every form works, and the docs no longer have to explain any of it.
# Do not put the space back to make the name prettier in Finder.
#
# Double-clicking it is refused exactly as the app is, because the .command file
# carries com.apple.quarantine too -- measured on a quarantined copy, and
# Control-click -> Open in Finder gave the same dialog (#179, T19 2026-09-24).
# So it must never be advertised as a click-only route.
#
# What #276 measured, on a copy where the .command AND all 4,220 bundle entries
# were quarantined: `bash First-Launch.command` ran, cleared the app's
# quarantine, launched WIMI un-translocated with its helpers and window, and
# exited 0. Only the LaunchServices paths are gated; invoking through bash reads
# the file as data and Gatekeeper never assesses it. The .command stays
# quarantined afterwards, which is harmless.
#
# The command below is `xattr -dr com.apple.quarantine`, not the `xattr -cr` it
# used until 2026-10-02. #276 measured them identical on a fresh build -- 0
# output lines each, 0 quarantine left, and the build carries no other xattrs
# for -cr's broader sweep to remove. The narrow form is preferred because a
# RECIPIENT's copy arrived by download and may carry attributes this has no
# business clearing (Finder tags, kMDItemWhereFroms), and because it is the form
# the docs tell recipients to type. Do not widen it back to -cr: it buys nothing
# measured and takes more than it needs on somebody else's machine.
#
# The docs still lead with the typed command rather than this file, because a
# student running something against a security feature can read a one-liner and
# cannot read a script they have not opened.
echo ""
echo "[6/7] Generating First-Launch.command..."
cat > "dist/$DIST_NAME/First-Launch.command" <<'LAUNCHER'
#!/bin/bash
cd "$(dirname "$0")"
echo "Preparing WIMI for first launch..."
xattr -dr com.apple.quarantine WIMI.app
echo "Done. Launching WIMI."
open WIMI.app
LAUNCHER
chmod +x "dist/$DIST_NAME/First-Launch.command"

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
echo "First-run helper: dist/$DIST_NAME/First-Launch.command"
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
# The real version, not a <version> placeholder for somebody to fill in
# (#425). A typed version is a third place the release can disagree with
# itself, and `stage_license_files.py` is the one build-time reader of
# APP_VERSION -- the same one `publish_release.py` uses to check a tag.
#
# DELIBERATELY NOT GUARDED LIKE WHISPER_TAG ABOVE, which exits on an empty
# read. That one is a build input: without it there is nothing to compile. This
# one is read AFTER the build has succeeded, and only decorates the printed
# "To distribute" advice -- so exiting here would turn a finished build into a
# failure over a filename hint.
#
# The fallback is a WORD rather than nothing, because `WIMI_mac_vunknown.zip`
# is unmissable while `WIMI_mac_v.zip` looks deliberate. Two different things
# produce it and only one is the reader's own: `--print-version` prints
# "unknown" when the parse fails, and the `-n` test below covers python being
# absent or silent, where a command substitution yields an EMPTY string and
# not "unknown". The first draft of this had only the former and its comment
# claimed both -- measured on Linux with python off PATH, which printed
# `WIMI_mac_v.zip` (the shell half of #425).
APP_VERSION="$(python scripts/stage_license_files.py --print-version)"
[ -n "$APP_VERSION" ] || APP_VERSION="unknown"

# ZIP WITH -y, ALWAYS. The .app holds 1,105 symlinks -- Qt's framework
# `Versions/Current` and `Resources` links -- and plain `zip -r` FOLLOWS
# them. Measured on a ba801a4 build:
#
#   zip -r    1,190,476,631 B  ->  unzips to 3.0 GB, 0 symlinks,
#                                  `codesign --verify --deep --strict` FAILS
#                                  ("bundle format is ambiguous")
#   zip -ry     195,382,759 B  ->  unzips to 504 MB, all 1,105 symlinks,
#                                  codesign passes
#
# So the archive is six times larger AND the app inside it is unsealed.
# This advice printed `-r` until 2026-10-11, which means anyone following
# the script's own instructions shipped a broken bundle. The macOS session
# measured it while cutting 0.2.0-beta.
echo "To distribute:"
if [ "$RELATIONS" = "1" ]; then
    # Asset naming follows the existing WIMI_mac_v0.1.0-beta.zip shape (#60).
    # Provisional but committed: the owner has approved this shape and will
    # write the release-page copy that explains what the larger download buys.
    echo "  cd dist && zip -ry WIMI_mac_relations_v${APP_VERSION}.zip $DIST_NAME"
    echo ""
    echo "This is the RELATIONS artifact: it carries the relation-extraction"
    echo "runtime and is roughly twice the size of the default one. It is a"
    echo "SEPARATE download, not a replacement -- publish both, and do not let"
    echo "this one take the default artifact's name."
else
    echo "  cd dist && zip -ry WIMI_mac_v${APP_VERSION}.zip $DIST_NAME"
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
echo "    bash /path/to/First-Launch.command"
echo ""
echo "Nobody has to know how to type a path: type  bash  with a trailing"
echo "space, then DRAG 'First-Launch.command' from Finder into the"
echo "Terminal window and press Return. Terminal fills the path in. Pass"
echo "that on -- it is the difference between an instruction a student"
echo "can follow and one they cannot."
echo ""
echo "Say that it has to be TERMINAL. 'Run First-Launch.command' on its"
echo "own reads as 'double-click it', and that is refused -- the .command"
echo "is quarantined like the app, and only Finder'\''s route is gated."
echo ""
echo "The helper does exactly two things, and it is worth telling them so"
echo "rather than asking them to trust a script they have not opened:"
echo "    xattr -dr com.apple.quarantine WIMI.app"
echo "    open WIMI.app"
echo "Anyone who would rather type those two lines gets the same result."
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
echo "Why bash and not a double-click: measured (#276). Only the"
echo "LaunchServices routes are gated, so Finder asks Gatekeeper and bash"
echo "does not ask anyone -- it reads the file as data. Verified with the"
echo ".command and all 4,220 bundle entries quarantined: cleared the app,"
echo "launched it un-translocated, exit 0."
echo "See docs/BUILD_MACOS.md, #179 and #276."
echo ""

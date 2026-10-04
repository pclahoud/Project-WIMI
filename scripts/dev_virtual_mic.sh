#!/usr/bin/env bash
# A virtual microphone for testing speech capture on a machine that has none.
#
# WHY: this project's audio capture (#59, src/app/stt/recorder.py) can only be
# tested against fakes on a box with no input device -- and "no input device"
# is the default state of a headless Linux dev box and of CI. Qt reports
# audioInputs() == 0 there, which is indistinguishable from a real machine
# whose microphone is unplugged. Every device assertion in T7 is against a
# fake for exactly this reason.
#
# WHAT: creates a PipeWire loopback -- a sink you play into and a source Qt
# enumerates as an ordinary microphone -- so audio written to the sink is
# captured by QAudioSource as if somebody had spoken it.
#
#   start   create the pair (idempotent; re-running replaces it)
#   stop    remove it, which is also how you test NO_INPUT_DEVICE
#   status  what PipeWire has and what Qt sees
#   feed    play a WAV into the mic (use --loop for a continuous signal)
#
# Verified on 2026-09-23, Ubuntu + PipeWire 1.0.5, PyQt6 6.9.1 / Qt 6.9.0:
# Qt enumerated 'VirtualMic' and a QAudioSource in PULL mode captured
# 96,256 bytes at peak 0.2957 full-scale from a real recording played in.
#
# NOT a substitute for hardware. A virtual device cannot show driver quirks,
# exclusive-mode contention (DEVICE_IN_USE), the Windows privacy toggle or
# macOS TCC, and it may negotiate formats a real device would refuse. It
# covers the plumbing, not the platform.

set -euo pipefail

SINK_NAME=virtsink
MIC_NAME=virtmic

have() { command -v "$1" >/dev/null 2>&1; }

require_pipewire() {
    have pw-loopback || {
        echo "pw-loopback not found. Install pipewire-utils / pipewire." >&2
        exit 1
    }
    pw-cli info 0 >/dev/null 2>&1 || {
        echo "Cannot reach PipeWire as $USER. Is the user session running?" >&2
        exit 1
    }
}

# Deliberately NOT `pkill -f pw-loopback`: that pattern also matches the shell
# running this script and kills its own process group (measured -- exit 144).
stop_mic() {
    local pids
    pids=$(pgrep -x pw-loopback || true)
    if [ -n "$pids" ]; then
        # shellcheck disable=SC2086
        kill $pids 2>/dev/null || true
        sleep 1
    fi
    echo "virtual mic stopped (Qt should now report zero input devices)"
}

start_mic() {
    require_pipewire
    stop_mic >/dev/null
    # setsid + disown so it outlives this shell; a plain background job dies
    # with the script and the device vanishes mid-test.
    setsid nohup pw-loopback \
        --capture-props="media.class=Audio/Sink node.name=${SINK_NAME} node.description=VirtualSink" \
        --playback-props="media.class=Audio/Source node.name=${MIC_NAME} node.description=VirtualMic" \
        >/tmp/wimi-virtual-mic.log 2>&1 </dev/null &
    disown || true
    sleep 3
    status_mic
}

status_mic() {
    echo "PipeWire nodes:"
    pw-cli ls Node 2>/dev/null | grep 'node.name' | grep -E "${SINK_NAME}|${MIC_NAME}" \
        || echo "  (none -- virtual mic is not running)"
    echo "Qt sees:"
    local py="${WIMI_PYTHON:-.venv/bin/python}"
    if [ -x "$py" ]; then
        QT_QPA_PLATFORM=offscreen "$py" -c "
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtMultimedia import QMediaDevices
app = QCoreApplication([])
names = [d.description() for d in QMediaDevices.audioInputs()]
print('  audioInputs():', names or '[] -- this is the NO_INPUT_DEVICE state')
" 2>/dev/null | grep -v '^qt\.'
    else
        echo "  (set WIMI_PYTHON or run from the repo root with .venv present)"
    fi
}

feed_mic() {
    local wav="${1:-}"
    [ -n "$wav" ] && [ -f "$wav" ] || { echo "usage: $0 feed FILE.wav [--loop]" >&2; exit 1; }
    have pw-play || { echo "pw-play not found." >&2; exit 1; }
    if [ "${2:-}" = "--loop" ]; then
        setsid nohup bash -c "while :; do pw-play --target=${SINK_NAME} '$wav' >/dev/null 2>&1; done" \
            >/dev/null 2>&1 </dev/null &
        disown || true
        echo "looping $wav into ${SINK_NAME} (stop with: $0 stop)"
    else
        # Backgrounded: the capture side must already be listening.
        setsid pw-play --target="${SINK_NAME}" "$wav" >/dev/null 2>&1 &
        disown || true
        echo "playing $wav into ${SINK_NAME}"
    fi
}

case "${1:-status}" in
    start)  start_mic ;;
    stop)   stop_mic ;;
    status) status_mic ;;
    feed)   shift; feed_mic "$@" ;;
    *)      echo "usage: $0 {start|stop|status|feed FILE.wav [--loop]}" >&2; exit 1 ;;
esac

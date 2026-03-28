#!/usr/bin/env bash

set -euo pipefail

PORTABLE_DIR="${FFMPEG_PORTABLE_DIR:-}"
PORTABLE_BIN_DIR=""

if [[ -n "${PORTABLE_DIR}" ]]; then
  PORTABLE_BIN_DIR="${PORTABLE_DIR%/}/bin"
fi

have_path_ffmpeg() {
  command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1
}

have_portable_ffmpeg() {
  [[ -n "${PORTABLE_BIN_DIR}" ]] && [[ -x "${PORTABLE_BIN_DIR}/ffmpeg" ]] && [[ -x "${PORTABLE_BIN_DIR}/ffprobe" ]]
}

append_path() {
  local dir="$1"

  if [[ -n "${GITHUB_PATH:-}" ]]; then
    printf '%s\n' "$dir" >> "${GITHUB_PATH}"
  fi

  export PATH="${dir}:${PATH}"
}

use_portable_ffmpeg() {
  append_path "${PORTABLE_BIN_DIR}"
  echo "Using portable FFmpeg toolchain from ${PORTABLE_BIN_DIR}."
  print_versions
  exit 0
}

print_versions() {
  ffmpeg -version | head -n 1
  ffprobe -version | head -n 1
}

copy_to_portable_dir() {
  if [[ -n "${PORTABLE_BIN_DIR}" ]]; then
    mkdir -p "${PORTABLE_BIN_DIR}"
    cp "$(command -v ffmpeg)" "${PORTABLE_BIN_DIR}/ffmpeg"
    cp "$(command -v ffprobe)" "${PORTABLE_BIN_DIR}/ffprobe"
    echo "Copied FFmpeg to ${PORTABLE_BIN_DIR} for artifact upload."
  fi
}

# Use cached portable build if available (artifact from a prior step)
if have_portable_ffmpeg; then
  use_portable_ffmpeg
fi

# Use pre-installed system ffmpeg if available (ubuntu-latest includes it)
if have_path_ffmpeg; then
  echo "Using preinstalled FFmpeg binaries."
  copy_to_portable_dir
  print_versions
  exit 0
fi

# Last resort: install via apt-get
export DEBIAN_FRONTEND=noninteractive

for attempt in 1 2 3; do
  echo "Installing FFmpeg via apt-get (attempt ${attempt}/3)..."

  if sudo apt-get update -o Acquire::Retries=3 && \
    sudo apt-get install -y --no-install-recommends -o Acquire::Retries=3 ffmpeg; then
    if have_path_ffmpeg; then
      echo "FFmpeg installation succeeded."
      copy_to_portable_dir
      print_versions
      exit 0
    fi
  fi

  sleep_seconds=$((attempt * 5))
  echo "FFmpeg install attempt ${attempt} failed; sleeping ${sleep_seconds}s before retry."
  sleep "${sleep_seconds}"
done

echo "Failed to install FFmpeg after 3 attempts." >&2
exit 1

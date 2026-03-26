#!/usr/bin/env bash

set -euo pipefail

PORTABLE_DIR="${FFMPEG_PORTABLE_DIR:-}"
PORTABLE_BIN_DIR=""
STATIC_URL="${FFMPEG_STATIC_URL:-https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz}"

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

install_portable_ffmpeg() {
  local scratch_root archive extract_root extracted_dir
  scratch_root="$(mktemp -d "${RUNNER_TEMP:-/tmp}/ffmpeg-static.XXXXXX")"
  archive="${scratch_root}/ffmpeg.tar.xz"
  extract_root="${scratch_root}/extract"

  for attempt in 1 2 3; do
    echo "Downloading portable FFmpeg (attempt ${attempt}/3)..."
    rm -rf "${archive}" "${extract_root}"
    mkdir -p "${extract_root}"

    if curl \
      --fail \
      --location \
      --retry 3 \
      --retry-delay 2 \
      --silent \
      --show-error \
      "${STATIC_URL}" \
      -o "${archive}" && \
      tar -xJf "${archive}" -C "${extract_root}"; then
      extracted_dir="$(find "${extract_root}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"

      if [[ -n "${extracted_dir}" ]] && [[ -x "${extracted_dir}/ffmpeg" ]] && [[ -x "${extracted_dir}/ffprobe" ]]; then
        rm -rf "${PORTABLE_DIR}"
        mkdir -p "${PORTABLE_BIN_DIR}"
        cp "${extracted_dir}/ffmpeg" "${PORTABLE_BIN_DIR}/ffmpeg"
        cp "${extracted_dir}/ffprobe" "${PORTABLE_BIN_DIR}/ffprobe"
        chmod +x "${PORTABLE_BIN_DIR}/ffmpeg" "${PORTABLE_BIN_DIR}/ffprobe"
        rm -rf "${scratch_root}"
        return 0
      fi
    fi

    sleep_seconds=$((attempt * 5))
    echo "Portable FFmpeg download attempt ${attempt} failed; sleeping ${sleep_seconds}s before retry."
    sleep "${sleep_seconds}"
  done

  rm -rf "${scratch_root}"
  return 1
}

if have_portable_ffmpeg; then
  use_portable_ffmpeg
fi

if [[ -n "${PORTABLE_DIR}" ]]; then
  echo "Preparing portable FFmpeg toolchain in ${PORTABLE_DIR}."
  if install_portable_ffmpeg; then
    use_portable_ffmpeg
  fi

  echo "Portable FFmpeg download failed; falling back to system install."
fi

if have_path_ffmpeg; then
  echo "Using preinstalled FFmpeg binaries."
  print_versions
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive

for attempt in 1 2 3; do
  echo "Installing FFmpeg (attempt ${attempt}/3)..."

  if sudo apt-get update -o Acquire::Retries=3 && \
    sudo apt-get install -y --no-install-recommends -o Acquire::Retries=3 ffmpeg; then
    if have_path_ffmpeg; then
      echo "FFmpeg installation succeeded."
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

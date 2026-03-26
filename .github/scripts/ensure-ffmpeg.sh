#!/usr/bin/env bash

set -euo pipefail

have_ffmpeg() {
  command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1
}

print_versions() {
  ffmpeg -version | head -n 1
  ffprobe -version | head -n 1
}

if have_ffmpeg; then
  echo "Using preinstalled FFmpeg binaries."
  print_versions
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive

for attempt in 1 2 3; do
  echo "Installing FFmpeg (attempt ${attempt}/3)..."

  if sudo apt-get update -o Acquire::Retries=3 && \
    sudo apt-get install -y --no-install-recommends -o Acquire::Retries=3 ffmpeg; then
    if have_ffmpeg; then
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

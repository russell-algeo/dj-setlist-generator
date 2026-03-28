#!/usr/bin/env bash
set -euo pipefail

echo "::group::Persist YouTube cookies"

if [[ -z "${YTDLP_COOKIE_FILE:-}" ]]; then
  echo "Skipping YouTube cookie persistence: YTDLP_COOKIE_FILE is not set"
  echo "::endgroup::"
  exit 0
fi

if [[ -z "${GH_PAT:-}" ]]; then
  echo "Skipping YouTube cookie persistence: GH_PAT is not configured"
  echo "::endgroup::"
  exit 0
fi

export GH_TOKEN="${GH_PAT}"

if [[ ! -s "${YTDLP_COOKIE_FILE}" ]]; then
  echo "Refreshed YouTube cookie jar missing or empty: ${YTDLP_COOKIE_FILE}"
  exit 1
fi

secret_name="${YOUTUBE_COOKIES_SECRET_NAME:-YOUTUBE_COOKIES_B64}"
echo "Persisting refreshed YouTube cookie jar bytes=$(wc -c < "${YTDLP_COOKIE_FILE}" | tr -d ' ') secret=${secret_name}"

base64 < "${YTDLP_COOKIE_FILE}" | tr -d '\n' | gh secret set "${secret_name}" --repo "${GH_REPO}"

echo "::endgroup::"

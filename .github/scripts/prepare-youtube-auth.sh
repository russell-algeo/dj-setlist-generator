#!/usr/bin/env bash
set -euo pipefail

echo "::group::Prepare YouTube auth"

cookies_present=false
user_agent_present=false

if [[ -n "${YOUTUBE_COOKIES_B64:-}" ]]; then
  printf '%s' "${YOUTUBE_COOKIES_B64}" | tr -cd 'A-Za-z0-9+/=' | base64 -d > /tmp/yt-cookies.txt
  echo "Prepared YouTube cookie jar bytes=$(wc -c < /tmp/yt-cookies.txt | tr -d ' ')"
  echo "YTDLP_COOKIE_FILE=/tmp/yt-cookies.txt" >> "$GITHUB_ENV"
  cookies_present=true
else
  echo "Prepared YouTube cookie jar: not configured"
fi

if [[ -n "${YOUTUBE_USER_AGENT:-}" ]]; then
  {
    echo "YTDLP_USER_AGENT<<__YTDLP_USER_AGENT__"
    printf '%s\n' "${YOUTUBE_USER_AGENT}"
    echo "__YTDLP_USER_AGENT__"
  } >> "$GITHUB_ENV"
  echo "Prepared YouTube user-agent: yes"
  user_agent_present=true
else
  echo "Prepared YouTube user-agent: not configured"
fi

echo "cookies_present=${cookies_present}" >> "$GITHUB_OUTPUT"
echo "user_agent_present=${user_agent_present}" >> "$GITHUB_OUTPUT"

echo "::endgroup::"

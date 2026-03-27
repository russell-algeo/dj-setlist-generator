# Findings Fixes Design

**Date:** 2026-03-26
**Status:** Approved

## Overview

Six targeted fixes stemming from an audit of the remote-deployment implementation against the original design spec. Two findings were intentionally deferred (public-site HTML rendering, Preview deployment target). Everything else is addressed here.

---

## 1. Spotify Playlist Wiring

**Problem:** The publish GitHub Actions job does not set `SET_LIST_ACTIVE_SET_RUN_ID` in its environment. `SpotifyPlaylistCreator._fetch_managed_access_token()` requires this env var to call the internal `/api/internal/spotify-token` endpoint and obtain the user's OAuth access token. Without it, the function returns `None`, the constructor falls back to the local OAuth cache flow (which does not exist in the workflow runner), and `self.spotify` is set to `None`. Playlist creation silently does nothing even when `createPlaylist: true`.

**Fix:** Add `SET_LIST_ACTIVE_SET_RUN_ID: ${{ github.event.inputs.set_run_id }}` to the `publish` job's `env` block in `.github/workflows/process-set.yml`. No Python or TypeScript changes needed — the full token-fetch and playlist-create path is already implemented.

**Files:** `.github/workflows/process-set.yml`

---

## 2. `createPlaylist` Submission Safeguard

**Problem:** `POST /api/jobs` accepts `createPlaylist: true` without checking whether the actor has an active Spotify connection. If they don't, the flag is stored, dispatched to the worker, and the playlist step silently fails.

**Fix:** In `apps/web/app/api/jobs/route.ts`, after `parseSubmissionInput`, check whether `input.createPlaylist` is `true`. If so, query `spotifyConnections` for the actor's userId to see if an active (non-revoked) connection exists. If no connection is found, set `createPlaylist` to `false` on the input and add a warning string to a `warnings` array. Pass `warnings` to the response — the submission is still created and returns 202 (already used for warnings) with `{ submissionId, warnings: ["Spotify playlist creation was disabled: no Spotify account connected"] }`. If a connection exists, proceed normally with 201.

The `createSubmission` function in `submissions.ts` does not need to change — the input is sanitized before it gets there.

**Files:** `apps/web/app/api/jobs/route.ts`

---

## 3. Spotify Disconnect

**Problem:** Users can connect and reconnect Spotify but cannot disconnect. The `revokedAt` column exists on `spotify_connections` but is never set by a user action. The settings page shows only "Connect Spotify" / "Reconnect Spotify".

**Fix — API route:** New `POST /api/spotify/disconnect` route. Requires a session actor. Finds the active `spotifyConnections` row for the actor's `userId`. Sets `revokedAt = now()` and nulls out `refreshTokenCiphertext` (so the token is not just soft-deleted but actually cleared). Returns 303 redirect to `/dashboard/settings?spotify=disconnected`, or JSON `{ ok: true }` for JSON requests.

**Fix — Settings page:** Add a "Disconnect" button in the Spotify panel, shown only when `spotifyConnection && !spotifyConnection.revokedAt`. The button posts a form to `/api/spotify/disconnect`. Display a success/error note for the `?spotify=disconnected` query param, alongside the existing `connected` / `error` cases.

No DB migration needed — `revokedAt` and `refreshTokenCiphertext` columns already exist.

**Files:** `apps/web/app/api/spotify/disconnect/route.ts` (new), `apps/web/app/dashboard/settings/page.tsx`

---

## 4. API Token Hashing (SHA-256 → scrypt)

**Problem:** `hashApiToken` uses a plain SHA-256 digest with no salt. The stored hash is fast to brute-force if the DB leaks. Token entropy is high (192 bits from `randomBytes(24)`), which limits practical risk, but a slow hash is the correct standard for stored secrets.

**Fix — Algorithm:** Replace SHA-256 with Node's built-in `crypto.scrypt`. Each token gets a unique random salt (16 bytes). The stored value in `tokenHash` is `"scrypt:<salt_hex>:<hash_hex>"` — no schema change required, the existing `text` column holds it.

**Fix — Verification:** `getBearerTokenActor` currently hashes the incoming token and compares. New flow: look up the token record by prefix, read the stored `tokenHash`, detect the format prefix (`"scrypt:"` vs. legacy), and verify accordingly. For legacy SHA-256 entries (anything not prefixed with `"scrypt:"`), the comparison will never match once the issuing code is changed — they will be treated as invalid.

**Fix — Migration:** A Drizzle SQL migration sets `revokedAt = now()` on all existing `api_tokens` rows where `revokedAt IS NULL`. This means existing tokens show as revoked in the token list and fail auth cleanly rather than silently. You will see "No active tokens yet" on the tokens page, create a new token, copy the `plainTextToken` from the JSON response shown in the new tab, and run `python -m worker.cli auth login --token <value>`.

**scrypt parameters:** `N=16384, r=8, p=1, keylen=32` — standard interactive parameters, fast enough for auth (<100ms), slow enough to make brute-force expensive.

**Files:** `apps/web/lib/security/api-tokens.ts`, `apps/web/lib/auth/session.ts`, `drizzle/migrations/<next>_revoke_sha256_tokens.sql`

---

## 5. Revalidation — Docs Only

**Problem:** The design spec describes a tag-based revalidation model. The implementation uses `revalidatePath`. The `revalidatePath` calls from `process_set.py` are not dead code — they do purge Next.js's router cache for those paths, which affects client-side navigation freshness. However, the public archive routes are `force-dynamic`, meaning Next.js has no full-route cache entry to purge; the main freshness mechanism is the HTTP `Cache-Control: public, max-age=60, stale-while-revalidate=300` header in `html-response.ts`, which governs Vercel's CDN TTL.

**Decision:** Keep `revalidatePath` as-is. Update the design doc to document the actual model: force-dynamic + CDN TTL (60s / 5min SWR) is the intentional approach for the stored-HTML phase. ISR + `revalidateTag` is the target model when the public archive pages are rebuilt as proper Next.js pages with DB queries — at that point the tag infrastructure will be added.

**Files:** `docs/claude/superpowers/specs/2026-03-24-remote-deployment-design.md` (update)

---

## 6. Design Doc Corrections

Update `docs/claude/superpowers/specs/2026-03-24-remote-deployment-design.md` to reflect actual implementation vs. original spec:

| Topic | Original Spec | Actual Implementation |
|---|---|---|
| Submission mode names | `single_set`, `artist_discovery`, `curated_artist` | `url`, `artist`, `curated_artist` |
| CLI polling default | 5s | 15s (`--interval` flag, default 15) |
| CLI auth env var | `SET_LIST_API_TOKEN` | `DJSET_API_TOKEN` (falls back to saved `~/.config/set_list_worker/auth.json`) |
| DB claim functions | Not named | `claim_next_artist_submission`, `claim_next_dispatchable_set_run`, `initialize_set_run_leases` |
| `claim_next_lease` signature | No slot_index | Requires `slot_index` parameter |
| Recognition slot default | 2 slots | Auto-tuned via scheduler; workflow input defaults to `"auto"` |
| Revalidation model | Tag-based ISR | Path-based + CDN TTL; ISR deferred to React pages phase |

**Files:** `docs/claude/superpowers/specs/2026-03-24-remote-deployment-design.md`

---

## Execution Order

1. DB migration (revoke SHA-256 tokens) — must land before the scrypt code ships so tokens aren't left in a half-valid state
2. scrypt token hashing (`api-tokens.ts`, `session.ts`)
3. Spotify workflow env var (one line in workflow YAML)
4. `createPlaylist` safeguard (`jobs/route.ts`)
5. Spotify disconnect route + settings UI
6. Design doc corrections

Items 3–5 are independent and can be done in any order or in parallel.

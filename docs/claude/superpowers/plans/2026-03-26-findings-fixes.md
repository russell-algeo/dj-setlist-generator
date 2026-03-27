# Findings Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix six audit findings: scrypt token hashing, Spotify playlist wiring, createPlaylist safeguard, Spotify disconnect, and design doc corrections.

**Architecture:** Clean-break token migration (revoke all SHA-256 tokens, new tokens use scrypt with stored salt). Spotify playlist wiring is a single env-var addition. Safeguard and disconnect are small additions to the jobs route and a new route + settings UI change. Revalidation model decision recorded in docs only.

**Tech Stack:** Next.js 14 App Router, Drizzle ORM, Node.js `crypto` (built-in scrypt), Vitest, TypeScript, GitHub Actions YAML.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `drizzle/migrations/0007_revoke_sha256_tokens.sql` | Create | Revoke all active SHA-256 tokens at migration time |
| `drizzle/migrations/meta/_journal.json` | Modify | Register new migration entry |
| `apps/web/lib/security/api-tokens.ts` | Modify | Replace SHA-256 with scrypt |
| `apps/web/lib/security/api-tokens.test.ts` | Create | Unit tests for hash/verify |
| `apps/web/lib/auth/session.ts` | Modify | Use `verifyApiToken` instead of `hashApiToken` + `safeEqualHex` |
| `.github/workflows/process-set.yml` | Modify | Add `SET_LIST_ACTIVE_SET_RUN_ID` to publish job |
| `apps/web/app/api/jobs/route.ts` | Modify | Strip `createPlaylist` + 202 warning when no Spotify connection |
| `apps/web/app/api/spotify/disconnect/route.ts` | Create | POST handler to soft-revoke Spotify connection |
| `apps/web/app/dashboard/settings/page.tsx` | Modify | Add Disconnect button and disconnected success message |
| `docs/claude/superpowers/specs/2026-03-24-remote-deployment-design.md` | Modify | Correct spec drift table |

---

### Task 1: DB migration — revoke existing SHA-256 tokens

**Files:**
- Create: `drizzle/migrations/0007_revoke_sha256_tokens.sql`
- Modify: `drizzle/migrations/meta/_journal.json`

- [ ] **Step 1: Create the migration SQL file**

Create `drizzle/migrations/0007_revoke_sha256_tokens.sql` with this exact content:

```sql
-- Revoke all active API tokens issued under the SHA-256 hashing scheme.
-- Tokens will need to be regenerated once the scrypt implementation ships.
--> statement-breakpoint
UPDATE authn.api_tokens
SET revoked_at = now(),
    updated_at = now()
WHERE revoked_at IS NULL;
```

- [ ] **Step 2: Register the migration in the journal**

Open `drizzle/migrations/meta/_journal.json`. The current last entry has `"idx": 6`. Add a new entry at the end of the `"entries"` array:

```json
{
  "idx": 7,
  "version": "7",
  "when": 1774670400000,
  "tag": "0007_revoke_sha256_tokens",
  "breakpoints": true
}
```

The `when` value is a unix timestamp in milliseconds — use a value slightly after the last entry (`1774666800000`). `1774670400000` is fine.

- [ ] **Step 3: Commit**

```bash
git add drizzle/migrations/0007_revoke_sha256_tokens.sql drizzle/migrations/meta/_journal.json
git commit -m "migration: revoke all active SHA-256 API tokens before scrypt rollout"
```

---

### Task 2: scrypt token hashing — library

**Files:**
- Modify: `apps/web/lib/security/api-tokens.ts`
- Create: `apps/web/lib/security/api-tokens.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `apps/web/lib/security/api-tokens.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { hashApiToken, issueApiToken, verifyApiToken } from "./api-tokens";

describe("hashApiToken", () => {
  it("returns a string prefixed with scrypt:", () => {
    const hash = hashApiToken("sl_sometoken");
    expect(hash.startsWith("scrypt:")).toBe(true);
  });

  it("produces different hashes for the same token (random salt)", () => {
    const h1 = hashApiToken("sl_sometoken");
    const h2 = hashApiToken("sl_sometoken");
    expect(h1).not.toBe(h2);
  });

  it("hash has three colon-separated segments: scrypt, salt, hash", () => {
    const hash = hashApiToken("sl_sometoken");
    const parts = hash.split(":");
    expect(parts).toHaveLength(3);
    expect(parts[0]).toBe("scrypt");
    expect(parts[1].length).toBeGreaterThan(0); // salt hex
    expect(parts[2].length).toBeGreaterThan(0); // hash hex
  });
});

describe("verifyApiToken", () => {
  it("returns true for a token that matches its stored hash", () => {
    const token = "sl_correcttoken";
    const stored = hashApiToken(token);
    expect(verifyApiToken(token, stored)).toBe(true);
  });

  it("returns false for a wrong token", () => {
    const stored = hashApiToken("sl_correcttoken");
    expect(verifyApiToken("sl_wrongtoken", stored)).toBe(false);
  });

  it("returns false for a legacy SHA-256 hash (no scrypt: prefix)", () => {
    const legacyHash = "a".repeat(64); // 64-char hex, no prefix
    expect(verifyApiToken("sl_anytoken", legacyHash)).toBe(false);
  });

  it("returns false for an empty stored hash", () => {
    expect(verifyApiToken("sl_anytoken", "")).toBe(false);
  });
});

describe("issueApiToken", () => {
  it("returns a plainTextToken, tokenPrefix, and tokenHash", () => {
    const result = issueApiToken();
    expect(result.plainTextToken).toMatch(/^sl_/);
    expect(result.tokenPrefix).toBe(result.plainTextToken.slice(0, 12));
    expect(result.tokenHash.startsWith("scrypt:")).toBe(true);
  });

  it("tokenHash verifies against plainTextToken", () => {
    const { plainTextToken, tokenHash } = issueApiToken();
    expect(verifyApiToken(plainTextToken, tokenHash)).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests — expect failures**

```bash
cd apps/web && npm run test -- lib/security/api-tokens.test.ts
```

Expected: multiple failures including "verifyApiToken is not a function" or similar, because `verifyApiToken` doesn't exist yet.

- [ ] **Step 3: Replace the implementation**

Replace the entire contents of `apps/web/lib/security/api-tokens.ts`:

```typescript
import { createHash, randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

const TOKEN_PREFIX_LENGTH = 12;

// scrypt parameters — N=16384 (2^14), r=8, p=1, keylen=32 bytes
const SCRYPT_N = 16384;
const SCRYPT_R = 8;
const SCRYPT_P = 1;
const SCRYPT_KEYLEN = 32;

export const createPlainApiToken = () => `sl_${randomBytes(24).toString("base64url")}`;

export const getTokenPrefix = (token: string) => token.slice(0, TOKEN_PREFIX_LENGTH);

/**
 * Hash a token using scrypt with a fresh random salt.
 * Stored format: "scrypt:<salt_hex>:<hash_hex>"
 */
export const hashApiToken = (token: string): string => {
  const salt = randomBytes(16);
  const hash = scryptSync(token, salt, SCRYPT_KEYLEN, { N: SCRYPT_N, r: SCRYPT_R, p: SCRYPT_P });
  return `scrypt:${salt.toString("hex")}:${hash.toString("hex")}`;
};

/**
 * Verify a plain token against a stored scrypt hash.
 * Returns false for any non-scrypt stored value (e.g. legacy SHA-256).
 */
export const verifyApiToken = (token: string, storedHash: string): boolean => {
  if (!storedHash.startsWith("scrypt:")) {
    return false;
  }

  const parts = storedHash.split(":");
  if (parts.length !== 3) {
    return false;
  }

  const salt = Buffer.from(parts[1], "hex");
  const expected = Buffer.from(parts[2], "hex");

  if (salt.length === 0 || expected.length !== SCRYPT_KEYLEN) {
    return false;
  }

  const actual = scryptSync(token, salt, SCRYPT_KEYLEN, { N: SCRYPT_N, r: SCRYPT_R, p: SCRYPT_P });

  return timingSafeEqual(actual, expected);
};

export const issueApiToken = () => {
  const token = createPlainApiToken();

  return {
    plainTextToken: token,
    tokenPrefix: getTokenPrefix(token),
    tokenHash: hashApiToken(token),
  };
};
```

Note: the old `hashApiToken` exported a simple SHA-256 hex string. It still exports under the same name but now returns a `"scrypt:..."` string. `session.ts` uses both the name and the comparison logic — we update that in the next task.

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd apps/web && npm run test -- lib/security/api-tokens.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/lib/security/api-tokens.ts apps/web/lib/security/api-tokens.test.ts
git commit -m "feat: replace SHA-256 token hashing with scrypt"
```

---

### Task 3: scrypt token hashing — wire into auth

**Files:**
- Modify: `apps/web/lib/auth/session.ts`

The current `getBearerTokenActor` function:
1. Hashes the incoming token with `hashApiToken` (old SHA-256)
2. Looks up by prefix
3. Compares stored hash with `safeEqualHex`

The new flow: look up by prefix, then call `verifyApiToken(plainToken, tokenRecord.tokenHash)`. The `safeEqualHex` helper and the eager `hashApiToken` call are no longer needed.

- [ ] **Step 1: Update the import in `session.ts`**

Find this line near the top of `apps/web/lib/auth/session.ts`:

```typescript
import { hashApiToken } from "@/lib/security/api-tokens";
```

Replace it with:

```typescript
import { verifyApiToken } from "@/lib/security/api-tokens";
```

- [ ] **Step 2: Remove `safeEqualHex` helper**

Delete these lines from `session.ts` (they are near the top, after the imports):

```typescript
const safeEqualHex = (left: string, right: string) => {
  const leftBuffer = Buffer.from(left, "utf8");
  const rightBuffer = Buffer.from(right, "utf8");

  if (leftBuffer.length !== rightBuffer.length) {
    return false;
  }

  return timingSafeEqual(leftBuffer, rightBuffer);
};
```

Also remove `timingSafeEqual` from the Node crypto import if it is no longer used elsewhere in the file. The import line is:

```typescript
import { timingSafeEqual } from "node:crypto";
```

Remove it entirely.

- [ ] **Step 3: Update `getBearerTokenActor`**

Find the section inside `getBearerTokenActor` that reads:

```typescript
  const tokenPrefix = plainToken.slice(0, 12);
  const tokenHash = hashApiToken(plainToken);

  const [tokenRecord] = await db
    .select({
      id: apiTokens.id,
      userId: apiTokens.userId,
      tokenHash: apiTokens.tokenHash,
      email: userProfiles.email,
      displayName: userProfiles.displayName,
      isAllowlisted: userProfiles.isAllowlisted,
      isAdmin: userProfiles.isAdmin,
    })
    .from(apiTokens)
    .innerJoin(userProfiles, eq(userProfiles.userId, apiTokens.userId))
    .where(and(eq(apiTokens.tokenPrefix, tokenPrefix), isNull(apiTokens.revokedAt)))
    .limit(1);

  if (!tokenRecord || !safeEqualHex(tokenRecord.tokenHash, tokenHash)) {
    return null;
  }
```

Replace it with:

```typescript
  const tokenPrefix = plainToken.slice(0, 12);

  const [tokenRecord] = await db
    .select({
      id: apiTokens.id,
      userId: apiTokens.userId,
      tokenHash: apiTokens.tokenHash,
      email: userProfiles.email,
      displayName: userProfiles.displayName,
      isAllowlisted: userProfiles.isAllowlisted,
      isAdmin: userProfiles.isAdmin,
    })
    .from(apiTokens)
    .innerJoin(userProfiles, eq(userProfiles.userId, apiTokens.userId))
    .where(and(eq(apiTokens.tokenPrefix, tokenPrefix), isNull(apiTokens.revokedAt)))
    .limit(1);

  if (!tokenRecord || !verifyApiToken(plainToken, tokenRecord.tokenHash)) {
    return null;
  }
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd apps/web && npx tsc --noEmit
```

Expected: no errors. If there are errors about `timingSafeEqual` still being imported/used, double-check step 2.

- [ ] **Step 5: Commit**

```bash
git add apps/web/lib/auth/session.ts
git commit -m "feat: wire scrypt verification into bearer token auth"
```

---

### Task 4: Spotify playlist wiring

**Files:**
- Modify: `.github/workflows/process-set.yml`

The `publish` job has an `env:` block starting around line 180. It needs one new entry.

- [ ] **Step 1: Add the env var to the publish job**

Find the `env:` block under the `publish:` job in `.github/workflows/process-set.yml`. It currently reads:

```yaml
    env:
      DATABASE_URL_DIRECT: ${{ github.event.inputs.deployment_target == 'production' && secrets.PRODUCTION_DATABASE_URL_DIRECT || secrets.DEVELOPMENT_DATABASE_URL_DIRECT }}
      APP_BASE_URL: ${{ github.event.inputs.deployment_target == 'production' && secrets.PRODUCTION_APP_BASE_URL || secrets.DEVELOPMENT_APP_BASE_URL }}
      INTERNAL_WORKER_SHARED_SECRET: ${{ secrets.INTERNAL_WORKER_SHARED_SECRET }}
      SPOTIFY_CLIENT_ID: ${{ secrets.SPOTIFY_CLIENT_ID }}
      SPOTIFY_CLIENT_SECRET: ${{ secrets.SPOTIFY_CLIENT_SECRET }}
      SPOTIFY_REDIRECT_URI: ${{ secrets.SPOTIFY_REDIRECT_URI }}
      DISCOGS_TOKEN: ${{ secrets.DISCOGS_TOKEN }}
      DISCOGS_CONSUMER_KEY: ${{ secrets.DISCOGS_CONSUMER_KEY }}
      DISCOGS_CONSUMER_SECRET: ${{ secrets.DISCOGS_CONSUMER_SECRET }}
      ENABLE_DISCOGS: "true"
      ENABLE_CHECKPOINTS: "false"
```

Add one line immediately after `INTERNAL_WORKER_SHARED_SECRET`:

```yaml
    env:
      DATABASE_URL_DIRECT: ${{ github.event.inputs.deployment_target == 'production' && secrets.PRODUCTION_DATABASE_URL_DIRECT || secrets.DEVELOPMENT_DATABASE_URL_DIRECT }}
      APP_BASE_URL: ${{ github.event.inputs.deployment_target == 'production' && secrets.PRODUCTION_APP_BASE_URL || secrets.DEVELOPMENT_APP_BASE_URL }}
      INTERNAL_WORKER_SHARED_SECRET: ${{ secrets.INTERNAL_WORKER_SHARED_SECRET }}
      SET_LIST_ACTIVE_SET_RUN_ID: ${{ github.event.inputs.set_run_id }}
      SPOTIFY_CLIENT_ID: ${{ secrets.SPOTIFY_CLIENT_ID }}
      SPOTIFY_CLIENT_SECRET: ${{ secrets.SPOTIFY_CLIENT_SECRET }}
      SPOTIFY_REDIRECT_URI: ${{ secrets.SPOTIFY_REDIRECT_URI }}
      DISCOGS_TOKEN: ${{ secrets.DISCOGS_TOKEN }}
      DISCOGS_CONSUMER_KEY: ${{ secrets.DISCOGS_CONSUMER_KEY }}
      DISCOGS_CONSUMER_SECRET: ${{ secrets.DISCOGS_CONSUMER_SECRET }}
      ENABLE_DISCOGS: "true"
      ENABLE_CHECKPOINTS: "false"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/process-set.yml
git commit -m "fix: inject SET_LIST_ACTIVE_SET_RUN_ID so publish job can fetch user Spotify token"
```

---

### Task 5: `createPlaylist` safeguard

**Files:**
- Modify: `apps/web/app/api/jobs/route.ts`

When `createPlaylist: true` is submitted and the actor has no active Spotify connection, strip the flag and return a 202 with a warning instead of a 201. The submission is still created and dispatched — only the playlist preference is downgraded.

- [ ] **Step 1: Add the Spotify connection import**

Open `apps/web/app/api/jobs/route.ts`. Add `getSpotifyConnectionForUser` to the session import:

```typescript
import { assertAllowlisted, getRequestActor, getSpotifyConnectionForUser } from "@/lib/auth/session";
```

The current import line only imports `assertAllowlisted` and `getRequestActor`. Keep the rest of the imports unchanged.

- [ ] **Step 2: Add the safeguard check**

The current `POST` handler body after `parseSubmissionInput` reads:

```typescript
  const { submission, warnings } = await createSubmission(actor!, input);
  await dispatchPendingWork();
```

Replace that section with:

```typescript
  const submissionWarnings: string[] = [];

  if (input.createPlaylist) {
    const spotifyConnection = await getSpotifyConnectionForUser(actor!.userId);
    const hasActiveConnection = spotifyConnection && !spotifyConnection.revokedAt;
    if (!hasActiveConnection) {
      input = { ...input, createPlaylist: false };
      submissionWarnings.push(
        "Spotify playlist creation was disabled: no Spotify account connected. Connect Spotify in Settings and resubmit to enable playlists.",
      );
    }
  }

  const { submission, warnings: submissionErrors } = await createSubmission(actor!, input);
  const warnings = [...submissionWarnings, ...submissionErrors];
  await dispatchPendingWork();
```

Note: `input` was declared with `const` in the original — change its declaration from `const input` to `let input` a few lines above this block. Find:

```typescript
  const input = parseSubmissionInput({
```

Change to:

```typescript
  let input = parseSubmissionInput({
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd apps/web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/app/api/jobs/route.ts
git commit -m "fix: strip createPlaylist and warn when no Spotify connection at submission time"
```

---

### Task 6: Spotify disconnect route

**Files:**
- Create: `apps/web/app/api/spotify/disconnect/route.ts`

- [ ] **Step 1: Create the route file**

Create `apps/web/app/api/spotify/disconnect/route.ts`:

```typescript
import { NextResponse } from "next/server";

import { eq } from "drizzle-orm";

import { requireSessionActor } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import { spotifyConnections } from "@/lib/db/schema";

const db = getDb();

export async function POST(request: Request) {
  const actor = await requireSessionActor("/dashboard/settings");

  await db
    .update(spotifyConnections)
    .set({
      revokedAt: new Date(),
      refreshTokenCiphertext: null,
      updatedAt: new Date(),
    })
    .where(eq(spotifyConnections.userId, actor.userId));

  if ((request.headers.get("content-type") ?? "").includes("application/json")) {
    return NextResponse.json({ ok: true });
  }

  return NextResponse.redirect(new URL("/dashboard/settings?spotify=disconnected", request.url), {
    status: 303,
  });
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd apps/web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/app/api/spotify/disconnect/route.ts
git commit -m "feat: add Spotify disconnect route (POST /api/spotify/disconnect)"
```

---

### Task 7: Settings page — disconnect button and status messages

**Files:**
- Modify: `apps/web/app/dashboard/settings/page.tsx`

Two additions:
1. A "Disconnect" form button shown only when an active connection exists.
2. Status messages for the `?spotify=disconnected` query param (alongside the existing `connected`, `error` etc. cases).

- [ ] **Step 1: Add `searchParams` prop and status message**

The current page signature is:

```typescript
export default async function DashboardSettingsPage() {
```

Replace it with:

```typescript
type DashboardSettingsPageProps = {
  searchParams: Promise<{ spotify?: string }>;
};

export default async function DashboardSettingsPage({ searchParams }: DashboardSettingsPageProps) {
  const { spotify: spotifyParam } = await searchParams;
```

Then directly after the `getSpotifyConnectionForUser` call, add a status message variable:

```typescript
  const spotifyStatusMessage = (() => {
    if (spotifyParam === "connected") return "Spotify connected successfully.";
    if (spotifyParam === "disconnected") return "Spotify disconnected.";
    if (spotifyParam === "error") return "Spotify connection failed. Please try again.";
    if (spotifyParam === "invalid_state") return "Spotify connection failed: invalid state. Please try again.";
    if (spotifyParam === "missing_config") return "Spotify OAuth is not configured on this deployment.";
    if (spotifyParam === "token_error") return "Spotify token exchange failed. Please try again.";
    if (spotifyParam === "profile_error") return "Could not fetch your Spotify profile. Please try again.";
    return null;
  })();
```

- [ ] **Step 2: Render status message and disconnect button**

Find the Spotify article section. The current content is:

```tsx
        <article className="panel">
          <h2>Spotify</h2>
          {spotifyConnection && !spotifyConnection.revokedAt ? (
            <>
              <p>Connected as {spotifyConnection.spotifyUserId}</p>
              <p className="muted">Last refresh: {formatTimestamp(spotifyConnection.lastRefreshAt)}</p>
            </>
          ) : (
            <p className="muted">No Spotify account connected yet.</p>
          )}

          <div className="inline-actions" style={{ marginTop: 18 }}>
            <Link className="pill-link" href="/api/spotify/start">
              {spotifyConnection && !spotifyConnection.revokedAt ? "Reconnect Spotify" : "Connect Spotify"}
            </Link>
            <Link className="pill-link" href="/dashboard/tokens">
              Manage API tokens
            </Link>
          </div>
        </article>
```

Replace it with:

```tsx
        <article className="panel">
          <h2>Spotify</h2>
          {spotifyStatusMessage ? (
            <p className="muted" style={{ marginBottom: 12 }}>{spotifyStatusMessage}</p>
          ) : null}
          {spotifyConnection && !spotifyConnection.revokedAt ? (
            <>
              <p>Connected as {spotifyConnection.spotifyUserId}</p>
              <p className="muted">Last refresh: {formatTimestamp(spotifyConnection.lastRefreshAt)}</p>
            </>
          ) : (
            <p className="muted">No Spotify account connected yet.</p>
          )}

          <div className="inline-actions" style={{ marginTop: 18 }}>
            <Link className="pill-link" href="/api/spotify/start">
              {spotifyConnection && !spotifyConnection.revokedAt ? "Reconnect Spotify" : "Connect Spotify"}
            </Link>
            {spotifyConnection && !spotifyConnection.revokedAt ? (
              <form action="/api/spotify/disconnect" method="post">
                <button className="button button--ghost" type="submit">
                  Disconnect Spotify
                </button>
              </form>
            ) : null}
            <Link className="pill-link" href="/dashboard/tokens">
              Manage API tokens
            </Link>
          </div>
        </article>
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd apps/web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/app/dashboard/settings/page.tsx
git commit -m "feat: add Spotify disconnect button and status messages to settings page"
```

---

### Task 8: Update design doc

**Files:**
- Modify: `docs/claude/superpowers/specs/2026-03-24-remote-deployment-design.md`

- [ ] **Step 1: Find and update the spec drift section**

Open `docs/claude/superpowers/specs/2026-03-24-remote-deployment-design.md`. Search for the section that references mode names (look for `single_set`, `artist_discovery`, or the jobs schema section).

Add a correction notice near the top of the document (after the title/date) or in the relevant sections. The simplest approach is to prepend an **Implementation Notes** section immediately after the document header:

```markdown
## Implementation Notes (as-built corrections)

The following details differ from the original spec. The as-built behavior is correct; this section records what changed.

| Topic | Original Spec | As Built |
|---|---|---|
| Submission mode names | `single_set`, `artist_discovery`, `curated_artist` | `url`, `artist`, `curated_artist` |
| CLI polling default | 5 s | 15 s (`--interval` flag, adjustable) |
| CLI auth env var | `SET_LIST_API_TOKEN` | `DJSET_API_TOKEN` (or saved token in `~/.config/set_list_worker/auth.json`) |
| DB claim helpers | Not named | `claim_next_artist_submission`, `claim_next_dispatchable_set_run`, `initialize_set_run_leases` |
| `claim_next_lease` | No slot_index arg | Requires `slot_index` parameter |
| Recognition slot default | 2 | Auto-tuned via scheduler; workflow input defaults to `"auto"` |
| Revalidation model | Tag-based ISR | `force-dynamic` + CDN TTL (60 s / 5 min SWR). `revalidatePath` calls kept for router cache hygiene. ISR + `revalidateTag` is the target when public archive pages are rebuilt as Next.js pages with real DB queries. |
| API token hashing | Salted slow hash (argon2id / scrypt) | scrypt (N=16384, r=8, p=1) with per-token random salt stored as `scrypt:<salt_hex>:<hash_hex>` |
```

- [ ] **Step 2: Commit**

```bash
git add docs/claude/superpowers/specs/2026-03-24-remote-deployment-design.md
git commit -m "docs: record as-built corrections in remote-deployment design spec"
```

---

## Run all tests after completion

```bash
cd apps/web && npm run test
```

Expected: the scrypt tests pass; no other test regressions (there are no other test files currently).

## Manual smoke test checklist

After deploying (or running `next dev`):

1. **Token migration**: Run `npm run db:migrate` from `apps/web`. Confirm the migration runs without error.
2. **Token regeneration**: Go to `/dashboard/tokens`. Confirm "No active tokens yet." Create a new token, copy the `plainTextToken` from the JSON response tab. Run `python -m worker.cli auth login --token <value>`. Run `python -m worker.cli --status <any-id>` to confirm 404 (not 401).
3. **Spotify disconnect**: Go to `/dashboard/settings`. If connected, click "Disconnect Spotify". Confirm the page reloads with "Spotify disconnected." and the connection panel shows "No Spotify account connected yet."
4. **createPlaylist safeguard**: With no Spotify connection, submit a job via the API with `createPlaylist: true`. Confirm the response is HTTP 202 with `warnings` array containing the Spotify message, and the job is created.
5. **Spotify playlist wiring**: Submit a job with `createPlaylist: true` while connected to Spotify. Confirm a playlist is created in your Spotify account after the run completes. (Requires a full pipeline run in the workflow.)

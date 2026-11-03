# Vercel Deployment Runbook

This document describes the checked-in DJ Setlist Generator deployment contract. It records durable architecture, configuration names, and verification steps. Current deployment state belongs to Vercel, GitHub Actions, Neon, and the live repository.

## Architecture

The deployed product is intentionally split across three systems:

| System | Responsibility |
| --- | --- |
| Vercel project `dj-setlist-generator` | Next.js web application, authentication, archive/search UI, API/control plane, internal worker callbacks, and cache revalidation |
| Neon | Application data, operations tables, queued submissions, set-run leases, recognition results, and published archive data |
| GitHub Actions | Long-running media discovery, audio preparation, FFmpeg, segment recognition, enrichment, and publication work |

Vercel does not run the media-recognition pipeline. Its role is intentionally short-running: accept user work, persist/dispatch state, expose status, and accept authenticated callbacks from Actions.

### Runtime flow

1. The Vercel Next.js app accepts a set or artist submission and writes operational state to Neon.
2. The app dispatches `process-set.yml` or `discover-artist.yml` through the GitHub Actions API. The dispatch includes a derived `deployment_target`.
3. GitHub Actions selects the matching development or production database and app URL secret.
4. `process-set.yml` runs four stages: bootstrap, matrix recognition, publish, and finalize. It uses short-lived artifacts to hand prepared media/runtime files from bootstrap to recognition slots.
5. `discover-artist.yml` performs discovery, creates/deduplicates queued set runs, then asks the app to dispatch pending work.
6. Actions and workers call Vercel internal routes with `x-internal-secret`; these routes publish results, finalize workflow state, dispatch pending work, and revalidate public pages.
7. `scheduler.yml` runs every 15 minutes and calls the Vercel internal scheduler. Scheduled invocations target production; manually dispatched invocations can select development or production.

## Verified Vercel topology

| Property | Value |
| --- | --- |
| Vercel project | `dj-setlist-generator` |
| Vercel root directory | `apps/web` |
| Framework | Next.js |
| Node runtime | `20.x` |
| Production alias | `https://dj-setlist-generator.vercel.app` |
| Region observed in production bundle | `iad1` |

The repository’s default integration branch is `remote-deployment`. The production Vercel alias was verified as a `Ready` deployment built from the matching Git branch alias.

## Vercel environment contract

Never retrieve, print, commit, or copy environment values into this repository. Inspect variable names/scopes with the Vercel CLI, and change values only with explicit approval.

### Required categories

- **Application/database:** `APP_ENVIRONMENT`, `APP_BASE_URL`, `DATABASE_URL`, `DATABASE_URL_DIRECT`, `DATABASE_URL_MIGRATIONS`
- **Authentication/session security:** `AUTH_SECRET`, `TOKEN_ENCRYPTION_KEY`, `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`, optional `NEXTAUTH_URL`
- **Spotify integration:** `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`
- **Vercel-to-GitHub dispatch:** `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_DISPATCH_TOKEN`, `GITHUB_WORKFLOW_PROCESS_SET`, `GITHUB_WORKFLOW_DISCOVER_ARTIST`, `GITHUB_WORKFLOW_REF`
- **Vercel-to-worker authentication:** `INTERNAL_WORKER_SHARED_SECRET`
- **Administration and capacity:** `INITIAL_ADMIN_EMAIL`, optional `PROCESS_SET_MAX_ACTIVE_RUNS` (defaults to 10 in code)

The application treats `APP_ENVIRONMENT=production` as the production dispatch target. Any other value, including Vercel preview, maps to the development dispatch target. `NEXTAUTH_URL` falls back to `APP_BASE_URL` when absent.

### GitHub Actions secrets

The worker cannot use Vercel environment values directly. GitHub repository secrets must independently provide the correct target values:

- development and production pooled/direct/migration Neon URLs;
- development and production public app URLs;
- `INTERNAL_WORKER_SHARED_SECRET`;
- Spotify and Discogs credentials needed by worker enrichment/playlists;
- YouTube authentication material where enabled.

Keep the Vercel app URL and GitHub Actions target aligned. A production Vercel request that dispatches Actions against a development app/database—or the inverse—creates an inconsistent control plane.

## Local CLI setup

Only `apps/web` is a Vercel deployment root:

```bash
cd apps/web
vercel link
```

Confirm that the link targets the existing `dj-setlist-generator` project before accepting. Linking creates ignored `.vercel/project.json` metadata only; it does not deploy, modify remote settings, or pull environment values.

Do **not** run `vercel` from the repository root. The root package scripts currently call `vercel deploy` directly, but the README correctly warns that a root invocation can create or target an unintended project. Until those scripts are corrected, invoke the CLI from `apps/web` explicitly.

## Build and validation

Before a deployment-sensitive change:

```bash
pnpm --filter web lint
pnpm --filter web test
pnpm --filter web build
python3 -m unittest discover -s tests -q
python3 -m compileall worker
python3 -m worker.cli --help
```

Use focused checks first when a change affects only the web app or worker, then run the full relevant set when a change crosses Vercel, Neon, or workflow boundaries.

### Archive-content deployment rule

The Next.js application serves checked-in generated pages from `apps/web/public`, not the git-ignored `output/` directory. After regenerating archive HTML:

```bash
python3 backfill_html.py --master
APP_BASE_URL=https://dj-setlist-generator.vercel.app pnpm --filter web archive:stage
```

Review the resulting `apps/web/public` diff before committing. A Git-triggered Vercel build cannot include generated files left only in `output/`.

### End-to-end non-production check

1. Identify the preview app alias and verify its Vercel environment has the required preview values.
2. Verify its `APP_ENVIRONMENT` yields the expected development workflow target.
3. Confirm the matching GitHub Actions development secrets point to the same non-production Neon/app topology.
4. Sign in and confirm `/artists`, `/sets`, and the dashboard load.
5. Submit one safe test URL or artist request.
6. Verify the Vercel app dispatches `process-set.yml` or `discover-artist.yml`.
7. Verify the workflow updates Neon, calls the authenticated internal endpoints, and the Vercel UI shows the final state.
8. Verify Spotify only after the callback URL for that exact public alias has been registered.

## Deployment safety

- Preview deployments, Vercel environment changes, production deployments, aliases/domains, database migrations, workflow dispatches that process external media, and public actions require Russell’s approval immediately before the action.
- Do not use `--prod`, `--yes`, `--force`, or inline environment values to bypass that approval.
- Do not use Vercel Cron for worker orchestration; GitHub Actions owns the 15-minute scheduler and long-running pipeline.
- Do not pull remote environment values into local files without explicit approval of the destination and secret-handling risk.

## Live-state audit notes

Last audited from the Vercel CLI on 2026-08-10:

- The production alias was `Ready`; the deployed Next.js bundle reported 80+ output items in `iad1`.
- Vercel has development, preview, and production database/application configuration entries. Encrypted values were intentionally not retrieved, so target alignment must be verified per deployment before consequential testing.
- Local clones are not Vercel-linked by default. Link only `apps/web` as described above; never copy another clone's `.vercel` metadata or credentials.

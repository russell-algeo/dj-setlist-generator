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

### Protected development worker callbacks

Development workers use `DEVELOPMENT_INTERNAL_WORKER_SHARED_SECRET`; production
keeps `INTERNAL_WORKER_SHARED_SECRET`. Set the development value as
`INTERNAL_WORKER_SHARED_SECRET` in Vercel **Preview only**. Missing development
credentials fail before media processing and never fall back to the production
callback credential. The development app origin must match
`WORKER_EXPECTED_PREVIEW_ORIGIN` in the workflows.

Vercel Deployment Protection stays enabled. Configure GitHub Actions as a
Trusted Source for **Preview only**, scoped to this repository, the selected
preview worker branch, and each workflow (`process-set`, `discover-artist`,
`scheduler`). Use audience `https://github.com/russell-algeo`. Changing this trust
rule grants access and requires authorization. Workers mint a fresh short-lived
GitHub OIDC token for each callback, including finalization after a long job;
they never persist it or follow callback redirects. The workflow needs
`contents: read` and `id-token: write`.

### Shared Actions development branch

Preview and Production share this GitHub repository, workflow definitions and
repository dispatch control. Preview runs `codex/preview-worker-isolation`;
Production continues to run its current release on `remote-deployment`. Set both
Preview's deployment source and `GITHUB_WORKFLOW_REF` to the development branch.
Verify the deployed web SHA and each workflow's `head_sha` after publishing.
GitHub checks out the dispatched event commit; no merge into Production is needed
to test worker code. Record the tested commit before further branch updates.

Preview uses the Neon development branch and its existing `set_list_dev_app`
role. Workers use only `set_list_dev_worker` on the development endpoint. The
worker validates that exact host, role and database before connecting, and
rejects connection overrides, insecure transport, and production/migration URL
fallbacks. Missing development secrets fail closed.

Production credentials remain repository secrets. Trusted development workflow
code can therefore request them, and the shared dispatch token can cancel
Production runs. This is the accepted trust model, not a hard security boundary.
Concurrency groups include branch and deployment target to prevent accidental
collisions between normal Preview and Production jobs with the same run UUID.
Do not claim this prevents deliberate cancellation through GitHub's API.

Development does not load Production YouTube cookies. The persistence step is
Production-only, and the script separately requires an explicit production target
before invoking GitHub. Spotify and Discogs metadata credentials remain shared,
so their quotas and client revocation can affect both environments. Public media
and Shazam requests can also encounter shared provider/IP throttling.

The only new callback credential is `DEVELOPMENT_INTERNAL_WORKER_SHARED_SECRET`
in GitHub, matched by Vercel Preview's `INTERNAL_WORKER_SHARED_SECRET`. Production
keeps its existing callback secret. Configure Vercel Preview-only OIDC trust for
repository `russell-algeo/dj-setlist-generator`, branch
`codex/preview-worker-isolation`, and workflows `process-set`, `discover-artist`,
and `scheduler`; issuer `https://token.actions.githubusercontent.com`, audience
`https://github.com/russell-algeo`. Preserve existing trust and deployment
protection. New credentials and trust require precise action-time confirmation.

After those approvals, restore the existing repository dispatch credential to
Vercel Preview, set its workflow ref to the development branch, and deploy that
same branch to the stable Preview alias. No new repository, dispatcher, OAuth
client, production secret migration, billing upgrade or production deployment is
part of this setup.

### Validation and rollback

Start with one new bounded URL through normal Preview app intake, one active set
and one recognition slot. Set playlist creation false and do not send test
notifications. Verify development submission/run IDs, workflow branch/head SHA,
bootstrap/download, recognition, publication, callback finalization, browser
reload and development database persistence. Then test bounded artist discovery
and failed-job finalization. Scheduled scheduler invocations remain Production;
manual development invocations use development callback authentication.

Use a public source suitable for anonymous download. Provider rejection must be
reported without importing Production cookies. Do not rerun old development-
target jobs which originally used the Production database. If callback
protection fails, inspect the development job and reconcile only its IDs.

Standard public GitHub-hosted runners are free, but Neon, Vercel, provider and
GitHub storage/capacity allowances remain shared. Keep short artifact retention,
bounded work and no unattended Preview cron. Verify allowance before processing;
do not enable paid runners, upgrades or overage.

Google and Spotify OAuth clients are intentionally shared with distinct callback
URLs. Google Preview sign-in has passed; the Spotify callback is saved but its
sign-in test remains pending. Sessions and tokens live in Development; the last
READ ONLY aggregate check found zero active Spotify connections, zero unexpired
sessions, zero account refresh tokens and one account access-token field. No
token values or identities were read. Spotify exports still affect a real user
account, so they are outside the initial worker validation.

For rollback, disable Preview dispatch first, allow its active runs to finish,
then restore the prior Preview deployment/ref as needed. Do not revoke a shared
GitHub/provider credential to roll back Preview. Remove only newly created
Preview trust/secret settings if explicitly requested. Production routing remains
unchanged throughout.

Local validation: 104 Python tests, all three workflow actionlint checks and
`git diff --check` passed. These cover wrong DB/role/override rejection before
connection, wrong app origin rejection before HTTP, missing OIDC/secret failures,
branch/environment concurrency and cookie-script refusal for development even
when given a test token. Live activation and end-to-end processing remain pending.

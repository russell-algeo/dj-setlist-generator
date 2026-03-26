# Remote Deployment Handoff

## Current State
- Branch: `remote-deployment`
- Web app root: `apps/web`
- Worker package: `worker`
- Database:
  - Neon `development` branch is migrated and seeded with the historical archive
  - Imported data shape in development:
    - `475` canonical sets
    - `478` set-artist relationships
    - `501` stored legacy pages
- Validation completed:
  - `pnpm --dir apps/web exec tsc --noEmit`
  - `pnpm --dir apps/web build`
  - `python3 -m unittest discover -s tests -q`
  - `python3 -m compileall worker`
  - `python3 -m worker.cli --help`
  - Browser validation for `/artists`, `/artists/[slug]`, and `/sets/[slug]`

## Vercel Project Setup
1. Create a new Vercel project from this GitHub repository.
2. Set the project root directory to `apps/web`.
3. Use Node `20.x`.
4. For the first deploy, deploy the `remote-deployment` branch.
5. After the first deploy finishes, copy the generated `https://<project>.vercel.app` URL.

## Vercel Environment Variables
Set these in Vercel before production use.

### Required for the app
- `APP_BASE_URL`
  - Production: `https://<project>.vercel.app` or your final custom domain
- `DATABASE_URL`
  - Production: Neon `production` pooled URL
  - Preview / development: Neon `development` pooled URL
- `DATABASE_URL_MIGRATIONS`
  - Production: Neon `production` direct URL
  - Preview / development: Neon `development` direct URL
- `AUTH_SECRET`
  - Generate with `openssl rand -base64 32`
- `TOKEN_ENCRYPTION_KEY`
  - Generate with `openssl rand -base64 32`
- `INTERNAL_WORKER_SHARED_SECRET`
  - Generate with `openssl rand -base64 32`
- `GITHUB_OWNER`
  - `russell-algeo`
- `GITHUB_REPO`
  - repository name for this project
- `GITHUB_DISPATCH_TOKEN`
  - existing GitHub token with `repo` and `workflow`
- `GITHUB_WORKFLOW_PROCESS_SET`
  - `process-set.yml`
- `GITHUB_WORKFLOW_DISCOVER_ARTIST`
  - `discover-artist.yml`
- `INITIAL_ADMIN_EMAIL`
  - `russellalgeo@gmail.com`

### Required once Google OAuth is created
- `AUTH_GOOGLE_ID`
- `AUTH_GOOGLE_SECRET`

### Required once Spotify remote playlist creation is enabled
- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REDIRECT_URI`
  - `https://<project>.vercel.app/api/spotify/callback`

### Helpful explicit override
- `APP_ENVIRONMENT`
  - Production: `production`
  - Preview / development: `development`

## GitHub Actions Secrets
The workflows now support both development and production dispatch targets.

Add these repository secrets:
- `DEVELOPMENT_DATABASE_URL_POOLED`
- `DEVELOPMENT_DATABASE_URL_DIRECT`
- `DEVELOPMENT_APP_BASE_URL`
- `PRODUCTION_DATABASE_URL_POOLED`
- `PRODUCTION_DATABASE_URL_DIRECT`
- `PRODUCTION_APP_BASE_URL`
- `INTERNAL_WORKER_SHARED_SECRET`
- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REDIRECT_URI`
- `DISCOGS_TOKEN`
- `DISCOGS_CONSUMER_KEY`
- `DISCOGS_CONSUMER_SECRET`
- `AUTH_SECRET`
- `TOKEN_ENCRYPTION_KEY`

## OAuth Callbacks

### Google
Create a Google OAuth web app after the first Vercel deploy exists.

Authorized redirect URI:
- `https://<project>.vercel.app/api/auth/callback/google`

### Spotify
Update the existing Spotify app after the first Vercel deploy exists.

Redirect URI:
- `https://<project>.vercel.app/api/spotify/callback`

## Workflow Targeting
- The app dispatches GitHub workflows with a `deployment_target`.
- Production Vercel deployments dispatch with `production`.
- Local, preview, and development environments dispatch with `development`.
- The scheduled GitHub workflow defaults to `production`.

## Recommended Post-Deploy Checks
1. Sign in with `russellalgeo@gmail.com`.
2. Confirm `/dashboard` loads and shows admin access.
3. Confirm `/artists` and `/sets` load from the deployed app.
4. Submit one URL job from the dashboard.
5. Verify the app dispatches `process-set.yml` or `discover-artist.yml`.
6. Confirm the workflow updates Neon and the dashboard job detail page.
7. Confirm Spotify connect only after the callback URL is registered.

## Security Cleanup
- Rotate the Neon password because the initial connection strings were shared in chat.

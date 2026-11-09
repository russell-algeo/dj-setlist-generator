# Deployment, Preview validation, and recovery

This is the operational runbook for the existing `russell-algeo/dj-setlist-generator` repository and Vercel project `dj-setlist-generator`. Read `AGENTS.md` before changing source or committing. This document is not authorization to deploy, change access, migrate data, or incur charges. Use the current task's authorization and applicable confirmation rules.

## Permanent Preview branch migration

Russell requested `preview` as the permanent development branch on 2026-11-09. Authorized direct pushes to `preview` require no PR or review; commits still require an explicit user request under `AGENTS.md`. Agents develop and test there, then propose a PR with one approving GitHub review into the current main/Production branch, `remote-deployment`. Keep `preview` after merges. Do not create a branch named `main` or rename Production as part of this change. The [README workflow](README.md#development-and-release-workflow) is the intended ongoing process.

**Historical branch-migration baseline, observed 2026-11-09 before cutover:**

- Production/mainline: `remote-deployment` at `57734820de733a76a032846538979b679a4edd02` (PR #30), READY deployment `dpl_93FnGkVUC8DukJ5Tyzjy76umfWEE`.
- Reviewed repair candidate: open draft [PR #31](https://github.com/russell-algeo/dj-setlist-generator/pull/31), head `be84b9b755b39ed43bae6b3e38cd39c22d21d9e2`; its separate Vercel Preview build `dpl_AVnxwiEqQpw3K5TXsmMwdZMTvuAg` is READY. It is not the stable Preview alias or a Production release.
- Existing Preview worker ref: `codex/preview-worker-isolation` at `6e522e9c55547334b77a8cf0e681ac5cc3b6ea6f`. The Preview-scoped `GITHUB_WORKFLOW_REF` still names this branch, with no branch-specific override. `APP_ENVIRONMENT=preview` resolves to the development worker target.
- Stable Preview alias: `dj-setlist-generator-listened-preview.vercel.app`, still on `dpl_HLExpWtjnfwAc8X68QwwrfoS8iJH`, source `76c5e994e7b044e8e0f7b3a4d42f1c9d901df509`. It is a deployment alias, not an automatically advancing branch domain.
- The remote `preview` ref now exists at the reviewed PR #31 head `be84b9b755b39ed43bae6b3e38cd39c22d21d9e2`; no existing ref was overwritten. At this baseline, routing, trust and stable-alias cutover were pending. Branch creation alone is not migration completion. Recheck the live configuration and release evidence rather than treating these historical deployment IDs as the latest state.

### Neutral hostname checkpoint (2026-11-09 UTC)

- The permanent worker branch is `preview`. The canonical [neutral Preview branch alias](https://dj-setlist-generator-git-preview-russell-algeos-projects.vercel.app) advances automatically after successful Preview builds. No PR is needed to push to `preview`; Production remains `remote-deployment` with a PR and one approving review. No branch protections were changed.
- Runtime commit `cfa97dec778fae7ee547d43075d7880ae76b0856` built READY as `dpl_Cfyv8Y1NFH8vnvpa3qon3zDVpuMT`. Preview `APP_BASE_URL`, `NEXTAUTH_URL`, GitHub `DEVELOPMENT_APP_BASE_URL`, and all six exact workflow-origin constants use the neutral origin. The two exact NextAuth Google/Spotify redirect URLs were added to the existing clients; no scopes or credentials changed.
- Google OAuth returned to the neutral origin as the expected account, and reload preserved the app session and existing Spotify connection. A later, explicitly authorized fresh Spotify OAuth roundtrip and reload also passed at `0d86749`, followed by DJ-app sign-out and explicit Google sign-in to restore Hal’s identity. Spotify recorded the connection update at `02:26:08.863Z`; final Hal restoration/reload completed before `02:27:42Z`. No new consent, provider logout, unlinking or playlist action occurred. The app displayed its mapped user during Spotify sign-in; provider identity and app identity are distinct.
- [Development scheduler 42548863225](https://github.com/russell-algeo/dj-setlist-generator/actions/runs/42548863225) used `cfa97de`/`preview`, the explicit development target and the protected callback helper; it returned HTTP 200 at `02:04:21.4372425Z`. At `02:06:15.098Z`, development had zero active submissions, runs or nonterminal leases and the same three archive sets. No new media or playlist was created for this hostname change. A later bounded discovery/media attempt is recorded below; full media completion after this origin change was not demonstrated because YouTube required sign-in. Earlier cancellation and Production media results retain their original SHA attribution.
- Production remains `ea5b59d4f507607e73ea0f55114d4eba2f450232` on READY `dpl_CovFwnrp9ZQXq4XdLkimkinpYvap`. [Post-merge process-set 42546426568](https://github.com/russell-algeo/dj-setlist-generator/actions/runs/42546426568) completed normally at that exact SHA and production target; finalizer HTTP 200 at `01:41:07.0983210Z`. The bounded Sleepless result increased the archive once, 1,706 to 1,707, with playlist creation false. Historical March queue residue was not modified.
- Cleanup removed the three obsolete `codex/preview-worker-isolation` OIDC rules after verifying current dispatch refs, zero active/queued workflows and the successful neutral scheduler callback. The three `preview` rules, project self-access and Standard Vercel Authentication remain. No Production setting, alias or Git branch was removed.
- The owner subsequently authorized retiring sign-in on the old `listened-preview` deployment. Only its exact Google `/api/auth/callback/google` and Spotify `/api/auth/callback/spotify` redirect entries were removed and independently read back at `02:23:00Z` and `02:23:55Z`, respectively. Production and neutral Preview callbacks remain; Google has three redirects and two unchanged JavaScript origins, and Spotify has seven redirects. The old immutable site still advertises its retired callbacks, so sign-in there is intentionally unsupported. Other Production, local-development and legacy entries remain unchanged. The legacy `SPOTIFY_REDIRECT_URI` and `/api/spotify/callback` route remain outside this migration.

### Remaining release checks (2026-11-09 UTC)

- **Natural Production schedule passed.** [Scheduler 42547943719](https://github.com/russell-algeo/dj-setlist-generator/actions/runs/42547943719) was an actual `schedule` event, not a manual dispatch. It ran `remote-deployment` at merged `ea5b59d`, targeted Production and returned HTTP 200 at `01:53:56.1194935Z`. This verifies that event, not a guarantee of every configured fifteen-minute firing.
- **Historical queue residue reconciled.** At `02:50:47.036157Z`, a serializable, exact-row compare-and-swap transaction marked two March submissions with no child runs failed and 34 unclaimed leases under failed parents cancelled. Persisted before-images, exact state/count assertions, after-images and a conditional rollback recipe were retained. Independent verification at `02:51:09.194Z` found zero active Production submissions/runs/nonterminal leases and the same 1,707 archive sets. Four failed parent runs/submissions were unchanged; nothing was deleted, dispatched or retried.
- **Live managed Spotify token path passed.** [Process-set diagnostic 42555288678](https://github.com/russell-algeo/dj-setlist-generator/actions/runs/42555288678) ran on `preview` at `172bd16`, using the existing cancelled Hal-owned run solely to resolve its existing connection. The real managed-token parser verified the protected callback at `03:14:40.4608129Z`. Bootstrap, recognition, publication and finalization were all skipped; the diagnostic never logged or persisted the access token, and no playlist was created. The run, its two leases and archive remained unchanged. The temporary diagnostic input, job and helper were subsequently removed; existing trust and permission scopes were not expanded.
- **Bounded in-app discovery passed through handoff, but media download failed.** The Preview UI submitted Phil Weeks with no aliases, maximum one set and playlist creation off: submission `35f0729f-1785-431d-bc0e-d93a453f8835`. [Discovery 42555729729](https://github.com/russell-algeo/dj-setlist-generator/actions/runs/42555729729), at `172bd16`, searched 476 unique results, filtered/deduplicated to 96 and selected one 83-minute Cercle set. Its callback returned HTTP 200 at `03:21:12.5775772Z` and automatically dispatched exactly one canonical child, `3ad4e23e-3d67-4a93-bd04-99d390b36b35`. Two candidate rows represent its accepted YouTube source and alternate SoundCloud source, not two queued sets.
- **Download limitation and clean failure.** [Media run 42555927472](https://github.com/russell-algeo/dj-setlist-generator/actions/runs/42555927472) exhausted its ten built-in attempts because YouTube required sign-in. No credentials, cookies or network settings were changed to work around that response. Recognition and publishing were skipped; failure finalization returned HTTP 200 at `03:31:00.4040170Z`. The sole submission/run became failed with no publication or leases. At `03:32:44.767Z`, independent development verification found zero active submissions/runs/nonterminal leases and the same three archive sets. Bootstrap currently reads only the primary source URL, so the discovered SoundCloud alternate was not automatically attempted. Do not label this a successful full media/publication test.
- **Preview-only count control retained.** The optional field uses the existing backend count limit and leaves blank/default behavior, aliases and playlist-off behavior intact. Trusted server policy requires the development target and rejects an actual `VERCEL_ENV=production`, even if app configuration is wrong. The control defaults off in client components; Production-mode requests containing the override return HTTP 400 before any create/dispatch. This protects a future merge, while the current Production deployment remains unchanged at `ea5b59d`. Existing stored caps, worker configuration and internal worker routes are unaffected.
- **Post-diagnostic source checks passed.** After removing the temporary probe, 146 Python tests and 173 web tests passed, TypeScript passed, and ESLint reported zero errors with four existing warnings. No new permissions or provider grants were added. Keep the permanent `preview` branch; do not promote this Preview-only checkpoint without the normal Production review.

### Ordered cutover acceptance checklist

- Recheck current branch heads, active/queued workflows and development submissions. Coordinate a quiet queue and an approved intake pause or agreed quiet window; an old empty-queue observation is not a lock. Preserve concurrent edits and account for in-flight callbacks.
- Confirm the exact candidate and update permanent `preview` without force pushes or overwriting work. Direct Preview pushes do not require a PR/review; obtain the explicit commit request required by `AGENTS.md`. Keep the older branch/trust/hostname available during transition. Production still requires a PR and one approving GitHub review.
- Inspect and preserve the existing, narrowly scoped Preview OIDC rules described below. Do not duplicate or broaden trust for the neutral alias. Keep the development database, callback secret, provider scopes and Production settings unchanged.
- Verify the exact Google redirect `https://dj-setlist-generator-git-preview-russell-algeos-projects.vercel.app/api/auth/callback/google` and Spotify redirect `https://dj-setlist-generator-git-preview-russell-algeos-projects.vercel.app/api/auth/callback/spotify` are present in the existing clients. Add only missing entries after required action-time approval, without duplicates. Retain destinations with live dependencies; do not create replacement clients, wildcards, origin fallbacks or redirect bypasses. The legacy `SPOTIFY_REDIRECT_URI` and `/api/spotify/callback` handler are outside this migration.
- Coordinate Preview Vercel `APP_BASE_URL` and `NEXTAUTH_URL`, the existing GitHub `DEVELOPMENT_APP_BASE_URL`, and all six workflow `WORKER_EXPECTED_PREVIEW_ORIGIN` constants to exactly `https://dj-setlist-generator-git-preview-russell-algeos-projects.vercel.app`. Keep Preview `GITHUB_WORKFLOW_REF=preview`. Do not accept either origin dynamically to mask mixed configuration.
- Build the exact `preview` commit with Preview configuration. Environment edits do not alter immutable deployments. Let Git integration build an authorized push, then verify READY state, source SHA, automatic branch-alias advancement and development routing; do not manually reassign the old alias as the routine deployment step.
- Keep intake quiet until the web deployment and worker ref agree on the candidate SHA and configuration. A worker ref changes at push time, before the new web build is READY. If a build fails or a newer push arrives, stop and reconcile rather than testing mixed SHAs.
- Test Google/Spotify sign-in and authenticated reload on the neutral origin, then run the approved bounded callback/cancellation checks. Verify worker `headSha` matches the web deployment, the target is development, callbacks succeed without redirects, cancelled work does not publish, and queue/final state reconcile. No additional Spotify playlist creation is included without its own specific approval.
- Record verified source, configuration, alias and test evidence in the release record and existing Vault note; only then mark migration complete and resume intake. Remove obsolete branches/trust/OAuth destinations only with their own applicable authorization and after no deployment or job depends on them.

OIDC permits only the named GitHub workflows to pass protected Preview access checks; the application still requires its internal development secret. It does not grant access to Production or replace app authentication.

## Historical release state and evidence

The following dated material predates the current state above. Keep its exact source/test attribution; statements that the PR #30 worker patch was not yet in Production describe that earlier checkpoint, not the current release. The cutover checklist is a reusable acceptance procedure; dated execution results belong in the release evidence and the existing project Vault note.

Branch heads and Vercel aliases were rechecked on **2026-11-08 UTC**. Tests below were performed on **2026-11-07 UTC**. Recheck live state before another release; these identifiers are a recovery reference, not a moving "latest" pointer.

| Environment | Source | Vercel deployment | Result |
| --- | --- | --- | --- |
| Production | `remote-deployment`, `faaedec434c0854fda7fa0f5dfb4a1cb67efecae` | `dpl_A9rsRehPLkzvk8kRuMX65YTwFuvq` | READY; reviewed PR #28, matching fixes, manual listened markers and database-specific archive caches already released |
| Preview | `codex/preview-worker-isolation`, `76c5e994e7b044e8e0f7b3a4d42f1c9d901df509` | `dpl_HLExpWtjnfwAc8X68QwwrfoS8iJH` | READY; development worker safeguards and protected callbacks verified |

- [Production](https://dj-setlist-generator.vercel.app)
- [Stable Preview](https://dj-setlist-generator-listened-preview.vercel.app)
- [Completed Preview workflow](https://github.com/russell-algeo/dj-setlist-generator/actions/runs/42421827559)
- [Preview submission](https://dj-setlist-generator-listened-preview.vercel.app/submissions/854fa1d8-c8f9-4226-8cf1-69cdae2a029d)
- [Published Preview result](https://dj-setlist-generator-listened-preview.vercel.app/sets/never-be-like-you-feat-kai-28202150)

**The Preview worker patch is not released to Production.** Its implementation is on the Preview branch above. A copy of this runbook on the production branch describes that candidate; it does not imply that `worker/isolation.py`, the new callback helper, or workflow guards are present in the production source yet.

| Verification | Observed result and limit |
| --- | --- |
| Worker tests at `76c5e99` | 104 Python tests passed, including 12 callback and 7 database-isolation tests; actionlint 1.7.12 passed for all three workflows with external shellcheck/pyflakes disabled; diff check passed |
| Released PR #28 | 103 web tests, 85 Python tests, TypeScript, production build and lint passed (four existing lint warnings); these are prior release results, not a new web-suite run on every later SHA |
| Preview process-set E2E | Normal app intake, anonymous SoundCloud download, bootstrap, one recognition slot, publish and finalize succeeded at the exact Preview SHA; final protected callback HTTP 200 |
| Recognition quality | 235-second source, 15 segment results, 9 recognized, 6 Shazam rate-limit failures; one expected Flume track published. Pipeline success is not 100% segment recognition |
| Persistence and browser | Development submission/run completed, one archive entry persisted, result survived reload, queue drained to zero; playlist creation was false; Production cookie preparation/persistence skipped |
| Google authentication | Real Preview sign-in, repeated sign-in and authenticated reload passed |
| Spotify authentication | User completed existing-account login; returned Preview session displayed Connected before and after reload. Read-only counts verified one Spotify account with refresh token, one active encrypted connection and an active session joined to it; no token values read |
| Not yet live-tested for the worker patch | Artist discovery, manual development scheduler, forced failure/cancellation finalization, long-running token renewal, anonymous YouTube processing, multiple simultaneous sets/slots, Spotify playlist writes, production worker execution, and rollback drill |

### Worker promotion checks (2026-11-08)

Candidate `b6e1070` was tested against production source `93c9c3e` (the documentation-only PR #29 merge). The worker source has not yet been released. Local checks passed: 109 Python tests, 110 web tests, TypeScript, actionlint (external shellcheck/pyflakes disabled), and lint with the same four existing warnings. The candidate Vercel build is READY (`dpl_24qwo4yumTV3SSnKH6MsXo3PhrCy`).

Three bounded development workflows ran at that exact candidate SHA using the existing protected Preview callback and unchanged web application code:

- Scheduler [42489963821](https://github.com/russell-algeo/dj-setlist-generator/actions/runs/42489963821): success, callback HTTP 200, initially empty queue.
- Discovery failure [42489991475](https://github.com/russell-algeo/dj-setlist-generator/actions/runs/42489991475): intentionally invalid test submission (missing artist name), expected workflow failure, finalizer HTTP 200, persisted failed submission. No provider search or media run was triggered.
- Cancellation [42489993425](https://github.com/russell-algeo/dj-setlist-generator/actions/runs/42489993425): cancelled during bootstrap setup; finalizer succeeded, isolated submission/run persisted cancelled, no published set and no retry. The development queue returned to zero active submissions/runs.

Successful discovery orchestration, empty results, provider failure, deduplication, recovery ordering, retry limits and superseded finalization are covered by local tests with external providers/database calls stubbed. A fresh live successful artist search, stale-lease recovery with real concurrent jobs, cancellation during recognition/publish, long-running token renewal, multi-slot processing and production execution of the candidate remain unverified. The earlier live process-set success remains evidence for `76c5e99`, not a claim that every later source SHA was media-tested.

Rollout constraint: no schema, secret, callback payload or production endpoint changes are proposed. Existing jobs keep their checked-out source. The new concurrency-group format will not cancel older-format workflows, so drain affected runs before merging and never redispatch an existing run during the transition. Recheck both active/queued Actions and application queue state immediately before merge; an earlier empty-queue observation is not a release lock. Preserve the required independent PR review. This section supersedes only the corresponding scheduler/failure/cancellation gaps in the historical table above.

Local sanitized evidence on Hal is in `/Users/hal/Documents/Codex/2026-11-06/task-3/live-check/`: `preview-worker-completion.json`, `preview-e2e-github-result.json`, `preview-e2e-current.json`, `preview-e2e-callback-log.txt`, `preview-media-completed.png`, `preview-spotify-completion.json`, and `preview-spotify-connected.png`. These are local audit artifacts, not files expected in a fresh clone. Do not commit credentials, browser sessions, downloaded media, or raw diagnostic logs.

## Architecture and target environment map

Vercel runs the Next.js control plane; GitHub Actions runs media work; Neon stores application, authentication and operation state. Production and Preview share one repository and existing Actions dispatch control. They have separate database branches and callback credentials.

| Component | Production | Preview / development |
| --- | --- | --- |
| Web and dispatched worker ref | `remote-deployment` | `preview`; see the migration baseline above for the previous worker ref |
| `APP_BASE_URL` | `https://dj-setlist-generator.vercel.app` | `https://dj-setlist-generator-git-preview-russell-algeos-projects.vercel.app` |
| App dispatch target | `APP_ENVIRONMENT=production` | Current `APP_ENVIRONMENT=preview` resolves to `deployment_target=development` |
| Neon project/database | `late-haze-65748644` / `neondb` | Same project/database name, independent branch |
| Neon branch | `production`, `br-blue-field-a412pexb` | `development`, `br-flat-cake-a4nsqzd6` |
| Direct endpoint | `ep-rough-dust-a4q90lxc.us-east-1.aws.neon.tech` | `ep-autumn-bar-a4f9xp8v.us-east-1.aws.neon.tech` |
| Roles (app / worker / migrations) | `set_list_app` / `set_list_worker` / `set_list_migrator` | `set_list_dev_app` / `set_list_dev_worker` / `set_list_dev_migrator` |
| GitHub database and URL secrets | `PRODUCTION_DATABASE_URL_*`, `PRODUCTION_APP_BASE_URL` | `DEVELOPMENT_DATABASE_URL_*`, `DEVELOPMENT_APP_BASE_URL` |
| GitHub callback secret | `INTERNAL_WORKER_SHARED_SECRET` | `DEVELOPMENT_INTERNAL_WORKER_SHARED_SECRET` |
| Vercel callback variable | `INTERNAL_WORKER_SHARED_SECRET` in Production | Same variable name in Preview, different development value |
| OAuth clients / metadata providers | Existing Google and Spotify clients; Spotify/Discogs provider credentials | Shared clients/providers, separate callback URLs and development auth records |
| Scheduler | Default-branch cron every 15 minutes, production target | No unattended Preview cron; manual development check only |

`*_DATABASE_URL_*` above denotes the existing `POOLED`, `DIRECT`, and `MIGRATIONS` names. Vercel uses `DATABASE_URL`, `DATABASE_URL_DIRECT`, and `DATABASE_URL_MIGRATIONS` in each target environment. The web app uses the app role; Actions runtime uses only the direct worker role; migration credentials are for explicitly planned maintenance. Pooled endpoints append `-pooler` to the endpoint name. The development worker guard intentionally accepts the direct host only.

The branch names were changed without moving live data. Development is the historical root and production its independently writable child; neither branch name nor lineage is permission to reset/copy data. Do not merge, reset, or replace Neon production as part of a source-code release. The former separate temporary Preview project was retired. Local web development currently uses real isolated Neon development credentials; PGlite was evaluated but is not integrated.

### Runtime and local setup

- Vercel root: **`apps/web`**, Next.js; repository package manager: **pnpm 10.8.0**.
- `.nvmrc`: **24.15.0**; root and web `package.json` engines: **24.x**.
- Vercel project API still reports a **20.x default**. The production build log explicitly confirms that package engines override it to **24.x**. Do not interpret the old project default as the effective build runtime. Inspect each build; do not change the project setting as a documentation fix. See [Vercel Node version precedence](https://vercel.com/docs/functions/runtimes/node-js/node-js-versions).
- Media workflows use **Python 3.11** and install their phase-specific requirements. Deno/FFmpeg are prepared by the workflow.
- From the repository root, use the pinned runtime, `pnpm install --frozen-lockfile`, then `pnpm --filter web dev`. Use an ignored private local environment file containing development-only credentials; do not copy Production values into it. Confirm the resolved database target before writes.
- When CLI deployment/linking is needed, run Vercel from `apps/web` and verify the existing project/team. Root `deploy:*` wrappers currently invoke Vercel from the repository root; do not use them as a shortcut. Do not copy another checkout's `.vercel` metadata or authorize a new CLI identity merely because the browser is already signed in.

Current `/sets`, `/artists`, and archive pages are rendered from normalized Neon rows and database-scoped caches. Local `output/` JSON/HTML is a separate CLI artifact, not automatically deployed. The old `archive:stage` package script is absent; do not follow the former static-HTML staging instructions. Imports/backfills are separately scoped data mutations and must include the relevant materialized-view/cache refresh.

## Submission and callback flow

1. An authenticated user submits through Preview UI or `POST /api/jobs`. A single hand-picked source uses `mode=curated_artist`, `artistName`, and `sourceUrls`; default `createPlaylist=false` avoids Spotify writes.
2. The app writes ownership, submission and set-run state to its Neon branch, then dispatches the existing workflow on `GITHUB_WORKFLOW_REF`. `APP_ENVIRONMENT` takes precedence over `VERCEL_ENV`; only `production` selects production secrets. Never leave Preview's ref unset: code falls back to `remote-deployment`.
3. GitHub checks out the dispatched commit and selects target-specific database, app URL and callback secret. A branch can move after the web build, so compare Vercel's source SHA with every workflow `headSha`; stop for drift rather than assuming matching branch names prove matching code.
4. Bootstrap checks routing, downloads public audio and creates recognition leases. Artifacts pass audio to recognition slots (one-day retention). Recognition persists segment results; publication enriches and sends the payload to the app.
5. Preview callbacks send both `x-internal-secret` and a newly minted `x-vercel-trusted-oidc-idp-token`. Vercel validates OIDC trust; the app validates its separate development secret. Publishing, revalidation, dispatch and finalization must all target the same Preview origin. Redirects are refused.
6. The app persists the archive result, refreshes the archive, and reconciles submission/run state. Inspect `/submissions/<id>`, then `/sets/<slug>` and reload. Workflow success alone is insufficient.

Direct `process-set.yml`/`discover-artist.yml` dispatch is not user intake: their IDs must already exist in the correct app database. Do not rerun historical development-target jobs from before the split; they originally used live data, but development secrets now point elsewhere. GitHub reruns preserve the original SHA/ref, not necessarily the historical external configuration ([GitHub rerun behavior](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs?tool=cli)). Recover through the correct app and reconcile the exact run IDs.

### Guards and shared trust

The Preview patch checks the exact development worker host, role, `neondb`, port and SSL settings, rejects connection overrides and production/migrator fallbacks, and checks the exact Preview callback origin before media work. Missing development callback credentials never select the production callback secret. `process-set` concurrency includes branch, deployment target and run UUID; discovery and scheduler do not gain such a group from this patch.

`process-set` bootstrap has one explicit shared-provider exception: `deployment_target=development` on `refs/heads/preview` in `russell-algeo/dj-setlist-generator` may prepare the existing `YOUTUBE_COOKIES_B64` and matching `YOUTUBE_USER_AGENT` for video metadata and audio download. Other development refs/repositories remain excluded; Production preparation is unchanged. Preview receives only a job-local cookie jar, outside the audio artifact paths, and cannot persist it to the repository secret. Both workflow writeback conditions and the persistence script still require Production; `GH_PAT` remains confined to those Production-only steps. Do not export, display, or copy the credential value to implement or validate this exception.

Sharing the session means compromise, invalidation, account challenges, and provider throttling can affect both environments. Keep database/callback guards intact. Discovery and publishing/enrichment receive no new cookie support from this change. The historical anonymous download failure above remains a failed test; validate a bounded authenticated Preview run separately before claiming media success or cookie validity.

This is an accidental-misrouting defense, **not isolation from hostile workflow code**. Repository-scoped Production secrets remain available to trusted development code; shared Actions access can cancel production runs. Provider credentials, OAuth client revocation, quotas, runner/storage allowances and possible provider/IP throttling are shared. Keep the Free-only constraint, bounded work and short retention; verify current allowances before tests. Do not add paid services, bigger runners or overage.

### Existing protected Preview configuration

Three Preview-only rules for `preview` remain saved. After the neutral callback and queue checks passed, the three obsolete `codex/preview-worker-isolation` rules were removed. Project self-access and Standard Vercel Authentication remain enabled. Inspect and preserve the three current workflow rules; do not add duplicates:

| Claim / destination | Value |
| --- | --- |
| Provider / issuer | GitHub Actions / `https://token.actions.githubusercontent.com` |
| Audience | `https://github.com/russell-algeo` |
| Repository | `russell-algeo/dj-setlist-generator` |
| Branch | `preview` |
| Workflow names (three separate rules) | `process-set`, `discover-artist`, `scheduler` — YAML `name`, not filenames |
| Vercel environment | Preview only |

Keep the existing project self-access rule and Vercel Authentication. Workflows default to `contents: read`. Only callback jobs (`publish`, `finalize`, `discover`, and `scheduler`) receive job-scoped `id-token: write`; bootstrap and recognition cannot mint OIDC tokens. Production callback jobs retain that job capability because permissions are static, but mint no token: their OIDC audience is empty and existing shared-secret authentication remains unchanged. No additional Vercel trust or provider grant is created by promoting this source. The neutral alias belongs to the same Vercel project and needs no additional trust. A different worker branch would need an explicitly scoped trust update before its callbacks work; changing the web/ref alone is insufficient. New credentials/trust changes require their own applicable authorization.

The historical sign-in checks used the old `listened-preview` destinations `/api/auth/callback/google` and `/api/auth/callback/spotify`. Both real sign-in flows and reload persistence passed there. The neutral-origin destinations are now also saved. Neutral Google and fresh Spotify sign-in/reload both passed. The test concluded with explicit Google sign-in and reload confirming Hal’s app identity; see the dated checkpoint above. The owner later accepted retiring old-site sign-in, and the two listened-preview callback entries were removed as recorded above. Use the neutral site for new sign-ins. Verify existing entries before writing and do not create replacement clients. Browser Vercel access, provider login and app login are separate sessions; an authenticated CLI/service callback does not prove an authenticated user flow. Preserve deployment protection and use existing authorized access; involve the user when provider login/consent is needed. Playlist creation remains a real external write and was not part of the completed test.

## Checklist: validate a new Preview candidate

- [ ] Record branch, exact commit/tree, diff, current production/Preview deployment IDs, environment mapping, database migration state and pending/active run IDs. Keep secret values out of the record. Freeze the candidate while testing.
- [ ] Review database/callback origin guards, secret selection, cookie conditions, concurrency and workflow permissions. Check current Free-plan/capacity constraints. Plan any schema changes separately and maintain backward compatibility with running workers.
- [ ] Run relevant local checks from the root in the configured environment:

  ```bash
  python3 -m unittest discover -s tests
  actionlint .github/workflows/process-set.yml .github/workflows/discover-artist.yml .github/workflows/scheduler.yml
  pnpm --filter web test
  pnpm --filter web exec tsc --noEmit
  pnpm --filter web lint
  pnpm --filter web build
  git diff --check
  ```

  Use the project's Python environment and requirements. Record actual results, versions and omitted checks; do not relabel the earlier actionlint run as including shellcheck/pyflakes. Build with development credentials only. Documentation-only edits need link/command/diff checks, not another media job.
- [ ] Within the approved deployment scope, build the exact branch with **Preview** configuration. Environment edits affect a new deployment, not an existing immutable one. Confirm READY/source SHA and automatic neutral branch-alias advancement. Keep intake quiet through worker/web SHA mismatch and preserve Production.
- [ ] Check Preview's database/role, `APP_BASE_URL`, `APP_ENVIRONMENT`, explicit `GITHUB_WORKFLOW_REF`, callback secret presence and exact trust. Verify access through Vercel protection, app Google/Spotify sign-in, and authenticated reload without printing tokens.
- [ ] Ensure the development queue is understood and empty for a one-job test. Submit one short anonymous public URL through normal app intake with playlist creation false and notifications off. Record submission/run IDs and duration. Capacity defaults are not a one-job guarantee: the web default is 10 active runs and slot selection is automatic. The completed 235-second test naturally selected one slot; verify actual slot/counts and use reviewed development-only limits if another source would exceed the intended budget.
- [ ] Confirm workflow `headSha` equals the frozen candidate, development routing and preflight success. For the permitted repository/`preview`/development bootstrap, verify cookie/user-agent preparation using presence-only logs; all Preview runs must skip Production-only cookie writeback and its `GH_PAT` step. Other development refs must also skip preparation. Follow bootstrap, recognition, publish, revalidation and finalize. Capture provider failures separately from pipeline state.
- [ ] Verify the resulting development rows, completed submission/run, final callback status, archive page and reload; ensure the queue drained. Record any external side effects and remove only explicitly disposable fixtures when cleanup is approved.
- [ ] Before releasing changes to those paths, add bounded discovery, development scheduler and controlled failure/cancellation tests. Exercise long-running renewal or multi-slot behavior when the change depends on it. These remain unverified by the initial process-set test; obtain an explicit risk decision if any required scenario is deferred.

## Checklist: release the reviewed source to Production

This promotes **source code and its compatible configuration**, not development data. Do not assign the Production alias directly to a development-backed build. Vercel's supported Preview-to-Production promotion rebuilds with Production variables; merely assigning an alias is not that operation ([Vercel promotion behavior](https://vercel.com/docs/deployments/promoting-a-deployment)). Prefer the repository's reviewed integration path below.

- [ ] Recheck live heads, rules and release authorization. `remote-deployment` currently requires a PR and one approving review. Get approval on the final candidate and resolve required checks; do not bypass protection or treat conversation approval as a recorded GitHub review.
- [ ] Rebase/merge against the current integration head and validate the resulting tree. If conflicts or source changes alter the tested candidate, rerun affected checks and Preview tests. Record the final merge SHA/tree and rollback baseline.
- [ ] Inventory active Production and development jobs. Agree a release window and compatibility plan. Do not rotate credentials/change DB or callback routing beneath active jobs. If the change requires stopping dispatch, use a reviewed reversible intake/dispatch pause; do not disable the shared workflows globally as a Preview-only measure.
- [ ] Review release triggers before merging: a merge can immediately build the Production web app, new workflow dispatches use the updated branch, and scheduled Actions execute the default-branch scheduler. These do not change atomically. Drain affected work or provide an explicit compatible rollout; do not merge first and investigate the gap later.
- [ ] Verify existing Production `APP_ENVIRONMENT=production`, app origin, production database roles and `GITHUB_WORKFLOW_REF=remote-deployment`. Keep its callback credential, endpoints, OAuth destinations and data unchanged for this worker patch. Stage any separately authorized migration against the correct branch/role with recovery evidence; never copy/reset Neon development into Production.
- [ ] Merge through the required PR gate within the approved release window. Let the existing Git integration build the merged source with Production configuration; inspect the resulting READY deployment and Production alias. Do not deploy twice if the Git-triggered build already succeeded. A controlled manual release must still use the reviewed source and Production environment.
- [ ] Verify deployment SHA/tree, app environment/database routing, existing archive/search/sign-in, manual listened mark/remove/reload and error logs. Run one approved bounded normal Production submission when worker behavior changed, check its workflow head/production target and all callbacks, then observe the scheduled production path. A read-only smoke check alone does not validate media work.
- [ ] Record results, remaining limitations, current source/deployment IDs and recovery owner in the release record/Vault. Resume any paused intake only after routing and callbacks are confirmed. Retain Preview separately; do not delete its branch or trust just because source was merged.

## Checklist: rollback and incident recovery

A Vercel rollback restores web deployment/configuration captured by that build. It does **not** revert Neon rows/migrations, GitHub branch workflow code, repository secrets, scheduled behavior or already-running jobs. Choose web, worker, configuration and data recovery independently, then verify them together.

### Preview

1. Stop new Preview intake and inventory pending/active development IDs. Disable only Preview dispatch using a reviewed mechanism. If using an empty Preview `GITHUB_DISPATCH_TOKEN`, build/serve a new Preview deployment for it to take effect; preserve callbacks so existing jobs can finish. Empty dispatch configuration can still leave claimed rows to reconcile, so it is not a complete queue pause. Do not revoke the shared GitHub token or disable shared workflows.
2. Drain current jobs, or cancel only the identified development jobs with explicit recovery handling. Preserve evidence and reconcile their database status through the app; do not leave leased/claimed rows silently stuck.
3. Select a previously verified **development-backed** deployment and compatible worker ref, or rebuild a corrected source with development configuration. Recheck SHA/ref, role/origin, callback credential and exact trust. The old PR #28 Preview and temporary holding builds predate this callback isolation; they are not proven worker rollback targets. Do not revive builds that captured the inherited cross-branch owner credential.
4. Restore only the Preview alias/configuration. Rebuild when environment changes are required. Keep the currently validated stable alias for callbacks until active jobs have drained; coordinate any alias change with their expected app behavior.
5. Remove newly added development-only secrets/trust only when specifically authorized and no job depends on them. Do not revoke shared providers or delete/reset the development branch as routine rollback. Verify a bounded recovery and drain state before reopening intake.

### Production

1. Record the incident and exact affected IDs; pause new work through an approved, scoped mechanism if necessary. Preserve live content and auth data.
2. For a web regression, choose the last compatible deployment that actually served Production and use Vercel's rollback operation. Inspect its captured database/app configuration and migration compatibility first. Do not use a Preview build as a substitute.
3. For a worker regression, restore reviewed good workflow/code on `remote-deployment` through a revert PR and required review. A web rollback leaves the branch and cron unchanged. A separately authorized temporary dispatch-ref pin must reference verified production-capable code; it does not move the default-branch scheduled workflow. Account for both paths and active jobs.
4. Recover schema/content only from a separately reviewed backup/guarded rollback plan. Never reset Production from development or assume deploying old code reverses a migration. Restore secrets only through the approved credential process, without exposing values.
5. Check Production alias/source, database role and endpoint, dispatch ref, scheduler source, active-job outcomes, app behavior and callback status. Reconcile failed jobs through the Production app; do not rerun pre-split development-target jobs. Document deviations and the source/deployment now serving users.

## Deployment authorization

- Preview deployments, Vercel environment changes, production deployments, aliases/domains, database migrations, workflow dispatches that process external media, and public actions require Russell’s approval immediately before the action.
- Do not use `--prod`, `--yes`, `--force`, or inline environment values to bypass that approval.
- Do not use Vercel Cron for worker orchestration; GitHub Actions owns the 15-minute scheduler and long-running pipeline.
- Do not pull remote environment values into local files without explicit approval of the destination and secret-handling risk.

## Documentation maintenance

Keep this runbook and the README deployment pointers aligned on both release and Preview branches. Distinguish observed state, historical evidence and planned checks. A documentation PR can still trigger Vercel builds; review its base, diff and deployment effects before publishing or merging. Never turn a prior approval stored in a note into standing permission for a future change.

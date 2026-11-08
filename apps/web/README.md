# Set Signal web application

Next.js control plane and archive UI for the DJ setlist generator. Neon stores data; GitHub Actions performs media processing.

## Local development

From the repository root, use `.nvmrc` (24.15.0; package engines 24.x) and pnpm 10.8.0:

```bash
pnpm install --frozen-lockfile
pnpm --filter web dev
```

Open http://localhost:3000. Use the project's ignored private environment configuration with the isolated Neon development branch and app role. Verify the resolved database before writing; local development is not backed by an in-memory database.

## Validation and deployment

See the root [deployment runbook](../../DEPLOYMENT.md) for environment variables, protected Preview access, worker branch routing, test evidence, production review/promotion gates, and rollback. Do not create another Vercel project from the template defaults. When using Vercel CLI, operate from `apps/web` and confirm the existing `dj-setlist-generator` project first. Root deployment wrappers are not the recommended path.

The archive uses database rows and cache revalidation. The removed `archive:stage` script and legacy static-HTML staging guidance do not describe the current web publication flow.

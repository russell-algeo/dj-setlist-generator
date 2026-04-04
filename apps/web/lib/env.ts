import fs from "node:fs";
import path from "node:path";

import { parse } from "dotenv";

const resolveWorkspaceRoot = () => {
  let current = process.cwd();

  while (true) {
    if (
      fs.existsSync(path.join(current, "pnpm-workspace.yaml")) ||
      fs.existsSync(path.join(current, ".git"))
    ) {
      return current;
    }

    const parent = path.dirname(current);
    if (parent === current) {
      return process.cwd();
    }
    current = parent;
  }
};

const fallbackEnv = (() => {
  const workspaceRoot = resolveWorkspaceRoot();
  const merged: Record<string, string> = {};

  for (const filename of [".env", ".env.local"]) {
    const filepath = path.join(workspaceRoot, filename);
    if (!fs.existsSync(filepath)) {
      continue;
    }

    Object.assign(merged, parse(fs.readFileSync(filepath)));
  }

  return merged;
})();

const get = (key: string) => {
  const runtimeValue = process.env[key];
  if (runtimeValue && runtimeValue.length > 0) {
    return runtimeValue;
  }

  const fallbackValue = fallbackEnv[key];
  return fallbackValue && fallbackValue.length > 0 ? fallbackValue : undefined;
};

const getPositiveInt = (key: string, defaultValue: number) => {
  const value = get(key);
  if (!value) {
    return defaultValue;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${key} must be a positive integer, got ${value}`);
  }

  return parsed;
};

const getDeploymentTarget = () => {
  const value = (get("APP_ENVIRONMENT") ?? get("VERCEL_ENV") ?? "development").toLowerCase();
  return value === "production" ? "production" : "development";
};

export const env = {
  appBaseUrl: get("APP_BASE_URL"),
  deploymentTarget: getDeploymentTarget(),
  nextAuthUrl: get("NEXTAUTH_URL") ?? get("APP_BASE_URL"),
  databaseUrl: get("DATABASE_URL") ?? get("DEVELOPMENT_DATABASE_URL_POOLED"),
  databaseUrlDirect:
    get("DATABASE_URL_DIRECT") ??
    get("DATABASE_URL_MIGRATIONS") ??
    get("DEVELOPMENT_DATABASE_URL_DIRECT"),
  databaseUrlMigrations:
    get("DATABASE_URL_MIGRATIONS") ??
    get("DATABASE_URL_DIRECT") ??
    get("DEVELOPMENT_DATABASE_URL_MIGRATIONS") ??
    get("DEVELOPMENT_DATABASE_URL_DIRECT"),
  authSecret: get("AUTH_SECRET") ?? get("NEXTAUTH_SECRET"),
  authGoogleId: get("AUTH_GOOGLE_ID"),
  authGoogleSecret: get("AUTH_GOOGLE_SECRET"),
  internalWorkerSharedSecret: get("INTERNAL_WORKER_SHARED_SECRET"),
  tokenEncryptionKey: get("TOKEN_ENCRYPTION_KEY"),
  spotifyClientId: get("SPOTIFY_CLIENT_ID"),
  spotifyClientSecret: get("SPOTIFY_CLIENT_SECRET"),
  spotifyRedirectUri: get("SPOTIFY_REDIRECT_URI"),
  githubDispatchToken: get("GITHUB_DISPATCH_TOKEN"),
  githubOwner: get("GITHUB_OWNER"),
  githubRepo: get("GITHUB_REPO"),
  githubWorkflowProcessSet: get("GITHUB_WORKFLOW_PROCESS_SET"),
  githubWorkflowDiscoverArtist: get("GITHUB_WORKFLOW_DISCOVER_ARTIST"),
  githubWorkflowRef: get("GITHUB_WORKFLOW_REF") ?? "remote-deployment",
  processSetMaxActiveRuns: getPositiveInt("PROCESS_SET_MAX_ACTIVE_RUNS", 10),
  initialAdminEmail: get("INITIAL_ADMIN_EMAIL") ?? "russellalgeo@gmail.com",
};

export const requireEnv = (key: keyof typeof env) => {
  const value = env[key];

  if (!value) {
    throw new Error(`Missing required environment variable for ${key}`);
  }

  return value;
};

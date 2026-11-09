import "server-only";

import { env } from "@/lib/env";

// Keep this checkpoint control on Preview even if its source reaches Production.
export const isDiscoveryMaxSetsEnabled = () =>
  env.deploymentTarget === "development" &&
  process.env.VERCEL_ENV?.trim().toLowerCase() !== "production";

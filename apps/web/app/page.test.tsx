import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  env: { deploymentTarget: "production" },
  getArchiveHomeExplorerInitial: vi.fn(),
}));
vi.mock("@/lib/env", () => ({ env: mocks.env }));
vi.mock("@/components/archive/archive-home-explorer", () => ({ ArchiveHomeExplorer: () => null }));
vi.mock("@/lib/archive/home-explorer-data", () => ({ getArchiveHomeExplorerInitial: mocks.getArchiveHomeExplorerInitial }));
vi.mock("@/lib/archive/metadata", () => ({ buildArchiveMetadata: vi.fn() }));
vi.mock("@/lib/auth/session", () => ({ getSessionActor: async () => null }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

import HomePage from "./page";

describe("server-derived Preview discovery capability", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv("VERCEL_ENV", "");
    mocks.getArchiveHomeExplorerInitial.mockResolvedValue({ scope: "global" });
  });
  afterEach(() => vi.unstubAllEnvs());

  it.each([["development", true], ["production", false]])("passes capability=%s only from trusted environment", async (deploymentTarget, expected) => {
    mocks.env.deploymentTarget = String(deploymentTarget);
    const element = await HomePage({ searchParams: Promise.resolve({
      allowDiscoveryMaxSets: "true", deploymentTarget: "development", APP_ENVIRONMENT: "development",
    }) }) as ReactElement<{ allowDiscoveryMaxSets: boolean }>;
    expect(element.props.allowDiscoveryMaxSets).toBe(expected);
  });

  it("withholds the capability on platform Production despite app development configuration", async () => {
    mocks.env.deploymentTarget = "development";
    vi.stubEnv("VERCEL_ENV", "production");
    const element = await HomePage({ searchParams: Promise.resolve({}) }) as ReactElement<{ allowDiscoveryMaxSets: boolean }>;
    expect(element.props.allowDiscoveryMaxSets).toBe(false);
  });
});

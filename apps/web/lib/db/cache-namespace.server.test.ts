import { describe, expect, it } from "vitest";

import { buildDatabaseCacheNamespace } from "./cache-namespace.server";

const production = "postgresql://worker:secret@ep-live.us-east-1.aws.neon.tech/neondb?sslmode=require";

describe("archive database cache namespace", () => {
  it("isolates two Neon branches even when their database names match", () => {
    const development = production.replace("ep-live", "ep-development");
    expect(buildDatabaseCacheNamespace(development)).not.toBe(buildDatabaseCacheNamespace(production));
  });

  it("treats pooled and direct connections to the same database as one identity", () => {
    const pooled = production.replace("ep-live.", "ep-live-pooler.");
    expect(buildDatabaseCacheNamespace(pooled)).toBe(buildDatabaseCacheNamespace(production));
  });

  it("keeps the identity across credential, protocol spelling and connection-option changes", () => {
    const rotated = "postgres://another:rotated@ep-live.us-east-1.aws.neon.tech:5432/neondb?connect_timeout=10";
    expect(buildDatabaseCacheNamespace(rotated)).toBe(buildDatabaseCacheNamespace(production));
  });

  it("isolates databases and local servers on different ports", () => {
    expect(buildDatabaseCacheNamespace(production.replace("/neondb", "/another"))).not.toBe(buildDatabaseCacheNamespace(production));
    expect(buildDatabaseCacheNamespace("postgresql://localhost:5432/app")).not.toBe(buildDatabaseCacheNamespace("postgresql://localhost:5433/app"));
  });

  it("does not put credentials in cache keys or invalid-URL errors", () => {
    expect(buildDatabaseCacheNamespace(production)).not.toContain("secret");
    expect(() => buildDatabaseCacheNamespace("postgresql://worker:secret@")).toThrow("Invalid database connection URL for archive cache");
  });
});

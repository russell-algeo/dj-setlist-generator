import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
const read = (file: string) => fs.readFileSync(path.resolve(process.cwd(), file), "utf8");
describe("public projection boundaries", () => {
  it.each(["lib/archive/data.ts", "lib/archive/repository.ts", "lib/archive/home-explorer-data.ts", "app/sitemap.ts"])("reads public-only views in %s", (file) => {
    const source = read(file); expect(source).toContain("publicSets as sets"); expect(source).toContain("publicArtists as artists");
    expect(source).not.toMatch(/"app"\."(?:sets|set_entries|set_artists|set_source_links|artists|tracks)"/);
    expect(source).not.toMatch(/"ops"\."(?:set_runs|submissions)"/);
  });
  it("rebuilds all global materialized views from public-only sources", () => {
    const sql = read("../../drizzle/migrations/0018_private_collection_access.sql");
    const views = sql.slice(sql.indexOf("-- Drop all three"), sql.indexOf('CREATE OR REPLACE FUNCTION "ops"."claim_next_artist_submission"'));
    expect(views.match(/CREATE MATERIALIZED VIEW/g)).toHaveLength(3);
    expect(views).not.toMatch(/"app"\."(?:sets|set_entries|set_artists|set_source_links|artists|tracks)"/);
    expect(views).toContain('"app"."public_sets"');
  });
  it("defaults new rows private while explicitly preserving legacy public rows", () => {
    const sql = read("../../drizzle/migrations/0018_private_collection_access.sql");
    expect(sql.match(/ADD COLUMN (?:publication_)?visibility text NOT NULL DEFAULT 'public'/g)).toHaveLength(3);
    expect(sql).not.toContain("SET DEFAULT 'private'");
    expect(read("../../drizzle/migrations/0019_private_insert_defaults.sql").match(/ALTER COLUMN (?:publication_)?visibility SET DEFAULT 'private'/g)).toHaveLength(3);
    expect(sql).toContain("Private set run target does not match");
    expect(sql).toContain("Set run submission scope does not match");
    expect(sql).toContain("Archive security scope is immutable");
    expect(sql).toContain("Public set run cannot reference a private item");
  });
  it("excludes private jobs from ordinary dispatch, discovery, and lease claiming", () => {
    const sql = read("../../drizzle/migrations/0018_private_collection_access.sql");
    expect(sql).toContain("visibility = 'public' AND mode = 'artist'");
    expect(sql).toContain("publication_visibility = 'public' AND status = 'queued'");
    expect(sql).toContain("r.publication_visibility = 'public'");
    expect(read("lib/jobs/dispatch.ts").match(/eq\(setRuns.publicationVisibility, "public"\)/g)?.length).toBeGreaterThanOrEqual(3);
  });
  it("invalidates prior shared data cache keys and protects authenticated route responses", () => {
    expect(read("lib/db/cache-namespace.server.ts")).toContain("public-acl-v1");
    const config = read("next.config.ts"); expect(config).toContain("/api/jobs/:path*"); expect(config).toContain("/submissions/:path*"); expect(config).toContain("no-store");
  });
});

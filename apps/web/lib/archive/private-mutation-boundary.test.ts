import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// SQL-source regression checks complement persistence mocks without opening Neon.
const source = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");

describe("private archive mutation boundaries", () => {
  it("does not use source URL as deletion ownership or run-removal authority", () => {
    const deletion = source("lib/archive/deletions.ts");
    expect(deletion).not.toMatch(/OR[^\n]*source_url/);
    expect(deletion).toContain('eq(sets.visibility, "public")');
    expect(deletion.match(/sr\.publication_visibility = 'public'/g)?.length).toBe(6);
    expect(deletion.match(/DELETE FROM "app"\."sets" WHERE id = ANY\(\$1::uuid\[\]\) AND visibility = 'public'/g)?.length).toBe(2);
  });

  it("retains shared artists while any private or public relationship remains", () => {
    const deletion = source("lib/archive/deletions.ts");
    const artistDeletes = deletion.split('DELETE FROM "app"."artists"').slice(1);
    expect(artistDeletes.length).toBe(4);
    for (const statement of artistDeletes) {
      const sql = statement.split('`')[0];
      expect(sql).toContain('"app"."set_artists"');
      expect(sql).toContain('"app"."track_artists"');
      // These retention predicates must inspect all relationships, not public views.
      expect(sql).not.toContain("visibility = 'public'");
    }
  });

  it("ordinary submission dedup only reuses public results", () => {
    const submissions = source("lib/jobs/submissions.ts");
    const dedup = submissions.slice(submissions.indexOf("const existingCompleted"), submissions.indexOf("for (const row of existingCompleted)"));
    expect(dedup).toContain(".innerJoin(sets, eq(sets.id, setRuns.publishedSetId))");
    expect(dedup).toContain('eq(setRuns.publicationVisibility, "public")');
    expect(dedup).toContain('eq(sets.visibility, "public")');
    expect(submissions).toContain('visibility: "public"');
    expect(submissions).toContain('publicationVisibility: "public"');
  });

  it("all submission listing variants use the collection-aware policy", () => {
    for (const path of ["lib/jobs/public.server.ts", "lib/jobs/submissions.ts", "lib/admin/users.ts", "lib/auth/session.ts"]) {
      const code = source(path);
      expect(code).toContain(path === "lib/admin/users.ts" ? "readableSubmissionPredicate(actor.userId, actor.isAdmin)"
        : 'readableSubmissionPredicate(actor.userId, actor.isAdmin, actor.authType === "session")');
      expect(code).not.toContain("actor.isAdmin ? undefined : eq(submissions.requestedBy");
    }
    expect(source("app/admin/page.tsx")).toContain("listAllSubmissionsWithUser(actor)");
  });
});

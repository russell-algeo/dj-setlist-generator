import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
const web = process.cwd();
describe("no public archive integration", () => {
  it.each(["lib/archive/data.ts", "lib/archive/repository.ts", "lib/archive/home-explorer-data.ts", "lib/archive/publish-set.ts", "app/sitemap.ts", "app/api/archive/search/route.ts", "app/api/archive/spotify/export/route.ts"])("keeps private data out of %s", (file) => { const source = fs.readFileSync(path.join(web, file), "utf8"); expect(source).not.toMatch(/yoon-fest|loadYoonCollection|getYoonSet/); });
  it.each(["data.server.ts", "collection-model.server.ts", "media.server.ts", "spotify-export.server.ts"])("does not use public publication or global cache in %s", (file) => { const source = fs.readFileSync(path.join(web, "lib/yoon-fest", file), "utf8"); expect(source).not.toMatch(/getArchiveSetDetail|upsertArchiveSet|unstable_cache|fixtures\.test-support/); });
  it("marks both private route families no-store and noindex", () => { const source = fs.readFileSync(path.join(web, "next.config.ts"), "utf8"); expect(source).toContain('/collections/yoon-fest/:path*'); expect(source).toContain('/api/yoon-fest/:path*'); expect(source).toContain("private, no-store"); expect(source).toContain("noindex, nofollow, noarchive"); });
});

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const archiveTestDir = path.dirname(fileURLToPath(import.meta.url));
const workspaceRoot = path.resolve(archiveTestDir, "..", "..", "..", "..");
const archiveRoot = path.join(workspaceRoot, "apps", "web", "lib", "archive");

describe("archive runtime guard", () => {
  it("does not keep the HTML response helper in the runtime source tree", () => {
    expect(fs.existsSync(path.join(archiveRoot, "html-response.ts"))).toBe(false);
  });

  it("does not export a getSitePageHtml helper from repository.ts", () => {
    const repositorySource = fs.readFileSync(path.join(archiveRoot, "repository.ts"), "utf8");
    expect(repositorySource).not.toContain("getSitePageHtml");
    expect(repositorySource).not.toContain("getSitePageByPath");
  });
});

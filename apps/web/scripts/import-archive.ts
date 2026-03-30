import fs from "node:fs/promises";
import path from "node:path";

import { refreshArchiveHomeMaterializedViews } from "@/lib/archive/home-materialized-views";
import { upsertArchiveSet, type ArchiveSetPayload } from "@/lib/archive/publish-set";

const WORKSPACE_ROOT = path.resolve(process.cwd(), "..", "..");
const OUTPUT_ROOT = path.resolve(WORKSPACE_ROOT, "output");

const readJson = async <T>(filePath: string) =>
  JSON.parse(await fs.readFile(filePath, "utf8")) as T;

const optionalResolvedPath = (value: string | undefined) => {
  if (!value) return undefined;
  return path.isAbsolute(value) ? value : path.resolve(WORKSPACE_ROOT, value);
};

const importSet = async (jsonPath: string) => {
  const payload = await readJson<ArchiveSetPayload>(jsonPath);
  const relativeIdentity = path.relative(OUTPUT_ROOT, jsonPath);

  return upsertArchiveSet({
    payload,
    provenance: {
      source: "output",
      relativeJsonPath: relativeIdentity,
    },
  });
};

const walk = async (dir: string): Promise<string[]> => {
  const dirents = (await fs.readdir(dir, { withFileTypes: true })).sort((left, right) =>
    left.name.localeCompare(right.name),
  );
  const files = await Promise.all(
    dirents.map(async (dirent) => {
      const entryPath = path.join(dir, dirent.name);
      return dirent.isDirectory() ? walk(entryPath) : [entryPath];
    }),
  );
  return files.flat();
};

const main = async () => {
  const targetedSetJson = optionalResolvedPath(process.env.IMPORT_SET_JSON);

  if (targetedSetJson) {
    await importSet(targetedSetJson);
    await refreshArchiveHomeMaterializedViews();
    console.log(`Imported targeted set payload ${targetedSetJson}`);
    return;
  }

  const allFiles = await walk(OUTPUT_ROOT);
  const setJsonFiles = allFiles.filter(
    (filePath) =>
      filePath.endsWith(".json") &&
      !filePath.endsWith("artist_summary.json") &&
      path.basename(filePath) !== "explorer_data.json",
  );

  for (const [index, filePath] of setJsonFiles.entries()) {
    try {
      await importSet(filePath);
    } catch (error) {
      console.error(`Import failed for ${filePath}`);
      throw error;
    }

    if ((index + 1) % 25 === 0 || index + 1 === setJsonFiles.length) {
      console.log(`Imported ${index + 1}/${setJsonFiles.length} set payloads`);
    }
  }

  await refreshArchiveHomeMaterializedViews();
  console.log(
    `Imported ${setJsonFiles.length} set payloads and refreshed archive home materialized views.`,
  );
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

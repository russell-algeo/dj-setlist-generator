import fs from "node:fs/promises";
import path from "node:path";

import { and, eq } from "drizzle-orm";

import { upsertArchiveSet, upsertArtist, type ArchiveSetPayload } from "@/lib/archive/publish-set";
import { toLegacyPath } from "@/lib/archive/import-helpers";
import { getDb } from "@/lib/db/client";
import { sitePages } from "@/lib/db/schema";

const WORKSPACE_ROOT = path.resolve(process.cwd(), "..", "..");
const OUTPUT_ROOT = path.resolve(WORKSPACE_ROOT, "output");

const readJson = async <T>(filePath: string) =>
  JSON.parse(await fs.readFile(filePath, "utf8")) as T;

const readHtml = async (filePath: string) => fs.readFile(filePath, "utf8");

const optionalResolvedPath = (value: string | undefined) => {
  if (!value) {
    return undefined;
  }

  return path.isAbsolute(value) ? value : path.resolve(WORKSPACE_ROOT, value);
};

const importSet = async (jsonPath: string) => {
  const db = getDb();
  const payload = await readJson<ArchiveSetPayload>(jsonPath);
  const htmlPath = jsonPath.replace(/\.json$/u, ".html");
  const html = await readHtml(htmlPath);
  const relativeIdentity = path.relative(OUTPUT_ROOT, jsonPath);

  return upsertArchiveSet({
    db,
    payload,
    html,
    legacyPath: toLegacyPath(OUTPUT_ROOT, htmlPath),
    provenance: {
      source: "output",
      relativeJsonPath: relativeIdentity,
      relativeHtmlPath: path.relative(OUTPUT_ROOT, htmlPath),
    },
  });
};

const importArtistPage = async (summaryPath: string) => {
  const db = getDb();
  const artistName = path.basename(path.dirname(summaryPath));
  const legacyPath = toLegacyPath(OUTPUT_ROOT, summaryPath);
  const artist = await upsertArtist(db, artistName, legacyPath);
  const html = await readHtml(summaryPath);

  await db
    .insert(sitePages)
    .values({
      path: legacyPath,
      pageType: "artist",
      artistId: artist.id,
      slug: artist.slug,
      html,
      metadata: {
        entity: "artist",
      },
    })
    .onConflictDoUpdate({
      target: sitePages.path,
      set: {
        pageType: "artist",
        artistId: artist.id,
        slug: artist.slug,
        html,
        metadata: {
          entity: "artist",
        },
        updatedAt: new Date(),
      },
    });
};

const importArtistPages = async () => {
  const artistSummaryFiles: string[] = [];
  const entries = await fs.readdir(OUTPUT_ROOT, { withFileTypes: true });

  for (const entry of [...entries].sort((left, right) => left.name.localeCompare(right.name))) {
    if (!entry.isDirectory()) {
      continue;
    }

    const summaryPath = path.join(OUTPUT_ROOT, entry.name, "artist_summary.html");

    try {
      await fs.access(summaryPath);
      artistSummaryFiles.push(summaryPath);
    } catch {
      continue;
    }
  }

  for (const summaryPath of artistSummaryFiles) {
    await importArtistPage(summaryPath);
  }
};

const importHomePage = async (htmlPath = path.join(OUTPUT_ROOT, "index.html")) => {
  const db = getDb();
  const html = await readHtml(htmlPath);

  await db
    .insert(sitePages)
    .values({
      path: "/",
      pageType: "home",
      html,
      metadata: {
        entity: "home",
      },
    })
    .onConflictDoUpdate({
      target: sitePages.path,
      set: {
        pageType: "home",
        html,
        metadata: {
          entity: "home",
        },
        updatedAt: new Date(),
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
  const db = getDb();
  const targetedSetJson = optionalResolvedPath(process.env.IMPORT_SET_JSON);
  const targetedArtistSummary = optionalResolvedPath(process.env.IMPORT_ARTIST_SUMMARY);
  const targetedHomeHtml = optionalResolvedPath(process.env.IMPORT_HOME_HTML);

  if (targetedHomeHtml) {
    await importHomePage(targetedHomeHtml);
  }

  if (targetedArtistSummary) {
    await importArtistPage(targetedArtistSummary);
  }

  if (targetedSetJson) {
    await importSet(targetedSetJson);
    console.log(`Imported targeted set payload ${targetedSetJson}`);
    return;
  }

  const allFiles = await walk(OUTPUT_ROOT);
  const setJsonCandidates = allFiles
    .filter(
      (filePath) =>
        filePath.endsWith(".json") &&
        !filePath.endsWith("artist_summary.json") &&
        path.basename(filePath) !== "explorer_data.json",
    )
    .sort((left, right) => left.localeCompare(right));
  const setJsonFiles: string[] = [];

  for (const filePath of setJsonCandidates) {
    try {
      await fs.access(filePath.replace(/\.json$/u, ".html"));
      setJsonFiles.push(filePath);
    } catch {
      continue;
    }
  }

  await importHomePage();
  await importArtistPages();

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

  const [homePage] = await db
    .select()
    .from(sitePages)
    .where(and(eq(sitePages.path, "/"), eq(sitePages.pageType, "home")))
    .limit(1);

  console.log(
    `Imported ${setJsonFiles.length} set pages and refreshed home page ${homePage?.path ?? "/"}.`,
  );
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

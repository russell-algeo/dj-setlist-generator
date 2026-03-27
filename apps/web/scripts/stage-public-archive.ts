import fs from "node:fs/promises";
import path from "node:path";

import { injectArchiveSocialMetadata } from "@/lib/social-preview";

const APP_ROOT = process.cwd();
const WORKSPACE_ROOT = path.resolve(APP_ROOT, "..", "..");
const OUTPUT_ROOT = path.resolve(WORKSPACE_ROOT, "output");
const PUBLIC_ROOT = path.resolve(APP_ROOT, "public");
const MANIFEST_PATH = path.resolve(PUBLIC_ROOT, ".archive-manifest.json");
const HOME_DESTINATION = "__archive-home.html";

type Manifest = {
  files: string[];
};

const normalizeRelativePath = (value: string) => value.split(path.sep).join("/");

const fileExists = async (targetPath: string) => {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
};

const readManifest = async (): Promise<Manifest> => {
  if (!(await fileExists(MANIFEST_PATH))) {
    return { files: [] };
  }

  try {
    const raw = await fs.readFile(MANIFEST_PATH, "utf8");
    const parsed = JSON.parse(raw) as Partial<Manifest>;
    return { files: Array.isArray(parsed.files) ? parsed.files.map(String) : [] };
  } catch {
    return { files: [] };
  }
};

const writeManifest = async (manifest: Manifest) => {
  await fs.writeFile(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
};

const pruneEmptyDirectories = async (startDirectory: string) => {
  let current = startDirectory;

  while (current.startsWith(PUBLIC_ROOT) && current !== PUBLIC_ROOT) {
    try {
      const entries = await fs.readdir(current);

      if (entries.length > 0) {
        return;
      }

      await fs.rmdir(current);
    } catch {
      return;
    }

    current = path.dirname(current);
  }
};

const removeStagedFiles = async (manifest: Manifest) => {
  for (const relativePath of manifest.files) {
    const absolutePath = path.resolve(PUBLIC_ROOT, relativePath);

    if (!absolutePath.startsWith(PUBLIC_ROOT)) {
      continue;
    }

    try {
      await fs.unlink(absolutePath);
      await pruneEmptyDirectories(path.dirname(absolutePath));
    } catch {
      continue;
    }
  }
};

const walkHtmlFiles = async (directory: string): Promise<string[]> => {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries
      .sort((left, right) => left.name.localeCompare(right.name))
      .map(async (entry) => {
        const absolutePath = path.resolve(directory, entry.name);

        if (entry.isDirectory()) {
          return walkHtmlFiles(absolutePath);
        }

        return absolutePath.endsWith(".html") ? [absolutePath] : [];
      }),
  );

  return nested.flat();
};

const stageHtmlFile = async (sourcePath: string) => {
  const relativePath = normalizeRelativePath(path.relative(OUTPUT_ROOT, sourcePath));
  const pagePath = relativePath === "index.html" ? "/" : `/${relativePath}`;
  const destinationRelativePath = relativePath === "index.html" ? HOME_DESTINATION : relativePath;
  const destinationPath = path.resolve(PUBLIC_ROOT, destinationRelativePath);
  const html = await fs.readFile(sourcePath, "utf8");

  await fs.mkdir(path.dirname(destinationPath), { recursive: true });
  await fs.writeFile(
    destinationPath,
    injectArchiveSocialMetadata({
      html,
      pagePath,
    }),
    "utf8",
  );

  return destinationRelativePath;
};

const main = async () => {
  const outputExists = await fileExists(OUTPUT_ROOT);
  const existingArchiveExists = await fileExists(path.resolve(PUBLIC_ROOT, HOME_DESTINATION));

  if (!outputExists) {
    if (existingArchiveExists) {
      console.log("Archive staging skipped: using already staged public HTML artifacts.");
      return;
    }

    throw new Error(
      "Archive staging failed: output/ is missing and no staged public archive artifacts exist.",
    );
  }

  const manifest = await readManifest();
  await removeStagedFiles(manifest);

  const htmlFiles = await walkHtmlFiles(OUTPUT_ROOT);
  const stagedFiles = await Promise.all(htmlFiles.map(stageHtmlFile));

  await writeManifest({
    files: stagedFiles.sort((left, right) => left.localeCompare(right)),
  });

  console.log(`Staged ${stagedFiles.length} archive HTML files into public/.`);
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

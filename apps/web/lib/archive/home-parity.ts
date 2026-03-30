import "server-only";

import fs from "node:fs/promises";
import path from "node:path";

import { asc } from "drizzle-orm";

import { normalizeLegacyPath, normalizeSearchText } from "@/lib/archive/utils";
import { getDb } from "@/lib/db/client";
import { artists, sets } from "@/lib/db/schema";

type ArchiveHomeParityPayload = {
  artistDirMapJson: string;
  cssText: string;
  dataJson: string;
  scriptText: string;
  shellHtml: string;
};

let homeParityPayloadPromise: Promise<ArchiveHomeParityPayload> | null = null;

const buildArtifactCandidates = (filename: string) => {
  const cwd = process.cwd();
  const segments = ["output", filename];

  return Array.from(
    new Set([
      path.resolve(cwd, ...segments),
      path.resolve(cwd, "..", ...segments),
      path.resolve(cwd, "..", "..", ...segments),
    ]),
  );
};

const readFirstExisting = async (filename: string) => {
  for (const candidate of buildArtifactCandidates(filename)) {
    try {
      return await fs.readFile(candidate, "utf8");
    } catch (error) {
      if (
        error &&
        typeof error === "object" &&
        "code" in error &&
        (error as NodeJS.ErrnoException).code === "ENOENT"
      ) {
        continue;
      }
      throw error;
    }
  }

  throw new Error(`Unable to locate archive artifact: ${filename}`);
};

const extractStaticSection = ({
  end,
  source,
  start,
}: {
  end: RegExp;
  source: string;
  start: RegExp;
}) => {
  const startMatch = source.match(start);
  if (!startMatch) {
    throw new Error("Unable to extract homepage parity template section.");
  }

  const startIdx = (startMatch.index ?? 0) + startMatch[0].length;
  const trailingSource = source.slice(startIdx);
  const endMatch = trailingSource.match(end);

  if (!endMatch) {
    throw new Error("Unable to extract homepage parity template section.");
  }

  const endIdx = startIdx + (endMatch.index ?? 0);
  return source.slice(startIdx, endIdx).trim();
};

const patchExplorerScript = (scriptText: string) => {
  const artistTrackQuerySource = `function artistTrackQueryHref(dirName, track) {
      if (!dirName) return '';
      const q = encodeURIComponent(\`\${track.artist || ''} \${track.title || ''}\`.trim());
      return \`\${dirName}/artist_summary.html?q=\${q}#sets-section\`;
    }`;

  const artistTrackQueryTarget = `function artistTrackQueryHref(dirName, track) {
      if (!dirName) return '';
      const previewBase = (window.__ARCHIVE_HOME_ARTIST_DIR_MAP__ || {})[String(dirName || '')];
      if (previewBase) {
        const q = encodeURIComponent(\`\${track.artist || ''} \${track.title || ''}\`.trim());
        return \`\${previewBase}?q=\${q}#sets-section\`;
      }
      const q = encodeURIComponent(\`\${track.artist || ''} \${track.title || ''}\`.trim());
      return \`\${dirName}/artist_summary.html?q=\${q}#sets-section\`;
    }`;

  const nestedSetHrefSource = `function buildTaxonomyTrackSourceGroups(track) {`;
  const nestedSetHrefTarget = `function extractArchiveTrackFragment(value) {
      const raw = String(value == null ? '' : value).trim();
      const hashIdx = raw.lastIndexOf('#');
      if (hashIdx < 0) return '';
      const tail = raw.slice(hashIdx + 1);
      return FRAGMENT_ID_RE.test(tail) ? \`#\${tail}\` : '';
    }

    function resolveArchiveSetHref(setRef) {
      const raw = String(setRef?.href || '').trim();
      const encoded = encodeLocalHref(raw);
      if (!encoded || encoded.startsWith('/archive-preview/sets/')) return encoded;

      const mapped = (DATA.all_sets || [])
        .find((setRow) => String(setRow.title || '').trim() === String(setRef?.title || '').trim())
        ?.set_html_master_rel || '';

      if (!mapped || !String(mapped).startsWith('/archive-preview/sets/')) return encoded;
      return \`\${mapped}\${extractArchiveTrackFragment(raw)}\`;
    }

    function buildTaxonomyTrackSourceGroups(track) {`;

  let patched = scriptText.replace(artistTrackQuerySource, artistTrackQueryTarget);
  patched = patched.replace(nestedSetHrefSource, nestedSetHrefTarget);
  patched = patched.replace(
    "const href = encodeLocalHref(s.href || '');",
    "const href = resolveArchiveSetHref(s);",
  );
  patched = patched.replace(
    "document.addEventListener('click', (ev) => {",
    "root.addEventListener('click', (ev) => {",
  );
  patched = patched.replace(
    "document.querySelectorAll('.reveal').forEach((el) => observer.observe(el));",
    "root.querySelectorAll('.reveal').forEach((el) => observer.observe(el));",
  );
  patched = patched.replace(
    `function fitHeroToViewport() {
      const hero = document.querySelector('.hero');
      const visual = $('heroVisual');
      const kicker = hero?.querySelector('.kicker');
      const marquee = hero?.querySelector('.marquee');
      if (!hero || !visual || !kicker || !marquee) return;

      if (window.matchMedia('(max-width: 1320px)').matches) {
        visual.style.removeProperty('height');
        return;
      }

      const kickerRect = kicker.getBoundingClientRect();
      const marqueeRect = marquee.getBoundingClientRect();
      const visualRect = visual.getBoundingClientRect();
      if (visualRect.height <= 0) return;

      const currentSpan = marqueeRect.bottom - kickerRect.top;
      const desiredSpan = window.innerHeight - kickerRect.top - 2;
      const targetVisualHeight = visualRect.height + (desiredSpan - currentSpan);
      const clamped = Math.max(300, Math.min(620, targetVisualHeight));

      if (Number.isFinite(clamped)) {
        visual.style.height = \`\${Math.round(clamped)}px\`;
      }
    }`,
    `function fitHeroToViewport() {
      const hero = document.querySelector('.hero');
      const visual = $('heroVisual');
      const kicker = hero?.querySelector('.kicker');
      const marquee = hero?.querySelector('.marquee');
      if (!hero || !visual || !kicker || !marquee) return;

      if (window.matchMedia('(max-width: 1320px)').matches) {
        visual.style.removeProperty('height');
        return;
      }

      const kickerRect = kicker.getBoundingClientRect();
      const marqueeRect = marquee.getBoundingClientRect();
      const visualRect = visual.getBoundingClientRect();
      if (visualRect.height <= 0) return;

      const currentSpan = marqueeRect.bottom - kickerRect.top;
      const desiredSpan = window.innerHeight - kickerRect.top - 2;
      const targetVisualHeight = visualRect.height + (desiredSpan - currentSpan);
      const clamped = Math.max(300, Math.min(620, targetVisualHeight));

      if (Number.isFinite(clamped)) {
        visual.style.height = \`\${Math.round(clamped)}px\`;
      }
    }`,
  );
  patched = `${patched}

requestAnimationFrame(() => {
  requestAnimationFrame(() => {
    fitHeroToViewport();
    syncHeroRailHeight();
  });
});

setTimeout(() => {
  if (window.scrollY > 0) {
    fitHeroToViewport();
    syncHeroRailHeight();
  }
}, 750);
`;

  return patched;
};

const isExternalHref = (value: string) =>
  /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(value) || value.startsWith("//");

const FRAGMENT_ID_RE = /^[A-Za-z][\w:-]*$/u;

const splitHref = (value: string) => {
  const hashIdx = value.lastIndexOf("#");
  if (hashIdx === -1) {
    return {
      base: value,
      hash: "",
    };
  }

  const tail = value.slice(hashIdx + 1);
  if (!FRAGMENT_ID_RE.test(tail)) {
    return {
      base: value,
      hash: "",
    };
  }

  return {
    base: value.slice(0, hashIdx),
    hash: value.slice(hashIdx),
  };
};

const rewriteLocalHref = ({
  artifactSetHrefMap,
  hrefMap,
  setTitleMap,
  raw,
}: {
  artifactSetHrefMap: Map<string, string>;
  hrefMap: Map<string, string>;
  setTitleMap: Map<string, string>;
  raw: string;
}) => {
  const trimmed = raw.trim();
  if (!trimmed || isExternalHref(trimmed)) {
    return raw;
  }

  const { base, hash } = splitHref(trimmed);
  const normalized = normalizeLegacyPath(base.startsWith("/") ? base : `/${base}`);
  const mapped = hrefMap.get(normalized);

  if (mapped) {
    return `${mapped}${hash}`;
  }

  const artifactMapped = artifactSetHrefMap.get(normalized);
  if (artifactMapped) {
    return `${artifactMapped}${hash}`;
  }

  const decodedBase = normalizeLegacyPath(base);
  const basename = decodedBase.split("/").filter(Boolean).at(-1) ?? "";
  const titleCandidate = basename.replace(/\.html$/iu, "");
  const titleMapped = setTitleMap.get(normalizeSearchText(titleCandidate));

  if (titleMapped) {
    return `${titleMapped}${hash}`;
  }

  const withLeadingSlash = base.startsWith("/") ? base : `/${base}`;
  return `${encodeURI(withLeadingSlash).replace(/#/g, "%23")}${hash}`;
};

const rewriteExplorerData = ({
  artifactSetHrefMap,
  hrefMap,
  setTitleMap,
  value,
}: {
  artifactSetHrefMap: Map<string, string>;
  hrefMap: Map<string, string>;
  setTitleMap: Map<string, string>;
  value: unknown;
}): unknown => {
  if (Array.isArray(value)) {
    return value.map((entry) =>
      rewriteExplorerData({
        artifactSetHrefMap,
        hrefMap,
        setTitleMap,
        value: entry,
      }),
    );
  }

  if (!value || typeof value !== "object") {
    return value;
  }

  const hrefKeys = new Set([
    "artist_html_rel",
    "html_rel",
    "href",
    "set_html_master_rel",
    "track_href",
  ]);

  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, entryValue]) => {
      if (hrefKeys.has(key) && typeof entryValue === "string") {
        return [
          key,
          rewriteLocalHref({
            artifactSetHrefMap,
            hrefMap,
            setTitleMap,
            raw: entryValue,
          }),
        ];
      }

      return [
        key,
        rewriteExplorerData({
          artifactSetHrefMap,
          hrefMap,
          setTitleMap,
          value: entryValue,
        }),
      ];
    }),
  );
};

const buildHomeParityPayloadUncached = async (): Promise<ArchiveHomeParityPayload> => {
  const [htmlSource, jsonSource] = await Promise.all([
    readFirstExisting("index.html"),
    readFirstExisting("explorer_data.json"),
  ]);

  const cssText = extractStaticSection({
    source: htmlSource,
    start: /<style>/,
    end: /<\/style>/,
  });
  const shellHtml = extractStaticSection({
    source: htmlSource,
    start: /<body>/,
    end: /<script>\s*window\.EXPLORER_DATA\s*=/,
  });
  const scriptText = patchExplorerScript(
    extractStaticSection({
      source: htmlSource,
      start: /const DATA = window\.EXPLORER_DATA;/,
      end: /<\/script>/,
    }),
  );

  const explorerData = JSON.parse(jsonSource) as Record<string, unknown>;
  const db = getDb();
  const [artistRows, setRows] = await Promise.all([
    db
      .select({
        legacyPath: artists.legacyPath,
        name: artists.name,
        slug: artists.slug,
      })
      .from(artists)
      .orderBy(asc(artists.name)),
    db
      .select({
        legacyPath: sets.legacyPath,
        slug: sets.slug,
        title: sets.title,
      })
      .from(sets),
  ]);

  const hrefMap = new Map<string, string>();
  const artistDirMap = new Map<string, string>();
  const artifactSetHrefMap = new Map<string, string>();
  const setTitleMap = new Map<string, string>();

  for (const row of artistRows) {
    if (!row.legacyPath) {
      continue;
    }

    const previewHref = `/archive-preview/artists/${row.slug}`;
    hrefMap.set(normalizeLegacyPath(row.legacyPath), previewHref);
    artistDirMap.set(row.name, previewHref);
  }

  for (const row of setRows) {
    const previewHref = `/archive-preview/sets/${row.slug}`;
    setTitleMap.set(normalizeSearchText(row.title), previewHref);

    if (row.legacyPath) {
      hrefMap.set(normalizeLegacyPath(row.legacyPath), previewHref);
    }
  }

  for (const rawSet of Array.isArray(explorerData.all_sets) ? explorerData.all_sets : []) {
    if (!rawSet || typeof rawSet !== "object") {
      continue;
    }

    const rawHref = typeof rawSet.set_html_master_rel === "string" ? rawSet.set_html_master_rel : null;
    if (!rawHref) {
      continue;
    }

    const { base } = splitHref(rawHref);
    const normalized = normalizeLegacyPath(base.startsWith("/") ? base : `/${base}`);
    const mapped = rewriteLocalHref({
      artifactSetHrefMap: new Map(),
      hrefMap,
      setTitleMap,
      raw: rawHref,
    });
    const mappedBase = splitHref(mapped).base;

    if (mappedBase.startsWith("/archive-preview/sets/")) {
      artifactSetHrefMap.set(normalized, mappedBase);
    }
  }

  const rewrittenData = rewriteExplorerData({
    artifactSetHrefMap,
    hrefMap,
    setTitleMap,
    value: explorerData,
  });

  return {
    artistDirMapJson: JSON.stringify(Object.fromEntries(artistDirMap)),
    cssText,
    dataJson: JSON.stringify(rewrittenData),
    scriptText,
    shellHtml,
  };
};

export const getArchiveHomeParityPayload = async () => {
  if (!homeParityPayloadPromise) {
    homeParityPayloadPromise = buildHomeParityPayloadUncached();
  }

  return homeParityPayloadPromise;
};

export type { ArchiveHomeParityPayload };

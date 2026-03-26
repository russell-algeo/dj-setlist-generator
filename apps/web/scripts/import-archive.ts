import fs from "node:fs/promises";
import path from "node:path";

import { and, eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import {
  artists,
  setArtists,
  setEntries,
  sets,
  sitePages,
  trackArtists,
  tracks,
} from "@/lib/db/schema";
import {
  detectSourcePlatform,
  hashSuffix,
  makeSlug,
  normalizeText,
  toLegacyPath,
} from "@/lib/archive/import-helpers";

type SetJson = {
  mix_info: Record<string, unknown>;
  metadata: {
    total_tracks?: number;
    uncertain_tracks?: number;
    [key: string]: unknown;
  };
  tracks: Array<Record<string, unknown>>;
};

const OUTPUT_ROOT = path.resolve(process.cwd(), "..", "..", "output");

const readJson = async <T>(filePath: string) =>
  JSON.parse(await fs.readFile(filePath, "utf8")) as T;

const readHtml = async (filePath: string) => fs.readFile(filePath, "utf8");
const optionalResolvedPath = (value: string | undefined) =>
  value ? path.resolve(value) : undefined;

const upsertArtist = async (
  db: ReturnType<typeof getDb>,
  artistName: string,
  legacyPath?: string,
  metadata: Record<string, unknown> = {},
) => {
  const normalizedName = normalizeText(artistName);
  const slug = makeSlug(artistName);
  const [existingArtist] = await db.select().from(artists).where(eq(artists.slug, slug)).limit(1);
  const nextLegacyPath = legacyPath ?? existingArtist?.legacyPath ?? null;
  const nextImageUrl =
    (metadata.artist_profile_image as string | undefined) ?? existingArtist?.imageUrl ?? null;
  const nextSpotifyArtistUrl =
    (metadata.spotify_artist_profile_url as string | undefined) ??
    existingArtist?.spotifyArtistUrl ??
    null;
  const nextDiscogsArtistUrl =
    (metadata.discogs_artist_profile_url as string | undefined) ??
    existingArtist?.discogsArtistUrl ??
    null;

  await db
    .insert(artists)
    .values({
      slug,
      name: artistName,
      normalizedName,
      legacyPath: nextLegacyPath,
      metadata,
      imageUrl: nextImageUrl,
      spotifyArtistUrl: nextSpotifyArtistUrl,
      discogsArtistUrl: nextDiscogsArtistUrl,
    })
    .onConflictDoUpdate({
      target: artists.slug,
      set: {
        name: artistName,
        normalizedName,
        legacyPath: nextLegacyPath,
        metadata,
        imageUrl: nextImageUrl,
        spotifyArtistUrl: nextSpotifyArtistUrl,
        discogsArtistUrl: nextDiscogsArtistUrl,
        updatedAt: new Date(),
      },
    });

  const [artist] = await db.select().from(artists).where(eq(artists.slug, slug)).limit(1);

  return artist;
};

const trackKeyForRow = (row: Record<string, unknown>) => {
  const shazamTrackId = row.shazam_track_id as string | undefined;
  const artist = String(row.artist ?? "");
  const title = String(row.title ?? "");

  if (shazamTrackId) {
    return `shazam:${shazamTrackId}`;
  }

  return `fallback:${normalizeText(`${artist} ${title}`)}`;
};

const upsertTrack = async (
  db: ReturnType<typeof getDb>,
  row: Record<string, unknown>,
) => {
  const artistName = String(row.artist ?? "Unknown");
  const title = String(row.title ?? "Unknown Track");
  const trackKey = trackKeyForRow(row);
  const suffix = hashSuffix(trackKey);
  const slug = makeSlug(`${artistName}-${title}`, suffix);

  await db
    .insert(tracks)
    .values({
      slug,
      title,
      normalizedTitle: normalizeText(title),
      primaryArtistName: artistName,
      shazamTrackId: (row.shazam_track_id as string | undefined) ?? null,
      spotifyUrl: (row.spotify_url as string | undefined) ?? null,
      youtubeUrl: (row.youtube_url as string | undefined) ?? null,
      discogsUrl: (row.discogs_url as string | undefined) ?? null,
      metadata: row,
    })
    .onConflictDoUpdate({
      target: tracks.slug,
      set: {
        title,
        normalizedTitle: normalizeText(title),
        primaryArtistName: artistName,
        shazamTrackId: (row.shazam_track_id as string | undefined) ?? null,
        spotifyUrl: (row.spotify_url as string | undefined) ?? null,
        youtubeUrl: (row.youtube_url as string | undefined) ?? null,
        discogsUrl: (row.discogs_url as string | undefined) ?? null,
        metadata: row,
        updatedAt: new Date(),
      },
    });

  const [track] = await db.select().from(tracks).where(eq(tracks.slug, slug)).limit(1);
  const artist = await upsertArtist(db, artistName);

  await db
    .insert(trackArtists)
    .values({
      trackId: track.id,
      artistId: artist.id,
      role: "primary",
    })
    .onConflictDoNothing();

  return track;
};

const importSet = async (db: ReturnType<typeof getDb>, jsonPath: string) => {
  const payload = await readJson<SetJson>(jsonPath);
  const mixInfo = payload.mix_info;
  const setTitle = String(mixInfo.title ?? path.basename(jsonPath, ".json"));
  const sourceUrl = (mixInfo.url as string | undefined) ?? null;
  const mixArtistName = String(mixInfo.artist_name ?? "").trim();
  const artistDirectory = path.basename(path.dirname(path.dirname(jsonPath)));
  const inferredArtistName =
    artistDirectory && artistDirectory !== path.basename(OUTPUT_ROOT) ? artistDirectory : "";
  const artistName = mixArtistName || inferredArtistName || null;
  const artist = artistName ? await upsertArtist(db, artistName, undefined, mixInfo) : null;
  const relativeIdentity = path.relative(OUTPUT_ROOT, jsonPath);
  const proposedSetSlug = makeSlug(setTitle, hashSuffix(sourceUrl ?? relativeIdentity));
  const htmlPath = jsonPath.replace(/\.json$/u, ".html");
  const legacyPath = toLegacyPath(OUTPUT_ROOT, htmlPath);
  const totalTracks = Number(payload.metadata.total_tracks ?? payload.tracks.length ?? 0);
  const uncertainTracks = Number(payload.metadata.uncertain_tracks ?? 0);
  const recognitionRate =
    totalTracks > 0 ? (((totalTracks - uncertainTracks) / totalTracks) * 100).toFixed(2) : null;
  const [existingSet] = sourceUrl
    ? await db.select().from(sets).where(eq(sets.sourceUrl, sourceUrl)).limit(1)
    : [];
  const setSlug = proposedSetSlug;
  const canonicalLegacyPath = existingSet?.legacyPath ?? legacyPath;
  const setValues = {
    slug: setSlug,
    title: setTitle,
    normalizedTitle: normalizeText(setTitle),
    sourcePlatform: detectSourcePlatform(sourceUrl ?? undefined),
    sourceUrl,
    durationSeconds: Math.round(Number(mixInfo.duration ?? 0)),
    uploader: (mixInfo.uploader as string | undefined) ?? null,
    imageUrl: (mixInfo.artist_profile_image as string | undefined) ?? null,
    recognitionRate,
    legacyPath: canonicalLegacyPath,
    metadata: {
      mixInfo,
      summary: payload.metadata,
      importProvenance: {
        source: "output",
        relativeJsonPath: relativeIdentity,
        relativeHtmlPath: path.relative(OUTPUT_ROOT, htmlPath),
      },
    },
  } as const;

  const upsertSet = db.insert(sets).values(setValues);

  if (sourceUrl) {
    await upsertSet.onConflictDoUpdate({
      target: sets.sourceUrl,
      set: {
        ...setValues,
        legacyPath: canonicalLegacyPath,
        updatedAt: new Date(),
      },
    });
  } else {
    await upsertSet.onConflictDoUpdate({
      target: sets.slug,
      set: {
        ...setValues,
        updatedAt: new Date(),
      },
    });
  }

  const [setRecord] = await db
    .select()
    .from(sets)
    .where(sourceUrl ? eq(sets.sourceUrl, sourceUrl) : eq(sets.slug, setSlug))
    .limit(1);

  if (artist) {
    await db
      .insert(setArtists)
      .values({
        setId: setRecord.id,
        artistId: artist.id,
        role: "primary",
      })
      .onConflictDoNothing();
  }

  await db.delete(setEntries).where(eq(setEntries.setId, setRecord.id));

  for (const [index, trackRow] of payload.tracks.entries()) {
    const isUnknown = String(trackRow.artist ?? "") === "Unknown";
    const trackRecord = isUnknown ? null : await upsertTrack(db, trackRow);

    await db.insert(setEntries).values({
      setId: setRecord.id,
      trackId: trackRecord?.id ?? null,
      position: Number(trackRow.position ?? index + 1),
      displayArtist: String(trackRow.artist ?? "Unknown"),
      displayTitle: String(trackRow.title ?? "Unknown Track"),
      startTimeSeconds: Math.round(Number(trackRow.start_time ?? 0)),
      endTimeSeconds:
        trackRow.end_time == null ? null : Math.round(Number(trackRow.end_time)),
      confidence: String(trackRow.confidence ?? "UNCERTAIN"),
      detectionCount: Number(trackRow.detection_count ?? 0),
      clusterDensity:
        trackRow.cluster_density == null ? null : String(trackRow.cluster_density),
      clusterSpan:
        trackRow.cluster_span == null ? null : Number(trackRow.cluster_span),
      sourceDeepLink: (trackRow.source_deep_link as string | undefined) ?? null,
      metadata: trackRow,
    });
  }

  const html = await readHtml(htmlPath);

  await db
    .insert(sitePages)
    .values({
      path: legacyPath,
      pageType: "set",
      setId: setRecord.id,
      artistId: artist?.id ?? null,
      slug: setRecord.slug,
      html,
      metadata: {
        entity: "set",
      },
    })
    .onConflictDoUpdate({
      target: sitePages.path,
      set: {
        pageType: "set",
        setId: setRecord.id,
        artistId: artist?.id ?? null,
        slug: setRecord.slug,
        html,
        metadata: {
          entity: "set",
        },
        updatedAt: new Date(),
      },
    });
};

const importArtistPages = async (db: ReturnType<typeof getDb>) => {
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
  }
};

const importHomePage = async (db: ReturnType<typeof getDb>) => {
  const homeHtmlPath = path.join(OUTPUT_ROOT, "index.html");
  const html = await readHtml(homeHtmlPath);

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
    const html = await readHtml(targetedHomeHtml);
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
  }

  if (targetedArtistSummary) {
    const artistName = path.basename(path.dirname(targetedArtistSummary));
    const legacyPath = toLegacyPath(OUTPUT_ROOT, targetedArtistSummary);
    const artist = await upsertArtist(db, artistName, legacyPath);
    const html = await readHtml(targetedArtistSummary);

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
  }

  if (targetedSetJson) {
    await importSet(db, targetedSetJson);
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

  await importHomePage(db);
  await importArtistPages(db);

  for (const [index, filePath] of setJsonFiles.entries()) {
    try {
      await importSet(db, filePath);
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

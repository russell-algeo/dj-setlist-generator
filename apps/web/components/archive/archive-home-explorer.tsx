/* eslint-disable @next/next/no-img-element */
"use client";

import {
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent,
} from "react";

import { buildArtistHref, buildSetHref } from "@/components/archive/archive-hrefs";
import { ArchiveHeader } from "@/components/archive/archive-header";
import {
  ArchiveEvidenceTrackCard,
  type ArchiveEvidenceTrackCardSourceGroup,
} from "@/components/archive/archive-evidence-track-card";
import { ArchiveSetCard } from "@/components/archive/archive-set-card";
import { ArchiveScrollRoot } from "@/components/archive/archive-scroll-root";
import { ArchiveTaxonomyPanel } from "@/components/archive/archive-taxonomy-panel";
import { InlineSubmitButton } from "@/components/archive/inline-submit-button";
import { ARCHIVE_HOME_EXPLORER_CSS } from "@/components/archive/archive-home-explorer.styles";
import type {
  ArchiveHomeAtlasSelectionPayload,
  ArchiveHomeArtistCard,
  ArchiveHomeBootstrapPayload,
  ArchiveHomeCompareMode,
  ArchiveHomeNetworkIndexPayload,
  ArchiveHomePairBucket,
  ArchiveHomePairSelectionPayload,
  ArchiveHomePairTrack,
  ArchiveHomeSetLibraryPagePayload,
  ArchiveHomeSetLibraryTrack,
  ArchiveHomeSetSort,
  ArchiveHomeSetTracklistPayload,
  ArchiveHomeTaxonomyLens,
  ArchiveHomeTrackArtistRef,
  ArchiveHomeTrackCatalogItem,
  ArchiveHomeTrackSetRef,
} from "@/lib/archive/home-explorer-types";
import type { ArchiveConfidence } from "@/lib/archive/types";
import { buildSearchBlob, extractSpotifyTrackId, normalizeSearchText } from "@/lib/archive/utils";

type ConfidenceFilter = ArchiveConfidence | "all";
type PairLens = "artists" | "genres" | "labels" | "tracks";
type TrackCardOpenState = {
  sourcesOpen: boolean;
  spotifyOpen: boolean;
};
type TrackCardStyle = CSSProperties & Partial<Record<`--${string}`, string>>;
type NetworkPointerState = {
  active: boolean;
  x: number;
  y: number;
};
type NetworkTouchGesture = {
  touches: Array<{ id: number; x: number; y: number }>;
  startScale: number;
  startPanX: number;
  startPanY: number;
  startDist: number;
  zoomOriginSvgX: number;
  zoomOriginSvgY: number;
};
type NetworkZoom = { scale: number; panX: number; panY: number };

const CONF_FILTER_LEVELS: ConfidenceFilter[] = ["all", "HIGH", "MEDIUM", "LOW"];
const THRESHOLD_LEVELS = [1, 2, 3, 5, 8, 12] as const;
const DEFAULT_NETWORK_MIN_SCORE = 7.5;
const NETWORK_EDGE_VISUAL_CURVE = 0.6;
const NETWORK_EDGE_ALPHA_FLOOR = 0.18;
const NETWORK_EDGE_ALPHA_RANGE = 0.58;
const NETWORK_EDGE_WIDTH_BASE = 1;
const NETWORK_EDGE_WIDTH_RANGE = 2;
const NETWORK_LENS_RADIUS = 96;
const NETWORK_LENS_FALLOFF = 1.8;
const NETWORK_NODE_BASE_RADIUS = 12;
const NETWORK_NODE_MAX_SCALE = 1.8;
const NETWORK_LABEL_BASE_SIZE = 11;
const NETWORK_LABEL_SIZE_RANGE = 7;
const NETWORK_LABEL_OUTSET = 4;
const NETWORK_LABEL_OUTSET_RANGE = 10;
const NETWORK_LABEL_HALO_RANGE = 6;
const NETWORK_SELECTED_LENS_FLOOR = 0.2;
const OPEN_EVIDENCE_ACTION_ROW_HEIGHT = 36;
const PAGE = {
  evidence: 9,
  pairRows: 10,
  taxonomy: 10,
} as const;
const FALLBACK_MEDIA = [
  ["#0b0b0b", "#f2f2f2", "#d8ff5a"],
  ["#101114", "#eceef2", "#7f51ff"],
  ["#0e1011", "#e4f4ff", "#d8ff5a"],
  ["#12100e", "#f6efe4", "#7f51ff"],
  ["#0c0f13", "#f1f5ff", "#d8ff5a"],
  ["#0f0c12", "#f3edf9", "#7f51ff"],
  ["#0f1110", "#e9f4e8", "#d8ff5a"],
  ["#100f0d", "#f3efe8", "#7f51ff"],
] as const;

const joinClasses = (...values: Array<string | false | null | undefined>) =>
  values.filter(Boolean).join(" ");

const fmt = (value: number) => value.toLocaleString("en-US");

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));

const isHoverCapablePointer = () =>
  typeof window !== "undefined" && window.matchMedia("(hover: hover) and (pointer: fine)").matches;

const buildNetworkEdgeVisual = (normalizedScore: number) => {
  const normalized = clamp(normalizedScore / 100, 0, 1);
  const visualWeight = Math.pow(normalized, NETWORK_EDGE_VISUAL_CURVE);
  const alpha = NETWORK_EDGE_ALPHA_FLOOR + visualWeight * NETWORK_EDGE_ALPHA_RANGE;
  const strokeWidth = NETWORK_EDGE_WIDTH_BASE + visualWeight * NETWORK_EDGE_WIDTH_RANGE;

  return {
    stroke: `rgba(216,255,90,${alpha.toFixed(3)})`,
    strokeWidth: strokeWidth.toFixed(2),
  };
};

const hashString = (value: string) => {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0;
  }
  return Math.abs(hash);
};

const buildFallbackSvg = (background: string, ink: string, accent: string) =>
  `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800">
      <rect width="800" height="800" fill="${background}"/>
      <rect x="40" y="44" width="720" height="26" fill="${ink}" opacity="0.65"/>
      <rect x="40" y="106" width="540" height="18" fill="${ink}" opacity="0.45"/>
      <rect x="40" y="158" width="640" height="10" fill="${ink}" opacity="0.25"/>
      <rect x="40" y="230" width="180" height="180" fill="${accent}" opacity="0.9"/>
      <rect x="248" y="230" width="512" height="180" fill="${ink}" opacity="0.2"/>
      <rect x="40" y="438" width="720" height="14" fill="${ink}" opacity="0.3"/>
      <rect x="40" y="478" width="420" height="92" fill="${ink}" opacity="0.22"/>
      <rect x="488" y="478" width="272" height="92" fill="${accent}" opacity="0.8"/>
      <rect x="40" y="608" width="720" height="150" fill="${ink}" opacity="0.15"/>
    </svg>`,
  )}`;

const fallbackMedia = (seed: string) => {
  const [background, ink, accent] = FALLBACK_MEDIA[hashString(seed) % FALLBACK_MEDIA.length]!;
  return buildFallbackSvg(background, ink, accent);
};

const normalizeThresholdValue = (current: number, levels: readonly number[]) => {
  const safeCurrent = Number.isFinite(current) && current > 0 ? Math.floor(current) : levels[0];
  return levels.includes(safeCurrent as (typeof levels)[number])
    ? safeCurrent
    : (levels[0] ?? 1);
};

const stepThresholdValue = (
  current: number,
  levels: readonly number[],
  direction: -1 | 1,
) => {
  const normalized = normalizeThresholdValue(current, levels);
  const index = levels.findIndex((value) => value === normalized);
  const nextIndex = clamp(index + direction, 0, levels.length - 1);
  return levels[nextIndex] ?? levels[0] ?? 1;
};

const primaryConfidenceFromCounts = (
  counts: Record<ArchiveConfidence, number>,
): ArchiveConfidence => {
  let best: ArchiveConfidence = "UNCERTAIN";
  for (const level of ["HIGH", "MEDIUM", "LOW", "UNCERTAIN"] as const) {
    if (counts[level] > counts[best]) {
      best = level;
    }
  }
  return best;
};

const emptyConfidenceCounts = (): Record<ArchiveConfidence, number> => ({
  HIGH: 0,
  LOW: 0,
  MEDIUM: 0,
  UNCERTAIN: 0,
});

const filterTrackRefsByConfidence = (
  setRefs: ArchiveHomeTrackSetRef[],
  filter: ConfidenceFilter,
) =>
  filter === "all"
    ? setRefs
    : setRefs.filter((setRef) => setRef.confidence === filter);

const projectTrackByConfidence = (
  track: ArchiveHomeTrackCatalogItem,
  filter: ConfidenceFilter,
): ArchiveHomeTrackCatalogItem | null => {
  if (filter === "all") {
    return track;
  }

  const nextArtistRefs: ArchiveHomeTrackArtistRef[] = [];
  const nextConfidenceCounts = emptyConfidenceCounts();
  let totalAppearances = 0;

  for (const artistRef of track.artistRefs) {
    const setRefs = filterTrackRefsByConfidence(artistRef.setRefs, filter);
    if (!setRefs.length) {
      continue;
    }

    totalAppearances += setRefs.length;
    nextConfidenceCounts[filter] += setRefs.length;
    nextArtistRefs.push({
      ...artistRef,
      appearances: setRefs.length,
      setRefs,
    });
  }

  if (!nextArtistRefs.length) {
    return null;
  }

  return {
    ...track,
    artistRefs: nextArtistRefs,
    artistsCount: nextArtistRefs.length,
    confidence: filter,
    confidenceCounts: nextConfidenceCounts,
    totalAppearances,
  };
};

const buildTrackQueryHref = ({
  artistSlug,
  query,
}: {
  artistSlug: string;
  query: string;
}) => {
  const base = buildArtistHref({ slug: artistSlug });
  return `${base}?q=${encodeURIComponent(query)}#sets-section`;
};

const buildTrackSetHref = ({
  setSlug,
  trackPosition,
}: {
  setSlug: string;
  trackPosition: number;
}) => `${buildSetHref({ slug: setSlug })}#track-${trackPosition}`;

const buildTrackCardStyle = (
  card: HTMLElement | null,
  panel: "embed" | "source",
): TrackCardStyle | null => {
  if (!card) {
    return null;
  }

  const art = card.querySelector<HTMLElement>(".track-art");
  const body = card.querySelector<HTMLElement>(".track-body");
  const actionsWrap = body?.querySelector<HTMLElement>(".actions");
  const cardHeight = Math.round(card.getBoundingClientRect().height);

  if (cardHeight > 0) {
    const targetPanelHeight = 91.2;
    const controls = actionsWrap ?? body;
    const actionsHeight = controls
      ? Math.max(OPEN_EVIDENCE_ACTION_ROW_HEIGHT, Math.round(controls.getBoundingClientRect().height))
      : OPEN_EVIDENCE_ACTION_ROW_HEIGHT;
    const bodyHeight = Math.min(cardHeight, actionsHeight + targetPanelHeight);
    const artHeight = Math.max(0, cardHeight - bodyHeight);
    const panelHeight = Math.max(0, bodyHeight - actionsHeight);

    return {
      "--open-action-row-height": `${actionsHeight}px`,
      "--open-art-height": `${Math.max(0, artHeight)}px`,
      "--open-body-height": `${Math.max(0, bodyHeight)}px`,
      "--open-card-height": `${cardHeight}px`,
      [panel === "embed" ? "--open-embed-height" : "--open-source-height"]: `${Math.max(0, panelHeight)}px`,
    };
  }

  if (art) {
    return {
      "--open-art-height": `${Math.round(art.getBoundingClientRect().height)}px`,
    };
  }

  return null;
};

const buildTaxonomyRows = ({
  lens,
  query,
  sort,
  trackCatalog,
}: {
  lens: ArchiveHomeTaxonomyLens;
  query: string;
  sort: "alpha" | "count";
  trackCatalog: ArchiveHomeTrackCatalogItem[];
}) => {
  const bucket = new Map<
    string,
    {
      count: number;
      id: string;
      labelUrl: string | null;
      name: string;
      tracks: Map<string, ArchiveHomeTrackCatalogItem>;
    }
  >();

  const put = (name: string, track: ArchiveHomeTrackCatalogItem) => {
    const key = name.trim() || "Unknown";
    const existing =
      bucket.get(key) ??
      {
        count: 0,
        id: key,
        labelUrl: null,
        name: key,
        tracks: new Map<string, ArchiveHomeTrackCatalogItem>(),
      };

    existing.tracks.set(track.trackKey, track);
    existing.count += lens === "tracks" ? track.totalAppearances : 1;
    if (!existing.labelUrl && lens === "labels" && track.labelUrl) {
      existing.labelUrl = track.labelUrl;
    }
    bucket.set(key, existing);
  };

  for (const track of trackCatalog) {
    if (lens === "genres") {
      const genres = track.genres.length ? track.genres : ["Unknown Genre"];
      genres.forEach((genre) => put(genre, track));
      continue;
    }
    if (lens === "labels") {
      put(track.label ?? "Unknown Label", track);
      continue;
    }
    if (lens === "track-artists") {
      put(track.artist || "Unknown Artist", track);
      continue;
    }
    put(`${track.artist || "Unknown"} - ${track.title || "Unknown"}`, track);
  }

  const normalizedQuery = normalizeSearchText(query);
  const rows = Array.from(bucket.values())
    .map((row) => ({
      count: row.count,
      id: row.id,
      labelUrl: row.labelUrl,
      name: row.name,
      searchBlob: buildSearchBlob(row.name),
      tracks: Array.from(row.tracks.values()).sort((left, right) => {
        if (right.totalAppearances !== left.totalAppearances) {
          return right.totalAppearances - left.totalAppearances;
        }
        return `${left.artist} ${left.title}`.localeCompare(`${right.artist} ${right.title}`);
      }),
    }))
    .filter((row) => (normalizedQuery ? row.searchBlob.includes(normalizedQuery) : true))
    .sort((left, right) => {
      if (sort === "alpha") {
        return left.name.localeCompare(right.name);
      }
      if (right.count !== left.count) {
        return right.count - left.count;
      }
      return left.name.localeCompare(right.name);
    });

  return rows;
};

const buildPairRows = ({
  confidence,
  lens,
  minUsage,
  pairPayload,
  query,
  sort,
}: {
  confidence: ConfidenceFilter;
  lens: PairLens;
  minUsage: number;
  pairPayload: ArchiveHomePairSelectionPayload;
  query: string;
  sort: "alpha" | "count";
}) => {
  const projectedTracks = pairPayload.sharedTracks
    .map((track) => projectPairTrackByConfidence(track, confidence))
    .filter((track): track is ArchiveHomePairTrack => Boolean(track));

  let rows: Array<{
    count: number;
    id: string;
    meta: string;
    name: string;
    tracks: ArchiveHomePairTrack[];
  }> = [];

  if (lens === "tracks") {
    rows = projectedTracks.map((track) => ({
      count: track.appearancesA + track.appearancesB,
      id: track.trackKey,
      meta: `${pairPayload.artistA.name} ${fmt(track.appearancesA)} | ${pairPayload.artistB.name} ${fmt(track.appearancesB)}`,
      name: `${track.artist} - ${track.title}`,
      tracks: [track],
    }));
  } else {
    const sourceBuckets: ArchiveHomePairBucket[] =
      lens === "genres"
        ? pairPayload.sharedGenres
        : lens === "labels"
          ? pairPayload.sharedLabels
          : pairPayload.sharedMusicArtists;
    const trackMap = new Map(projectedTracks.map((track) => [track.trackKey, track]));

    rows = sourceBuckets.map((bucket) => ({
      count: bucket.trackKeys.filter((trackKey) => trackMap.has(trackKey)).length,
      id: bucket.id,
      meta: `${pairPayload.artistA.name} ${fmt(bucket.countA)} | ${pairPayload.artistB.name} ${fmt(bucket.countB)}`,
      name: bucket.name,
      tracks: bucket.trackKeys
        .map((trackKey) => trackMap.get(trackKey))
        .filter((track): track is ArchiveHomePairTrack => Boolean(track)),
    }));
  }

  const normalizedQuery = normalizeSearchText(query);
  rows = rows
    .filter((row) => row.count >= minUsage)
    .filter((row) =>
      normalizedQuery ? buildSearchBlob(row.name).includes(normalizedQuery) : true,
    )
    .sort((left, right) => {
      if (sort === "alpha") {
        return left.name.localeCompare(right.name);
      }
      if (right.count !== left.count) {
        return right.count - left.count;
      }
      return left.name.localeCompare(right.name);
    });

  return rows;
};

const buildFocusStats = ({
  artistCards,
  selectedArtistSlugs,
  trackCatalog,
}: {
  artistCards: ArchiveHomeArtistCard[];
  selectedArtistSlugs: string[];
  trackCatalog: ArchiveHomeTrackCatalogItem[];
}) => {
  if (selectedArtistSlugs.length === 1) {
    const artistCard = artistCards.find((artist) => artist.slug === selectedArtistSlugs[0]);
    return {
      artists: 1,
      appearances: artistCard?.totalAppearances ?? 0,
      sets: artistCard?.setCount ?? 0,
      uniqueTracks: artistCard?.uniqueTracks ?? 0,
    };
  }

  const setKeys = new Set<string>();
  let totalAppearances = 0;
  for (const track of trackCatalog) {
    totalAppearances += track.totalAppearances;
    for (const artistRef of track.artistRefs) {
      for (const setRef of artistRef.setRefs) {
        setKeys.add(`${artistRef.artistSlug}::${setRef.title}`);
      }
    }
  }

  return {
    artists: selectedArtistSlugs.length,
    appearances: totalAppearances,
    sets: setKeys.size,
    uniqueTracks: trackCatalog.length,
  };
};

const buildPairLookupKey = (leftSlug: string, rightSlug: string) =>
  [leftSlug, rightSlug].sort().join("::");

const projectPairTrackByConfidence = (
  track: ArchiveHomePairTrack,
  filter: ConfidenceFilter,
): ArchiveHomePairTrack | null => {
  if (filter === "all") {
    return track;
  }

  const setsA = track.setsA.filter((setRef) => setRef.confidence === filter);
  const setsB = track.setsB.filter((setRef) => setRef.confidence === filter);
  const appearancesA = setsA.length;
  const appearancesB = setsB.length;
  const totalAppearances = appearancesA + appearancesB;

  if (!totalAppearances) {
    return null;
  }

  const confidenceCounts = emptyConfidenceCounts();
  confidenceCounts[filter] = totalAppearances;

  return {
    ...track,
    appearancesA,
    appearancesB,
    confidence: filter,
    confidenceCounts,
    setsA,
    setsB,
  };
};

const buildTrackCardSourceGroups = (
  track: ArchiveHomePairTrack | ArchiveHomeTrackCatalogItem,
): ArchiveEvidenceTrackCardSourceGroup[] => {
  const sourceGroups = "artistRefs" in track
    ? track.artistRefs
    : [
        {
          appearances: track.appearancesA,
          artistName: "",
          artistSlug: "",
          setRefs: track.setsA,
        },
        {
          appearances: track.appearancesB,
          artistName: "",
          artistSlug: "",
          setRefs: track.setsB,
        },
      ].filter((group) => group.setRefs.length > 0);

  return sourceGroups.map((group, index) => {
    const queryHref =
      "artistSlug" in group && group.artistSlug
        ? buildTrackQueryHref({
            artistSlug: group.artistSlug,
            query: `${track.artist} ${track.title}`.trim(),
          })
        : null;

    return {
      emptyLabel: "No set links",
      id: `${track.trackKey}-source-${index}`,
      links: group.setRefs.slice(0, 8).map((setRef) => ({
        href: buildTrackSetHref({
          setSlug: setRef.setSlug,
          trackPosition: setRef.trackPosition,
        }),
        id: `${track.trackKey}-${setRef.setSlug}-${setRef.trackPosition}`,
        label: setRef.title,
      })),
      title: group.artistName || `Source ${index + 1}`,
      titleHref: queryHref,
    };
  });
};

export function ArchiveHomeExplorer({
  initial,
}: {
  initial: ArchiveHomeBootstrapPayload;
}) {
  const scope = initial.scope ?? "global";
  const rootRef = useRef<HTMLDivElement | null>(null);
  const artistGridRef = useRef<HTMLDivElement | null>(null);
  const heroVisualRef = useRef<HTMLDivElement | null>(null);
  const heroStatsRef = useRef<HTMLDivElement | null>(null);
  const heroSideRef = useRef<HTMLDivElement | null>(null);
  const heroSideViewportRef = useRef<HTMLDivElement | null>(null);
  const heroSideTrackRef = useRef<HTMLDivElement | null>(null);
  const networkSectionRef = useRef<HTMLElement | null>(null);
  const networkWrapRef = useRef<HTMLDivElement | null>(null);
  const networkTouchRef = useRef<NetworkTouchGesture | null>(null);
  const [selectedArtistSlugs, setSelectedArtistSlugs] = useState<string[]>(
    initial.initialAtlas.selectedArtistSlugs,
  );
  const [focusArtistSlug, setFocusArtistSlug] = useState<string | null>(
    initial.initialAtlas.focusArtistSlug,
  );
  const [compareMode, setCompareMode] = useState<ArchiveHomeCompareMode>(
    initial.initialAtlas.compareMode,
  );
  const [atlasPayload, setAtlasPayload] = useState<ArchiveHomeAtlasSelectionPayload>(
    initial.initialAtlas,
  );
  const [artistQuery, setArtistQuery] = useState("");
  const [dockedSelectedArtistSlugs, setDockedSelectedArtistSlugs] = useState<string[]>(
    initial.initialAtlas.selectedArtistSlugs,
  );
  const [hoverLatchedArtistSlug, setHoverLatchedArtistSlug] = useState<string | null>(null);
  const [artistPanePointerInside, setArtistPanePointerInside] = useState(false);
  const touchArtistStackEngagedRef = useRef(false);
  const touchArtistScrollStartYRef = useRef(0);
  const touchArtistDidScrollRef = useRef(false);
  const touchArtistLastScrollTimeRef = useRef(0);
  const pendingTapArtistSlugRef = useRef<string | null>(null);
  const latestSelectedArtistSlugsRef = useRef(selectedArtistSlugs);
  const pendingArtistGridResetRef = useRef(false);

  const [taxonomyLens, setTaxonomyLens] = useState<ArchiveHomeTaxonomyLens>("genres");
  const [taxonomyQuery, setTaxonomyQuery] = useState("");
  const [taxonomySort, setTaxonomySort] = useState<"alpha" | "count">("count");
  const [taxonomyThreshold, setTaxonomyThreshold] = useState(1);
  const [taxonomyConfidence, setTaxonomyConfidence] =
    useState<ConfidenceFilter>("all");
  const [taxonomyPage, setTaxonomyPage] = useState(0);
  const [taxonomyActiveName, setTaxonomyActiveName] = useState<string | null>(null);
  const [trackCardStates, setTrackCardStates] = useState<Record<string, TrackCardOpenState>>({});
  const [trackCardStyles, setTrackCardStyles] = useState<Record<string, TrackCardStyle | null>>({});

  const networkPayload = initial.initialNetwork as ArchiveHomeNetworkIndexPayload;
  const [networkLayoutVersion, setNetworkLayoutVersion] = useState(0);
  const [networkMinScore, setNetworkMinScore] = useState(DEFAULT_NETWORK_MIN_SCORE);
  const [networkSearch, setNetworkSearch] = useState("");
  const [networkSelectedArtistSlugs, setNetworkSelectedArtistSlugs] = useState<string[]>([]);
  const [networkLensEnabled, setNetworkLensEnabled] = useState(false);
  const [networkPointer, setNetworkPointer] = useState<NetworkPointerState>({
    active: false,
    x: 0,
    y: 0,
  });
  const [networkZoom, setNetworkZoom] = useState<NetworkZoom>({ scale: 1, panX: 0, panY: 0 });
  const networkZoomRef = useRef<NetworkZoom>({ scale: 1, panX: 0, panY: 0 });

  const [pairPayload, setPairPayload] = useState<ArchiveHomePairSelectionPayload | null>(null);
  const [pairLens, setPairLens] = useState<PairLens>("genres");
  const [pairQuery, setPairQuery] = useState("");
  const [pairSort, setPairSort] = useState<"alpha" | "count">("count");
  const [pairThreshold, setPairThreshold] = useState(1);
  const [pairConfidence, setPairConfidence] = useState<ConfidenceFilter>("all");
  const [pairPage, setPairPage] = useState(0);
  const [pairActiveName, setPairActiveName] = useState<string | null>(null);

  const [setLibrary, setSetLibrary] = useState<ArchiveHomeSetLibraryPagePayload>(
    initial.initialSetLibrary,
  );
  const [setQuery, setSetQuery] = useState(initial.initialSetLibrary.query);
  const [setArtistFilter, setSetArtistFilter] = useState(initial.initialSetLibrary.artistFilter);
  const [setSort, setSetSort] = useState<ArchiveHomeSetSort>(initial.initialSetLibrary.sort);
  const [setPage, setSetPage] = useState(initial.initialSetLibrary.page);
  const [expandedSets, setExpandedSets] = useState<string[]>([]);
  const [setTracklists, setSetTracklists] = useState<Record<string, ArchiveHomeSetLibraryTrack[]>>(
    {},
  );
  const [loadingTracklists, setLoadingTracklists] = useState<Record<string, boolean>>({});
  const [tracklistErrors, setTracklistErrors] = useState<Record<string, string>>({});

  const artistCards = initial.artistCards;
  // In workspace mode, do not pre-populate the atlas cache with server-rendered data so the
  // useEffect always fires a fresh workspace-scoped fetch on mount.
  const atlasCacheRef = useRef(
    initial.scope === "mine"
      ? new Map<string, ArchiveHomeAtlasSelectionPayload>()
      : new Map<string, ArchiveHomeAtlasSelectionPayload>([
          [
            `${initial.initialAtlas.compareMode}::${initial.initialAtlas.selectedArtistSlugs.join(",")}`,
            initial.initialAtlas,
          ],
        ]),
  );
  const pairCacheRef = useRef(new Map<string, ArchiveHomePairSelectionPayload | null>());
  const pendingSetLibraryJumpRef = useRef(false);
  // In workspace mode, do not pre-populate the cache with server-rendered data so the
  // useEffect always fires a fresh workspace-scoped fetch on mount.
  const setLibraryCacheRef = useRef(
    initial.scope === "mine"
      ? new Map<string, ArchiveHomeSetLibraryPagePayload>()
      : new Map<string, ArchiveHomeSetLibraryPagePayload>([
          [
            `${initial.initialSetLibrary.artistFilter}::${initial.initialSetLibrary.sort}::${initial.initialSetLibrary.page}::${initial.initialSetLibrary.query}`,
            initial.initialSetLibrary,
          ],
        ]),
  );
  const setTracklistCacheRef = useRef(new Map<string, ArchiveHomeSetTracklistPayload | null>());

  const deferredArtistQuery = useDeferredValue(artistQuery);
  const deferredTaxonomyQuery = useDeferredValue(taxonomyQuery);
  const deferredPairQuery = useDeferredValue(pairQuery);
  const deferredSetQuery = useDeferredValue(setQuery);
  const artistBySlug = useMemo(
    () => new Map(artistCards.map((artistCard) => [artistCard.slug, artistCard])),
    [artistCards],
  );
  const scopedTrackCatalog = artistCards.length === 0 ? [] : atlasPayload.trackCatalog;
  const visibleArtists = useMemo(() => {
    const normalizedQuery = normalizeSearchText(deferredArtistQuery);
    return artistCards.filter((artistCard) =>
      normalizedQuery ? buildSearchBlob(artistCard.name).includes(normalizedQuery) : true,
    );
  }, [artistCards, deferredArtistQuery]);

  const allArtistsSelected =
    selectedArtistSlugs.length > 0 && selectedArtistSlugs.length === artistCards.length;

  useEffect(() => {
    latestSelectedArtistSlugsRef.current = selectedArtistSlugs;
  }, [selectedArtistSlugs]);

  useEffect(() => {
    networkZoomRef.current = networkZoom;
  }, [networkZoom]);

  useEffect(() => {
    if (artistPanePointerInside || !pendingArtistGridResetRef.current) {
      return;
    }

    pendingArtistGridResetRef.current = false;
    const grid = artistGridRef.current;
    if (!grid) {
      return;
    }

    let frame = window.requestAnimationFrame(() => {
      frame = window.requestAnimationFrame(() => {
        grid.scrollTo({
          top: 0,
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "auto"
            : "smooth",
        });
      });
    });

    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [artistPanePointerInside, dockedSelectedArtistSlugs]);

  const orderedArtists = useMemo(() => {
    if (allArtistsSelected) {
      return visibleArtists;
    }
    const docked = visibleArtists.filter((artist) =>
      dockedSelectedArtistSlugs.includes(artist.slug),
    );
    if (!docked.length) {
      return visibleArtists;
    }
    const dockedSet = new Set(docked.map((artist) => artist.slug));
    return [...docked, ...visibleArtists.filter((artist) => !dockedSet.has(artist.slug))];
  }, [allArtistsSelected, dockedSelectedArtistSlugs, visibleArtists]);
  const clearArtistSelectionSlug =
    focusArtistSlug ?? orderedArtists[0]?.slug ?? selectedArtistSlugs[0] ?? null;

  const normalizedTaxonomyThreshold = normalizeThresholdValue(taxonomyThreshold, THRESHOLD_LEVELS);
  const thresholdScopedTaxonomyTracks = useMemo(
    () =>
      scopedTrackCatalog.filter((track) => track.totalAppearances >= normalizedTaxonomyThreshold),
    [normalizedTaxonomyThreshold, scopedTrackCatalog],
  );
  const projectedTaxonomyTracks = useMemo(
    () =>
      thresholdScopedTaxonomyTracks
        .map((track) => projectTrackByConfidence(track, taxonomyConfidence))
        .filter((track): track is ArchiveHomeTrackCatalogItem => Boolean(track)),
    [taxonomyConfidence, thresholdScopedTaxonomyTracks],
  );
  const taxonomyRows = useMemo(
    () =>
      buildTaxonomyRows({
        lens: taxonomyLens,
        query: deferredTaxonomyQuery,
        sort: taxonomySort,
        trackCatalog: projectedTaxonomyTracks,
      }),
    [deferredTaxonomyQuery, projectedTaxonomyTracks, taxonomyLens, taxonomySort],
  );
  const taxonomyFocusStats = useMemo(
    () =>
      buildFocusStats({
        artistCards,
        selectedArtistSlugs,
        trackCatalog: scopedTrackCatalog,
      }),
    [artistCards, scopedTrackCatalog, selectedArtistSlugs],
  );

  const pairRows = useMemo(() => {
    if (!pairPayload) {
      return [];
    }
    return buildPairRows({
      confidence: pairConfidence,
      lens: pairLens,
      minUsage: normalizeThresholdValue(pairThreshold, THRESHOLD_LEVELS),
      pairPayload,
      query: deferredPairQuery,
      sort: pairSort,
    });
  }, [deferredPairQuery, pairConfidence, pairLens, pairPayload, pairSort, pairThreshold]);

  const filteredNetworkEdges = useMemo(() => {
    if (!networkPayload) {
      return [];
    }

    const normalizedSearch = normalizeSearchText(networkSearch);
    return networkPayload.edges.filter((edge) => {
      if (edge.normalizedScore < networkMinScore) {
        return false;
      }
      if (networkSelectedArtistSlugs.length === 1) {
        const target = networkSelectedArtistSlugs[0];
        if (edge.artistASlug !== target && edge.artistBSlug !== target) {
          return false;
        }
      } else if (networkSelectedArtistSlugs.length >= 2) {
        const [left, right] = networkSelectedArtistSlugs;
        const match =
          (edge.artistASlug === left && edge.artistBSlug === right) ||
          (edge.artistASlug === right && edge.artistBSlug === left);
        if (!match) {
          return false;
        }
      }
      if (!normalizedSearch) {
        return true;
      }
      return buildSearchBlob(edge.artistA, edge.artistB).includes(normalizedSearch);
    });
  }, [networkMinScore, networkPayload, networkSearch, networkSelectedArtistSlugs]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const media = window.matchMedia(
      "(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)",
    );
    const sync = () => {
      setNetworkLensEnabled(media.matches);
      if (!media.matches) {
        setNetworkPointer({
          active: false,
          x: 0,
          y: 0,
        });
      }
    };

    sync();

    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", sync);
      return () => media.removeEventListener("change", sync);
    }

    media.addListener(sync);
    return () => media.removeListener(sync);
  }, []);

  // Touch-only: scroll-driven hover + deferred reorder for artist stack
  useEffect(() => {
    if (typeof window === "undefined" || isHoverCapablePointer()) {
      return;
    }

    const grid = artistGridRef.current;
    if (!grid) {
      return;
    }

    const exitStack = () => {
      if (!touchArtistStackEngagedRef.current) {
        return;
      }
      touchArtistStackEngagedRef.current = false;
      setArtistPanePointerInside(false);
      setHoverLatchedArtistSlug(null);
      setDockedSelectedArtistSlugs(latestSelectedArtistSlugsRef.current);
      pendingArtistGridResetRef.current = true;
    };

    const computeTopCard = () => {
      const style = getComputedStyle(grid);
      const cardHeight = parseFloat(style.getPropertyValue("--artist-card-height")) || 160;
      const cardOverlap = parseFloat(style.getPropertyValue("--artist-card-overlap")) || 114;
      const cardStep = cardHeight - cardOverlap;
      // Advance hover 18% of a card-height early so the incoming card is fully
      // visible at the top of the stack before it scrolls out of view.
      const buffer = cardHeight * 0.25;
      const index = Math.floor((grid.scrollTop + buffer) / cardStep);
      const cards = grid.querySelectorAll<HTMLElement>("[data-artist]");
      return cards[index]?.dataset.artist ?? cards[0]?.dataset.artist ?? null;
    };

    const handleGridScroll = () => {
      touchArtistStackEngagedRef.current = true;
      touchArtistDidScrollRef.current = true;
      touchArtistLastScrollTimeRef.current = Date.now();
      pendingTapArtistSlugRef.current = null;
      setArtistPanePointerInside(true);
      setHoverLatchedArtistSlug(computeTopCard());
    };

    let gridTouchMoveStartY = 0;
    const handleGridTouchStart = (e: TouchEvent) => {
      gridTouchMoveStartY = e.touches[0]?.clientY ?? 0;
      const card = (e.target as HTMLElement).closest<HTMLElement>("[data-artist]");
      pendingTapArtistSlugRef.current = card?.dataset.artist ?? null;
    };
    const handleGridTouchMove = (e: TouchEvent) => {
      if (Math.abs((e.touches[0]?.clientY ?? 0) - gridTouchMoveStartY) > 6) {
        pendingTapArtistSlugRef.current = null;
      }
    };

    const handleOutsideClick = (e: Event) => {
      if (grid.contains(e.target as Node)) {
        return;
      }
      exitStack();
    };

    const handlePageScroll = () => exitStack();

    // Set initial hover to the first card
    setHoverLatchedArtistSlug(computeTopCard());

    grid.addEventListener("scroll", handleGridScroll, { passive: true });
    grid.addEventListener("touchstart", handleGridTouchStart, { passive: true });
    grid.addEventListener("touchmove", handleGridTouchMove, { passive: true });
    document.addEventListener("click", handleOutsideClick);
    window.addEventListener("scroll", handlePageScroll, { passive: true });

    return () => {
      grid.removeEventListener("scroll", handleGridScroll);
      grid.removeEventListener("touchstart", handleGridTouchStart);
      grid.removeEventListener("touchmove", handleGridTouchMove);
      document.removeEventListener("click", handleOutsideClick);
      window.removeEventListener("scroll", handlePageScroll);
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const elements = rootRef.current?.querySelectorAll<HTMLElement>(".reveal");
    if (!elements?.length) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
          }
        });
      },
      {
        rootMargin: "0px 0px -40px 0px",
        threshold: 0.1,
      },
    );

    elements.forEach((element) => observer.observe(element));

    return () => {
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const viewport = heroSideViewportRef.current;
    const track = heroSideTrackRef.current;
    if (!viewport || !track) {
      return;
    }

    let raf = 0;
    let lastTs = 0;
    let scrollPos = 0;

    const stop = () => {
      if (raf) {
        window.cancelAnimationFrame(raf);
      }
      raf = 0;
      lastTs = 0;
    };

    const start = () => {
      stop();
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        return;
      }
      if (window.matchMedia("(max-width: 1320px)").matches) {
        return;
      }

      const cycleHeight = track.scrollHeight / 2;
      if (cycleHeight <= viewport.clientHeight + 4) {
        return;
      }

      scrollPos = viewport.scrollTop % cycleHeight;
      viewport.scrollTop = scrollPos;

      const tick = (ts: number) => {
        if (!raf) {
          return;
        }
        if (!lastTs) {
          lastTs = ts;
        }
        const dt = (ts - lastTs) / 1000;
        lastTs = ts;
        scrollPos += 12 * dt;
        if (scrollPos >= cycleHeight) {
          scrollPos -= cycleHeight;
        }
        viewport.scrollTop = scrollPos;
        raf = window.requestAnimationFrame(tick);
      };

      raf = window.requestAnimationFrame(tick);
    };

    const syncHeroRailHeight = () => {
      const visual = heroVisualRef.current;
      const stats = heroStatsRef.current;
      const side = heroSideRef.current;
      if (!visual || !stats || !side) {
        return;
      }
      side.style.removeProperty("height");
      if (window.matchMedia("(max-width: 1320px)").matches) {
        return;
      }
      const height =
        Math.round(
          visual.getBoundingClientRect().height +
            parseFloat(getComputedStyle(stats).marginTop || "0") +
            stats.getBoundingClientRect().height,
        ) || 0;
      if (height > 0 && height < 2200) {
        side.style.height = `${height}px`;
      }
    };

    const fitHeroToViewport = () => {
      const hero = rootRef.current?.querySelector<HTMLElement>(".hero");
      const visual = heroVisualRef.current;
      const kicker = hero?.querySelector(".kicker");
      const marquee = hero?.querySelector(".marquee");
      if (!hero || !visual || !kicker || !marquee) {
        return;
      }
      if (window.matchMedia("(max-width: 1320px)").matches) {
        visual.style.removeProperty("height");
        return;
      }
      const kickerRect = kicker.getBoundingClientRect();
      const marqueeRect = marquee.getBoundingClientRect();
      const visualRect = visual.getBoundingClientRect();
      if (visualRect.height <= 0) {
        return;
      }
      const currentSpan = marqueeRect.bottom - kickerRect.top;
      const desiredSpan = window.innerHeight - kickerRect.top - 2;
      const targetVisualHeight = visualRect.height + (desiredSpan - currentSpan);
      const clamped = clamp(targetVisualHeight, 300, 620);
      visual.style.height = `${Math.round(clamped)}px`;
    };

    const handleResize = () => {
      fitHeroToViewport();
      syncHeroRailHeight();
      start();
    };

    const handleHeroMediaReady = () => {
      window.requestAnimationFrame(() => {
        handleResize();
      });
    };

    const heroImage = heroVisualRef.current?.querySelector("img");

    viewport.addEventListener("mouseenter", stop);
    viewport.addEventListener("mouseleave", start);
    heroImage?.addEventListener("load", handleHeroMediaReady);
    window.addEventListener("resize", handleResize);
    window.addEventListener("load", handleHeroMediaReady);

    fitHeroToViewport();
    syncHeroRailHeight();
    start();
    window.requestAnimationFrame(handleHeroMediaReady);
    if (heroImage?.complete) {
      handleHeroMediaReady();
    }

    return () => {
      stop();
      viewport.removeEventListener("mouseenter", stop);
      viewport.removeEventListener("mouseleave", start);
      heroImage?.removeEventListener("load", handleHeroMediaReady);
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("load", handleHeroMediaReady);
    };
  }, [initial.hero.railSets.length]);

  useEffect(() => {
    const selectionKey = `${scope}::${compareMode}::${selectedArtistSlugs.join(",")}`;
    const cached = atlasCacheRef.current.get(selectionKey);

    if (cached) {
      setAtlasPayload(cached);
      return;
    }

    const controller = new AbortController();
    const searchParams = new URLSearchParams({
      mode: compareMode,
    });

    if (scope === "mine") {
      searchParams.set("scope", "mine");
    }

    if (
      selectedArtistSlugs.length > 0 &&
      selectedArtistSlugs.length === artistCards.length
    ) {
      searchParams.append("artist", "__ALL__");
    } else {
      for (const artistSlug of selectedArtistSlugs) {
        searchParams.append("artist", artistSlug);
      }
    }

    void fetch(`/api/archive/home/atlas?${searchParams.toString()}`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Atlas request failed with ${response.status}`);
        }
        return (await response.json()) as ArchiveHomeAtlasSelectionPayload;
      })
      .then((payload) => {
        atlasCacheRef.current.set(selectionKey, payload);
        setAtlasPayload(payload);
      })
      .catch((error) => {
        if (controller.signal.aborted) {
          return;
        }
        console.error("[archive-home] atlas selection request failed", error);
      });

    return () => {
      controller.abort();
    };
  }, [artistCards.length, compareMode, scope, selectedArtistSlugs]);

  useEffect(() => {
    if (networkSelectedArtistSlugs.length !== 2) {
      setPairPayload(null);
      return;
    }

    const key = buildPairLookupKey(
      networkSelectedArtistSlugs[0]!,
      networkSelectedArtistSlugs[1]!,
    );
    const cached = pairCacheRef.current.get(key);
    if (cached !== undefined) {
      setPairPayload(cached);
      return;
    }

    const controller = new AbortController();
    const searchParams = new URLSearchParams({
      a: networkSelectedArtistSlugs[0]!,
      b: networkSelectedArtistSlugs[1]!,
    });

    if (scope === "mine") {
      searchParams.set("scope", "mine");
    }

    void fetch(`/api/archive/home/pair?${searchParams.toString()}`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (response.status === 404) {
          return null;
        }
        if (!response.ok) {
          throw new Error(`Pair request failed with ${response.status}`);
        }
        return (await response.json()) as ArchiveHomePairSelectionPayload;
      })
      .then((payload) => {
        pairCacheRef.current.set(key, payload);
        setPairPayload(payload);
      })
      .catch((error) => {
        if (controller.signal.aborted) {
          return;
        }
        console.error("[archive-home] pair selection request failed", error);
      });

    return () => {
      controller.abort();
    };
  }, [networkSelectedArtistSlugs, scope]);

  useEffect(() => {
    const updateLayout = () => {
      setNetworkLayoutVersion((current) => current + 1);
    };

    updateLayout();
    window.addEventListener("resize", updateLayout);
    return () => {
      window.removeEventListener("resize", updateLayout);
    };
  }, []);

  useEffect(() => {
    const requestKey = `${scope}::${setArtistFilter}::${setSort}::${setPage}::${deferredSetQuery}`;
    const cached = setLibraryCacheRef.current.get(requestKey);

    if (cached) {
      setSetLibrary(cached);
      return;
    }

    const controller = new AbortController();
    const searchParams = new URLSearchParams({
      artist: setArtistFilter,
      page: String(setPage),
      query: deferredSetQuery,
      sort: setSort,
    });

    if (scope === "mine") {
      searchParams.set("scope", "mine");
    }

    void fetch(`/api/archive/home/sets?${searchParams.toString()}`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Set library request failed with ${response.status}`);
        }
        return (await response.json()) as ArchiveHomeSetLibraryPagePayload;
      })
      .then((payload) => {
        setLibraryCacheRef.current.set(requestKey, payload);
        setSetLibrary(payload);
      })
      .catch((error) => {
        if (controller.signal.aborted) {
          return;
        }
        console.error("[archive-home] set library request failed", error);
      });

    return () => {
      controller.abort();
    };
  }, [deferredSetQuery, scope, setArtistFilter, setPage, setSort]);

  const updateTrackCardState = ({
    openSources,
    openSpotify,
    trackKey,
  }: {
    openSources: boolean;
    openSpotify: boolean;
    trackKey: string;
  }) => {
    setTrackCardStates((current) => ({
      ...current,
      [trackKey]: {
        sourcesOpen: openSources,
        spotifyOpen: openSpotify,
      },
    }));
  };

  const toggleTrackSources = (trackKey: string) => (event: MouseEvent<HTMLElement>) => {
    const card = event.currentTarget.closest<HTMLElement>(".track-card");
    const currentlyOpen = trackCardStates[trackKey]?.sourcesOpen ?? false;
    if (!currentlyOpen) {
      const style = buildTrackCardStyle(card, "source");
      setTrackCardStyles((current) => ({ ...current, [trackKey]: style }));
    }
    updateTrackCardState({
      openSources: !currentlyOpen,
      openSpotify: false,
      trackKey,
    });
  };

  const toggleTrackSpotify = (trackKey: string) => (event: MouseEvent<HTMLButtonElement>) => {
    const card = event.currentTarget.closest<HTMLElement>(".track-card");
    const currentlyOpen = trackCardStates[trackKey]?.spotifyOpen ?? false;
    if (!currentlyOpen) {
      const style = buildTrackCardStyle(card, "embed");
      setTrackCardStyles((current) => ({ ...current, [trackKey]: style }));
    }
    updateTrackCardState({
      openSources: false,
      openSpotify: !currentlyOpen,
      trackKey,
    });
  };

  const toggleSetTracklist = (slug: string) => {
    setExpandedSets((current) =>
      current.includes(slug) ? current.filter((key) => key !== slug) : [...current, slug],
    );

    if (setTracklistCacheRef.current.has(slug)) {
      const cached = setTracklistCacheRef.current.get(slug);
      if (cached) {
        setSetTracklists((current) => ({
          ...current,
          [slug]: cached.tracks,
        }));
      }
      return;
    }

    setTracklistErrors((current) => {
      const next = { ...current };
      delete next[slug];
      return next;
    });
    setLoadingTracklists((current) => ({ ...current, [slug]: true }));
    void fetch(`/api/archive/home/sets/${encodeURIComponent(slug)}/tracklist`)
      .then(async (response) => {
        if (response.status === 404) {
          return null;
        }
        if (!response.ok) {
          throw new Error(`Tracklist request failed with ${response.status}`);
        }
        return (await response.json()) as ArchiveHomeSetTracklistPayload;
      })
      .then((payload) => {
        setTracklistCacheRef.current.set(slug, payload);
        setSetTracklists((current) => ({
          ...current,
          [slug]: payload?.tracks ?? [],
        }));
      })
      .catch((error) => {
        console.error("[archive-home] set tracklist request failed", error);
        setTracklistErrors((current) => ({
          ...current,
          [slug]: "Unable to load tracklist right now.",
        }));
      })
      .finally(() => {
        setLoadingTracklists((current) => ({
          ...current,
          [slug]: false,
        }));
      });
  };

  const jumpToSetLibrary = () => {
    document.getElementById("sets")?.scrollIntoView({
      behavior: "auto",
      block: "start",
    });
  };

  useEffect(() => {
    if (!pendingSetLibraryJumpRef.current) {
      return;
    }

    pendingSetLibraryJumpRef.current = false;
    jumpToSetLibrary();
  }, [setLibrary.page]);

  const taxonomyMaxCount = taxonomyRows.length
    ? Math.max(...taxonomyRows.map((row) => row.count))
    : 1;
  const taxonomyTotalPages = Math.max(1, Math.ceil(taxonomyRows.length / PAGE.taxonomy));
  const safeTaxonomyPage = clamp(taxonomyPage, 0, Math.max(0, taxonomyTotalPages - 1));
  const taxonomyPageRows =
    taxonomyLens === "tracks"
      ? taxonomyRows
      : taxonomyRows.slice(
          safeTaxonomyPage * PAGE.taxonomy,
          safeTaxonomyPage * PAGE.taxonomy + PAGE.taxonomy,
        );

  const pairMaxCount = pairRows.length ? Math.max(...pairRows.map((row) => row.count)) : 1;
  const pairTotalPages = Math.max(1, Math.ceil(pairRows.length / PAGE.pairRows));
  const safePairPage = clamp(pairPage, 0, Math.max(0, pairTotalPages - 1));
  const pairPageRows =
    pairLens === "tracks"
      ? pairRows
      : pairRows.slice(safePairPage * PAGE.pairRows, safePairPage * PAGE.pairRows + PAGE.pairRows);

  const handleArtistFocus = (artistSlug: string, event: MouseEvent<HTMLElement>) => {
    if (!isHoverCapablePointer()) {
      // Only process tap if finger movement didn't cancel it
      if (pendingTapArtistSlugRef.current !== artistSlug) {
        return;
      }
      pendingTapArtistSlugRef.current = null;
      // First tap → hover this card; second tap on hovered card → select
      if (hoverLatchedArtistSlug !== artistSlug) {
        touchArtistStackEngagedRef.current = true;
        setArtistPanePointerInside(true);
        setHoverLatchedArtistSlug(artistSlug);
        return;
      }
      // Tap on already-hovered card: select
      setFocusArtistSlug(artistSlug);
      setSelectedArtistSlugs((current) => {
        const next = [artistSlug];
        latestSelectedArtistSlugsRef.current = next;
        if (!artistPanePointerInside) {
          setDockedSelectedArtistSlugs(next);
        }
        return next;
      });
      setTaxonomyPage(0);
      setTaxonomyActiveName(null);
      return;
    }
    const additive = event.shiftKey || event.metaKey || event.ctrlKey;
    setHoverLatchedArtistSlug(artistSlug);
    setFocusArtistSlug(artistSlug);
    setSelectedArtistSlugs((current) => {
      const next = additive ? Array.from(new Set([...current, artistSlug])) : [artistSlug];
      latestSelectedArtistSlugsRef.current = next;
      if (!artistPanePointerInside) {
        setDockedSelectedArtistSlugs(next);
      }
      return next;
    });
    setTaxonomyPage(0);
    setTaxonomyActiveName(null);
  };

  const toggleCompareArtist = (artistSlug: string) => {
    setSelectedArtistSlugs((current) => {
      const exists = current.includes(artistSlug);
      let next = exists ? current.filter((slug) => slug !== artistSlug) : [...current, artistSlug];
      if (!next.length) {
        next = [artistSlug];
      }
      latestSelectedArtistSlugsRef.current = next;
      if (!artistPanePointerInside) {
        setDockedSelectedArtistSlugs(next);
      }
      return next;
    });
    setTaxonomyPage(0);
    setTaxonomyActiveName(null);
  };

  const networkPositions = useMemo(() => {
    if (!networkPayload || !networkWrapRef.current) {
      return { height: 560, positions: new Map<string, { r: number; x: number; y: number }>(), width: 860 };
    }
    const width =
      Math.max(860, networkWrapRef.current.clientWidth || 860) +
      networkLayoutVersion * 0;
    const height = 560;
    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(width, height) * 0.38;
    const positions = new Map<string, { r: number; x: number; y: number }>();

    networkPayload.artists
      .slice()
      .sort((left, right) => left.name.localeCompare(right.name))
      .forEach((artist, index) => {
        const angle =
          (Math.PI * 2 * index) / Math.max(1, networkPayload.artists.length) - Math.PI / 2;
        positions.set(artist.slug, {
          r: NETWORK_NODE_BASE_RADIUS,
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
        });
      });

    return { height, positions, width };
  }, [networkLayoutVersion, networkPayload]);

  // Network map pinch-to-zoom + drag-to-pan (touch only, placed after networkPositions)
  useEffect(() => {
    const wrap = networkWrapRef.current;
    if (!wrap) {
      return;
    }

    const getTouchPos = (t: Touch) => ({ id: t.identifier, x: t.clientX, y: t.clientY });
    const touchDist = (a: { x: number; y: number }, b: { x: number; y: number }) =>
      Math.hypot(b.x - a.x, b.y - a.y);

    const onTouchStart = (e: TouchEvent) => {
      const touches = Array.from(e.touches).map(getTouchPos);
      const current = networkZoomRef.current;

      if (touches.length >= 2) {
        const t0 = touches[0]!;
        const t1 = touches[1]!;
        const d = touchDist(t0, t1);
        const mx = (t0.x + t1.x) / 2;
        const my = (t0.y + t1.y) / 2;
        const rect = wrap.getBoundingClientRect();
        const svgW = networkPositions.width / current.scale;
        const svgH = networkPositions.height / current.scale;
        const originX = current.panX + ((mx - rect.left) / rect.width) * svgW;
        const originY = current.panY + ((my - rect.top) / rect.height) * svgH;
        networkTouchRef.current = {
          touches,
          startScale: current.scale,
          startPanX: current.panX,
          startPanY: current.panY,
          startDist: d,
          zoomOriginSvgX: originX,
          zoomOriginSvgY: originY,
        };
      } else if (touches.length === 1) {
        networkTouchRef.current = {
          touches,
          startScale: current.scale,
          startPanX: current.panX,
          startPanY: current.panY,
          startDist: 0,
          zoomOriginSvgX: 0,
          zoomOriginSvgY: 0,
        };
      }
    };

    const onTouchMove = (e: TouchEvent) => {
      if (!networkTouchRef.current) {
        return;
      }
      e.preventDefault();

      const { startScale, startPanX, startPanY, startDist, zoomOriginSvgX, zoomOriginSvgY } =
        networkTouchRef.current;
      const activeTouches = Array.from(e.touches).map(getTouchPos);

      if (activeTouches.length >= 2) {
        const t0 = activeTouches[0]!;
        const t1 = activeTouches[1]!;
        const d = touchDist(t0, t1);
        const newScale = clamp(startScale * (d / startDist), 1, 8);
        const mx = (t0.x + t1.x) / 2;
        const my = (t0.y + t1.y) / 2;
        const rect = wrap.getBoundingClientRect();
        const svgW = networkPositions.width / newScale;
        const svgH = networkPositions.height / newScale;
        const newPanX = clamp(
          zoomOriginSvgX - ((mx - rect.left) / rect.width) * svgW,
          0,
          networkPositions.width - svgW,
        );
        const newPanY = clamp(
          zoomOriginSvgY - ((my - rect.top) / rect.height) * svgH,
          0,
          networkPositions.height - svgH,
        );
        setNetworkZoom({ scale: newScale, panX: newPanX, panY: newPanY });
      } else if (activeTouches.length === 1) {
        const t0 = activeTouches[0]!;
        const init = networkTouchRef.current.touches[0];
        if (!init) {
          return;
        }
        const rect = wrap.getBoundingClientRect();
        const svgW = networkPositions.width / startScale;
        const svgH = networkPositions.height / startScale;
        const newPanX = clamp(
          startPanX - ((t0.x - init.x) / rect.width) * svgW,
          0,
          networkPositions.width - svgW,
        );
        const newPanY = clamp(
          startPanY - ((t0.y - init.y) / rect.height) * svgH,
          0,
          networkPositions.height - svgH,
        );
        setNetworkZoom((prev) => ({ ...prev, panX: newPanX, panY: newPanY }));
      }
    };

    const onTouchEnd = (e: TouchEvent) => {
      if (e.touches.length === 0) {
        networkTouchRef.current = null;
      } else if (e.touches.length === 1 && networkTouchRef.current) {
        // Transition from pinch to single-finger pan — re-anchor reference point
        const current = networkZoomRef.current;
        const t = e.touches[0]!;
        networkTouchRef.current = {
          touches: [{ id: t.identifier, x: t.clientX, y: t.clientY }],
          startScale: current.scale,
          startPanX: current.panX,
          startPanY: current.panY,
          startDist: 0,
          zoomOriginSvgX: 0,
          zoomOriginSvgY: 0,
        };
      }
    };

    wrap.addEventListener("touchstart", onTouchStart, { passive: true });
    wrap.addEventListener("touchmove", onTouchMove, { passive: false });
    wrap.addEventListener("touchend", onTouchEnd, { passive: true });

    return () => {
      wrap.removeEventListener("touchstart", onTouchStart);
      wrap.removeEventListener("touchmove", onTouchMove);
      wrap.removeEventListener("touchend", onTouchEnd);
    };
  }, [networkPositions]);

  const networkArtists = useMemo(
    () =>
      networkPayload
        ? networkPayload.artists.slice().sort((left, right) => left.name.localeCompare(right.name))
        : [],
    [networkPayload],
  );

  const networkNodeVisuals = useMemo(() => {
    const centerX = networkPositions.width / 2;
    const centerY = networkPositions.height / 2;
    const lensActive = networkLensEnabled && networkPointer.active;

    return networkArtists
      .map((artist) => {
        const position = networkPositions.positions.get(artist.slug);
        if (!position) {
          return null;
        }

        const selected = networkSelectedArtistSlugs.includes(artist.slug);
        let visualWeight = 0;

        if (lensActive) {
          const distance = Math.hypot(position.x - networkPointer.x, position.y - networkPointer.y);
          const proximity = clamp(1 - distance / NETWORK_LENS_RADIUS, 0, 1);
          visualWeight = proximity > 0 ? Math.pow(proximity, NETWORK_LENS_FALLOFF) : 0;
          if (selected) {
            visualWeight = Math.max(visualWeight, NETWORK_SELECTED_LENS_FLOOR);
          }
        }

        const directionXRaw = position.x - centerX;
        const directionYRaw = position.y - centerY;
        const directionLength = Math.hypot(directionXRaw, directionYRaw) || 1;
        const directionX = directionXRaw / directionLength;
        const directionY = directionYRaw / directionLength;
        const circleRadius = position.r * (1 + visualWeight * (NETWORK_NODE_MAX_SCALE - 1));
        const fontSize = NETWORK_LABEL_BASE_SIZE + visualWeight * NETWORK_LABEL_SIZE_RANGE;
        const labelOffset = circleRadius + NETWORK_LABEL_OUTSET + visualWeight * NETWORK_LABEL_OUTSET_RANGE;
        const textAnchor: "start" | "end" = directionX >= 0 ? "start" : "end";
        const estimatedLabelWidth = artist.name.length * fontSize * 0.62;
        let labelX = position.x + directionX * labelOffset;
        let labelY = position.y + directionY * labelOffset;

        if (textAnchor === "start") {
          labelX = clamp(labelX, 8, networkPositions.width - estimatedLabelWidth - 8);
        } else {
          labelX = clamp(labelX, estimatedLabelWidth + 8, networkPositions.width - 8);
        }

        labelY = clamp(labelY, fontSize, networkPositions.height - fontSize);

        return {
          artist,
          circleRadius,
          labelFontSize: fontSize,
          labelHaloWidth: visualWeight * NETWORK_LABEL_HALO_RANGE,
          labelX,
          labelY,
          position,
          renderWeight: visualWeight,
          selected,
          textAnchor,
          visualWeight,
        };
      })
      .filter((value): value is NonNullable<typeof value> => value !== null)
      .sort((left, right) => {
        if (left.renderWeight !== right.renderWeight) {
          return left.renderWeight - right.renderWeight;
        }
        return Number(left.selected) - Number(right.selected);
      });
  }, [
    networkArtists,
    networkLensEnabled,
    networkPointer,
    networkPositions,
    networkSelectedArtistSlugs,
  ]);

  const toggleNetworkArtistSelection = (artistSlug: string) => {
    setPairPage(0);
    setPairActiveName(null);
    setNetworkSelectedArtistSlugs((current) => {
      if (current.includes(artistSlug)) {
        return current.filter((slug) => slug !== artistSlug);
      }
      if (current.length >= 2) {
        return [artistSlug];
      }
      return [...current, artistSlug];
    });
  };

  const updateNetworkPointer = ({
    clientX,
    clientY,
    currentTarget,
  }: {
    clientX: number;
    clientY: number;
    currentTarget: SVGSVGElement;
  }) => {
    if (!networkLensEnabled) {
      return;
    }

    const rect = currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return;
    }

    const nextX = ((clientX - rect.left) / rect.width) * networkPositions.width;
    const nextY = ((clientY - rect.top) / rect.height) * networkPositions.height;

    setNetworkPointer((current) => {
      if (
        current.active &&
        Math.abs(current.x - nextX) < 0.5 &&
        Math.abs(current.y - nextY) < 0.5
      ) {
        return current;
      }

      return {
        active: true,
        x: nextX,
        y: nextY,
      };
    });
  };

  return (
    <div ref={rootRef}>
      <style dangerouslySetInnerHTML={{ __html: ARCHIVE_HOME_EXPLORER_CSS }} />
      <ArchiveScrollRoot />
      <div className="shell archive-home-native">
        <ArchiveHeader
          navLinks={[
            { label: "Artist Atlas", href: "#artists" },
            { label: "Artist Network", href: "#network" },
            { label: "Set Library", href: "#sets" },
          ]}
        />

        <section className="hero reveal" id="top">
          <div className="section-inner">
            <span className="kicker">Outcome-Driven Music Intelligence</span>
            <div className="hero-grid">
              <div className="hero-main">
                <div className="hero-visual" id="heroVisual" ref={heroVisualRef}>
                  {initial.hero.imageUrl ? (
                    <img alt={initial.hero.imageAlt} loading="eager" src={initial.hero.imageUrl} />
                  ) : null}
                  <h1 className="hero-title-overlay">
                    <span>SET</span>
                    <span>SIGNAL</span>
                  </h1>
                </div>
                <div className="hero-stats" id="heroStats" ref={heroStatsRef}>
                  <article className="stat-card accent">
                    <p className="stat-label">Artists mapped</p>
                    <p className="stat-value">{fmt(initial.globalStats.totalArtists)}</p>
                  </article>
                  <article className="stat-card">
                    <p className="stat-label">Sets analyzed</p>
                    <p className="stat-value">{fmt(initial.globalStats.totalSets)}</p>
                  </article>
                  <article className="stat-card">
                    <p className="stat-label">Unique tracks</p>
                    <p className="stat-value">{fmt(initial.globalStats.totalUniqueTracks)}</p>
                  </article>
                  <article className="stat-card">
                    <p className="stat-label">Track appearances</p>
                    <p className="stat-value">{fmt(initial.globalStats.totalAppearances)}</p>
                  </article>
                </div>
              </div>
              <div className="hero-side" id="heroSide" ref={heroSideRef}>
                {initial.hero.railSets.length ? (
                  <div className="hero-side-viewport" id="heroSideViewport" ref={heroSideViewportRef}>
                    <div className="hero-side-track" id="heroSideTrack" ref={heroSideTrackRef}>
                      {[...initial.hero.railSets, ...initial.hero.railSets].map((setItem, index) => (
                        <a
                          className="hero-card"
                          href={buildSetHref({ slug: setItem.slug })}
                          key={`${setItem.id}-${index}`}
                          title="Open set page"
                        >
                          <img
                            alt={setItem.title}
                            loading="lazy"
                            src={
                              setItem.thumbnailUrl ??
                              fallbackMedia(`hero:${setItem.artistName}:${setItem.title}:${index}`)
                            }
                          />
                          <div className="hero-card-meta">
                            <p className="hero-card-artist">{setItem.artistName}</p>
                            <p className="hero-card-title">{setItem.title}</p>
                            <p className="hero-card-match">{Math.round(setItem.recognitionRate ?? 0)}% match</p>
                          </div>
                        </a>
                      ))}
                    </div>
                  </div>
                ) : (
                  <article className="hero-card">
                    <span className="hero-empty">No media preview yet</span>
                  </article>
                )}
              </div>
            </div>
            <div className="marquee">
              <div className="marquee-track" id="heroTicker">
                {[...initial.hero.tickerItems, ...initial.hero.tickerItems, ...initial.hero.tickerItems].map(
                  (item, index) => (
                    <span key={`${item}-${index}`}>{item}</span>
                  ),
                )}
              </div>
            </div>
          </div>
        </section>

        <section className="section reveal" id="artists" style={{ position: "relative" }}>
          <div style={{ position: "absolute", top: 18, right: 24, zIndex: 500 }}>
            <InlineSubmitButton mode="scan-artist" />
          </div>
          <div className="section-inner">
            <div className="section-head">
              <h2>ARTIST ATLAS</h2>
              <p>Select artists to compare and drill into the right-side taxonomy atlas to investigate genres, labels, artists, and tracks.</p>
            </div>

            <div className="atlas-layout">
              <div className="artist-stack">
                <div className="control">
                  <label htmlFor="artistSearch">Search Artists</label>
                  <span className="mobile-search-shell mobile-search-shell-compact">
                    <input
                      id="artistSearch"
                      onChange={(event) => setArtistQuery(event.target.value)}
                      placeholder="find artist cards"
                      type="text"
                      value={artistQuery}
                    />
                  </span>
                </div>
                <div
                  className={joinClasses(
                    "artist-grid",
                    dockedSelectedArtistSlugs.length > 0 && !allArtistsSelected && "selected-dock",
                  )}
                  id="artistGrid"
                  ref={artistGridRef}
                  onTouchStart={(e) => {
                    touchArtistScrollStartYRef.current = e.touches[0]?.clientY ?? 0;
                    touchArtistDidScrollRef.current = false;
                  }}
                  onPointerEnter={(event) => {
                    if (!isHoverCapablePointer()) {
                      return;
                    }
                    setArtistPanePointerInside(true);
                    event.currentTarget.scrollTo({ top: 0, behavior: "auto" });
                  }}
                  onPointerLeave={() => {
                    if (!isHoverCapablePointer()) {
                      return;
                    }
                    setArtistPanePointerInside(false);
                    setHoverLatchedArtistSlug(null);
                    setDockedSelectedArtistSlugs(latestSelectedArtistSlugsRef.current);
                    pendingArtistGridResetRef.current = true;
                  }}
                >
                  {orderedArtists.length ? (
                    orderedArtists.map((artistCard, index) => {
                      const focused = !allArtistsSelected && artistCard.slug === focusArtistSlug;
                      const selected = selectedArtistSlugs.includes(artistCard.slug);
                      const compareLabel = allArtistsSelected
                        ? "In Scope"
                        : selected
                          ? "In Compare"
                          : "Add to Compare";

                      return (
                        <article
                          className={joinClasses(
                            "artist-card",
                            focused && "focus",
                            selected && "selected",
                            hoverLatchedArtistSlug === artistCard.slug && "hover-latched",
                          )}
                          data-action="focus-artist"
                          data-artist={artistCard.slug}
                          key={artistCard.id}
                          onClick={(event) => handleArtistFocus(artistCard.slug, event)}
                          style={{ zIndex: orderedArtists.length - index }}
                        >
                          {artistCard.imageUrl ? (
                            <img alt={artistCard.name} loading="lazy" src={artistCard.imageUrl} />
                          ) : null}
                          <div className="artist-detail">
                            <div className="artist-meta-row">
                              <div className="card-actions atlas-card-actions">
                                <span className="card-actions-main">
                                  <button
                                    className={joinClasses("chip-btn", selected && "active")}
                                    data-action="toggle-compare-artist"
                                    onClick={(event) => {
                                      event.preventDefault();
                                      event.stopPropagation();
                                      toggleCompareArtist(artistCard.slug);
                                    }}
                                    type="button"
                                  >
                                    {compareLabel}
                                  </button>
                                  <a className="chip-btn" href={buildArtistHref({ slug: artistCard.slug })}>
                                    Artist Page
                                  </a>
                                </span>
                              </div>
                            </div>
                            <h3>{artistCard.name}</h3>
                          </div>
                        </article>
                      );
                    })
                  ) : (
                    <div className="empty">No artist cards match this search.</div>
                  )}
                </div>
              </div>

              <aside className="atlas-panel">
                <div className="focus-header" id="focusHeader">
                  <div
                    className={joinClasses(
                      "focus-names",
                      allArtistsSelected ? "single" : selectedArtistSlugs.length > 1 ? "multi" : "single",
                      selectedArtistSlugs.length > 2 && "compact",
                    )}
                  >
                    {allArtistsSelected ? (
                      <span className="focus-name">All Artists</span>
                    ) : selectedArtistSlugs.length > 1 ? (
                      selectedArtistSlugs.map((artistSlug, index) => {
                        const artistCard = artistBySlug.get(artistSlug);
                        if (!artistCard) {
                          return null;
                        }
                        return (
                          <span key={artistSlug}>
                            <span className="focus-name">
                              <span className="focus-label">{artistCard.name}</span>
                              <button
                                className="focus-remove"
                                onClick={() => toggleCompareArtist(artistSlug)}
                                type="button"
                              >
                                x
                              </button>
                            </span>
                            {index < selectedArtistSlugs.length - 1 ? (
                              <span className="focus-sep">&amp;</span>
                            ) : null}
                          </span>
                        );
                      })
                    ) : (
                      <span className="focus-name">
                        {artistBySlug.get(selectedArtistSlugs[0] ?? "")?.name ?? "No artist selected"}
                      </span>
                    )}
                  </div>
                  <div className="focus-toolbar">
                    <p className="focus-summary">
                      {allArtistsSelected
                        ? `${compareMode === "intersection" ? "Intersection" : "Union"} scope across all artists.`
                        : selectedArtistSlugs.length > 1
                          ? `${fmt(selectedArtistSlugs.length)} artists selected. ${compareMode === "intersection" ? "Intersection" : "Union"} scope.`
                          : "Single artist focus. Add more artists to compare overlap."}
                    </p>
                    <div className="focus-mode">
                      {selectedArtistSlugs.length > 1 ? (
                        <>
                          <button
                            className={joinClasses("chip-btn", compareMode === "union" && "active")}
                            onClick={() => setCompareMode("union")}
                            type="button"
                          >
                            Union
                          </button>
                          <button
                            className={joinClasses("chip-btn", compareMode === "intersection" && "active")}
                            onClick={() => setCompareMode("intersection")}
                            type="button"
                          >
                            Intersection
                          </button>
                        </>
                      ) : null}
                      <button
                        className={joinClasses("chip-btn", allArtistsSelected && "active")}
                        onClick={() => {
                          const allSlugs = artistCards.map((artistCard) => artistCard.slug);
                          latestSelectedArtistSlugsRef.current = allSlugs;
                          setSelectedArtistSlugs(allSlugs);
                          setDockedSelectedArtistSlugs(allSlugs);
                          setFocusArtistSlug(null);
                          setTaxonomyActiveName(null);
                          setTaxonomyPage(0);
                        }}
                        type="button"
                      >
                        Select All
                      </button>
                      {selectedArtistSlugs.length > 1 ? (
                        <button
                          className="chip-btn"
                          onClick={() => {
                            if (!clearArtistSelectionSlug) {
                              return;
                            }
                            latestSelectedArtistSlugsRef.current = [clearArtistSelectionSlug];
                            setFocusArtistSlug(clearArtistSelectionSlug);
                            setSelectedArtistSlugs([clearArtistSelectionSlug]);
                            setDockedSelectedArtistSlugs([clearArtistSelectionSlug]);
                            setTaxonomyActiveName(null);
                            setTaxonomyPage(0);
                          }}
                          type="button"
                        >
                          Clear
                        </button>
                      ) : null}
                    </div>
                  </div>
                  <div className="focus-stats">
                    <article className="focus-tile">
                      <p>Sets</p>
                      <h4>{fmt(taxonomyFocusStats.sets)}</h4>
                    </article>
                    <article className="focus-tile">
                      <p>Unique Tracks</p>
                      <h4>{fmt(taxonomyFocusStats.uniqueTracks)}</h4>
                    </article>
                    <article className="focus-tile">
                      <p>Appearances</p>
                      <h4>{fmt(taxonomyFocusStats.appearances)}</h4>
                    </article>
                    <article className="focus-tile">
                      <p>Artists</p>
                      <h4>{fmt(taxonomyFocusStats.artists)}</h4>
                    </article>
                  </div>
                </div>

                <div className="taxonomy-workbench">
                  <ArchiveTaxonomyPanel
                    className="taxonomy-panel"
                    confidenceContainerId="taxonomyTrackConfFilters"
                    confidenceFilters={CONF_FILTER_LEVELS.map((filter) => {
                      const count =
                        filter === "all"
                          ? thresholdScopedTaxonomyTracks.length
                          : thresholdScopedTaxonomyTracks.filter(
                              (track) => track.confidenceCounts[filter] > 0,
                            ).length;

                      return {
                        active: taxonomyConfidence === filter,
                        id: filter,
                        label: filter === "all" ? `All (${fmt(count)})` : filter,
                        onSelect: () => {
                          setTaxonomyConfidence(filter);
                          setTaxonomyPage(0);
                          setTaxonomyActiveName(null);
                        },
                      };
                    })}
                    lensOptions={[
                      { active: taxonomyLens === "genres", id: "genres", label: "Genres" },
                      { active: taxonomyLens === "labels", id: "labels", label: "Labels" },
                      { active: taxonomyLens === "track-artists", id: "track-artists", label: "Artists" },
                      { active: taxonomyLens === "tracks", id: "tracks", label: "Tracks" },
                    ]}
                    lensTabsId="taxonomyTabs"
                    onLensChange={(lensId) => {
                      setTaxonomyLens(lensId as ArchiveHomeTaxonomyLens);
                      setTaxonomyActiveName(null);
                      setTaxonomyPage(0);
                    }}
                    pager={
                      <div className="pager" id="taxonomyPager">
                        {taxonomyLens !== "tracks" ? (
                          <>
                            <button
                              disabled={safeTaxonomyPage <= 0}
                              onClick={() => setTaxonomyPage((current) => current - 1)}
                              type="button"
                            >
                              Prev
                            </button>
                            <span className="info">
                              Page {safeTaxonomyPage + 1} / {taxonomyTotalPages}
                            </span>
                            <button
                              disabled={safeTaxonomyPage >= taxonomyTotalPages - 1}
                              onClick={() => setTaxonomyPage((current) => current + 1)}
                              type="button"
                            >
                              Next
                            </button>
                          </>
                        ) : null}
                      </div>
                    }
                    rowsId="taxonomyRows"
                    search={{
                      id: "taxonomySearch",
                      onChange: (value) => {
                        setTaxonomyQuery(value);
                        setTaxonomyPage(0);
                      },
                      placeholder: "search",
                      value: taxonomyQuery,
                    }}
                    sort={{
                      id: "taxonomySort",
                      onChange: (value) => setTaxonomySort(value === "alpha" ? "alpha" : "count"),
                      options: [
                        { label: "HIGHEST USAGE", value: "count" },
                        { label: "ALPHABETICAL", value: "alpha" },
                      ],
                      value: taxonomySort,
                    }}
                    threshold={{
                      canDecrease: taxonomyThreshold !== THRESHOLD_LEVELS[0],
                      canIncrease: taxonomyThreshold !== THRESHOLD_LEVELS[THRESHOLD_LEVELS.length - 1],
                      containerId: "taxonomyThresholds",
                      onDecrease: () =>
                        setTaxonomyThreshold((current) =>
                          stepThresholdValue(current, THRESHOLD_LEVELS, -1),
                        ),
                      onIncrease: () =>
                        setTaxonomyThreshold((current) =>
                          stepThresholdValue(current, THRESHOLD_LEVELS, 1),
                        ),
                      valueLabel: `${fmt(taxonomyThreshold)}+ SETS`,
                    }}
                    title="Taxonomy Atlas"
                  >
                      {taxonomyLens === "tracks" ? (
                        projectedTaxonomyTracks.length ? (
                          <div className="inline-evidence">
                            <p className="inline-head">
                              Tracks | {fmt(projectedTaxonomyTracks.length)} matching tracks
                            </p>
                            <div className="evidence-grid">
                              {projectedTaxonomyTracks.map((track) => {
                                const sourceGroups = buildTrackCardSourceGroups(track);
                                const sourceDjs = sourceGroups.length;
                                const sourceSets = sourceGroups.reduce((total, group) => total + group.links.length, 0);
                                return (
                                  <ArchiveEvidenceTrackCard
                                    dataTrackKey={track.trackKey}
                                    key={track.trackKey}
                                    openState={
                                      trackCardStates[track.trackKey] ?? {
                                        sourcesOpen: false,
                                        spotifyOpen: false,
                                      }
                                    }
                                    onToggleSources={toggleTrackSources(track.trackKey)}
                                    onToggleSpotify={toggleTrackSpotify(track.trackKey)}
                                    sourceGroups={sourceGroups}
                                    sourceLabel={`Sets (${fmt(sourceDjs)} DJs, ${fmt(sourceSets)} Sets)`}
                                    spotifyTrackId={extractSpotifyTrackId(track.spotifyUrl)}
                                    style={trackCardStyles[track.trackKey] ?? null}
                                    title={track.title}
                                    titlePrefix={`${track.artist} - `}
                                    confidence={primaryConfidenceFromCounts(track.confidenceCounts)}
                                    albumArt={track.albumArt}
                                  />
                                );
                              })}
                            </div>
                          </div>
                        ) : (
                          <div className="empty">No tracks match current scope, query, and confidence filter.</div>
                        )
                      ) : taxonomyPageRows.length ? (
                        taxonomyPageRows.map((row) => {
                          const active = row.id === taxonomyActiveName;
                          const widthPct = taxonomyMaxCount ? (row.count / taxonomyMaxCount) * 100 : 0;
                          return (
                            <article className={joinClasses("quant-row", active && "active")} key={row.id}>
                              <button
                                className="row-hit"
                                onClick={() => {
                                  setTaxonomyActiveName((current) => (current === row.id ? null : row.id));
                                }}
                                type="button"
                              >
                                <div className="row-line">
                                  <span className="row-name" title={row.name}>
                                    {row.name}
                                  </span>
                                  {" "}
                                  <div className="bar">
                                    <span style={{ width: `${widthPct}%` }} />
                                  </div>
                                  {" "}
                                  <span className="row-count">{fmt(row.count)}</span>
                                </div>
                              </button>
                              {active ? (
                                <div className="inline-evidence">
                                  <div className="inline-head-row">
                                    <p className="inline-head">
                                      {row.name} | {fmt(row.tracks.length)} matching tracks
                                    </p>
                                    {row.labelUrl ? (
                                      <div className="inline-head-actions">
                                        <a className="discogs" href={row.labelUrl} rel="noreferrer" target="_blank">
                                          Label Page
                                        </a>
                                      </div>
                                    ) : null}
                                  </div>
                                  <div className="evidence-grid">
                                    {row.tracks.map((track) => {
                                      const sourceGroups = buildTrackCardSourceGroups(track);
                                      const sourceDjs = sourceGroups.length;
                                      const sourceSets = sourceGroups.reduce((total, group) => total + group.links.length, 0);
                                      return (
                                        <ArchiveEvidenceTrackCard
                                          albumArt={track.albumArt}
                                          confidence={primaryConfidenceFromCounts(track.confidenceCounts)}
                                          dataTrackKey={track.trackKey}
                                          key={track.trackKey}
                                          openState={
                                            trackCardStates[track.trackKey] ?? {
                                              sourcesOpen: false,
                                              spotifyOpen: false,
                                            }
                                          }
                                          onToggleSources={toggleTrackSources(track.trackKey)}
                                          onToggleSpotify={toggleTrackSpotify(track.trackKey)}
                                          sourceGroups={sourceGroups}
                                          sourceLabel={`Sets (${fmt(sourceDjs)} DJs, ${fmt(sourceSets)} Sets)`}
                                          spotifyTrackId={extractSpotifyTrackId(track.spotifyUrl)}
                                          style={trackCardStyles[track.trackKey] ?? null}
                                          title={track.title}
                                          titlePrefix={`${track.artist} - `}
                                        />
                                      );
                                    })}
                                  </div>
                                </div>
                              ) : null}
                            </article>
                          );
                        })
                      ) : (
                        <div className="empty">No taxonomy entries match current scope and query.</div>
                      )}
                  </ArchiveTaxonomyPanel>
                </div>
              </aside>
            </div>
          </div>
        </section>

        <section className="section dark reveal" id="network" ref={networkSectionRef}>
          <div className="section-inner">
            <div className="section-head">
              <h2>ARTIST CONNECTION MAP</h2>
              <p>
                Any-to-any comparison map. Click nodes to add/remove artists in the compare basket. Click edges to open pair analysis.
              </p>
            </div>

            <div className="network-panel">
              <div className="network-controls">
                <div className="control">
                  <label htmlFor="networkMinScore">Min Connection Score</label>
                  <input
                    id="networkMinScore"
                    max="100"
                    min="0"
                    onChange={(event) => setNetworkMinScore(Number(event.target.value))}
                    step="0.5"
                    style={{ margin: 2 }}
                    type="range"
                    value={networkMinScore}
                  />
                </div>
                <div className="control">
                  <label htmlFor="networkSearch">Find Artist</label>
                  <span className="mobile-search-shell mobile-search-shell-compact">
                    <input
                      id="networkSearch"
                      onChange={(event) => setNetworkSearch(event.target.value)}
                      placeholder="search artist nodes"
                      type="text"
                      value={networkSearch}
                    />
                  </span>
                </div>
                <div className="network-clear-wrap">
                  <button
                    className="chip-btn"
                    onClick={() => {
                      setNetworkSelectedArtistSlugs([]);
                      setPairPayload(null);
                      setPairPage(0);
                      setPairActiveName(null);
                      setNetworkZoom({ scale: 1, panX: 0, panY: 0 });
                    }}
                    type="button"
                  >
                    Clear
                  </button>
                </div>
              </div>

              <div className="network-wrap" id="networkWrap" ref={networkWrapRef}>
                {networkPayload ? (
                  <svg
                    aria-label="Artist connection map"
                    className="network-svg"
                    onPointerEnter={(event) => {
                      updateNetworkPointer({
                        clientX: event.clientX,
                        clientY: event.clientY,
                        currentTarget: event.currentTarget,
                      });
                    }}
                    onPointerLeave={() => {
                      setNetworkPointer((current) =>
                        current.active
                          ? {
                              active: false,
                              x: current.x,
                              y: current.y,
                            }
                          : current,
                      );
                    }}
                    onPointerMove={(event) => {
                      updateNetworkPointer({
                        clientX: event.clientX,
                        clientY: event.clientY,
                        currentTarget: event.currentTarget,
                      });
                    }}
                    viewBox={`${networkZoom.panX} ${networkZoom.panY} ${networkPositions.width / networkZoom.scale} ${networkPositions.height / networkZoom.scale}`}
                  >
                    <rect fill="#0f0f0f" height={networkPositions.height} width={networkPositions.width} x="0" y="0" />
                    {filteredNetworkEdges.map((edge) => {
                      const left = networkPositions.positions.get(edge.artistASlug);
                      const right = networkPositions.positions.get(edge.artistBSlug);
                      if (!left || !right) {
                        return null;
                      }
                      const { stroke, strokeWidth } = buildNetworkEdgeVisual(
                        edge.normalizedScore,
                      );
                      return (
                        <line
                          key={`${edge.artistASlug}-${edge.artistBSlug}`}
                          onClick={() => {
                            setPairLens("genres");
                            setPairPage(0);
                            setPairActiveName(null);
                            setNetworkSelectedArtistSlugs([edge.artistASlug, edge.artistBSlug]);
                            networkSectionRef.current?.scrollIntoView({
                              behavior: "smooth",
                              block: "start",
                            });
                          }}
                          stroke={stroke}
                          strokeWidth={strokeWidth}
                          x1={left.x}
                          x2={right.x}
                          y1={left.y}
                          y2={right.y}
                        />
                      );
                    })}
                    {networkNodeVisuals.map((node) => (
                      <g
                        key={node.artist.id}
                        onClick={() => toggleNetworkArtistSelection(node.artist.slug)}
                        style={{ cursor: "pointer" }}
                      >
                        <circle
                          className={joinClasses("network-node", node.selected && "selected")}
                          cx={node.position.x}
                          cy={node.position.y}
                          fill={node.selected ? "#7f51ff" : "#d8ff5a"}
                          r={node.circleRadius}
                        />
                        <text
                          dominantBaseline="middle"
                          fill="#f1f1f1"
                          fontFamily="Space Mono, monospace"
                          fontSize={node.labelFontSize}
                          fontWeight={node.visualWeight > 0.1 ? 700 : 400}
                          letterSpacing="0.02em"
                          paintOrder="stroke fill"
                          stroke="rgba(15,15,15,0.96)"
                          strokeLinejoin="round"
                          strokeWidth={node.labelHaloWidth}
                          textAnchor={node.textAnchor as "start" | "end"}
                          x={node.labelX}
                          y={node.labelY}
                        >
                          {node.artist.name}
                        </text>
                      </g>
                    ))}
                  </svg>
                ) : (
                  <div className="empty">No network graph data available.</div>
                )}
              </div>
            </div>

            <ArchiveTaxonomyPanel
              className="pair-panel"
              confidenceContainerId="pairTrackConfFilters"
              confidenceFilters={
                pairPayload
                  ? CONF_FILTER_LEVELS.map((filter) => {
                      const count =
                        filter === "all"
                          ? pairPayload.sharedTracks.length
                          : pairPayload.sharedTracks.filter(
                              (track) => track.confidenceCounts[filter] > 0,
                            ).length;
                      return {
                        active: pairConfidence === filter,
                        id: filter,
                        label: filter === "all" ? `All (${fmt(count)})` : filter,
                        onSelect: () => {
                          setPairConfidence(filter);
                          setPairPage(0);
                          setPairActiveName(null);
                        },
                      };
                    })
                  : []
              }
              lensOptions={
                pairPayload
                  ? [
                      { active: pairLens === "genres", id: "genres", label: "Genres" },
                      { active: pairLens === "labels", id: "labels", label: "Labels" },
                      { active: pairLens === "artists", id: "artists", label: "Artists" },
                      { active: pairLens === "tracks", id: "tracks", label: "Tracks" },
                    ]
                  : []
              }
              lensTabsId="pairTabs"
              onLensChange={(lensId) => {
                setPairLens(lensId as PairLens);
                setPairPage(0);
                setPairActiveName(null);
              }}
              pager={
                <div className="pager" id="pairPager">
                  {pairPayload && pairLens !== "tracks" ? (
                    <>
                      <button
                        disabled={safePairPage <= 0}
                        onClick={() => setPairPage((current) => current - 1)}
                        type="button"
                      >
                        Prev
                      </button>
                      <span className="info">
                        Page {safePairPage + 1} / {pairTotalPages}
                      </span>
                      <button
                        disabled={safePairPage >= pairTotalPages - 1}
                        onClick={() => setPairPage((current) => current + 1)}
                        type="button"
                      >
                        Next
                      </button>
                    </>
                  ) : null}
                </div>
              }
              rowsId="pairRows"
              search={{
                id: "pairSearch",
                onChange: (value) => {
                  setPairQuery(value);
                  setPairPage(0);
                  setPairActiveName(null);
                },
                placeholder: "search pair entries",
                value: pairQuery,
              }}
              sort={{
                id: "pairSort",
                onChange: (value) => setPairSort(value === "alpha" ? "alpha" : "count"),
                options: [
                  { label: "HIGHEST USAGE", value: "count" },
                  { label: "ALPHABETICAL", value: "alpha" },
                ],
                value: pairSort,
              }}
              style={{ marginTop: 12 }}
              summary={
                pairPayload
                  ? `Score ${fmt(pairPayload.normalizedScore)} | ${fmt(pairPayload.sharedTracksCount)} tracks | ${fmt(pairPayload.sharedLabelsCount)} labels | ${fmt(pairPayload.sharedGenresCount)} genres`
                  : "Pick an edge in the network or select exactly two artists."
              }
              threshold={
                pairPayload
                  ? {
                      canDecrease: pairThreshold !== THRESHOLD_LEVELS[0],
                      canIncrease: pairThreshold !== THRESHOLD_LEVELS[THRESHOLD_LEVELS.length - 1],
                      containerId: "pairThresholds",
                      onDecrease: () =>
                        setPairThreshold((current) => stepThresholdValue(current, THRESHOLD_LEVELS, -1)),
                      onIncrease: () =>
                        setPairThreshold((current) => stepThresholdValue(current, THRESHOLD_LEVELS, 1)),
                      valueLabel: `${fmt(pairThreshold)}+ SETS`,
                    }
                  : null
              }
              title={
                pairPayload
                  ? `Pair Analysis Workspace: ${pairPayload.artistA.name} x ${pairPayload.artistB.name}`
                  : "Pair Analysis Workspace"
              }
              titleId="pairTitle"
            >
                {pairPayload ? (
                  pairLens === "tracks" ? (
                    <div className="inline-evidence">
                      <p className="inline-head">Tracks | {fmt(pairRows.length)} matching tracks</p>
                      <div className="evidence-grid">
                        {pairRows.flatMap((row) =>
                          row.tracks.map((track) => {
                            const sourceGroups = buildTrackCardSourceGroups(track);
                            const sourceDjs = sourceGroups.length;
                            const sourceSets = sourceGroups.reduce((total, group) => total + group.links.length, 0);
                            return (
                              <ArchiveEvidenceTrackCard
                                albumArt={track.albumArt}
                                confidence={primaryConfidenceFromCounts(track.confidenceCounts)}
                                dataTrackKey={track.trackKey}
                                key={track.trackKey}
                                openState={
                                  trackCardStates[track.trackKey] ?? {
                                    sourcesOpen: false,
                                    spotifyOpen: false,
                                  }
                                }
                                onToggleSources={toggleTrackSources(track.trackKey)}
                                onToggleSpotify={toggleTrackSpotify(track.trackKey)}
                                sourceGroups={sourceGroups}
                                sourceLabel={`Sets (${fmt(sourceDjs)} DJs, ${fmt(sourceSets)} Sets)`}
                                spotifyTrackId={extractSpotifyTrackId(track.spotifyUrl)}
                                style={trackCardStyles[track.trackKey] ?? null}
                                title={track.title}
                                titlePrefix={`${track.artist} - `}
                              />
                            );
                          }),
                        )}
                      </div>
                    </div>
                  ) : pairPageRows.length ? (
                    pairPageRows.map((row) => {
                      const active = pairActiveName === row.id;
                      const widthPct = pairMaxCount ? (row.count / pairMaxCount) * 100 : 0;
                      return (
                        <article className={joinClasses("quant-row", active && "active")} key={row.id}>
                          <button
                            className="row-hit"
                            onClick={() => setPairActiveName((current) => (current === row.id ? null : row.id))}
                            type="button"
                          >
                            <div className="row-line">
                              <span className="row-name" title={row.name}>
                                {row.name}
                              </span>
                              {" "}
                              <div className="bar">
                                <span style={{ width: `${widthPct}%` }} />
                              </div>
                              {" "}
                              <span className="row-count">{fmt(row.count)}</span>
                            </div>
                          </button>
                          {active ? (
                            <div className="inline-evidence">
                              <div className="inline-head-row">
                                <p className="inline-head">
                                  {row.name} | {fmt(row.tracks.length)} shared tracks | {row.meta}
                                </p>
                              </div>
                              <div className="evidence-grid">
                                {row.tracks.map((track) => {
                                  const sourceGroups = buildTrackCardSourceGroups(track);
                                  const sourceDjs = sourceGroups.length;
                                  const sourceSets = sourceGroups.reduce((total, group) => total + group.links.length, 0);
                                  return (
                                    <ArchiveEvidenceTrackCard
                                      albumArt={track.albumArt}
                                      confidence={primaryConfidenceFromCounts(track.confidenceCounts)}
                                      dataTrackKey={track.trackKey}
                                      key={track.trackKey}
                                      openState={
                                        trackCardStates[track.trackKey] ?? {
                                          sourcesOpen: false,
                                          spotifyOpen: false,
                                        }
                                      }
                                      onToggleSources={toggleTrackSources(track.trackKey)}
                                      onToggleSpotify={toggleTrackSpotify(track.trackKey)}
                                      sourceGroups={sourceGroups}
                                      sourceLabel={`Sets (${fmt(sourceDjs)} DJs, ${fmt(sourceSets)} Sets)`}
                                      spotifyTrackId={extractSpotifyTrackId(track.spotifyUrl)}
                                      style={trackCardStyles[track.trackKey] ?? null}
                                      title={track.title}
                                      titlePrefix={`${track.artist} - `}
                                    />
                                  );
                                })}
                              </div>
                            </div>
                          ) : null}
                        </article>
                      );
                    })
                  ) : (
                    <div className="empty">No pair entries match current controls.</div>
                  )
                ) : (
                  <div className="empty">No active pair selected.</div>
                )}
            </ArchiveTaxonomyPanel>
          </div>
        </section>

        <section className="section reveal" id="sets" style={{ position: "relative" }}>
          <div style={{ position: "absolute", top: 18, right: 24, zIndex: 500 }}>
            <InlineSubmitButton label="+ submit sets" mode="scan-artist" />
          </div>
          <div className="section-inner">
            <div className="section-head">
              <h2>FULL SET LIBRARY</h2>
              <p>
                Search across all processed sets, filter by artist, and inspect tracklists.
              </p>
            </div>

            <div className="set-panel">
              <div className="controls-grid set-library-controls" style={{ marginBottom: 10, marginTop: 0 }}>
                <div className="control">
                  <label htmlFor="setSearch">Search Sets</label>
                  <span className="mobile-search-shell mobile-search-shell-compact">
                    <input
                      id="setSearch"
                      onChange={(event) => {
                        setSetQuery(event.target.value);
                        setSetPage(1);
                      }}
                      placeholder="set title, artist, track"
                      type="text"
                      value={setQuery}
                    />
                  </span>
                </div>
                <div className="control">
                  <label htmlFor="setArtistFilter">Artist Filter</label>
                  <select
                    id="setArtistFilter"
                    onChange={(event) => {
                      setSetArtistFilter(event.target.value);
                      setSetPage(1);
                    }}
                    value={setArtistFilter}
                  >
                    {setLibrary.artistOptions.map((artistOption) => (
                      <option key={artistOption} value={artistOption}>
                        {artistOption === "ALL" ? "ALL ARTISTS" : artistOption.toUpperCase()}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="control">
                  <label htmlFor="setSort">Sort</label>
                  <select
                    id="setSort"
                    onChange={(event) => {
                      setSetSort((event.target.value as ArchiveHomeSetSort) ?? "default");
                      setSetPage(1);
                    }}
                    value={setSort}
                  >
                    <option value="default">DEFAULT</option>
                    <option value="rate">RECOGNITION RATE</option>
                    <option value="tracks">TRACK COUNT</option>
                    <option value="duration">DURATION</option>
                  </select>
                </div>
              </div>

              <div className="set-grid" id="setGrid">
                {setLibrary.items.length ? (
                  setLibrary.items.map((setItem) => {
                    const expanded = expandedSets.includes(setItem.slug);
                    const tracklist = setTracklists[setItem.slug] ?? [];
                    const tracklistError = tracklistErrors[setItem.slug];
                    const tracklistLoading = loadingTracklists[setItem.slug] ?? false;

                    return (
                      <ArchiveSetCard
                        actions={
                          setItem.artistSlug
                            ? [
                                {
                                  href: buildArtistHref({ slug: setItem.artistSlug }),
                                  key: `artist:${setItem.id}`,
                                  label: "Artist Page",
                                },
                              ]
                            : []
                        }
                        imageAlt={setItem.title}
                        imageUrl={setItem.thumbnailUrl}
                        key={setItem.id}
                        metaPills={[
                          `${fmt(setItem.totalTracks)} tracks`,
                          `${Math.round(setItem.recognitionRate ?? 0)}% match`,
                          setItem.duration >= 3600
                            ? `${Math.floor(setItem.duration / 3600)}h ${Math.floor((setItem.duration % 3600) / 60)}m`
                            : `${Math.floor(setItem.duration / 60)}m`,
                        ]}
                        miniTimeline={setItem.miniTimeline.map((segment) => ({
                          confidence: segment.confidence,
                          leftPct: segment.startPct,
                          widthPct: segment.widthPct,
                        }))}
                        setHref={buildSetHref({ slug: setItem.slug })}
                        sourceHref={setItem.sourceUrl}
                        title={setItem.title}
                        toggleTracklist={() => toggleSetTracklist(setItem.slug)}
                        tracklist={tracklist.map((track) => ({
                          confidence: track.confidence,
                          href: buildTrackSetHref({
                            setSlug: track.setSlug,
                            trackPosition: track.position,
                          }),
                          id: `${setItem.id}-${track.trackKey}-${track.position}`,
                          label: `${track.artist} - ${track.title}`,
                          startTimeFormatted: track.startTimeFormatted,
                        }))}
                        tracklistEmptyLabel={tracklistError ?? "No recognized tracks in this set."}
                        tracklistExpanded={expanded}
                        tracklistLoading={tracklistLoading}
                      />
                    );
                  })
                ) : (
                  <div className="empty">No sets match current filters.</div>
                )}
              </div>
              <div className="pager" id="setPager">
                <button
                  disabled={setLibrary.page <= 1}
                  onClick={() => {
                    pendingSetLibraryJumpRef.current = true;
                    setSetPage((current) => current - 1);
                  }}
                  type="button"
                >
                  Prev
                </button>
                <span className="info">
                  Page {setLibrary.page} / {setLibrary.totalPages} | {fmt(setLibrary.totalItems)} sets
                </span>
                <button
                  disabled={setLibrary.page >= setLibrary.totalPages}
                  onClick={() => {
                    pendingSetLibraryJumpRef.current = true;
                    setSetPage((current) => current + 1);
                  }}
                  type="button"
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        </section>

        <footer className="footer reveal">
          <h2>FOLLOW THE CURATION SIGNAL</h2>
          <p>
            Generated from local archive data on <span id="generatedAt">{initial.generatedAt ?? "N/A"}</span>.
            This experience is designed for investigation depth: compare artists, inspect overlap logic, and follow evidence to concrete tracks and sets.
          </p>
        </footer>
      </div>
    </div>
  );
}

/* eslint-disable @next/next/no-img-element */
"use client";

import {
  startTransition,
  useDeferredValue,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent,
} from "react";

import { buildSetHref } from "@/components/archive/archive-hrefs";
import {
  ArchiveEvidenceTrackCard,
  type ArchiveEvidenceTrackCardSourceGroup,
} from "@/components/archive/archive-evidence-track-card";
import { ArchiveHeader } from "@/components/archive/archive-header";
import { ArchiveSetCard } from "@/components/archive/archive-set-card";
import { SpotifyExportButton } from "@/components/archive/spotify-export-button";
import { ArchiveScrollRoot } from "@/components/archive/archive-scroll-root";
import { ArchiveTaxonomyPanel } from "@/components/archive/archive-taxonomy-panel";
import { InlineSubmitButton } from "@/components/archive/inline-submit-button";
import { buildArtistSpotifyExportCounts } from "@/lib/archive/spotify-export";
import { buildArtistHeroRail, pickFirstImageUrl } from "@/lib/archive/artist-visuals";
import { ARCHIVE_SET_LIBRARY_PAGE_SIZE } from "@/lib/archive/constants";
import type {
  ArchiveArtistAtlasTrack,
  ArchiveArtistSet,
  ArchiveArtistSetTrackRef,
  ArchiveArtistSummary,
  ArchiveConfidence,
  ArchiveRecurringTrack,
} from "@/lib/archive/types";
import { buildSearchBlob, extractSpotifyTrackId, normalizeSearchText } from "@/lib/archive/utils";

import styles from "./archive-artist-explorer.module.css";

type ConfidenceFilter = ArchiveConfidence | "all";
type AtlasScope = "artist" | "set";
type AtlasCompareMode = "intersection" | "union";
type AtlasLens = "artists" | "genres" | "labels" | "tracks";
type SetSort = "default" | "duration" | "rate" | "tracks";

type RecurringCardModel = ArchiveRecurringTrack & {
  searchBlob: string;
  spotifyTrackId: string | null;
};

type SetCardModel = ArchiveArtistSet & {
  heroImageUrl: string | null;
  matchLabel: string;
  previewHref: string;
  searchBlob: string;
  trackKeySet: Set<string>;
  visibleTracks: ArchiveArtistSetTrackRef[];
};

type AtlasTrackModel = ArchiveArtistAtlasTrack & {
  previewAnchorHref: string;
  searchBlob: string;
  spotifyTrackId: string | null;
};

type AtlasEvidenceTrack = {
  albumArt: string | null;
  artist: string;
  confidence: ArchiveConfidence;
  genres: string[];
  label: string | null;
  labelUrl: string | null;
  occurrences: number;
  searchBlob: string;
  setLinks: Array<{
    href: string;
    label: string;
  }>;
  spotifyTrackId: string | null;
  spotifyUrl: string | null;
  title: string;
  trackKey: string;
};

type AtlasRow = {
  count: number;
  coverage: Set<string>;
  labelUrl: string | null;
  name: string;
  searchBlob: string;
  tracks: AtlasEvidenceTrack[];
};

type TrackCardInlineStyle = CSSProperties & Partial<Record<`--${string}`, string>>;

const TRACK_CONFIDENCE_LEVELS: ConfidenceFilter[] = ["all", "HIGH", "MEDIUM", "LOW"];
const ATLAS_PAGE_SIZE = 10;
const SETS_PAGE_SIZE = ARCHIVE_SET_LIBRARY_PAGE_SIZE;
const FOCUS_TITLE_NBSP = "\u00a0";
const HERO_TITLE_FIT_VAR = "--artist-hero-title-fit-size";
const HERO_TITLE_MIN_SIZE = 24;
const HERO_TITLE_SAFE_PADDING = 6;
const OPEN_EVIDENCE_ACTION_ROW_HEIGHT = 36;
const CONFIDENCE_RANK: Record<ArchiveConfidence, number> = {
  HIGH: 4,
  MEDIUM: 3,
  LOW: 2,
  UNCERTAIN: 1,
};

const joinClasses = (...values: Array<string | false | null | undefined>) =>
  values.filter(Boolean).join(" ");

const formatGeneratedAt = (value: string | null) => {
  if (!value) {
    return "Unknown";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  const hours = String(parsed.getHours()).padStart(2, "0");
  const minutes = String(parsed.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes}`;
};

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));

const isHoverCapablePointer = () =>
  typeof window !== "undefined" && window.matchMedia("(hover: hover) and (pointer: fine)").matches;

const toggleSelectedSetIds = (currentSelectedIds: string[], setId: string) => {
  if (!setId) {
    return currentSelectedIds;
  }

  if (currentSelectedIds.includes(setId)) {
    return currentSelectedIds.length > 1
      ? currentSelectedIds.filter((currentSetId) => currentSetId !== setId)
      : [setId];
  }

  return [...currentSelectedIds, setId];
};

const buildArtistTrackSourceGroups = (
  trackKey: string,
  setLinks: Array<{
    href?: string | null;
    label: string;
  }>,
): ArchiveEvidenceTrackCardSourceGroup[] =>
  setLinks.length > 0
    ? [
        {
          emptyLabel: "No set links available.",
          id: `${trackKey}-sets`,
          links: setLinks.map((link, index) => ({
            href: link.href,
            id: `${trackKey}-set-${index}`,
            label: link.label,
          })),
        },
      ]
    : [];

const formatMatch = (rate: number | null) => `${Math.round(rate ?? 0)}% match`;

const formatSetSummary = (setItem: ArchiveArtistSet) =>
  `${setItem.totalTracks} tracks · ${formatMatch(setItem.recognitionRate)} · ${setItem.durationFmt}`;

const formatHeroSetSummary = (setItem: ArchiveArtistSet) =>
  `${setItem.totalTracks} tracks · ${setItem.durationFmt}`;

const normalizeThresholdValues = (values: number[]) => {
  const unique = Array.from(
    new Set(values.filter((value) => Number.isFinite(value) && value > 0).map((value) => Math.floor(value))),
  ).sort((left, right) => left - right);

  return unique.length > 0 ? unique : [1];
};

const stepThresholdValue = (current: number, values: number[], direction: number) => {
  const safeValues = normalizeThresholdValues(values);
  const index = safeValues.findIndex((value) => value === current);
  const resolvedIndex = index >= 0 ? index : 0;
  const nextIndex = clamp(resolvedIndex + direction, 0, safeValues.length - 1);
  return safeValues[nextIndex] ?? safeValues[0] ?? 1;
};

const trackMatchesConfidence = (
  confidenceCounts: Record<ArchiveConfidence, number>,
  filter: ConfidenceFilter,
) => {
  if (filter === "all") {
    return true;
  }

  return Number(confidenceCounts[filter] ?? 0) > 0;
};

const buildTrackAnchorHref = (setSlug: string, trackPosition: number) =>
  `${buildSetHref({ slug: setSlug })}#track-${trackPosition}`;

const buildRecurringCards = (artist: ArchiveArtistSummary): RecurringCardModel[] =>
  artist.recurringTracks.map((track) => ({
    ...track,
    searchBlob: buildSearchBlob(track.artist, track.title, track.genres.join(" "), track.label ?? ""),
    spotifyTrackId: extractSpotifyTrackId(track.spotifyUrl),
  }));

const buildSetCards = (artist: ArchiveArtistSummary): SetCardModel[] =>
  artist.sets.map((setItem) => {
    const previewHref = buildSetHref({ slug: setItem.slug });

    return {
      ...setItem,
      heroImageUrl: setItem.thumbnailUrl,
      matchLabel: formatMatch(setItem.recognitionRate),
      previewHref,
      searchBlob: buildSearchBlob(setItem.title, setItem.trackSearchText),
      trackKeySet: new Set(
        setItem.tracks
          .filter((track) => !track.isUnknown)
          .map((track) => normalizeSearchText(track.trackKey)),
      ),
      visibleTracks: setItem.tracks.filter((track) => !track.isUnknown),
    };
  });

const buildAtlasTracks = (artist: ArchiveArtistSummary): AtlasTrackModel[] =>
  artist.atlasTracks.map((track) => ({
    ...track,
    previewAnchorHref: buildTrackAnchorHref(track.setSlug, track.idx),
    searchBlob: buildSearchBlob(
      track.artist,
      track.title,
      track.genres.join(" "),
      track.label ?? "",
      track.setTitle,
    ),
    spotifyTrackId: extractSpotifyTrackId(track.spotifyUrl),
  }));

const splitSetAtlasHeadingTwoLines = (title: string) => {
  const normalized = title.replace(/\s+/gu, " ").trim();
  if (!normalized) {
    return { line1: "No Set Selected", line2: FOCUS_TITLE_NBSP, sizeClass: "focus-title-md" };
  }

  const words = normalized.split(" ");
  if (words.length === 1) {
    const singleClass =
      normalized.length > 42 ? "focus-title-sm" : normalized.length > 26 ? "focus-title-md" : "focus-title-lg";
    return { line1: normalized, line2: FOCUS_TITLE_NBSP, sizeClass: singleClass };
  }

  let splitIndex = 1;
  let bestScore = Number.POSITIVE_INFINITY;
  for (let index = 1; index < words.length; index += 1) {
    const left = words.slice(0, index).join(" ");
    const right = words.slice(index).join(" ");
    const delta = Math.abs(left.length - right.length);
    const longest = Math.max(left.length, right.length);
    const shortest = Math.min(left.length, right.length);
    const score = delta + (longest > 52 ? (longest - 52) * 2 : 0) + (shortest < 8 ? 8 - shortest : 0);
    if (score < bestScore) {
      bestScore = score;
      splitIndex = index;
    }
  }

  const line1 = words.slice(0, splitIndex).join(" ");
  const line2 = words.slice(splitIndex).join(" ") || FOCUS_TITLE_NBSP;
  const longestLine = Math.max(line1.length, line2.length);
  const totalLength = normalized.length;
  let sizeClass = "focus-title-lg";
  if (longestLine > 46 || totalLength > 92) {
    sizeClass = "focus-title-xs";
  } else if (longestLine > 36 || totalLength > 74) {
    sizeClass = "focus-title-sm";
  } else if (longestLine > 27 || totalLength > 56) {
    sizeClass = "focus-title-md";
  }

  return { line1, line2, sizeClass };
};

const getBetterConfidence = (left: ArchiveConfidence, right: ArchiveConfidence) =>
  CONFIDENCE_RANK[right] > CONFIDENCE_RANK[left] ? right : left;

const getPrimaryConfidenceFromCounts = (
  confidenceCounts: Record<ArchiveConfidence, number>,
): ArchiveConfidence =>
  (Object.keys(CONFIDENCE_RANK) as ArchiveConfidence[]).reduce((best, candidate) => {
    const bestCount = Number(confidenceCounts[best] ?? 0);
    const candidateCount = Number(confidenceCounts[candidate] ?? 0);
    if (candidateCount > bestCount) {
      return candidate;
    }
    if (candidateCount === bestCount) {
      return getBetterConfidence(best, candidate);
    }
    return best;
  }, "UNCERTAIN");

const buildMiniTimeline = (setItem: SetCardModel) => {
  if (setItem.duration <= 0 || setItem.tracks.length === 0) {
    return [];
  }

  const orderedTracks = [...setItem.tracks].sort((left, right) => left.start - right.start);
  const segments: Array<{
    confidence: ArchiveConfidence;
    leftPct: number;
    widthPct: number;
  }> = [];
  let cursor = 0;

  for (let index = 0; index < orderedTracks.length; index += 1) {
    const track = orderedTracks[index];
    const nextTrack = orderedTracks[index + 1];
    const start = clamp(track.start, 0, setItem.duration);
    const endCandidate =
      track.end ??
      (nextTrack ? clamp(nextTrack.start, start, setItem.duration) : setItem.duration);
    const end = clamp(endCandidate, start, setItem.duration);

    if (start > cursor) {
      segments.push({
        confidence: "UNCERTAIN",
        leftPct: (cursor / setItem.duration) * 100,
        widthPct: ((start - cursor) / setItem.duration) * 100,
      });
    }

    const resolvedConfidence = track.isUnknown ? "UNCERTAIN" : track.confidence;
    const width = Math.max(0.8, ((end - start) / setItem.duration) * 100);
    segments.push({
      confidence: resolvedConfidence,
      leftPct: (start / setItem.duration) * 100,
      widthPct: width,
    });
    cursor = Math.max(cursor, end);
  }

  if (cursor < setItem.duration) {
    segments.push({
      confidence: "UNCERTAIN",
      leftPct: (cursor / setItem.duration) * 100,
      widthPct: ((setItem.duration - cursor) / setItem.duration) * 100,
    });
  }

  return segments.filter((segment) => segment.widthPct > 0);
};

const buildAtlasRows = ({
  lens,
  mode,
  query,
  scope,
  selectedSetIds,
  sort,
  threshold,
  tracks,
}: {
  lens: AtlasLens;
  mode: AtlasCompareMode;
  query: string;
  scope: AtlasScope;
  selectedSetIds: Set<string>;
  sort: "alpha" | "count";
  threshold: number;
  tracks: AtlasTrackModel[];
}): AtlasRow[] => {
  const rowMap = new Map<string, AtlasRow>();
  const normalizedQuery = normalizeSearchText(query);
  const selectedCount = selectedSetIds.size;

  for (const track of tracks) {
    const names =
      lens === "genres"
        ? track.genres
        : lens === "labels"
          ? track.label
            ? [track.label]
            : []
          : lens === "artists"
            ? [track.artist]
            : [`${track.artist} - ${track.title}`];

    for (const name of names) {
      if (!name) {
        continue;
      }

      const row =
        rowMap.get(name) ??
        {
          count: 0,
          coverage: new Set<string>(),
          labelUrl: lens === "labels" ? track.labelUrl : null,
          name,
          searchBlob: normalizeSearchText(name),
          tracks: [],
        };

      row.coverage.add(track.setId);
      if (!row.labelUrl && lens === "labels") {
        row.labelUrl = track.labelUrl;
      }

      const existingTrackIndex = row.tracks.findIndex((value) => value.trackKey === track.trackKey);
      if (existingTrackIndex === -1) {
        row.tracks.push({
          albumArt: track.albumArt,
          artist: track.artist,
          confidence: track.confidence,
          genres: track.genres,
          label: track.label,
          labelUrl: track.labelUrl,
          occurrences: 1,
          searchBlob: track.searchBlob,
          setLinks: [
            {
              href: track.previewAnchorHref,
              label: track.setTitle,
            },
          ],
          spotifyTrackId: track.spotifyTrackId,
          spotifyUrl: track.spotifyUrl,
          title: track.title,
          trackKey: track.trackKey,
        });
      } else {
        const existingTrack = row.tracks[existingTrackIndex];
        const nextLink = {
          href: track.previewAnchorHref,
          label: track.setTitle,
        };
        const hasLink = existingTrack.setLinks.some(
          (value) => value.href === nextLink.href && value.label === nextLink.label,
        );
        row.tracks[existingTrackIndex] = {
          ...existingTrack,
          albumArt: existingTrack.albumArt ?? track.albumArt,
          confidence: getBetterConfidence(existingTrack.confidence, track.confidence),
          genres: existingTrack.genres.length > 0 ? existingTrack.genres : track.genres,
          label: existingTrack.label ?? track.label,
          labelUrl: existingTrack.labelUrl ?? track.labelUrl,
          occurrences: existingTrack.occurrences + 1,
          setLinks: hasLink ? existingTrack.setLinks : [...existingTrack.setLinks, nextLink],
          spotifyTrackId: existingTrack.spotifyTrackId ?? track.spotifyTrackId,
          spotifyUrl: existingTrack.spotifyUrl ?? track.spotifyUrl,
        };
      }

      rowMap.set(name, row);
    }
  }

  return Array.from(rowMap.values())
    .map((row) => ({
      ...row,
      count:
        lens === "tracks"
          ? row.tracks.reduce((total, track) => total + track.occurrences, 0)
          : row.tracks.length,
      tracks: [...row.tracks].sort((left, right) => {
        if (right.occurrences !== left.occurrences) {
          return right.occurrences - left.occurrences;
        }

        return `${left.artist} ${left.title}`.localeCompare(`${right.artist} ${right.title}`);
      }),
    }))
    .filter((row) => row.count >= threshold)
    .filter((row) => (normalizedQuery ? row.searchBlob.includes(normalizedQuery) : true))
    .filter((row) =>
      scope === "set" && mode === "intersection" && selectedCount > 1
        ? row.coverage.size === selectedCount
        : true,
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
};

const getRecurringThresholdValues = (cards: RecurringCardModel[]) =>
  normalizeThresholdValues(cards.map((track) => track.appearances));

const getAtlasThresholdValues = (rows: AtlasRow[]) =>
  normalizeThresholdValues(rows.map((row) => row.count));

const buildAtlasOpenCardStyle = (
  card: HTMLElement | null,
  panel: "embed" | "source",
): TrackCardInlineStyle | null => {
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

export function ArchiveArtistExplorer({
  artist,
  initialQuery,
  scope,
}: {
  artist: ArchiveArtistSummary;
  initialQuery: string;
  scope: "global" | "mine";
}) {
  const heroMainRef = useRef<HTMLDivElement | null>(null);
  const heroVisualRef = useRef<HTMLDivElement | null>(null);
  const heroTitleRef = useRef<HTMLHeadingElement | null>(null);
  const heroSideRef = useRef<HTMLElement | null>(null);
  const heroRailViewportRef = useRef<HTMLDivElement | null>(null);
  const heroRailTrackRef = useRef<HTMLDivElement | null>(null);
  const atlasRailRef = useRef<HTMLDivElement | null>(null);
  const recurringCards = buildRecurringCards(artist);
  const setCards = buildSetCards(artist);
  const atlasTracks = buildAtlasTracks(artist);
  const spotifyExportCounts = useMemo(() => buildArtistSpotifyExportCounts(artist), [artist]);
  const heroRail = buildArtistHeroRail(setCards);
  const heroVisualImageUrl = pickFirstImageUrl([
    artist.imageUrl,
    artist.heroImageUrl,
    ...heroRail.map((setItem) => setItem.heroImageUrl),
  ]);

  const recurringThresholdValues = getRecurringThresholdValues(recurringCards);
  const [recMin, setRecMin] = useState(recurringThresholdValues[0] ?? 1);
  const [recFilter, setRecFilter] = useState<ConfidenceFilter>("all");
  const [recSearch, setRecSearch] = useState(initialQuery);
  const deferredRecSearch = useDeferredValue(recSearch);
  const [openRecurringSources, setOpenRecurringSources] = useState<string[]>([]);
  const [openRecurringSpotify, setOpenRecurringSpotify] = useState<string[]>([]);
  const [recurringCardStyles, setRecurringCardStyles] = useState<Record<string, TrackCardInlineStyle>>({});

  const [atlasScope, setAtlasScope] = useState<AtlasScope>("set");
  const [atlasSelectedSetIds, setAtlasSelectedSetIds] = useState<string[]>(
    setCards[0] ? [setCards[0].id] : [],
  );
  const [atlasCompareMode, setAtlasCompareMode] = useState<AtlasCompareMode>("union");
  const [atlasLens, setAtlasLens] = useState<AtlasLens>("genres");
  const [atlasMin, setAtlasMin] = useState(1);
  const [atlasConf, setAtlasConf] = useState<ConfidenceFilter>("all");
  const [atlasSetSearch, setAtlasSetSearch] = useState("");
  const [atlasQuery, setAtlasQuery] = useState("");
  const deferredAtlasSetSearch = useDeferredValue(atlasSetSearch);
  const deferredAtlasQuery = useDeferredValue(atlasQuery);
  const [atlasSort, setAtlasSort] = useState<"alpha" | "count">("count");
  const [atlasPage, setAtlasPage] = useState(0);
  const [atlasActiveName, setAtlasActiveName] = useState<string | null>(null);
  const [, setAtlasEvidencePage] = useState(0);
  const [openAtlasSources, setOpenAtlasSources] = useState<string[]>([]);
  const [openAtlasSpotify, setOpenAtlasSpotify] = useState<string[]>([]);
  const [atlasCardStyles, setAtlasCardStyles] = useState<Record<string, TrackCardInlineStyle>>({});
  const [atlasDockedSelectedSetIds, setAtlasDockedSelectedSetIds] = useState<string[]>(
    setCards[0] ? [setCards[0].id] : [],
  );
  const [atlasPanePointerInside, setAtlasPanePointerInside] = useState(false);
  const [atlasHoverLatchedSetId, setAtlasHoverLatchedSetId] = useState<string | null>(null);
  const pendingSetExplorerJumpRef = useRef(false);
  const pendingAtlasRailResetRef = useRef(false);
  const latestAtlasSelectedSetIdsRef = useRef(atlasSelectedSetIds);

  const [setSearch, setSetSearch] = useState(initialQuery);
  const [setSort, setSetSort] = useState<SetSort>("default");
  const deferredSetSearch = useDeferredValue(setSearch);
  const [setPage, setSetPage] = useState(0);
  const [compareSelection, setCompareSelection] = useState<string[]>([]);
  const [expandedSetCards, setExpandedSetCards] = useState<string[]>([]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.location.hash) {
      return;
    }

    const hash = decodeURIComponent(window.location.hash.slice(1));
    if (!hash) {
      return;
    }

    const scrollToHash = () => {
      const target = document.getElementById(hash);
      if (!target) {
        return;
      }

      target.scrollIntoView({ behavior: "auto", block: "start" });
    };

    const frame = window.requestAnimationFrame(() => {
      window.requestAnimationFrame(scrollToHash);
    });

    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, []);

  useLayoutEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const visual = heroVisualRef.current;
    const title = heroTitleRef.current;
    if (!visual || !title) {
      return;
    }

    let frame = 0;
    let disposed = false;

    const applyFontSize = (size?: number) => {
      if (typeof size === "number" && Number.isFinite(size) && size > 0) {
        title.style.setProperty(HERO_TITLE_FIT_VAR, `${size}px`);
      } else {
        title.style.removeProperty(HERO_TITLE_FIT_VAR);
      }
    };

    const titleFits = () => {
      const visualRect = visual.getBoundingClientRect();
      const titleRect = title.getBoundingClientRect();

      return (
        titleRect.top >= visualRect.top + HERO_TITLE_SAFE_PADDING &&
        titleRect.left >= visualRect.left + HERO_TITLE_SAFE_PADDING &&
        titleRect.right <= visualRect.right - HERO_TITLE_SAFE_PADDING &&
        titleRect.bottom <= visualRect.bottom - HERO_TITLE_SAFE_PADDING
      );
    };

    // Shrink the display title only when the rendered text actually clips inside the hero box.
    const fitTitle = () => {
      applyFontSize();

      const baseSize = Number.parseFloat(window.getComputedStyle(title).fontSize);
      if (!Number.isFinite(baseSize) || baseSize <= HERO_TITLE_MIN_SIZE) {
        return;
      }

      if (titleFits()) {
        return;
      }

      let low = HERO_TITLE_MIN_SIZE;
      let high = baseSize;
      let best = HERO_TITLE_MIN_SIZE;

      applyFontSize(HERO_TITLE_MIN_SIZE);
      if (!titleFits()) {
        return;
      }

      for (let iteration = 0; iteration < 12; iteration += 1) {
        const mid = (low + high) / 2;
        applyFontSize(mid);

        if (titleFits()) {
          best = mid;
          low = mid;
        } else {
          high = mid;
        }
      }

      applyFontSize(Math.floor(best * 10) / 10);
    };

    const scheduleFit = () => {
      if (disposed) {
        return;
      }

      if (frame) {
        window.cancelAnimationFrame(frame);
      }

      frame = window.requestAnimationFrame(() => {
        frame = 0;
        fitTitle();
      });
    };

    const resizeObserver =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => scheduleFit());
    resizeObserver?.observe(visual);

    const heroImage = visual.querySelector("img") as HTMLImageElement | null;
    if (heroImage && !heroImage.complete) {
      heroImage.addEventListener("load", scheduleFit);
    }

    void document.fonts?.ready.then(() => {
      scheduleFit();
    });

    scheduleFit();

    return () => {
      disposed = true;
      if (frame) {
        window.cancelAnimationFrame(frame);
      }
      resizeObserver?.disconnect();
      heroImage?.removeEventListener("load", scheduleFit);
      applyFontSize();
    };
  }, [artist.name, heroVisualImageUrl]);

  useLayoutEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const heroMain = heroMainRef.current;
    const heroSide = heroSideRef.current;
    if (!heroMain || !heroSide) {
      return;
    }

    let frame = 0;

    const syncHeroSideHeight = () => {
      heroSide.style.removeProperty("height");
      if (window.matchMedia("(max-width: 1320px)").matches) {
        return;
      }

      const nextHeight = Math.round(heroMain.getBoundingClientRect().height);
      if (nextHeight > 0) {
        heroSide.style.height = `${nextHeight}px`;
      }
    };

    const scheduleSync = () => {
      if (frame) {
        window.cancelAnimationFrame(frame);
      }

      frame = window.requestAnimationFrame(() => {
        frame = 0;
        syncHeroSideHeight();
      });
    };

    const resizeObserver =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => scheduleSync());
    resizeObserver?.observe(heroMain);
    window.addEventListener("resize", scheduleSync);
    void document.fonts?.ready.then(() => {
      scheduleSync();
    });
    scheduleSync();

    return () => {
      if (frame) {
        window.cancelAnimationFrame(frame);
      }
      resizeObserver?.disconnect();
      window.removeEventListener("resize", scheduleSync);
      heroSide.style.removeProperty("height");
    };
  }, [artist.name, heroRail.length]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const viewport = heroRailViewportRef.current;
    const track = heroRailTrackRef.current;
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

    const handleResize = () => {
      start();
    };

    viewport.addEventListener("mouseenter", stop);
    viewport.addEventListener("mouseleave", start);
    window.addEventListener("resize", handleResize);
    start();

    return () => {
      stop();
      viewport.removeEventListener("mouseenter", stop);
      viewport.removeEventListener("mouseleave", start);
      window.removeEventListener("resize", handleResize);
    };
  }, [heroRail.length]);

  const clearAtlasCardStyle = (trackKey: string) => {
    setAtlasCardStyles((current) => {
      if (!current[trackKey]) {
        return current;
      }

      const next = { ...current };
      delete next[trackKey];
      return next;
    });
  };

  const setAtlasCardStyle = (trackKey: string, style: TrackCardInlineStyle | null) => {
    if (!style) {
      clearAtlasCardStyle(trackKey);
      return;
    }

    setAtlasCardStyles((current) => ({
      ...current,
      [trackKey]: style,
    }));
  };

  const clearRecurringCardStyle = (trackKey: string) => {
    setRecurringCardStyles((current) => {
      if (!current[trackKey]) {
        return current;
      }

      const next = { ...current };
      delete next[trackKey];
      return next;
    });
  };

  const setRecurringCardStyle = (trackKey: string, style: TrackCardInlineStyle | null) => {
    if (!style) {
      clearRecurringCardStyle(trackKey);
      return;
    }

    setRecurringCardStyles((current) => ({
      ...current,
      [trackKey]: style,
    }));
  };

  const handleRecurringSpotifyToggle = (
    event: MouseEvent<HTMLButtonElement>,
    trackKey: string,
  ) => {
    const card = event.currentTarget.closest(".track-card") as HTMLElement | null;
    const isOpen = openRecurringSpotify.includes(trackKey);

    if (isOpen) {
      setOpenRecurringSpotify((current) => current.filter((value) => value !== trackKey));
      clearRecurringCardStyle(trackKey);
      return;
    }

    setRecurringCardStyle(trackKey, buildAtlasOpenCardStyle(card, "embed"));
    setOpenRecurringSources((current) => current.filter((value) => value !== trackKey));
    setOpenRecurringSpotify((current) => [...current.filter((value) => value !== trackKey), trackKey]);
  };

  const handleRecurringSourcesToggle = (
    event: MouseEvent<HTMLButtonElement>,
    trackKey: string,
  ) => {
    const card = event.currentTarget.closest(".track-card") as HTMLElement | null;
    const isOpen = openRecurringSources.includes(trackKey);

    if (isOpen) {
      setOpenRecurringSources((current) => current.filter((value) => value !== trackKey));
      clearRecurringCardStyle(trackKey);
      return;
    }

    setRecurringCardStyle(trackKey, buildAtlasOpenCardStyle(card, "source"));
    setOpenRecurringSpotify((current) => current.filter((value) => value !== trackKey));
    setOpenRecurringSources((current) => [...current.filter((value) => value !== trackKey), trackKey]);
  };

  const handleAtlasSpotifyToggle = (
    event: MouseEvent<HTMLButtonElement>,
    trackKey: string,
  ) => {
    const card = event.currentTarget.closest(".track-card") as HTMLElement | null;
    const isOpen = openAtlasSpotify.includes(trackKey);

    if (isOpen) {
      setOpenAtlasSpotify((current) => current.filter((value) => value !== trackKey));
      clearAtlasCardStyle(trackKey);
      return;
    }

    setAtlasCardStyle(trackKey, buildAtlasOpenCardStyle(card, "embed"));
    setOpenAtlasSources((current) => current.filter((value) => value !== trackKey));
    setOpenAtlasSpotify((current) => [...current.filter((value) => value !== trackKey), trackKey]);
  };

  const handleAtlasSourcesToggle = (
    event: MouseEvent<HTMLButtonElement>,
    trackKey: string,
  ) => {
    const card = event.currentTarget.closest(".track-card") as HTMLElement | null;
    const isOpen = openAtlasSources.includes(trackKey);

    if (isOpen) {
      setOpenAtlasSources((current) => current.filter((value) => value !== trackKey));
      clearAtlasCardStyle(trackKey);
      return;
    }

    setAtlasCardStyle(trackKey, buildAtlasOpenCardStyle(card, "source"));
    setOpenAtlasSpotify((current) => current.filter((value) => value !== trackKey));
    setOpenAtlasSources((current) => [...current.filter((value) => value !== trackKey), trackKey]);
  };

  const recurringQuery = normalizeSearchText(deferredRecSearch);
  const visibleRecurringCards = recurringCards
    .filter((track) => {
      if (track.appearances < recMin) {
        return false;
      }

      if (!trackMatchesConfidence(track.confidenceCounts, recFilter)) {
        return false;
      }

      return recurringQuery ? track.searchBlob.includes(recurringQuery) : true;
    })
    .sort((left, right) => {
      if (right.appearances !== left.appearances) {
        return right.appearances - left.appearances;
      }

      return `${left.artist} - ${left.title}`.localeCompare(`${right.artist} - ${right.title}`);
    });

  const atlasSetQuery = normalizeSearchText(deferredAtlasSetSearch);
  const visibleAtlasSetCards = setCards.filter((setItem) =>
    atlasSetQuery ? setItem.searchBlob.includes(atlasSetQuery) : true,
  );
  const effectiveAtlasSelectedIds = useMemo(() => {
    if (atlasScope === "artist") {
      return [];
    }

    const visibleAtlasSetIdSet = new Set(visibleAtlasSetCards.map((setItem) => setItem.id));
    const visibleSelectedIds = atlasSelectedSetIds.filter((setId) => visibleAtlasSetIdSet.has(setId));

    if (visibleSelectedIds.length > 0) {
      return visibleSelectedIds;
    }

    return visibleAtlasSetCards[0] ? [visibleAtlasSetCards[0].id] : [];
  }, [atlasScope, atlasSelectedSetIds, visibleAtlasSetCards]);
  const scopedAtlasSetIds = new Set(
    atlasScope === "artist"
      ? visibleAtlasSetCards.map((setItem) => setItem.id)
      : effectiveAtlasSelectedIds,
  );
  const allScopedAtlasTracks = atlasTracks.filter((track) => {
    if (!scopedAtlasSetIds.has(track.setId)) {
      return false;
    }

    return true;
  });
  const filteredAtlasTracks =
    atlasConf === "all"
      ? allScopedAtlasTracks
      : allScopedAtlasTracks.filter((track) => track.confidence === atlasConf);
  const atlasRowsAll = buildAtlasRows({
    lens: atlasLens,
    mode: atlasCompareMode,
    query: deferredAtlasQuery,
    scope: atlasScope,
    selectedSetIds: scopedAtlasSetIds,
    sort: atlasSort,
    threshold: atlasMin,
    tracks: filteredAtlasTracks,
  });
  const atlasThresholdValues = getAtlasThresholdValues(
    buildAtlasRows({
      lens: atlasLens,
      mode: atlasCompareMode,
      query: "",
      scope: atlasScope,
      selectedSetIds: scopedAtlasSetIds,
      sort: "count",
      threshold: 1,
      tracks: allScopedAtlasTracks,
    }),
  );
  const maxAtlasPage = Math.max(0, Math.ceil(atlasRowsAll.length / ATLAS_PAGE_SIZE) - 1);
  const currentAtlasPage = clamp(atlasPage, 0, maxAtlasPage);
  const atlasPageRows = atlasRowsAll.slice(
    currentAtlasPage * ATLAS_PAGE_SIZE,
    currentAtlasPage * ATLAS_PAGE_SIZE + ATLAS_PAGE_SIZE,
  );
  const effectiveAtlasActiveName =
    atlasRowsAll.find((row) => row.name === atlasActiveName)?.name ?? null;
  const activeAtlasRow = atlasRowsAll.find((row) => row.name === effectiveAtlasActiveName) ?? null;
  const evidenceTracks = activeAtlasRow?.tracks ?? [];

  const setQuery = normalizeSearchText(deferredSetSearch);
  const filteredSetCards = [...setCards]
    .filter((setItem) => (setQuery ? setItem.searchBlob.includes(setQuery) : true))
    .sort((left, right) => {
      if (setSort === "rate") {
        return Number(right.recognitionRate ?? 0) - Number(left.recognitionRate ?? 0);
      }
      if (setSort === "tracks") {
        return right.totalTracks - left.totalTracks;
      }
      if (setSort === "duration") {
        return right.duration - left.duration;
      }
      return 0;
    });
  const maxSetPage = Math.max(0, Math.ceil(filteredSetCards.length / SETS_PAGE_SIZE) - 1);
  const currentSetPage = clamp(setPage, 0, maxSetPage);
  const visibleSetCards = filteredSetCards.slice(
    currentSetPage * SETS_PAGE_SIZE,
    currentSetPage * SETS_PAGE_SIZE + SETS_PAGE_SIZE,
  );
  const compareCards = compareSelection
    .map(
      (setId) =>
        filteredSetCards.find((setItem) => setItem.id === setId) ??
        setCards.find((setItem) => setItem.id === setId),
    )
    .filter((value): value is SetCardModel => Boolean(value));
  const sharedTrackNames =
    compareCards.length === 2
      ? [...compareCards[0].trackKeySet].filter((trackKey) => compareCards[1].trackKeySet.has(trackKey))
      : [];
  const compareMetrics =
    compareCards.length === 2
      ? (() => {
          const union = new Set([...compareCards[0].trackKeySet, ...compareCards[1].trackKeySet]);
          return {
            durationDelta: Math.abs(compareCards[0].duration - compareCards[1].duration),
            onlyA: Math.max(0, compareCards[0].trackKeySet.size - sharedTrackNames.length),
            onlyB: Math.max(0, compareCards[1].trackKeySet.size - sharedTrackNames.length),
            overlapPct: union.size > 0 ? Math.round((sharedTrackNames.length / union.size) * 100) : 0,
            rateDelta: Math.abs(Number(compareCards[0].recognitionRate ?? 0) - Number(compareCards[1].recognitionRate ?? 0)),
            sharedCount: sharedTrackNames.length,
          };
        })()
      : null;
  const sharedTrackKeySet = new Set(sharedTrackNames);
  const visibleDockedAtlasSetCards = visibleAtlasSetCards.filter((setItem) =>
    atlasDockedSelectedSetIds.includes(setItem.id),
  );
  const dockSelectedAtlasCards =
    atlasScope !== "artist" && visibleDockedAtlasSetCards.length > 0;
  const orderedAtlasSetCards = dockSelectedAtlasCards
    ? [
        ...visibleDockedAtlasSetCards,
        ...visibleAtlasSetCards.filter((setItem) => !atlasDockedSelectedSetIds.includes(setItem.id)),
      ]
    : visibleAtlasSetCards;
  const selectedAtlasSet =
    effectiveAtlasSelectedIds.length === 1
      ? setCards.find((setItem) => setItem.id === effectiveAtlasSelectedIds[0]) ?? null
      : null;
  const allVisibleAtlasSetIds = visibleAtlasSetCards.map((setItem) => setItem.id);
  const allVisibleAtlasSetsSelected =
    allVisibleAtlasSetIds.length > 0 &&
    allVisibleAtlasSetIds.every((setId) => atlasSelectedSetIds.includes(setId));
  const clearAtlasSelectionId = effectiveAtlasSelectedIds[0] ?? visibleAtlasSetCards[0]?.id ?? null;
  const focusHeading =
    effectiveAtlasSelectedIds.length > 1
      ? `${effectiveAtlasSelectedIds.length} Sets Selected`
      : selectedAtlasSet?.title ?? "No Set Selected";
  const focusHeadingLayout = splitSetAtlasHeadingTwoLines(focusHeading);
  const focusSummary =
    effectiveAtlasSelectedIds.length <= 1
      ? "Single set focus. Select all or add another set card to compare overlap."
      : `${effectiveAtlasSelectedIds.length} sets in scope. ${atlasCompareMode === "intersection" ? "Intersection" : "Union"} mode active.`;
  const maxAtlasCount = atlasPageRows.length
    ? Math.max(...atlasPageRows.map((row) => row.count))
    : 1;
  const trackLensUniverse = buildAtlasRows({
    lens: "tracks",
    mode: atlasCompareMode,
    query: deferredAtlasQuery,
    scope: atlasScope,
    selectedSetIds: scopedAtlasSetIds,
    sort: atlasSort,
    threshold: atlasMin,
    tracks: allScopedAtlasTracks,
  });
  const trackLensCountLabel =
    atlasConf === "all"
      ? `${atlasRowsAll.length} matching tracks`
      : `${atlasRowsAll.length} / ${trackLensUniverse.length} matching tracks`;

  useEffect(() => {
    latestAtlasSelectedSetIdsRef.current = atlasSelectedSetIds;
  }, [atlasSelectedSetIds]);

  useEffect(() => {
    if (atlasPanePointerInside || !pendingAtlasRailResetRef.current) {
      return;
    }

    pendingAtlasRailResetRef.current = false;
    const rail = atlasRailRef.current;
    if (!rail) {
      return;
    }

    let frame = window.requestAnimationFrame(() => {
      frame = window.requestAnimationFrame(() => {
        rail.scrollTo({
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
  }, [atlasDockedSelectedSetIds, atlasPanePointerInside]);

  useEffect(() => {
    setSetPage((current) => Math.min(current, maxSetPage));
  }, [maxSetPage]);

  const jumpToSetExplorer = () => {
    document.getElementById("sets-section")?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  };

  useEffect(() => {
    if (!pendingSetExplorerJumpRef.current) {
      return;
    }

    let outerFrame = 0;
    let innerFrame = 0;

    outerFrame = window.requestAnimationFrame(() => {
      innerFrame = window.requestAnimationFrame(() => {
        pendingSetExplorerJumpRef.current = false;
        jumpToSetExplorer();
      });
    });

    return () => {
      if (outerFrame) {
        window.cancelAnimationFrame(outerFrame);
      }
      if (innerFrame) {
        window.cancelAnimationFrame(innerFrame);
      }
    };
  }, [currentSetPage]);

  return (
    <div className={styles.root}>
      <ArchiveScrollRoot />
      <ArchiveHeader
        navLinks={[
          { label: "Recurring", href: "#recurring-section" },
          { label: "Set Atlas", href: "#set-atlas-section" },
          { label: "Set Explorer", href: "#sets-section" },
          { label: "Status", href: "#status-section" },
        ]}
      />

      <main className="shell">
        <section className="section" id="overview">
          <div className="section-inner">
            <div className="kicker">Artist Intelligence Deck</div>
            <div className="artist-hero">
              <div className="artist-hero-main" ref={heroMainRef}>
                <div className="artist-hero-visual" ref={heroVisualRef}>
                  {heroVisualImageUrl ? (
                    <img alt={`${artist.name} artist image`} src={heroVisualImageUrl} />
                  ) : (
                    <div className="artist-hero-image-fallback" />
                  )}
                  <h1 className="artist-hero-title" ref={heroTitleRef}>
                    {artist.name.split(/\s+/u).map((word) => (
                      <span key={word}>{word}</span>
                    ))}
                  </h1>
                </div>
                <div className="stats-grid artist-hero-stats">
                  <article className="stat">
                    <span className="stat-value">{artist.stats.setsAnalyzed}</span>
                    <span className="stat-label">Sets analyzed</span>
                  </article>
                  <article className="stat">
                    <span className="stat-value">{artist.stats.uniqueTracks}</span>
                    <span className="stat-label">Unique tracks</span>
                  </article>
                  <article className="stat">
                    <span className="stat-value">{artist.stats.totalDetections}</span>
                    <span className="stat-label">Total detections</span>
                  </article>
                  <article className="stat">
                    <span className="stat-value">{artist.stats.recurringTracks}</span>
                    <span className="stat-label">Recurring tracks</span>
                  </article>
                </div>
              </div>

              <aside className="artist-hero-side" ref={heroSideRef}>
                <div className="artist-hero-side-viewport" ref={heroRailViewportRef}>
                  <div className="artist-hero-side-track" ref={heroRailTrackRef}>
                    {heroRail.map((setItem, index) => (
                      <a className="artist-hero-card" href={setItem.previewHref} key={`${setItem.id}:${index}`} rel="noopener" target="_blank">
                        {setItem.heroImageUrl ? (
                          <img alt={setItem.title} src={setItem.heroImageUrl} />
                        ) : (
                          <div className="artist-hero-card-fallback">No Image</div>
                        )}
                        <div className="artist-hero-card-meta">
                          <p className="artist-hero-card-match">{setItem.matchLabel.toLowerCase()}</p>
                          <p className="artist-hero-card-title">{setItem.title}</p>
                          <p className="artist-hero-card-sub">{formatHeroSetSummary(setItem)}</p>
                        </div>
                      </a>
                    ))}
                  </div>
                </div>
              </aside>
            </div>
          </div>
        </section>

        <section className="section" id="recurring-section">
          <div className="section-inner">
            <div className="section-head">
              <h2 className="recurring-heading">Recurring Tracks</h2>
              <p>
                Index-style track cards with set evidence and source deep links. Threshold and search
                controls are available below.
              </p>
            </div>

            <div className="recurring-controls">
              <div className="recurring-toolbar">
                <input
                  aria-label="Search recurring tracks"
                  className={joinClasses("input", "recurring-search-input")}
                  onChange={(event) => {
                    const next = event.target.value;
                    startTransition(() => {
                      setRecSearch(next);
                    });
                  }}
                  placeholder="Search recurring tracks..."
                  type="search"
                  value={recSearch}
                />

                <div className="controls-row recurring-filter-row">
                  <div className="threshold-stepper">
                    <button
                      aria-label="Decrease recurring set threshold"
                      className="btn threshold-arrow"
                      disabled={recMin === recurringThresholdValues[0]}
                      onClick={() => setRecMin((current) => stepThresholdValue(current, recurringThresholdValues, -1))}
                      type="button"
                    >
                      ▼
                    </button>
                    <span className="btn threshold-value">{recMin}+ SETS</span>
                    <button
                      aria-label="Increase recurring set threshold"
                      className="btn threshold-arrow"
                      disabled={recMin === recurringThresholdValues[recurringThresholdValues.length - 1]}
                      onClick={() => setRecMin((current) => stepThresholdValue(current, recurringThresholdValues, 1))}
                      type="button"
                    >
                      ▲
                    </button>
                  </div>

                  {TRACK_CONFIDENCE_LEVELS.map((filter) => (
                    <button
                      className={joinClasses("btn", recFilter === filter && "active")}
                      key={filter}
                      onClick={() => setRecFilter(filter)}
                      type="button"
                    >
                      {filter === "all" ? "All" : filter.charAt(0) + filter.slice(1).toLowerCase()}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="recurring-grid">
              {visibleRecurringCards.map((track) => {
                const visibleSetRefs = track.setRefs.filter((setRef) =>
                  recFilter === "all" ? true : setRef.confidence === recFilter,
                );
                const hasSources = visibleSetRefs.length > 0;
                const sourcesOpen = openRecurringSources.includes(track.trackKey);
                const spotifyOpen = openRecurringSpotify.includes(track.trackKey);

                return (
                  <ArchiveEvidenceTrackCard
                    albumArt={track.albumArt}
                    cardClassName="rec-card"
                    confidence={getPrimaryConfidenceFromCounts(track.confidenceCounts)}
                    dataTrackKey={track.trackKey}
                    key={track.trackKey}
                    openState={{
                      sourcesOpen,
                      spotifyOpen,
                    }}
                    onToggleSources={(event) => handleRecurringSourcesToggle(event, track.trackKey)}
                    onToggleSpotify={(event) => handleRecurringSpotifyToggle(event, track.trackKey)}
                    sourceGroups={buildArtistTrackSourceGroups(
                      track.trackKey,
                      visibleSetRefs.map((setRef) => ({
                        href: setRef.href,
                        label: setRef.setTitle,
                      })),
                    )}
                    sourceLabel={hasSources ? `Sets (${visibleSetRefs.length})` : null}
                    spotifyTrackId={track.spotifyTrackId}
                    style={recurringCardStyles[track.trackKey]}
                    title={track.title}
                    titlePrefix={`${track.artist} - `}
                  />
                );
              })}
            </div>

            {visibleRecurringCards.length === 0 ? (
              <div className="no-results">No recurring tracks match the active threshold/filter.</div>
            ) : null}
          </div>
        </section>

        <section className="section" id="set-atlas-section" style={{ position: "relative" }}>
          <div className="set-atlas-actions" style={{ display: "flex", gap: 8, position: "absolute", right: 24, top: 18, zIndex: 500 }}>
            <SpotifyExportButton
              counts={spotifyExportCounts}
              entityType="artist"
              scope={scope}
              slug={artist.slug}
            />
            <InlineSubmitButton mode="add-sets" artistName={artist.name} />
          </div>
          <div className="section-inner">
            <div className="section-head">
              <h2>Set Atlas</h2>
              <p>Pick a set on the left, then investigate genres, labels, track artists, and tracks with evidence in the right pane.</p>
            </div>

            <div className="atlas-layout">
              <div className="atlas-set-pane">
                <div className="controls-grid set-controls-inline">
                  <div className="control">
                    <label htmlFor="atlasSetSearch">Search Sets</label>
                    <input
                      className="input"
                      id="atlasSetSearch"
                      onChange={(event) => {
                        const next = event.target.value;
                        startTransition(() => {
                          setAtlasSetSearch(next);
                          setAtlasPage(0);
                          setAtlasEvidencePage(0);
                          setAtlasActiveName(null);
                        });
                      }}
                      placeholder="find set cards"
                      type="text"
                      value={atlasSetSearch}
                    />
                  </div>
                </div>

                <div
                  className={joinClasses(
                    "artist-grid",
                    "atlas-set-grid",
                    dockSelectedAtlasCards && "selected-dock",
                  )}
                  onPointerEnter={(event) => {
                    if (!isHoverCapablePointer()) {
                      return;
                    }
                    setAtlasPanePointerInside(true);
                    event.currentTarget.scrollTo({ top: 0, behavior: "auto" });
                  }}
                  onPointerMove={(event) => {
                    if (!isHoverCapablePointer()) {
                      return;
                    }
                    setAtlasPanePointerInside(true);
                    if (!atlasHoverLatchedSetId) {
                      return;
                    }
                    const target = event.target;
                    const card = target instanceof Element ? target.closest(".atlas-set-card") : null;
                    const hoveredSetId =
                      card instanceof HTMLElement ? card.dataset.atlasSetId ?? null : null;
                    if (hoveredSetId === atlasHoverLatchedSetId) {
                      return;
                    }
                    setAtlasHoverLatchedSetId(null);
                  }}
                  onPointerLeave={() => {
                    if (isHoverCapablePointer()) {
                      setAtlasPanePointerInside(false);
                    }
                    setAtlasHoverLatchedSetId(null);
                    setAtlasDockedSelectedSetIds(latestAtlasSelectedSetIdsRef.current);
                    pendingAtlasRailResetRef.current = true;
                  }}
                  ref={atlasRailRef}
                >
                  {orderedAtlasSetCards.map((setItem, index) => {
                    const isSelected = effectiveAtlasSelectedIds.includes(setItem.id);

                    return (
                      <article
                        className={joinClasses(
                          "artist-card",
                          "atlas-set-card",
                          effectiveAtlasSelectedIds[0] === setItem.id && "focus",
                          isSelected && "selected",
                          atlasHoverLatchedSetId === setItem.id && "hover-latched",
                        )}
                        data-atlas-set-id={setItem.id}
                        key={setItem.id}
                        onClick={(event) => {
                          if ((event.target as HTMLElement).closest("a,button")) {
                            return;
                          }

                          const additive = event.shiftKey || event.metaKey || event.ctrlKey;
                          const hoverCapable = isHoverCapablePointer();
                          const nextSelectedIds = additive
                            ? toggleSelectedSetIds(atlasSelectedSetIds, setItem.id)
                            : [setItem.id];
                          latestAtlasSelectedSetIdsRef.current = nextSelectedIds;
                          if (!atlasPanePointerInside) {
                            setAtlasDockedSelectedSetIds(nextSelectedIds);
                          }
                          setAtlasHoverLatchedSetId(hoverCapable ? setItem.id : null);
                          setAtlasScope("set");
                          setAtlasPage(0);
                          setAtlasEvidencePage(0);
                          setAtlasActiveName(null);
                          setAtlasSelectedSetIds(nextSelectedIds);
                        }}
                        role="button"
                        style={{ zIndex: orderedAtlasSetCards.length - index }}
                        tabIndex={0}
                        onKeyDown={(event) => {
                          if (event.key !== "Enter" && event.key !== " ") {
                            return;
                          }
                          event.preventDefault();
                          const nextSelectedIds = [setItem.id];
                          latestAtlasSelectedSetIdsRef.current = nextSelectedIds;
                          if (!atlasPanePointerInside) {
                            setAtlasDockedSelectedSetIds(nextSelectedIds);
                          }
                          setAtlasHoverLatchedSetId(null);
                          setAtlasScope("set");
                          setAtlasPage(0);
                          setAtlasEvidencePage(0);
                          setAtlasActiveName(null);
                          setAtlasSelectedSetIds(nextSelectedIds);
                        }}
                      >
                        {setItem.heroImageUrl ? (
                          <img alt={setItem.title} loading="lazy" src={setItem.heroImageUrl} />
                        ) : (
                          <div className="set-card-fallback" aria-hidden="true" />
                        )}
                        <div className="artist-detail">
                          <div className="artist-meta-row">
                            <div className="card-actions">
                              <button
                                className={joinClasses("chip-btn", isSelected && "active")}
                                onClick={(event) => {
                                  event.preventDefault();
                                  event.stopPropagation();
                                  const hoverCapable = isHoverCapablePointer();
                                  const nextSelectedIds = toggleSelectedSetIds(
                                    atlasSelectedSetIds,
                                    setItem.id,
                                  );
                                  latestAtlasSelectedSetIdsRef.current = nextSelectedIds;
                                  if (!atlasPanePointerInside) {
                                    setAtlasDockedSelectedSetIds(nextSelectedIds);
                                  }
                                  setAtlasHoverLatchedSetId(hoverCapable ? setItem.id : null);
                                  setAtlasScope("set");
                                  setAtlasPage(0);
                                  setAtlasEvidencePage(0);
                                  setAtlasActiveName(null);
                                  setAtlasSelectedSetIds(nextSelectedIds);
                                }}
                                type="button"
                              >
                                {isSelected ? "In Scope" : "Add to Scope"}
                              </button>
                              <a className="chip-btn" href={setItem.previewHref} rel="noopener" target="_blank">
                                Set Page
                              </a>
                              {setItem.sourceUrl ? (
                                <a className="chip-btn" href={setItem.sourceUrl} rel="noopener" target="_blank">
                                  Source
                                </a>
                              ) : null}
                            </div>
                          </div>
                          <h3>{setItem.title}</h3>
                          <p>{formatSetSummary(setItem)}</p>
                        </div>
                      </article>
                    );
                  })}
                </div>

                {visibleAtlasSetCards.length === 0 ? (
                  <div className="no-results">No sets match current filters.</div>
                ) : null}
              </div>

              <aside className="atlas-panel">
                <div className="focus-header">
                  <div className={joinClasses("focus-names", "single", focusHeadingLayout.sizeClass)}>
                    <span className="focus-name">
                      <span className="focus-line">{focusHeadingLayout.line1}</span>
                      <span className="focus-line">{focusHeadingLayout.line2}</span>
                    </span>
                  </div>
                  <div className="focus-toolbar">
                    <p className="focus-summary">{focusSummary}</p>
                    <div className="focus-mode">
                      {effectiveAtlasSelectedIds.length > 1 ? (
                        <>
                          <button
                            className={joinClasses("chip-btn", atlasCompareMode === "union" && "active")}
                            onClick={() => {
                              setAtlasCompareMode("union");
                              setAtlasPage(0);
                              setAtlasEvidencePage(0);
                              setAtlasActiveName(null);
                            }}
                            type="button"
                          >
                            Union
                          </button>
                          <button
                            className={joinClasses("chip-btn", atlasCompareMode === "intersection" && "active")}
                            onClick={() => {
                              setAtlasCompareMode("intersection");
                              setAtlasPage(0);
                              setAtlasEvidencePage(0);
                              setAtlasActiveName(null);
                            }}
                            type="button"
                          >
                            Intersection
                          </button>
                          <button
                            className={joinClasses("chip-btn", allVisibleAtlasSetsSelected && "active")}
                            onClick={() => {
                              latestAtlasSelectedSetIdsRef.current = allVisibleAtlasSetIds;
                              if (!atlasPanePointerInside) {
                                setAtlasDockedSelectedSetIds(allVisibleAtlasSetIds);
                              }
                              setAtlasScope("set");
                              setAtlasSelectedSetIds(allVisibleAtlasSetIds);
                              setAtlasPage(0);
                              setAtlasEvidencePage(0);
                              setAtlasActiveName(null);
                            }}
                            type="button"
                          >
                            Select All
                          </button>
                          <button
                            className="chip-btn"
                            onClick={() => {
                              if (!clearAtlasSelectionId) {
                                return;
                              }
                              const nextSelectedIds = [clearAtlasSelectionId];
                              latestAtlasSelectedSetIdsRef.current = nextSelectedIds;
                              if (!atlasPanePointerInside) {
                                setAtlasDockedSelectedSetIds(nextSelectedIds);
                              }
                              setAtlasScope("set");
                              setAtlasSelectedSetIds(nextSelectedIds);
                              setAtlasPage(0);
                              setAtlasEvidencePage(0);
                              setAtlasActiveName(null);
                            }}
                            type="button"
                          >
                            Clear
                          </button>
                        </>
                      ) : (
                        <button
                          className={joinClasses("chip-btn", allVisibleAtlasSetsSelected && "active")}
                          onClick={() => {
                            latestAtlasSelectedSetIdsRef.current = allVisibleAtlasSetIds;
                            if (!atlasPanePointerInside) {
                              setAtlasDockedSelectedSetIds(allVisibleAtlasSetIds);
                            }
                            setAtlasScope("set");
                            setAtlasSelectedSetIds(allVisibleAtlasSetIds);
                            setAtlasPage(0);
                            setAtlasEvidencePage(0);
                            setAtlasActiveName(null);
                          }}
                          type="button"
                        >
                          Select All
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="focus-stats">
                    <article className="focus-tile">
                      <p>Sets</p>
                      <h4>{scopedAtlasSetIds.size}</h4>
                    </article>
                    <article className="focus-tile">
                      <p>Unique Tracks</p>
                      <h4>{new Set(allScopedAtlasTracks.map((track) => track.trackKey)).size}</h4>
                    </article>
                    <article className="focus-tile">
                      <p>Detections</p>
                      <h4>{allScopedAtlasTracks.length}</h4>
                    </article>
                    <article className="focus-tile">
                      <p>Scope</p>
                      <h4>{atlasScope === "artist" ? "Artist" : "Set"}</h4>
                    </article>
                  </div>
                </div>

                <div className="taxonomy-workbench">
                  <ArchiveTaxonomyPanel
                    className="taxonomy-panel"
                    confidenceFilters={TRACK_CONFIDENCE_LEVELS.map((filter) => ({
                      active: atlasConf === filter,
                      id: filter,
                      label: filter === "all" ? `All (${allScopedAtlasTracks.length})` : filter,
                      onSelect: () => {
                        setAtlasConf(filter);
                        setAtlasPage(0);
                        setAtlasEvidencePage(0);
                        setAtlasActiveName(null);
                      },
                    }))}
                    lensOptions={(["genres", "labels", "artists", "tracks"] as const).map((lens) => ({
                      active: atlasLens === lens,
                      id: lens,
                      label:
                        lens === "genres"
                          ? "Genres"
                          : lens === "labels"
                            ? "Labels"
                            : lens === "artists"
                              ? "Artists"
                              : "Tracks",
                    }))}
                    onLensChange={(lensId) => {
                      setAtlasLens(lensId as AtlasLens);
                      setAtlasPage(0);
                      setAtlasEvidencePage(0);
                      setAtlasActiveName(null);
                    }}
                    pager={
                      atlasLens !== "tracks" ? (
                        <div className="pager">
                          <button
                            className="btn"
                            disabled={currentAtlasPage === 0}
                            onClick={() => setAtlasPage((current) => Math.max(0, current - 1))}
                            type="button"
                          >
                            Prev
                          </button>
                          <span>
                            Page {currentAtlasPage + 1} / {Math.max(1, maxAtlasPage + 1)}
                          </span>
                          <button
                            className="btn"
                            disabled={currentAtlasPage >= maxAtlasPage}
                            onClick={() => setAtlasPage((current) => Math.min(maxAtlasPage, current + 1))}
                            type="button"
                          >
                            Next
                          </button>
                        </div>
                      ) : null
                    }
                    search={{
                      onChange: (value) => {
                        startTransition(() => {
                          setAtlasQuery(value);
                          setAtlasPage(0);
                          setAtlasEvidencePage(0);
                          setAtlasActiveName(null);
                        });
                      },
                      placeholder: "search",
                      value: atlasQuery,
                    }}
                    sort={{
                      ariaLabel: "Sort taxonomy entries",
                      onChange: (value) => {
                        setAtlasSort((value as "alpha" | "count") ?? "count");
                        setAtlasPage(0);
                        setAtlasEvidencePage(0);
                      },
                      options: [
                        { label: "HIGHEST USAGE", value: "count" },
                        { label: "ALPHABETICAL", value: "alpha" },
                      ],
                      value: atlasSort,
                    }}
                    threshold={{
                      canDecrease: atlasMin !== atlasThresholdValues[0],
                      canIncrease: atlasMin !== atlasThresholdValues[atlasThresholdValues.length - 1],
                      decreaseLabel: "Decrease set threshold",
                      increaseLabel: "Increase set threshold",
                      onDecrease: () => {
                        setAtlasMin((current) => stepThresholdValue(current, atlasThresholdValues, -1));
                        setAtlasPage(0);
                        setAtlasEvidencePage(0);
                        setAtlasActiveName(null);
                      },
                      onIncrease: () => {
                        setAtlasMin((current) => stepThresholdValue(current, atlasThresholdValues, 1));
                        setAtlasPage(0);
                        setAtlasEvidencePage(0);
                        setAtlasActiveName(null);
                      },
                      valueLabel: `${atlasMin}+ SETS`,
                    }}
                    title="Taxonomy Atlas"
                  >
                      {atlasLens === "tracks"
                        ? null
                        : atlasPageRows.map((row) => {
                            const isActive = effectiveAtlasActiveName === row.name;

                            return (
                              <article className={joinClasses("quant-row", isActive && "active")} key={row.name}>
                                <button
                                  className="row-hit"
                                  onClick={() => {
                                    setAtlasActiveName((current) => (current === row.name ? null : row.name));
                                    setAtlasEvidencePage(0);
                                  }}
                                  type="button"
                                >
                                  <div className="row-line">
                                    <span className="row-name" title={row.name}>
                                      {row.name}
                                    </span>
                                    <div className="bar">
                                      <span
                                        style={{
                                          width: `${maxAtlasCount > 0 ? (row.count / maxAtlasCount) * 100 : 0}%`,
                                        }}
                                      />
                                    </div>
                                    <span className="row-count">{row.count}</span>
                                  </div>
                                </button>
                                {isActive ? (
                                  <div className="inline-evidence">
                                    <div className="inline-head-row">
                                      <p className="inline-head">{`${row.name} | ${row.tracks.length} matching tracks`}</p>
                                      {atlasLens === "labels" && row.labelUrl ? (
                                        <div className="inline-head-actions">
                                          <a className="discogs" href={row.labelUrl} rel="noopener" target="_blank">
                                            Label Page
                                          </a>
                                        </div>
                                      ) : null}
                                    </div>
                                    {evidenceTracks.length > 0 ? (
                                      <div className="evidence-grid">
                                        {evidenceTracks.map((track) => {
                                          const trackKey = track.trackKey;
                                          const sourcesOpen = openAtlasSources.includes(trackKey);
                                          const spotifyOpen = openAtlasSpotify.includes(trackKey);

                                          return (
                                            <ArchiveEvidenceTrackCard
                                              albumArt={track.albumArt}
                                              cardClassName="atlas-track-card"
                                              confidence={track.confidence}
                                              dataTrackKey={trackKey}
                                              key={trackKey}
                                              openState={{
                                                sourcesOpen,
                                                spotifyOpen,
                                              }}
                                              onToggleSources={(event) => handleAtlasSourcesToggle(event, trackKey)}
                                              onToggleSpotify={(event) => handleAtlasSpotifyToggle(event, trackKey)}
                                              sourceGroups={buildArtistTrackSourceGroups(trackKey, track.setLinks)}
                                              sourceLabel={`Sets (${track.setLinks.length})`}
                                              spotifyTrackId={track.spotifyTrackId}
                                              style={atlasCardStyles[trackKey]}
                                              title={track.title}
                                              titlePrefix={`${track.artist} - `}
                                            />
                                          );
                                        })}
                                      </div>
                                    ) : (
                                      <div className="empty">No evidence tracks match the selected confidence filter.</div>
                                    )}
                                  </div>
                                ) : null}
                              </article>
                            );
                          })}

                    {atlasLens === "tracks" && atlasRowsAll.length > 0 ? (
                      <div className="inline-evidence">
                        <p className="inline-head">{`Tracks | ${trackLensCountLabel}`}</p>
                        <div className="evidence-grid">
                          {atlasRowsAll.map((row) => {
                            const track = row.tracks[0];
                            if (!track) {
                              return null;
                            }

                            const trackKey = track.trackKey;
                            const sourcesOpen = openAtlasSources.includes(trackKey);
                            const spotifyOpen = openAtlasSpotify.includes(trackKey);

                            return (
                              <ArchiveEvidenceTrackCard
                                albumArt={track.albumArt}
                                cardClassName="atlas-track-card"
                                confidence={track.confidence}
                                dataTrackKey={trackKey}
                                key={trackKey}
                                openState={{
                                  sourcesOpen,
                                  spotifyOpen,
                                }}
                                onToggleSources={(event) => handleAtlasSourcesToggle(event, trackKey)}
                                onToggleSpotify={(event) => handleAtlasSpotifyToggle(event, trackKey)}
                                sourceGroups={buildArtistTrackSourceGroups(trackKey, track.setLinks)}
                                sourceLabel={`Sets (${track.setLinks.length})`}
                                spotifyTrackId={track.spotifyTrackId}
                                style={atlasCardStyles[trackKey]}
                                title={track.title}
                                titlePrefix={`${track.artist} - `}
                              />
                            );
                          })}
                        </div>
                      </div>
                    ) : null}

                    {atlasRowsAll.length === 0 ? (
                      <div className="no-results">No taxonomy entries match current controls.</div>
                    ) : null}
                  </ArchiveTaxonomyPanel>
                </div>
              </aside>
            </div>
          </div>
        </section>

        <section className="section" id="sets-section" style={{ position: "relative" }}>
          <div style={{ position: "absolute", top: 18, right: 24, zIndex: 500 }}>
            <InlineSubmitButton mode="add-sets" artistName={artist.name} />
          </div>
          <div className="section-inner">
            <div className="section-head">
              <h2>Set Explorer</h2>
              <p>Search and compare sets, then inspect shared tracks through expanded tracklists and deep links.</p>
            </div>

            <div className="set-panel">
              <div className="controls-grid set-controls-inline set-explorer-controls">
                <div className="control">
                  <input
                    aria-label="Search sets"
                    className="input"
                    id="setSearch"
                    onChange={(event) => {
                      const next = event.target.value;
                      startTransition(() => {
                        setSetPage(0);
                        setSetSearch(next);
                      });
                    }}
                    placeholder="set title, track"
                    type="text"
                    value={setSearch}
                  />
                </div>
                <div className="control">
                  <select
                    aria-label="Sort sets"
                    id="setSort"
                    onChange={(event) => {
                      setSetPage(0);
                      setSetSort((event.target.value as SetSort) ?? "default");
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

              <div className="compare-panel" hidden={compareSelection.length === 0}>
                <div className="controls-row compare-head">
                  <strong>Set Connection View</strong>
                  <button
                    className="btn"
                    onClick={() => setCompareSelection([])}
                    type="button"
                  >
                    Clear
                  </button>
                </div>
                <div className="compare-body">
                  {compareSelection.length === 1 ? (
                    <div>1 set selected. Choose one more to compare.</div>
                  ) : compareCards.length < 2 ? (
                    <div>Select two sets to compare overlap.</div>
                  ) : (
                    <div className="compare-stack">
                      <div className="compare-summary">
                        {compareCards[0].title} {"<->"} {compareCards[1].title}
                      </div>
                      <div className="compare-grid">
                        <div className="compare-card">
                          <span className="compare-value">{compareMetrics?.sharedCount ?? 0}</span>
                          <span className="compare-label">Shared tracks</span>
                        </div>
                        <div className="compare-card">
                          <span className="compare-value">{compareMetrics?.overlapPct ?? 0}%</span>
                          <span className="compare-label">Overlap</span>
                        </div>
                        <div className="compare-card">
                          <span className="compare-value">{Math.round(compareMetrics?.rateDelta ?? 0)}%</span>
                          <span className="compare-label">ID delta</span>
                        </div>
                        <div className="compare-card">
                          <span className="compare-value">{Math.round((compareMetrics?.durationDelta ?? 0) / 60)}m</span>
                          <span className="compare-label">Duration delta</span>
                        </div>
                        <div className="compare-card">
                          <span className="compare-value">{compareMetrics?.onlyA ?? 0}</span>
                          <span className="compare-label">Only in A</span>
                        </div>
                        <div className="compare-card">
                          <span className="compare-value">{compareMetrics?.onlyB ?? 0}</span>
                          <span className="compare-label">Only in B</span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="set-grid">
                {visibleSetCards.map((setItem) => {
                  const isCompared = compareSelection.includes(setItem.id);
                  const isExpanded = expandedSetCards.includes(setItem.id);
                  const miniSegments = buildMiniTimeline(setItem);

                  return (
                    <ArchiveSetCard
                      actions={[
                        {
                          key: `compare:${setItem.id}`,
                          label: "Compare",
                          onClick: () =>
                            setCompareSelection((current) => {
                              if (current.includes(setItem.id)) {
                                return current.filter((value) => value !== setItem.id);
                              }
                              if (current.length >= 2) {
                                return [current[1], setItem.id];
                              }
                              return [...current, setItem.id];
                            }),
                        },
                      ]}
                      imageAlt={setItem.title}
                      imageTarget="_blank"
                      imageUrl={setItem.heroImageUrl}
                      key={setItem.id}
                      metaPills={[
                        `${setItem.totalTracks} tracks`,
                        setItem.matchLabel,
                        setItem.durationFmt,
                      ]}
                      miniTimeline={miniSegments}
                      selected={isCompared}
                      setHref={setItem.previewHref}
                      sourceHref={setItem.sourceUrl}
                      title={setItem.title}
                      titleTarget="_blank"
                      toggleTracklist={() =>
                        setExpandedSetCards((current) =>
                          current.includes(setItem.id)
                            ? current.filter((value) => value !== setItem.id)
                            : [...current, setItem.id],
                        )
                      }
                      tracklist={setItem.visibleTracks.map((track) => ({
                        confidence: track.confidence,
                        href: buildTrackAnchorHref(setItem.slug, track.position),
                        id: `${setItem.id}:${track.position}`,
                        label: `${track.artist} - ${track.title}`,
                        shared: sharedTrackKeySet.has(normalizeSearchText(track.trackKey)),
                        startTimeFormatted: track.startTimeFormatted,
                        target: "_blank",
                      }))}
                      tracklistExpanded={isExpanded}
                    />
                  );
                })}
              </div>

              <div className="pager compact">
                <button
                  className="btn"
                  disabled={currentSetPage === 0}
                  onClick={() => {
                    pendingSetExplorerJumpRef.current = true;
                    setSetPage((current) => Math.max(0, current - 1));
                  }}
                  type="button"
                >
                  Prev
                </button>
                <span>
                  Page {currentSetPage + 1} / {Math.max(1, maxSetPage + 1)} | {filteredSetCards.length} sets
                </span>
                <button
                  className="btn"
                  disabled={currentSetPage >= maxSetPage}
                  onClick={() => {
                    pendingSetExplorerJumpRef.current = true;
                    setSetPage((current) => Math.min(maxSetPage, current + 1));
                  }}
                  type="button"
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        </section>

        <section className="section" id="status-section">
          <div className="section-inner">
            <div className="section-head">
              <h2>Collection Status</h2>
              <p>Visibility into failed set collection attempts for this artist.</p>
            </div>

            {artist.failedSets.length > 0 ? (
              <div className="status-list">
                {artist.failedSets.map((setItem) => (
                  <article className="status-card" key={`${setItem.title}:${setItem.url ?? ""}`}>
                    <h3>{setItem.title}</h3>
                    <p>{setItem.reason ?? "Collection failed for an unknown reason."}</p>
                    {setItem.url ? (
                      <a className="chip-btn" href={setItem.url} rel="noopener" target="_blank">
                        Open Source
                      </a>
                    ) : null}
                  </article>
                ))}
              </div>
            ) : (
              <div className="status-list">
                <div className="empty">No failed sets were recorded for this artist.</div>
              </div>
            )}

            <div className="footer-note">
              Generated {formatGeneratedAt(artist.generatedAt)} · Set Signal Explorer
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

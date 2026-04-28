/* eslint-disable @next/next/no-img-element */
"use client";

import { startTransition, useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { ArchiveDeleteControl, SubmittedByYouBadge } from "@/components/archive/archive-delete-control";
import { buildArtistHref } from "@/components/archive/archive-hrefs";
import { ArchiveHeader } from "@/components/archive/archive-header";
import { ArchiveScrollRoot } from "@/components/archive/archive-scroll-root";
import { SpotifyExportButton } from "@/components/archive/spotify-export-button";
import { buildSetSpotifyExportCounts } from "@/lib/archive/spotify-export";
import type {
  ArchiveConfidence,
  ArchiveJourneyPoint,
  ArchiveSetDetail,
  ArchiveSetSourceLink,
  ArchiveSetTrack,
} from "@/lib/archive/types";
import {
  buildDiscogsSearchUrl,
  buildSearchBlob,
  buildSpotifySearchUrl,
  buildYouTubeSearchUrl,
  extractSpotifyTrackId,
  extractYouTubeId,
  formatDuration,
  normalizeSearchText,
} from "@/lib/archive/utils";

import styles from "./archive-set-explorer.module.css";

type JourneyMetric = "bpm" | "energy" | "dance";
type ConfidenceFilter = ArchiveConfidence | "all";

type SetManagement = {
  canDeleteSet: boolean;
  deleteImpact: string | null;
  setWillBeRemoved: boolean;
  submittedByViewer: boolean;
};

type UiTrack = ArchiveSetTrack & {
  densityPct: number;
  directDiscogsUrl: string | null;
  directSpotifyUrl: string | null;
  directYouTubeUrl: string | null;
  discogsLinkLabel: string;
  discogsResolvedUrl: string;
  endResolved: number;
  endResolvedFmt: string;
  isUnknownTrack: boolean;
  searchBlob: string;
  spotifyLinkLabel: string;
  spotifyResolvedUrl: string;
  spotifyTrackId: string | null;
  timeRange: string;
  youtubeLinkLabel: string;
  youtubeResolvedUrl: string;
};

type HeroCard = {
  artist: string;
  idx: number;
  imageUrl: string;
  start: number;
  title: string;
};

type SetSourceModel =
  | {
    embedId: string;
    frameClass: string;
    kind: "youtube";
    label: string;
    platform: string;
    sourceUrl: string;
  }
  | {
    embedSrc: string;
    frameClass: string;
    kind: "soundcloud";
    label: string;
    platform: string;
    sourceUrl: string;
  }
  | {
    frameClass: string;
    kind: "fallback";
    label: string;
    platform: string;
    sourceUrl: string;
  }
  | {
    frameClass: string;
    kind: "missing";
    label: string;
    platform: string;
    sourceUrl: null;
  };

type EmbeddableSetSourceModel = Extract<SetSourceModel, { kind: "youtube" | "soundcloud" }>;

type TimelineTooltipState = {
  badge: string;
  badgeColor: string;
  sub: string;
  title: string;
  x: number;
  y: number;
} | null;

type JourneyTooltipState = {
  title: string;
  value: string;
  x: number;
  y: number;
} | null;

type JourneyAxisScale = {
  isBpm: boolean;
  max: number;
  min: number;
};

type JourneyAxisTick = {
  label: string;
  top: number;
};

type JourneyAxis = {
  metrics: JourneyMetric[];
  side: "left" | "right";
  ticks: JourneyAxisTick[];
} | null;

type JourneyPointNode = {
  cx: number;
  cy: number;
  idx: number;
  metric: JourneyMetric;
  title: string;
  value: number;
};

type JourneyLayer = {
  color: string;
  d: string;
  metric: JourneyMetric;
  points: JourneyPointNode[];
};

const CONFIDENCE_LEVELS: ArchiveConfidence[] = ["HIGH", "MEDIUM", "LOW"];
const JOURNEY_COLORS: Record<JourneyMetric, string> = {
  bpm: "#6fffa4",
  dance: "#7dc3ff",
  energy: "#ffcf5c",
};
const JOURNEY_CODES: Record<JourneyMetric, string> = {
  bpm: "BPM",
  dance: "DNC",
  energy: "NRG",
};
const TOOLTIP_OFFSET = 14;

const joinClasses = (...values: Array<string | false | null | undefined>) =>
  values.filter(Boolean).join(" ");

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));

const roundHalfEven = (value: number, precision = 0) => {
  const factor = 10 ** precision;
  const scaled = value * factor;
  const floor = Math.floor(scaled);
  const diff = scaled - floor;
  const epsilon = 1e-9;

  if (Math.abs(diff - 0.5) <= epsilon) {
    return (floor % 2 === 0 ? floor : floor + 1) / factor;
  }

  return Math.round(scaled) / factor;
};

const formatStaticPercent = (numerator: number, denominator: number) => {
  if (denominator <= 0) {
    return 0;
  }

  return roundHalfEven(roundHalfEven((numerator / denominator) * 100, 1), 0);
};

const formatGeneratedAt = (value: string | null) => {
  if (!value) {
    return "Unknown";
  }

  const parsed = new Date(value);
  if (!Number.isNaN(parsed.getTime())) {
    const year = parsed.getFullYear();
    const month = String(parsed.getMonth() + 1).padStart(2, "0");
    const day = String(parsed.getDate()).padStart(2, "0");
    const hours = String(parsed.getHours()).padStart(2, "0");
    const minutes = String(parsed.getMinutes()).padStart(2, "0");
    return `${year}-${month}-${day} ${hours}:${minutes}`;
  }

  return value.replace("T", " ").replace(/:\d{2}(?:\.\d+)?Z?$/u, "").slice(0, 16);
};

const sourceLabel = (platform: string) => {
  const normalized = platform.toLowerCase();
  if (normalized === "youtube" || normalized === "youtu") {
    return "YouTube";
  }
  if (normalized === "soundcloud") {
    return "SoundCloud";
  }
  return "Source";
};

const detectSourceModel = ({
  platform,
  sourceUrl,
}: {
  platform: string | null;
  sourceUrl: string | null;
}): SetSourceModel => {
  const normalizedPlatform = String(platform ?? "").toLowerCase();
  const label = sourceLabel(normalizedPlatform);
  const embedId = sourceUrl ? extractYouTubeId(sourceUrl) : null;

  if ((normalizedPlatform === "youtube" || normalizedPlatform === "youtu" || embedId) && sourceUrl) {
    return {
      embedId: embedId ?? "",
      frameClass: "source-player-frame is-youtube",
      kind: "youtube",
      label: "YouTube",
      platform: "youtube",
      sourceUrl,
    };
  }

  if ((normalizedPlatform === "soundcloud" || sourceUrl?.includes("soundcloud.com")) && sourceUrl) {
    return {
      embedSrc:
        `https://w.soundcloud.com/player/?url=${encodeURIComponent(sourceUrl)}` +
        "&color=%23111111&auto_play=false&hide_related=false&show_comments=false" +
        "&show_user=true&show_reposts=false&show_teaser=false&visual=false",
      frameClass: "source-player-frame is-soundcloud",
      kind: "soundcloud",
      label: "SoundCloud",
      platform: "soundcloud",
      sourceUrl,
    };
  }

  if (sourceUrl) {
    return {
      frameClass: "source-player-frame is-fallback",
      kind: "fallback",
      label,
      platform: normalizedPlatform || "unknown",
      sourceUrl,
    };
  }

  return {
    frameClass: "source-player-frame is-fallback",
    kind: "missing",
    label: "Source",
    platform: "unknown",
    sourceUrl: null,
  };
};

const buildSourceOptions = (detail: ArchiveSetDetail) => {
  const canonicalLink: ArchiveSetSourceLink | null = detail.sourceUrl
    ? {
      id: null,
      platform: detail.sourcePlatform ?? "unknown",
      url: detail.sourceUrl,
      title: detail.title,
      durationSeconds: detail.duration,
      isPrimary: true,
      matchConfidence: 1,
    }
    : null;
  const rawLinks = [...(canonicalLink ? [canonicalLink] : []), ...(detail.sourceLinks ?? [])];
  const deduped = new Map<string, ArchiveSetSourceLink>();

  for (const link of rawLinks) {
    const platform = link.platform.toLowerCase();
    if (platform !== "youtube" && platform !== "youtu" && platform !== "soundcloud") {
      continue;
    }
    const key = `${platform}:${link.url}`;
    const existing = deduped.get(key);
    deduped.set(key, {
      ...link,
      isPrimary: Boolean(existing?.isPrimary || link.isPrimary),
    });
  }

  return [...deduped.values()]
    .sort((left, right) => {
      if (left.isPrimary !== right.isPrimary) {
        return left.isPrimary ? -1 : 1;
      }
      return left.platform.localeCompare(right.platform) || left.url.localeCompare(right.url);
    })
    .map((link) => detectSourceModel({ platform: link.platform, sourceUrl: link.url }))
    .filter((source) => source.kind === "youtube" || source.kind === "soundcloud");
};

const buildUiTrack = (track: ArchiveSetTrack, duration: number): UiTrack => {
  const endResolved = track.end ?? duration;
  const spotifyResolvedUrl = track.spotifyUrl ?? buildSpotifySearchUrl(track.artist, track.title);
  const youtubeResolvedUrl = track.youtubeUrl ?? buildYouTubeSearchUrl(track.artist, track.title);
  const discogsResolvedUrl = track.discogsUrl ?? buildDiscogsSearchUrl(track.artist, track.title);
  const spotifyTrackId = extractSpotifyTrackId(track.spotifyUrl);
  const densityPct = Math.max(0, Math.min(100, Number(track.clusterDensity ?? 0) * 100));
  const timeRange = `${track.startFmt} - ${track.endFmt ?? formatDuration(endResolved)}`;

  return {
    ...track,
    densityPct,
    directDiscogsUrl: track.discogsUrl,
    directSpotifyUrl: track.spotifyUrl,
    directYouTubeUrl: track.youtubeUrl,
    discogsLinkLabel: track.discogsUrl ? "Discogs" : "Search Discogs",
    discogsResolvedUrl,
    endResolved,
    endResolvedFmt: track.endFmt ?? formatDuration(endResolved),
    isUnknownTrack: normalizeSearchText(track.title) === "unknown track",
    searchBlob: buildSearchBlob(
      track.artist,
      track.title,
      track.genres.join(" "),
      track.detailGenres.join(" "),
      track.label ?? "",
    ),
    spotifyLinkLabel: track.spotifyUrl ? "Spotify" : "Search Spotify",
    spotifyResolvedUrl,
    spotifyTrackId,
    timeRange,
    youtubeLinkLabel: track.youtubeUrl ? "YouTube" : "Search YouTube",
    youtubeResolvedUrl,
  };
};

const buildSetModel = (detail: ArchiveSetDetail) => {
  const tracks = detail.tracks.map((track) => buildUiTrack(track, detail.duration));
  const heroCards: HeroCard[] = tracks
    .filter((track) => Boolean(track.albumArt))
    .slice(0, 12)
    .map((track) => ({
      artist: track.artist,
      idx: track.idx,
      imageUrl: track.albumArt ?? "",
      start: track.start,
      title: track.title,
    }));
  const titleLength = detail.title.trim().length;
  const bpmValues = tracks
    .map((track) => track.bpm)
    .filter((value): value is number => value != null);

  return {
    confidenceCounts: tracks.reduce<Record<ArchiveConfidence, number>>(
      (counts, track) => {
        counts[track.conf] += 1;
        return counts;
      },
      {
        HIGH: 0,
        LOW: 0,
        MEDIUM: 0,
        UNCERTAIN: 0,
      },
    ),
    confidenceRate: formatStaticPercent(detail.stats.highOrMediumTracks, tracks.length),
    generatedDisplay: formatGeneratedAt(detail.generatedAt),
    heroCards,
    heroImageUrl:
      detail.heroImageUrl ??
      detail.thumbnailUrl ??
      heroCards[0]?.imageUrl ??
      null,
    heroTitleMinSize: titleLength >= 68 ? 20 : titleLength >= 44 ? 22 : 24,
    heroTitleVariant: titleLength >= 68 ? "xlong" : titleLength >= 44 ? "long" : "default",
    identificationRate: formatStaticPercent(detail.stats.identifiedTracks, tracks.length),
    tempoSpan:
      bpmValues.length > 0
        ? `${Math.min(...bpmValues).toFixed(0)} - ${Math.max(...bpmValues).toFixed(0)} BPM`
        : "Tempo unavailable",
    ticks: [0, 25, 50, 75, 100].map((pct) => formatDuration((detail.duration * pct) / 100)),
    tracks,
  };
};

const scaleFromValues = (values: number[], isBpm: boolean): JourneyAxisScale | null => {
  if (values.length === 0) {
    return null;
  }

  let min = Math.min(...values);
  let max = Math.max(...values);

  if (min === max) {
    const padding = isBpm ? 1 : 0.05;
    min -= padding;
    max += padding;
  }

  return {
    isBpm,
    max,
    min,
  };
};

const buildJourneyAxis = (
  scale: JourneyAxisScale | null,
  side: "left" | "right",
  metrics: JourneyMetric[],
): JourneyAxis => {
  if (!scale) {
    return null;
  }

  const ticks: JourneyAxisTick[] = [];
  const span = Math.max(0.0001, scale.max - scale.min);
  const chartHeight = 260;
  const chartPadding = 22;

  for (let index = 0; index < 5; index += 1) {
    const pct = index / 4;
    const value = scale.min + pct * span;
    const top = chartHeight - chartPadding - pct * (chartHeight - chartPadding * 2);
    ticks.push({
      label: scale.isBpm ? value.toFixed(0) : value.toFixed(2),
      top,
    });
  }

  return {
    metrics,
    side,
    ticks,
  };
};

const buildJourneyViewModel = (
  points: ArchiveJourneyPoint[],
  metrics: JourneyMetric[],
  duration: number,
) => {
  if (points.length === 0) {
    return {
      empty: true,
      layers: [] as JourneyLayer[],
      leftAxis: null as JourneyAxis,
      rightAxis: null as JourneyAxis,
    };
  }

  const activeMetrics = metrics.filter((metric) => ["bpm", "energy", "dance"].includes(metric));
  const metricPoints = {
    bpm: points
      .filter((point) => point.bpm != null)
      .map((point) => ({
        point,
        value: Number(point.bpm),
        x: Math.max(0, point.start) / Math.max(1, duration),
      }))
      .sort((left, right) => left.x - right.x),
    dance: points
      .filter((point) => point.dance != null)
      .map((point) => ({
        point,
        value: Number(point.dance),
        x: Math.max(0, point.start) / Math.max(1, duration),
      }))
      .sort((left, right) => left.x - right.x),
    energy: points
      .filter((point) => point.energy != null)
      .map((point) => ({
        point,
        value: Number(point.energy),
        x: Math.max(0, point.start) / Math.max(1, duration),
      }))
      .sort((left, right) => left.x - right.x),
  };
  const hasRenderableMetric = activeMetrics.some((metric) => metricPoints[metric].length > 0);

  if (!hasRenderableMetric) {
    return {
      empty: true,
      layers: [] as JourneyLayer[],
      leftAxis: null as JourneyAxis,
      rightAxis: null as JourneyAxis,
    };
  }

  const isolated = activeMetrics.length === 1;
  let leftScale: JourneyAxisScale | null = null;
  let rightScale: JourneyAxisScale | null = null;

  if (isolated) {
    const metric = activeMetrics[0]!;
    if (metric === "bpm") {
      leftScale = scaleFromValues(
        metricPoints.bpm.map((entry) => entry.value),
        true,
      );
    } else {
      leftScale = {
        isBpm: false,
        max: 1,
        min: 0,
      };
    }
  } else {
    const hasEnergy = activeMetrics.includes("energy") && metricPoints.energy.length > 0;
    const hasDance = activeMetrics.includes("dance") && metricPoints.dance.length > 0;

    if (hasEnergy || hasDance) {
      leftScale = {
        isBpm: false,
        max: 1,
        min: 0,
      };
    }

    if (activeMetrics.includes("bpm") && metricPoints.bpm.length > 0) {
      rightScale = scaleFromValues(
        metricPoints.bpm.map((entry) => entry.value),
        true,
      );
    }

    if (!leftScale && rightScale) {
      leftScale = rightScale;
      rightScale = null;
    }
  }

  const leftMetrics: JourneyMetric[] = [];
  const rightMetrics: JourneyMetric[] = [];

  if (isolated) {
    leftMetrics.push(activeMetrics[0]!);
  } else {
    if (activeMetrics.includes("energy") && metricPoints.energy.length > 0) {
      leftMetrics.push("energy");
    }
    if (activeMetrics.includes("dance") && metricPoints.dance.length > 0) {
      leftMetrics.push("dance");
    }
    if (rightScale && activeMetrics.includes("bpm") && metricPoints.bpm.length > 0) {
      rightMetrics.push("bpm");
    }
    if (!rightMetrics.length && leftScale?.isBpm && activeMetrics.includes("bpm")) {
      leftMetrics.push("bpm");
    }
  }

  const width = 1000;
  const height = 260;
  const padding = 22;
  const layers: JourneyLayer[] = [];

  for (const metric of activeMetrics) {
    const pointsForMetric = metricPoints[metric];
    if (pointsForMetric.length === 0) {
      continue;
    }

    const scale = isolated ? leftScale : metric === "bpm" && rightScale ? rightScale : leftScale;
    if (!scale) {
      continue;
    }

    const range = Math.max(0.0001, scale.max - scale.min);
    const coords = pointsForMetric.map((entry) => {
      const cx = padding + entry.x * (width - padding * 2);
      const normalized = (entry.value - scale.min) / range;
      const cy = height - padding - normalized * (height - padding * 2);
      return {
        cx,
        cy,
        idx: entry.point.idx,
        metric,
        title: `${entry.point.artist} — ${entry.point.title}`,
        value: entry.value,
      };
    });

    layers.push({
      color: JOURNEY_COLORS[metric],
      d: coords
        .map((coord, index) => `${index === 0 ? "M" : "L"}${coord.cx.toFixed(2)} ${coord.cy.toFixed(2)}`)
        .join(" "),
      metric,
      points: coords,
    });
  }

  return {
    empty: layers.length === 0,
    layers,
    leftAxis: buildJourneyAxis(leftScale, "left", leftMetrics),
    rightAxis: buildJourneyAxis(rightScale, "right", rightMetrics),
  };
};

const loadScript = (src: string) =>
  new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${src}"]`);

    if (existing) {
      if (existing.dataset.loaded === "1") {
        resolve();
        return;
      }

      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error(`Failed to load ${src}`)), {
        once: true,
      });
      return;
    }

    const script = document.createElement("script");
    script.async = true;
    script.src = src;
    script.addEventListener(
      "load",
      () => {
        script.dataset.loaded = "1";
        resolve();
      },
      { once: true },
    );
    script.addEventListener("error", () => reject(new Error(`Failed to load ${src}`)), {
      once: true,
    });
    document.head.appendChild(script);
  });

const buildSourceLinkAt = (source: SetSourceModel, seconds: number) => {
  const safeSeconds = Math.max(0, Math.floor(seconds));

  if (source.kind === "youtube") {
    if (source.embedId) {
      return `https://www.youtube.com/watch?v=${encodeURIComponent(source.embedId)}&t=${safeSeconds}s`;
    }

    try {
      const url = new URL(source.sourceUrl);
      url.searchParams.set("t", `${safeSeconds}s`);
      return url.toString();
    } catch {
      return source.sourceUrl;
    }
  }

  return source.sourceUrl ?? "";
};

type PlayerWindow = Window &
  typeof globalThis & {
    onYouTubeIframeAPIReady?: (() => void) | undefined;
    SC?: {
      Widget?: SoundCloudWidgetFactory;
    };
    YT?: {
      Player?: new (
        element: HTMLElement,
        config: {
          playerVars?: Record<string, number | string>;
          events: {
            onError?: () => void;
            onReady?: () => void;
            onStateChange?: (event: { data?: number }) => void;
          };
          videoId?: string;
        },
      ) => YouTubePlayer;
      PlayerState?: {
        CUED?: number;
        ENDED?: number;
        PAUSED?: number;
        PLAYING?: number;
      };
    };
  };

type YouTubePlayer = {
  destroy?: () => void;
  getCurrentTime?: () => number;
  getPlayerState?: () => number;
  pauseVideo?: () => void;
  playVideo?: () => void;
  seekTo?: (seconds: number, allowSeekAhead?: boolean) => void;
};

type SoundCloudWidgetFactory = ((element: HTMLIFrameElement) => SoundCloudWidget) & {
  Events: {
    FINISH: string;
    PAUSE: string;
    PLAY: string;
    PLAY_PROGRESS: string;
    READY: string;
    SEEK: string;
  };
};

type SoundCloudWidgetEvent =
  | {
    currentPosition?: number;
  }
  | number
  | null
  | undefined;

type SoundCloudWidget = {
  bind: (eventName: string, callback: (event?: SoundCloudWidgetEvent) => void) => void;
  getPosition: (callback: (milliseconds: number) => void) => void;
  isPaused?: (callback: (paused: boolean) => void) => void;
  pause?: () => void;
  play?: () => void;
  seekTo?: (milliseconds: number) => void;
};

export function ArchiveSetExplorer({
  detail,
  initialQuery,
  management,
}: {
  detail: ArchiveSetDetail;
  initialQuery: string;
  management: SetManagement;
}) {
  const model = useMemo(() => buildSetModel(detail), [detail]);
  const sourceOptions = useMemo(() => buildSourceOptions(detail), [detail]);
  const [selectedSourceUrl, setSelectedSourceUrl] = useState<string | null>(null);
  const activeSource = useMemo(() => {
    if (sourceOptions.length === 0) {
      return detectSourceModel({
        platform: detail.sourcePlatform,
        sourceUrl: detail.sourceUrl,
      });
    }

    return (
      sourceOptions.find((source) => source.sourceUrl === selectedSourceUrl) ??
      sourceOptions.find((source) => source.sourceUrl === detail.sourceUrl) ??
      sourceOptions[0]!
    );
  }, [detail.sourcePlatform, detail.sourceUrl, selectedSourceUrl, sourceOptions]);
  const sourceSwitcherSources = useMemo(() => {
    const soundCloudSource = sourceOptions.find((source) => source.kind === "soundcloud");
    const youtubeSource = sourceOptions.find((source) => source.kind === "youtube");
    return [soundCloudSource, youtubeSource].filter(
      (source): source is EmbeddableSetSourceModel => Boolean(source?.sourceUrl),
    );
  }, [sourceOptions]);
  const spotifyExportCounts = useMemo(() => buildSetSpotifyExportCounts(detail), [detail]);
  const [query, setQuery] = useState(initialQuery);
  const [confidenceFilter, setConfidenceFilter] = useState<ConfidenceFilter>("all");
  const [activeIdx, setActiveIdx] = useState<number | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [journeyOpen, setJourneyOpen] = useState(false);
  const [activeMetrics, setActiveMetrics] = useState<JourneyMetric[]>(["bpm", "energy", "dance"]);
  const [openDetailIdxs, setOpenDetailIdxs] = useState<number[]>([]);
  const [openSpotifyIdxs, setOpenSpotifyIdxs] = useState<number[]>([]);
  const [hoveredTrackIdx, setHoveredTrackIdx] = useState<number | null>(null);
  const [timelineTooltip, setTimelineTooltip] = useState<TimelineTooltipState>(null);
  const [journeyTooltip, setJourneyTooltip] = useState<JourneyTooltipState>(null);
  const [hashHitIdx, setHashHitIdx] = useState<number | null>(null);
  const [ytEmbedBlocked, setYtEmbedBlocked] = useState(false);
  const [scEmbedBlocked, setScEmbedBlocked] = useState(false);
  const deferredQuery = useDeferredValue(query);
  const heroMainRef = useRef<HTMLDivElement | null>(null);
  const heroTitleRef = useRef<HTMLHeadingElement | null>(null);
  const heroSideRef = useRef<HTMLDivElement | null>(null);
  const heroViewportRef = useRef<HTMLDivElement | null>(null);
  const heroTrackRef = useRef<HTMLDivElement | null>(null);
  const youtubeHostRef = useRef<HTMLDivElement | null>(null);
  const soundCloudFrameRef = useRef<HTMLIFrameElement | null>(null);
  const currentTimeRef = useRef(currentTime);
  const isPlayingRef = useRef(isPlaying);
  const activeIdxRef = useRef<number | null>(activeIdx);
  const playerReadyRef = useRef(false);
  const pendingSeekRef = useRef<number | null>(null);
  const pendingAutoplayRef = useRef(false);
  const seekLockUntilRef = useRef(0);
  const fallbackTickRef = useRef<number | null>(null);
  const playerPollRef = useRef<number | null>(null);
  const heroRailRafRef = useRef<number | null>(null);
  const heroRailLastTsRef = useRef(0);
  const prevTrackPressTsRef = useRef(0);
  const ytPlayerRef = useRef<YouTubePlayer | null>(null);
  const scWidgetRef = useRef<SoundCloudWidget | null>(null);

  useEffect(() => {
    setQuery(initialQuery);
  }, [initialQuery]);

  useEffect(() => {
    setSelectedSourceUrl(null);
  }, [detail.id]);

  useEffect(() => {
    if (sourceOptions.length < 2 || typeof window === "undefined") {
      return;
    }

    const soundCloudSource = sourceOptions.find((source) => source.kind === "soundcloud");
    const youtubeSource = sourceOptions.find((source) => source.kind === "youtube");
    if (!soundCloudSource || !youtubeSource) {
      return;
    }

    const prefersSoundCloud = window.matchMedia("(max-width: 760px), (pointer: coarse)").matches;
    setSelectedSourceUrl((prefersSoundCloud ? soundCloudSource : youtubeSource).sourceUrl);
  }, [detail.id, sourceOptions]);

  useEffect(() => {
    currentTimeRef.current = currentTime;
  }, [currentTime]);

  useEffect(() => {
    isPlayingRef.current = isPlaying;
  }, [isPlaying]);

  useEffect(() => {
    activeIdxRef.current = activeIdx;
  }, [activeIdx]);

  const normalizedQuery = normalizeSearchText(deferredQuery);
  const filteredTracks = normalizedQuery
    ? model.tracks.filter((track) => track.searchBlob.includes(normalizedQuery))
    : model.tracks;
  const confidenceFilteredTracks =
    confidenceFilter === "all"
      ? filteredTracks
      : filteredTracks.filter((track) => track.conf === confidenceFilter);
  const visibleTrackIds = new Set(confidenceFilteredTracks.map((track) => track.idx));
  const journeyView = buildJourneyViewModel(detail.journeyPoints, activeMetrics, detail.duration);
  const activeTrack = model.tracks.find((track) => track.idx === activeIdx) ?? null;
  const showDock =
    (activeSource.kind === "youtube" || activeSource.kind === "soundcloud") &&
    !ytEmbedBlocked &&
    !scEmbedBlocked;
  const artistNames = detail.artists.map((artist) => artist.name).join(", ");
  const nowPlayingArtist = detail.artistName ?? (artistNames || "Set Signal Archive");

  const publishNowPlayingMetadata = () => {
    if (typeof window === "undefined" || !("mediaSession" in navigator) || !("MediaMetadata" in window)) {
      return;
    }

    navigator.mediaSession.metadata = new window.MediaMetadata({
      album: "Set Signal Archive",
      artist: nowPlayingArtist,
      title: detail.title,
    });
  };

  const stopHeroRail = () => {
    if (heroRailRafRef.current != null) {
      cancelAnimationFrame(heroRailRafRef.current);
      heroRailRafRef.current = null;
    }
    heroRailLastTsRef.current = 0;
  };

  const startHeroRail = () => {
    stopHeroRail();

    const viewport = heroViewportRef.current;
    const track = heroTrackRef.current;
    if (!viewport || !track || model.heroCards.length === 0) {
      return;
    }

    if (
      window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
      window.matchMedia("(max-width: 1180px)").matches
    ) {
      return;
    }

    const cycleHeight = track.scrollHeight / 2;
    if (!Number.isFinite(cycleHeight) || cycleHeight <= viewport.clientHeight + 4) {
      return;
    }

    let scrollPosition = viewport.scrollTop % cycleHeight;
    viewport.scrollTop = scrollPosition;
    const pixelsPerSecond = 14;

    const tick = (timestamp: number) => {
      if (heroRailRafRef.current == null) {
        return;
      }
      if (!heroRailLastTsRef.current) {
        heroRailLastTsRef.current = timestamp;
      }
      const delta = (timestamp - heroRailLastTsRef.current) / 1000;
      heroRailLastTsRef.current = timestamp;
      scrollPosition += pixelsPerSecond * delta;
      if (scrollPosition >= cycleHeight) {
        scrollPosition -= cycleHeight;
      }
      viewport.scrollTop = scrollPosition;
      heroRailRafRef.current = requestAnimationFrame(tick);
    };

    heroRailRafRef.current = requestAnimationFrame(tick);
  };

  const fitHeroTitle = () => {
    const heroMain = heroMainRef.current;
    const heroTitle = heroTitleRef.current;
    if (!heroMain || !heroTitle) {
      return;
    }

    const computed = window.getComputedStyle(heroTitle);
    if (!heroTitle.dataset.baseSize) {
      const baseSize = Number.parseFloat(computed.fontSize || "0");
      if (baseSize > 0) {
        heroTitle.dataset.baseSize = String(baseSize);
      }
    }

    const baseSize =
      Number.parseFloat(heroTitle.dataset.baseSize || computed.fontSize || "0") || 56;
    const minSize = Math.max(16, model.heroTitleMinSize);
    let nextSize = baseSize;
    heroTitle.style.fontSize = `${nextSize}px`;

    const fits = () => {
      const mainRect = heroMain.getBoundingClientRect();
      const titleRect = heroTitle.getBoundingClientRect();
      return titleRect.top >= mainRect.top + 6 && titleRect.bottom <= mainRect.bottom - 8;
    };

    let guard = 0;
    while (!fits() && nextSize > minSize && guard < 50) {
      nextSize -= 1;
      heroTitle.style.fontSize = `${nextSize}px`;
      guard += 1;
    }
  };

  const findTrackByTime = (seconds: number) => {
    const safeSeconds = Math.max(0, seconds);
    let best: UiTrack | null = null;
    for (const track of model.tracks) {
      if (safeSeconds >= track.start && safeSeconds < track.endResolved) {
        if (!best || track.start > best.start) {
          best = track;
        }
      }
    }
    return best ?? model.tracks[model.tracks.length - 1] ?? null;
  };

  const scrollToTrack = (idx: number) => {
    const card = document.getElementById(`track-${idx}`);
    if (card) {
      card.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const clearActiveTrack = () => {
    setActiveIdx(null);
  };

  const updateFromTime = (seconds: number, scroll: boolean) => {
    const safeSeconds = clamp(seconds, 0, Math.max(0, detail.duration));
    setCurrentTime(safeSeconds);
    const track = findTrackByTime(safeSeconds);
    if (track) {
      setActiveIdx(track.idx);
      if (scroll) {
        scrollToTrack(track.idx);
      }
    }
  };

  const stopPlayerPoll = () => {
    if (playerPollRef.current != null) {
      window.clearInterval(playerPollRef.current);
      playerPollRef.current = null;
    }
  };

  const stopFallbackTick = () => {
    if (fallbackTickRef.current != null) {
      window.clearInterval(fallbackTickRef.current);
      fallbackTickRef.current = null;
    }
  };

  const destroyPlayers = () => {
    stopPlayerPoll();
    stopFallbackTick();
    pendingSeekRef.current = null;
    pendingAutoplayRef.current = false;
    playerReadyRef.current = false;

    if (ytPlayerRef.current?.destroy) {
      ytPlayerRef.current.destroy();
    }
    ytPlayerRef.current = null;
    scWidgetRef.current = null;
  };

  const showYouTubeBlockedFallback = () => {
    destroyPlayers();
    setYtEmbedBlocked(true);
    setIsPlaying(false);
  };

  const showSoundCloudBlockedFallback = () => {
    destroyPlayers();
    setScEmbedBlocked(true);
    setIsPlaying(false);
  };

  const resolveSoundCloudEventSeconds = (event?: SoundCloudWidgetEvent) => {
    if (typeof event === "number" && Number.isFinite(event)) {
      return event / 1000;
    }

    if (
      event &&
      typeof event === "object" &&
      "currentPosition" in event &&
      typeof event.currentPosition === "number" &&
      Number.isFinite(event.currentPosition)
    ) {
      return event.currentPosition / 1000;
    }

    return null;
  };

  const updateFromPolledTime = (seconds: number) => {
    const safeSeconds = clamp(seconds, 0, Math.max(0, detail.duration));
    setCurrentTime(safeSeconds);
    if (Date.now() < seekLockUntilRef.current) {
      return;
    }
    const track = findTrackByTime(safeSeconds);
    if (track && track.idx !== activeIdxRef.current) {
      setActiveIdx(track.idx);
    }
  };

  const pollPlayerTime = () => {
    if (!playerReadyRef.current) {
      return;
    }

    if (
      activeSource.kind === "youtube" &&
      ytPlayerRef.current?.getCurrentTime &&
      ytPlayerRef.current?.getPlayerState
    ) {
      const playerWindow = window as PlayerWindow;
      const state = ytPlayerRef.current.getPlayerState();
      const playing = state === playerWindow.YT?.PlayerState?.PLAYING;
      const paused =
        state === playerWindow.YT?.PlayerState?.PAUSED ||
        state === playerWindow.YT?.PlayerState?.ENDED ||
        state === playerWindow.YT?.PlayerState?.CUED;
      if (playing !== isPlayingRef.current) {
        setIsPlaying(playing);
      } else if (paused && isPlayingRef.current) {
        setIsPlaying(false);
      }

      const seconds = ytPlayerRef.current.getCurrentTime();
      if (Number.isFinite(seconds)) {
        updateFromPolledTime(seconds);
      }
      return;
    }

    if (activeSource.kind === "soundcloud" && scWidgetRef.current?.getPosition) {
      scWidgetRef.current.isPaused?.((paused) => {
        const nextPlaying = !paused;
        if (nextPlaying !== isPlayingRef.current) {
          setIsPlaying(nextPlaying);
        }
      });
      scWidgetRef.current.getPosition((milliseconds: number) => {
        const seconds = Number(milliseconds) / 1000;
        if (Number.isFinite(seconds)) {
          updateFromPolledTime(seconds);
        }
      });
    }
  };

  const startPlayerPoll = () => {
    if (playerPollRef.current != null) {
      return;
    }

    playerPollRef.current = window.setInterval(() => {
      pollPlayerTime();
    }, 400);
    pollPlayerTime();
  };

  const flushPendingSeek = () => {
    if (pendingSeekRef.current == null) {
      return;
    }

    const target = pendingSeekRef.current;
    const autoplay = pendingAutoplayRef.current;
    pendingSeekRef.current = null;
    pendingAutoplayRef.current = false;
    seekPlayer(target, false, autoplay);
  };

  const startFallbackProgress = () => {
    if (fallbackTickRef.current != null) {
      return;
    }

    fallbackTickRef.current = window.setInterval(() => {
      if (!isPlayingRef.current) {
        return;
      }

      const nextTime = Math.min(detail.duration, currentTimeRef.current + 1);
      updateFromTime(nextTime, false);
      if (nextTime >= detail.duration) {
        setIsPlaying(false);
        stopFallbackTick();
      }
    }, 1000);
  };

  const seekPlayer = (seconds: number, scroll: boolean, autoplay: boolean) => {
    const safeSeconds = clamp(seconds, 0, Math.max(0, detail.duration));
    updateFromTime(safeSeconds, scroll);
    seekLockUntilRef.current = Date.now() + 1500;

    if (activeSource.kind === "youtube") {
      if (ytEmbedBlocked) {
        setIsPlaying(false);
        return;
      }

      if (ytPlayerRef.current && playerReadyRef.current && ytPlayerRef.current.seekTo) {
        ytPlayerRef.current.seekTo(safeSeconds, true);
        if (autoplay && ytPlayerRef.current.playVideo) {
          ytPlayerRef.current.playVideo();
        }
        if (!autoplay && ytPlayerRef.current.pauseVideo) {
          ytPlayerRef.current.pauseVideo();
        }
      } else {
        pendingSeekRef.current = safeSeconds;
        pendingAutoplayRef.current = autoplay;
      }
      if (autoplay) {
        setIsPlaying(true);
      }
      return;
    }

    if (activeSource.kind === "soundcloud") {
      if (scEmbedBlocked) {
        setIsPlaying(false);
        return;
      }

      if (scWidgetRef.current && playerReadyRef.current && scWidgetRef.current.seekTo) {
        scWidgetRef.current.seekTo(safeSeconds * 1000);
        if (autoplay && scWidgetRef.current.play) {
          scWidgetRef.current.play();
        }
        if (!autoplay && scWidgetRef.current.pause) {
          scWidgetRef.current.pause();
        }
      } else {
        pendingSeekRef.current = safeSeconds;
        pendingAutoplayRef.current = autoplay;
      }
      if (autoplay) {
        setIsPlaying(true);
      }
      return;
    }

    if (autoplay) {
      setIsPlaying(true);
      startFallbackProgress();
    } else {
      setIsPlaying(false);
      stopFallbackTick();
    }
  };

  const jumpTo = (seconds: number, scroll: boolean, autoplay: boolean) => {
    seekPlayer(seconds, scroll, autoplay);
  };

  const pausePlayer = () => {
    if (activeSource.kind === "youtube" && ytPlayerRef.current?.pauseVideo && playerReadyRef.current) {
      setIsPlaying(false);
      stopFallbackTick();
      ytPlayerRef.current.pauseVideo();
      pollPlayerTime();
      return;
    }

    if (activeSource.kind === "soundcloud" && scWidgetRef.current?.pause && playerReadyRef.current) {
      setIsPlaying(false);
      stopFallbackTick();
      scWidgetRef.current.pause();
      pollPlayerTime();
      return;
    }

    setIsPlaying(false);
    stopFallbackTick();
  };

  const playPlayer = () => {
    publishNowPlayingMetadata();

    if (activeSource.kind === "youtube") {
      if (ytEmbedBlocked) {
        setIsPlaying(false);
        return;
      }

      if (ytPlayerRef.current?.playVideo && playerReadyRef.current) {
        ytPlayerRef.current.playVideo();
      } else {
        pendingAutoplayRef.current = true;
      }
      setIsPlaying(true);
      return;
    }

    if (activeSource.kind === "soundcloud") {
      if (scEmbedBlocked) {
        setIsPlaying(false);
        return;
      }

      if (scWidgetRef.current?.play && playerReadyRef.current) {
        scWidgetRef.current.play();
      } else {
        pendingAutoplayRef.current = true;
      }
      setIsPlaying(true);
      return;
    }

    setIsPlaying(true);
    startFallbackProgress();
  };

  const togglePlay = () => {
    if (
      activeSource.kind === "youtube" &&
      ytPlayerRef.current?.getPlayerState &&
      playerReadyRef.current
    ) {
      const playerWindow = window as PlayerWindow;
      const state = ytPlayerRef.current.getPlayerState();
      if (state === playerWindow.YT?.PlayerState?.PLAYING) {
        pausePlayer();
        return;
      }

      if (detail.duration > 0 && currentTimeRef.current >= detail.duration) {
        seekPlayer(0, false, true);
        return;
      }

      playPlayer();
      return;
    }

    if (
      activeSource.kind === "soundcloud" &&
      scWidgetRef.current?.isPaused &&
      playerReadyRef.current
    ) {
      scWidgetRef.current.isPaused((paused) => {
        if (!paused) {
          pausePlayer();
          return;
        }

        if (detail.duration > 0 && currentTimeRef.current >= detail.duration) {
          seekPlayer(0, false, true);
          return;
        }

        playPlayer();
      });
      return;
    }

    if (isPlayingRef.current) {
      pausePlayer();
      return;
    }

    if (detail.duration > 0 && currentTimeRef.current >= detail.duration) {
      seekPlayer(0, false, true);
      return;
    }

    playPlayer();
  };

  const nextTrack = () => {
    const next = model.tracks.find((track) => track.start > currentTimeRef.current + 1);
    if (next) {
      jumpTo(next.start, false, true);
    }
  };

  const previousTrack = () => {
    const now = Date.now();
    const sorted = [...model.tracks].sort((left, right) => left.start - right.start);
    const current = [...sorted].reverse().find((track) => track.start <= currentTimeRef.current);

    if (current && now - prevTrackPressTsRef.current < 2000) {
      const previous = [...sorted].reverse().find((track) => track.start < current.start);
      if (previous) {
        jumpTo(previous.start, false, true);
      }
    } else if (current) {
      jumpTo(current.start, false, true);
    } else {
      jumpTo(0, false, true);
    }

    prevTrackPressTsRef.current = now;
  };

  useEffect(() => {
    updateFromTime(0, false);
    setIsPlaying(false);
    setJourneyOpen(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.id]);

  useEffect(() => {
    fitHeroTitle();
    startHeroRail();

    const handleResize = () => {
      window.clearTimeout((handleResize as typeof handleResize & { timer?: number }).timer);
      (handleResize as typeof handleResize & { timer?: number }).timer = window.setTimeout(() => {
        fitHeroTitle();
        startHeroRail();
      }, 120);
    };
    const handleVisibility = () => {
      if (document.hidden) {
        stopHeroRail();
      } else {
        startHeroRail();
      }
    };

    window.addEventListener("resize", handleResize);
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      window.removeEventListener("resize", handleResize);
      document.removeEventListener("visibilitychange", handleVisibility);
      stopHeroRail();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.id, model.heroCards.length, model.heroTitleMinSize]);

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
      if (window.matchMedia("(max-width: 1180px)").matches) {
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
  }, [detail.id, model.heroCards.length]);

  useEffect(() => {
    let cancelled = false;

    setYtEmbedBlocked(false);
    setScEmbedBlocked(false);
    destroyPlayers();
    setIsPlaying(false);

    const youtubeEmbedId = activeSource.kind === "youtube" ? activeSource.embedId : null;
    const youtubeHost = youtubeHostRef.current;

    if (youtubeEmbedId && youtubeHost) {
      youtubeHost.replaceChildren();
      const youtubePlayerElement = document.createElement("div");
      youtubeHost.appendChild(youtubePlayerElement);

      loadScript("https://www.youtube.com/iframe_api")
        .then(() => {
          const playerWindow = window as PlayerWindow;
          const boot = () => {
            if (cancelled || !playerWindow.YT?.Player || !youtubePlayerElement.isConnected) {
              return;
            }

            ytPlayerRef.current = new playerWindow.YT.Player(youtubePlayerElement, {
              playerVars: {
                iv_load_policy: 3,
                modestbranding: 1,
                playsinline: 1,
                rel: 0,
              },
              videoId: youtubeEmbedId,
              events: {
                onError: () => {
                  if (!cancelled) {
                    showYouTubeBlockedFallback();
                  }
                },
                onReady: () => {
                  playerReadyRef.current = true;
                  startPlayerPoll();
                  pollPlayerTime();
                  flushPendingSeek();
                },
                onStateChange: (event: { data?: number }) => {
                  const YT = playerWindow.YT;
                  const playing = event?.data === YT?.PlayerState?.PLAYING;
                  if (playing) {
                    publishNowPlayingMetadata();
                    setIsPlaying(true);
                    startPlayerPoll();
                    pollPlayerTime();
                    return;
                  }

                  const paused =
                    event?.data === YT?.PlayerState?.PAUSED ||
                    event?.data === YT?.PlayerState?.ENDED ||
                    event?.data === YT?.PlayerState?.CUED;
                  if (paused) {
                    setIsPlaying(false);
                    pollPlayerTime();
                  }
                },
              },
            });
          };

          if (playerWindow.YT?.Player) {
            boot();
            return;
          }

          const previousReady = playerWindow.onYouTubeIframeAPIReady;
          playerWindow.onYouTubeIframeAPIReady = () => {
            previousReady?.();
            boot();
          };
        })
        .catch(() => {
          if (!cancelled) {
            showYouTubeBlockedFallback();
          }
        });
    }

    if (activeSource.kind === "soundcloud" && soundCloudFrameRef.current) {
      loadScript("https://w.soundcloud.com/player/api.js")
        .then(() => {
          const playerWindow = window as PlayerWindow;
          if (cancelled || !playerWindow.SC?.Widget || !soundCloudFrameRef.current) {
            if (!cancelled) {
              showSoundCloudBlockedFallback();
            }
            return;
          }

          const widget = playerWindow.SC.Widget(soundCloudFrameRef.current);
          scWidgetRef.current = widget;
          const markSoundCloudReady = () => {
            if (cancelled || playerReadyRef.current) {
              return;
            }
            playerReadyRef.current = true;
            startPlayerPoll();
            pollPlayerTime();
            flushPendingSeek();
          };

          widget.bind(playerWindow.SC.Widget.Events.READY, () => {
            markSoundCloudReady();
          });
          widget.bind(playerWindow.SC.Widget.Events.PLAY, () => {
            publishNowPlayingMetadata();
            setIsPlaying(true);
            startPlayerPoll();
            pollPlayerTime();
          });
          widget.bind(playerWindow.SC.Widget.Events.PAUSE, () => {
            setIsPlaying(false);
            pollPlayerTime();
          });
          widget.bind(playerWindow.SC.Widget.Events.FINISH, () => {
            setIsPlaying(false);
            pollPlayerTime();
          });
          widget.bind(playerWindow.SC.Widget.Events.SEEK, (event?: SoundCloudWidgetEvent) => {
            const seconds = resolveSoundCloudEventSeconds(event);
            if (seconds != null) {
              updateFromPolledTime(seconds);
              return;
            }
            pollPlayerTime();
          });
          widget.bind(
            playerWindow.SC.Widget.Events.PLAY_PROGRESS,
            (event?: SoundCloudWidgetEvent) => {
              const seconds = resolveSoundCloudEventSeconds(event);
              if (seconds != null) {
                updateFromPolledTime(seconds);
                return;
              }
              pollPlayerTime();
            },
          );
          widget.getPosition(() => {
            markSoundCloudReady();
          });
          window.setTimeout(() => {
            if (cancelled || playerReadyRef.current || !widget.getPosition) {
              return;
            }
            widget.getPosition(() => {
              markSoundCloudReady();
            });
          }, 1200);
        })
        .catch(() => {
          if (!cancelled) {
            showSoundCloudBlockedFallback();
          }
        });
    }

    return () => {
      cancelled = true;
      destroyPlayers();
      youtubeHost?.replaceChildren();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.id, activeSource.kind, activeSource.sourceUrl]);

  useEffect(() => {
    const handleHash = () => {
      const hash = window.location.hash || "";
      if (!hash.startsWith("#track-")) {
        return;
      }

      const idx = Number(hash.replace("#track-", ""));
      if (!Number.isFinite(idx)) {
        return;
      }

      const track = model.tracks.find((entry) => entry.idx === idx);
      if (track) {
        updateFromTime(track.start, false);
      } else {
        setActiveIdx(idx);
      }

      window.setTimeout(() => {
        scrollToTrack(idx);
        setHashHitIdx(idx);
        window.setTimeout(() => setHashHitIdx((current) => (current === idx ? null : current)), 1800);
      }, 120);
    };

    handleHash();
    window.addEventListener("hashchange", handleHash);
    return () => window.removeEventListener("hashchange", handleHash);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.id]);

  useEffect(() => {
    if (typeof window === "undefined" || !("mediaSession" in navigator) || !("MediaMetadata" in window)) {
      return;
    }

    publishNowPlayingMetadata();

    return () => {
      navigator.mediaSession.metadata = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.id, detail.title, nowPlayingArtist, activeSource.kind, activeSource.sourceUrl]);

  useEffect(() => {
    if (typeof window === "undefined" || !("mediaSession" in navigator)) {
      return;
    }

    navigator.mediaSession.playbackState = isPlaying ? "playing" : "paused";

    try {
      navigator.mediaSession.setPositionState({
        duration: Math.max(0, detail.duration),
        playbackRate: 1,
        position: clamp(currentTime, 0, Math.max(0, detail.duration)),
      });
    } catch {
      // Position state support is uneven, especially around embedded players.
    }
  }, [currentTime, detail.duration, isPlaying]);

  useEffect(() => {
    return () => {
      stopHeroRail();
      destroyPlayers();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const progressPercent =
    detail.duration > 0 ? clamp((currentTime / detail.duration) * 100, 0, 100) : 0;
  const currentTimeLabel = formatDuration(currentTime);
  const deleteRedirectHref = detail.artists[0]?.slug
    ? buildArtistHref({ slug: detail.artists[0].slug })
    : "/";
  return (
    <div
      className={styles.root}
      data-yt-embed-blocked={ytEmbedBlocked ? "true" : undefined}
    >
      <ArchiveScrollRoot />
      <ArchiveHeader
        hideScopeToggle
        navLinks={[
          { label: "Playback", href: "#workspace" },
        ]}
      />

      <main className="shell detail-shell">
        <section className="section" id="overview">
          <div className="section-inner">
            <div className="kicker">Set Intelligence Deck</div>
            <div className="set-hero">
              <div className="set-hero-grid">
                <div className="set-hero-main" ref={heroMainRef}>
                  {model.heroImageUrl ? (
                    <img alt={`${detail.title} cover image`} loading="eager" src={model.heroImageUrl} />
                  ) : (
                    <div className="set-hero-main-empty">No set image available</div>
                  )}
                  <h2
                    className={joinClasses(
                      "set-hero-title-overlay",
                      model.heroTitleVariant === "long" && "long",
                      model.heroTitleVariant === "xlong" && "xlong",
                    )}
                    data-min-size={model.heroTitleMinSize}
                    ref={heroTitleRef}
                  >
                    {detail.title}
                  </h2>
                </div>
                <div className="set-hero-side" ref={heroSideRef}>
                  {model.heroCards.length > 0 ? (
                    <div
                      className="set-hero-side-viewport"
                      onMouseEnter={stopHeroRail}
                      onMouseLeave={startHeroRail}
                      ref={heroViewportRef}
                    >
                      <div className="set-hero-side-track" ref={heroTrackRef}>
                        {[...model.heroCards, ...model.heroCards].map((card, index) => (
                          <button
                            className={joinClasses(
                              "set-hero-card",
                              "js-hero-jump",
                              activeIdx === card.idx && "active",
                            )}
                            data-time={card.start.toFixed(3)}
                            data-track-idx={String(card.idx)}
                            key={`${card.idx}-${index}`}
                            onClick={() => jumpTo(card.start, true, true)}
                            title={`Jump to track ${card.idx}`}
                            type="button"
                          >
                            <div className="set-hero-card-media">
                              <img alt="" loading="lazy" src={card.imageUrl} />
                            </div>
                            <div className="set-hero-card-meta">
                              <p className="set-hero-card-artist">{card.artist}</p>
                              <p className="set-hero-card-title">{card.title}</p>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="set-hero-side-empty">No track cards available.</div>
                  )}
                </div>
              </div>
            </div>

            <div className="stats-grid">
              <div className="stat">
                <span className="stat-value">{detail.stats.totalTracks}</span>
                <span className="stat-label">Tracks</span>
              </div>
              <div className="stat">
                <span className="stat-value">{model.identificationRate}%</span>
                <span className="stat-label">Identified</span>
              </div>
              <div className="stat">
                <span className="stat-value">{model.confidenceRate}%</span>
                <span className="stat-label">High / Medium</span>
              </div>
              <div className="stat">
                <span className="stat-value">{detail.stats.distinctArtists}</span>
                <span className="stat-label">Distinct Artists</span>
              </div>
            </div>

            <div className="cluster-row">
              {management.canDeleteSet && management.deleteImpact ? (
                <ArchiveDeleteControl
                  entityType="set"
                  impact={management.deleteImpact}
                  leadingNode={management.submittedByViewer ? <SubmittedByYouBadge /> : undefined}
                  redirectHref={deleteRedirectHref}
                  slug={detail.slug}
                  title={detail.title}
                />
              ) : null}
              <span className="cluster-pill">{detail.durationFmt}</span>
              <span className="cluster-pill">{model.tempoSpan}</span>
              <span className="cluster-pill">Generated {model.generatedDisplay}</span>
            </div>
          </div>
        </section>

        <section className="section" id="workspace" style={{ position: "relative" }}>
          <div className={styles.workspaceSpotifyDock} style={{ position: "absolute", right: 24, top: 18, zIndex: 500 }}>
            <SpotifyExportButton
              counts={spotifyExportCounts}
              entityType="set"
              slug={detail.slug}
            />
          </div>
          <div className="section-inner">
            <div className="section-head">
              <h2 className="set-workspace-heading">Playback Workspace</h2>
              <p>Start at the embedded source, scan timeline confidence, and inspect full track evidence below.</p>
            </div>

            <div className="panel timeline-journey-panel" id="timeline">
              <div
                className={joinClasses(
                  activeSource.frameClass,
                  ytEmbedBlocked && "is-youtube-error",
                  scEmbedBlocked && "is-embed-error",
                )}
                id="sourcePlayerFrame"
              >
                {activeSource.kind === "youtube" && !ytEmbedBlocked ? (
                  <div className="youtube-player-host" ref={youtubeHostRef} />
                ) : null}
                {activeSource.kind === "soundcloud" && !scEmbedBlocked ? (
                  <iframe
                    allow="autoplay"
                    loading="lazy"
                    ref={soundCloudFrameRef}
                    src={activeSource.embedSrc}
                    title="Set source player"
                  />
                ) : null}
                {ytEmbedBlocked ? (
                  <div className="source-player-error-note">
                    Embedded player is prevented by the video uploader.
                  </div>
                ) : null}
                {scEmbedBlocked ? (
                  <div className="source-player-error-note">
                    SoundCloud embedded player requires validation in this browser. Use Open Source to continue.
                  </div>
                ) : null}
                {activeSource.kind === "fallback" ? (
                  <div className="source-player-fallback">
                    Embedded playback is unavailable for this source.
                    <br />
                    <a href={activeSource.sourceUrl} rel="noopener" target="_blank">
                      Open original source
                    </a>
                    .
                  </div>
                ) : null}
                {activeSource.kind === "missing" ? (
                  <div className="source-player-fallback">No source URL available for this set.</div>
                ) : null}
              </div>

              <div className="timeline-wrap">
                <div className="timeline-bar">
                  {model.tracks.map((track) => {
                    const segmentTitle = `${track.artist} — ${track.title}`;
                    const isActive = activeIdx === track.idx;
                    const isDim = !visibleTrackIds.has(track.idx);
                    const isHovered = hoveredTrackIdx === track.idx && activeIdx !== track.idx;
                    const segmentClass =
                      track.conf === "HIGH"
                        ? "conf-high"
                        : track.conf === "MEDIUM"
                          ? "conf-medium"
                          : track.conf === "LOW"
                            ? "conf-low"
                            : "conf-uncertain";

                    return (
                      <button
                        className={joinClasses(
                          "timeline-segment",
                          segmentClass,
                          isDim && "dim",
                          isActive && "active",
                          isHovered && "hover",
                        )}
                        data-track-idx={String(track.idx)}
                        key={track.idx}
                        onClick={() => {
                          if (activeIdx === track.idx) {
                            clearActiveTrack();
                            return;
                          }
                          jumpTo(track.start, ytEmbedBlocked && activeSource.kind === "youtube", true);
                        }}
                        onMouseEnter={(event) => {
                          setHoveredTrackIdx(track.idx);
                          setTimelineTooltip({
                            badge: track.conf,
                            badgeColor:
                              track.conf === "HIGH"
                                ? "#6fffa4"
                                : track.conf === "MEDIUM"
                                  ? "#ffd166"
                                  : track.conf === "LOW"
                                    ? "#ffa55a"
                                    : "#7b7b7b",
                            sub: track.timeRange,
                            title: `Track #${track.idx} · ${segmentTitle}`,
                            x: event.clientX,
                            y: event.clientY,
                          });
                        }}
                        onMouseLeave={() => {
                          setHoveredTrackIdx(null);
                          setTimelineTooltip(null);
                        }}
                        onMouseMove={(event) =>
                          setTimelineTooltip((current) =>
                            current
                              ? {
                                ...current,
                                x: event.clientX,
                                y: event.clientY,
                              }
                              : current,
                          )
                        }
                        style={{
                          left: `${((track.start / Math.max(detail.duration, 1)) * 100).toFixed(4)}%`,
                          width: `${Math.max(
                            ((track.endResolved - track.start) / Math.max(detail.duration, 1)) * 100,
                            0.5,
                          ).toFixed(4)}%`,
                        }}
                        title={segmentTitle}
                        type="button"
                      />
                    );
                  })}
                </div>
                <div className="timeline-ticks">
                  {model.ticks.map((tick) => (
                    <span key={tick}>{tick}</span>
                  ))}
                </div>
              </div>

              <div className="workspace-actions">
                {sourceSwitcherSources.length >= 2 ? (
                  <div aria-label="Choose playback source" className="source-switcher" role="group">
                    {sourceSwitcherSources.map((source) => (
                      <button
                        aria-pressed={activeSource.sourceUrl === source.sourceUrl}
                        className={joinClasses("source-switcher-option", activeSource.sourceUrl === source.sourceUrl && "active")}
                        key={source.sourceUrl}
                        onClick={() => setSelectedSourceUrl(source.sourceUrl)}
                        type="button"
                      >
                        {source.kind === "soundcloud" ? "Soundcloud" : "Youtube"}
                      </button>
                    ))}
                  </div>
                ) : null}
                {activeSource.sourceUrl ? (
                  <a className="source-player-open" href={activeSource.sourceUrl} rel="noopener" target="_blank">
                    Open Source
                  </a>
                ) : null}
                <button
                  aria-controls="journeyPanel"
                  aria-expanded={journeyOpen}
                  className={joinClasses("btn", "journey-toggle-btn", journeyOpen && "active")}
                  id="journeyToggleBtn"
                  onClick={() => {
                    setJourneyOpen((current) => !current);
                    setJourneyTooltip(null);
                  }}
                  type="button"
                >
                  {journeyOpen ? "Hide Journey Lens" : "Show Journey Lens"}
                </button>
              </div>
              {!journeyOpen ? null : (
                <div className="journey-panel" id="journeyPanel">
                  <div className="journey-controls">
                    {(["bpm", "energy", "dance"] as JourneyMetric[]).map((metric) => (
                      <button
                        className={joinClasses("btn", activeMetrics.includes(metric) && "active")}
                        data-metric={metric}
                        key={metric}
                        onClick={() =>
                          setActiveMetrics((current) =>
                            current.includes(metric)
                              ? current.filter((entry) => entry !== metric)
                              : [...current, metric],
                          )
                        }
                        type="button"
                      >
                        {metric === "bpm" ? "BPM" : metric === "energy" ? "Energy" : "Dance"}
                      </button>
                    ))}
                  </div>

                  <div className="journey-chart-wrap" id="journeyWrap">
                    {journeyView.leftAxis ? (
                      <div className="journey-yaxis-left">
                        {journeyView.leftAxis.ticks.map((tick) => (
                          <span className="journey-axis-tick" key={`left-${tick.label}-${tick.top}`} style={{ top: tick.top }}>
                            {tick.label}
                          </span>
                        ))}
                        {journeyView.leftAxis.metrics.length > 0 ? (
                          <span className="journey-axis-metrics">
                            {journeyView.leftAxis.metrics.map((metric) => (
                              <span className="journey-axis-metric" key={metric} style={{ color: JOURNEY_COLORS[metric] }}>
                                {JOURNEY_CODES[metric]}
                              </span>
                            ))}
                          </span>
                        ) : null}
                      </div>
                    ) : null}

                    <svg id="journeySvg" preserveAspectRatio="none" viewBox="0 0 1000 260">
                      {journeyView.layers.map((layer) => (
                        <g key={layer.metric}>
                          <path d={layer.d} fill="none" stroke={layer.color} strokeWidth="2" />
                          {layer.points.map((point) => {
                            const isPointActive = activeIdx === point.idx;
                            return (
                              <circle
                                className={joinClasses("journey-point", isPointActive && "active")}
                                cx={point.cx}
                                cy={point.cy}
                                data-track-idx={String(point.idx)}
                                fill={layer.color}
                                key={`${layer.metric}-${point.idx}`}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  const track = model.tracks.find((entry) => entry.idx === point.idx);
                                  if (track) {
                                    jumpTo(track.start, false, true);
                                  }
                                }}
                                onMouseEnter={(event) =>
                                  setJourneyTooltip({
                                    title: point.title,
                                    value:
                                      point.metric === "bpm"
                                        ? `BPM ${point.value.toFixed(1)}`
                                        : `${point.metric === "energy" ? "Energy" : "Dance"} ${point.value.toFixed(2)}`,
                                    x: event.clientX,
                                    y: event.clientY,
                                  })
                                }
                                onMouseLeave={() => setJourneyTooltip(null)}
                                onMouseMove={(event) =>
                                  setJourneyTooltip((current) =>
                                    current
                                      ? {
                                        ...current,
                                        x: event.clientX,
                                        y: event.clientY,
                                      }
                                      : current,
                                  )
                                }
                                r="4"
                              />
                            );
                          })}
                        </g>
                      ))}
                    </svg>

                    {journeyView.rightAxis ? (
                      <div className="journey-yaxis-right">
                        {journeyView.rightAxis.ticks.map((tick) => (
                          <span className="journey-axis-tick" key={`right-${tick.label}-${tick.top}`} style={{ top: tick.top }}>
                            {tick.label}
                          </span>
                        ))}
                        {journeyView.rightAxis.metrics.length > 0 ? (
                          <span className="journey-axis-metrics">
                            {journeyView.rightAxis.metrics.map((metric) => (
                              <span className="journey-axis-metric" key={metric} style={{ color: JOURNEY_COLORS[metric] }}>
                                {JOURNEY_CODES[metric]}
                              </span>
                            ))}
                          </span>
                        ) : null}
                      </div>
                    ) : null}

                    {!journeyView.empty ? null : (
                      <div className="journey-empty">No track metrics available for this set.</div>
                    )}
                  </div>

                  <div className="journey-legend">
                    <span className="journey-key">
                      <span className="journey-dot" style={{ background: JOURNEY_COLORS.bpm }} />
                      BPM
                    </span>
                    <span className="journey-key">
                      <span className="journey-dot" style={{ background: JOURNEY_COLORS.energy }} />
                      Energy
                    </span>
                    <span className="journey-key">
                      <span className="journey-dot" style={{ background: JOURNEY_COLORS.dance }} />
                      Dance
                    </span>
                  </div>
                </div>
              )}

              <div className="timeline-track-atlas" id="tracks">
                <h2 className="panel-title">Track Atlas</h2>
                <p className="panel-sub">Search, slice, and inspect evidence for each detected track.</p>
                <div className="track-explorer-panel">
                  <div className="track-head">
                    <div className="controls track-atlas-controls">
                      <input
                        className="input compact-control"
                        id="trackSearchInput"
                        onChange={(event) => {
                          const nextValue = event.target.value;
                          startTransition(() => setQuery(nextValue));
                        }}
                        placeholder="Search by artist or title..."
                        type="search"
                        value={query}
                      />
                      <div className="controls-row">
                        <button
                          className={joinClasses("btn", confidenceFilter === "all" && "active")}
                          onClick={() => setConfidenceFilter("all")}
                          type="button"
                        >
                          All
                        </button>
                        {CONFIDENCE_LEVELS.filter((level) => model.confidenceCounts[level] > 0).map((level) => (
                          <button
                            className={joinClasses("btn", confidenceFilter === level && "active")}
                            key={level}
                            onClick={() => setConfidenceFilter(level)}
                            type="button"
                          >
                            {level}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="tracklist" id="tracklist">
                    {confidenceFilteredTracks.map((track) => {
                      const isActive = activeIdx === track.idx;
                      const isHashHit = hashHitIdx === track.idx;
                      const isSpotifyOpen = openSpotifyIdxs.includes(track.idx);
                      const areDetailsOpen = openDetailIdxs.includes(track.idx);
                      const confidenceClass =
                        track.conf === "HIGH"
                          ? "conf-high"
                          : track.conf === "MEDIUM"
                            ? "conf-medium"
                            : track.conf === "LOW"
                              ? "conf-low"
                              : "conf-uncertain";
                      const showSpotifyButton = !track.isUnknownTrack && Boolean(track.spotifyTrackId);
                      const showYouTubeButton =
                        !track.isUnknownTrack && !showSpotifyButton && Boolean(track.directYouTubeUrl);
                      const showDiscogsButton =
                        !track.isUnknownTrack &&
                        !showSpotifyButton &&
                        !showYouTubeButton &&
                        Boolean(track.directDiscogsUrl);

                      return (
                        <article
                          className={joinClasses(
                            "track-card",
                            isActive && "active",
                            isHashHit && "hash-hit",
                          )}
                          data-track-idx={String(track.idx)}
                          id={`track-${track.idx}`}
                          key={track.idx}
                          onMouseEnter={() => setHoveredTrackIdx(track.idx)}
                          onMouseLeave={() => setHoveredTrackIdx(null)}
                        >
                          <div className="track-grid">
                            <div className="track-index">{track.idx}</div>
                            <div className="track-art">
                              {track.albumArt ? (
                                <img alt="" src={track.albumArt} />
                              ) : (
                                <span className="track-art--empty">♪</span>
                              )}
                            </div>
                              <div className="track-time-col">
                                <button
                                  className={joinClasses(
                                    "btn",
                                    "track-tool-btn",
                                    "js-track-play",
                                    isActive && isPlaying && "active",
                                  )}
                                  data-time={track.start.toFixed(3)}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    if (ytEmbedBlocked && activeSource.kind === "youtube") {
                                      jumpTo(track.start, true, false);
                                      const sourceLink = buildSourceLinkAt(activeSource, track.start);
                                      if (sourceLink) {
                                        window.open(sourceLink, "_blank", "noopener");
                                      }
                                      return;
                                    }

                                    if (activeIdx === track.idx) {
                                      togglePlay();
                                      return;
                                    }

                                    jumpTo(track.start, true, true);
                                  }}
                                  title={
                                    ytEmbedBlocked && activeSource.kind === "youtube"
                                      ? "Open source on YouTube at this timestamp"
                                      : "Play / pause at this track"
                                  }
                                  type="button"
                                >
                                  {ytEmbedBlocked && activeSource.kind === "youtube"
                                    ? "YT"
                                    : isActive && isPlaying
                                      ? "❚❚"
                                      : "▶"}
                                </button>
                                <span className="track-time-label" title="Track timestamp">
                                  {track.startFmt}
                                </span>
                              </div>
                              <div className="track-main">
                                <div className="track-title-row">
                                  <span className="track-artist">{track.artist}</span>
                                  <span className="track-sep">—</span>
                                  <span className="track-title">{track.title}</span>
                                </div>
                                <div className="track-meta">
                                  <span className={joinClasses("pill", "confidence-pill", confidenceClass)}>{track.conf}</span>
                              </div>
                            </div>
                            <div className="track-actions">
                              {showSpotifyButton ? (
                                <button
                                  className="btn track-tool-btn embed-btn js-spotify-embed"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    setOpenSpotifyIdxs((current) =>
                                      current.includes(track.idx)
                                        ? current.filter((entry) => entry !== track.idx)
                                        : [...current, track.idx],
                                    );
                                  }}
                                  type="button"
                                >
                                  Spotify
                                </button>
                              ) : null}
                              {showYouTubeButton ? (
                                <a
                                  className="action-link youtube"
                                  href={track.directYouTubeUrl ?? track.youtubeResolvedUrl}
                                  onClick={(event) => event.stopPropagation()}
                                  rel="noopener"
                                  target="_blank"
                                >
                                  YouTube
                                </a>
                              ) : null}
                              {showDiscogsButton ? (
                                <a
                                  className="action-link discogs"
                                  href={track.directDiscogsUrl ?? track.discogsResolvedUrl}
                                  onClick={(event) => event.stopPropagation()}
                                  rel="noopener"
                                  target="_blank"
                                >
                                  Discogs
                                </a>
                              ) : null}
                              <button
                                className={joinClasses("btn", "track-tool-btn", areDetailsOpen && "active")}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setOpenDetailIdxs((current) =>
                                    current.includes(track.idx)
                                      ? current.filter((entry) => entry !== track.idx)
                                      : [...current, track.idx],
                                  );
                                }}
                                type="button"
                              >
                                Details
                              </button>
                            </div>
                          </div>

                          <div className="spotify-inline" hidden={!isSpotifyOpen}>
                            {isSpotifyOpen && track.spotifyTrackId ? (
                              <iframe
                                allow="autoplay; clipboard-write; encrypted-media"
                                frameBorder="0"
                                height="80"
                                loading="lazy"
                                src={`https://open.spotify.com/embed/track/${track.spotifyTrackId}?utm_source=generator&theme=0`}
                                style={{ borderRadius: 0 }}
                                title={`${track.artist} ${track.title} Spotify embed`}
                                width="100%"
                              />
                            ) : null}
                          </div>

                          <div className="track-details" hidden={!areDetailsOpen}>
                            {!track.isUnknownTrack ? (
                              <div className="track-external-links in-details">
                                <a
                                  className={joinClasses(
                                    "action-link",
                                    "spotify",
                                    !track.directSpotifyUrl && "fallback",
                                  )}
                                  href={track.spotifyResolvedUrl}
                                  onClick={(event) => event.stopPropagation()}
                                  rel="noopener"
                                  target="_blank"
                                >
                                  {track.spotifyLinkLabel}
                                </a>
                                <a
                                  className={joinClasses(
                                    "action-link",
                                    "youtube",
                                    !track.directYouTubeUrl && "fallback",
                                  )}
                                  href={track.youtubeResolvedUrl}
                                  onClick={(event) => event.stopPropagation()}
                                  rel="noopener"
                                  target="_blank"
                                >
                                  {track.youtubeLinkLabel}
                                </a>
                                <a
                                  className={joinClasses(
                                    "action-link",
                                    "discogs",
                                    !track.directDiscogsUrl && "fallback",
                                  )}
                                  href={track.discogsResolvedUrl}
                                  onClick={(event) => event.stopPropagation()}
                                  rel="noopener"
                                  target="_blank"
                                >
                                  {track.discogsLinkLabel}
                                </a>
                              </div>
                            ) : null}

                            <div className="details-grid">
                              <div className="detail-item">
                                <span className="detail-k">Detections</span>
                                <span className="detail-v">{track.detectionCount}</span>
                              </div>
                              <div className="detail-item">
                                <span className="detail-k">Density</span>
                                <span className="detail-v">{track.densityPct.toFixed(0)}%</span>
                              </div>
                              <div className="detail-item">
                                <span className="detail-k">Cluster Span</span>
                                <span className="detail-v">
                                  {track.clusterSpan != null ? `${track.clusterSpan} seg` : "—"}
                                </span>
                              </div>
                              <div className="detail-item">
                                <span className="detail-k">Window</span>
                                <span className="detail-v">{track.timeRange}</span>
                              </div>
                              {track.bpm != null ? (
                                <div className="detail-item">
                                  <span className="detail-k">BPM</span>
                                  <span className="detail-v">{track.bpm.toFixed(1)}</span>
                                </div>
                              ) : null}
                              {track.detailGenres.length > 0 ? (
                                <div className="detail-item">
                                  <span className="detail-k">Genres</span>
                                  <span className="detail-v">{track.detailGenres.join(", ")}</span>
                                </div>
                              ) : null}
                              {track.label ? (
                                <div className="detail-item">
                                  <span className="detail-k">Label</span>
                                  <span className="detail-v">{track.label}</span>
                                </div>
                              ) : null}
                              {track.key ? (
                                <div className="detail-item">
                                  <span className="detail-k">Key</span>
                                  <span className="detail-v">{track.key}</span>
                                </div>
                              ) : null}
                              {track.energy != null ? (
                                <div className="detail-item">
                                  <span className="detail-k">Energy</span>
                                  <span className="detail-v">{track.energy.toFixed(2)}</span>
                                </div>
                              ) : null}
                              {track.dance != null ? (
                                <div className="detail-item">
                                  <span className="detail-k">Dance</span>
                                  <span className="detail-v">{track.dance.toFixed(2)}</span>
                                </div>
                              ) : null}
                              <div className="detail-item">
                                <span className="detail-k">Density Bar</span>
                                <div className="detail-density-bar">
                                  <div
                                    className="detail-density-fill"
                                    style={{ width: `${track.densityPct.toFixed(1)}%` }}
                                  />
                                </div>
                              </div>
                            </div>
                          </div>
                        </article>
                      );
                    })}
                  </div>

                  <div className="no-results" style={{ display: confidenceFilteredTracks.length ? "none" : "block" }}>
                    No tracks match the active filters.
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <div className="footer-note">Generated {model.generatedDisplay} · Set Signal Explorer</div>
      </main>

      {showDock ? (
        <div className="dock" id="playerDock">
          <div className="dock-grid">
            <div className="dock-art-frame">
              {activeTrack?.albumArt ? (
                <img
                  alt=""
                  className={joinClasses("dock-art", "visible")}
                  id="dockArt"
                  loading="lazy"
                  src={activeTrack.albumArt}
                />
              ) : null}
              <div className={joinClasses("dock-art-fallback", activeTrack?.albumArt && "hidden")} id="dockArtFallback">
                ♫
              </div>
            </div>
            <div className="dock-now">
              <div>
                <div className="dock-track" id="dockTrack">
                  {activeTrack?.title ?? "No active track"}
                </div>
                <div className="dock-artist" id="dockArtist">
                  {activeTrack?.artist ?? "—"}
                </div>
              </div>
            </div>

            <div className="dock-center">
              <div className="dock-main-row">
                <div className="dock-primary-controls">
                  <button className="dock-mini-btn" onClick={() => jumpTo(currentTime - 15, false, true)} title="Back 15 seconds" type="button">
                    -15
                  </button>
                  <button className="dock-nav-btn" onClick={previousTrack} title="Previous track" type="button">
                    {"\u23EE\uFE0E"}
                  </button>
                  <button
                    className={joinClasses("dock-play-btn", isPlaying && "is-playing")}
                    onClick={togglePlay}
                    title="Play / pause"
                    type="button"
                  >
                    {isPlaying ? "❚❚" : "▶"}
                  </button>
                  <button className="dock-nav-btn" onClick={nextTrack} title="Next track" type="button">
                    {"\u23ED\uFE0E"}
                  </button>
                  <button className="dock-mini-btn" onClick={() => jumpTo(currentTime + 15, false, true)} title="Forward 15 seconds" type="button">
                    +15
                  </button>
                </div>
              </div>

              <div className="dock-range">
                <div className="dock-time">
                  <span id="dockCurrentTime">{currentTimeLabel}</span>
                  <span>{detail.durationFmt}</span>
                </div>
                <div
                  className="dock-progress"
                  id="dockProgress"
                  onClick={(event) => {
                    const rect = event.currentTarget.getBoundingClientRect();
                    const fraction = clamp((event.clientX - rect.left) / rect.width, 0, 1);
                    jumpTo(fraction * detail.duration, false, true);
                  }}
                >
                  <div className="dock-progress-fill" id="dockProgressFill" style={{ width: `${progressPercent}%` }} />
                </div>
              </div>
            </div>

            <div className="dock-actions">
              <button
                className="dock-util-btn"
                onClick={() => {
                  const workspaceHeading = document.querySelector<HTMLElement>("#workspace .set-workspace-heading");
                  if (workspaceHeading) {
                    const topbar = document.querySelector<HTMLElement>(".topbar");
                    const offset = (topbar?.offsetHeight ?? 0) + 6;
                    const rect = workspaceHeading.getBoundingClientRect();
                    const targetTop = Math.max(0, window.scrollY + rect.top - offset);
                    window.scrollTo({ behavior: "smooth", top: targetTop });
                    return;
                  }
                  window.scrollTo({ behavior: "smooth", top: 0 });
                }}
                type="button"
              >
                <span className="dock-util-icon" aria-hidden="true">
                  ↑
                </span>
                <span>Top</span>
              </button>
              <button
                className="dock-util-btn"
                onClick={() => {
                  if (activeIdx != null) {
                    scrollToTrack(activeIdx);
                  }
                }}
                type="button"
              >
                <span className="dock-util-icon" aria-hidden="true">
                  ↓
                </span>
                <span>Track</span>
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {timelineTooltip ? (
        <div
          className="tooltip visible"
          id="tl-tooltip"
          style={{
            left: timelineTooltip.x + TOOLTIP_OFFSET,
            top: timelineTooltip.y + TOOLTIP_OFFSET,
          }}
        >
          <div className="tt-title">{timelineTooltip.title}</div>
          <div className="tt-sub">{timelineTooltip.sub}</div>
          <div className="tt-badge" style={{ borderColor: timelineTooltip.badgeColor, color: timelineTooltip.badgeColor }}>
            {timelineTooltip.badge}
          </div>
        </div>
      ) : null}

      {journeyTooltip ? (
        <div
          className="tooltip visible"
          id="journey-tooltip"
          style={{
            left: journeyTooltip.x + TOOLTIP_OFFSET,
            top: journeyTooltip.y + TOOLTIP_OFFSET,
          }}
        >
          <div className="jt-title">{journeyTooltip.title}</div>
          <div className="jt-value">{journeyTooltip.value}</div>
        </div>
      ) : null}
    </div>
  );
}

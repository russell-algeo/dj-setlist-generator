export type ArchiveConfidence = "HIGH" | "MEDIUM" | "LOW" | "UNCERTAIN";

export type ArchiveEntityResolution =
  | {
      entityType: "artist";
      entityId: string;
      legacyPath: string;
      slug: string;
    }
  | {
      entityType: "set";
      entityId: string;
      legacyPath: string;
      slug: string;
    };

export type ArchiveSetTrack = {
  idx: number;
  artist: string;
  title: string;
  start: number;
  end: number | null;
  startFmt: string;
  endFmt: string | null;
  conf: ArchiveConfidence;
  albumArt: string | null;
  previewUrl: string | null;
  bpm: number | null;
  energy: number | null;
  dance: number | null;
  key: string | null;
  genres: string[];
  detailGenres: string[];
  label: string | null;
  labelUrl: string | null;
  spotifyUrl: string | null;
  youtubeUrl: string | null;
  discogsUrl: string | null;
  detectionCount: number;
  clusterDensity: number | null;
  clusterSpan: number | null;
  sourceDeepLink: string | null;
};

export type ArchiveJourneyPoint = {
  idx: number;
  start: number;
  artist: string;
  title: string;
  bpm: number | null;
  energy: number | null;
  dance: number | null;
};

export type ArchiveSetTimelineSegment = {
  idx: number;
  leftPct: number;
  widthPct: number;
  conf: ArchiveConfidence;
  label: string;
  timeRange: string;
};

export type ArchiveSetDetail = {
  id: string;
  slug: string;
  legacyPath: string | null;
  title: string;
  artistName: string | null;
  artists: Array<{
    id: string;
    name: string;
    slug: string;
  }>;
  heroImageUrl: string | null;
  thumbnailUrl: string | null;
  sourcePlatform: string | null;
  sourceUrl: string | null;
  embedUrl: string | null;
  duration: number;
  durationFmt: string;
  recognitionRate: number | null;
  generatedAt: string | null;
  stats: {
    totalTracks: number;
    identifiedTracks: number;
    highOrMediumTracks: number;
    distinctArtists: number;
  };
  highlightedTracks: ArchiveSetTrack[];
  timeline: ArchiveSetTimelineSegment[];
  tracks: ArchiveSetTrack[];
  journeyPoints: ArchiveJourneyPoint[];
};

export type ArchiveArtistSetTrackRef = {
  end: number | null;
  endTimeFormatted: string | null;
  isUnknown: boolean;
  position: number;
  artist: string;
  start: number;
  title: string;
  startTimeFormatted: string;
  confidence: ArchiveConfidence;
  spotifyUrl: string | null;
  trackHref: string | null;
  trackKey: string;
};

export type ArchiveArtistSet = {
  id: string;
  slug: string;
  legacyPath: string | null;
  title: string;
  sourceUrl: string | null;
  thumbnailUrl: string | null;
  duration: number;
  durationFmt: string;
  totalTracks: number;
  recognizedTracks: number;
  recognitionRate: number | null;
  confidenceCounts: Record<ArchiveConfidence, number>;
  trackSearchText: string;
  tracks: ArchiveArtistSetTrackRef[];
};

export type ArchiveRecurringTrack = {
  trackKey: string;
  artist: string;
  title: string;
  appearances: number;
  confidenceCounts: Record<ArchiveConfidence, number>;
  albumArt: string | null;
  spotifyUrl: string | null;
  genres: string[];
  label: string | null;
  setRefs: Array<{
    setTitle: string;
    href: string | null;
    confidence: ArchiveConfidence;
    position: number | null;
  }>;
};

export type ArchiveArtistAtlasTrack = {
  idx: number;
  trackKey: string;
  artist: string;
  title: string;
  confidence: ArchiveConfidence;
  time: string;
  genres: string[];
  label: string | null;
  labelUrl: string | null;
  spotifyUrl: string | null;
  youtubeUrl: string | null;
  discogsUrl: string | null;
  albumArt: string | null;
  setId: string;
  setLegacyPath: string | null;
  setSlug: string;
  setAnchor: string | null;
  sourceDeepLink: string | null;
  timeRange: string;
  setTitle: string;
};

export type ArchiveArtistSummary = {
  id: string;
  slug: string;
  legacyPath: string | null;
  name: string;
  imageUrl: string | null;
  heroImageUrl: string | null;
  generatedAt: string | null;
  stats: {
    setsAnalyzed: number;
    uniqueTracks: number;
    totalDetections: number;
    recurringTracks: number;
  };
  topGenres: string[];
  topLabels: Array<{
    name: string;
    count: number;
  }>;
  recurringTracks: ArchiveRecurringTrack[];
  sets: ArchiveArtistSet[];
  atlasTracks: ArchiveArtistAtlasTrack[];
  failedSets: Array<{
    title: string;
    url: string | null;
    reason: string | null;
  }>;
};

export type ArchiveHomeArtistCard = {
  id: string;
  slug: string;
  legacyPath: string | null;
  name: string;
  imageUrl: string | null;
  setCount: number;
  recognizedTracks: number;
  latestSetTitle: string | null;
  latestSetPath: string | null;
};

export type ArchiveHomeConnection = {
  artistA: string;
  artistASlug: string;
  artistALegacyPath: string | null;
  artistB: string;
  artistBSlug: string;
  artistBLegacyPath: string | null;
  sharedTracks: number;
};

export type ArchiveHomeSetCard = {
  id: string;
  slug: string;
  legacyPath: string | null;
  title: string;
  artistName: string | null;
  sourceUrl: string | null;
  thumbnailUrl: string | null;
  duration: number;
  durationFmt: string;
  totalTracks: number;
  recognitionRate: number | null;
};

export type ArchiveHomeBaseSummary = {
  generatedAt: string | null;
  globalStats: {
    totalArtists: number;
    totalSets: number;
    totalRecognizedTracks: number;
    totalTrackEntries: number;
    unknownRatio: number;
  };
  featuredArtists: ArchiveHomeArtistCard[];
  setLibrary: {
    items: ArchiveHomeSetCard[];
    page: number;
    pageSize: number;
    totalItems: number;
    query: string;
  };
};

export type ArchiveHomeConnectionsResponse = {
  connections: ArchiveHomeConnection[];
  generatedAt: string | null;
};

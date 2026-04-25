import type { ArchiveConfidence } from "@/lib/archive/types";

export type ArchiveHomeCompareMode = "intersection" | "union";
export type ArchiveHomePairLens = "artists" | "genres" | "labels" | "tracks";
export type ArchiveHomeSetSort = "default" | "duration" | "rate" | "tracks";
export type ArchiveHomeTaxonomyLens = "genres" | "labels" | "track-artists" | "tracks";

export type ArchiveHomeArtistCard = {
  id: string;
  imageUrl: string | null;
  name: string;
  setCount: number;
  slug: string;
  submittedByViewer?: boolean;
  totalAppearances: number;
  uniqueTracks: number;
};

export type ArchiveHomeHeroSet = {
  artistName: string;
  artistSlug: string;
  duration: number;
  id: string;
  recognitionRate: number | null;
  slug: string;
  submittedByViewer?: boolean;
  thumbnailUrl: string | null;
  title: string;
  totalTracks: number;
};

export type ArchiveHomeTrackSetRef = {
  confidence: ArchiveConfidence;
  setSlug: string;
  title: string;
  trackPosition: number;
};

export type ArchiveHomeTrackArtistRef = {
  appearances: number;
  artistName: string;
  artistSlug: string;
  setRefs: ArchiveHomeTrackSetRef[];
};

export type ArchiveHomeTrackCatalogItem = {
  albumArt: string | null;
  artist: string;
  artistImage: string | null;
  artistProfileImage: string | null;
  artistRefs: ArchiveHomeTrackArtistRef[];
  artistsCount: number;
  confidence: ArchiveConfidence;
  confidenceCounts: Record<ArchiveConfidence, number>;
  genres: string[];
  label: string | null;
  labelUrl: string | null;
  spotifyUrl: string | null;
  title: string;
  totalAppearances: number;
  trackKey: string;
};

export type ArchiveHomeAtlasSelectionPayload = {
  compareMode: ArchiveHomeCompareMode;
  focusArtistSlug: string | null;
  generatedAt: string | null;
  selectedArtistSlugs: string[];
  trackCatalog: ArchiveHomeTrackCatalogItem[];
};

export type ArchiveHomeNetworkArtist = {
  id: string;
  name: string;
  setCount: number;
  slug: string;
};

export type ArchiveHomeNetworkEdge = {
  artistA: string;
  artistASlug: string;
  artistB: string;
  artistBSlug: string;
  normalizedScore: number;
  score: number;
  sharedArtistsCount: number;
  sharedGenresCount: number;
  sharedLabelsCount: number;
  sharedTracksCount: number;
};

export type ArchiveHomeNetworkIndexPayload = {
  artists: ArchiveHomeNetworkArtist[];
  edges: ArchiveHomeNetworkEdge[];
};

export type ArchiveHomePairTrack = {
  albumArt: string | null;
  appearancesA: number;
  appearancesB: number;
  artist: string;
  artistImage: string | null;
  artistProfileImage: string | null;
  confidence: ArchiveConfidence;
  confidenceCounts: Record<ArchiveConfidence, number>;
  genres: string[];
  label: string | null;
  labelUrl: string | null;
  setsA: ArchiveHomeTrackSetRef[];
  setsB: ArchiveHomeTrackSetRef[];
  spotifyUrl: string | null;
  title: string;
  trackKey: string;
};

export type ArchiveHomePairBucket = {
  countA: number;
  countB: number;
  id: string;
  name: string;
  trackKeys: string[];
};

export type ArchiveHomePairSelectionPayload = {
  artistA: ArchiveHomeNetworkArtist;
  artistB: ArchiveHomeNetworkArtist;
  normalizedScore: number;
  score: number;
  sharedGenres: ArchiveHomePairBucket[];
  sharedGenresCount: number;
  sharedLabels: ArchiveHomePairBucket[];
  sharedLabelsCount: number;
  sharedMusicArtists: ArchiveHomePairBucket[];
  sharedMusicArtistsCount: number;
  sharedTracks: ArchiveHomePairTrack[];
  sharedTracksCount: number;
};

export type ArchiveHomeSetLibraryTrack = {
  artist: string;
  confidence: ArchiveConfidence;
  position: number;
  setSlug: string;
  spotifyUrl: string | null;
  startTimeFormatted: string;
  title: string;
  trackKey: string;
};

export type ArchiveHomeSetLibraryItem = {
  artistName: string;
  artistSlug: string;
  confidenceCounts: Record<ArchiveConfidence, number>;
  duration: number;
  id: string;
  miniTimeline: Array<{
    confidence: ArchiveConfidence;
    startPct: number;
    widthPct: number;
  }>;
  recognitionRate: number | null;
  slug: string;
  sourcePlatform: string | null;
  sourceUrl: string | null;
  submittedByViewer?: boolean;
  thumbnailUrl: string | null;
  title: string;
  totalTracks: number;
};

export type ArchiveHomeSetLibraryPagePayload = {
  artistFilter: string;
  artistOptions: string[];
  items: ArchiveHomeSetLibraryItem[];
  page: number;
  pageSize: number;
  query: string;
  sort: ArchiveHomeSetSort;
  totalItems: number;
  totalPages: number;
};

export type ArchiveHomeSetTracklistPayload = {
  generatedAt: string | null;
  slug: string;
  tracks: ArchiveHomeSetLibraryTrack[];
};

export type ArchiveHomeBootstrapPayload = {
  artistCards: ArchiveHomeArtistCard[];
  generatedAt: string | null;
  globalStats: {
    confidenceBreakdown: Record<ArchiveConfidence, number>;
    totalAppearances: number;
    totalArtists: number;
    totalSets: number;
    totalUniqueTracks: number;
    unknownRatio: number;
  };
  hero: {
    imageAlt: string;
    imageUrl: string | null;
    railSets: ArchiveHomeHeroSet[];
    tickerItems: string[];
  };
  initialAtlas: ArchiveHomeAtlasSelectionPayload;
  initialNetwork: ArchiveHomeNetworkIndexPayload;
  initialSetLibrary: ArchiveHomeSetLibraryPagePayload;
  scope: "mine" | "global";
};

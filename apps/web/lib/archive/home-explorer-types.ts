import type { ArchiveConfidence } from "@/lib/archive/types";

export type ArchiveHomeCompareMode = "intersection" | "union";
export type ArchiveHomePairLens = "artists" | "genres" | "labels" | "tracks";
export type ArchiveHomeSetSort = "default" | "duration" | "rate" | "tracks";
export type ArchiveHomeTaxonomyLens = "genres" | "labels" | "track-artists" | "tracks";

export type ArchiveHomeArtistCard = {
  id: string;
  imageUrl: string | null;
  legacyPath: string | null;
  name: string;
  setCount: number;
  slug: string;
  totalAppearances: number;
  uniqueTracks: number;
};

export type ArchiveHomeHeroSet = {
  artistLegacyPath: string | null;
  artistName: string;
  artistSlug: string;
  duration: number;
  id: string;
  legacyPath: string | null;
  recognitionRate: number | null;
  slug: string;
  thumbnailUrl: string | null;
  title: string;
  totalTracks: number;
};

export type ArchiveHomeTrackSetRef = {
  confidence: ArchiveConfidence;
  setLegacyPath: string | null;
  setSlug: string;
  title: string;
  trackPosition: number;
};

export type ArchiveHomeTrackArtistRef = {
  appearances: number;
  artistLegacyPath: string | null;
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

export type ArchiveHomeNetworkArtist = {
  id: string;
  legacyPath: string | null;
  name: string;
  setCount: number;
  slug: string;
};

export type ArchiveHomeNetworkEdge = {
  artistA: string;
  artistALegacyPath: string | null;
  artistASlug: string;
  artistB: string;
  artistBLegacyPath: string | null;
  artistBSlug: string;
  normalizedScore: number;
  score: number;
  sharedArtistsCount: number;
  sharedGenresCount: number;
  sharedLabelsCount: number;
  sharedTracksCount: number;
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

export type ArchiveHomePairPayload = {
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
  spotifyUrl: string | null;
  startTimeFormatted: string;
  title: string;
  trackKey: string;
  trackLegacyPath: string | null;
  trackSetSlug: string;
};

export type ArchiveHomeSetLibraryItem = {
  artistLegacyPath: string | null;
  artistName: string;
  artistSlug: string;
  confidenceCounts: Record<ArchiveConfidence, number>;
  duration: number;
  id: string;
  legacyPath: string | null;
  miniTimeline: Array<{
    confidence: ArchiveConfidence;
    startPct: number;
    widthPct: number;
  }>;
  recognitionRate: number | null;
  slug: string;
  sourceUrl: string | null;
  thumbnailUrl: string | null;
  title: string;
  totalTracks: number;
  tracks: ArchiveHomeSetLibraryTrack[];
  trackSearchText: string;
};

export type ArchiveHomeAtlasPayload = {
  allArtistsSelected: boolean;
  artistCards: ArchiveHomeArtistCard[];
  compareMode: ArchiveHomeCompareMode;
  focusArtistSlug: string | null;
  generatedAt: string | null;
  selectedArtistSlugs: string[];
  tickerItems: string[];
  trackCatalog: ArchiveHomeTrackCatalogItem[];
};

export type ArchiveHomeNetworkPayload = {
  artists: ArchiveHomeNetworkArtist[];
  edges: ArchiveHomeNetworkEdge[];
};

export type ArchiveHomeSetLibraryPayload = {
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

export type ArchiveHomeExplorerInitialPayload = {
  allSetLibraryItems: ArchiveHomeSetLibraryItem[];
  artistCards: ArchiveHomeArtistCard[];
  edgeCount: number;
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
  initialAtlas: ArchiveHomeAtlasPayload;
  initialNetwork: ArchiveHomeNetworkPayload;
  initialSetLibrary: ArchiveHomeSetLibraryPayload;
  pairPayloads: Record<string, ArchiveHomePairPayload>;
};

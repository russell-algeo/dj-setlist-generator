import { sql } from "drizzle-orm";
import {
  boolean,
  index,
  integer,
  jsonb,
  numeric,
  pgSchema,
  primaryKey,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";

const timestamps = () => ({
  createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow().notNull(),
});

export const authn = pgSchema("authn");
export const app = pgSchema("app");
export const ops = pgSchema("ops");

export const users = authn.table("users", {
  id: text("id")
    .primaryKey()
    .default(sql`gen_random_uuid()::text`),
  name: text("name"),
  email: text("email").unique(),
  emailVerified: timestamp("email_verified", { withTimezone: true }),
  image: text("image"),
  ...timestamps(),
});

export const accounts = authn.table(
  "accounts",
  {
    userId: text("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    type: text("type").notNull(),
    provider: text("provider").notNull(),
    providerAccountId: text("provider_account_id").notNull(),
    refresh_token: text("refresh_token"),
    access_token: text("access_token"),
    expires_at: integer("expires_at"),
    token_type: text("token_type"),
    scope: text("scope"),
    id_token: text("id_token"),
    session_state: text("session_state"),
  },
  (table) => ({
    compoundPk: primaryKey({
      columns: [table.provider, table.providerAccountId],
    }),
    userIdx: index("accounts_user_id_idx").on(table.userId),
  }),
);

export const sessions = authn.table(
  "sessions",
  {
    sessionToken: text("session_token").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    expires: timestamp("expires", { withTimezone: true }).notNull(),
  },
  (table) => ({
    userIdx: index("sessions_user_id_idx").on(table.userId),
  }),
);

export const verificationTokens = authn.table(
  "verification_tokens",
  {
    identifier: text("identifier").notNull(),
    token: text("token").notNull(),
    expires: timestamp("expires", { withTimezone: true }).notNull(),
  },
  (table) => ({
    compoundPk: primaryKey({
      columns: [table.identifier, table.token],
    }),
  }),
);

export const userProfiles = authn.table(
  "user_profiles",
  {
    userId: text("user_id")
      .primaryKey()
      .references(() => users.id, { onDelete: "cascade" }),
    email: text("email").notNull(),
    displayName: text("display_name"),
    isAllowlisted: boolean("is_allowlisted").default(false).notNull(),
    isAdmin: boolean("is_admin").default(false).notNull(),
    ...timestamps(),
  },
  (table) => ({
    emailIdx: uniqueIndex("user_profiles_email_idx").on(table.email),
  }),
);

export const apiTokens = authn.table(
  "api_tokens",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    name: text("name").notNull(),
    tokenPrefix: text("token_prefix").notNull(),
    tokenHash: text("token_hash").notNull(),
    lastUsedAt: timestamp("last_used_at", { withTimezone: true }),
    revokedAt: timestamp("revoked_at", { withTimezone: true }),
    ...timestamps(),
  },
  (table) => ({
    userIdx: index("api_tokens_user_id_idx").on(table.userId),
  }),
);

export const spotifyConnections = authn.table(
  "spotify_connections",
  {
    userId: text("user_id")
      .primaryKey()
      .references(() => users.id, { onDelete: "cascade" }),
    spotifyUserId: text("spotify_user_id").notNull(),
    refreshTokenCiphertext: text("refresh_token_ciphertext"),
    scopes: jsonb("scopes").default(sql`'[]'::jsonb`).notNull(),
    connectedAt: timestamp("connected_at", { withTimezone: true }).defaultNow().notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow().notNull(),
    lastRefreshAt: timestamp("last_refresh_at", { withTimezone: true }),
    lastError: text("last_error"),
    revokedAt: timestamp("revoked_at", { withTimezone: true }),
  },
  (table) => ({
    spotifyUserIdx: uniqueIndex("spotify_connections_spotify_user_id_idx").on(
      table.spotifyUserId,
    ),
  }),
);

export const artists = app.table(
  "artists",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    slug: text("slug").notNull(),
    name: text("name").notNull(),
    normalizedName: text("normalized_name").notNull(),
    imageUrl: text("image_url"),
    spotifyArtistUrl: text("spotify_artist_url"),
    discogsArtistUrl: text("discogs_artist_url"),
    metadata: jsonb("metadata").default(sql`'{}'::jsonb`).notNull(),
    ...timestamps(),
  },
  (table) => ({
    slugIdx: uniqueIndex("artists_slug_idx").on(table.slug),
    normalizedNameIdx: index("artists_normalized_name_idx").on(table.normalizedName),
  }),
);

export const tracks = app.table(
  "tracks",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    slug: text("slug").notNull(),
    title: text("title").notNull(),
    normalizedTitle: text("normalized_title").notNull(),
    primaryArtistName: text("primary_artist_name"),
    shazamTrackId: text("shazam_track_id"),
    spotifyUrl: text("spotify_url"),
    youtubeUrl: text("youtube_url"),
    discogsUrl: text("discogs_url"),
    metadata: jsonb("metadata").default(sql`'{}'::jsonb`).notNull(),
    ...timestamps(),
  },
  (table) => ({
    slugIdx: uniqueIndex("tracks_slug_idx").on(table.slug),
    normalizedTitleIdx: index("tracks_normalized_title_idx").on(table.normalizedTitle),
  }),
);

export const trackArtists = app.table(
  "track_artists",
  {
    trackId: uuid("track_id")
      .notNull()
      .references(() => tracks.id, { onDelete: "cascade" }),
    artistId: uuid("artist_id")
      .notNull()
      .references(() => artists.id, { onDelete: "cascade" }),
    role: text("role").default("primary").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => ({
    compoundPk: primaryKey({
      columns: [table.trackId, table.artistId, table.role],
    }),
  }),
);

export const sets = app.table(
  "sets",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    slug: text("slug").notNull(),
    title: text("title").notNull(),
    normalizedTitle: text("normalized_title").notNull(),
    sourcePlatform: text("source_platform"),
    sourceUrl: text("source_url"),
    sourceId: text("source_id"),
    durationSeconds: integer("duration_seconds"),
    uploader: text("uploader"),
    imageUrl: text("image_url"),
    recognitionRate: numeric("recognition_rate", {
      precision: 5,
      scale: 2,
    }),
    metadata: jsonb("metadata").default(sql`'{}'::jsonb`).notNull(),
    ...timestamps(),
  },
  (table) => ({
    slugIdx: uniqueIndex("sets_slug_idx").on(table.slug),
    sourceUrlIdx: uniqueIndex("sets_source_url_idx").on(table.sourceUrl),
    normalizedTitleIdx: index("sets_normalized_title_idx").on(table.normalizedTitle),
  }),
);

export const setArtists = app.table(
  "set_artists",
  {
    setId: uuid("set_id")
      .notNull()
      .references(() => sets.id, { onDelete: "cascade" }),
    artistId: uuid("artist_id")
      .notNull()
      .references(() => artists.id, { onDelete: "cascade" }),
    role: text("role").default("primary").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => ({
    compoundPk: primaryKey({
      columns: [table.setId, table.artistId, table.role],
    }),
  }),
);

export const setEntries = app.table(
  "set_entries",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    setId: uuid("set_id")
      .notNull()
      .references(() => sets.id, { onDelete: "cascade" }),
    trackId: uuid("track_id").references(() => tracks.id, { onDelete: "set null" }),
    position: integer("position").notNull(),
    displayArtist: text("display_artist").notNull(),
    displayTitle: text("display_title").notNull(),
    startTimeSeconds: integer("start_time_seconds").notNull(),
    endTimeSeconds: integer("end_time_seconds"),
    confidence: text("confidence").notNull(),
    detectionCount: integer("detection_count").notNull().default(0),
    clusterDensity: numeric("cluster_density", { precision: 6, scale: 4 }),
    clusterSpan: integer("cluster_span"),
    sourceDeepLink: text("source_deep_link"),
    metadata: jsonb("metadata").default(sql`'{}'::jsonb`).notNull(),
    ...timestamps(),
  },
  (table) => ({
    setPositionIdx: uniqueIndex("set_entries_set_position_idx").on(
      table.setId,
      table.position,
    ),
    setTimeIdx: index("set_entries_set_time_idx").on(table.setId, table.startTimeSeconds),
  }),
);

export const sitePages = app.table(
  "site_pages",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    path: text("path").notNull(),
    pageType: text("page_type").notNull(),
    artistId: uuid("artist_id").references(() => artists.id, { onDelete: "cascade" }),
    setId: uuid("set_id").references(() => sets.id, { onDelete: "cascade" }),
    slug: text("slug"),
    html: text("html").notNull(),
    metadata: jsonb("metadata").default(sql`'{}'::jsonb`).notNull(),
    ...timestamps(),
  },
  (table) => ({
    pathIdx: uniqueIndex("site_pages_path_idx").on(table.path),
    slugIdx: index("site_pages_slug_idx").on(table.slug),
  }),
);

export const submissions = ops.table(
  "submissions",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    requestedBy: text("requested_by")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    mode: text("mode").notNull(),
    status: text("status").notNull(),
    artistName: text("artist_name"),
    sourceUrl: text("source_url"),
    sourceUrls: jsonb("source_urls").default(sql`'[]'::jsonb`).notNull(),
    createPlaylist: boolean("create_playlist").default(false).notNull(),
    maxSetsOverride: integer("max_sets_override"),
    warningSummary: text("warning_summary"),
    errorSummary: text("error_summary"),
    cancelRequestedAt: timestamp("cancel_requested_at", { withTimezone: true }),
    completedAt: timestamp("completed_at", { withTimezone: true }),
    ...timestamps(),
  },
  (table) => ({
    requestedByIdx: index("submissions_requested_by_idx").on(table.requestedBy),
    statusIdx: index("submissions_status_idx").on(table.status),
  }),
);

export const setRuns = ops.table(
  "set_runs",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    submissionId: uuid("submission_id")
      .notNull()
      .references(() => submissions.id, { onDelete: "cascade" }),
    requestedBy: text("requested_by")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    status: text("status").notNull(),
    stage: text("stage"),
    attemptCount: integer("attempt_count").default(0).notNull(),
    sourceUrl: text("source_url").notNull(),
    sourcePlatform: text("source_platform"),
    setTitle: text("set_title"),
    createPlaylist: boolean("create_playlist").default(false).notNull(),
    sourceMetadata: jsonb("source_metadata").default(sql`'{}'::jsonb`).notNull(),
    heartbeatAt: timestamp("heartbeat_at", { withTimezone: true }),
    publishedSetId: uuid("published_set_id").references(() => sets.id, {
      onDelete: "set null",
    }),
    errorSummary: text("error_summary"),
    cancelRequestedAt: timestamp("cancel_requested_at", { withTimezone: true }),
    completedAt: timestamp("completed_at", { withTimezone: true }),
    ...timestamps(),
  },
  (table) => ({
    submissionIdx: index("set_runs_submission_id_idx").on(table.submissionId),
    statusIdx: index("set_runs_status_idx").on(table.status),
  }),
);

export const setRunLeases = ops.table(
  "set_run_leases",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    setRunId: uuid("set_run_id")
      .notNull()
      .references(() => setRuns.id, { onDelete: "cascade" }),
    slotIndex: integer("slot_index").notNull().default(0),
    segmentStartIndex: integer("segment_start_index").notNull(),
    segmentEndIndex: integer("segment_end_index").notNull(),
    status: text("status").notNull(),
    claimedBy: text("claimed_by"),
    claimedAt: timestamp("claimed_at", { withTimezone: true }),
    completedAt: timestamp("completed_at", { withTimezone: true }),
    errorText: text("error_text"),
    ...timestamps(),
  },
  (table) => ({
    setRunIdx: index("set_run_leases_set_run_id_idx").on(table.setRunId),
    statusIdx: index("set_run_leases_status_idx").on(table.status),
  }),
);

export const segmentHits = ops.table(
  "segment_hits",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    setRunId: uuid("set_run_id")
      .notNull()
      .references(() => setRuns.id, { onDelete: "cascade" }),
    leaseId: uuid("lease_id").references(() => setRunLeases.id, { onDelete: "set null" }),
    segmentIndex: integer("segment_index").notNull(),
    timestampSeconds: numeric("timestamp_seconds", { precision: 10, scale: 2 }).notNull(),
    trackTitle: text("track_title"),
    artist: text("artist"),
    shazamTrackId: text("shazam_track_id"),
    recognized: boolean("recognized").default(false).notNull(),
    rawData: jsonb("raw_data"),
    createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => ({
    runSegmentIdx: uniqueIndex("segment_hits_run_segment_idx").on(
      table.setRunId,
      table.segmentIndex,
    ),
  }),
);

export const discoveryCandidates = ops.table(
  "discovery_candidates",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    submissionId: uuid("submission_id")
      .notNull()
      .references(() => submissions.id, { onDelete: "cascade" }),
    sourceUrl: text("source_url").notNull(),
    sourcePlatform: text("source_platform"),
    sourceTitle: text("source_title"),
    durationSeconds: integer("duration_seconds"),
    status: text("status").notNull(),
    rejectionReason: text("rejection_reason"),
    metadata: jsonb("metadata").default(sql`'{}'::jsonb`).notNull(),
    ...timestamps(),
  },
  (table) => ({
    submissionIdx: index("discovery_candidates_submission_id_idx").on(table.submissionId),
  }),
);

export const workerEvents = ops.table(
  "worker_events",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    submissionId: uuid("submission_id").references(() => submissions.id, {
      onDelete: "cascade",
    }),
    setRunId: uuid("set_run_id").references(() => setRuns.id, {
      onDelete: "cascade",
    }),
    leaseId: uuid("lease_id").references(() => setRunLeases.id, {
      onDelete: "set null",
    }),
    eventType: text("event_type").notNull(),
    message: text("message").notNull(),
    details: jsonb("details").default(sql`'{}'::jsonb`).notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => ({
    submissionIdx: index("worker_events_submission_id_idx").on(table.submissionId),
    setRunIdx: index("worker_events_set_run_id_idx").on(table.setRunId),
  }),
);

export const authTables = {
  usersTable: users,
  accountsTable: accounts,
  sessionsTable: sessions,
  verificationTokensTable: verificationTokens,
};

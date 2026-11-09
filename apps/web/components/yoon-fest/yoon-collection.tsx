"use client";
import { useState } from "react";
import { ArchiveHeader } from "@/components/archive/archive-header";
import { ArchiveSetCard } from "@/components/archive/archive-set-card";
import { SpotifyExportButton } from "@/components/archive/spotify-export-button";
import type { ArchiveSetDetail } from "@/lib/archive/types";
import { buildSetSpotifyExportCandidates, SPOTIFY_EXPORT_FILTERS, type SpotifyExportCounts } from "@/lib/archive/spotify-export";

export function YoonCollection({ sets }: { sets: Array<{ detail: ArchiveSetDetail; boundaryNote: string }> }) {
  const [expanded, setExpanded] = useState<string[]>([]);
  const counts = Object.fromEntries(SPOTIFY_EXPORT_FILTERS.map((filter) => [filter,
    new Set(sets.flatMap(({ detail }) => buildSetSpotifyExportCandidates(detail, filter).map((track) => track.spotifyTrackId))).size,
  ])) as SpotifyExportCounts;
  return <>
    <ArchiveHeader hideScopeToggle hideSearch hideSubmit navLinks={[{ label: "Yoon Fest", href: "/collections/yoon-fest" }]} />
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: 24 }}>
      <p>Private collection</p><h1>Yoon Fest</h1>
      <p>This website and its setlists are restricted to Russell and Hal. Provisional boundaries are labeled on each set.</p>
      <p>Audio streams directly from Dropbox. Anyone who receives an audio link can play it.</p>
      <SpotifyExportButton counts={counts} entityType="festival" slug="yoon-fest" endpoint="/api/yoon-fest/spotify/export" label="Export Festival to Spotify" />
      {!sets.length ? <p>No reviewed recordings have been added yet.</p> : null}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))", gap: 20, marginTop: 24 }}>
        {sets.map(({ detail, boundaryNote }) => {
          const href = `/collections/yoon-fest/sets/${detail.slug}`;
          return <ArchiveSetCard key={detail.id} title={detail.title} setHref={href} imageAlt="" imageUrl={null}
            emptyImageLabel="Private recording" metaPills={[detail.artistName ?? "", detail.durationFmt, boundaryNote]}
            miniTimeline={detail.timeline.map((segment) => ({ confidence: segment.conf, leftPct: segment.leftPct, widthPct: segment.widthPct }))}
            tracklistExpanded={expanded.includes(detail.id)} toggleTracklist={() => setExpanded((current) => current.includes(detail.id) ? current.filter((id) => id !== detail.id) : [...current, detail.id])}
            tracklist={detail.tracks.map((track) => ({ confidence: track.conf, href: `${href}#track-${track.idx}`, id: `${detail.id}-${track.idx}`, label: `${track.artist} - ${track.title}`, startTimeFormatted: track.startFmt }))}
          />;
        })}
      </div>
    </main>
  </>;
}

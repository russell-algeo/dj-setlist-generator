"use client";

import { useRef, useState } from "react";

import { ArtistNameField } from "@/components/forms/artist-name-field";

type DashboardSubmitFormsProps = {
  discoveryHelperText: string;
  curatedHelperText: string;
};

export function DashboardSubmitForms({
  discoveryHelperText,
  curatedHelperText,
}: DashboardSubmitFormsProps) {
  const [discoveryName, setDiscoveryName] = useState("");
  const [curatedName, setCuratedName] = useState("");
  const curatedUrlsRef = useRef<HTMLTextAreaElement | null>(null);

  const routeDiscoveryToCurated = (artistName: string) => {
    setCuratedName(artistName);

    requestAnimationFrame(() => {
      curatedUrlsRef.current?.focus();
      curatedUrlsRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  };

  return (
    <section className="panel-grid panel-grid--two">
      <article className="panel">
        <h2>Artist discovery</h2>
        <form action="/api/jobs" className="stack-form" method="post">
          <input name="mode" type="hidden" value="artist" />
          <ArtistNameField
            existingArtistHelperText={discoveryHelperText}
            inputClassName="field"
            name="artistName"
            onSuggestionSelect={(artist) => routeDiscoveryToCurated(artist.name)}
            onValueChange={setDiscoveryName}
            placeholder="Artist name"
            required
            value={discoveryName}
          />
          <input min="1" name="maxSetsOverride" placeholder="Max sets override (optional)" type="number" />
          <label>
            <input name="createPlaylist" type="checkbox" value="true" /> Create Spotify playlist
          </label>
          <button className="button" type="submit">
            Discover sets
          </button>
        </form>
      </article>

      <article className="panel">
        <h2>Curated artist batch</h2>
        <form action="/api/jobs" className="stack-form" method="post">
          <input name="mode" type="hidden" value="curated_artist" />
          <ArtistNameField
            existingArtistHelperText={curatedHelperText}
            inputClassName="field"
            name="artistName"
            onValueChange={setCuratedName}
            placeholder="Artist name"
            required
            value={curatedName}
          />
          <textarea
            ref={curatedUrlsRef}
            name="sourceUrls"
            placeholder={"One URL per line\nhttps://...\nhttps://..."}
            required
          />
          <label>
            <input name="createPlaylist" type="checkbox" value="true" /> Create Spotify playlist
          </label>
          <button className="button" type="submit">
            Queue curated batch
          </button>
        </form>
      </article>
    </section>
  );
}

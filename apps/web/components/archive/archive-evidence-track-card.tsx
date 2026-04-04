import type { CSSProperties, MouseEvent } from "react";

const joinClasses = (...values: Array<string | false | null | undefined>) =>
  values.filter(Boolean).join(" ");

export type ArchiveEvidenceTrackCardLink = {
  href?: string | null;
  id: string;
  label: string;
  target?: string;
};

export type ArchiveEvidenceTrackCardSourceGroup = {
  emptyLabel?: string;
  id: string;
  links: ArchiveEvidenceTrackCardLink[];
  title?: string;
  titleHref?: string | null;
};

type ArchiveEvidenceTrackCardProps = {
  albumArt?: string | null;
  cardClassName?: string;
  confidence: string;
  confidencePrefix?: string;
  dataTrackKey?: string;
  emptyArtLabel?: string;
  onToggleSources: (event: MouseEvent<HTMLButtonElement>) => void;
  onToggleSpotify?: (event: MouseEvent<HTMLButtonElement>) => void;
  openState: {
    sourcesOpen: boolean;
    spotifyOpen: boolean;
  };
  sourceGroups: ArchiveEvidenceTrackCardSourceGroup[];
  sourceLabel?: string | null;
  spotifyTrackId?: string | null;
  style?: CSSProperties | null;
  title: string;
  titlePrefix: string;
};

const normalizeConfidenceTone = (value: string) => {
  const normalized = value.trim().toLowerCase();
  if (normalized === "high" || normalized === "medium" || normalized === "low") {
    return normalized;
  }
  return "uncertain";
};

export function ArchiveEvidenceTrackCard({
  albumArt,
  cardClassName,
  confidence,
  confidencePrefix = "Confidence",
  dataTrackKey,
  emptyArtLabel = "No Art",
  onToggleSources,
  onToggleSpotify,
  openState,
  sourceGroups,
  sourceLabel,
  spotifyTrackId,
  style,
  title,
  titlePrefix,
}: ArchiveEvidenceTrackCardProps) {
  const confidenceTone = normalizeConfidenceTone(confidence);
  const hasSources = sourceGroups.length > 0 && Boolean(sourceLabel);

  return (
    <article
      className={joinClasses(
        "track-card",
        cardClassName,
        openState.sourcesOpen && "sources-open",
        openState.spotifyOpen && "embed-open",
      )}
      data-track-key={dataTrackKey}
      style={style ?? undefined}
    >
      <div className="track-art">
        {albumArt ? <img alt={title} loading="lazy" src={albumArt} /> : <div className="track-art-fallback">{emptyArtLabel}</div>}
      </div>
      <div className="track-body">
        <h4 className="track-title">
          {titlePrefix}
          {title}
        </h4>
        <p className="muted">
          {confidencePrefix}{" "}
          <span className={joinClasses("set-track-conf", confidenceTone)}>{confidence}</span>
        </p>
        <div className="actions">
          {spotifyTrackId && onToggleSpotify ? (
            <button onClick={onToggleSpotify} type="button">
              {openState.spotifyOpen ? "Hide Spotify" : "Spotify"}
            </button>
          ) : null}
          {hasSources ? (
            <button onClick={onToggleSources} type="button">
              {openState.sourcesOpen ? "Hide Sets" : sourceLabel}
            </button>
          ) : null}
        </div>
        {spotifyTrackId && openState.spotifyOpen ? (
          <div className="spotify-embed">
            <iframe
              allow="autoplay; clipboard-write; encrypted-media"
              src={`https://open.spotify.com/embed/track/${spotifyTrackId}?utm_source=generator&theme=0`}
              title="Spotify embed"
            />
          </div>
        ) : null}
        <div className={joinClasses("source-panel", openState.sourcesOpen && "open")}>
          {sourceGroups.map((group) => (
            <div className="source-group" key={group.id}>
              {group.title ? (
                <h5>
                  {group.titleHref ? (
                    <a href={group.titleHref}>{group.title}</a>
                  ) : (
                    group.title
                  )}
                </h5>
              ) : null}
              {group.links.length > 0 ? (
                <ul className="source-list">
                  {group.links.map((link) => (
                    <li key={link.id}>
                      {link.href ? (
                        <a href={link.href} rel="noopener" target={link.target ?? "_blank"}>
                          {link.label}
                        </a>
                      ) : (
                        <span>{link.label}</span>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="empty">{group.emptyLabel ?? "No set links available."}</div>
              )}
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

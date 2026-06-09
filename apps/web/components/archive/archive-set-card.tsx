/* eslint-disable @next/next/no-img-element */
"use client";

import type { ReactNode } from "react";

import type { ArchiveConfidence } from "@/lib/archive/types";

import styles from "./archive-set-card.module.css";

type ArchiveSetCardAction =
  | {
      href: string;
      key: string;
      label: string;
      target?: "_blank" | "_self";
    }
  | {
      key: string;
      label: string;
      onClick: () => void;
    };

export type ArchiveSetCardTrack = {
  confidence: ArchiveConfidence;
  href: string;
  id: string;
  label: string;
  shared?: boolean;
  startTimeFormatted: string;
  target?: "_blank" | "_self";
};

export type ArchiveSetCardMiniSegment = {
  confidence: ArchiveConfidence;
  leftPct: number;
  widthPct: number;
};

type ArchiveSetCardProps = {
  actions?: ArchiveSetCardAction[];
  emptyImageLabel?: string;
  imageAlt: string;
  imageTarget?: "_blank" | "_self";
  imageUrl: string | null;
  miniTimeline: ArchiveSetCardMiniSegment[];
  metaPills: string[];
  selected?: boolean;
  setHref: string;
  listened?: boolean;
  sourceHref?: string | null;
  title: string;
  titleTarget?: "_blank" | "_self";
  toggleTracklist: () => void;
  tracklist: ArchiveSetCardTrack[];
  tracklistEmptyLabel?: string;
  tracklistExpanded: boolean;
  tracklistLoading?: boolean;
  tracklistLoadingLabel?: string;
};

const joinClasses = (...values: Array<string | false | null | undefined>) =>
  values.filter(Boolean).join(" ");

const buildTargetProps = (target?: "_blank" | "_self") =>
  target === "_blank" ? { rel: "noopener", target } : undefined;

const CONFIDENCE_CLASS: Record<ArchiveConfidence, string> = {
  HIGH: styles.miniSegmentHigh,
  LOW: styles.miniSegmentLow,
  MEDIUM: styles.miniSegmentMedium,
  UNCERTAIN: styles.miniSegmentUncertain,
};

const TRACK_CONFIDENCE_CLASS: Record<ArchiveConfidence, string> = {
  HIGH: styles.trackConfidenceHigh,
  LOW: styles.trackConfidenceLow,
  MEDIUM: styles.trackConfidenceMedium,
  UNCERTAIN: styles.trackConfidenceUncertain,
};

const renderAction = (action: ArchiveSetCardAction) => {
  if ("href" in action) {
    return (
      <a
        className={styles.actionLink}
        href={action.href}
        key={action.key}
        {...buildTargetProps(action.target)}
      >
        {action.label}
      </a>
    );
  }

  return (
    <button className={styles.actionButton} key={action.key} onClick={action.onClick} type="button">
      {action.label}
    </button>
  );
};

export function ArchiveSetCard({
  actions = [],
  emptyImageLabel = "No Image",
  imageAlt,
  imageTarget,
  imageUrl,
  miniTimeline,
  metaPills,
  selected = false,
  setHref,
  listened = false,
  sourceHref,
  title,
  titleTarget,
  toggleTracklist,
  tracklist,
  tracklistEmptyLabel = "No identified tracks in this set.",
  tracklistExpanded,
  tracklistLoading = false,
  tracklistLoadingLabel = "Loading tracklist…",
}: ArchiveSetCardProps) {
  const setLinkProps = buildTargetProps(titleTarget);
  const imageLinkProps = buildTargetProps(imageTarget ?? titleTarget);
  const actionItems: ArchiveSetCardAction[] = [
    {
      href: setHref,
      key: "open-set",
      label: "Open Set Page",
      target: titleTarget,
    },
    ...(sourceHref
      ? [
          {
            href: sourceHref,
            key: "source",
            label: "Source",
            target: "_blank" as const,
          },
        ]
      : []),
    ...actions,
    {
      key: "toggle-tracklist",
      label: tracklistExpanded ? "Hide Tracklist" : "Show Tracklist",
      onClick: toggleTracklist,
    },
  ];

  let tracklistContent: ReactNode = <div className={styles.empty}>{tracklistEmptyLabel}</div>;
  if (tracklistLoading) {
    tracklistContent = <div className={styles.empty}>{tracklistLoadingLabel}</div>;
  } else if (tracklist.length > 0) {
    tracklistContent = tracklist.map((track) => (
      <div
        className={joinClasses(styles.track, track.shared && styles.trackShared)}
        key={track.id}
      >
        <span className={styles.trackTime}>{track.startTimeFormatted}</span>
        <span>
          <a className={styles.trackLink} href={track.href} {...buildTargetProps(track.target)}>
            {track.label}
          </a>
        </span>
        <span className={joinClasses(styles.trackConfidence, TRACK_CONFIDENCE_CLASS[track.confidence])}>
          {track.confidence}
        </span>
      </div>
    ));
  }

  return (
    <article
      className={joinClasses(
        styles.card,
        !imageUrl && styles.emptyThumbCard,
        selected && styles.selected,
        listened && styles.listened,
      )}
    >
      <div className={joinClasses(styles.thumb, !imageUrl && styles.thumbEmpty)}>
        {imageUrl ? (
          <a className={styles.thumbLink} href={setHref} {...imageLinkProps}>
            <img alt={imageAlt} className={styles.thumbImage} loading="lazy" src={imageUrl} />
          </a>
        ) : (
          emptyImageLabel
        )}
      </div>
      <div className={styles.body}>
        <h4 className={styles.title}>
          <a className={styles.titleLink} href={setHref} {...setLinkProps}>
            {title}
          </a>
        </h4>
        <div className={styles.mini}>
          {miniTimeline.map((segment, index) => (
            <span
              className={joinClasses(styles.miniSegment, CONFIDENCE_CLASS[segment.confidence])}
              key={`${segment.leftPct}:${segment.widthPct}:${index}`}
              style={{
                left: `${segment.leftPct}%`,
                width: `${segment.widthPct}%`,
              }}
            />
          ))}
        </div>
        <div className={styles.meta}>
          {metaPills.map((pill) => (
            <span className={styles.pill} key={pill}>
              {pill}
            </span>
          ))}
          {listened ? <span className={styles.listenedPill}>Listened</span> : null}
        </div>
        <div className={styles.actions}>{actionItems.map(renderAction)}</div>
        <div className={joinClasses(styles.tracklist, tracklistExpanded && styles.tracklistOpen)}>
          {tracklistContent}
        </div>
      </div>
    </article>
  );
}

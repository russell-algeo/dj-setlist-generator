import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";

import { ArchiveHeader } from "@/components/archive/archive-header";

import styles from "./operator-ui.module.css";

const joinClasses = (...values: Array<string | false | null | undefined>) =>
  values.filter(Boolean).join(" ");

export function OperatorFrame({
  activeNavHref,
  backCurrentLabel,
  backHref,
  backLabel,
  children,
  headerNavLinks = [],
  width = "default",
}: {
  activeNavHref?: string;
  backCurrentLabel?: string;
  backHref?: string;
  backLabel?: string;
  children: ReactNode;
  headerNavLinks?: Array<{ label: string; href: string }>;
  width?: "default" | "wide";
}) {
  return (
    <main className={styles.page}>
      <ArchiveHeader
        activeHref={activeNavHref}
        hideScopeToggle
        hideSubmit
        navLinks={headerNavLinks}
      />
      <div className={styles.shell} data-width={width}>
        <div className={styles.contentFrame}>
          {backHref ? (
            <div className={styles.backRow}>
              <Link className={styles.backLink} href={backHref}>
                {backLabel ?? "Back"}
              </Link>
              {backCurrentLabel ? <span className={styles.backCurrent}>› {backCurrentLabel}</span> : null}
            </div>
          ) : null}
          {children}
        </div>
      </div>
    </main>
  );
}

export function OperatorPageHeader({
  aside,
  eyebrow,
  meta,
  subtitle,
  title,
  titleFont = "mono",
  titleSize = "compact",
}: {
  aside?: ReactNode;
  eyebrow?: string;
  meta?: ReactNode;
  subtitle?: ReactNode;
  title: string;
  titleFont?: "mono" | "sans";
  titleSize?: "compact" | "display";
}) {
  return (
    <header className={styles.header}>
      <div className={styles.headerCopy}>
        {eyebrow ? <div className={styles.eyebrow}>{eyebrow}</div> : null}
        <h1 className={styles.title} data-font={titleFont} data-size={titleSize}>
          {title}
        </h1>
        {subtitle ? <div className={styles.subtitle}>{subtitle}</div> : null}
        {meta ? <div className={styles.headerMeta}>{meta}</div> : null}
      </div>
      {aside ? <div className={styles.headerAside}>{aside}</div> : null}
    </header>
  );
}

export function OperatorMetricCard({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className={styles.metricCard}>
      <span className={styles.metricValue}>{value}</span>
      <span className={styles.metricLabel}>{label}</span>
    </div>
  );
}

export function OperatorNotice({
  action,
  body,
  title,
  tone = "neutral",
}: {
  action?: ReactNode;
  body: ReactNode;
  title: string;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  return (
    <div
      className={joinClasses(
        styles.notice,
        tone === "neutral" && styles.noticeNeutral,
        tone === "success" && styles.noticeSuccess,
        tone === "warning" && styles.noticeWarning,
        tone === "danger" && styles.noticeDanger,
      )}
    >
      <div className={styles.noticeTitle}>{title}</div>
      <div className={styles.noticeBody}>{body}</div>
      {action ? <div className={styles.noticeActions}>{action}</div> : null}
    </div>
  );
}

export function OperatorStatusBadge({
  align = "left",
  label,
  status,
}: {
  align?: "left" | "right";
  label?: string;
  status: string;
}) {
  const tone = getStatusTone(status);

  return (
    <div className={styles.statusWrap} data-align={align}>
      <span
        className={styles.statusBadge}
        style={
          {
            "--operator-status-bg": tone.background,
            "--operator-status-color": tone.color,
          } as CSSProperties
        }
      >
        {label ?? status}
      </span>
    </div>
  );
}

const statusToneByStatus: Record<string, { background: string; color: string }> = {
  active: {
    background: "rgba(210, 174, 50, 0.16)",
    color: "#d2ae32",
  },
  aggregating: {
    background: "rgba(210, 174, 50, 0.16)",
    color: "#d2ae32",
  },
  cancelled: {
    background: "rgba(108, 108, 108, 0.14)",
    color: "#6c6c6c",
  },
  cancelling: {
    background: "rgba(210, 174, 50, 0.16)",
    color: "#b99255",
  },
  claimed: {
    background: "rgba(210, 174, 50, 0.16)",
    color: "#d2ae32",
  },
  completed: {
    background: "rgba(58, 138, 87, 0.16)",
    color: "#3a8a57",
  },
  connected: {
    background: "rgba(58, 138, 87, 0.16)",
    color: "#3a8a57",
  },
  dispatched: {
    background: "rgba(210, 174, 50, 0.16)",
    color: "#d2ae32",
  },
  enriching: {
    background: "rgba(210, 174, 50, 0.16)",
    color: "#d2ae32",
  },
  failed: {
    background: "rgba(162, 74, 74, 0.16)",
    color: "#a24a4a",
  },
  partial: {
    background: "rgba(185, 146, 85, 0.16)",
    color: "#b99255",
  },
  publishing: {
    background: "rgba(210, 174, 50, 0.16)",
    color: "#d2ae32",
  },
  queued: {
    background: "rgba(108, 108, 108, 0.14)",
    color: "#6c6c6c",
  },
  recognizing: {
    background: "rgba(210, 174, 50, 0.16)",
    color: "#d2ae32",
  },
  resolving: {
    background: "rgba(210, 174, 50, 0.16)",
    color: "#d2ae32",
  },
  running: {
    background: "rgba(210, 174, 50, 0.16)",
    color: "#d2ae32",
  },
};

const neutralTone = {
  background: "rgba(108, 108, 108, 0.14)",
  color: "#6c6c6c",
};

export const getStatusTone = (status: string) =>
  statusToneByStatus[status.toLowerCase()] ?? neutralTone;

export { styles as operatorUiStyles };

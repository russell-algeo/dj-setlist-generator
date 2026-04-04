import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";

import styles from "./dark-ui.module.css";

const joinClasses = (...values: Array<string | false | null | undefined>) =>
  values.filter(Boolean).join(" ");

type DarkPageShellProps = {
  backHref?: string;
  backLabel?: string;
  children: ReactNode;
  eyebrow?: string;
  headerAside?: ReactNode;
  headerMeta?: ReactNode;
  subtitle?: ReactNode;
  title: string;
  titleSize?: "default" | "compact" | "micro";
  variant?: "archive" | "operator";
};

export function DarkPageShell({
  backHref,
  backLabel,
  children,
  eyebrow,
  headerAside,
  headerMeta,
  subtitle,
  title,
  titleSize = "default",
  variant = "operator",
}: DarkPageShellProps) {
  return (
    <main className={styles.page} data-variant={variant}>
      <div className={styles.shell}>
        {backHref ? (
          <div className={styles.backRow}>
            <Link className={styles.backLink} href={backHref}>
              {backLabel ?? "Back"}
            </Link>
          </div>
        ) : null}
        <header className={styles.header}>
          <div className={styles.headerCopy}>
            {eyebrow ? <div className={styles.eyebrow}>{eyebrow}</div> : null}
            <h1
              className={joinClasses(
                styles.title,
                titleSize === "compact" && styles.titleCompact,
                titleSize === "micro" && styles.titleMicro,
              )}
            >
              {title}
            </h1>
            {subtitle ? <div className={styles.subtitle}>{subtitle}</div> : null}
            {headerMeta ? <div className={styles.headerMeta}>{headerMeta}</div> : null}
          </div>
          {headerAside ? <div className={styles.headerAside}>{headerAside}</div> : null}
        </header>
        <div className={styles.section}>{children}</div>
      </div>
    </main>
  );
}

export type StatusTone = "neutral" | "active" | "success" | "warning" | "danger";

const STATUS_TONE_BY_STATUS: Record<string, StatusTone> = {
  active: "active",
  aggregating: "active",
  cancelled: "neutral",
  cancelling: "warning",
  claimed: "active",
  completed: "success",
  connected: "success",
  dispatched: "active",
  enriching: "active",
  failed: "danger",
  partial: "warning",
  publishing: "active",
  queued: "neutral",
  recognizing: "active",
  resolving: "active",
  running: "active",
};

const STATUS_STYLE_BY_TONE: Record<StatusTone, { color: string; background: string }> = {
  active: {
    background: "var(--dark-status-warning-soft)",
    color: "var(--dark-status-warning)",
  },
  danger: {
    background: "var(--dark-status-danger-soft)",
    color: "var(--dark-status-danger)",
  },
  neutral: {
    background: "var(--dark-status-neutral-soft)",
    color: "var(--dark-status-neutral)",
  },
  success: {
    background: "var(--dark-status-success-soft)",
    color: "var(--dark-status-success)",
  },
  warning: {
    background: "var(--dark-status-warning-soft)",
    color: "var(--dark-status-warning)",
  },
};

export const getStatusTone = (status: string): StatusTone =>
  STATUS_TONE_BY_STATUS[status.toLowerCase()] ?? "neutral";

export function DarkStatusBadge({
  align = "left",
  label,
  status,
}: {
  align?: "left" | "right";
  label?: string;
  status: string;
}) {
  const tone = getStatusTone(status);
  const chrome = STATUS_STYLE_BY_TONE[tone];

  return (
    <div className={joinClasses(styles.statusWrap, align === "right" && styles.statusWrapRight)}>
      <span
        className={styles.statusBadge}
        style={
          {
            "--status-bg": chrome.background,
            "--status-color": chrome.color,
          } as CSSProperties
        }
      >
        {label ?? status}
      </span>
    </div>
  );
}

export function DarkNotice({
  action,
  body,
  tone = "neutral",
  title,
}: {
  action?: ReactNode;
  body: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
  title: string;
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

export function DarkMetricCard({
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

export { styles as darkUiStyles };

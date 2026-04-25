"use client";

import { useRouter } from "next/navigation";
import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import styles from "./archive-delete-control.module.css";

type DeleteEntityType = "artist" | "set";

type DeleteResponse = {
  entityRemoved?: boolean;
  error?: string;
  message?: string;
};

type ArchiveDeleteControlProps = {
  entityType: DeleteEntityType;
  impact: string;
  leadingNode?: ReactNode;
  redirectHref?: string;
  slug: string;
  title: string;
};

type SubmittedByYouBadgeProps = {
  className?: string;
};

const endpointFor = (entityType: DeleteEntityType, slug: string) =>
  `/api/archive/${entityType === "artist" ? "artists" : "sets"}/${encodeURIComponent(slug)}/delete`;

const labelFor = (entityType: DeleteEntityType) =>
  entityType === "artist" ? "Delete Artist" : "Delete Set";

export function SubmittedByYouBadge({ className }: SubmittedByYouBadgeProps) {
  return <span className={[styles.submittedBadge, className].filter(Boolean).join(" ")}>Submitted by you</span>;
}

export function ArchiveDeleteControl({
  entityType,
  impact,
  leadingNode,
  redirectHref,
  slug,
  title,
}: ArchiveDeleteControlProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [popoverShift, setPopoverShift] = useState(0);
  const menuRootRef = useRef<HTMLSpanElement | null>(null);
  const popoverRef = useRef<HTMLSpanElement | null>(null);

  useLayoutEffect(() => {
    if (!open) {
      return;
    }

    const updatePopoverShift = () => {
      const menuRoot = menuRootRef.current;
      const popover = popoverRef.current;

      if (!menuRoot || !popover) {
        return;
      }

      const viewportMargin = 24;
      const documentWidth = document.documentElement.clientWidth || window.innerWidth;
      const visualViewportLeft = window.visualViewport?.offsetLeft ?? 0;
      const visualViewportRight = visualViewportLeft + (window.visualViewport?.width ?? window.innerWidth);
      const viewportLeft = Math.max(0, visualViewportLeft) + viewportMargin;
      const viewportRight = Math.min(window.innerWidth, documentWidth, visualViewportRight) - viewportMargin;
      const anchorLeft = menuRoot.getBoundingClientRect().left;
      const popoverWidth = popover.offsetWidth;
      let nextShift = 0;

      if (anchorLeft + popoverWidth > viewportRight) {
        nextShift = viewportRight - anchorLeft - popoverWidth;
      }

      if (anchorLeft + nextShift < viewportLeft) {
        nextShift = viewportLeft - anchorLeft;
      }

      setPopoverShift(Math.round(nextShift));
    };

    updatePopoverShift();
    window.addEventListener("resize", updatePopoverShift);
    window.visualViewport?.addEventListener("resize", updatePopoverShift);

    return () => {
      window.removeEventListener("resize", updatePopoverShift);
      window.visualViewport?.removeEventListener("resize", updatePopoverShift);
    };
  }, [confirming, open]);

  const close = (force = false) => {
    if (busy && !force) {
      return;
    }
    setOpen(false);
    setConfirming(false);
    setError(null);
    setReason("");
    setPopoverShift(0);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);

    try {
      const response = await fetch(endpointFor(entityType, slug), {
        body: JSON.stringify({ reason }),
        headers: {
          "content-type": "application/json",
        },
        method: "POST",
      });
      const payload = (await response.json()) as DeleteResponse;

      if (!response.ok) {
        setError(payload.error ?? "Deletion failed.");
        return;
      }

      close(true);
      if (payload.entityRemoved && redirectHref) {
        router.push(redirectHref);
        router.refresh();
        return;
      }

      router.refresh();
    } catch {
      setError("Deletion failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className={styles.root} onClick={(event) => event.stopPropagation()}>
      {leadingNode ? <span className={styles.leading}>{leadingNode}</span> : null}
      <span className={styles.menuRoot} ref={menuRootRef}>
        <button
          aria-expanded={open}
          aria-label={`More actions for ${title}`}
          className={styles.trigger}
          onClick={(event) => {
            event.preventDefault();
            setOpen((current) => !current);
            setConfirming(false);
            setError(null);
          }}
          type="button"
        >
          ...
        </button>
        {open ? (
          <span
            className={styles.popover}
            ref={popoverRef}
            style={{ "--delete-popover-shift": `${popoverShift}px` } as CSSProperties}
          >
            {!confirming ? (
              <button
                className={styles.menuItem}
                onClick={(event) => {
                  event.preventDefault();
                  setConfirming(true);
                }}
                type="button"
              >
                {labelFor(entityType)}
              </button>
            ) : (
              <span className={styles.confirmPanel}>
                <span className={styles.confirmTitle}>{labelFor(entityType)}</span>
                <span className={styles.confirmCopy}>{impact}</span>
                <textarea
                  className={styles.reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Reason (optional)"
                  rows={3}
                  value={reason}
                />
                {error ? <span className={styles.error}>{error}</span> : null}
                <span className={styles.confirmActions}>
                  <button className={styles.cancel} disabled={busy} onClick={() => close()} type="button">
                    Cancel
                  </button>
                  <button
                    className={styles.delete}
                    disabled={busy}
                    onClick={(event) => {
                      event.preventDefault();
                      void submit();
                    }}
                    type="button"
                  >
                    {busy ? "Deleting..." : "Confirm"}
                  </button>
                </span>
              </span>
            )}
          </span>
        ) : null}
      </span>
    </span>
  );
}

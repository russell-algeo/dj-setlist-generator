"use client";

import { useEffect, useRef } from "react";

type ArchiveHomeParityPayload = {
  artistDirMapJson: string;
  cssText: string;
  dataJson: string;
  scriptText: string;
  shellHtml: string;
};

const HOME_PARITY_RESET_CSS = `
.archive-home-parity-root .panel-title {
  line-height: normal;
}

.archive-home-parity-root input[type="range"] {
  margin: 2px 0;
}
`;

const HOME_SCROLL_KEY = "archive-home-parity:scroll-y";

declare global {
  interface Window {
    EXPLORER_DATA?: unknown;
    __ARCHIVE_HOME_ARTIST_DIR_MAP__?: Record<string, string>;
  }
}

const interceptAddEventListener = (
  target: Document | HTMLElement | Window,
  cleanups: Array<() => void>,
) => {
  const original = target.addEventListener.bind(target);

  target.addEventListener = ((type: string, listener: EventListenerOrEventListenerObject, options?: AddEventListenerOptions | boolean) => {
    cleanups.push(() => {
      target.removeEventListener(type, listener, options);
    });
    return original(type, listener, options);
  }) as typeof target.addEventListener;

  return () => {
    target.addEventListener = original;
  };
};

export function ArchiveHomeParity({
  payload,
}: {
  payload: ArchiveHomeParityPayload;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const restoreScrollRef = useRef<number | null>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) {
      return;
    }

    if (restoreScrollRef.current === null) {
      const navEntry = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
      const saved = Number(sessionStorage.getItem(HOME_SCROLL_KEY) ?? "");
      if (navEntry?.type === "reload" && Number.isFinite(saved) && saved > 0) {
        restoreScrollRef.current = saved;
      } else {
        restoreScrollRef.current = 0;
      }
    }

    root.innerHTML = `<style>${HOME_PARITY_RESET_CSS}</style><style>${payload.cssText}</style>${payload.shellHtml}`;

    const persistScroll = () => {
      sessionStorage.setItem(HOME_SCROLL_KEY, String(window.scrollY));
    };

    window.addEventListener("pagehide", persistScroll);
    window.addEventListener("beforeunload", persistScroll);

    const cleanups: Array<() => void> = [];
    const restoreWindow = interceptAddEventListener(window, cleanups);
    const restoreDocument = interceptAddEventListener(document, cleanups);
    const restoreRoot = interceptAddEventListener(root, cleanups);

    try {
      window.EXPLORER_DATA = JSON.parse(payload.dataJson);
      window.__ARCHIVE_HOME_ARTIST_DIR_MAP__ = JSON.parse(payload.artistDirMapJson) as Record<string, string>;

      const runner = new Function("root", `const DATA = window.EXPLORER_DATA;\n${payload.scriptText}`);
      runner(root);

      const targetScrollY = restoreScrollRef.current ?? 0;
      if (targetScrollY > 0) {
        requestAnimationFrame(() => {
          window.scrollTo(0, targetScrollY);
        });
      }
    } finally {
      restoreRoot();
      restoreDocument();
      restoreWindow();
    }

    return () => {
      persistScroll();
      window.removeEventListener("pagehide", persistScroll);
      window.removeEventListener("beforeunload", persistScroll);
      cleanups.forEach((cleanup) => cleanup());
      root.innerHTML = "";
    };
  }, [
    payload.artistDirMapJson,
    payload.cssText,
    payload.dataJson,
    payload.scriptText,
    payload.shellHtml,
  ]);

  return <div className="archive-home-parity-root" ref={rootRef} suppressHydrationWarning />;
}

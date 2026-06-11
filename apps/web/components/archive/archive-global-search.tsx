/* eslint-disable @next/next/no-img-element */
"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import styles from "./archive-global-search.module.css";

type SearchType = "all" | "artists" | "sets";
type SearchScope = "global" | "mine";

type SearchResult = {
  href: string;
  id: string;
  imageUrl: string | null;
  kind: "artist" | "set";
  meta: string;
  name: string;
  slug: string;
};

type SearchPayload = {
  artists: SearchResult[];
  authRequired: boolean;
  query: string;
  scope: SearchScope;
  sets: SearchResult[];
  type: SearchType;
};

const TYPE_OPTIONS: Array<{ label: string; value: SearchType }> = [
  { label: "All", value: "all" },
  { label: "Artists", value: "artists" },
  { label: "Sets", value: "sets" },
];

const EMPTY_PAYLOAD: SearchPayload = {
  artists: [],
  authRequired: false,
  query: "",
  scope: "global",
  sets: [],
  type: "all",
};

const isTypingTarget = (target: EventTarget | null) => {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  return (
    target.isContentEditable ||
    target.tagName === "INPUT" ||
    target.tagName === "SELECT" ||
    target.tagName === "TEXTAREA"
  );
};

export function ArchiveGlobalSearch() {
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const searchParams = useSearchParams();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [type, setType] = useState<SearchType>("all");
  const [payload, setPayload] = useState<SearchPayload>(EMPTY_PAYLOAD);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  const scope: SearchScope = searchParams.get("scope") === "mine" ? "mine" : "global";
  const trimmedQuery = query.trim();

  const visibleGroups = useMemo(() => {
    const groups: Array<{ label: string; results: SearchResult[] }> = [];
    if (type !== "sets") {
      groups.push({ label: "Artists", results: payload.artists });
    }
    if (type !== "artists") {
      groups.push({ label: "Sets", results: payload.sets });
    }
    return groups;
  }, [payload.artists, payload.sets, type]);

  const flatResults = useMemo(
    () => visibleGroups.flatMap((group) => group.results),
    [visibleGroups],
  );

  const activeResult = flatResults[activeIndex] ?? flatResults[0] ?? null;

  const openSearch = ({ focusInput = false }: { focusInput?: boolean } = {}) => {
    setOpen(true);
    if (focusInput) {
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  };

  const closeSearch = () => {
    setOpen(false);
    setActiveIndex(0);
  };

  const navigateToResult = (result: SearchResult | null) => {
    if (!result) return;
    closeSearch();
    router.push(result.href);
  };

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey && !isTypingTarget(event.target)) {
        event.preventDefault();
        openSearch({ focusInput: true });
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }

    const controller = new AbortController();

    if (trimmedQuery.length < 2) {
      setPayload({ ...EMPTY_PAYLOAD, scope, type, query: trimmedQuery });
      setLoading(false);
      return () => controller.abort();
    }

    setLoading(true);
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({
        q: trimmedQuery,
        scope,
        type,
      });

      fetch(`/api/archive/search?${params.toString()}`, {
        cache: "no-store",
        signal: controller.signal,
      })
        .then((response) => response.json() as Promise<SearchPayload>)
        .then((nextPayload) => {
          setPayload(nextPayload);
          setActiveIndex(0);
        })
        .catch((error: Error) => {
          if (error.name !== "AbortError") {
            setPayload({ ...EMPTY_PAYLOAD, scope, type, query: trimmedQuery });
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) {
            setLoading(false);
          }
        });
    }, 160);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [open, scope, trimmedQuery, type]);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeSearch();
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => Math.min(index + 1, Math.max(0, flatResults.length - 1)));
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => Math.max(0, index - 1));
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      navigateToResult(activeResult);
    }
  };

  return (
    <>
      <button
        aria-expanded={open}
        aria-label="Search artists and sets"
        className={`${styles.trigger} ${open ? styles.open : ""}`}
        onClick={() => {
          if (open) {
            closeSearch();
            return;
          }

          openSearch();
        }}
        title="Search"
        type="button"
      >
        <span aria-hidden="true" className={styles.searchIcon} />
      </button>

      {open ? (
        <div className={styles.overlay} onKeyDown={handleKeyDown} role="dialog" aria-modal="true">
          <button aria-label="Close search" className={styles.backdrop} onClick={closeSearch} type="button" />
          <div className={styles.panel}>
            <div className={styles.panelHeader}>
              <div className={styles.inputRow}>
                <span aria-hidden="true" className={styles.searchIcon} />
                <span className={styles.inputShell}>
                  <input
                    aria-label="Search artists and sets"
                    className={styles.input}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="artist or set"
                    ref={inputRef}
                    type="search"
                    value={query}
                  />
                </span>
                <span className={styles.scopePill}>{scope === "mine" ? "My Workspace" : "Global"}</span>
              </div>
            </div>

            <div className={styles.toolbar}>
              <div className={styles.typeToggle} aria-label="Search result type">
                {TYPE_OPTIONS.map((option) => (
                  <button
                    className={`${styles.typeOption} ${type === option.value ? styles.typeOptionActive : ""}`}
                    key={option.value}
                    onClick={() => {
                      setType(option.value);
                      setActiveIndex(0);
                    }}
                    type="button"
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <div className={styles.toolbarHint}>
                {scope === "mine" ? "Only workspace items" : "Archive-wide artist and set matches"}
              </div>
            </div>

            <div className={styles.resultsGrid}>
              <div className={styles.resultsPane}>
                {payload.authRequired ? (
                  <div className={styles.empty}>Sign in to search My Workspace.</div>
                ) : trimmedQuery.length < 2 ? (
                  null
                ) : loading && flatResults.length === 0 ? (
                  <div className={styles.empty}>Searching...</div>
                ) : flatResults.length === 0 ? (
                  <div className={styles.empty}>No artists or sets match this search.</div>
                ) : (
                  visibleGroups.map((group) =>
                    group.results.length > 0 ? (
                      <div className={styles.group} key={group.label}>
                        <div className={styles.groupLabel}>{group.label}</div>
                        {group.results.map((result) => {
                          const resultIndex = flatResults.findIndex((item) => item.id === result.id && item.kind === result.kind);
                          const active = resultIndex === activeIndex;
                          return (
                            <button
                              className={`${styles.resultRow} ${active ? styles.resultRowActive : ""}`}
                              key={`${result.kind}:${result.id}`}
                              onClick={() => navigateToResult(result)}
                              onMouseEnter={() => setActiveIndex(resultIndex)}
                              type="button"
                            >
                              <span className={styles.thumb}>
                                {result.imageUrl ? <img alt="" src={result.imageUrl} /> : null}
                              </span>
                              <span className={styles.resultCopy}>
                                <span className={styles.resultName}>{result.name}</span>
                                <span className={styles.resultMeta}>{result.meta}</span>
                              </span>
                              <span className={styles.resultKind}>{result.kind}</span>
                            </button>
                          );
                        })}
                      </div>
                    ) : null,
                  )
                )}
              </div>

              <aside className={styles.previewPane}>
                {activeResult ? (
                  <>
                    <div className={styles.previewArt}>
                      {activeResult.imageUrl ? <img alt="" src={activeResult.imageUrl} /> : null}
                      <div className={styles.previewTitle}>{activeResult.name}</div>
                    </div>
                    <div className={styles.previewMeta}>{activeResult.meta}</div>
                    <button className={styles.previewAction} onClick={() => navigateToResult(activeResult)} type="button">
                      Open {activeResult.kind}
                    </button>
                    {activeResult.kind === "artist" ? (
                      <button
                        className={styles.previewAction}
                        onClick={() => {
                          closeSearch();
                          router.push(`${activeResult.href}?q=${encodeURIComponent(trimmedQuery)}`);
                        }}
                        type="button"
                      >
                        Search within artist
                      </button>
                    ) : null}
                  </>
                ) : (
                  <div className={styles.previewEmpty}>Results preview appears here.</div>
                )}
              </aside>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

"use client";

import { useId, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";

import { ArtistAliasFields } from "@/components/forms/artist-alias-fields";
import { ArtistNameField } from "@/components/forms/artist-name-field";

import styles from "./inline-submit-button.module.css";

type InlineSubmitMode = "scan-artist" | "add-sets";

type InlineSubmitButtonProps = {
  /** Server-derived Preview-only capability; defaults off. */
  allowDiscoveryMaxSets?: boolean;
  mode: InlineSubmitMode;
  /** Pre-filled artist name for add-sets mode */
  artistName?: string;
  label?: string;
};

type SubmitState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "error"; message: string };

async function postSubmission(body: Record<string, string | string[]>): Promise<{ submissionId: string }> {
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { error?: string }).error ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<{ submissionId: string }>;
}

const LABEL: Record<InlineSubmitMode, string> = {
  "scan-artist": "+ submit artist",
  "add-sets": "+ add sets",
};

const TITLE: Record<InlineSubmitMode, string> = {
  "scan-artist": "Choose an artist submission mode",
  "add-sets": "Add sets",
};

export function InlineSubmitButton({ allowDiscoveryMaxSets = false, mode, artistName, label }: InlineSubmitButtonProps) {
  const { data: session } = useSession();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const [discoveryName, setDiscoveryName] = useState("");
  const [discoveryAliases, setDiscoveryAliases] = useState<string[]>([]);
  const [discoveryMaxSets, setDiscoveryMaxSets] = useState("");
  const [curatedName, setCuratedName] = useState("");
  const [urls, setUrls] = useState("");
  const [state, setState] = useState<SubmitState>({ status: "idle" });
  const curatedUrlsRef = useRef<HTMLTextAreaElement | null>(null);
  const discoveryMaxSetsRef = useRef<HTMLInputElement | null>(null);
  const discoveryMaxSetsId = useId();

  const isAuthenticated = Boolean(session?.user);

  const handleSubmit = async (payload: Record<string, string | string[]>) => {
    setState({ status: "submitting" });
    try {
      const { submissionId } = await postSubmission(payload);
      setOpen(false);
      router.push(`/submissions/${submissionId}`);
    } catch (err) {
      setState({ status: "error", message: (err as Error).message });
    }
  };

  const isSubmitting = state.status === "submitting";
  const maximumSets = discoveryMaxSets.trim();
  const hasValidMaximumSets = !allowDiscoveryMaxSets || maximumSets === "" || (
    Number.isSafeInteger(Number(maximumSets)) && Number(maximumSets) > 0
  );

  const handleDiscoverySubmit = async () => {
    // Native number inputs can report badInput while their value is empty.
    // Never interpret an unfinished numeric entry as an uncapped submission.
    if (allowDiscoveryMaxSets && (!discoveryMaxSetsRef.current?.reportValidity() || !hasValidMaximumSets)) return;
    await handleSubmit({
      mode: "artist",
      artistName: discoveryName,
      artistAliases: discoveryAliases,
      ...(allowDiscoveryMaxSets && maximumSets ? { maxSetsOverride: maximumSets } : {}),
    });
  };

  const routeDiscoveryToCurated = (artistName: string) => {
    setCuratedName(artistName);

    requestAnimationFrame(() => {
      curatedUrlsRef.current?.focus();
      curatedUrlsRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  };

  const triggerLabel = label ?? LABEL[mode];

  return (
    <div className={styles.wrap}>
      <div style={{ position: "relative", display: "inline-block" }}>
        <button
          className={`${styles.trigger} ${!isAuthenticated ? styles.disabled : ""}`}
          onClick={() => { if (isAuthenticated) setOpen((v) => !v); }}
          onMouseEnter={() => !isAuthenticated && setTooltipVisible(true)}
          onMouseLeave={() => setTooltipVisible(false)}
          type="button"
        >
          {triggerLabel}
        </button>
        {tooltipVisible && !isAuthenticated && (
          <div className={styles.tooltip}>You must log in to submit work</div>
        )}

      {open && (
        <div className={styles.panel}>
          <div className={styles.panelTitle}>{TITLE[mode]}</div>

          {/* Artist Discovery + Curated Artist */}
          {mode === "scan-artist" && (
            <div className={styles.modes}>
              <div className={styles.modeCard}>
                <span className={styles.modeTitle}>Artist Discovery</span>
                <span className={styles.modeDesc}>
                  Enter a name — auto-finds all their sets on YouTube &amp; SoundCloud
                </span>
                <ArtistNameField
                  className={styles.artistFieldTheme}
                  existingArtistHelperText={'If the artist you are looking for has already been submitted, use "Curated Artist" mode to add new sets to their existing page.'}
                  inputClassName={styles.input}
                  onSuggestionSelect={(artist) => routeDiscoveryToCurated(artist.name)}
                  onValueChange={setDiscoveryName}
                  placeholder="e.g. Floating Points"
                  value={discoveryName}
                />
                <ArtistAliasFields
                  className={styles.artistAliasTheme}
                  inputClassName={styles.input}
                  onChange={setDiscoveryAliases}
                  values={discoveryAliases}
                />
                {allowDiscoveryMaxSets ? (
                  <>
                    <label className={styles.fieldLabel} htmlFor={discoveryMaxSetsId}>
                      Maximum sets (optional)
                    </label>
                    <input
                      aria-describedby={`${discoveryMaxSetsId}-hint${hasValidMaximumSets ? "" : ` ${discoveryMaxSetsId}-error`}`}
                      aria-invalid={!hasValidMaximumSets}
                      className={styles.input}
                      id={discoveryMaxSetsId}
                      min={1}
                      name="maxSetsOverride"
                      onChange={(event) => setDiscoveryMaxSets(event.target.value)}
                      placeholder="Default"
                      ref={discoveryMaxSetsRef}
                      step={1}
                      type="number"
                      value={discoveryMaxSets}
                    />
                    <span className={styles.modeDesc} id={`${discoveryMaxSetsId}-hint`}>
                      Leave blank to use the default. Limits set count, not duration.
                    </span>
                    {!hasValidMaximumSets && (
                      <span className={styles.error} id={`${discoveryMaxSetsId}-error`} role="alert">
                        Enter a whole number greater than zero.
                      </span>
                    )}
                  </>
                ) : null}
                <div className={styles.btnRow}>
                  <button
                    className={styles.submitBtn}
                    disabled={!discoveryName.trim() || isSubmitting || !hasValidMaximumSets}
                    onClick={handleDiscoverySubmit}
                    type="button"
                  >
                    {isSubmitting ? "…" : "Start Scan"}
                  </button>
                  <button className={styles.cancelBtn} onClick={() => setOpen(false)} type="button">
                    Cancel
                  </button>
                </div>
              </div>
              <div className={styles.modeCard}>
                <span className={styles.modeTitle}>Curated Artist</span>
                <span className={styles.modeDesc}>Paste hand-picked URLs for a named artist and reuse an existing page when it already exists</span>
                <ArtistNameField
                  className={styles.artistFieldTheme}
                  existingArtistHelperText="Select an existing artist to add additional sets to their existing page"
                  inputClassName={styles.input}
                  onValueChange={setCuratedName}
                  placeholder="Artist name"
                  value={curatedName}
                />
                <textarea
                  className={styles.textarea}
                  ref={curatedUrlsRef}
                  placeholder="Paste URLs, one per line"
                  value={urls}
                  onChange={(e) => setUrls(e.target.value)}
                />
                <div className={styles.btnRow}>
                  <button
                    className={styles.submitBtn}
                    disabled={!curatedName.trim() || !urls.trim() || isSubmitting}
                    onClick={() =>
                      handleSubmit({ mode: "curated_artist", artistName: curatedName, sourceUrls: urls })
                    }
                    type="button"
                  >
                    {isSubmitting ? "…" : "Submit"}
                  </button>
                  <button className={styles.cancelBtn} onClick={() => setOpen(false)} type="button">
                    Cancel
                  </button>
                </div>
              </div>
              {state.status === "error" && <div className={styles.error}>{state.message}</div>}
            </div>
          )}

          {/* Add Sets — curated batch with pre-filled artist */}
          {mode === "add-sets" && (
            <div className={styles.modesOne}>
              <input
                readOnly
                className={styles.inputPrefilled}
                value={artistName ?? ""}
              />
              <textarea
                className={styles.textarea}
                placeholder="Paste URLs, one per line — add one or as many as you like"
                value={urls}
                onChange={(e) => setUrls(e.target.value)}
              />
              <div className={styles.btnRow}>
                <button
                  className={styles.submitBtn}
                  disabled={!urls.trim() || isSubmitting}
                  onClick={() =>
                    handleSubmit({
                      mode: "curated_artist",
                      artistName: artistName ?? "",
                      sourceUrls: urls,
                    })
                  }
                  type="button"
                >
                  {isSubmitting ? "…" : "Submit"}
                </button>
                <button className={styles.cancelBtn} onClick={() => setOpen(false)} type="button">
                  Cancel
                </button>
              </div>
              {state.status === "error" && <div className={styles.error}>{state.message}</div>}
            </div>
          )}
        </div>
      )}
      </div>
    </div>
  );
}

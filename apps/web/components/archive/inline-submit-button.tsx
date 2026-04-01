"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";

import styles from "./inline-submit-button.module.css";

type InlineSubmitMode = "scan-artist" | "submit-set" | "add-sets";

type InlineSubmitButtonProps = {
  mode: InlineSubmitMode;
  /** Pre-filled artist name for add-sets mode */
  artistName?: string;
};

type SubmitState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "error"; message: string };

async function postSubmission(body: Record<string, string>): Promise<{ submissionId: string }> {
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
  "scan-artist": "+ scan new artist",
  "submit-set": "+ scan new set",
  "add-sets": "+ scan new set",
};

const TITLE: Record<InlineSubmitMode, string> = {
  "scan-artist": "How would you like to scan this artist?",
  "submit-set": "Paste a YouTube or SoundCloud URL",
  "add-sets": "Add sets",
};

export function InlineSubmitButton({ mode, artistName }: InlineSubmitButtonProps) {
  const { data: session } = useSession();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const [discoveryName, setDiscoveryName] = useState("");
  const [curatedName, setCuratedName] = useState("");
  const [urls, setUrls] = useState("");
  const [singleUrl, setSingleUrl] = useState("");
  const [state, setState] = useState<SubmitState>({ status: "idle" });

  const isAuthenticated = Boolean(session?.user);

  const handleSubmit = async (payload: Record<string, string>) => {
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
          {LABEL[mode]}
        </button>
        {tooltipVisible && !isAuthenticated && (
          <div className={styles.tooltip}>You must log in to submit work</div>
        )}

      {open && (
        <div className={styles.panel}>
          <div className={styles.panelTitle}>{TITLE[mode]}</div>

          {/* Single Set URL */}
          {mode === "submit-set" && (
            <div className={styles.modesOne}>
              <div className={styles.singleRow}>
                <input
                  className={styles.singleInput}
                  placeholder="https://www.youtube.com/watch?v=…"
                  value={singleUrl}
                  onChange={(e) => setSingleUrl(e.target.value)}
                />
                <button
                  className={styles.submitBtn}
                  disabled={!singleUrl.trim() || isSubmitting}
                  onClick={() => handleSubmit({ mode: "url", sourceUrl: singleUrl })}
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

          {/* Artist Discovery + Curated Artist */}
          {mode === "scan-artist" && (
            <div className={styles.modes}>
              <div className={styles.modeCard}>
                <span className={styles.modeTitle}>Artist Discovery</span>
                <span className={styles.modeDesc}>
                  Enter a name — auto-finds all their sets on YouTube &amp; SoundCloud
                </span>
                <input
                  className={styles.input}
                  placeholder="e.g. Floating Points"
                  value={discoveryName}
                  onChange={(e) => setDiscoveryName(e.target.value)}
                />
                <div className={styles.btnRow}>
                  <button
                    className={styles.submitBtn}
                    disabled={!discoveryName.trim() || isSubmitting}
                    onClick={() => handleSubmit({ mode: "artist", artistName: discoveryName })}
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
                <span className={styles.modeDesc}>Paste hand-picked URLs for a named artist</span>
                <input
                  className={styles.input}
                  placeholder="Artist name"
                  value={curatedName}
                  onChange={(e) => setCuratedName(e.target.value)}
                />
                <textarea
                  className={styles.textarea}
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

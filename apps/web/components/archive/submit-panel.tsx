"use client";

import { type RefObject, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";

import { ArtistNameField } from "@/components/forms/artist-name-field";

import styles from "./submit-panel.module.css";

type SubmitState = { status: "idle" } | { status: "submitting" } | { status: "error"; message: string };

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

function ArtistForm({
  onClose,
  onExistingArtistSelect,
}: {
  onClose: () => void;
  onExistingArtistSelect: (artistName: string) => void;
}) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [state, setState] = useState<SubmitState>({ status: "idle" });

  const handleSubmit = async () => {
    setState({ status: "submitting" });
    try {
      const { submissionId } = await postSubmission({ mode: "artist", artistName: name });
      onClose();
      router.push(`/submissions/${submissionId}`);
    } catch (err) {
      setState({ status: "error", message: (err as Error).message });
    }
  };

  return (
    <>
      <ArtistNameField
        className={styles.artistFieldTheme}
        existingArtistHelperText={'If the artist you are looking for has already been submitted, use "Curated Artist" mode to add new sets to their existing page.'}
        inputClassName={styles.input}
        onSuggestionSelect={(artist) => onExistingArtistSelect(artist.name)}
        onValueChange={setName}
        placeholder="e.g. Floating Points"
        value={name}
      />
      <div className={styles.btnRow}>
        <button
          className={styles.submitBtn}
          disabled={!name.trim() || state.status === "submitting"}
          onClick={handleSubmit}
          type="button"
        >
          {state.status === "submitting" ? "Submitting…" : "Start Scan"}
        </button>
        <button className={styles.cancelBtn} onClick={onClose} type="button">
          Cancel
        </button>
      </div>
      {state.status === "error" && <div className={styles.error}>{state.message}</div>}
    </>
  );
}

function CuratedForm({
  artistName,
  onArtistNameChange,
  onClose,
  textareaRef,
}: {
  artistName?: string;
  onArtistNameChange?: (value: string) => void;
  onClose: () => void;
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
}) {
  const router = useRouter();
  const [internalName, setInternalName] = useState("");
  const [urls, setUrls] = useState("");
  const [state, setState] = useState<SubmitState>({ status: "idle" });
  const name = artistName ?? internalName;
  const setName = onArtistNameChange ?? setInternalName;

  const handleSubmit = async () => {
    setState({ status: "submitting" });
    try {
      const { submissionId } = await postSubmission({
        mode: "curated_artist",
        artistName: name,
        sourceUrls: urls,
      });
      onClose();
      router.push(`/submissions/${submissionId}`);
    } catch (err) {
      setState({ status: "error", message: (err as Error).message });
    }
  };

  return (
    <>
      <ArtistNameField
        className={styles.artistFieldTheme}
        existingArtistHelperText="Select an existing artist to add additional sets to their existing page"
        inputClassName={styles.input}
        onValueChange={setName}
        placeholder="Artist name"
        value={name}
      />
      <textarea
        className={styles.textarea}
        ref={textareaRef}
        placeholder="Paste URLs, one per line"
        value={urls}
        onChange={(e) => setUrls(e.target.value)}
      />
      <div className={styles.btnRow}>
        <button
          className={styles.submitBtn}
          disabled={!name.trim() || !urls.trim() || state.status === "submitting"}
          onClick={handleSubmit}
          type="button"
        >
          {state.status === "submitting" ? "Submitting…" : "Submit"}
        </button>
        <button className={styles.cancelBtn} onClick={onClose} type="button">
          Cancel
        </button>
      </div>
      {state.status === "error" && <div className={styles.error}>{state.message}</div>}
    </>
  );
}

export function SubmitPanel() {
  const { data: session } = useSession();
  const [open, setOpen] = useState(false);
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const [curatedName, setCuratedName] = useState("");
  const curatedUrlsRef = useRef<HTMLTextAreaElement | null>(null);

  const isAuthenticated = Boolean(session?.user);

  const routeDiscoveryToCurated = (artistName: string) => {
    setCuratedName(artistName);

    requestAnimationFrame(() => {
      curatedUrlsRef.current?.focus();
      curatedUrlsRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  };

  return (
    <>
      <div style={{ position: "relative" }}>
        <button
          className={`${styles.trigger} ${open ? styles.open : ""} ${!isAuthenticated ? styles.disabled : ""}`}
          onClick={() => { if (isAuthenticated) setOpen((v) => !v); }}
          onMouseEnter={() => !isAuthenticated && setTooltipVisible(true)}
          onMouseLeave={() => setTooltipVisible(false)}
          type="button"
        >
          {`+ Submit ${!isAuthenticated || !open ? "▾" : "▴"}`}
        </button>
        {tooltipVisible && !isAuthenticated && (
          <div className={styles.tooltip}>You must log in to submit work</div>
        )}
      </div>

      {open && isAuthenticated && (
        <>
          <div className={styles.overlay} onClick={() => setOpen(false)} />
          <div className={styles.panel}>
            <div className={styles.panelTitle}>Choose an artist submission mode</div>
            <div className={styles.modes}>
              <div className={styles.mode}>
                <span className={styles.modeTitle}>Artist Discovery</span>
                <span className={styles.modeDesc}>Enter a DJ name — auto-finds all their recorded sets</span>
                <ArtistForm
                  onClose={() => setOpen(false)}
                  onExistingArtistSelect={routeDiscoveryToCurated}
                />
              </div>
              <div className={styles.mode}>
                <span className={styles.modeTitle}>Curated Artist</span>
                <span className={styles.modeDesc}>Hand-pick URLs for a named artist and reuse an existing page when it already exists</span>
                <CuratedForm
                  artistName={curatedName}
                  onArtistNameChange={setCuratedName}
                  onClose={() => setOpen(false)}
                  textareaRef={curatedUrlsRef}
                />
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
